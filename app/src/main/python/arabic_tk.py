"""Arabic text for Tk: joins the letters (shaping) and puts mixed Arabic/Latin text in display order (bidi).

Tk draws text left-to-right letter by letter, so Arabic comes out disconnected and reversed.  install() makes every
label / button / menu entry / canvas text / window title / dialog message go through shape() automatically.
Works without any pip package (the joining forms come from Python's own unicodedata table).

Use it by hand too:   import arabic_tk;  arabic_tk.shape("مرحبا")
Entry fields (also ttk.Entry / Combobox and the built-in input dialogs) join the letters while you type; entry.get() still
returns the normal logical text.  Typing works at the END of the field (the cursor is kept there).
Not covered yet: Text widgets and Treeview cells.
"""
import os
import unicodedata

_ISO, _FIN, _INI, _MED, _LIGA = {}, {}, {}, {}, {}
_TAT = 0x640
_ALEFS = (0x622, 0x623, 0x625, 0x627)
_BR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<", "«": "»", "»": "«"}


def _build():
    for cp in list(range(0xFE70, 0xFF00)) + list(range(0xFB50, 0xFE00)):
        d = unicodedata.decomposition(chr(cp))
        if not d.startswith("<"):
            continue
        tag, _, rest = d[1:].partition("> ")
        parts = rest.split()
        if len(parts) == 1:
            table = {"isolated": _ISO, "final": _FIN, "initial": _INI, "medial": _MED}.get(tag)
            if table is not None:
                table.setdefault(int(parts[0], 16), cp)
        elif len(parts) == 2 and parts[0] == "0644" and tag in ("isolated", "final"):
            _LIGA.setdefault((0x644, int(parts[1], 16)), {})[tag] = cp


_build()


def has_rtl(s):
    for ch in s:
        o = ord(ch)
        if 0x0590 <= o <= 0x08FF or 0xFB1D <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            return True
    return False


def _is_mark(ch):
    return unicodedata.category(ch) == "Mn"


def reshape(text):
    chars = list(text)
    n = len(chars)
    out = []
    prev_join = False          # does the previous letter connect to the next one?
    i = 0
    while i < n:
        c = chars[i]
        cp = ord(c)
        if _is_mark(c):
            out.append(c)
            i += 1
            continue
        if cp == _TAT:
            out.append(c)
            prev_join = True
            i += 1
            continue
        if cp not in _ISO:
            out.append(c)
            prev_join = False
            i += 1
            continue
        j = i + 1
        marks = []
        while j < n and _is_mark(chars[j]):
            marks.append(chars[j])
            j += 1
        nxt = ord(chars[j]) if j < n else None
        if cp == 0x644 and nxt in _ALEFS and (0x644, nxt) in _LIGA:
            lig = _LIGA[(0x644, nxt)]
            form = lig.get("final") if prev_join else None
            if form is None:
                form = lig.get("isolated")
            out.append(chr(form))
            out.extend(marks)
            prev_join = False
            i = j + 1
            continue
        join_next = cp in _INI and nxt is not None and (nxt in _FIN or nxt == _TAT)
        if prev_join and join_next and cp in _MED:
            form = _MED[cp]
        elif prev_join and cp in _FIN:
            form = _FIN[cp]
        elif join_next:
            form = _INI[cp]
        else:
            form = _ISO[cp]
        out.append(chr(form))
        out.extend(marks)
        prev_join = join_next
        i = j
    return "".join(out)


def _dir(ch):
    b = unicodedata.bidirectional(ch)
    if b in ("R", "AL"):
        return "R"
    if b in ("L", "EN", "AN"):
        return "L"
    return "N"


def _bidi_line(line):
    if not line:
        return line
    dirs = [_dir(c) for c in line]
    base = "L"
    for c in line:
        b = unicodedata.bidirectional(c)
        if b in ("R", "AL"):
            base = "R"
            break
        if b == "L":
            break
    res = list(dirs)
    n = len(res)
    i = 0
    while i < n:
        if dirs[i] != "N":
            i += 1
            continue
        j = i
        while j < n and dirs[j] == "N":
            j += 1
        left = dirs[i - 1] if i > 0 else base
        right = dirs[j] if j < n else base
        d = left if left == right else base
        for k in range(i, j):
            res[k] = d
        i = j
    runs = []
    for c, d in zip(line, res):
        if runs and runs[-1][0] == d:
            runs[-1][1].append(c)
        else:
            runs.append([d, [c]])
    if base == "R":
        runs.reverse()
    out = []
    for d, cs in runs:
        if d == "R":
            out.extend(_BR.get(c, c) for c in reversed(cs))
        else:
            out.extend(cs)
    return "".join(out)


def bidi(text):
    return "\n".join(_bidi_line(l) for l in text.split("\n"))


def shape(text):
    """joined letters + display order, ready to hand to Tk"""
    if not isinstance(text, str) or not has_rtl(text):
        return text
    return bidi(reshape(text))


# ---------------------------------------------------------------------------------------------------------
_KEYS = ("-text", "-label", "-title")
_WRAPPED = ("-message", "-detail")      # pop-up messages: wrapped here, because Tk would wrap the already reversed text
WRAP_PX = 0                              # set by tkrun (width of a pop-up message in pixels)
_shadows = {}


def wrap_lines(text, width, measure):
    """greedy word wrap on the LOGICAL text; every line is shaped separately so the reading order stays right"""
    out = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split(" "):
            trial = w if not cur else cur + " " + w
            if cur and measure(shape(trial)) > width:
                out.append(cur)
                cur = w
            else:
                cur = trial
        out.append(cur)
    return "\n".join(shape(l) for l in out)


