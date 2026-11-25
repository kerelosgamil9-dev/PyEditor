"""Runs a script on the REAL tkinter (Tcl/Tk 8.6 on SDL). Called from TkActivity.runPython() on the SDL thread."""
import os, sys, io, traceback
import importlib.machinery, importlib.util

_ACT = None          # the TkActivity (Kotlin) - used for live output and the on-screen keyboard


def _load_tkinter(libdir):
    """the native _tkinter module ships as lib_tkinter_py.so (Android only unpacks lib*.so files)"""
    p = os.path.join(libdir, "lib_tkinter_py.so")
    loader = importlib.machinery.ExtensionFileLoader("_tkinter", p)
    spec = importlib.util.spec_from_file_location("_tkinter", p, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    sys.modules["_tkinter"] = mod
    return mod


def _keyboard(root):
    """show the Android keyboard only while a text field has the focus, hide it when the field goes away"""
    import tkinter
    from tkinter import ttk
    texty = (tkinter.Entry, tkinter.Text, tkinter.Spinbox, ttk.Entry)   # ttk.Combobox / ttk.Spinbox are ttk.Entry

    def is_texty(w):
        try:
            return isinstance(w, texty) and str(w.cget("state")) not in ("disabled", "readonly")
        except Exception:
            return isinstance(w, texty)

    def on_focus(e):
        try:
            if is_texty(e.widget):
                _ACT.showKeyboard()
            else:
                _ACT.hideKeyboard()
        except Exception:
            pass

    def on_click(e):
        try:
            if is_texty(e.widget):
                _ACT.showKeyboard()
        except Exception:
            pass

    root.bind_all("<FocusIn>", on_focus, add="+")
    root.bind_all("<ButtonRelease-1>", on_click, add="+")


def _patch_tk(scale=2.0):
    """phone-friendly defaults for every Tk() window"""
    import tkinter
    try:
        scale = float(os.environ.get("PYVORA_TK_SCALING", scale))
    except ValueError:
        pass
    orig = tkinter.Tk.__init__

    def __init__(self, *a, **k):
        orig(self, *a, **k)
        # the phone reports a very high DPI, which made everything ~5x too big
        try:
            self.tk.call("tk", "scaling", scale)
        except Exception:
            pass
        # default widget fonts (also used by the built-in dialogs): big enough for a finger
        try:
            import tkinter.font as tkfont
            base = int(os.environ.get("PYVORA_TK_FONT", "14"))
            for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                      "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont", "TkFixedFont"):
                try:
                    tkfont.nametofont(n, root=self).configure(size=base)
                except Exception:
                    pass
        except Exception:
            pass
        # a phone has no desktop to float windows on: the main window fills the screen
        # (PYVORA_TK_FULLSCREEN=0 or root.attributes("-fullscreen", False) to undo)
        if os.environ.get("PYVORA_TK_FULLSCREEN", "1") != "0":
            try:
                self.attributes("-fullscreen", True)
            except Exception:
                pass
        if _ACT is not None:
            try:
                _keyboard(self)
            except Exception:
                pass

    tkinter.Tk.__init__ = __init__


class _Out:
    """stdout / stderr: goes to the live output panel of TkActivity and to a file (shown after the window closes)"""
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


def main(codepath, name, wd, pub, libdir, tcl, tk, realpy, outfile, act=None):
    global _ACT
    _ACT = act
    out = open(outfile, "a", encoding="utf-8")
    sys.stdout = _Out(out)
    sys.stderr = _Out(out)
    sys.stdin = io.StringIO("")

    # libraries the user installed with pip (same folder the normal console uses)
    try:
        import runner
        runner._site(wd)
    except Exception:
        pass
    if realpy not in sys.path:
        sys.path.insert(0, realpy)               # real tkinter package + real turtle.py
    os.environ["TCL_LIBRARY"] = tcl
    os.environ["TK_LIBRARY"] = tk
    os.environ["PYVORA_DIR"] = pub
    os.environ.setdefault("HOME", wd)
    try:
        os.chdir(pub)
    except Exception:
        pass
    if pub not in sys.path:
        sys.path.insert(0, pub)

    rc = 0
    try:
        with open(codepath, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            os.remove(codepath)
        except OSError:
            pass
        _load_tkinter(libdir)
        _patch_tk()
        try:
            import arabic_tk
            arabic_tk.install()
        except Exception:
            pass
        g = {"__name__": "__main__", "__file__": os.path.join(pub, name), "__builtins__": __builtins__}
        exec(compile(src, name, "exec"), g)
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
