"""tkinter emulation: same API, widgets are drawn in a WebView (tk.html)."""
import sys, json, time, re, types, traceback
import runner

_C = dict(N="n", S="s", E="e", W="w", NE="ne", NW="nw", SE="se", SW="sw", NS="ns", EW="ew", NSEW="nsew",
          CENTER="center", END="end", INSERT="insert", SEL="sel", ALL="all", LEFT="left", RIGHT="right",
          TOP="top", BOTTOM="bottom", X="x", Y="y", BOTH="both", NONE="none", YES=1, NO=0, TRUE=True,
          FALSE=False, NORMAL="normal", DISABLED="disabled", ACTIVE="active", HIDDEN="hidden",
          HORIZONTAL="horizontal", VERTICAL="vertical", WORD="word", CHAR="char", RAISED="raised",
          SUNKEN="sunken", FLAT="flat", GROOVE="groove", RIDGE="ridge", SOLID="solid", SINGLE="single",
          BROWSE="browse", MULTIPLE="multiple", EXTENDED="extended")
globals().update(_C)
TkVersion = 8.6

class TclError(Exception):
    pass

_ops = []; _W = {}; _n = [0]; _after = []; _dlg = {}
_st = {"quit": False, "root": None, "w": 360, "h": 640, "aid": 0}

def _reset():
    del _ops[:]; _W.clear(); del _after[:]; _dlg.clear(); _n[0] = 0
    _st.update(quit=False, root=None, imgclosed=False)

def _send(*o): _ops.append(list(o))

def _flush():
    if _ops:
        s = json.dumps(_ops, default=str); del _ops[:]
        runner._IO.gui(s)

# ---------------- fonts ----------------
class Font:
    def __init__(self, root=None, font=None, family="Arial", size=10, weight="normal", slant="roman", underline=0, **k):
        self.d = _font(font) if font else {"f": family, "s": size, "w": "bold" if weight == "bold" else "", "i": slant == "italic", "u": bool(underline)}
    def configure(self, **k):
        if "size" in k: self.d["s"] = k["size"]
        if "family" in k: self.d["f"] = k["family"]
        if "weight" in k: self.d["w"] = "bold" if k["weight"] == "bold" else ""
    config = configure
    def measure(self, t): return int(len(str(t)) * abs(self.d["s"]) * 0.6)
    def metrics(self, *a): return 16
    def actual(self, *a): return self.d

def _font(f):
    if f is None: return None
    if isinstance(f, Font): return f.d
    if isinstance(f, str): f = f.split()
    f = list(f); d = {"f": "", "s": 10, "w": "", "i": False, "u": False}
    if f: d["f"] = str(f[0])
    if len(f) > 1:
        try: d["s"] = int(f[1])
        except Exception: pass
    rest = " ".join(str(x) for x in f[2:]).lower()
    d["w"] = "bold" if "bold" in rest else ""; d["i"] = "italic" in rest; d["u"] = "underline" in rest
    return d

# ---------------- variables ----------------
class Variable:
    _d = ""
    def __init__(self, master=None, value=None, name=None):
        self._v = self._d if value is None else value; self._ws = []; self._tr = []
    def get(self): return self._v
    def set(self, v):
        self._v = v
        for w in list(self._ws): w._vupd(v)
        for f in list(self._tr): f()
    def _link(self, w): self._ws.append(w)
    def trace_add(self, mode, cb):
        self._tr.append(lambda: cb("PY_VAR", "", "write")); return "trace"
    trace = trace_variable = lambda self, m, cb: self.trace_add(m, cb)

class StringVar(Variable):
    _d = ""
    def get(self): return str(self._v)

class IntVar(Variable):
    _d = 0
    def get(self):
        try: return int(float(self._v))
        except Exception: return 0

class DoubleVar(Variable):
    _d = 0.0
    def get(self):
        try: return float(self._v)
        except Exception: return 0.0

class BooleanVar(Variable):
    _d = False
    def get(self): return bool(self._v)

# ---------------- helpers ----------------
_ALIAS = {"background": "bg", "foreground": "fg", "borderwidth": "bd"}
_SKIP = ("image", "yscrollcommand", "xscrollcommand", "menu", "validatecommand", "validate", "vcmd",
         "invalidcommand", "style", "class_", "takefocus", "cursor", "compound", "bitmap")

def _eoff(v, i):
    if i in ("end", "insert"): return len(v)
    try: return max(0, min(len(v), int(i)))
    except Exception: return len(v)

