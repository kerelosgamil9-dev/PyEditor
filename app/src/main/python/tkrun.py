"""Runs a script on the REAL tkinter (Tcl/Tk 8.6 on SDL). Called from TkActivity.runPython() on the SDL thread."""
import os, sys, io, traceback
import importlib.machinery, importlib.util


def _load_tkinter(libdir):
    """the native _tkinter module ships as lib_tkinter_py.so (Android only unpacks lib*.so files)"""
    p = os.path.join(libdir, "lib_tkinter_py.so")
    loader = importlib.machinery.ExtensionFileLoader("_tkinter", p)
    spec = importlib.util.spec_from_file_location("_tkinter", p, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    sys.modules["_tkinter"] = mod
    return mod


def _patch_scaling(default=2.0):
    """The phone reports a very high DPI, which made Tk draw everything ~5x too big.
    Every Tk() now starts with a sane 'pixels per point' (scripts can still change it with root.tk.call('tk','scaling',x))."""
    import tkinter
    try:
        scale = float(os.environ.get("PYVORA_TK_SCALING", default))
    except ValueError:
        scale = default
    orig = tkinter.Tk.__init__

    def __init__(self, *a, **k):
        orig(self, *a, **k)
        try:
            self.tk.call("tk", "scaling", scale)
        except Exception:
            pass

    tkinter.Tk.__init__ = __init__


class _Out:
    encoding = "utf-8"
    errors = "strict"

    def __init__(self, f): self.f = f
    def write(self, s):
        s = str(s)
        self.f.write(s); self.f.flush()
        return len(s)
    def flush(self): self.f.flush()
    def isatty(self): return False


def main(codepath, name, wd, pub, libdir, tcl, tk, realpy, outfile):
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
        _patch_scaling()
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
