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