def _toff(s, i):
    i = str(i); adj = 0
    m = re.match(r"^(.*?)([+-]\d+)c$", i)
    if m: i, adj = m.group(1), int(m.group(2))
    if i in ("end", "insert"): o = len(s)
    else:
        l, _, c = i.partition("."); lines = s.split("\n"); l = max(1, int(l or 1))
        if l > len(lines): o = len(s)
        else: o = sum(len(x) + 1 for x in lines[:l - 1]) + (len(lines[l - 1]) if c == "end" else int(c or 0))
    return max(0, min(len(s), o + adj))

def _parse(seq):
    seq = str(seq)
    if seq.startswith("<<"): return ("sel" if "Select" in seq else "none", "", set())
    mods = set(); rest = []; dbl = False
    for x in seq.strip("<>").split("-"):
        if x in ("Control", "Ctrl"): mods.add("control")
        elif x == "Shift": mods.add("shift")
        elif x in ("Alt", "Mod1", "Option"): mods.add("alt")
        elif x in ("Any", "Lock", "Triple", "Meta"): pass
        elif x == "Double": dbl = True
        elif x: rest.append(x)
    if not rest: return ("key", "", mods)
    a = rest[0]; n = rest[1] if len(rest) > 1 else "1"
    if rest[-1] == "Motion": return ("motion", "", mods)
    if a in ("Enter", "Leave", "FocusIn", "FocusOut"): return (a.lower(), "", mods)
    if a == "MouseWheel": return ("wheel", "", mods)
    if a in ("Button", "ButtonPress"): return ("dbl" + n if dbl else "b" + n, "", mods)
    if a == "ButtonRelease": return ("b" + n + "up", "", mods)
    if a.isdigit() and len(rest) == 1: return ("dbl" + a if dbl else "b" + a, "", mods)
    if a in ("Key", "KeyPress"): return ("key", n if len(rest) > 1 else "", mods)
    if a == "KeyRelease": return ("keyup", n if len(rest) > 1 else "", mods)
    return ("key", a, mods)

class Event:
    def __init__(self, **k): self.__dict__.update(k)

# ---------------- widgets ----------------
def _nop(self, *a, **k): return None

