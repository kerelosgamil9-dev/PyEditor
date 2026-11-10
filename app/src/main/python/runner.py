import sys, os, re, shlex, shutil, traceback

HELP = """Commands / الأوامر:
  pip install <pkg>   pip uninstall <pkg>   pip list
  python file.py      python (REPL)
  ls  cd  pwd  cat  mkdir  rm  clear  exit"""

class _Out:
    encoding = "utf-8"; errors = "strict"
    def __init__(self, b): self.b = b
    def write(self, x):
        self.b.write(x); return len(x)
    def flush(self): pass
    def isatty(self): return False

class _In:
    encoding = "utf-8"
    def __init__(self, b): self.b = b
    def readline(self, *a): return self.b.readLine()
    def read(self, *a): return self.b.readLine()
    def close(self): pass
    def isatty(self): return False

def _site(wd):
    d = os.path.join(wd, "site-packages")
    os.makedirs(d, exist_ok=True)
    if d not in sys.path:
        sys.path.insert(0, d)
    return d

def _setup(b, wd):
    sys.stdout = sys.stderr = _Out(b)
    sys.stdin = _In(b)
    os.chdir(wd)
    return _site(wd)

def _exec(code, name):
    try:
        exec(compile(code, name, "exec"), {"__name__": "__main__", "__file__": name})
    except SystemExit:
        pass
    except BaseException as e:
        traceback.print_exception(type(e), e, e.__traceback__.tb_next)

def run(b, code, name, wd):
    _setup(b, wd)
    _exec(code, name)

def _norm(n): return re.sub(r"[-_.]+", "_", n).lower()

def _dists(d):
    out = []
    for f in os.listdir(d):
        if f.endswith(".dist-info") and "-" in f:
            n, v = f[:-10].rsplit("-", 1)
            out.append((n, v, f))
    return sorted(out)

def _pip(a, d):
    if not a or a[0] == "list":
        for n, v, _ in _dists(d): print(n, v)
    elif a[0] == "uninstall":
        for p in [x for x in a[1:] if not x.startswith("-")]:
            for n, v, f in _dists(d):
                if _norm(n) == _norm(p):
                    for l in open(os.path.join(d, f, "RECORD"), encoding="utf8"):
                        q = os.path.join(d, l.rsplit(",", 2)[0])
                        if os.path.isfile(q): os.remove(q)
                    shutil.rmtree(os.path.join(d, f), ignore_errors=True)
                    for r, ds, fs in os.walk(d, topdown=False):
                        if r != d and not os.listdir(r): os.rmdir(r)
                    print("Uninstalled", n)
                    break
            else:
                print("Not installed:", p)
    elif a[0] == "install":
        try:
            from pip._internal.cli.main import main
            main(["install", "--target", d, "--upgrade", "--no-warn-script-location",
                  "--disable-pip-version-check",
                  "--extra-index-url", "https://chaquo.com/pypi-13.1"] + a[1:])
        except SystemExit:
            pass
        except BaseException:
            traceback.print_exc()
    else:
        print("pip install|uninstall|list")

def _cmd(a, wd, d):
    c = a[0]
    if c == "help": print(HELP)
    elif c == "pip": _pip(a[1:], d)
    elif c in ("python", "python3"):
        if len(a) > 1:
            sys.argv = a[1:]
            _exec(open(a[1], encoding="utf8").read(), a[1])
        else:
            import code
            try:
                code.interact(banner="Python " + sys.version.split()[0], local={}, exitmsg="")
            except SystemExit:
                pass
    elif c == "ls": print("  ".join(sorted(os.listdir(a[1] if len(a) > 1 else "."))))
    elif c == "cd": os.chdir(a[1] if len(a) > 1 else wd)
    elif c == "pwd": print(os.getcwd())
    elif c == "cat": print(open(a[1], encoding="utf8").read())
    elif c == "mkdir": os.makedirs(a[1], exist_ok=True)
    elif c == "rm":
        shutil.rmtree(a[1]) if os.path.isdir(a[1]) else os.remove(a[1])
    elif c == "clear": sys.stdout.write("\f")
    elif c == "exit": return True
    else: print(c + ": command not found")

def shell(b, wd):
    d = _setup(b, wd)
    print("PyEditor Terminal  (help)")
    while True:
        sys.stdout.write(os.path.relpath(os.getcwd(), wd) + " $ ")
        line = b.readLine().strip()
        if not line: continue
        try:
            if _cmd(shlex.split(line), wd, d): break
        except SystemExit:
            pass
        except BaseException as e:
            print(type(e).__name__ + ":", e)
