"""tkinter emulation: same API, widgets are drawn in a WebView (tk.html)."""
import sys, json, time, re, types, os, base64, traceback
import runner

_C = dict(NO=0, FALSE=0, OFF=0, YES=1, TRUE=1, ON=1,
          N="n", S="s", E="e", W="w", NW="nw", SW="sw", NE="ne", SE="se", NS="ns", EW="ew", NSEW="nsew",
          CENTER="center", NONE="none", X="x", Y="y", BOTH="both", LEFT="left", TOP="top", RIGHT="right",
          BOTTOM="bottom", RAISED="raised", SUNKEN="sunken", FLAT="flat", RIDGE="ridge", GROOVE="groove",
          SOLID="solid", HORIZONTAL="horizontal", VERTICAL="vertical", NUMERIC="numeric", CHAR="char",
          WORD="word", BASELINE="baseline", INSIDE="inside", OUTSIDE="outside", SEL="sel",
          SEL_FIRST="sel.first", SEL_LAST="sel.last", END="end", INSERT="insert", CURRENT="current",
          ANCHOR="anchor", ALL="all", NORMAL="normal", DISABLED="disabled", ACTIVE="active", HIDDEN="hidden",
          CASCADE="cascade", CHECKBUTTON="checkbutton", COMMAND="command", RADIOBUTTON="radiobutton",
          SEPARATOR="separator", SINGLE="single", BROWSE="browse", MULTIPLE="multiple", EXTENDED="extended",
          DOTBOX="dotbox", UNDERLINE="underline", PIESLICE="pieslice", CHORD="chord", ARC="arc",
          FIRST="first", LAST="last", BUTT="butt", PROJECTING="projecting", ROUND="round", BEVEL="bevel",
          MITER="miter", MOVETO="moveto", SCROLL="scroll", UNITS="units", PAGES="pages")
globals().update(_C)
TkVersion = 8.6
TclVersion = 8.6
READABLE = 2; WRITABLE = 4; EXCEPTION = 8
wantobjects = 1


class TclError(Exception):
    pass


_ops = []; _W = {}; _n = [0]; _after = []; _dlg = {}; _qres = {}; _dirty = []; _reg = {}; _IMGS = {}
_clip = [""]
_st = {"quit": False, "root": None, "w": 360, "h": 640, "aid": 0, "focus": 0, "imgclosed": False}
_STYLES = {}


def _reset():
    for d in (_ops, _after, _dirty):
        del d[:]
    for d in (_W, _dlg, _qres, _reg, _IMGS, _STYLES):
        d.clear()
    _n[0] = 0
    _st.update(quit=False, root=None, imgclosed=False, focus=0)


def _send(*o): _ops.append(list(o))


def _flush():
    while _dirty:
        w = _dirty.pop(0)
        try: w._sync()
        except Exception: runner.report_exc()
    if _ops:
        s = json.dumps(_ops, default=str); del _ops[:]
        runner._IO.gui(s)


def _mark(w):
    if w not in _dirty: _dirty.append(w)


def _query(op, *a, default=None, timeout=3.0):
    _n[0] += 1; r = _n[0]
    _send("q", r, op, list(a)); _flush()
    t0 = time.time()
    while r not in _qres and not _st["quit"] and time.time() - t0 < timeout:
        _pump(0.02)
    v = _qres.pop(r, default)
    return default if v is None else v


def _cb(f, *a):
    """Run a user callback; errors are shown (with friendly text) and do not stop the loop."""
    try:
        return f(*a)
    except SystemExit:
        _st["quit"] = True
    except BaseException as e:
        root = _st["root"]; h = getattr(root, "report_callback_exception", None) if root else None
        if h is not None and getattr(h, "__func__", None) is not Tk.report_callback_exception:
            try: h(type(e), e, e.__traceback__); return
            except Exception: pass
        runner.report_exc(e)


def _reg_cmd(f):
    _n[0] += 1; name = "register#%d" % _n[0]; _reg[name] = f; return name


# ---------------- fonts ----------------
_FONTS = []


class Font:
    def __init__(self, root=None, font=None, name=None, exists=False, family="Arial", size=10, weight="normal",
                 slant="roman", underline=0, overstrike=0, **k):
        self.d = dict(_font(font)) if font else {"f": family, "s": size, "w": "bold" if weight == "bold" else "",
                                                 "i": slant == "italic", "u": bool(underline), "o": bool(overstrike)}
        self._ws = []; self.name = name or "font%d" % len(_FONTS); _FONTS.append(self)
    def configure(self, **k):
        if "size" in k: self.d["s"] = k["size"]
        if "family" in k: self.d["f"] = k["family"]
        if "weight" in k: self.d["w"] = "bold" if k["weight"] == "bold" else ""
        if "slant" in k: self.d["i"] = k["slant"] == "italic"
        if "underline" in k: self.d["u"] = bool(k["underline"])
        if "overstrike" in k: self.d["o"] = bool(k["overstrike"])
        for w in list(self._ws):
            if w._id in _W: _send("cfg", w._id, {"font": dict(self.d)})
    config = configure
    def cget(self, k):
        return {"size": self.d["s"], "family": self.d["f"], "weight": "bold" if self.d["w"] else "normal",
                "slant": "italic" if self.d["i"] else "roman", "underline": int(self.d["u"]), "overstrike": int(self.d.get("o", 0))}.get(k)
    __getitem__ = cget
    def copy(self): return Font(font=self.d)
    def measure(self, t, displayof=None):
        r = _query("fm", self.d, str(t), default=None)
        return int(r) if r is not None else int(len(str(t)) * abs(self.d["s"]) * 0.6 * (1 if self.d["s"] < 0 else 1.333))
    def metrics(self, *a, **k):
        px = abs(self.d["s"]) * (1 if self.d["s"] < 0 else 1.333)
        m = _query("fmet", self.d, default=None) or {"ascent": int(px * .8), "descent": int(px * .25), "linespace": int(px * 1.2), "fixed": 0}
        return m[a[0].lstrip("-")] if a else m
    def actual(self, *a, **k):
        d = self.configure.__self__.d
        r = {"family": d["f"], "size": d["s"], "weight": "bold" if d["w"] else "normal", "slant": "italic" if d["i"] else "roman",
             "underline": int(d["u"]), "overstrike": int(d.get("o", 0))}
        return r[a[0].lstrip("-")] if a else r
    def __str__(self): return self.name


def _font(f):
    if f is None: return None
    if isinstance(f, Font): return f.d
    if isinstance(f, dict): return f
    if isinstance(f, str):
        m = re.match(r"^\{(.+?)\}\s*(.*)$", f)
        f = ([m.group(1)] + m.group(2).split()) if m else f.split()
    f = list(f); d = {"f": "", "s": 10, "w": "", "i": False, "u": False, "o": False}
    if f: d["f"] = str(f[0])
    if len(f) > 1:
        try: d["s"] = int(float(f[1]))
        except Exception: pass
    rest = " ".join(str(x) for x in f[2:]).lower()
    d["w"] = "bold" if "bold" in rest else ""; d["i"] = "italic" in rest; d["u"] = "underline" in rest; d["o"] = "overstrike" in rest
    return d


# ---------------- variables ----------------
class Variable:
    _d = ""
    def __init__(self, master=None, value=None, name=None):
        _n[0] += 1; self._name = name or "PY_VAR%d" % _n[0]
        self._v = self._d if value is None else value; self._ws = []; self._tr = []
    def __str__(self): return self._name
    def initialize(self, v): self.set(v)
    def _fire(self, mode):
        for md, cb in list(self._tr):
            if mode in md: _cb(cb, self._name, "", mode)
    def get(self):
        self._fire("read"); return self._v
    def set(self, v):
        self._v = v
        for w in list(self._ws): w._vupd(v)
        self._fire("write")
    def trace_add(self, mode, cb):
        md = (mode,) if isinstance(mode, str) else tuple(mode)
        self._tr.append((md, cb)); return "trace%d" % len(self._tr)
    def trace_remove(self, mode, cbname):
        try: self._tr.pop(int(str(cbname).replace("trace", "")) - 1)
        except Exception: pass
    def trace_info(self): return [(m, "trace%d" % (i + 1)) for i, (m, c) in enumerate(self._tr)]
    def trace_variable(self, mode, cb):
        m = {"w": "write", "r": "read", "u": "unset"}.get(mode, mode)
        return self.trace_add(m, lambda n, i, mo: cb(n, i, mode))
    trace = trace_variable
    def trace_vdelete(self, mode, cbname): self.trace_remove(mode, cbname)
    def trace_vinfo(self): return self.trace_info()
    def _link(self, w):
        if w not in self._ws: self._ws.append(w)


class StringVar(Variable):
    _d = ""
    def get(self): Variable.get(self); return str(self._v)


class IntVar(Variable):
    _d = 0
    def get(self):
        Variable.get(self)
        try: return int(float(self._v))
        except Exception: return 0


class DoubleVar(Variable):
    _d = 0.0
    def get(self):
        Variable.get(self)
        try: return float(self._v)
        except Exception: return 0.0


class BooleanVar(Variable):
    _d = False
    def get(self):
        Variable.get(self); v = self._v
        if isinstance(v, str): return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)
    def set(self, v): Variable.set(self, bool(v) if not isinstance(v, str) else v.strip().lower() in ("1", "true", "yes", "on"))


# ---------------- images ----------------
_MIME = {"png": "image/png", "gif": "image/gif", "jpg": "image/jpeg", "jpeg": "image/jpeg", "bmp": "image/bmp",
         "webp": "image/webp", "svg": "image/svg+xml", "ppm": "image/x-portable-pixmap"}


class Image:
    pass