class Misc:
    _type = "frame"
    def __init__(self, master=None, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw)
        if self._type == "root":
            master = None; _st["root"] = self
        elif master is None:
            master = _st["root"] or Tk()
        _n[0] += 1; self._id = _n[0]
        self.master = master; self._kids = []; self._o = {}; self._cmd = None; self._var = None
        self._binds = {}; self._val = ""; self._sel = []; self._on = 1; self._off = 0; self._rv = ""; self._proto = {}
        _W[self._id] = self
        if master: master._kids.append(self)
        self._pre(o)
        _send("new", self._id, self._type, master._id if master else 0, self._cl(o))
    def _pre(self, o):
        if "onvalue" in o: self._on = o["onvalue"]
        if "offvalue" in o: self._off = o["offvalue"]
        if "value" in o and self._type == "radio": self._rv = o["value"]
        if self._type == "check": self._val = self._off
    def _cl(self, o):
        r = {}
        for k, v in o.items():
            k = _ALIAS.get(k, k)
            if k == "command": self._cmd = v; r["cmd"] = 1
            elif k in ("textvariable", "variable"):
                self._var = v; v._link(self); t = self._type
                if k == "textvariable":
                    if t in ("entry", "spin", "combo"): r["val"] = v.get(); self._val = v.get()
                    else: r["tv"] = v.get()
                else:
                    x = v._v; self._val = x
                    if t == "check": r["chk"] = (x == self._on)
                    elif t == "radio": r["chk"] = (str(x) == str(self._rv))
                    else: r["val"] = x
            elif k == "font": r[k] = _font(v)
            elif k == "value" and self._type == "progress": r["val"] = v; self._val = v
            elif k in _SKIP or v is None: pass
            elif isinstance(v, (int, float, str, bool)): r[k] = v
            elif isinstance(v, (list, tuple)): r[k] = [x if isinstance(x, (int, float, str, bool)) else str(x) for x in v]
            else: r[k] = str(v)
        self._o.update(r)
        return r
    def config(self, cnf=None, **kw):
        o = dict(cnf or {}); o.update(kw)
        if not o: return dict(self._o)
        self._pre(o); _send("cfg", self._id, self._cl(o))
    configure = config
    def __setitem__(self, k, v): self.config(**{k: v})
    def __getitem__(self, k): return self.cget(k)
    def cget(self, k): return self._o.get(_ALIAS.get(k, k), "")
    def keys(self): return list(self._o)
    # geometry managers
    def _mg(self, op, keys, cnf, kw):
        o = dict(cnf or {}); o.update(kw)
        r = {k: (list(o[k]) if isinstance(o[k], (tuple, list)) else o[k]) for k in keys if k in o}
        if "expand" in r: r["expand"] = r["expand"] not in (0, False, "0", "no", "false", "")
        _send(op, self._id, r)
    def pack(self, cnf=None, **kw): self._mg("pk", ("side", "fill", "expand", "anchor", "padx", "pady", "ipadx", "ipady"), cnf, kw)
    def grid(self, cnf=None, **kw): self._mg("gr", ("row", "column", "rowspan", "columnspan", "sticky", "padx", "pady", "ipadx", "ipady"), cnf, kw)
    def place(self, cnf=None, **kw): self._mg("pl", ("x", "y", "relx", "rely", "width", "height", "relwidth", "relheight", "anchor"), cnf, kw)
    pack_configure = pack; grid_configure = grid; place_configure = place
    def pack_forget(self): _send("fg", self._id)
    grid_forget = place_forget = grid_remove = pack_forget
    pack_propagate = grid_propagate = propagate = _nop
    def _cc(self, k, i, kw):
        for x in (i if isinstance(i, (list, tuple)) else [i]): _send("cc", self._id, k, int(x), kw.get("weight", 0) or 0)
    def columnconfigure(self, i, cnf=None, **kw): self._cc("c", i, dict(cnf or {}, **kw))
    def rowconfigure(self, i, cnf=None, **kw): self._cc("r", i, dict(cnf or {}, **kw))
    grid_columnconfigure = columnconfigure; grid_rowconfigure = rowconfigure
    # misc
    def destroy(self):
        for k in list(self._kids): k.destroy()
        if self.master and self in self.master._kids: self.master._kids.remove(self)
        _W.pop(self._id, None); _send("del", self._id)
        if self._type == "root": _st["quit"] = True
    def focus_set(self): _send("foc", self._id)
    focus = focus_force = focus_set
    def bind(self, seq=None, func=None, add=None):
        if func is None: return self._binds.get(seq)
        self._binds[seq] = func; c = _parse(seq)[0]
        if c not in ("none", "sel"): _send("bind", self._id, c)
        return seq
    def bind_all(self, seq, func, add=None): (_st["root"] or self).bind(seq, func, add)
    bind_class = lambda self, cls, seq, func, add=None: None
    def unbind(self, seq, *a): self._binds.pop(seq, None)
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
    def winfo_children(self): return list(self._kids)
    def winfo_width(self): return _st["w"]
    winfo_reqwidth = winfo_screenwidth = winfo_width
    def winfo_height(self): return _st["h"]
    winfo_reqheight = winfo_screenheight = winfo_height
    def winfo_exists(self): return 1 if self._id in _W else 0
    def winfo_toplevel(self): return _st["root"]
    winfo_x = winfo_y = winfo_rootx = winfo_rooty = lambda self: 0
    event_generate = option_add = tkraise = lift = lower = grab_set = grab_release = _nop
    # internal event handling
    def _vset(self, v):
        self._val = v
        if self._var is not None:
            self._var._v = v
            for w in list(self._var._ws):
                if w is not self: w._vupd(v)
            for f in list(self._var._tr): f()
    def _vupd(self, v):
        t = self._type
        if t == "check": _send("cfg", self._id, {"chk": v == self._on})
        elif t == "radio": _send("cfg", self._id, {"chk": str(v) == str(self._rv)})
        elif t in ("entry", "scale", "spin", "combo", "progress"): self._val = v; _send("cfg", self._id, {"val": v})
        else: _send("cfg", self._id, {"tv": v})
    def _evval(self, v):
        t = self._type
        if t == "check": v = self._on if v else self._off
        elif t == "radio": v = self._rv
        elif t == "scale": v = float(v)
        self._vset(v)
        if t == "scale" and self._cmd: self._cmd(str(int(v)) if v == int(v) else str(v))
    def _invoke(self):
        if self._cmd: self._cmd()
    def _close(self):
        f = self._proto.get("WM_DELETE_WINDOW")
        if f: f()
        else: self.destroy()
    def _fire(self, e):
        for seq, f in list(self._binds.items()):
            cat, det, mods = _parse(seq)
            if cat != e.get("cat") or (det and det != e.get("k")) or not mods <= set(e.get("m", [])): continue
            f(Event(widget=self, x=e.get("x", 0), y=e.get("y", 0), char=e.get("c", ""), keysym=e.get("k", ""),
                    keycode=0, num=1, delta=e.get("d", 0), x_root=e.get("x", 0), y_root=e.get("y", 0)))

