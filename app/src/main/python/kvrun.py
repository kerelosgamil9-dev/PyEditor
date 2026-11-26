"""Runs a script on the REAL Kivy (Kivy 2.3.1 on SDL2 + OpenGL ES).
Called from KivyActivity.runPython() on the SDL thread (the thread SDL_main() runs on)."""
import os, sys, io, json, types, traceback
import importlib.abc, importlib.machinery, importlib.util

_ACT = None          # the KivyActivity (Kotlin) - used for the live output panel


class _NativeFinder(importlib.abc.MetaPathFinder):
    """Kivy's native modules ship as lib*.so files in the app's lib folder (Android only unpacks lib*.so),
    so 'import kivy.graphics.texture' is pointed at libkvx_kivy_graphics_texture.so"""

    def __init__(self, libdir, mods):
        self.libdir = libdir
        self.mods = mods

    def find_spec(self, fullname, path=None, target=None):
        so = self.mods.get(fullname)
        if so is None:
            return None
        p = os.path.join(self.libdir, so)
        if not os.path.exists(p):
            return None
        loader = importlib.machinery.ExtensionFileLoader(fullname, p)
        return importlib.util.spec_from_file_location(fullname, p, loader=loader)


# Kivy's own Android audio provider needs pyjnius (python-for-android). This one does the same job with Chaquopy:
# android.media.MediaPlayer plays mp3 / ogg / wav / flac / m4a ... (no extra native library needed).
_AUDIO_SRC = r'''
__all__ = ("SoundAndroidPlayer",)

from java import jclass, dynamic_proxy
from kivy.clock import mainthread
from kivy.core.audio import Sound, SoundLoader
from kivy.logger import Logger

MediaPlayer = jclass("android.media.MediaPlayer")
AudioManager = jclass("android.media.AudioManager")
AudioAttributesBuilder = jclass("android.media.AudioAttributes$Builder")
_CompletionListener = jclass("android.media.MediaPlayer$OnCompletionListener")


class _Done(dynamic_proxy(_CompletionListener)):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def onCompletion(self, mp):
        self.callback()


class SoundAndroidPlayer(Sound):
    @staticmethod
    def extensions():
        return ("mp3", "aac", "3gp", "flac", "wav", "ogg", "m4a", "mid", "mp4")

    def __init__(self, **kwargs):
        self._mp = None
        self._done = None
        super().__init__(**kwargs)

    def load(self):
        self.unload()
        try:
            mp = MediaPlayer()
            mp.setAudioAttributes(
                AudioAttributesBuilder().setLegacyStreamType(AudioManager.STREAM_MUSIC).build())
            mp.setDataSource(str(self.source))
            self._done = _Done(self._completed)
            mp.setOnCompletionListener(self._done)
            mp.setLooping(bool(self.loop))
            v = float(self.volume)
            mp.setVolume(v, v)
            mp.prepare()
            self._mp = mp
        except Exception as e:
            Logger.warning("Audio: cannot load %s: %s" % (self.source, e))
            self._mp = None

    def unload(self):
        mp, self._mp = self._mp, None
        if mp is not None:
            try:
                mp.release()
            except Exception:
                pass

    def play(self):
        mp = self._mp
        if mp is None:
            return
        try:
            if mp.isPlaying():
                mp.seekTo(0)          # played again while still playing: start over
            else:
                mp.start()
        except Exception as e:
            Logger.warning("Audio: play failed: %s" % e)
            return
        super().play()

    def stop(self):
        mp = self._mp
        if mp is None:
            return
        try:
            mp.stop()
            mp.prepare()
        except Exception:
            pass
        super().stop()

    def seek(self, position):
        if self._mp is not None:
            try:
                self._mp.seekTo(int(float(position) * 1000))
            except Exception:
                pass

    def get_pos(self):
        if self._mp is not None:
            try:
                return self._mp.getCurrentPosition() / 1000.
            except Exception:
                pass
        return 0

    def _get_length(self):
        if self._mp is not None:
            try:
                return self._mp.getDuration() / 1000.
            except Exception:
                pass
        return 0

    def on_volume(self, instance, volume):
        if self._mp is not None:
            v = float(volume)
            self._mp.setVolume(v, v)

    def on_loop(self, instance, loop):
        if self._mp is not None:
            self._mp.setLooping(bool(loop))

    @mainthread
    def _completed(self):
        super().stop()


SoundLoader.register(SoundAndroidPlayer)
'''


class _SrcLoader(importlib.abc.Loader):
    def __init__(self, src, path):
        self.src = src
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.src, self.path, "exec"), module.__dict__)