class PhotoImage(Image):
    def __init__(self, name=None, cnf=None, master=None, **kw):
        kw.update(cnf or {})
        _n[0] += 1; self._id = _n[0]; _IMGS[self._id] = self; self.name = name or "pyimage%d" % self._id
        self._uri = None
        self._load(kw)
        _send("pimg", self._id, self._uri, int(kw.get("width", 0) or 0), int(kw.get("height", 0) or 0))
    def _load(self, kw):
        if "file" in kw and kw["file"]:
            p = str(kw["file"])
            try:
                with open(p, "rb") as f: raw = f.read()
            except OSError:
                raise TclError('couldn\'t open "%s": no such file or directory' % p)
            self._uri = "data:%s;base64,%s" % (_MIME.get(p.rsplit(".", 1)[-1].lower(), "image/png"), base64.b64encode(raw).decode())
        elif "data" in kw and kw["data"] is not None:
            d = kw["data"]
            if isinstance(d, str): d = d.encode()
            if d[:4] in (b"\x89PNG", b"GIF8", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1") or d[:2] == b"BM":
                raw64 = base64.b64encode(d).decode()
            else:
                raw64 = d.decode().strip().replace("\n", "")
            try: head = base64.b64decode(raw64[:16] + "=" * (-len(raw64[:16]) % 4))
            except Exception: head = b""
            mime = "image/gif" if head[:3] == b"GIF" else "image/jpeg" if head[:2] == b"\xff\xd8" else "image/png"
            self._uri = "data:%s;base64,%s" % (mime, raw64)
    def __str__(self): return self.name
    def width(self): r = _query("imgsz", self._id, default=[0, 0]); return int(r[0])
    def height(self): r = _query("imgsz", self._id, default=[0, 0]); return int(r[1])
    def blank(self): _send("imgclr", self._id)
    def read(self, filename, **k):
        self._load({"file": filename}); _send("pimg", self._id, self._uri, 0, 0)
    def data(self, *a, **k): return _query("imgdata", self._id, default="")
    def put(self, data, to=None):
        if isinstance(data, str) and "{" not in data and " " not in data.strip():
            rows = [[data]]
        elif isinstance(data, str):
            rows = [r.split() for r in re.findall(r"\{([^}]*)\}", data)] or [data.split()]
        else:
            rows = [[c] if isinstance(c, str) else list(c) for c in data]
            if rows and isinstance(rows[0], list) and rows[0] and isinstance(data[0], str): rows = [list(data)]
        to = list(to) if to else [0, 0]
        _send("imgput", self._id, rows, to)
    def get(self, x, y):
        r = _query("imgpx", self._id, int(x), int(y), default=[0, 0, 0]); return tuple(r[:3])
    def copy(self, **k):
        im = PhotoImage.__new__(PhotoImage); _n[0] += 1; im._id = _n[0]; _IMGS[im._id] = im; im.name = "pyimage%d" % im._id; im._uri = None
        _send("imgcopy", im._id, self._id, 1, 1, 1, 1); return im
    def _scaled(self, zx, zy, sx, sy):
        im = self.copy(); _send("imgcopy", im._id, self._id, zx, zy, sx, sy); return im
    def zoom(self, x, y=None): return self._scaled(int(x), int(y or x), 1, 1)
    def subsample(self, x, y=None): return self._scaled(1, 1, int(x), int(y or x))
    def write(self, filename, format=None, from_coords=None):
        b = _query("imgdata", self._id, default="")
        if b:
            with open(filename, "wb") as f: f.write(base64.b64decode(b))
    def cget(self, k): return {"file": "", "width": self.width(), "height": self.height()}.get(k, "")
    configure = config = lambda self, **k: None
    def transparency_get(self, x, y): return False
    transparency_set = lambda self, *a: None
    def copy_replace(self, *a, **k): pass


class BitmapImage(PhotoImage):
    pass


def image_names(): return tuple(i.name for i in _IMGS.values())


def image_types(): return ("photo", "bitmap")


# ---------------- helpers ----------------
_ALIAS = {"background": "bg", "foreground": "fg", "borderwidth": "bd", "invcmd": "invalidcommand", "vcmd": "validatecommand"}
_SKIP = ("cursor", "takefocus", "bitmap", "class_", "exportselection", "setgrid", "highlightcolor", "highlightbackground",
         "tearoff", "tearoffcommand", "title", "underline_", "xscrollincrement", "yscrollincrement", "confine", "colormap",
         "visual", "container", "use", "screen", "tabstyle", "elementborderwidth")


def _eoff(v, i):
    if i in ("end", "insert"): return len(v)
    try: return max(0, min(len(v), int(i)))
    except Exception: return len(v)


def _tkl(v):
    if isinstance(v, (list, tuple)): return [str(x) for x in v]
    s = str(v or "")
    if "{" in s: return [a or b for a, b in re.findall(r"\{([^}]*)\}|(\S+)", s)]
    return s.split()


def _parse(seq):
    seq = str(seq)
    if seq.startswith("<<"): return ("v:" + seq.strip("<>"), "", set())
    mods = set(); rest = []; dbl = False
    for x in seq.strip("<>").split("-"):
        if x in ("Control", "Ctrl"): mods.add("control")
        elif x == "Shift": mods.add("shift")
        elif x in ("Alt", "Mod1", "Option", "M1", "Meta", "M"): mods.add("alt")
        elif x in ("B1", "B2", "B3"): mods.add(x.lower())
        elif x in ("Any", "Lock", "Triple", "Quadruple"): pass
        elif x == "Double": dbl = True
        elif x: rest.append(x)
    if not rest: return ("key", "", mods)
    a = rest[0]; n = rest[1] if len(rest) > 1 else None
    if a == "Motion": return ("motion", "", mods)
    if a in ("Enter", "Leave", "FocusIn", "FocusOut", "Configure", "Map", "Unmap", "Destroy", "Expose", "Visibility"):
        return (a.lower(), "", mods)
    if a == "MouseWheel": return ("wheel", "", mods)
    if a in ("Button", "ButtonPress"): return (("dbl" if dbl else "b") + (n or "1"), "", mods)
    if a == "ButtonRelease": return ("b" + (n or "1") + "up", "", mods)
    if a.isdigit() and len(rest) == 1: return (("dbl" if dbl else "b") + a, "", mods)
    if a in ("Key", "KeyPress"): return ("key", n or "", mods)
    if a == "KeyRelease": return ("keyup", n or "", mods)
    return ("key", a, mods)


class Event:
    def __init__(self, **k): self.__dict__.update(k)
    def __repr__(self): return "<Event %s>" % " ".join("%s=%r" % (a, b) for a, b in self.__dict__.items() if a in ("type", "x", "y", "keysym", "char"))


class _TkObj:
    def call(self, *a): return ""
    eval = call
    def createcommand(self, name, f): _reg[name] = f
    def deletecommand(self, name): _reg.pop(name, None)
    def splitlist(self, s): return tuple(_tkl(s))
    def getboolean(self, s): return str(s).lower() in ("1", "true", "yes", "on")
    def getint(self, s): return int(s)
    def getdouble(self, s): return float(s)
    def __getattr__(self, n): return lambda *a, **k: ""


def _nop(self, *a, **k): return None


_NAMES = {}


class Misc:
    _type = "frame"; _ttk = 0
    def __init__(self, master=None, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw)
        if self._type == "root":
            master = None; _st["root"] = self
        elif master is None:
            master = _st["root"] or Tk()
        _n[0] += 1; self._id = _n[0]
        self.master = master; self._kids = []; self.children = {}; self._o = {}; self._cmd = None; self._var = None
        self._binds = {}; self._val = ""; self._sel = []; self._on = 1; self._off = 0; self._rv = ""; self._proto = {}
        self._geo = None; self._vc = None; self._fonts = []; self._tstate = set(); self._ysc = self._xsc = None
        self.tk = master.tk if master is not None else _TkObj()
        cls = type(self).__name__.lower()
        if master is not None:
            c = master._ncnt = getattr(master, "_ncnt", {}); c[cls] = c.get(cls, 0) + 1
            self._name = "!" + cls + (str(c[cls]) if c[cls] > 1 else "")
            master.children[self._name] = self
        else:
            self._name = "."
        _W[self._id] = self
        if master: master._kids.append(self)
        self._pre(o)
        _send("new", self._id, self._type, master._id if master else 0, self._cl(o))
        self._post(o)
    def __str__(self):
        if self.master is None: return "."
        p = str(self.master)
        return ("." if p == "." else p + ".") + self._name
    _w = property(lambda self: str(self))
    widgetName = property(lambda self: self._type)
    def _pre(self, o):
        if "onvalue" in o: self._on = o["onvalue"]
        if "offvalue" in o: self._off = o["offvalue"]
        if "value" in o and self._type == "radio": self._rv = o["value"]
        if self._type == "check": self._val = self._off
        if "validatecommand" in o or "vcmd" in o: self._setvc(o.get("validatecommand", o.get("vcmd")))
    def _post(self, o): pass
    def _oc(self, o): pass
    def _setvc(self, v):
        if callable(v): self._vc = (v, []); return
        if isinstance(v, (tuple, list)) and v:
            f = v[0]
            if isinstance(f, str): f = _reg.get(f.split()[0])
            if callable(f): self._vc = (f, [str(x) for x in v[1:]]); return
        if isinstance(v, str):
            parts = v.split()
            if parts and parts[0] in _reg: self._vc = (_reg[parts[0]], parts[1:]); return
        self._vc = None
    def _style_opts(self):
        if not self._ttk: return {}
        nm = self._o.get("style") or self._sname()
        return _style_resolve(nm, self._type)
    def _sname(self): return "T" + type(self).__name__
    def _cl(self, o):
        r = {}
        if "style" in o: self._o["style"] = o["style"]
        for k, v in o.items():
            k = _ALIAS.get(k, k)
            if k == "command":
                if self._type == "scroll":
                    tg = getattr(v, "__self__", None); nm = getattr(v, "__name__", "")
                    if isinstance(tg, Misc) and nm in ("yview", "xview"): r["lk"] = [tg._id, nm[0]]
                    else: self._cmd = v; r["cmd"] = 1
                else:
                    self._cmd = v; r["cmd"] = 1
            elif k in ("yscrollcommand", "xscrollcommand"):
                tg = getattr(v, "__self__", None)
                if isinstance(tg, Scrollbar): _send("cfg", tg._id, {"lk": [self._id, k[0]]})
                elif callable(v):
                    setattr(self, "_ysc" if k[0] == "y" else "_xsc", v); r["sc" + k[0]] = 1
            elif k in ("textvariable", "variable", "listvariable"):
                self._var = v; v._link(self); t = self._type
                x = v._v
                if k == "listvariable": self._items = [str(i) for i in _tkl(x)]; r["items"] = self._items
                elif k == "textvariable":
                    if t in ("entry", "spin", "combo"): r["val"] = x; self._val = x
                    else: r["tv"] = x
                else:
                    self._val = x
                    if t == "check": r["chk"] = (x == self._on)
                    elif t == "radio": r["chk"] = (str(x) == str(self._rv))
                    else: r["val"] = x
            elif k == "font":
                if isinstance(v, Font) and self not in v._ws: v._ws.append(self)
                r[k] = _font(v)
            elif k in ("image", "selectimage"):
                im = v if isinstance(v, PhotoImage) else next((i for i in _IMGS.values() if i.name == v), None)
                r[k] = im._id if im else 0
            elif k == "menu":
                if isinstance(v, Menu):
                    v._attach(self); self._menu = v
                    if self._type in ("root", "top"): continue
                    r["menu"] = v._id
            elif k == "value" and self._type == "progress": r["val"] = v; self._val = v
            elif k in ("validatecommand", "invalidcommand", "validate"):
                if k == "validate": r[k] = v
                else:
                    if k == "validatecommand": self._setvc(v)
                    else: self._ivc = v
            elif k == "text" and self._type != "lframe" and not isinstance(v, str): r[k] = str(v)
            elif k in _SKIP or v is None: pass
            elif isinstance(v, (int, float, str, bool)): r[k] = v
            elif isinstance(v, (list, tuple)): r[k] = [x if isinstance(x, (int, float, str, bool)) else str(x) for x in v]
            elif isinstance(v, Misc): pass
            else: r[k] = str(v)
        if self._ttk:
            base = self._style_opts(); base.update(r); r = base; r["ttk"] = 1
        self._o.update(r)
        return r
    def config(self, cnf=None, **kw):
        if isinstance(cnf, str): return (self.cget(cnf),)
        o = dict(cnf or {}); o.update(kw)
        if not o: return {k: (k, k, k, v, v) for k, v in self._o.items()}
        self._pre(o); r = self._cl(o); self._oc(o); _send("cfg", self._id, r)
    configure = config
    def __setitem__(self, k, v): self.config(**{k: v})
    def __getitem__(self, k): return self.cget(k)
    def cget(self, k):
        k = _ALIAS.get(k, k)
        if k == "menu": return getattr(self, "_menu", "")
        if k == "text" and self._type in ("label", "button", "check", "radio") and self._var is not None and k not in self._o:
            return self._var._v
        return self._o.get(k, "")
    def keys(self): return list(self._o)
    # ---- geometry managers
    def _mg(self, op, name, keys, cnf, kw):
        o = dict(cnf or {}); o.update(kw)
        if "in_" in o: o["in"] = o.pop("in_")
        r = {k: (list(o[k]) if isinstance(o[k], (tuple, list)) else o[k]) for k in keys if k in o}
        if "expand" in r: r["expand"] = r["expand"] not in (0, False, "0", "no", "false", "", "off")
        for k in ("side", "fill", "anchor", "sticky"):
            if k in r: r[k] = str(r[k])
        self._geo = (name, dict(o)); _send(op, self._id, r)
    def pack(self, cnf=None, **kw): self._mg("pk", "pack", ("side", "fill", "expand", "anchor", "padx", "pady", "ipadx", "ipady"), cnf, kw)
    def grid(self, cnf=None, **kw): self._mg("gr", "grid", ("row", "column", "rowspan", "columnspan", "sticky", "padx", "pady", "ipadx", "ipady"), cnf, kw)
    def place(self, cnf=None, **kw): self._mg("pl", "place", ("x", "y", "relx", "rely", "width", "height", "relwidth", "relheight", "anchor"), cnf, kw)
    pack_configure = pack; grid_configure = grid; place_configure = place
    def pack_forget(self): self._geo = None; _send("fg", self._id)
    grid_forget = place_forget = forget = pack_forget
    def grid_remove(self): _send("fg", self._id)
    def _info(self, name):
        if self._geo and self._geo[0] == name: return dict(self._geo[1])
        return {}
    def pack_info(self): return self._info("pack")
    def grid_info(self): return self._info("grid")
    def place_info(self): return self._info("place")
    info = pack_info
    def _slaves(self, name): return [k for k in self._kids if k._geo and k._geo[0] == name]
    def pack_slaves(self): return self._slaves("pack")
    def grid_slaves(self, row=None, column=None):
        r = self._slaves("grid")
        if row is not None: r = [k for k in r if int(k._geo[1].get("row", 0)) == row]
        if column is not None: r = [k for k in r if int(k._geo[1].get("column", 0)) == column]
        return r
    def place_slaves(self): return self._slaves("place")
    slaves = pack_slaves
    def grid_size(self):
        g = [k._geo[1] for k in self._slaves("grid")]
        return (max([int(x.get("column", 0)) + int(x.get("columnspan", 1)) for x in g] or [0]),
                max([int(x.get("row", 0)) + int(x.get("rowspan", 1)) for x in g] or [0]))
    size = grid_size
    def grid_bbox(self, *a): return (0, 0, 0, 0)
    def grid_location(self, x, y): return (0, 0)
    def pack_propagate(self, flag=None):
        if flag is None: return self._o.get("prop", True)
        self._o["prop"] = bool(flag); _send("cfg", self._id, {"prop": bool(flag)})
    grid_propagate = propagate = pack_propagate
    def _cc(self, k, i, kw):
        for x in (i if isinstance(i, (list, tuple)) else [i]):
            _send("cc", self._id, k, 0 if x == "all" else int(x), kw.get("weight", 0) or 0, kw.get("minsize", 0) or 0, str(x) == "all")
    def columnconfigure(self, i, cnf=None, **kw): self._cc("c", i, dict(cnf or {}, **kw))
    def rowconfigure(self, i, cnf=None, **kw): self._cc("r", i, dict(cnf or {}, **kw))
    grid_columnconfigure = columnconfigure; grid_rowconfigure = rowconfigure
    # ---- misc
    def destroy(self):
        for k in list(self._kids): k.destroy()
        if self.master and self in self.master._kids: self.master._kids.remove(self)
        if self.master: self.master.children.pop(self._name, None)
        _fireb(self, {"cat": "destroy"})
        _W.pop(self._id, None); _send("del", self._id)
        if self._type == "root": _st["quit"] = True
    def focus_set(self): _send("foc", self._id)
    focus = focus_force = focus_set
    def focus_get(self): return _W.get(_st["focus"])
    focus_displayof = focus_lastfor = focus_get
    def tk_focusNext(self): return self
    tk_focusPrev = tk_focusNext
    def bind(self, seq=None, func=None, add=None):
        if func is None: return "\n".join(str(f) for f in self._binds.get(seq, [])) or None
        lst = self._binds.setdefault(seq, [])
        if add in ("+", True, 1, "1"): lst.append(func)
        else: lst[:] = [func]
        c = _parse(seq)[0]
        if not c.startswith("v:"): _send("bind", self._id, c)
        return _reg_cmd(func)
    def bind_all(self, seq, func=None, add=None): return (_st["root"] or self).bind(seq, func, add)
    def bind_class(self, cls, seq, func=None, add=None):
        name = cls if isinstance(cls, str) else cls.__name__
        def g(e):
            try:
                if e.widget.winfo_class() == name: return func(e)
            except Exception: pass
        return (_st["root"] or self).bind(seq, g, "+")
    def unbind(self, seq, funcid=None): self._binds.pop(seq, None)
    unbind_all = unbind_class = lambda self, *a: None
    def event_add(self, v, *seqs): pass
    event_delete = event_info = _nop
    def event_generate(self, seq, **kw):
        c, det, mods = _parse(seq)
        e = {"cat": c, "k": det or kw.get("keysym", ""), "m": list(mods), "x": kw.get("x", 0), "y": kw.get("y", 0),
             "c": kw.get("char", ""), "wid": self._id}
        _fireb(self, e)
    def after(self, ms, func=None, *args):
        if func is None: time.sleep(ms / 1000.0); return None
        _st["aid"] += 1; i = "after#%d" % _st["aid"]
        _after.append((time.time() + ms / 1000.0, i, func, args)); return i
    def after_idle(self, func, *args): return self.after(0, func, *args)
    def after_cancel(self, i):
        for a in list(_after):
            if a[1] == i: _after.remove(a)
    def update(self): _pump(0)
    def update_idletasks(self): _flush()
    def mainloop(self, n=0): _mainloop()
    def quit(self): _st["quit"] = True
    def wait_window(self, w=None):
        w = w or self
        while w._id in _W and not _st["quit"]: _pump(0.05)
    def wait_variable(self, v):
        old = v._v
        while v._v == old and not _st["quit"]: _pump(0.05)
    waitvar = wait_variable
    def wait_visibility(self, w=None): _flush()
    def winfo_children(self): return list(self._kids)
    def winfo_class(self): return type(self).__name__ if self._type != "root" else "Tk"
    def winfo_name(self): return self._name.lstrip("!") if self._name != "." else "tk"
    def winfo_parent(self): return str(self.master) if self.master else ""
    def winfo_id(self): return self._id
    def winfo_toplevel(self):
        w = self
        while w.master is not None and w._type not in ("top", "root"): w = w.master
        return w
    def winfo_exists(self): return 1 if self._id in _W else 0
    def winfo_ismapped(self): return 1 if self._id in _W else 0
    winfo_viewable = winfo_ismapped
    def winfo_manager(self): return self._geo[0] if self._geo else ""
    def _g(self): return _query("geo", self._id, default=[0, 0, _st["w"], _st["h"], 0, 0, 1, 1])
    def winfo_width(self): return int(self._g()[2])
    def winfo_height(self): return int(self._g()[3])
    def winfo_x(self): return int(self._g()[0])
    def winfo_y(self): return int(self._g()[1])
    def winfo_rootx(self): return int(self._g()[4])
    def winfo_rooty(self): return int(self._g()[5])
    def winfo_reqwidth(self): return int(self._g()[6])
    def winfo_reqheight(self): return int(self._g()[7])
    def winfo_screenwidth(self): return _st["w"]
    def winfo_screenheight(self): return _st["h"]
    winfo_vrootwidth = winfo_screenmmwidth = winfo_screenwidth
    winfo_vrootheight = winfo_screenmmheight = winfo_screenheight
    def winfo_pointerxy(self):
        r = _query("ptr", default=[0, 0]); return (int(r[0]), int(r[1]))
    def winfo_pointerx(self): return self.winfo_pointerxy()[0]
    def winfo_pointery(self): return self.winfo_pointerxy()[1]
    def winfo_containing(self, x, y, displayof=0):
        r = _query("at", int(x), int(y), default=0); return _W.get(r)
    def winfo_depth(self): return 24
    def winfo_rgb(self, c):
        r = _query("rgb", str(c), default=[0, 0, 0]); return tuple(int(x) * 257 for x in r)
    def winfo_fpixels(self, n): return float(str(n).rstrip("cmipx") or 0)
    def winfo_pixels(self, n): return int(self.winfo_fpixels(n))
    def winfo_geometry(self): g = self._g(); return "%dx%d+%d+%d" % (g[2], g[3], g[0], g[1])
    def winfo_atom(self, n): return 0
    def winfo_interps(self): return ()
    def bindtags(self, tagList=None): return (str(self), self.winfo_class(), str(self.winfo_toplevel()), "all") if tagList is None else None
    def getboolean(self, s): return getboolean(s)
    def getdouble(self, s): return float(s)
    def getint(self, s): return int(s)
    grid_anchor = send = tk_focusFollowsMouse = _nop
    def winfo_pathname(self, id, displayof=0): return str(_W.get(id, self))
    def winfo_atomname(self, i): return ""
    def winfo_cells(self): return 256
    winfo_screencells = winfo_cells
    def winfo_colormapfull(self): return 0
    def winfo_screen(self): return ":0.0"
    def winfo_screendepth(self): return 24
    def winfo_screenvisual(self): return "truecolor"
    winfo_visual = winfo_screenvisual
    def winfo_server(self): return ""
    def winfo_visualid(self): return "0x21"
    def winfo_visualsavailable(self, includeids=False): return []
    def winfo_vrootx(self): return 0
    winfo_vrooty = winfo_vrootx
    def nametowidget(self, name):
        if isinstance(name, Misc): return name
        n = str(name)
        if n in (".", ""): return _st["root"]
        for w in _W.values():
            if str(w) == n: return w
        raise KeyError(name)
    def register(self, func, subst=None, needcleanup=1): return _reg_cmd(func)
    def getvar(self, name="PYTHON_VAR"): return ""
    setvar = _nop
    def clipboard_clear(self, **k): _clip[0] = ""
    def clipboard_append(self, s, **k): _clip[0] += str(s); _send("clip", _clip[0])
    def clipboard_get(self, **k): return _clip[0]
    def selection_get(self, **k):
        if hasattr(self, "_cur") and hasattr(self, "_val"):
            a, b = sorted(self._cur[:2])
            if a != b: return self._val[a:b]
        return _clip[0]
    selection_clear = selection_own = selection_handle = selection_own_get = _nop
    def bell(self, *a): pass
    def option_add(self, *a, **k): pass
    option_get = option_clear = option_readfile = tk_setPalette = tk_strictMotif = tk_bisque = _nop
    def image_names(self): return image_names()
    def image_types(self): return image_types()
    def lift(self, above=None): _send("raise", self._id)
    tkraise = lift
    def lower(self, below=None): _send("lower", self._id)
    grab_set = grab_set_global = grab_release = grab_current = grab_status = _nop
    def _vset(self, v):
        self._val = v
        if self._var is not None:
            self._var._v = v
            for w in list(self._var._ws):
                if w is not self: w._vupd(v)
            self._var._fire("write")
    def _vupd(self, v):
        t = self._type
        if t == "check": self._val = v; _send("cfg", self._id, {"chk": v == self._on})
        elif t == "radio": self._val = v; _send("cfg", self._id, {"chk": str(v) == str(self._rv)})
        elif t in ("entry", "scale", "spin", "combo", "progress"): self._val = v; _send("cfg", self._id, {"val": v})
        else: _send("cfg", self._id, {"tv": v})
    def _evval(self, e):
        t = self._type; v = e.get("v")
        if t == "check": v = self._on if v else self._off
        elif t == "radio": v = self._rv
        elif t == "scale": v = float(v)
        self._vset(v)
        if t == "scale" and self._cmd: _cb(self._cmd, str(int(v)) if v == int(v) else str(v))
    def _invoke(self):
        if self._cmd: return _cb(self._cmd)
    def _close(self):
        f = self._proto.get("WM_DELETE_WINDOW")
        if f: _cb(f)
        else: self.destroy()
    def _vcheck(self, new, old, mode):
        """entry validation: returns False when the change must be reverted"""
        if not self._vc or self._o.get("validate", "none") not in (mode, "all"): return True
        f, subs = self._vc
        d = 1 if len(new) > len(old) else 0
        pr = 0
        while pr < min(len(old), len(new)) and old[pr] == new[pr]: pr += 1
        S = new[pr:len(new) - (len(old) - pr)] if d else old[pr:len(old) - (len(new) - pr)]
        mp = {"%d": str(d), "%i": str(pr), "%P": new, "%s": old, "%S": S, "%v": self._o.get("validate", "none"),
              "%V": "key" if mode == "key" else mode, "%W": str(self)}
        try: r = f(*[mp.get(x, x) for x in subs])
        except SystemExit: raise
        except BaseException as ex: runner.report_exc(ex); return True
        return str(r).lower() not in ("0", "false", "", "no", "off", "none") if not isinstance(r, bool) else r


def _fireb(w, e):
    """fire the bindings of widget w (and root bindings when w is not root) for event dict e"""
    _fire_one(w, e)
    if w is not _st["root"] and _st["root"] is not None and e.get("cat") not in ("destroy",): _fire_one(_st["root"], e)


_STATE = {"shift": 1, "control": 4, "alt": 8, "b1": 256, "b2": 512, "b3": 1024}


def _fire_one(w, e):
    cat = e.get("cat"); have = set(e.get("m", []))
    for seq, fs in list(w._binds.items()):
        c, det, mods = _parse(seq)
        ok = c == cat or (c in ("b4", "b5") and cat == "wheel" and (e.get("d", 0) > 0) == (c == "b4"))
        if not ok: continue
        if det:
            k = e.get("k", "")
            if not (det == k or ((("control" in mods) or len(det) == 1) and det.lower() == str(k).lower() and len(det) == 1 and det.islower())):
                continue
        if not mods <= have: continue
        tgt = _W.get(e.get("wid")) or w
        ev = Event(widget=tgt, x=e.get("x", 0), y=e.get("y", 0), char=e.get("c", ""), keysym=e.get("k", ""),
                   keycode=e.get("kc", 0), num=e.get("n", 1), delta=e.get("d", 0), x_root=e.get("rx", e.get("x", 0)),
                   y_root=e.get("ry", e.get("y", 0)), width=e.get("w", 0), height=e.get("h", 0),
                   state=sum(_STATE[m] for m in have if m in _STATE), type=cat, time=int(time.time() * 1000),
                   serial=0, keysym_num=0, focus=False, send_event=False)
        for f in list(fs):
            if _cb(f, ev) == "break": break


# ---------------- windows ----------------
class _Win:
    def _wmi(self): return self.__dict__.setdefault("_wm", {"title": "", "geo": None, "state": "normal"})
    def title(self, s=None):
        if s is None: return self._wmi()["title"]
        self._wmi()["title"] = str(s); _send("cfg", self._id, {"title": str(s)})
    wm_title = title
    def geometry(self, s=None):
        wm = self._wmi()
        if s is None or s == "":
            if wm["geo"]: return wm["geo"]
            g = self._g(); return "%dx%d+%d+%d" % (g[2], g[3], g[0], g[1])
        m = re.match(r"=?(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?", str(s))
        if m and self._type == "root": _send("win", {"geo": [int(m.group(1)), int(m.group(2))]})
        elif m and self._type == "top":
            g = [int(m.group(1)), int(m.group(2))]
            if m.group(3) is not None: g += [int(m.group(3)), int(m.group(4))]
            _send("cfg", self._id, {"tg": g})
        wm["geo"] = str(s)
    wm_geometry = geometry
    def protocol(self, name=None, func=None):
        if func is None: return self._proto.get(name, "")
        self._proto[name] = func
    wm_protocol = protocol
    def state(self, s=None):
        wm = self._wmi()
        if s is None: return wm["state"]
        wm["state"] = s
        if self._type == "top": _send("cfg", self._id, {"hid": s in ("withdrawn", "iconic")})
    wm_state = state
    def withdraw(self): self.state("withdrawn")
    def iconify(self): self.state("iconic")
    def deiconify(self): self.state("normal")
    def attributes(self, *a, **k):
        at = self._wmi().setdefault("attr", {"alpha": 1.0, "topmost": 0, "fullscreen": 0, "zoomed": 0, "disabled": 0, "toolwindow": 0})
        if not a and not k: return tuple(x for kv in at.items() for x in ("-" + kv[0], kv[1]))
        if len(a) == 1 and not k: return at.get(str(a[0]).lstrip("-"), 0)
        items = list(zip(a[::2], a[1::2])) + [("-" + x, y) for x, y in k.items()]
        for n, v in items:
            n = str(n).lstrip("-"); at[n] = v
            if n == "alpha":
                try: _send("cfg", self._id, {"alpha": float(v)})
                except (TypeError, ValueError): pass
    wm_attributes = attributes
    def resizable(self, w=None, h=None): return (1, 1)
    wm_resizable = resizable
    def minsize(self, w=None, h=None): return (1, 1)
    maxsize = wm_minsize = wm_maxsize = minsize
    iconbitmap = iconphoto = wm_iconbitmap = wm_iconphoto = overrideredirect = transient = _nop
    wm_overrideredirect = wm_transient = iconname = wm_iconname = group = wm_group = aspect = _nop
    frame = lambda self: "0x0"
    focusmodel = positionfrom = sizefrom = wm_focusmodel = _nop
    def iconposition(self, *a): return None
    client = colormapwindows = command = iconmask = iconwindow = manage = _nop
    wm_aspect = wm_client = wm_command = wm_frame = wm_grid = wm_iconmask = wm_iconposition = wm_iconwindow = wm_manage = _nop
    wm_positionfrom = wm_sizefrom = _nop
    def wm_withdraw(self): self.state("withdrawn")
    def wm_iconify(self): self.state("iconic")
    def wm_deiconify(self): self.state("normal")


class Tk(_Win, Misc):
    _type = "root"
    def __init__(self, screenName=None, baseName=None, className="Tk", useTk=True, sync=False, use=None):
        Misc.__init__(self, None)
        self.tk = _TkObj()
    def report_callback_exception(self, exc, val, tb): runner.report_exc(val)
    def loadtk(self): pass
    def readprofile(self, *a): pass
    def __getattr__(self, n):
        if n.startswith("__") or n.startswith("_"): raise AttributeError(n)
        raise AttributeError("'Tk' object has no attribute '%s'" % n)


class Toplevel(_Win, Misc):
    _type = "top"


Tcl = lambda *a, **k: _TkObj()


class Frame(Misc): _type = "frame"
class LabelFrame(Misc): _type = "lframe"
Labelframe = LabelFrame
class Label(Misc): _type = "label"
class Message(Label): pass


class Button(Misc):
    _type = "button"
    def invoke(self): return self._invoke()
    flash = _nop


class _Scr:
    def yview(self, *a):
        if not a: return tuple(_query("scv", self._id, "y", default=[0.0, 1.0]))
        _send("scr", self._id, "y", [x if isinstance(x, (int, float)) else str(x) for x in a])
    def xview(self, *a):
        if not a: return tuple(_query("scv", self._id, "x", default=[0.0, 1.0]))
        _send("scr", self._id, "x", [x if isinstance(x, (int, float)) else str(x) for x in a])
    def yview_moveto(self, f): _send("scr", self._id, "y", ["moveto", float(f)])
    def yview_scroll(self, n, w): _send("scr", self._id, "y", ["scroll", int(n), str(w)])
    def xview_moveto(self, f): _send("scr", self._id, "x", ["moveto", float(f)])
    def xview_scroll(self, n, w): _send("scr", self._id, "x", ["scroll", int(n), str(w)])
    scan_mark = scan_dragto = _nop


class Scrollbar(Misc):
    _type = "scroll"
    def _pre(self, o): Misc._pre(self, o); self._sv = (0.0, 1.0)
    def set(self, first, last):
        self._sv = (float(first), float(last)); _send("cfg", self._id, {"sbv": [float(first), float(last)]})
    def get(self): return self._sv
    activate = identify = _nop
    def delta(self, dx, dy): return 0.0
    def fraction(self, x, y): return 0.0


class Entry(_Scr, Misc):
    _type = "entry"
    def _pre(self, o): Misc._pre(self, o); self._cur = [0, 0]; self._ivc = None
    def _wr(self): return self._o.get("state", "normal") not in ("disabled", "readonly")
    def get(self): return str(self._val)
    def _set(self, s):
        self._vset(s); _send("cfg", self._id, {"val": s})
    def _ei(self, i):
        v = str(self._val); s = str(i)
        if s == "end": return len(v)
        if s == "insert": return self._cur[1]
        if s == "anchor": return self._cur[0]
        if s == "sel.first": return min(self._cur)
        if s == "sel.last": return max(self._cur)
        if s.startswith("@"): return len(v)
        try: return max(0, min(len(v), int(s)))
        except Exception: return len(v)
    def _selr(self, a, b): self._cur = [a, b]; _send("selr", self._id, a, b)
    def insert(self, i, s):
        if not self._wr(): return
        v = str(self._val); p = self._ei(i); s = str(s)
        self._set(v[:p] + s + v[p:]); self._selr(p + len(s), p + len(s))
    def delete(self, a, b=None):
        if not self._wr(): return
        v = str(self._val); p = self._ei(a); q = p + 1 if b is None else self._ei(b)
        if q > p: self._set(v[:p] + v[q:]); self._selr(p, p)
    def icursor(self, i): p = self._ei(i); self._selr(p, p)
    def index(self, i): return self._ei(i)
    def selection_range(self, a, b): self._selr(self._ei(a), self._ei(b))
    select_range = selection_range
    def selection_clear(self): p = self._cur[1]; self._selr(p, p)
    select_clear = selection_clear
    def selection_present(self): return self._cur[0] != self._cur[1]
    select_present = selection_present
    selection_adjust = select_adjust = selection_from = select_from = selection_to = select_to = _nop
    def bbox(self, i): return (0, 0, 8, 16)
    def validate(self): return True
    def xview(self, *a): return (0.0, 1.0)
    def _evval(self, e):
        v = str(e.get("v", "")); old = str(self._val); prev = list(self._cur)
        self._cur = [e.get("a", 0), e.get("b", 0)]
        if not self._vcheck(v, old, "key"):
            _send("cfg", self._id, {"val": old}); self._selr(*prev)
            if self._ivc: _cb(self._ivc)
            return
        self._vset(v)
    def _blur(self):
        if not self._vcheck(str(self._val), str(self._val), "focusout") and self._ivc: _cb(self._ivc)


class Spinbox(Entry):
    _type = "spin"
    def _pre(self, o):
        Entry._pre(self, o)
        vs = list(o.get("values", []) or [])
        if vs: self._val = str(vs[0])
        elif "from_" in o: self._val = str(o["from_"])
    def _post(self, o):
        if self._var is None and self._val != "": _send("cfg", self._id, {"val": self._val})
    def set(self, v): self._set(str(v))
    identify = lambda self, x, y: ""
    scan = selection_element = _nop
    def invoke(self, el):
        vs = [str(x) for x in (self._o.get("values") or [])]; d = 1 if el == "buttonup" else -1
        if vs:
            i = vs.index(str(self._val)) if str(self._val) in vs else 0
            self._set(vs[(i + d) % len(vs)] if self._o.get("wrap") else vs[max(0, min(len(vs) - 1, i + d))])
        else:
            try:
                inc = float(self._o.get("increment", 1)); v = float(self._val or 0) + d * inc
                lo = float(self._o.get("from_", -1e18)); hi = float(self._o.get("to", 1e18))
                v = max(lo, min(hi, v)); self._set(str(int(v)) if v == int(v) and inc == int(inc) else str(v))
            except Exception: pass
        self._invoke()
    def _evval(self, e): Entry._evval(self, e)


class Checkbutton(Misc):
    _type = "check"
    def _setchk(self, on): self._vset(self._on if on else self._off); _send("cfg", self._id, {"chk": bool(on)})
    def select(self): self._setchk(True)
    def deselect(self): self._setchk(False)
    def toggle(self): self._setchk(self._val != self._on)
    def invoke(self): self.toggle(); return self._invoke()
    flash = _nop


class Radiobutton(Misc):
    _type = "radio"
    def select(self): self._vset(self._rv); _send("cfg", self._id, {"chk": True})
    def deselect(self): _send("cfg", self._id, {"chk": False})
    def invoke(self): self.select(); return self._invoke()
    flash = _nop


class Scale(Misc):
    _type = "scale"
    def _pre(self, o):
        Misc._pre(self, o); self._val = o.get("from_", 0); self._res = o.get("resolution", 1)
    def get(self):
        v = float(self._val)
        return int(v) if v == int(v) and float(self._res) >= 1 else v
    def set(self, v):
        self._vset(v); _send("cfg", self._id, {"val": v})
        if self._cmd: _cb(self._cmd, str(int(float(v))) if float(v) == int(float(v)) else str(v))
    coords = lambda self, v=None: (0, 0)
    identify = lambda self, x, y: ""


class Listbox(_Scr, Misc):
    _type = "list"
    def _pre(self, o): Misc._pre(self, o); self._items = []; self._sel = []; self._act = 0; self._ic = {}
    def _li(self, i):
        s = str(i); n = len(self._items)
        if s == "end": return n
        if s in ("active", "anchor"): return self._act
        if s.startswith("@"):
            try: return int(_query("lnear", self._id, int(s[1:].split(",")[1]), default=0))
            except Exception: return 0
        try: return int(s)
        except Exception: return n
    def _le(self, i): return max(0, min(self._li(i), len(self._items) - 1))
    def _push(self):
        _send("items", self._id, self._items)
        if self._var is not None: self._var._v = tuple(self._items)
    def _vupd(self, v): self._items = [str(x) for x in _tkl(v)]; self._sel = []; _send("items", self._id, self._items)
    def insert(self, i, *items):
        p = max(0, min(self._li(i), len(self._items))); self._items[p:p] = [str(x) for x in items]; self._sel = []; self._push()
    def delete(self, a, b=None):
        n = len(self._items); p = self._li(a)
        q = p + 1 if b is None else (n if str(b) == "end" else self._li(b) + 1)
        del self._items[max(0, p):max(0, q)]; self._sel = []; self._push()
    def get(self, a, b=None):
        if b is None:
            try: return self._items[self._le(a)]
            except IndexError: return ""
        q = len(self._items) if str(b) == "end" else self._li(b) + 1
        return tuple(self._items[self._li(a):q])
    def curselection(self): return tuple(self._sel)
    def size(self): return len(self._items)
    def index(self, i): return self._li(i)
    def selection_set(self, a, b=None):
        p = self._le(a); q = p if b is None else self._le(b)
        if self._o.get("selectmode") in ("single", "browse", None, ""): self._sel = [q]
        else: self._sel = sorted(set(self._sel) | set(range(min(p, q), max(p, q) + 1)))
        _send("lsel", self._id, self._sel)
    select_set = selection_set
    def selection_clear(self, a=0, b=None):
        p = self._li(a) if str(a) != "0" or True else 0; q = p if b is None else (len(self._items) if str(b) == "end" else self._li(b))
        self._sel = [i for i in self._sel if not (min(p, q) <= i <= max(p, q))]; _send("lsel", self._id, self._sel)
    select_clear = selection_clear
    def selection_includes(self, i): return self._li(i) in self._sel
    select_includes = selection_includes
    def selection_anchor(self, i): self._act = self._le(i)
    select_anchor = selection_anchor
    def activate(self, i): self._act = self._le(i)
    def see(self, i): _send("lsee", self._id, self._le(i))
    def nearest(self, y): return int(_query("lnear", self._id, y, default=0))
    def itemconfig(self, i, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); n = self._le(i)
        if not o: return dict(self._ic.get(n, {}))
        o = {_ALIAS.get(k, k): v for k, v in o.items()}; self._ic.setdefault(n, {}).update(o); _send("litem", self._id, n, o)
    itemconfigure = itemconfig
    def itemcget(self, i, k): return self._ic.get(self._le(i), {}).get(_ALIAS.get(k, k), "")
    def bbox(self, i): return (0, 0, 10, 16)


# ---------------- Text ----------------
def _tstyle(cfg):
    d = {}
    for k, v in cfg.items():
        k = _ALIAS.get(k, k)
        if k in ("fg", "bg"): d[k] = str(v)
        elif k == "font": d["font"] = _font(v)
        elif k == "underline": d["u"] = bool(v)
        elif k == "overstrike": d["o"] = bool(v)
        elif k == "elide": d["hide"] = bool(v)
    return d


class Text(_Scr, Misc):
    _type = "text"
    def _pre(self, o):
        Misc._pre(self, o)
        self._tg = {}; self._mk = {}; self._cur = [0, 0]; self._tp = 0; self._tbind = {}; self._mod = False; self._lc = None
        self._embs = []; self._ec = 0; self._hadembs = False
    def _s(self): return self._val + "\n"
    def _wr(self): return self._o.get("state", "normal") != "disabled"
    def _lcof(self, off):
        s = self._s(); off = max(0, min(len(s), off)); return s.count("\n", 0, off) + 1, off - (s.rfind("\n", 0, off) + 1)
    def _i2s(self, off): l, c = self._lcof(off); return "%d.%d" % (l, c)
    def _lineoff(self, ln, col):
        lines = self._s().split("\n"); ln = max(1, min(ln, len(lines)))
        return sum(len(x) + 1 for x in lines[:ln - 1]) + min(col if col is not None else 0, len(lines[ln - 1]))
    def _ix(self, i):
        s = self._s(); L = len(s); i = str(i).strip()
        m = re.match(r"(@-?\d+,-?\d+|[^\s+\-]+)(.*)$", i)
        if not m: raise TclError('bad text index "%s"' % i)
        b, rest = m.group(1), m.group(2).strip()
        mt = re.match(r"^(.+)\.(first|last)$", b)
        if b == "end": off = L
        elif b == "insert": off = self._cur[1]
        elif b == "current": off = self._lc if self._lc is not None else self._cur[1]
        elif b == "anchor": off = self._cur[0]
        elif b.startswith("@"):
            try: xx, yy = b[1:].split(","); r = _query("tidx", self._id, int(xx), int(yy), default=None)
            except Exception: r = None
            off = int(r) if r is not None else (self._lc if self._lc is not None else self._cur[1])
        elif b in ("sel.first", "sel.last"):
            a, bb = sorted(self._cur)
            if a == bb: raise TclError('text doesn\'t contain any characters tagged with "sel"')
            off = a if b == "sel.first" else bb
        elif re.match(r"^\d+\.(\d+|end)$", b):
            l, c = b.split("."); lines = s.split("\n"); l = max(1, int(l))
            if l > len(lines): off = L
            else:
                ll = len(lines[l - 1]); off = sum(len(x) + 1 for x in lines[:l - 1]) + (ll if c == "end" else min(int(c), ll))
        elif b in self._mk: off = self._mk[b][0]
        elif mt and mt.group(1) in self._tg and self._tg[mt.group(1)]["rg"]:
            rg = self._tg[mt.group(1)]["rg"]; off = rg[0][0] if mt.group(2) == "first" else rg[-1][1]
        else: raise TclError('bad text index "%s"' % i)
        while rest:
            m = re.match(r"([+-])\s*(\d+)\s*(display\s+)?(chars?|c|indices|any|lines?|l)?\s*(.*)$", rest)
            if m:
                sg = 1 if m.group(1) == "+" else -1; n = int(m.group(2)); u = (m.group(4) or "c")[0]
                if u == "l":
                    ln, col = self._lcof(off); off = self._lineoff(ln + sg * n, col)
                else: off = max(0, min(L, off + sg * n))
                rest = m.group(5).strip(); continue
            m = re.match(r"(display\s+)?(linestart|lineend|wordstart|wordend)\s*(.*)$", rest)
            if not m: raise TclError('bad text index "%s"' % i)
            k = m.group(2); ln, col = self._lcof(off)
            if k == "linestart": off = self._lineoff(ln, 0)
            elif k == "lineend": off = self._lineoff(ln, 10 ** 9)
            else:
                t = self._s()
                if k == "wordstart":
                    while off > 0 and (t[off - 1].isalnum() or t[off - 1] == "_"): off -= 1
                else:
                    while off < L - 1 and (t[off].isalnum() or t[off] == "_"): off += 1
            rest = m.group(3).strip()
        return max(0, min(L, off))
    # ---- model updates
    def _tag(self, name):
        t = self._tg.get(name)
        if t is None: self._tp += 1; t = self._tg[name] = {"cfg": {}, "rg": [], "n": self._tp}
        return t
    @staticmethod
    def _norm(rg):
        rg = sorted([list(r) for r in rg if r[1] > r[0]]); out = []
        for s, e in rg:
            if out and s <= out[-1][1]: out[-1][1] = max(out[-1][1], e)
            else: out.append([s, e])
        return out
    def _shift_ins(self, p, n, explicit):
        for t in self._tg.values():
            nr = []
            for s, e in t["rg"]:
                if e <= p: nr.append([s, e])
                elif s >= p: nr.append([s + n, e + n])
                elif explicit: nr += [[s, p], [p + n, e + n]]
                else: nr.append([s, e + n])
            t["rg"] = nr
        for m in self._mk.values():
            if m[0] > p or (m[0] == p and m[1] == "right"): m[0] += n
        _mark(self)
    def _shift_del(self, a, b):
        d = b - a
        f = lambda x: x if x <= a else (a if x < b else x - d)
        for t in self._tg.values(): t["rg"] = self._norm([[f(s), f(e)] for s, e in t["rg"]])
        for m in self._mk.values(): m[0] = f(m[0])
        self._cur = [f(self._cur[0]), f(self._cur[1])]
        _mark(self)
    def _pushv(self):
        _send("cfg", self._id, {"val": self._val}); _send("selr", self._id, self._cur[0], self._cur[1]); _mark(self)
    def _sync(self):
        cfg = {n: _tstyle(t["cfg"]) for n, t in self._tg.items()}
        vis = [n for n, st in cfg.items() if st]
        rg = [[s, e, n] for n in vis for s, e in self._tg[n]["rg"]]
        _send("ttag", self._id, {"rg": rg, "cfg": {n: cfg[n] for n in vis}, "ord": sorted(vis, key=lambda n: self._tg[n]["n"])})
        if self._embs or self._hadembs:
            pos = [i for i, ch in enumerate(self._val) if ch == "\ufffc"]
            es = sorted(enumerate(self._embs), key=lambda x: (self._mk.get(x[1]["m"], [0])[0], x[0]))
            es = [e for _, e in es][:len(pos)]
            lst = []
            for e in es:
                if e["kind"] == "win" and e["w"] is not None: lst.append({"k": "win", "id": e["w"]._id})
                elif e["kind"] == "img" and e["img"] is not None: lst.append({"k": "img", "id": e["img"]._id})
                else: lst.append({"k": "img", "id": 0})
            self._hadembs = bool(lst); _send("temb", self._id, lst)
    # ---- public API
    def get(self, a="1.0", b=None):
        s = self._s(); p = self._ix(a); q = self._ix(b) if b is not None else p + 1
        return s[p:q].replace("\ufffc", "")
    def insert(self, index, chars, *args):
        if not self._wr(): return
        p = min(self._ix(index), len(self._val)); items = [chars] + list(args); j = 0
        while j < len(items):
            txt = str(items[j]); tg = items[j + 1] if j + 1 < len(items) else None
            if isinstance(tg, str): tg = (tg,)
            self._ins(p, txt, tuple(tg) if tg is not None else None); p += len(txt); j += 2
        self._pushv()
    def _ins(self, p, txt, tg):
        n = len(txt)
        if not n: return
        self._val = self._val[:p] + txt + self._val[p:]
        self._shift_ins(p, n, tg is not None)
        for k in (0, 1):
            if self._cur[k] >= p: self._cur[k] += n
        for t in tg or (): t = self._tag(t); t["rg"] = self._norm(t["rg"] + [[p, p + n]])
    def delete(self, a, b=None):
        if not self._wr(): return
        p = self._ix(a); q = self._ix(b) if b is not None else p + 1
        p = min(p, len(self._val)); q = min(q, len(self._val))
        if q <= p: return
        self._val = self._val[:p] + self._val[q:]; self._shift_del(p, q); self._pushv()
    def replace(self, a, b, chars, *tags):
        p = self._ix(a); self.delete(a, b); self.insert(self._i2s(p), chars, *tags)
    def index(self, i): return self._i2s(self._ix(i))
    def compare(self, a, op, b):
        x, y = self._ix(a), self._ix(b)
        return {"<": x < y, "<=": x <= y, "==": x == y, ">=": x >= y, ">": x > y, "!=": x != y}[op]
    def count(self, a, b, *opts):
        p, q = self._ix(a), self._ix(b); o = [str(x).lstrip("-") for x in opts] or ["chars"]
        r = []
        for k in o:
            if k.startswith("line"): r.append(self._lcof(q)[0] - self._lcof(p)[0])
            else: r.append(q - p)
        return tuple(r) if len(r) > 1 else (r[0],)
    def see(self, i): _send("tsee", self._id, self._ix(i))
    def search(self, pattern, index, stopindex=None, forwards=None, backwards=None, exact=None, regexp=None,
               nocase=None, count=None, elide=None):
        s = self._s(); p = self._ix(index); stop = self._ix(stopindex) if stopindex else None
        rx = re.compile(pattern if regexp else re.escape(pattern), re.I if nocase else 0)
        found = None
        if backwards:
            lo = stop if stop is not None else 0
            for m in rx.finditer(s, lo, p + (0 if not regexp else 0)):
                if m.end() <= p or m.start() < p: found = m
        else:
            hi = stop if stop is not None else len(s)
            found = rx.search(s, p, hi)
            if found is None and stop is None and p > 0: found = rx.search(s, 0, p)
        if found is None: return ""
        if count is not None:
            try: count.set(found.end() - found.start())
            except Exception: pass
        return self._i2s(found.start())
    def mark_set(self, name, index):
        p = self._ix(index)
        if name == "insert": self._cur = [p, p]; _send("selr", self._id, p, p)
        elif name == "current": self._lc = p
        else: self._mk[name] = [p, self._mk.get(name, [0, "right"])[1]]
    def mark_unset(self, *names):
        for n in names: self._mk.pop(n, None)
    def mark_names(self): return ("insert", "current") + tuple(self._mk)
    def mark_gravity(self, name, g=None):
        m = self._mk.setdefault(name, [0, "right"])
        if g is None: return m[1]
        m[1] = g
    mark_next = mark_previous = lambda self, i: None
    # tags
    def tag_configure(self, name, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); t = self._tag(name)
        if not o: return dict(t["cfg"])
        t["cfg"].update({_ALIAS.get(k, k): v for k, v in o.items()}); _mark(self)
    tag_config = tag_configure
    def tag_cget(self, name, k): return self._tag(name)["cfg"].get(_ALIAS.get(k, k), "")
    def tag_add(self, name, a, *more):
        pts = [a] + list(more)
        if len(pts) % 2: pts.append(None)
        for j in range(0, len(pts), 2):
            p = self._ix(pts[j]); q = self._ix(pts[j + 1]) if pts[j + 1] is not None else p + 1
            if q < p: p, q = q, p
            if name == "sel": self._cur = [p, q]; _send("selr", self._id, p, q); continue
            t = self._tag(name); t["rg"] = self._norm(t["rg"] + [[p, min(q, len(self._val))]])
        _mark(self)
    def tag_remove(self, name, a, *more):
        pts = [a] + list(more)
        if len(pts) % 2: pts.append(None)
        for j in range(0, len(pts), 2):
            p = self._ix(pts[j]); q = self._ix(pts[j + 1]) if pts[j + 1] is not None else p + 1
            if name == "sel": c = self._cur[1]; self._cur = [c, c]; _send("selr", self._id, c, c); continue
            t = self._tg.get(name)
            if not t: continue
            nr = []
            for s, e in t["rg"]:
                if e <= p or s >= q: nr.append([s, e])
                else:
                    if s < p: nr.append([s, p])
                    if e > q: nr.append([q, e])
            t["rg"] = nr
        _mark(self)
    def tag_delete(self, *names):
        for n in names: self._tg.pop(n, None)
        _mark(self)
    def tag_names(self, index=None):
        if index is None: return tuple(["sel"] + list(self._tg))
        o = self._ix(index)
        return tuple(sorted([n for n, t in self._tg.items() if any(s <= o < e for s, e in t["rg"])], key=lambda n: self._tg[n]["n"]))
    def tag_ranges(self, name):
        if name == "sel":
            a, b = sorted(self._cur); return (self._i2s(a), self._i2s(b)) if a != b else ()
        t = self._tg.get(name)
        return tuple(self._i2s(x) for r in (t["rg"] if t else []) for x in r)
    def tag_nextrange(self, name, a, b=None):
        t = self._tg.get(name); p = self._ix(a); q = self._ix(b) if b else 10 ** 9
        for s, e in (t["rg"] if t else []):
            if e > p and s < q: return (self._i2s(max(s, p)), self._i2s(e))
        return ()
    def tag_prevrange(self, name, a, b=None):
        t = self._tg.get(name); p = self._ix(a); q = self._ix(b) if b else 0
        for s, e in reversed(t["rg"] if t else []):
            if s < p and e > q: return (self._i2s(s), self._i2s(min(e, p)))
        return ()
    def tag_raise(self, name, above=None):
        self._tp += 1; self._tag(name)["n"] = self._tp; _mark(self)
    def tag_lower(self, name, below=None):
        self._tag(name)["n"] = min([t["n"] for t in self._tg.values()] + [0]) - 1; _mark(self)
    def tag_has(self, name, index=None):
        t = self._tg.get(name)
        if index is None: return tuple(self.tag_ranges(name))
        o = self._ix(index); return bool(t and any(s <= o < e for s, e in t["rg"]))
    def tag_bind(self, name, seq=None, func=None, add=None):
        c = _parse(seq)[0]
        if func is not None:
            lst = self._tbind.setdefault((name, c), [])
            if add not in ("+", True): lst[:] = []
            lst.append(func); _send("bind", self._id, c)
        return seq
    tag_unbind = _nop
    def tag_ranges_all(self): return {n: t["rg"] for n, t in self._tg.items()}
    # misc
    def edit_modified(self, flag=None):
        if flag is None: return self._mod
        self._mod = bool(flag)
    def edit_undo(self): _send("undo", self._id, "undo")
    def edit_redo(self): _send("undo", self._id, "redo")
    edit_reset = edit_separator = _nop
    def edit(self, *a, **k):
        if a and a[0] == "modified": return self.edit_modified(*a[1:])
        if a and a[0] in ("undo", "redo"): _send("undo", self._id, a[0])
    def _embed(self, kind, index, w, img, o):
        p = min(self._ix(index), len(self._val)); self._ins(p, "\ufffc", None)
        self._ec += 1; name = "\x00e%d" % self._ec; self._mk[name] = [p, "right"]
        self._embs.append({"m": name, "kind": kind, "w": w, "img": img, "o": o}); self._pushv()
        return str(w) if w is not None else (img.name if img is not None else "")
    def window_create(self, index, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); w = o.get("window")
        if w is None and callable(o.get("create")): w = o["create"]()
        return self._embed("win", index, w, None, o)
    def image_create(self, index, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); im = o.get("image")
        if not isinstance(im, PhotoImage): im = next((i for i in _IMGS.values() if i.name == im), None)
        return self._embed("img", index, None, im, o)
    def window_names(self): return tuple(str(e["w"]) for e in self._embs if e["w"] is not None)
    def image_names(self): return tuple(e["img"].name for e in self._embs if e["img"] is not None)
    def window_cget(self, i, k): return ""
    image_cget = window_cget
    window_configure = image_configure = lambda self, *a, **k: None
    debug = _nop
    def yview_pickplace(self, *a): pass
    def dump(self, *a, **k): return []
    def dlineinfo(self, i): return (0, 0, 10, 16, 12)
    def bbox(self, i):
        r = _query("tbbox", self._id, self._ix(i), default=None); return tuple(r) if r else (0, 0, 8, 16)
    peer_create = peer_names = _nop
    def _evval(self, e):
        v = e.get("v", ""); old = self._val
        if v != old:
            pr = 0; m = min(len(old), len(v))
            while pr < m and old[pr] == v[pr]: pr += 1
            sf = 0
            while sf < m - pr and old[len(old) - 1 - sf] == v[len(v) - 1 - sf]: sf += 1
            rem = len(old) - pr - sf; ins = len(v) - pr - sf
            if rem > 0: self._shift_del(pr, pr + rem)
            if ins > 0: self._shift_ins(pr, ins, False)
            self._val = v
            if not self._mod:
                self._mod = True; _fireb(self, {"cat": "v:Modified", "wid": self._id})
        self._cur = [e.get("a", 0), e.get("b", 0)]
    def _tagfire(self, e):
        o = e.get("o")
        if o is None or not self._tbind: return
        for (name, c), fs in list(self._tbind.items()):
            if c != e.get("cat"): continue
            t = self._tg.get(name)
            if t and any(s <= o < en for s, en in t["rg"]):
                ev = Event(widget=self, x=e.get("x", 0), y=e.get("y", 0), char="", keysym="", num=e.get("n", 1), delta=0, type=c)
                for f in list(fs): _cb(f, ev)


class ScrolledText(Text):
    def __init__(self, master=None, **kw):
        kw.setdefault("wrap", "word"); Text.__init__(self, master, **kw)
        self.frame = self; self.vbar = None


# ---------------- Canvas ----------------
def _flatc(args):
    out = []
    for a in args:
        if isinstance(a, (list, tuple)): out += _flatc(a)
        else: out.append(float(a))
    return out


class Canvas(_Scr, Misc):
    _type = "canvas"
    def _pre(self, o):
        Misc._pre(self, o); self._it = {}; self._ord = []; self._nid = 0; self._tb = {}; self._ox = 0.0; self._oy = 0.0; self._hov = 0
    def _oc(self, o):
        sr = o.get("scrollregion")
        if sr:
            try: v = _tkl(sr); self._ox = float(v[0]); self._oy = float(v[1])
            except Exception: pass
    def _post(self, o): self._oc(o)
    def _conv(self, k, v):
        if k == "font": return _font(v)
        if k == "image":
            im = v if isinstance(v, PhotoImage) else next((i for i in _IMGS.values() if i.name == v), None)
            return im._id if im else 0
        if k == "window": return v._id
        if isinstance(v, (list, tuple)): return [x if isinstance(x, (int, float, str, bool)) else str(x) for x in v]
        return v if isinstance(v, (int, float, str, bool)) else str(v)
    def _add(self, kind, args, o):
        co = _flatc(args); self._nid += 1; i = self._nid
        raw = dict(o); tags = raw.pop("tags", ()); tags = [tags] if isinstance(tags, str) else list(tags)
        self._it[i] = {"k": kind, "c": co, "o": raw, "t": tags}; self._ord.append(i)
        _send("cv", self._id, "add", i, kind, co, {k: self._conv(k, v) for k, v in raw.items() if v is not None}); return i
    def create_line(self, *c, **o): return self._add("line", c, o)
    def create_rectangle(self, *c, **o): return self._add("rectangle", c, o)
    def create_oval(self, *c, **o): return self._add("oval", c, o)
    def create_polygon(self, *c, **o): return self._add("polygon", c, o)
    def create_text(self, *c, **o): return self._add("text", c, o)
    def create_arc(self, *c, **o): return self._add("arc", c, o)
    def create_image(self, *c, **o): return self._add("image", c, o)
    def create_window(self, *c, **o): return self._add("window", c, o)
    def create_bitmap(self, *c, **o): return self._add("rectangle", c + (0, 0), dict(o, state="hidden"))
    def _ids(self, t):
        if isinstance(t, (list, tuple)): return [i for x in t for i in self._ids(x)]
        if t == "all": return list(self._ord)
        if t == "current": return [self._hov] if self._hov in self._it else []
        if isinstance(t, int): return [t] if t in self._it else []
        s = str(t)
        if s.isdigit(): return [int(s)] if int(s) in self._it else []
        return [i for i in self._ord if s in self._it[i]["t"]]
    def _sz(self, it):
        k = it["k"]; o = it["o"]
        if k == "text":
            f = _font(o.get("font")) or {"s": 10}; px = abs(f["s"]) * (1 if f["s"] < 0 else 1.333); ls = str(o.get("text", "")).split("\n")
            return max(len(x) for x in ls) * px * 0.6, len(ls) * px * 1.25
        if k == "image":
            im = o.get("image"); im = im if isinstance(im, PhotoImage) else next((x for x in _IMGS.values() if x.name == im), None)
            return (im.width(), im.height()) if im else (0, 0)
        w = o.get("window")
        if w is not None:
            g = w._g(); return g[2], g[3]
        return 0, 0
    def _bb(self, i):
        it = self._it[i]; c = it["c"]; k = it["k"]
        if k in ("text", "image", "window"):
            x, y = c[0], c[1]; ww, hh = self._sz(it); a = str(it["o"].get("anchor", "center"))
            x0 = x if "w" in a else (x - ww if "e" in a else x - ww / 2); y0 = y if "n" in a else (y - hh if "s" in a else y - hh / 2)
            return [x0, y0, x0 + ww, y0 + hh]
        w = float(it["o"].get("width", 1) or 1) if k != "polygon" or it["o"].get("outline") else 0
        xs = c[0::2]; ys = c[1::2]
        return [min(xs) - w / 2, min(ys) - w / 2, max(xs) + w / 2, max(ys) + w / 2]
    def _ub(self, ids):
        bs = [self._bb(i) for i in ids]
        if not bs: return None
        return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]
    def bbox(self, *tags):
        ids = self._ids(list(tags) or ["all"])
        if not ids: return None
        r = _query("cvbb", self._id, ids, default=None)
        if not r: r = self._ub(ids)
        return tuple(int(round(x)) for x in r) if r else None
    def delete(self, *tags):
        ids = self._ids(list(tags))
        for i in ids:
            self._it.pop(i, None)
            if i in self._ord: self._ord.remove(i)
        _send("cv", self._id, "del", ids)
    def move(self, t, dx, dy):
        ids = self._ids(t)
        for i in ids:
            c = self._it[i]["c"]; self._it[i]["c"] = [v + (dx if j % 2 == 0 else dy) for j, v in enumerate(c)]
        _send("cv", self._id, "mv", ids, float(dx), float(dy))
    def moveto(self, t, x="", y=""):
        ids = self._ids(t); b = self._ub(ids)
        if b: self.move(t, (float(x) - b[0]) if x not in ("", None) else 0, (float(y) - b[1]) if y not in ("", None) else 0)
    def scale(self, t, xo, yo, xs, ys):
        for i in self._ids(t):
            c = self._it[i]["c"]
            self._it[i]["c"] = [(xo + (v - xo) * xs) if j % 2 == 0 else (yo + (v - yo) * ys) for j, v in enumerate(c)]
            _send("cv", self._id, "co", i, self._it[i]["c"])
    def coords(self, t, *c):
        ids = self._ids(t)
        if not ids: return []
        if not c: return list(self._it[ids[0]]["c"])
        self._it[ids[0]]["c"] = _flatc(c); _send("cv", self._id, "co", ids[0], self._it[ids[0]]["c"])
    def itemconfig(self, t, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); ids = self._ids(t)
        if not o: return {k: (k, "", "", "", v) for k, v in (self._it[ids[0]]["o"].items() if ids else [])}
        tg = o.pop("tags", None)
        for i in ids:
            self._it[i]["o"].update(o)
            if tg is not None: self._it[i]["t"] = [tg] if isinstance(tg, str) else list(tg)
        _send("cv", self._id, "ic", ids, {k: self._conv(k, v) for k, v in o.items() if v is not None})
    itemconfigure = itemconfig
    def itemcget(self, t, k):
        ids = self._ids(t)
        if not ids: return ""
        if k == "tags": return tuple(self._it[ids[0]]["t"])
        return self._it[ids[0]]["o"].get(k, "")
    def type(self, t):
        ids = self._ids(t); return self._it[ids[0]]["k"] if ids else None
    def gettags(self, t):
        ids = self._ids(t); return tuple(self._it[ids[0]]["t"]) if ids else ()
    def addtag_withtag(self, new, t):
        for i in self._ids(t):
            if new not in self._it[i]["t"]: self._it[i]["t"].append(new)
    def addtag_all(self, new): self.addtag_withtag(new, "all")
    def addtag(self, new, how, *a):
        if how == "withtag": self.addtag_withtag(new, *a)
        elif how == "all": self.addtag_all(new)
        elif how == "overlapping": self.addtag_overlapping(new, *a)
    def addtag_overlapping(self, new, x1, y1, x2, y2):
        for i in self.find_overlapping(x1, y1, x2, y2):
            if new not in self._it[i]["t"]: self._it[i]["t"].append(new)
    def addtag_enclosed(self, new, x1, y1, x2, y2):
        for i in self.find_enclosed(x1, y1, x2, y2):
            if new not in self._it[i]["t"]: self._it[i]["t"].append(new)
    def addtag_closest(self, new, x, y, halo=None, start=None):
        for i in self.find_closest(x, y):
            if new not in self._it[i]["t"]: self._it[i]["t"].append(new)
    def dtag(self, t, deltag=None):
        for i in self._ids(t):
            d = deltag if deltag is not None else t
            if d in self._it[i]["t"]: self._it[i]["t"].remove(d)
    def find(self, what, *a):
        f = getattr(self, "find_" + what, None)
        return f(*a) if f else ()
    def addtag_above(self, new, t):
        for i in self.find_above(t): self._it[i]["t"].append(new)
    def addtag_below(self, new, t):
        for i in self.find_below(t): self._it[i]["t"].append(new)
    select_item = _nop
    def find_all(self): return tuple(self._ord)
    def find_withtag(self, t): return tuple(self._ids(t))
    def find_overlapping(self, x1, y1, x2, y2):
        x1, x2 = sorted((x1, x2)); y1, y2 = sorted((y1, y2)); r = []
        for i in self._ord:
            if self._it[i]["o"].get("state") == "hidden": continue
            b = self._bb(i)
            if b[0] <= x2 and b[2] >= x1 and b[1] <= y2 and b[3] >= y1: r.append(i)
        return tuple(r)
    def find_enclosed(self, x1, y1, x2, y2):
        x1, x2 = sorted((x1, x2)); y1, y2 = sorted((y1, y2))
        return tuple(i for i in self._ord if (lambda b: b[0] >= x1 and b[2] <= x2 and b[1] >= y1 and b[3] <= y2)(self._bb(i)))
    def find_closest(self, x, y, halo=None, start=None):
        best = None; bd = 1e18
        for i in self._ord:
            b = self._bb(i); dx = max(b[0] - x, 0, x - b[2]); dy = max(b[1] - y, 0, y - b[3]); d = dx * dx + dy * dy
            if d <= bd: bd = d; best = i
        return (best,) if best else ()
    def find_above(self, t):
        ids = self._ids(t)
        if not ids: return ()
        k = self._ord.index(ids[-1]); return (self._ord[k + 1],) if k + 1 < len(self._ord) else ()
    def find_below(self, t):
        ids = self._ids(t)
        if not ids: return ()
        k = self._ord.index(ids[0]); return (self._ord[k - 1],) if k > 0 else ()
    def tag_raise(self, t, above=None):
        ids = self._ids(t)
        self._ord = [i for i in self._ord if i not in ids] + ids; _send("cv", self._id, "rz", list(self._ord))
    def tag_lower(self, t, below=None):
        ids = self._ids(t)
        self._ord = ids + [i for i in self._ord if i not in ids]; _send("cv", self._id, "rz", list(self._ord))
    lift = tkraise = tag_raise
    lower = tag_lower
    def tag_bind(self, t, seq=None, func=None, add=None):
        c = _parse(seq)[0]
        if func is not None:
            lst = self._tb.setdefault((t, c), [])
            if add not in ("+", True): lst[:] = []
            lst.append(func); _send("bind", self._id, {"enter": "ienter", "leave": "ileave"}.get(c, c))
        return seq
    tag_unbind = _nop
    def canvasx(self, x, gridspacing=None): return float(x) + self._ox
    def canvasy(self, y, gridspacing=None): return float(y) + self._oy
    def focus(self, *a): return ""
    def itemfocus(self, *a): return ""
    select_clear = select_from = select_to = select_adjust = icursor = dchars = insert = index = _nop
    def postscript(self, **k):
        r = _query("cvps", self._id, default=None, timeout=20)
        if not r: raise TclError("postscript: could not draw the canvas")
        w, h, hx = r["w"], r["h"], r["hex"]
        body = "\n".join(hx[i:i + 78] for i in range(0, len(hx), 78))
        ps = ("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 " + str(w) + " " + str(h) + "\n%%EndComments\ngsave\n" + str(w) + " " + str(h) +
              " scale\n/pix " + str(w * 3) + " string def\n" + str(w) + " " + str(h) + " 8 [" + str(w) + " 0 0 -" + str(h) + " 0 " + str(h) +
              "]\n{currentfile pix readhexstring pop}\nfalse 3 colorimage\n" + body + "\ngrestore\nshowpage\n%%EOF\n")
        f = k.get("file")
        if f:
            with open(f, "w") as fh: fh.write(ps)
            return ""
        return ps
    def _tagfire(self, e):
        cat = {"ienter": "enter", "ileave": "leave"}.get(e.get("cat"), e.get("cat")); it = e.get("it", 0)
        if not it or not self._tb: return
        for (t, c), fs in list(self._tb.items()):
            if c == cat and it in self._ids(t):
                ev = Event(widget=self, x=e.get("x", 0), y=e.get("y", 0), char="", keysym=e.get("k", ""), num=e.get("n", 1), delta=e.get("d", 0), type=c,
                           x_root=e.get("rx", 0), y_root=e.get("ry", 0))
                for f in list(fs): _cb(f, ev)


