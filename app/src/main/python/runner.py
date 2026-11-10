import sys, io, os, traceback, contextlib

def _site(workdir):
    d = os.path.join(workdir, "site-packages")
    os.makedirs(d, exist_ok=True)
    if d not in sys.path:
        sys.path.insert(0, d)
    return d

class _NoStdin:
    def readline(self, *a):
        raise EOFError("input() not supported yet / input() مش مدعومة لسه")
    read = readline

def run(code, name, workdir):
    _site(workdir)
    os.chdir(workdir)
    buf = io.StringIO()
    old_in = sys.stdin
    sys.stdin = _NoStdin()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                exec(compile(code, name, "exec"), {"__name__": "__main__", "__file__": name})
            except SystemExit:
                pass
            except BaseException:
                tb = traceback.format_exc().splitlines()
                buf.write("\n".join(tb[:1] + tb[3:]) + "\n")
    finally:
        sys.stdin = old_in
    return buf.getvalue()

def pip(args, workdir):
    d = _site(workdir)
    buf = io.StringIO()
    parts = args.split()
    if parts and parts[0] == "pip":
        parts = parts[1:]
    try:
        if parts and parts[0] == "list":
            return "\n".join(sorted(os.listdir(d))) or "(empty)"
        if parts and parts[0] == "install":
            parts = ["install", "--target", d, "--upgrade", "--no-warn-script-location"] + parts[1:]
        else:
            return "usage: pip install <package> | pip list"
        from pip._internal.cli.main import main
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            main(parts)
    except SystemExit:
        pass
    except BaseException:
        buf.write(traceback.format_exc())
    return buf.getvalue()