def _wrap_shape(widget, text):
    if not WRAP_PX:
        return shape(text)
    try:
        import tkinter.font as tkfont
        f = tkfont.Font(root=widget, font="TkCaptionFont")
        return wrap_lines(text, int(WRAP_PX * 0.92), f.measure)
    except Exception:
        return shape(text)


def _shadow(widget, name):
    """Label(textvariable=var): show a shaped copy of the variable (the variable itself stays logical)"""
    if not isinstance(name, str):
        return name
    if name in _shadows:
        return _shadows[name]
    tk = widget.tk
    sh = name + "__ar"

    def sync(*a):
        try:
            v = tk.globalgetvar(name)
        except Exception:
            return
        try:
            tk.globalsetvar(sh, shape(v) if isinstance(v, str) else v)
        except Exception:
            pass

    try:
        sync()
        cmd = "pv_ar_sync_%d" % len(_shadows)
        tk.createcommand(cmd, sync)
        tk.call("trace", "add", "variable", name, "write", cmd)
    except Exception:
        return name
    _shadows[name] = sh
    return sh


def _install_entry():
    """Entry fields: keep the typed (logical) text in Python, show the shaped text in the field"""
    import tkinter
    from tkinter import ttk

    o_get, o_insert, o_delete = tkinter.Entry.get, tkinter.Entry.insert, tkinter.Entry.delete
    seen = set()

    def to_logical(d):
        return bidi(unicodedata.normalize("NFKC", d)) if has_rtl(d) else d

    def chars(t):
        return unicodedata.normalize("NFKC", t) if has_rtl(t) else t

    def display(w, logical):
        disp = shape(logical)
        o_delete(w, 0, "end")
        o_insert(w, 0, disp)
        try:
            w.icursor("end")
            w.configure(justify="right")
        except Exception:
            pass
        w._pv = [logical, disp]

    def get(self):
        d = o_get(self)
        st = getattr(self, "_pv", None)
        if st is not None and st[1] == d:
            return st[0]
        return d

    def insert(self, index, string):
        st = getattr(self, "_pv", None)
        if isinstance(string, str) and (has_rtl(string) or (st is not None and has_rtl(st[0]))):
            try:
                cur = get(self)
                try:
                    i = self.index(index)
                except Exception:
                    i = len(cur)
                new = (string + cur) if (i <= 0 and cur) else (cur + string)
                display(self, new)
                return
            except Exception:
                pass
        return o_insert(self, index, string)

    def delete(self, first, last=None):
        r = o_delete(self, first, last)
        try:
            if o_get(self) == "":
                self._pv = ["", ""]
        except Exception:
            pass
        return r

    def sync_init(w):
        try:
            d = o_get(w)
            st = getattr(w, "_pv", None)
            if st is None or st[1] != d:
                w._pv = [to_logical(d), d]
        except Exception:
            pass

    def fix(w):
        try:
            if not w.winfo_exists():
                return
            d1 = o_get(w)
            st = getattr(w, "_pv", None)
            if st is None:
                w._pv = [to_logical(d1), d1]
                return
            l0, d0 = st
            if d1 == d0:
                return
            if len(d1) > len(d0):
                k = 0
                while k < len(d0) and d0[k] == d1[k]:
                    k += 1
                l1 = l0 + chars(d1[k:k + len(d1) - len(d0)])
            elif len(d1) < len(d0):
                l1 = l0[:-(len(d0) - len(d1))]
            else:
                l1 = to_logical(d1)
            if has_rtl(l1) or has_rtl(l0):
                display(w, l1)
            else:
                w._pv = [l1, d1]
        except Exception:
            pass

    def attach(w):
        try:
            w.bindtags(("PvAr",) + tuple(w.bindtags()))
            if id(w.tk) not in seen:
                seen.add(id(w.tk))
                w.bind_class("PvAr", "<KeyPress>", lambda e: e.widget.after_idle(fix, e.widget), add="+")
                w.bind_class("PvAr", "<FocusIn>", lambda e: sync_init(e.widget), add="+")
        except Exception:
            pass

    for cls in (tkinter.Entry, ttk.Entry):
        orig = cls.__init__

        def __init__(self, *a, _orig=orig, **k):
            _orig(self, *a, **k)
            attach(self)

        cls.__init__ = __init__

    tkinter.Entry.get = get
    tkinter.Entry.insert = insert
    tkinter.Entry.delete = delete


def install():
    """patch tkinter so Arabic shows correctly everywhere text is only displayed"""
    if os.environ.get("PYVORA_TK_ARABIC", "1") == "0":
        return
    import tkinter
    from tkinter import ttk

    entryish = (tkinter.Entry, tkinter.Spinbox, ttk.Entry)
    orig_options = tkinter.Misc._options

    def _options(self, cnf, kw=None):
        res = orig_options(self, cnf, kw)
        try:
            out = list(res)
            for i in range(0, len(out) - 1, 2):
                k, v = out[i], out[i + 1]
                if k in _KEYS:
                    if isinstance(v, str) and has_rtl(v):
                        out[i + 1] = shape(v)
                elif k in _WRAPPED:
                    if isinstance(v, str) and has_rtl(v):
                        out[i + 1] = _wrap_shape(self, v)
                elif k == "-textvariable" and not isinstance(self, entryish):
                    out[i + 1] = _shadow(self, str(v))
            return tuple(out)
        except Exception:
            return res

    tkinter.Misc._options = _options

    orig_title = tkinter.Wm.wm_title

    def wm_title(self, string=None):
        if isinstance(string, str):
            string = shape(string)
        return orig_title(self, string)

    tkinter.Wm.wm_title = wm_title
    tkinter.Wm.title = wm_title
    try:
        _install_entry()
    except Exception:
        pass