# ---------------- menus ----------------
class Menu(Misc):
    _type = "menu"
    def __init__(self, master=None, cnf=None, **kw):
        self._items = []; self._at = []; self._par = []
        Misc.__init__(self, master, cnf, **kw)
        tear = kw.get("tearoff", (cnf or {}).get("tearoff", 1))
        if tear: self._items.append({"t": "tearoff"})
    def _attach(self, w):
        if w not in self._at: self._at.append(w)
        self._touch()
    def _touch(self):
        _mark(self)
        for p in self._par: p._touch()
    def _vupd(self, v): self._touch()
    def _sync(self):
        tr = self._tree()
        for w in self._at:
            if w._id in _W: _send("mbar" if w._type in ("root", "top") else "mmenu", w._id, tr)
    def _tree(self, depth=0):
        its = []
        for i, d in enumerate(self._items):
            t = d["t"]
            if t == "tearoff": continue
            x = {"i": i, "t": {"checkbutton": "check", "radiobutton": "radio", "separator": "sep"}.get(t, t),
                 "label": str(d.get("label", "")), "acc": str(d.get("accelerator", "")), "st": d.get("state", "normal"),
                 "ul": d.get("underline", -1)}
            for k in ("background", "foreground", "font"):
                if d.get(k): x[{"background": "bg", "foreground": "fg", "font": "font"}[k]] = _font(d[k]) if k == "font" else d[k]
            v = d.get("variable")
            if t == "checkbutton" and v is not None: x["chk"] = v._v == d.get("onvalue", 1)
            elif t == "radiobutton" and v is not None: x["chk"] = str(v._v) == str(d.get("value", d.get("label", "")))
            if t == "cascade" and isinstance(d.get("menu"), Menu) and depth < 8: x["sub"] = d["menu"]._tree(depth + 1)
            its.append(x)
        return {"id": self._id, "items": its}
    def _mk(self, kind, kw):
        d = {"t": kind}; d.update(kw)
        if "bg" in d: d["background"] = d.pop("bg")
        if "fg" in d: d["foreground"] = d.pop("fg")
        v = d.get("variable")
        if kind in ("checkbutton", "radiobutton"):
            if v is None: v = d["variable"] = IntVar() if kind == "checkbutton" else StringVar()
            v._link(self)
        if kind == "cascade" and isinstance(d.get("menu"), Menu):
            m = d["menu"]
            if self not in m._par: m._par.append(self)
        return d
    def add(self, kind, cnf=None, **kw): self.insert(len(self._items), kind, cnf, **kw)
    def insert(self, index, kind, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); p = self._idx(index, True)
        self._items.insert(p, self._mk(kind, o)); self._touch()
    def add_command(self, cnf=None, **kw): self.add("command", cnf, **kw)
    def add_cascade(self, cnf=None, **kw): self.add("cascade", cnf, **kw)
    def add_checkbutton(self, cnf=None, **kw): self.add("checkbutton", cnf, **kw)
    def add_radiobutton(self, cnf=None, **kw): self.add("radiobutton", cnf, **kw)
    def add_separator(self, cnf=None, **kw): self.add("separator", cnf, **kw)
    def insert_command(self, i, cnf=None, **kw): self.insert(i, "command", cnf, **kw)
    def insert_cascade(self, i, cnf=None, **kw): self.insert(i, "cascade", cnf, **kw)
    def insert_checkbutton(self, i, cnf=None, **kw): self.insert(i, "checkbutton", cnf, **kw)
    def insert_radiobutton(self, i, cnf=None, **kw): self.insert(i, "radiobutton", cnf, **kw)
    def insert_separator(self, i, cnf=None, **kw): self.insert(i, "separator", cnf, **kw)
    def _idx(self, i, ins=False):
        n = len(self._items); s = str(i)
        if s in ("end", "last"): return n if ins else n - 1
        if s in ("none", "active"): return -1
        if s.startswith("@"): return 0
        try: return max(0, int(s))
        except ValueError:
            for k, d in enumerate(self._items):
                if str(d.get("label", "")) == s: return k
            import fnmatch
            for k, d in enumerate(self._items):
                if fnmatch.fnmatch(str(d.get("label", "")), s): return k
            return -1
    def index(self, i): r = self._idx(i); return None if r < 0 else r
    def delete(self, a, b=None):
        p = self._idx(a); q = p if b is None else self._idx(b)
        if p < 0: return
        del self._items[p:q + 1]; self._touch()
    def entryconfig(self, i, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw); p = self._idx(i)
        if p < 0 or p >= len(self._items): return
        if not o: return dict(self._items[p])
        if "bg" in o: o["background"] = o.pop("bg")
        if "fg" in o: o["foreground"] = o.pop("fg")
        self._items[p].update(o); m = o.get("menu")
        if isinstance(m, Menu) and self not in m._par: m._par.append(self)
        self._touch()
    entryconfigure = entryconfig
    def entrycget(self, i, k):
        p = self._idx(i); return self._items[p].get(k, "") if 0 <= p < len(self._items) else ""
    def type(self, i): p = self._idx(i); return self._items[p]["t"]
    def invoke(self, i): return self._mi(self._idx(i))
    def _mi(self, i):
        if not (0 <= i < len(self._items)): return
        d = self._items[i]
        if d.get("state") == "disabled": return
        t = d["t"]; v = d.get("variable")
        if t == "checkbutton" and v is not None: v.set(d.get("offvalue", 0) if v._v == d.get("onvalue", 1) else d.get("onvalue", 1))
        elif t == "radiobutton" and v is not None: v.set(d.get("value", d.get("label", "")))
        self._touch()
        if d.get("command"): return _cb(d["command"])
    def tk_popup(self, x, y, entry=""): _flush(); _send("popup", self._tree(), x, y)
    def post(self, x, y): self.tk_popup(x, y)
    unpost = activate = tk_mbPost = tk_mbUnpost = _nop
    def yposition(self, i): return 0
    def xposition(self, i): return 0
    def post_cascade(self, i): pass