class _AudioFinder(importlib.abc.MetaPathFinder):
    """Kivy 2.3 only allows the audio providers gstplayer / pygame / ffpyplayer / sdl2 / avplayer. We answer to the name
    'sdl2' (its module 'audio_sdl2' needs SDL2_mixer, which is not built), and also to Kivy's 'audio_android' name,
    with the Chaquopy version above."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("kivy.core.audio.audio_sdl2", "kivy.core.audio.audio_android"):
            return importlib.util.spec_from_loader(fullname, _SrcLoader(_AUDIO_SRC, "<pyvora audio_android>"))
        return None


def _android_stub(act):
    """Kivy (when it knows it runs on Android) imports python-for-android's 'android' module here and there.
    This stand-in accepts every call and does nothing, so those code paths simply pass."""
    m = types.ModuleType("android")
    m.mActivity = act
    m.activity = act

    def _noop(*a, **k):
        return None

    def _kb_height(*a, **k):
        try:
            return int(act.kbHeight())
        except Exception:
            return 0

    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "get_keyboard_height":      # Kivy does arithmetic with this one
            return _kb_height
        return _noop

    m.__getattr__ = __getattr__
    return m


class _Out:
    """stdout / stderr: goes to the live output panel of KivyActivity and to a file (shown if the script fails)"""
    encoding = "utf-8"
    errors = "strict"

    def __init__(self, f):
        self.f = f

    def write(self, s):
        s = str(s)
        self.f.write(s)
        self.f.flush()
        if _ACT is not None:
            try:
                _ACT.appendOut(s)
            except Exception:
                pass
        return len(s)

    def flush(self):
        self.f.flush()

    def isatty(self):
        return False


def _setup_text(fonts):
    """Arabic on Kivy (its text provider here is Pillow, which can neither join Arabic letters nor reorder them):
    1) the default font becomes Cairo (Latin + Arabic) from assets/tkfonts, the same fonts real tkinter uses
    2) every Label / Button / TextInput line goes through arabic_tk.shape() (joined letters + display order)
    PYVORA_KV_ARABIC=0 switches both off (plain Kivy / Roboto)."""
    if os.environ.get("PYVORA_KV_ARABIC", "1") == "0":
        return
    import re
    import arabic_tk
    from kivy.core.text import LabelBase, DEFAULT_FONT
    from kivy.core.text.markup import MarkupLabel

    reg = os.path.join(fonts, "Cairo-Regular.ttf")
    bold = os.path.join(fonts, "Cairo-Bold.ttf")
    if os.path.exists(reg):
        if not os.path.exists(bold):
            bold = reg
        LabelBase.register(DEFAULT_FONT, fn_regular=reg, fn_italic=reg, fn_bold=bold, fn_bolditalic=bold)

    tag = re.compile(r"(\[/?[A-Za-z]+(?:=[^\]]*)?\]|&bl;|&br;|&amp;)")

    def _get_text(self):
        t = self._text
        if not isinstance(t, str) or not arabic_tk.has_rtl(t):
            return t
        try:
            if isinstance(self, MarkupLabel):
                # keep [b] [color=..] ... tags as they are, shape only the words between them
                parts = tag.split(t)
                return "".join(p if i % 2 else arabic_tk.shape(p) for i, p in enumerate(parts))
            ts = getattr(self, "_text_size", None)
            uw = ts[0] if ts else None
            if uw and uw > 8:
                try:
                    # wrap on the logical text, then shape every line (so long Arabic text keeps its reading order)
                    return arabic_tk.wrap_lines(t, int(uw * 0.97), lambda s: self.get_extents(s)[0])
                except Exception:
                    pass
            return arabic_tk.shape(t)
        except Exception:
            return t

    prop = property(_get_text, LabelBase._set_text, doc="Get/Set the text (Arabic shaped on the way out)")
    LabelBase.text = prop
    LabelBase.label = prop


_KB = {"h": 0, "patched": False}


def ime_changed(height):
    """Called by KivyActivity (on Android's UI thread) when the on-screen keyboard opens, changes or closes.
    height = pixels covered by the keyboard (0 = closed).
    Kivy 2.3 reports keyboard_height = 0 on Android+SDL2, so Window.softinput_mode never worked there: we feed the real
    height in. If the app did not choose a mode itself, 'below_target' is used (content moves up just enough to keep
    the focused TextInput above the keyboard)."""
    h = int(height)
    prev = _KB["h"]
    _KB["h"] = h
    try:
        from kivy.clock import Clock

        def _apply(dt):
            try:
                from kivy.core.window import Window, WindowBase
                if not _KB["patched"]:
                    WindowBase._get_android_kheight = lambda self: _KB["h"]
                    _KB["patched"] = True
                if h > 0 and Window.softinput_mode == "":
                    Window.softinput_mode = "below_target"
                Window.trigger_keyboard_height()
                if h == 0 and prev > 0:
                    Window.release_all_keyboards()   # closed with its own button: let the TextInput lose focus
            except Exception:
                pass

        Clock.schedule_once(_apply, 0)
    except Exception:
        pass


def ime_hidden():
    """Called by KivyActivity (on Android's UI thread) when the on-screen keyboard was closed.
    Kivy is not told about that by Android, so the TextInput would stay 'focused' and a new tap would not open the
    keyboard again.  Let go of the keyboard on Kivy's own thread."""
    try:
        from kivy.clock import Clock

        def _release(dt):
            try:
                from kivy.core.window import Window
                Window.release_all_keyboards()
            except Exception:
                pass

        Clock.schedule_once(_release, 0)
    except Exception:
        pass


def main(codepath, name, wd, pub, libdir, rt, fonts, outfile, act=None):
    global _ACT
    _ACT = act
    out = open(outfile, "a", encoding="utf-8")
    sys.stdout = _Out(out)
    sys.stderr = _Out(out)
    sys.stdin = io.StringIO("")
    sys.argv = [name]

    # libraries the user installed with pip (same folder the normal console uses)
    try:
        import runner
        runner._site(wd)
    except Exception:
        pass

    rc = 0
    try:
        # 1) where Kivy's python files and native modules are
        with open(os.path.join(rt, "kivy_ext.json"), "r", encoding="utf-8") as f:
            mods = json.load(f)
        sys.meta_path.insert(0, _NativeFinder(libdir, mods))
        sys.meta_path.insert(0, _AudioFinder())
        if rt not in sys.path:
            sys.path.insert(0, rt)
        sys.modules["android"] = _android_stub(act)

        # 2) Kivy settings (must be set before 'import kivy')
        env = os.environ
        env["KIVY_BUILD"] = "android"
        env["ANDROID_ARGUMENT"] = pub
        env["KIVY_HOME"] = os.path.join(wd, ".kivy")
        env["KIVY_NO_ARGS"] = "1"
        env["KIVY_NO_FILELOG"] = "1"
        env["KIVY_WINDOW"] = "sdl2"
        env["KIVY_GL_BACKEND"] = "sdl2"
        env["KIVY_TEXT"] = "pil"
        env["KIVY_IMAGE"] = "pil"
        env["PYVORA_DIR"] = pub
        env["PYVORA_KV_FONTS"] = fonts
        env.setdefault("HOME", wd)
        # screen metrics from Android itself (Kivy would ask python-for-android's "jnius" for them)
        try:
            res = act.getResources()
            dm = res.getDisplayMetrics()
            env.setdefault("KIVY_DPI", str(float(dm.densityDpi)))
            env.setdefault("KIVY_METRICS_DENSITY", str(float(dm.density)))
            env.setdefault("KIVY_METRICS_FONTSCALE", str(float(res.getConfiguration().fontScale)))
        except Exception:
            env.setdefault("KIVY_DPI", "320")
            env.setdefault("KIVY_METRICS_DENSITY", "2")
            env.setdefault("KIVY_METRICS_FONTSCALE", "1")
        try:
            # the icon folder is made here, so Kivy skips copying its logo files (that copy failed with "Permission denied")
            os.makedirs(os.path.join(env["KIVY_HOME"], "icon"), exist_ok=True)
        except Exception:
            pass
        try:
            os.chdir(pub)
        except Exception:
            pass
        if pub not in sys.path:
            sys.path.insert(0, pub)

        try:
            import PIL  # noqa: F401
        except Exception:
            print("[PYVORA] Pillow is missing: Kivy needs it to draw text and images")

        from kivy.config import Config
        Config.set("graphics", "fullscreen", "auto")
        Config.set("kivy", "exit_on_escape", "0")
        try:
            _setup_text(fonts)
        except Exception:
            traceback.print_exc()

        # 3) run the user's script
        with open(codepath, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            os.remove(codepath)
        except OSError:
            pass
        # a real __main__ module with a __file__: Kivy (inspect.getfile) needs it to find the app's folder / .kv file
        main_mod = types.ModuleType("__main__")
        main_mod.__file__ = os.path.join(pub, name)
        main_mod.__builtins__ = __builtins__
        sys.modules["__main__"] = main_mod
        exec(compile(src, name, "exec"), main_mod.__dict__)
    except SystemExit:
        rc = 0
    except BaseException:
        rc = 1
        et, ev, tb = sys.exc_info()
        traceback.print_exception(et, ev, tb.tb_next if tb is not None and tb.tb_next is not None else tb)
    finally:
        try:
            out.flush()
        except Exception:
            pass
    return rc