class _Win:
    def title(self, s=None): _send("cfg", self._id, {"title": str(s)})
    wm_title = title
    def geometry(self, s=None):
        m = re.match(r"(\d+)x(\d+)", str(s or ""))
        if m and self._type == "root": _send("win", {"geo": [int(m.group(1)), int(m.group(2))]})
        return "%dx%d+0+0" % (_st["w"], _st["h"])
    wm_geometry = geometry
    def protocol(self, name=None, func=None): self._proto[name] = func
    resizable = minsize = maxsize = attributes = wm_attributes = iconbitmap = iconphoto = _nop
    state = overrideredirect = withdraw = deiconify = iconify = transient = wm_state = _nop

class Tk(_Win, Misc):
    _type = "root"
    def __init__(self, *a, **k): Misc.__init__(self, None)

class Toplevel(_Win, Misc):
    _type = "top"

class Frame(Misc): _type = "frame"
class LabelFrame(Misc): _type = "lframe"
class Label(Misc): _type = "label"
class Message(Label): pass
class Scrollbar(Misc):
    _type = "scroll"
    set = _nop
class Menu:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None
class PanedWindow(Frame):
    add = _nop
class PhotoImage:
    def __init__(self, *a, **k): pass
    def width(self): return 0
    height = width
    def subsample(self, *a): return self
    zoom = subsample
BitmapImage = PhotoImage

class Button(Misc):
    _type = "button"
    def invoke(self): self._invoke()
    flash = _nop

class Entry(Misc):
    _type = "entry"
    def get(self): return str(self._val)
    def _set(self, s): self._vset(s); _send("cfg", self._id, {"val": s})
    def insert(self, i, s): v = self._val; p = _eoff(v, i); self._set(v[:p] + str(s) + v[p:])
    def delete(self, a, b=None):
        v = self._val; p = _eoff(v, a); q = p + 1 if b is None else _eoff(v, b); self._set(v[:p] + v[q:])
    icursor = selection_range = select_range = selection_clear = select_clear = _nop

class Spinbox(Entry):
    _type = "spin"

class Text(Misc):
    _type = "text"
    def get(self, a="1.0", b=None):
        s = self._val + "\n"; p = _toff(s, a)
        return s[p:p + 1] if b is None else s[p:_toff(s, b)]
    def _tset(self, v): self._vset(v); _send("cfg", self._id, {"val": v})
    def insert(self, i, t, *tags):
        v = self._val; p = min(_toff(v + "\n", i), len(v)); self._tset(v[:p] + str(t) + v[p:])
    def delete(self, a, b=None):
        v = self._val; s = v + "\n"; p = min(_toff(s, a), len(v)); q = min(_toff(s, b), len(v)) if b is not None else p + 1
        self._tset(v[:p] + v[q:])
    see = tag_configure = tag_config = tag_add = tag_remove = tag_delete = mark_set = yview = xview = edit_modified = _nop

class Checkbutton(Misc):
    _type = "check"
    def _setchk(self, on): self._vset(self._on if on else self._off); _send("cfg", self._id, {"chk": bool(on)})
    def select(self): self._setchk(True)
    def deselect(self): self._setchk(False)
    def toggle(self): self._setchk(self._val != self._on)
    def invoke(self): self.toggle(); self._invoke()

class Radiobutton(Misc):
    _type = "radio"
    def select(self): self._vset(self._rv); _send("cfg", self._id, {"chk": True})
    def deselect(self): _send("cfg", self._id, {"chk": False})
    def invoke(self): self.select(); self._invoke()

class Scale(Misc):
    _type = "scale"
    def _pre(self, o):
        Misc._pre(self, o); self._val = o.get("from_", 0); self._res = o.get("resolution", 1)
    def get(self):
        v = float(self._val)
        return int(v) if v == int(v) and float(self._res) >= 1 else v
    def set(self, v): self._vset(v); _send("cfg", self._id, {"val": v})

class Combobox(Misc):
    _type = "combo"
    def get(self): return str(self._val)
    def set(self, v): self._vset(v); _send("cfg", self._id, {"val": v})
    def current(self, i=None):
        vals = list(self._o.get("values", []))
        if i is None: return vals.index(self._val) if self._val in vals else -1
        self.set(vals[i])

