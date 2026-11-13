import sys, os, re, shlex, shutil, traceback, platform, ast, builtins, keyword, difflib

HELP = """Commands / الأوامر:
  pip install <pkg> | uninstall <pkg> | list | show <pkg> | freeze
  python file.py | python -c "code" | python (REPL)
  ls  cd  pwd  cat  echo  touch  mkdir  rm  cp  mv  clear  exit"""

HINT = """(!) فشل التحميل. غالبًا المكتبة مالهاش نسخة لأندرويد (زي pygame و Kivy و PyQt) أو الاسم غلط.
    Install failed: no Android build for this package, or wrong name."""

PIP_INDEX = "https://chaquo.com/pypi-13.1"
_IO = None
_HOME = ""
_SRC = {"code": "", "name": ""}


class _Out:
    encoding = "utf-8"; errors = "strict"
    def __init__(self, b): self.b = b
    def write(self, x):
        x = str(x)
        self.b.write(x); return len(x)
    def flush(self): pass
    def isatty(self): return False


class _Err(_Out):
    """stderr: the console paints text between \x01 and \x02 in red."""
    def write(self, x):
        x = str(x)
        if x: self.b.write("\x01" + x + "\x02")
        return len(x)


class _In:
    encoding = "utf-8"
    def __init__(self, b): self.b = b
    def readline(self, *a): return self.b.readLine()
    def read(self, *a): return self.b.readLine()
    def readlines(self, *a): return [self.b.readLine()]
    def __iter__(self): return self
    def __next__(self):
        s = self.b.readLine()
        if not s: raise StopIteration
        return s
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


def _setup(b, wd, pub=""):
    """wd = private app folder (libraries). pub = public folder on the phone storage (user files)."""
    global _IO, _HOME
    _IO = b
    sys.stdout = _Out(b); sys.stderr = _Err(b)
    sys.stdin = _In(b)
    _HOME = wd
    if pub:
        try:
            os.makedirs(pub, exist_ok=True)
            if os.access(pub, os.W_OK): _HOME = pub
        except OSError:
            pass
    os.chdir(_HOME)
    os.environ["PYVORA_DIR"] = _HOME
    if _HOME not in sys.path: sys.path.insert(0, _HOME)
    import tkshim
    tkshim._install()
    return _site(wd)


# =====================================================================
#                      friendly error messages
# =====================================================================
_SOFT = {"match", "case"}
_EXEMPT = {"__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__loader__", "__package__",
           "__class__", "__path__", "__annotations__", "__cached__"}