class Menubutton(Misc):
    _type = "menubtn"


class OptionMenu(Menubutton):
    def __init__(self, master, variable, value, *values, **kw):
        cmd = kw.pop("command", None); variable.set(value)
        Menubutton.__init__(self, master, textvariable=variable, indicatoron=1, relief="raised", **kw)
        m = Menu(self, tearoff=0); self.config(menu=m)
        def mk(v): return lambda: (variable.set(v), cmd(v) if cmd else None)
        for v in (value,) + values: m.add_command(label=v, command=mk(v))
    def __getitem__(self, k): return self.cget(k)


class PanedWindow(Misc):
    _type = "pane"
    def _pre(self, o): Misc._pre(self, o); self._panes = []
    def add(self, child, **kw): self._panes.append(child); _send("padd", self._id, child._id, {k: v for k, v in kw.items() if isinstance(v, (int, float, str, bool))})
    def insert(self, pos, child, **kw): self.add(child, **kw)
    def forget(self, child):
        if child in self._panes: self._panes.remove(child); _send("fg", child._id)
    remove = forget
    def panes(self): return tuple(str(p) for p in self._panes)
    def pane(self, c, **k): return {}
    paneconfig = paneconfigure = pane
    sash_coord = lambda self, i: (0, 0)
    sash_place = sash_mark = sashpos = proxy_coord = proxy = proxy_forget = proxy_place = sash = _nop
    identify = lambda self, x, y: ""
    def panecget(self, c, k): return ""