class OptionMenu(Combobox):
    def __init__(self, master, variable, value, *values, **kw):
        variable.set(value)
        Misc.__init__(self, master, textvariable=variable, values=[value] + list(values), state="readonly")

class Progressbar(Misc):
    _type = "progress"
    def step(self, a=1):
        self._val = float(self._val or 0) + a; _send("cfg", self._id, {"val": self._val})
    def start(self, *a): _send("cfg", self._id, {"ind": True})
    def stop(self): _send("cfg", self._id, {"ind": False})

class Separator(Misc): _type = "sep"

class Listbox(Misc):
    _type = "list"
    def _pre(self, o): Misc._pre(self, o); self._items = []
    def _li(self, i): return len(self._items) if i in ("end", "end") else (0 if i == "active" else int(i))
    def _push(self): _send("items", self._id, self._items)
    def insert(self, i, *items):
        p = self._li(i); self._items[p:p] = [str(x) for x in items]; self._push()
    def delete(self, a, b=None):
        p = self._li(a); q = p + 1 if b is None else (len(self._items) if b == "end" else self._li(b) + 1)
        del self._items[p:q]; self._sel = []; self._push()
    def get(self, a, b=None):
        if b is None: return self._items[self._li(a)]
        return tuple(self._items[self._li(a):self._li(b) + 1])
    def curselection(self): return tuple(self._sel)
    def size(self): return len(self._items)
    def selection_set(self, a, b=None):
        p = self._li(a); q = p if b is None else self._li(b)
        self._sel = sorted(set(self._sel) | set(range(p, q + 1))); _send("lsel", self._id, self._sel)
    select_set = selection_set
    def selection_clear(self, a=0, b=None): self._sel = []; _send("lsel", self._id, [])
    select_clear = selection_clear
    def selection_includes(self, i): return int(i) in self._sel
    see = activate = _nop

class Canvas(Misc):
    _type = "canvas"
    def _pre(self, o): Misc._pre(self, o); self._it = 0; self._tags = {}
    def _add(self, kind, co, o):
        self._it += 1; i = self._it
        co = co[0] if len(co) == 1 and isinstance(co[0], (list, tuple)) else co
        r = {}
        for k, v in o.items():
            if k == "tags":
                for t in ([v] if isinstance(v, str) else v): self._tags.setdefault(t, []).append(i)
            elif k == "font": r[k] = _font(v)
            elif isinstance(v, (int, float, str, bool)): r[k] = v
        _send("cv", self._id, "add", i, kind, [float(x) for x in co], r); return i
    def create_line(self, *c, **o): return self._add("line", c, o)
    def create_rectangle(self, *c, **o): return self._add("rectangle", c, o)
    def create_oval(self, *c, **o): return self._add("oval", c, o)
    def create_polygon(self, *c, **o): return self._add("polygon", c, o)
    def create_text(self, *c, **o): return self._add("text", c, o)
    def _ids(self, t):
        if t in ("all", "all"): return list(range(1, self._it + 1))
        return [t] if isinstance(t, int) else list(self._tags.get(t, []))
    def delete(self, *t): _send("cv", self._id, "del", [i for x in t for i in self._ids(x)])
    def move(self, t, dx, dy): _send("cv", self._id, "mv", self._ids(t), dx, dy)
    def coords(self, t, *c):
        c = c[0] if len(c) == 1 and isinstance(c[0], (list, tuple)) else c
        for i in self._ids(t)[:1]: _send("cv", self._id, "co", i, [float(x) for x in c])
    def itemconfig(self, t, **o):
        r = {k: v for k, v in o.items() if isinstance(v, (int, float, str, bool))}
        _send("cv", self._id, "ic", self._ids(t), r)
    itemconfigure = itemconfig
    tag_bind = tag_raise = tag_lower = _nop

# ---------------- event loop ----------------
def _handle(e):
    t = e.get("t")
    if t == "size": _st["w"], _st["h"] = e["w"], e["h"]; return
    if t == "dlg": _dlg[e["req"]] = e["r"]; return
    if t == "err": print("[tk error]", e.get("m")); return
    if t == "imgclose": _st["imgclosed"] = True; return
    w = _W.get(e.get("id"))
    if w is None: return
    if t == "cmd": w._invoke()
    elif t == "val": w._evval(e["v"])
    elif t == "sel": w._sel = e["v"]
    elif t == "bind": w._fire(e)
    elif t == "close": w._close()