_PYTHON2 = {"raw_input": "input", "unicode": "str", "xrange": "range", "unichr": "chr", "long": "int"}
_NOANDROID = ("pygame", "kivy", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi")
_PIPNAME = {"cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "yaml": "pyyaml",
            "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "Crypto": "pycryptodome"}


def _suggest(word, pool, cutoff=0.7, n=3):
    word = str(word or "")
    if not word: return []
    pool = [p for p in set(pool) if isinstance(p, str) and p != word and (word.startswith("_") or not p.startswith("__"))]
    out = []
    low = {}
    for p in pool: low.setdefault(p.lower(), p)
    if word.lower() in low: out.append(low[word.lower()])
    for m in difflib.get_close_matches(word, pool, n=n, cutoff=cutoff):
        if m not in out: out.append(m)
    return out[:n]


def _dym(s):
    if not s: return ""
    return "هل تقصد " + " أو ".join('"%s"' % x for x in s) + " ؟"


def _b2c(line, b):
    """UTF-8 byte offset -> character offset."""
    try: return len(line.encode("utf-8")[:b].decode("utf-8", "ignore"))
    except Exception: return b


def _code_block(lines, n, c0=None, c1=None):
    """'  3 │ code' + caret line. c0/c1 are 0-based character offsets in the original line."""
    if not (0 < n <= len(lines)): return ""
    raw = lines[n - 1].rstrip("\r\n").replace("\t", "    ")
    st = raw.lstrip()
    if not st: return ""
    delta = len(raw) - len(st)
    pre = "  %d │ " % n
    out = pre + st + "\n"
    if c0 is not None:
        c1 = c1 if (c1 is not None and c1 > c0) else c0 + 1
        a = max(0, c0 - delta); w = max(1, min(c1 - c0, max(1, len(st) - a)))
        out += " " * (len(pre) + a) + "^" * w + "\n"
    return out


def _frames(tb):
    r = []
    while tb:
        r.append((tb.tb_frame, tb.tb_lineno)); tb = tb.tb_next
    return r


def _installed_names():
    names = set()
    try:
        import sysconfig
        for d in set(p for p in sys.path if isinstance(p, str) and p.endswith("site-packages")):
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith(".dist-info") or f.startswith("_"): continue
                    names.add(f.split(".")[0])
    except Exception:
        pass
    return names


def _known_modules():
    s = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names) | _installed_names()
    s |= {"tkinter", "matplotlib", "numpy", "PIL", "requests"}
    return {x for x in s if not x.startswith("_")}


def _explain(e, uframe):
    """Return a short Arabic explanation for exception e (may be '')."""
    t = type(e).__name__; m = str(e)
    g = {}
    if uframe is not None:
        g.update(uframe.f_globals); g.update(uframe.f_locals)
    if isinstance(e, UnboundLocalError):
        n = getattr(e, "name", None) or (re.search(r"'(\w+)'", m) or [0, "?"])[1]
        return ('المتغير "%s" اتستخدم داخل الدالة قبل ما تتحط له قيمة. '
                'لو هو متغير برّه الدالة اكتب global %s في أول الدالة، أو اديله قيمة قبل الاستخدام.') % (n, n)
    if isinstance(e, NameError):
        n = getattr(e, "name", None) or (re.search(r"'(\w+)'", m) or [0, "?"])[1]
        if n in _PYTHON2:
            return 'كلمة "%s" كانت في بايثون 2. في بايثون 3 استخدم "%s".' % (n, _PYTHON2[n])
        sg = _suggest(n, list(g) + dir(builtins) + keyword.kwlist)
        if sg: return 'كلمة "%s" غير معروفة. %s' % (n, _dym(sg))
        return ('كلمة "%s" غير معروفة. اتأكد إنك كتبتها صح، أو عرّفتها (متغير/دالة) قبل ما تستخدمها، '
                'أو عملت لها import.') % n
    if isinstance(e, AttributeError):
        n = getattr(e, "name", None); o = getattr(e, "obj", None)
        if n is None:
            mm = re.search(r"attribute '(\w+)'", m); n = mm.group(1) if mm else "?"
        if o is None and "NoneType" in m:
            return ('القيمة اللي بتستخدمها فاضية (None) فمفيهاش "%s". غالبًا دالة رجّعت None '
                    'أو نسيت return، أو بحث ملقاش نتيجة.') % n
        if o is not None:
            tn = "موديول %s" % o.__name__ if isinstance(o, type(os)) else 'من نوع "%s"' % type(o).__name__
            sg = _suggest(n, dir(o))
            return 'الكائن %s ماعندوش "%s". %s' % (tn, n, _dym(sg) if sg else "اتأكد من الاسم ومن حروفه (كبير/صغير).")
        return 'مفيش خاصية اسمها "%s". %s' % (n, "")
    if isinstance(e, ModuleNotFoundError):
        n = getattr(e, "name", None) or "?"
        top = n.split(".")[0]
        if top in _NOANDROID:
            return 'مكتبة "%s" مالهاش نسخة تشتغل على أندرويد.' % top
        sg = _suggest(top, _known_modules())
        s = 'المكتبة "%s" مش موجودة. ' % n
        if sg: s += _dym(sg) + " "
        s += 'لو دي مكتبة خارجية ثبّتها من القائمة ☰ ← Pip (اسم التثبيت: %s).' % _PIPNAME.get(top, top)
        return s
    if isinstance(e, ImportError):
        mod = getattr(e, "name", None)
        mm = re.search(r"cannot import name '(\w+)'", m)
        if mm and mod in sys.modules:
            sg = _suggest(mm.group(1), dir(sys.modules[mod]))
            return 'مفيش "%s" جوه "%s". %s' % (mm.group(1), mod, _dym(sg))
        return "فشل استيراد المكتبة. " + m
    if isinstance(e, ZeroDivisionError):
        return "حصلت قسمة على صفر. اتأكد إن المقسوم عليه مش 0 قبل القسمة."
    if isinstance(e, IndexError):
        return "رقم العنصر أكبر من عدد العناصر الموجودة. افتكر إن الترقيم بيبدأ من 0 وآخر عنصر رقمه len(x)-1."
    if isinstance(e, KeyError):
        return 'المفتاح %s مش موجود في القاموس (dict). استخدم .get(المفتاح) أو اتأكد من الاسم.' % (m,)
    if isinstance(e, FileNotFoundError):
        return 'الملف أو الفولدر "%s" مش موجود. المسار الحالي: %s' % (getattr(e, "filename", "") or m, os.getcwd())
    if isinstance(e, PermissionError):
        return "مفيش صلاحية للوصول للملف ده. فعّل صلاحية الملفات للتطبيق من الإعدادات."
    if isinstance(e, IsADirectoryError):
        return "ده فولدر مش ملف."
    if isinstance(e, RecursionError):
        return "الدالة بتنادي نفسها بدون ما توقف. ضيف شرط إيقاف (base case)."
    if isinstance(e, EOFError):
        return "البرنامج طلب إدخال (input) لكن مفيش مدخلات."
    if isinstance(e, UnicodeError):
        return "مشكلة في ترميز الحروف. جرّب open(path, encoding='utf-8')."
    if isinstance(e, AssertionError):
        return "شرط assert اتحقق بالغلط (النتيجة كانت False)."
    if isinstance(e, OverflowError):
        return "الرقم كبير أوي على العملية دي."
    if isinstance(e, MemoryError):
        return "الذاكرة خلصت."
    if isinstance(e, ValueError):
        mm = re.search(r"invalid literal for int\(\) with base \d+: (.+)", m)
        if mm: return "النص %s مش رقم صحيح، فمش ينفع تحوله بـ int(). اتأكد إن المستخدم كتب رقم فعلاً." % mm.group(1)
        mm = re.search(r"could not convert string to float: (.+)", m)
        if mm: return "النص %s مش رقم، فمش ينفع تحوله بـ float()." % mm.group(1)
        mm = re.search(r"not enough values to unpack \(expected (\d+), got (\d+)\)", m)
        if mm: return "بتفك %s قيم لكن الموجود %s بس." % (mm.group(1), mm.group(2))
        mm = re.search(r"too many values to unpack \(expected (\d+)", m)
        if mm: return "القيم أكتر من %s اللي متوقعها." % mm.group(1)
        if "math domain error" in m: return "القيمة خارج نطاق الدالة الرياضية (زي جذر عدد سالب أو log لصفر)."
        if "not in list" in m: return "العنصر اللي بتدوّر عليه مش موجود في القائمة."
        if hasattr(e, "lineno") and hasattr(e, "colno") and hasattr(e, "doc"):
            return "ملف JSON مكتوب غلط عند السطر %s عمود %s." % (e.lineno, e.colno)
        return "القيمة مش مناسبة للعملية دي."
    if isinstance(e, TypeError):
        mm = re.search(r"unsupported operand type\(s\) for ([^:]+): '(\w+)' and '(\w+)'", m)
        if mm:
            a, b = mm.group(2), mm.group(3)
            s = 'مش ينفع تستخدم العملية %s بين نوع "%s" ونوع "%s".' % (mm.group(1).strip(), a, b)
            if {a, b} & {"str"} and {a, b} & {"int", "float"}:
                s += " حوّل النص لرقم بـ int()/float() أو الرقم لنص بـ str()."
            return s
        mm = re.search(r'can only concatenate str \(not "(\w+)"\) to str', m)
        if mm: return 'مش ينفع تجمع نص مع "%s". حوّله بـ str(...) أو استخدم f-string.' % mm.group(1)
        mm = re.search(r"'(\w+)' object is not callable", m)
        if mm: return 'قيمة من نوع "%s" مش دالة عشان تتنادي بأقواس (). شيل الأقواس، أو اتأكد إنك مغيّرتش اسم دالة بمتغير.' % mm.group(1)
        mm = re.search(r"'(\w+)' object is not subscriptable", m)
        if mm:
            if mm.group(1) == "NoneType": return "القيمة فاضية (None) فمش ينفع تستخدم [] معاها. غالبًا دالة رجّعت None."
            return 'مش ينفع تستخدم [] مع نوع "%s".' % mm.group(1)
        mm = re.search(r"'(\w+)' object is not iterable", m)
        if mm: return 'مش ينفع تلف (for) على نوع "%s".' % mm.group(1)
        mm = re.search(r"(\w+)\(\) missing (\d+) required positional argument", m)
        if mm: return 'الدالة %s() محتاجة %s قيمة وإنت ما كتبتهاش.' % (mm.group(1), mm.group(2))
        mm = re.search(r"(\w+)\(\) takes (\d+|from \d+ to \d+) positional arguments? but (\d+) (?:was|were) given", m)
        if mm: return 'الدالة %s() بتاخد %s قيمة وإنت بعتّ %s.' % (mm.group(1), mm.group(2), mm.group(3))
        mm = re.search(r"(\w+)\(\) got an unexpected keyword argument '(\w+)'", m)
        if mm: return 'الدالة %s() مفيهاش مُعامل اسمه "%s".' % (mm.group(1), mm.group(2))
        if "string indices must be integers" in m: return "الفهرس (index) في النص لازم يبقى رقم."
        if "list indices must be integers" in m: return "الفهرس (index) في القائمة لازم يبقى رقم صحيح مش نص."
        if "not supported between instances" in m: return "مش ينفع تقارن بين نوعين مختلفين (زي رقم ونص)."
        return "نوع القيمة مش مناسب للعملية دي."
    if t == "TclError":
        return "خطأ في مكتبة tkinter (واجهة الرسوم)."
    return ""


def _fmt_syntax(e, lines, name):
    msg = e.msg or ""; ln = e.lineno or 0
    off = e.offset or 0
    text = e.text
    if e.filename and e.filename != name and text:
        lines = text.split("\n")
        ln = 1 if ln == 0 or ln > len(lines) else ln
    c0 = off - 1 if off else None
    c1 = (e.end_offset - 1) if getattr(e, "end_offset", None) and getattr(e, "end_lineno", ln) == ln else None
    is_ind = isinstance(e, IndentationError)
    out = "✖ %s في السطر %d\n" % ("خطأ في المسافات (Indentation)" if is_ind else "خطأ في كتابة الكود (Syntax)", ln)
    out += _code_block(lines, ln, c0, c1)
    ex = ""
    word = None
    cur = lines[ln - 1] if 0 < ln <= len(lines) else (text or "")
    mm = re.match(r"\s*([A-Za-z_]\w*)", cur)
    if mm: word = mm.group(1)
    mt = re.search(r"'(.)' was never closed", msg)
    if mt: ex = 'القوس "%s" اتفتح في السطر %d وما اتقفلش. اقفله بالقوس المناسب.' % (mt.group(1), ln)
    elif "unterminated triple-quoted" in msg: ex = 'النص اللي بيبدأ بـ """ ما اتقفلش. اقفله بـ """.'
    elif "unterminated string literal" in msg: ex = "النص مفتوح بعلامة تنصيص ومقفولش. ناقص ' أو \" في آخره."
    elif re.search(r"expected ':'", msg): ex = 'ناقص ":" في آخر السطر (بعد if / for / while / def / class / else ...).'
    elif re.search(r"unmatched '(.)'", msg):
        ex = 'القوس "%s" زيادة وملوش قوس فتح.' % re.search(r"unmatched '(.)'", msg).group(1)
    elif "does not match opening" in msg: ex = "القوس المقفول مش نفس نوع القوس اللي اتفتح قبله."
    elif "unexpected indent" in msg: ex = "فيه مسافات زيادة في بداية السطر. شيلها أو خلّيها زي السطر اللي فوقه."
    elif "unindent does not match" in msg: ex = "مسافة بداية السطر مش مطابقة لأي مستوى قبلها."
    elif "expected an indented block" in msg: ex = "بعد السطر اللي بينتهي بـ : لازم السطر اللي بعده يبدأ بمسافة (4 مسافات)."
    elif "Missing parentheses in call to 'print'" in msg: ex = 'في بايثون 3 اكتب print("...") بأقواس.'
    elif "Maybe you meant '=='" in msg or "cannot assign to" in msg: ex = "لو بتقارن بين قيمتين استخدم == (اتنين يساوي) مش =."
    elif "Perhaps you forgot a comma" in msg: ex = "غالبًا نسيت فاصلة , بين العناصر."
    elif "'return' outside function" in msg: ex = "return لازم تكون جوه دالة (def)."
    elif "'break' outside loop" in msg or "'continue' not properly in loop" in msg: ex = "break و continue بيشتغلوا جوه for أو while بس."
    elif "positional argument follows keyword argument" in msg: ex = "القيم العادية لازم تيجي قبل القيم اللي ليها اسم."
    elif "non-default argument follows default argument" in msg: ex = "المُعاملات اللي ليها قيمة افتراضية لازم تيجي آخر الأقواس."
    elif "invalid decimal literal" in msg: ex = "رقم مكتوب غلط، أو اسم متغير بيبدأ برقم."
    elif "invalid character" in msg or "non-printable" in msg:
        ex = "فيه حرف غير مسموح في الكود (غالبًا علامات تنصيص منحنية “ ” أو مسافة مخفية). اكتب العلامات العادية \" و '."
    elif "expected 'except' or 'finally'" in msg: ex = "try لازم يجي بعدها except أو finally."
    elif "f-string" in msg: ex = "فيه مشكلة جوه f-string (راجع الأقواس { } والعلامات)."
    elif "unexpected EOF" in msg or "EOL" in msg: ex = "الكود ناقص (فيه قوس أو علامة تنصيص مش مقفولة)."
    if word and (not ex or msg == "invalid syntax") and word not in keyword.kwlist and word not in _SOFT:
        nxt = cur.lstrip()[len(word):len(word) + 1]
        if nxt in ("", " ", "\t", ":") or word in _PYTHON2:
            pool = keyword.kwlist + [b for b in dir(builtins) if b.islower() and not b.startswith("_")]
            sg = _suggest(word, pool, 0.6)
            if word in _PYTHON2: sg = [_PYTHON2[word]]
            if sg: ex = 'كلمة "%s" مش معروفة في بايثون. %s' % (word, _dym(sg))
    if not ex:
        ex = "الجملة مكتوبة غلط. راجع الكلمات والأقواس وعلامات التنصيص والنقطتين في السطر ده (وأحيانًا في السطر اللي قبله)."
    return out + ex + "\n(%s: %s)" % (type(e).__name__, msg)


def _fmt_exc(e):
    name = _SRC.get("name", ""); code = _SRC.get("code", "")
    lines = code.split("\n")
    if isinstance(e, SyntaxError):
        return _fmt_syntax(e, lines, name)
    tb = e.__traceback__
    fr = _frames(tb)
    fs = traceback.extract_tb(tb)
    user = [(f, s) for f, s in zip(fr, fs) if f[0].f_code.co_filename == name]
    uframe = user[-1][0][0] if user else None
    out = ""
    if user:
        (fobj, ln), s = user[-1]
        fn = s.name
        head = "✖ خطأ في السطر %d" % ln
        if fn and fn != "<module>": head += " (داخل الدالة %s)" % fn
        head += " — " + type(e).__name__
        out += head + "\n"
        c0 = c1 = None
        if getattr(s, "colno", None) is not None and getattr(s, "end_lineno", ln) == ln:
            raw = lines[ln - 1] if 0 < ln <= len(lines) else ""
            c0 = _b2c(raw, s.colno); c1 = _b2c(raw, s.end_colno) if s.end_colno else None
        out += _code_block(lines, ln, c0, c1)
        if len(user) > 1:
            out += "اتنادت من:\n"
            for (fo, l2), s2 in reversed(user[:-1]):
                out += "  السطر %d%s\n" % (l2, "" if s2.name == "<module>" else " (داخل %s)" % s2.name)
        last = fs[-1]
        if last.filename != name:
            out += "(الخطأ حصل جوه مكتبة: %s سطر %s)\n" % (os.path.basename(last.filename), last.lineno)
    else:
        out += "✖ خطأ — %s\n" % type(e).__name__
    ex = _explain(e, uframe)
    if ex: out += ex + "\n"
    msg = str(e)
    out += "(%s%s)" % (type(e).__name__, (": " + msg) if msg else "")
    return out


def report_exc(e=None):
    e = e or sys.exc_info()[1]
    if e is None: return
    try: s = _fmt_exc(e)
    except Exception:
        s = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    sys.stderr.write(s + "\n")


_STAR_OK = {"tkinter": "tkinter", "tkinter.ttk": "tkinter.ttk", "tkinter.constants": "tkinter.constants",
            "math": "math", "random": "random", "time": "time"}


def _static_check(tree, lines):
    """Find misspelled names (close to a known word) before running."""
    bound = set(); stars = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)): bound.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): bound.add(n.name)
        elif isinstance(n, ast.arg): bound.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name == "*": stars.append(getattr(n, "module", None) or "")
                else: bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name: bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)): bound.update(n.names)
        elif type(n).__name__ == "MatchAs" and n.name: bound.add(n.name)
        elif type(n).__name__ == "MatchStar" and n.name: bound.add(n.name)
        elif type(n).__name__ == "MatchMapping" and n.rest: bound.add(n.rest)
    for s in stars:
        if s not in _STAR_OK: return []
        try:
            import importlib
            bound.update(dir(importlib.import_module(_STAR_OK[s])))
        except Exception:
            return []
    known = bound | set(dir(builtins)) | _EXEMPT
    pool = list(bound | set(dir(builtins)) | set(keyword.kwlist))
    seen = {}; res = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in known and n.id not in seen:
            seen[n.id] = 1
            if n.id in _PYTHON2: sg = [_PYTHON2[n.id]]
            else: sg = _suggest(n.id, pool, 0.75)
            if sg: res.append((n.lineno, n.col_offset, n.end_col_offset, n.id, sg))
    res.sort()
    return res