class Sizegrip(Misc): _type = "sizegrip"
class Separator(Misc): _type = "sep"


class Combobox(Misc):
    _type = "combo"
    def get(self): return str(self._val)
    def set(self, v): self._vset(v); _send("cfg", self._id, {"val": v})
    def current(self, i=None):
        vals = [str(x) for x in self._o.get("values", [])]
        if i is None: return vals.index(str(self._val)) if str(self._val) in vals else -1
        self.set(vals[i])
    selection_range = selection_clear = icursor = _nop
    def delete(self, a, b=None): self.set("")
    def insert(self, i, s): self.set(str(self._val) + str(s))


class Progressbar(Misc):
    _type = "progress"
    def step(self, a=10.0):
        mx = float(self._o.get("maximum", 100) or 100)
        self._val = (float(self._val or 0) + a) % mx if mx else 0; _send("cfg", self._id, {"val": self._val})
        if self._var is not None: self._var._v = self._val
    def start(self, interval=None): _send("cfg", self._id, {"ind": True})
    def stop(self): _send("cfg", self._id, {"ind": False, "val": 0}); self._val = 0
    def cget(self, k): return self._val if k == "value" else Misc.cget(self, k)


# ---------------- Treeview / Notebook ----------------
class Treeview(_Scr, Misc):
    _type = "tree"
    def _pre(self, o):
        Misc._pre(self, o)
        self._tn = {"": {"ch": [], "p": None}}; self._sel = []; self._foc = ""; self._tgc = {}; self._n = 0; self._tbnd = {}
        self._cols = _tkl(o.get("columns", ())); self._hd = {}; self._cw = {}
        for c in ["#0"] + self._cols: self._colinit(c)
    def _colinit(self, c):
        self._hd.setdefault(c, {"text": "" if c == "#0" else c, "anchor": "w" if c == "#0" else "center", "cmd": None, "image": 0})
        self._cw.setdefault(c, {"w": 200 if c == "#0" else 100, "anchor": "w" if c == "#0" else "center", "st": 1, "mw": 20})
    def _oc(self, o):
        if "columns" in o:
            self._cols = _tkl(o["columns"])
            for c in self._cols: self._colinit(c)
        _mark(self)
    def _post(self, o): _mark(self)
    def _sync(self):
        rows = []
        def walk(p, d):
            for iid in self._tn[p]["ch"]:
                n = self._tn[iid]
                rows.append([iid, p, str(n["text"]), [str(x) for x in n["values"]], bool(n["open"]), list(n["tags"]), n["image"], d]); walk(iid, d + 1)
        walk("", 0)
        cols = []
        for c in ["#0"] + self._cols:
            h = self._hd[c]; w = self._cw[c]
            cols.append({"id": c, "text": str(h["text"]), "a": h["anchor"], "w": w["w"], "mw": w["mw"], "st": w["st"], "img": h["image"]})
        _send("tvset", self._id, {"cols": cols, "rows": rows, "sel": list(self._sel), "foc": self._foc,
                                  "tags": {t: _tstyle(c) for t, c in self._tgc.items()}, "show": str(self._o.get("show", "tree headings")),
                                  "mode": str(self._o.get("selectmode", "extended"))})
    def _gid(self, a):
        if len(a) == 1 and isinstance(a[0], (list, tuple)): return [str(x) for x in a[0]]
        return [str(x) for x in a]
    def _chk(self, i):
        if i not in self._tn or i == "": raise TclError('Item %s not found' % i)
        return self._tn[i]
    def insert(self, parent, index, iid=None, **kw):
        parent = str(parent)
        if parent not in self._tn: raise TclError("Item %s not found" % parent)
        if iid is None:
            self._n += 1; iid = "I%03X" % self._n
            while iid in self._tn: self._n += 1; iid = "I%03X" % self._n
        iid = str(iid)
        if iid in self._tn: raise TclError('Item %s already exists' % iid)
        tags = kw.get("tags", ()); tags = (tags,) if isinstance(tags, str) else tuple(tags)
        im = kw.get("image"); im = im if isinstance(im, PhotoImage) else None
        vals = kw.get("values", ()); vals = tuple(_tkl(vals)) if isinstance(vals, str) else tuple(vals)
        self._tn[iid] = {"p": parent, "ch": [], "text": kw.get("text", ""), "values": vals, "open": bool(kw.get("open", False)),
                         "tags": tags, "image": im._id if im else 0}
        ch = self._tn[parent]["ch"]
        if str(index) == "end": ch.append(iid)
        else: ch.insert(max(0, int(index)), iid)
        _mark(self); return iid
    def delete(self, *items):
        for i in self._gid(items):
            if i in self._tn and i != "":
                self._rm(i); 
        _mark(self)
    def _rm(self, i):
        for c in list(self._tn[i]["ch"]): self._rm(c)
        p = self._tn[i]["p"]
        if p in self._tn and i in self._tn[p]["ch"]: self._tn[p]["ch"].remove(i)
        del self._tn[i]
        if i in self._sel: self._sel.remove(i)
    def detach(self, *items):
        for i in self._gid(items):
            p = self._tn[i]["p"]
            if i in self._tn[p]["ch"]: self._tn[p]["ch"].remove(i)
        _mark(self)
    def move(self, item, parent, index):
        item = str(item); p = self._tn[item]["p"]
        if item in self._tn[p]["ch"]: self._tn[p]["ch"].remove(item)
        self._tn[item]["p"] = str(parent); ch = self._tn[str(parent)]["ch"]
        if str(index) == "end": ch.append(item)
        else: ch.insert(int(index), item)
        _mark(self)
    reattach = move
    def exists(self, i): return str(i) in self._tn and str(i) != ""
    def parent(self, i): return self._chk(str(i))["p"] or ""
    def index(self, i): n = self._chk(str(i)); return self._tn[n["p"]]["ch"].index(str(i))
    def get_children(self, item=None): return tuple(self._tn[str(item or "")]["ch"])
    def set_children(self, item, *new):
        for c in list(self._tn[str(item)]["ch"]): self.detach(c)
        for c in self._gid(new): self.move(c, item, "end")
    def next(self, i):
        n = self._chk(str(i)); ch = self._tn[n["p"]]["ch"]; k = ch.index(str(i)); return ch[k + 1] if k + 1 < len(ch) else ""
    def prev(self, i):
        n = self._chk(str(i)); ch = self._tn[n["p"]]["ch"]; k = ch.index(str(i)); return ch[k - 1] if k > 0 else ""
    def item(self, i, option=None, **kw):
        n = self._chk(str(i))
        if kw:
            for k, v in kw.items():
                if k == "image": n["image"] = v._id if isinstance(v, PhotoImage) else 0
                elif k == "tags": n["tags"] = (v,) if isinstance(v, str) else tuple(v)
                elif k == "values": n["values"] = tuple(v) if not isinstance(v, str) else tuple(_tkl(v))
                elif k == "open": n["open"] = bool(v)
                else: n[k] = v
            _mark(self); return
        d = {"text": n["text"], "image": "", "values": n["values"], "open": 1 if n["open"] else 0, "tags": n["tags"]}
        return d if option is None else d.get(option, "")
    def set(self, item, column=None, value=None):
        n = self._chk(str(item)); vals = list(n["values"]) + [""] * (len(self._cols) - len(n["values"]))
        if column is None: return {c: vals[k] for k, c in enumerate(self._cols)}
        k = self._cols.index(column) if column in self._cols else int(str(column).lstrip("#")) - 1
        if value is None: return vals[k]
        vals[k] = value; n["values"] = tuple(vals); _mark(self)
    def selection(self): return tuple(self._sel)
    def selection_set(self, *items): self._sel = self._gid(items); _mark(self)
    def selection_add(self, *items): self._sel += [i for i in self._gid(items) if i not in self._sel]; _mark(self)
    def selection_remove(self, *items): self._sel = [i for i in self._sel if i not in self._gid(items)]; _mark(self)
    def selection_toggle(self, *items):
        for i in self._gid(items): self._sel.remove(i) if i in self._sel else self._sel.append(i)
        _mark(self)
    def focus(self, item=None):
        if item is None: return self._foc
        self._foc = str(item); _mark(self)
    def see(self, item):
        p = self._tn[str(item)]["p"]
        while p:
            self._tn[p]["open"] = True; p = self._tn[p]["p"]
        _mark(self); _send("tvsee", self._id, str(item))
    def heading(self, col, option=None, **kw):
        col = "#0" if col == "#0" else (self._cols[int(col[1:]) - 1] if str(col).startswith("#") else col); self._colinit(col); h = self._hd[col]
        if kw:
            for k, v in kw.items():
                if k == "command": h["cmd"] = v
                elif k == "image": h["image"] = v._id if isinstance(v, PhotoImage) else 0
                else: h[k] = v
            _mark(self); return
        return h if option is None else h.get(option, "")
    def column(self, col, option=None, **kw):
        col = "#0" if col == "#0" else (self._cols[int(col[1:]) - 1] if str(col).startswith("#") else col); self._colinit(col); w = self._cw[col]
        if kw:
            for k, v in kw.items():
                if k == "width": w["w"] = int(v)
                elif k == "minwidth": w["mw"] = int(v)
                elif k == "stretch": w["st"] = 1 if v in (1, True, "1", "yes") else 0
                elif k == "anchor": w["anchor"] = str(v)
            _mark(self); return
        d = {"width": w["w"], "minwidth": w["mw"], "stretch": w["st"], "anchor": w["anchor"], "id": col}
        return d if option is None else d.get(option, "")
    def tag_configure(self, tag, option=None, **kw):
        self._tgc.setdefault(tag, {}).update(kw)
        _mark(self)
    tag_config = tag_configure
    def tag_has(self, tag, item=None):
        if item is None: return tuple(i for i, n in self._tn.items() if i and tag in n["tags"])
        return tag in self._chk(str(item))["tags"]
    def tag_bind(self, tag, seq=None, func=None, add=None):
        if func: self._tbnd.setdefault((tag, _parse(seq)[0]), []).append(func)
        return seq
    def identify_row(self, y): return _query("tvrow", self._id, int(y), default="") or ""
    def identify_column(self, x): return _query("tvcol", self._id, int(x), default="#0") or "#0"
    def identify_region(self, x, y): return _query("tvreg", self._id, int(x), int(y), default="nothing") or "nothing"
    def identify_element(self, x, y): return ""
    def identify(self, c, x, y):
        return {"row": self.identify_row(y), "column": self.identify_column(x), "region": self.identify_region(x, y)}.get(c, "")
    def bbox(self, item, column=None): return ""
    def _hdrclick(self, col):
        h = self._hd.get(col)
        if h and h["cmd"]: _cb(h["cmd"])