def _pump(t=0.05):
    _flush(); now = time.time()
    if _after: t = max(0, min(t, min(a[0] for a in _after) - now))
    e = runner._IO.nextEvent(int(t * 1000))
    if e:
        try: _handle(json.loads(e))
        except Exception: traceback.print_exc()
    now = time.time()
    for a in sorted([a for a in _after if a[0] <= now], key=lambda a: a[0]):
        if a in _after:
            _after.remove(a)
            try: a[2](*a[3])
            except Exception: traceback.print_exc()
    _flush()

def _mainloop():
    _st["quit"] = False; _flush()
    while not _st["quit"]: _pump(0.05)

def mainloop(n=0): _mainloop()

def _show_images(b64s):
    _st["imgclosed"] = False
    _send("img", b64s); _flush()
    while not _st["imgclosed"]: _pump(0.05)

def _ask(kind, title="", msg="", init=""):
    _n[0] += 1; r = _n[0]
    _send("dlg", r, kind, str(title), str(msg), str(init)); _flush()
    while r not in _dlg and not _st["quit"]: _pump(0.05)
    return _dlg.pop(r, None)

# ---------------- submodules ----------------
def _mod(name, **attrs):
    m = types.ModuleType("tkinter." + name); m.__dict__.update(attrs); sys.modules["tkinter." + name] = m; return m

def _install():
    me = sys.modules[__name__]
    if getattr(me, "_done", False): return
    me._done = True; me.__path__ = []; sys.modules["tkinter"] = me
    ok = lambda t="", m="", **k: (_ask("info", t, m), "ok")[1]
    me.messagebox = _mod("messagebox",
        showinfo=ok,
        showwarning=lambda t="", m="", **k: (_ask("warn", t, m), "ok")[1],
        showerror=lambda t="", m="", **k: (_ask("error", t, m), "ok")[1],
        askyesno=lambda t="", m="", **k: _ask("yesno", t, m) == "yes",
        askokcancel=lambda t="", m="", **k: _ask("okcancel", t, m) == "ok",
        askretrycancel=lambda t="", m="", **k: _ask("retrycancel", t, m) == "retry",
        askquestion=lambda t="", m="", **k: "yes" if _ask("yesno", t, m) == "yes" else "no",
        askyesnocancel=lambda t="", m="", **k: {"yes": True, "no": False}.get(_ask("yesnocancel", t, m)))
    def _int(t, p, **k):
        try: return int(_ask("string", t, p))
        except Exception: return None
    def _flt(t, p, **k):
        try: return float(_ask("string", t, p))
        except Exception: return None
    me.simpledialog = _mod("simpledialog", askstring=lambda t, p, **k: _ask("string", t, p, k.get("initialvalue", "")),
                           askinteger=_int, askfloat=_flt)
    me.filedialog = _mod("filedialog", askopenfilename=lambda **k: "", asksaveasfilename=lambda **k: "",
                         askdirectory=lambda **k: "", askopenfilenames=lambda **k: ())
    me.colorchooser = _mod("colorchooser", askcolor=lambda *a, **k: (None, None))
    me.font = _mod("font", Font=Font, BOLD="bold", ITALIC="italic", NORMAL="normal", families=lambda *a: ("Arial",),
                   nametofont=lambda n: Font())
    class Style:
        def __init__(self, *a): pass
        configure = map = theme_use = layout = lookup = _nop
    me.ttk = _mod("ttk", Button=Button, Label=Label, Entry=Entry, Frame=Frame, LabelFrame=LabelFrame, Labelframe=LabelFrame,
                  Checkbutton=Checkbutton, Radiobutton=Radiobutton, Combobox=Combobox, Progressbar=Progressbar,
                  Scale=Scale, Separator=Separator, Scrollbar=Scrollbar, Spinbox=Spinbox, Style=Style,
                  PanedWindow=PanedWindow, Menubutton=Button)
    me.scrolledtext = _mod("scrolledtext", ScrolledText=Text)
    me.constants = _mod("constants", **_C)
    me.__all__ = list(_C) + ["Tk", "Toplevel", "Frame", "LabelFrame", "Label", "Message", "Scrollbar", "Menu",
        "PanedWindow", "PhotoImage", "BitmapImage", "Button", "Entry", "Spinbox", "Text", "Checkbutton",
        "Radiobutton", "Scale", "Listbox", "Canvas", "OptionMenu", "StringVar", "IntVar", "DoubleVar",
        "BooleanVar", "Variable", "Event", "TclError", "mainloop", "TkVersion"]
    me.Labelframe = LabelFrame