def _exec(code, name):
    import tkshim
    tkshim._reset()
    _SRC["code"] = code; _SRC["name"] = name
    try:
        tree = compile(code, name, "exec", flags=ast.PyCF_ONLY_AST)
        bad = _static_check(tree, code.split("\n"))
        if bad:
            lines = code.split("\n"); out = ""
            for ln, c0, c1, w, sg in bad:
                raw = lines[ln - 1] if 0 < ln <= len(lines) else ""
                out += '✖ في السطر %d: كلمة "%s" غير معروفة. %s\n' % (ln, w, _dym(sg))
                out += _code_block(lines, ln, _b2c(raw, c0), _b2c(raw, c1) if c1 else None) + "\n"
            sys.stderr.write(out + "صحّح الكلمات دي وشغّل تاني (البرنامج ما اشتغلش).\n")
            return
        co = compile(tree, name, "exec")
    except SyntaxError as e:
        report_exc(e); return
    except (ValueError, TypeError) as e:
        report_exc(e); return
    g = {"__name__": "__main__", "__file__": name, "__builtins__": builtins}
    try:
        exec(co, g)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        sys.stderr.write("KeyboardInterrupt\n")
    except BaseException as e:
        report_exc(e)


def run(b, code, name, wd, pub=""):
    _setup(b, wd, pub)
    if not pub:
        sys.stderr.write("⚠ مفيش صلاحية الملفات: الملفات هتتحفظ جوه التطبيق بس. فعّلها من القائمة ☰ ← صلاحية الملفات.\n")
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
    elif c == "cd": os.chdir(os.path.expanduser(a[1]) if len(a) > 1 and a[1] != "~" else _HOME)
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
    rel = os.path.relpath(os.path.realpath(os.getcwd()), os.path.realpath(_HOME))
    return ("~" if rel == "." else "~/" + rel if not rel.startswith("..") else os.getcwd()) + " $ "

def shell(b, wd, pub=""):
    d = _setup(b, wd, pub)
    print("PYVORA Terminal  (help)   —  " + _HOME)
    while True:
        sys.stdout.write(_prompt(wd))
        line = b.readLine().strip()
        if not line: continue
        try:
            if _cmd(shlex.split(line), wd, d): break
        except SystemExit:
            pass
        except BaseException as e:
            print(type(e).__name__ + ":", e, file=sys.stderr)

def pip_page(b, wd, pub=""):
    d = _setup(b, wd, pub)
    print("Pip  -  installed / المثبتة:")
    _pip(["list"], d)
    print("")
    while True:
        a = b.readLine().split()
        if a and a[0] in ("install", "uninstall", "list"):
            _pip(a, d)
            print("-- done --")