class Notebook(Misc):
    _type = "nb"
    def _pre(self, o): Misc._pre(self, o); self._tabs = []; self._tsel = None
    def _tab(self, spec):
        if spec in (None, "current"): return self._tsel
        if isinstance(spec, Misc): return spec
        if str(spec) == "end": return self._tabs[-1][0] if self._tabs else None
        try: return self._tabs[int(spec)][0]
        except (ValueError, IndexError):
            for ch, _ in self._tabs:
                if str(ch) == str(spec): return ch
        raise TclError('Invalid slave specification %s' % spec)
    def _pos(self, ch):
        for k, (c, _) in enumerate(self._tabs):
            if c is ch: return k
        return -1
    def add(self, child, **kw): self.insert("end", child, **kw)
    def insert(self, pos, child, **kw):
        k = self._pos(child)
        if k >= 0: self._tabs.pop(k)
        idx = len(self._tabs) if str(pos) == "end" else max(0, min(int(pos), len(self._tabs)))
        self._tabs.insert(idx, (child, dict(kw))); child._geo = ("notebook", {})
        im = kw.get("image"); _send("nbadd", self._id, child._id, idx, {"text": str(kw.get("text", "")), "state": kw.get("state", "normal"),
                                                                       "image": im._id if isinstance(im, PhotoImage) else 0})
        if self._tsel is None: self._tsel = child; _send("nbsel", self._id, child._id)
    def forget(self, tab):
        ch = self._tab(tab); k = self._pos(ch)
        if k >= 0:
            self._tabs.pop(k); _send("nbdel", self._id, ch._id)
            if self._tsel is ch: self._tsel = self._tabs[0][0] if self._tabs else None
            if self._tsel: _send("nbsel", self._id, self._tsel._id)
    def hide(self, tab): _send("nbcfg", self._id, self._tab(tab)._id, {"state": "hidden"})
    def select(self, tab_id=None):
        if tab_id is None: return str(self._tsel) if self._tsel else ""
        ch = self._tab(tab_id)
        if ch is not self._tsel:
            self._tsel = ch; _send("nbsel", self._id, ch._id); _fireb(self, {"cat": "v:NotebookTabChanged", "wid": self._id})
    def index(self, tab_id): return len(self._tabs) if str(tab_id) == "end" else self._pos(self._tab(tab_id))
    def tabs(self): return tuple(str(c) for c, _ in self._tabs)
    def tab(self, tab_id, option=None, **kw):
        ch = self._tab(tab_id); k = self._pos(ch); d = self._tabs[k][1]
        if kw:
            d.update(kw); _send("nbcfg", self._id, ch._id, {"text": str(d.get("text", "")), "state": d.get("state", "normal")}); return
        return dict(d) if option is None else d.get(option, "")
    enable_traversal = identify = _nop
    def _nbsel(self, i):
        if 0 <= i < len(self._tabs) and self._tabs[i][0] is not self._tsel:
            self._tsel = self._tabs[i][0]; _fireb(self, {"cat": "v:NotebookTabChanged", "wid": self._id})


