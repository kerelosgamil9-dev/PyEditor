import sys, os, re, shlex, shutil, traceback, platform

HELP = """Commands / الأوامر:
  pip install <pkg> | uninstall <pkg> | list | show <pkg> | freeze
  python file.py | python -c "code" | python (REPL)
  ls  cd  pwd  cat  echo  touch  mkdir  rm  cp  mv  clear  exit"""

HINT = """(!) فشل التحميل. غالبًا المكتبة مالهاش نسخة لأندرويد (زي pygame و Kivy و PyQt) أو الاسم غلط.
    Install failed: no Android build for this package, or wrong name."""

PIP_INDEX = "https://chaquo.com/pypi-13.1"
_IO = None

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

def _preload(d):
    """Load helper .so files (libc++, openblas...) that downloaded native wheels depend on."""
    try:
        import ctypes, glob
        libs = glob.glob(os.path.join(d, "chaquopy", "lib", "*.so*")) + glob.glob(os.path.join(d, "*.libs", "*.so*"))
        for _ in range(4):
            left = []
            for f in libs:
                try: ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
                except OSError: left.append(f)
            if not left or left == libs: break
            libs = left
    except Exception:
        pass

def _site(wd):
    d = os.path.join(wd, "site-packages")
    os.makedirs(d, exist_ok=True)
    if d not in sys.path:
        sys.path.insert(0, d)
        _preload(d)
    os.environ.setdefault("HOME", wd)
    os.environ["MPLCONFIGDIR"] = os.path.join(wd, "mpl")
    os.environ.setdefault("MPLBACKEND", "module://pyvora_mpl")
    return d

def _setup(b, wd):
    global _IO
    _IO = b
    sys.stdout = sys.stderr = _Out(b)
    sys.stdin = _In(b)
    os.chdir(wd)
    import tkshim
    tkshim._install()
    return _site(wd)

def _exec(code, name):
    import tkshim
    tkshim._reset()
    try:
        exec(compile(code, name, "exec"), {"__name__": "__main__", "__file__": name})
    except SystemExit:
        pass
    except BaseException as e:
        traceback.print_exception(type(e), e, e.__traceback__.tb_next)

def run(b, code, name, wd):
    _setup(b, wd)
    _exec(code, name)

# ---------------- pip ----------------
def _norm(n): return re.sub(r"[-_.]+", "_", n).lower()

def _dists(d):
    out = []
    for f in os.listdir(d):
        if f.endswith(".dist-info") and "-" in f:
            n, v = f[:-10].rsplit("-", 1)
            out.append((n, v, f))
    return sorted(out, key=lambda x: x[0].lower())

def _plat():
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"): abi = "arm64_v8a"
    elif m == "x86_64": abi = "x86_64"
    elif m in ("i686", "x86"): abi = "x86"
    else: abi = "armeabi_v7a"
    return ["android_%d_%s" % (api, abi) for api in range(16, 25)]

def _pipcmd(d, a, extra=()):
    v = sys.version_info
    cmd = ["install", "--target", d, "--upgrade", "--no-warn-script-location", "--no-warn-conflicts",
           "--disable-pip-version-check", "--only-binary=:all:", "--implementation", "cp",
           "--python-version", "%d.%d" % (v[0], v[1]), "--abi", "cp%d%d" % (v[0], v[1]),
           "--extra-index-url", PIP_INDEX] + list(extra)
    for p in _plat(): cmd += ["--platform", p]
    return cmd + list(a)

def _fix_pip(d):
    """sys.path on Android has special objects pip cannot scan: make pip look only in our folder."""
    from pip._internal.metadata.importlib import _envs
    E = _envs.Environment
    E.default = classmethod(lambda cls: cls([d]))
    E.from_paths = classmethod(lambda cls, paths=None: cls([d] if paths is None else [x for x in paths if isinstance(x, str)]))

def _cacert(wd):
    p = os.path.join(wd, "cacert.pem")
    if not os.path.exists(p):
        import pkgutil
        with open(p, "wb") as f: f.write(pkgutil.get_data("pip._vendor.certifi", "cacert.pem"))
    return p

def _install(a, d):
    try:
        from pip._internal.cli.main import main
        _fix_pip(d)
        extra = []
        try: extra = ["--cert", _cacert(os.path.dirname(d))]
        except Exception: pass
        rc = main(_pipcmd(d, a, extra))
    except SystemExit as e:
        rc = e.code or 0
    except BaseException:
        traceback.print_exc(); rc = 1
    if rc: print(HINT)
    else: _preload(d)

def _pip(a, d):
    if not a or a[0] in ("list", "freeze"):
        for n, v, _ in _dists(d): print(n + ("==" if a and a[0] == "freeze" else " ") + v)
    elif a[0] == "show":
        for n, v, f in _dists(d):
            if a[1:] and _norm(n) == _norm(a[1]): print("Name:", n); print("Version:", v); print("Location:", d); return
        print("Not installed:", " ".join(a[1:]))
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
        _install(a[1:], d)
    else:
        print("pip install|uninstall|list|show|freeze")

# ---------------- terminal ----------------
def _cmd(a, wd, d):
    c = a[0]
    if c == "help": print(HELP)
    elif c == "pip": _pip(a[1:], d)
    elif c in ("python", "python3"):
        if a[1:3] == ["-m", "pip"]: _pip(a[3:], d)
        elif a[1:2] == ["-c"]: _exec(a[2], "<string>")
        elif len(a) > 1:
            sys.argv = a[1:]
            _exec(open(a[1], encoding="utf8").read(), a[1])
        else:
            import code
            try:
                code.interact(banner="Python " + sys.version.split()[0], local={}, exitmsg="")
            except SystemExit:
                pass
    elif c == "ls":
        p = a[1] if len(a) > 1 else "."
        print("  ".join(x + ("/" if os.path.isdir(os.path.join(p, x)) else "") for x in sorted(os.listdir(p))))
    elif c == "cd": os.chdir(a[1] if len(a) > 1 else wd)
    elif c == "pwd": print(os.getcwd())
    elif c == "cat": print(open(a[1], encoding="utf8").read())
    elif c == "echo": print(" ".join(a[1:]))
    elif c == "touch": open(a[1], "a").close()
    elif c == "mkdir": os.makedirs(a[1], exist_ok=True)
    elif c == "cp": (shutil.copytree if os.path.isdir(a[1]) else shutil.copy)(a[1], a[2])
    elif c == "mv": shutil.move(a[1], a[2])
    elif c == "rm": shutil.rmtree(a[1]) if os.path.isdir(a[1]) else os.remove(a[1])
    elif c == "clear": sys.stdout.write("\f")
    elif c == "exit": return True
    else: print(c + ": command not found  (help)")

def _prompt(wd):
    rel = os.path.relpath(os.path.realpath(os.getcwd()), os.path.realpath(wd))
    return ("~" if rel == "." else "~/" + rel if not rel.startswith("..") else os.getcwd()) + " $ "

def shell(b, wd):
    d = _setup(b, wd)
    print("PYVORA Terminal  (help)")
    while True:
        sys.stdout.write(_prompt(wd))
        line = b.readLine().strip()
        if not line: continue
        try:
            if _cmd(shlex.split(line), wd, d): break
        except SystemExit:
            pass
        except BaseException as e:
            print(type(e).__name__ + ":", e)

def pip_page(b, wd):
    d = _setup(b, wd)
    print("Pip  -  installed / المثبتة:")
    _pip(["list"], d)
    print("")
    while True:
        a = b.readLine().split()
        if a and a[0] in ("install", "uninstall", "list"):
            _pip(a, d)
            print("-- done --")