# ---------------- ttk ----------------
def _style_resolve(name, wtype):
    parts = str(name).split("."); chain = [".".join(parts[i:]) for i in range(len(parts) - 1, -1, -1)]
    d = {}; mp = {}
    for nm in chain:
        s = _STYLES.get(nm, {}); d.update({k: v for k, v in s.items() if k != "_map"}); mp.update(s.get("_map", {}))
    fieldy = wtype in ("entry", "spin", "combo", "text", "tree", "list")
    km = {"foreground": "fg", "font": "font", "padding": "pad", "relief": "relief", "borderwidth": "bd", "anchor": "anchor",
          "justify": "justify", "width": "width", "rowheight": "rh", "troughcolor": "tc", "selectbackground": "selbg",
          "selectforeground": "selfg"}
    out = {}
    for k, v in d.items():
        if k == "fieldbackground" and fieldy: out["bg"] = v
        elif k == "background" and not (fieldy and "fieldbackground" in d): out["bg"] = v
        elif k in km: out[km[k]] = _font(v) if k == "font" else (list(v) if isinstance(v, (list, tuple)) else v)
    for opt, key in (("background", "abg"), ("foreground", "afg")):
        for spec in mp.get(opt, []):
            try:
                if "active" in spec[:-1] or "pressed" in spec[:-1]: out[key] = spec[-1]; break
            except Exception: pass
    if wtype == "tree":
        h = _STYLES.get("Treeview.Heading", {})
        if "background" in h: out["hbg"] = h["background"]
        if "foreground" in h: out["hfg"] = h["foreground"]
        if "font" in h: out["hfont"] = _font(h["font"])
    return out


class Style:
    def __init__(self, master=None): pass
    def configure(self, style, query_opt=None, **kw):
        if query_opt: return _STYLES.get(style, {}).get(query_opt)
        _STYLES.setdefault(style, {}).update(kw)
        self._reapply()
    def map(self, style, query_opt=None, **kw):
        s = _STYLES.setdefault(style, {}); m = s.setdefault("_map", {})
        if query_opt: return m.get(query_opt, [])
        for k, v in kw.items(): m[k] = [tuple(x) for x in v]
        self._reapply(); return m
    def _reapply(self):
        for w in list(_W.values()):
            if getattr(w, "_ttk", 0):
                try: _send("cfg", w._id, w._style_opts())
                except Exception: pass
                if w._type == "tree": _mark(w)
    def lookup(self, style, option, state=None, default=None): return _STYLES.get(style, {}).get(option, default)
    def layout(self, style, layoutspec=None): return []
    def element_create(self, *a, **k): pass
    def element_names(self): return ()
    def element_options(self, e): return ()
    def theme_create(self, *a, **k): pass
    def theme_settings(self, *a, **k): pass
    def theme_names(self): return ("default", "clam", "alt", "classic")
    def theme_use(self, name=None): return "default" if name is None else None


class _T:
    _ttk = 1
    def _sname(self): return getattr(self, "_cname", "T" + type(self).__name__)
    def winfo_class(self): return getattr(self, "_cname", type(self).__name__)
    def state(self, spec=None):
        if spec is None: return tuple(self._tstate)
        for s in (spec if isinstance(spec, (list, tuple)) else str(spec).split()):
            if s.startswith("!"): self._tstate.discard(s[1:])
            else: self._tstate.add(s)
        st = "disabled" if "disabled" in self._tstate else ("readonly" if "readonly" in self._tstate else "normal")
        _send("cfg", self._id, {"state": st})
        return ()
    def instate(self, spec, callback=None, *a):
        ok = all((s[1:] not in self._tstate) if s.startswith("!") else (s in self._tstate) for s in spec)
        if ok and callback: callback(*a)
        return ok
    def identify(self, x, y): return ""


def _tt(base, name, cname, **extra):
    return type(name, (_T, base), dict({"_cname": cname}, **extra))


ttk_Button = _tt(Button, "Button", "TButton")
ttk_Checkbutton = _tt(Checkbutton, "Checkbutton", "TCheckbutton")
ttk_Radiobutton = _tt(Radiobutton, "Radiobutton", "TRadiobutton")
ttk_Entry = _tt(Entry, "Entry", "TEntry")
ttk_Combobox = _tt(Combobox, "Combobox", "TCombobox")
ttk_Frame = _tt(Frame, "Frame", "TFrame")
ttk_Label = _tt(Label, "Label", "TLabel")
ttk_LabelFrame = _tt(LabelFrame, "Labelframe", "TLabelframe")
ttk_Menubutton = _tt(Menubutton, "Menubutton", "TMenubutton")
ttk_Notebook = _tt(Notebook, "Notebook", "TNotebook")
ttk_Panedwindow = _tt(PanedWindow, "Panedwindow", "TPanedwindow")
ttk_Progressbar = _tt(Progressbar, "Progressbar", "TProgressbar")
ttk_Scale = _tt(Scale, "Scale", "TScale")
ttk_Scrollbar = _tt(Scrollbar, "Scrollbar", "TScrollbar")
ttk_Separator = _tt(Separator, "Separator", "TSeparator")
ttk_Sizegrip = _tt(Sizegrip, "Sizegrip", "TSizegrip")
ttk_Spinbox = _tt(Spinbox, "Spinbox", "TSpinbox")
ttk_Treeview = _tt(Treeview, "Treeview", "Treeview")


class ttk_OptionMenu(_T, Menubutton):
    _cname = "TMenubutton"
    def __init__(self, master, variable, default=None, *values, **kw):
        cmd = kw.pop("command", None)
        if default is not None: variable.set(default)
        Menubutton.__init__(self, master, textvariable=variable, indicatoron=1, **kw)
        m = Menu(self, tearoff=0); self.config(menu=m)
        def mk(v): return lambda: (variable.set(v), cmd(v) if cmd else None)
        for v in values: m.add_command(label=v, command=mk(v))
    def set_menu(self, default=None, *values):
        m = self.cget("menu"); m.delete(0, "end")
        for v in values: m.add_command(label=v, command=lambda v=v: self._var.set(v))


class ttk_LabeledScale(ttk_Frame):
    def __init__(self, master=None, variable=None, from_=0, to=10, **kw):
        ttk_Frame.__init__(self, master, **kw)
        self._variable = variable or IntVar(master); self._variable.set(from_)
        self.label = ttk_Label(self, text=str(from_)); self.scale = ttk_Scale(self, variable=self._variable, from_=from_, to=to)
        self.scale.pack(fill="x"); self.label.pack()
        self._variable.trace_add("write", lambda *a: self.label.config(text=str(int(float(self._variable._v)))))
    value = property(lambda self: self._variable.get(), lambda self, v: self._variable.set(v))


# ---------------- event loop ----------------
def _handle(e):
    t = e.get("t")
    if t == "size": _st["w"], _st["h"] = e["w"], e["h"]; return
    if t == "dlg": _dlg[e["req"]] = e["r"]; return
    if t == "qr": _qres[e["req"]] = e["r"]; return
    if t == "err": print("[tk error]", e.get("m"), file=sys.stderr); return
    if t == "imgclose": _st["imgclosed"] = True; return
    if t == "focus": _st["focus"] = e.get("id", 0); return
    if t == "ls":
        p = e.get("p") or os.getcwd()
        try:
            p = os.path.abspath(p); ents = sorted(((n, os.path.isdir(os.path.join(p, n))) for n in os.listdir(p)), key=lambda x: (not x[1], x[0].lower()))
        except OSError:
            ents = []
        _send("lsr", e["req"], p, ents); _flush(); return
    w = _W.get(e.get("id"))
    if w is None: return
    if t == "cmd": w._invoke()
    elif t == "val": w._evval(e)
    elif t == "sel":
        w._sel = e["v"]
        if hasattr(w, "_act") and e["v"]: w._act = e["v"][-1]
    elif t == "cur":
        if hasattr(w, "_cur"): w._cur = [e["a"], e["b"]]
    elif t == "bind":
        if hasattr(w, "_ox"):
            w._ox = e.get("ox", w._ox); w._oy = e.get("oy", w._oy); w._hov = e.get("it", 0)
        if isinstance(w, Text) and e.get("o") is not None and e.get("cat") in ("b1", "b2", "b3", "dbl1"): w._lc = e["o"]
        _fire_one(w, e)
        if hasattr(w, "_tagfire"): w._tagfire(e)
    elif t == "virt": _fireb(w, {"cat": "v:" + e["name"], "wid": w._id})
    elif t == "close": w._close()
    elif t == "mcmd": w._mi(e["i"])
    elif t == "tvsel":
        w._sel = [str(x) for x in e["v"]]; w._foc = w._sel[-1] if w._sel else w._foc
        _fireb(w, {"cat": "v:TreeviewSelect", "wid": w._id})
    elif t == "tvopen":
        n = w._tn.get(e["iid"])
        if n is not None:
            n["open"] = bool(e["open"]); _fireb(w, {"cat": "v:TreeviewOpen" if e["open"] else "v:TreeviewClose", "wid": w._id})
    elif t == "hdr": w._hdrclick(e["col"])
    elif t == "spin":
        if hasattr(w, "invoke"): w.invoke("buttonup" if e.get("d", 1) > 0 else "buttondown")
    elif t == "nbsel": w._nbsel(e["i"])
    elif t == "sbcmd":
        if w._cmd: _cb(w._cmd, *e["a"])
    elif t == "scr":
        f = w._ysc if e.get("k") == "y" else w._xsc
        if f: _cb(f, e["a"], e["b"])
    elif t == "blur":
        if hasattr(w, "_blur"): w._blur()
    elif t == "ov":
        pass


def _pump(t=0.05):
    _flush(); now = time.time()
    if _after: t = max(0, min(t, min(a[0] for a in _after) - now))
    e = runner._IO.nextEvent(int(t * 1000))
    if e:
        try: _handle(json.loads(e))
        except Exception: runner.report_exc()
    now = time.time()
    for a in sorted([a for a in _after if a[0] <= now], key=lambda a: a[0]):
        if a in _after:
            _after.remove(a); _cb(a[2], *a[3])
    _flush()


def _mainloop():
    _st["quit"] = False; _flush()
    while not _st["quit"] and (_st["root"] is not None): _pump(0.05)


def mainloop(n=0): _mainloop()


def _show_images(b64s):
    _st["imgclosed"] = False
    _send("img", b64s); _flush()
    while not _st["imgclosed"]: _pump(0.05)


def _ask(kind, title="", msg="", init="", extra=None):
    _n[0] += 1; r = _n[0]
    _send("dlg", r, kind, str(title or ""), str(msg or ""), str(init or ""), extra or {}); _flush()
    while r not in _dlg and not _st["quit"]: _pump(0.05)
    return _dlg.pop(r, None)


def _asf(mode, **k):
    ft = []
    for x in (k.get("filetypes") or []):
        try:
            pats = x[1] if isinstance(x[1], (list, tuple)) else str(x[1]).split()
            ft.append([str(x[0]), [str(p) for p in pats]])
        except Exception: pass
    return _ask("file", k.get("title") or "", mode, k.get("initialdir") or os.getcwd(),
                {"name": k.get("initialfile") or "", "ft": ft, "ext": k.get("defaultextension") or "", "multi": bool(k.get("multiple"))})


def getint(s): return int(s)
def getdouble(s): return float(s)
def getboolean(s): return str(s).lower() in ("1", "true", "yes", "on")
def NoDefaultRoot(): _st["root"] = None


# ---------------- simpledialog.Dialog ----------------
class _Dialog(Toplevel):
    def __init__(self, parent, title=None):
        Toplevel.__init__(self, parent)
        if title: self.title(title)
        self.parent = parent; self.result = None
        body = Frame(self); self.initial_focus = self.body(body); body.pack(padx=5, pady=5)
        self.buttonbox(); self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.wait_window(self)
    def body(self, master): return None
    def buttonbox(self):
        box = Frame(self)
        Button(box, text="OK", width=10, command=self.ok, default=ACTIVE).pack(side=LEFT, padx=5, pady=5)
        Button(box, text="Cancel", width=10, command=self.cancel).pack(side=LEFT, padx=5, pady=5)
        box.pack()
    def ok(self, event=None):
        if not self.validate(): return
        self.withdraw(); self.apply(); self.cancel()
    def cancel(self, event=None): self.destroy()
    def validate(self): return 1
    def apply(self): pass


class _FileDialog:
    def __init__(self, master=None, title=None): self.master = master; self.title = title; self._sv = ""
    def go(self, dir_or_file=".", pattern="*", default="", key=None):
        d = dir_or_file if os.path.isdir(dir_or_file) else os.path.dirname(dir_or_file) or "."
        r = _asf("open", title=self.title, initialdir=os.path.abspath(d), initialfile=default)
        return r or None
    def quit(self, how=None): pass


# ---------------- submodules ----------------
def _mod(name, **attrs):
    m = types.ModuleType("tkinter." + name); m.__dict__.update(attrs); sys.modules["tkinter." + name] = m; return m


def _install():
    me = sys.modules[__name__]
    if getattr(me, "_done", False): return
    me._done = True; me.__path__ = []; sys.modules["tkinter"] = me; me.__name__ = "tkinter"
    sys.modules["_tkinter"] = types.ModuleType("_tkinter"); sys.modules["_tkinter"].TclError = TclError
    mb = lambda kind, ret: (lambda title=None, message=None, **k: ret(_ask(kind, title, message)))
    def _q(kind, title, message, pos, neg):
        r = _ask(kind, title, message); return pos if r == pos else neg
    me.messagebox = _mod("messagebox",
        ABORT="abort", RETRY="retry", IGNORE="ignore", OK="ok", CANCEL="cancel", YES="yes", NO="no",
        ERROR="error", INFO="info", QUESTION="question", WARNING="warning", ABORTRETRYIGNORE="abortretryignore",
        OKCANCEL="okcancel", RETRYCANCEL="retrycancel", YESNO="yesno", YESNOCANCEL="yesnocancel",
        showinfo=lambda title=None, message=None, **k: (_ask("info", title, message), "ok")[1],
        showwarning=lambda title=None, message=None, **k: (_ask("warn", title, message), "ok")[1],
        showerror=lambda title=None, message=None, **k: (_ask("error", title, message), "ok")[1],
        askyesno=lambda title=None, message=None, **k: _ask("yesno", title, message) == "yes",
        askokcancel=lambda title=None, message=None, **k: _ask("okcancel", title, message) == "ok",
        askretrycancel=lambda title=None, message=None, **k: _ask("retrycancel", title, message) == "retry",
        askquestion=lambda title=None, message=None, **k: "yes" if _ask("yesno", title, message) == "yes" else "no",
        askyesnocancel=lambda title=None, message=None, **k: {"yes": True, "no": False}.get(_ask("yesnocancel", title, message)),
        Message=lambda *a, **k: None)
    def _num(conv, name):
        def f(title, prompt, **k):
            init = k.get("initialvalue", "")
            while True:
                r = _ask("string", title, prompt, init)
                if r is None: return None
                try: v = conv(r)
                except Exception:
                    _ask("warn", "Illegal value", "Not an %s value.\nPlease try again" % name); init = r; continue
                lo, hi = k.get("minvalue"), k.get("maxvalue")
                if lo is not None and v < lo or hi is not None and v > hi:
                    _ask("warn", "Too small" if lo is not None and v < lo else "Too large", "The allowed range is %s to %s" % (lo, hi)); init = r; continue
                return v
        return f
    me.simpledialog = _mod("simpledialog", askstring=lambda title, prompt, **k: _ask("string", title, prompt, k.get("initialvalue", ""), {"show": k.get("show", "")}),
                           askinteger=_num(int, "integer"), askfloat=_num(float, "floating point"), Dialog=_Dialog, SimpleDialog=_Dialog)
    def _open(mode, **k):
        p = _asf("open", **k); return p or ""
    def _file(m, kind, **k):
        p = _asf(kind, **k)
        return open(p, m, **({"encoding": "utf-8"} if "b" not in m else {})) if p else None
    me.filedialog = _mod("filedialog",
        askopenfilename=lambda **k: _asf("open", **k) or "",
        asksaveasfilename=lambda **k: _asf("save", **k) or "",
        askopenfilenames=lambda **k: tuple(_asf("open", multiple=True, **{a: b for a, b in k.items() if a != "multiple"}) or ()),
        askdirectory=lambda **k: _asf("dir", **k) or "",
        askopenfile=lambda mode="r", **k: _file(mode, "open", **k),
        askopenfiles=lambda mode="r", **k: tuple(open(p, mode) for p in (_asf("open", multiple=True, **k) or ())),
        asksaveasfile=lambda mode="w", **k: _file(mode, "save", **k),
        Open=lambda **k: None, SaveAs=lambda **k: None, Directory=lambda **k: None,
        FileDialog=_FileDialog, LoadFileDialog=_FileDialog, SaveFileDialog=_FileDialog)
    def _color(color=None, **k):
        r = _ask("color", k.get("title", ""), "", color if isinstance(color, str) else "#ffffff")
        if not r: return (None, None)
        r = r.lstrip("#"); return ((int(r[0:2], 16), int(r[2:4], 16), int(r[4:6], 16)), "#" + r)
    me.colorchooser = _mod("colorchooser", askcolor=_color, Chooser=lambda **k: None)
    fams = ("Arial", "Courier", "Courier New", "Consolas", "Georgia", "Helvetica", "Monospace", "Roboto", "Sans Serif", "Serif", "Tahoma", "Times", "Times New Roman", "Verdana")
    me.font = _mod("font", Font=Font, BOLD="bold", ITALIC="italic", NORMAL="normal", ROMAN="roman", families=lambda *a, **k: fams,
                   names=lambda *a, **k: tuple(f.name for f in _FONTS),
                   nametofont=lambda n, *a, **k: next((f for f in _FONTS if f.name == n), Font(font=("TkDefaultFont", 10))))
    me.scrolledtext = _mod("scrolledtext", ScrolledText=ScrolledText)
    me.constants = _mod("constants", **_C)
    me.dnd = _mod("dnd", dnd_start=lambda *a, **k: None, DndHandler=object)
    me.dialog = _mod("dialog", Dialog=_Dialog, DIALOG_ICON="questhead")
    me.commondialog = _mod("commondialog", Dialog=object)
    me.ttk = _mod("ttk", Button=ttk_Button, Checkbutton=ttk_Checkbutton, Radiobutton=ttk_Radiobutton, Entry=ttk_Entry,
                  Combobox=ttk_Combobox, Frame=ttk_Frame, Label=ttk_Label, LabelFrame=ttk_LabelFrame, Labelframe=ttk_LabelFrame,
                  Menubutton=ttk_Menubutton, Notebook=ttk_Notebook, Panedwindow=ttk_Panedwindow, PanedWindow=ttk_Panedwindow,
                  Progressbar=ttk_Progressbar, Scale=ttk_Scale, Scrollbar=ttk_Scrollbar, Separator=ttk_Separator,
                  Sizegrip=ttk_Sizegrip, Spinbox=ttk_Spinbox, Treeview=ttk_Treeview, OptionMenu=ttk_OptionMenu, Style=Style,
                  LabeledScale=ttk_LabeledScale, Widget=_T, tclobjs_to_py=lambda d: d, setup_master=lambda m=None: m or _st["root"])
    me.ttk.__all__ = ["Button", "Checkbutton", "Combobox", "Entry", "Frame", "Label", "Labelframe", "LabelFrame", "Menubutton",
                      "Notebook", "Panedwindow", "PanedWindow", "Progressbar", "Radiobutton", "Scale", "Scrollbar", "Separator",
                      "Sizegrip", "Spinbox", "Style", "Treeview", "OptionMenu", "LabeledScale", "Widget"]
    # PIL.ImageTk support
    import io
    class _PILPhoto(PhotoImage):
        def __init__(self, image=None, size=None, **kw):
            self._pil = image
            PhotoImage.__init__(self, **self._data(image, kw))
        def _data(self, image, kw):
            if image is None: return dict(kw)
            b = io.BytesIO(); image.save(b, "PNG"); return {"data": b.getvalue()}
        def paste(self, im, box=None):
            self._pil = im; self._load(self._data(im, {})); _send("pimg", self._id, self._uri, 0, 0)
    sys.modules["PIL.ImageTk"] = types.ModuleType("PIL.ImageTk")
    sys.modules["PIL.ImageTk"].PhotoImage = _PILPhoto
    sys.modules["PIL.ImageTk"].BitmapImage = _PILPhoto
    me.__all__ = [n for n, o in list(me.__dict__.items()) if not n.startswith("_") and not isinstance(o, types.ModuleType)
                  and n not in ("wantobjects", "runner", "ttk_Button")
                  and not n.startswith("ttk_")]
    me.Widget = Misc; me.BaseWidget = Misc; me.Wm = _Win; me.Pack = me.Place = me.Grid = Misc
    me.XView = me.YView = _Scr; me.CallWrapper = object; me.EventType = str
    me.image_names = image_names; me.image_types = image_types
