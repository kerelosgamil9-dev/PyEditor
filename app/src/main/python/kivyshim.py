"""Kivy emulation (basics): same Python API, widgets are drawn through tkshim in the WebView (tk.html).

Supported: App, Widget, Label, Button, TextInput, CheckBox, Switch, Slider, ProgressBar,
           BoxLayout, GridLayout, FloatLayout, properties, events (bind / on_<name>), Clock, dp/sp, Window.
Not supported yet: canvas drawing, KV language, ScrollView, Image, Popup, ScreenManager, touch events.
"""
import sys, time, types, math
import tkshim as tk
import runner

_MISSING = object()
_ALL = []                      # every realized widget (so a Window.clearcolor change can restyle them)
_st = {"app": None, "clear": (0, 0, 0, 1)}


def _reset():
    del _ALL[:]
    _st.update(app=None, clear=(0, 0, 0, 1))
    Clock._ev = []


# =====================================================================
#                           helpers
# =====================================================================
def _num(v, default=0):
    if v is None: return None
    if isinstance(v, (int, float)): return v
    s = str(v).strip().lower()
    for u in ("dp", "sp", "px", "pt"):
        if s.endswith(u): s = s[:-len(u)]
    try: return float(s)
    except ValueError: return default


def _hex(c, fallback="#ffffff"):
    try:
        r, g, b = [max(0, min(255, int(round(float(x) * 255)))) for x in list(c)[:3]]
        return "#%02x%02x%02x" % (r, g, b)
    except Exception:
        return fallback


def _mix(c, base):
    """Kivy tints the default (gray) button image with background_color."""
    try: return _hex([float(c[i]) * base for i in range(3)])
    except Exception: return _hex([base] * 3)


def _pad4(p):
    """padding -> (left, top, right, bottom)"""
    if isinstance(p, (int, float)): return (p, p, p, p)
    p = list(p or [0])
    if len(p) == 1: return (p[0],) * 4
    if len(p) == 2: return (p[0], p[1], p[0], p[1])
    return tuple((p + [0, 0, 0, 0])[:4])


# =====================================================================
#                           properties
# =====================================================================
class Property:
    def __init__(self, default=None, **kw):
        self.default = default; self.name = None; self.allownone = kw.get("allownone", True)
    def __set_name__(self, owner, name): self.name = name
    def _default(self, inst): return self.default
    def _conv(self, inst, v): return v
    def __get__(self, inst, owner=None):
        if inst is None: return self
        d = inst.__dict__.setdefault("_pv", {})
        if self.name not in d: d[self.name] = self._default(inst)
        return d[self.name]
    def __set__(self, inst, v):
        v = self._conv(inst, v)
        d = inst.__dict__.setdefault("_pv", {})
        old = d.get(self.name, _MISSING)
        if old is _MISSING: old = self._default(inst)
        d[self.name] = v
        try: same = old == v
        except Exception: same = False
        if not same: inst._changed(self.name, v)
    def bind(self, *a, **k): pass


class StringProperty(Property):
    def __init__(self, defaultvalue="", **kw): Property.__init__(self, defaultvalue, **kw)
    def _conv(self, inst, v): return "" if v is None else (v if isinstance(v, str) else str(v))


class NumericProperty(Property):
    def __init__(self, defaultvalue=0, **kw): Property.__init__(self, defaultvalue, **kw)
    def _conv(self, inst, v): return _num(v)


class BooleanProperty(Property):
    def __init__(self, defaultvalue=False, **kw): Property.__init__(self, defaultvalue, **kw)
    def _conv(self, inst, v): return bool(v)


class ObjectProperty(Property):
    def __init__(self, defaultvalue=None, **kw): Property.__init__(self, defaultvalue, **kw)


class ListProperty(Property):
    def __init__(self, defaultvalue=None, **kw): Property.__init__(self, defaultvalue or [], **kw)
    def _default(self, inst): return list(self.default)
    def _conv(self, inst, v): return list(v) if isinstance(v, (list, tuple)) else v


class DictProperty(Property):
    def __init__(self, defaultvalue=None, **kw): Property.__init__(self, defaultvalue or {}, **kw)
    def _default(self, inst): return dict(self.default)


class OptionProperty(Property):
    def __init__(self, defaultvalue=None, options=None, **kw): Property.__init__(self, defaultvalue, **kw)


class AliasProperty(Property):
    def __init__(self, getter=None, setter=None, bind=(), **kw):
        Property.__init__(self); self.g = getter; self.s = setter
    def __get__(self, inst, owner=None): return self if inst is None else self.g(inst)
    def __set__(self, inst, v):
        if self.s: self.s(inst, v)


class ReferenceListProperty(Property):
    """size = ReferenceListProperty(width, height) - read/write the parts as a list"""
    def __init__(self, *props, **kw): Property.__init__(self); self.parts = props
    def __get__(self, inst, owner=None):
        if inst is None: return self
        return [p.__get__(inst) for p in self.parts]
    def __set__(self, inst, v):
        for p, x in zip(self.parts, list(v)): p.__set__(inst, x)


class EventDispatcher:
    __events__ = ()

    def __init__(self, **kw):
        self.__dict__.setdefault("_obs", {})
        for k, v in kw.items():
            if isinstance(getattr(type(self), k, None), Property) or hasattr(type(self), k) or k.startswith("on_") or k in ("id",):
                try: setattr(self, k, v)
                except AttributeError: pass

    def _changed(self, name, value):
        for cb in list(self.__dict__.get("_obs", {}).get(name, [])):
            tk._cb(cb, self, value)
        h = getattr(self, "on_" + name, None)
        if callable(h) and ("on_" + name) not in type(self)._all_events():
            tk._cb(h, self, value)
        self._prop_changed(name, value)

    def _prop_changed(self, name, value): pass

    @classmethod
    def _all_events(cls):
        s = set()
        for c in cls.__mro__: s |= set(getattr(c, "__events__", ()) or ())
        return s

    def bind(self, **kw):
        o = self.__dict__.setdefault("_obs", {})
        for name, cb in kw.items(): o.setdefault(name, []).append(cb)
    fbind = bind

    def unbind(self, **kw):
        o = self.__dict__.setdefault("_obs", {})
        for name, cb in kw.items():
            if cb in o.get(name, []): o[name].remove(cb)
    funbind = unbind

    def dispatch(self, name, *a):
        for cb in list(self.__dict__.get("_obs", {}).get(name, [])):
            try:
                if cb(self, *a): return True
            except SystemExit:
                tk._st["quit"] = True; return True
            except BaseException as e:
                runner.report_exc(e)
        h = getattr(self, name, None)
        if callable(h):
            try: return h(*a)
            except SystemExit: tk._st["quit"] = True
            except BaseException as e: runner.report_exc(e)

    def register_event_type(self, name): pass
    def is_event_type(self, name): return name in type(self)._all_events()


# =====================================================================
#                           widgets
# =====================================================================
class Widget(EventDispatcher):
    x = NumericProperty(0); y = NumericProperty(0)
    width = NumericProperty(100); height = NumericProperty(100)
    size_hint_x = NumericProperty(1); size_hint_y = NumericProperty(1)
    pos_hint = DictProperty({})
    opacity = NumericProperty(1)
    disabled = BooleanProperty(False)
    pos = ReferenceListProperty(x, y)
    size = ReferenceListProperty(width, height)
    parent = ObjectProperty(None)
    _LAYOUT = ("size_hint_x", "size_hint_y", "width", "height", "pos_hint", "x", "y")

    def __init__(self, **kw):
        self.__dict__["_kids"] = []; self.__dict__["_w"] = None
        sh = kw.pop("size_hint", None)
        if sh is not None: self.size_hint_x, self.size_hint_y = sh
        EventDispatcher.__init__(self, **kw)

    # -- size_hint as a pair (a ReferenceListProperty that allows None)
    @property
    def size_hint(self): return [self.size_hint_x, self.size_hint_y]
    @size_hint.setter
    def size_hint(self, v): self.size_hint_x, self.size_hint_y = v

    @property
    def children(self): return self._kids[::-1]
    @property
    def center_x(self): return self.x + self.width / 2.0
    @property
    def center_y(self): return self.y + self.height / 2.0
    @property
    def right(self): return self.x + self.width
    @property
    def top(self): return self.y + self.height

    # -- tree
    def add_widget(self, w, index=0, **k):
        if w.parent is not None and w.parent is not self:
            raise RuntimeError("Widget already has a parent / الودجت دي متضافة لأب تاني")
        if w in self._kids: return
        w.parent = self
        self._kids.insert(len(self._kids) - int(index), w)
        if self._w is not None:
            w._realize(self._w); self._relayout()

    def remove_widget(self, w):
        if w not in self._kids: return
        self._kids.remove(w); w.parent = None; w._unrealize()
        if self._w is not None: self._relayout()

    def clear_widgets(self, children=None):
        for w in list(children if children is not None else self._kids): self.remove_widget(w)

    def walk(self, restrict=False, loopback=False):
        yield self
        for c in self.children:
            for x in c.walk(): yield x

    def get_root_window(self): return Window
    def collide_point(self, x, y): return self.x <= x <= self.right and self.y <= y <= self.top

    # -- realization (create the tk widgets)
    def _make(self, master): return tk.Frame(master, bg=_hex(_st["clear"]), bd=0, highlightthickness=0)
    def _cfg(self): return {}

    def _realize(self, master):
        self._w = self._make(master); _ALL.append(self)
        self._built()
        for c in self._kids: c._realize(self._w)
        self._relayout()

    def _built(self): pass

    def _unrealize(self):
        w = self._w; self._w = None
        if self in _ALL: _ALL.remove(self)
        for c in self._kids: c._unrealize_only()
        if w is not None:
            try: w.destroy()
            except Exception: pass

    def _unrealize_only(self):
        self._w = None
        if self in _ALL: _ALL.remove(self)
        for c in self._kids: c._unrealize_only()

    def _restyle(self):
        if self._w is not None:
            c = self._cfg()
            if c: self._w.config(**c)
        for k in self._kids: k._restyle()

    def _prop_changed(self, name, value):
        if self._w is None: return
        if name in self._LAYOUT:
            p = self.parent
            if p is not None and p._w is not None: p._relayout()
            if name in ("width", "height"): return
        elif name == "disabled" or name == "opacity": pass
        self._restyle_self()

    def _restyle_self(self):
        if self._w is not None:
            c = self._cfg()
            if c: self._w.config(**c)

    # -- children placement: free placement (Widget / FloatLayout)
    def _relayout(self):
        if self._w is None: return
        for c in self._kids:
            if c._w is None: continue
            c._w.place(**_place_args(c))


def _place_args(c):
    """FloatLayout style placement from size_hint / pos_hint."""
    ph = c.pos_hint or {}
    shx, shy = c.size_hint_x, c.size_hint_y
    a = {}
    if shx is not None: a["relwidth"] = float(shx)
    else: a["width"] = max(1, int(c.width))
    if shy is not None: a["relheight"] = float(shy)
    else: a["height"] = max(1, int(c.height))
    w = float(shx) if shx is not None else 0.0
    h = float(shy) if shy is not None else 0.0
    hv, vv = "w", "s"                      # default: bottom-left
    if "center_x" in ph: rx, hv = ph["center_x"], ""
    elif "right" in ph: rx, hv = ph["right"], "e"
    elif "x" in ph: rx = ph["x"]
    else: rx = 0
    if "center_y" in ph: ry, vv = 1 - ph["center_y"], ""
    elif "top" in ph: ry, vv = 1 - ph["top"], "n"
    elif "y" in ph: ry = 1 - ph["y"]
    else: ry = 1
    a["relx"] = float(rx); a["rely"] = float(ry)
    a["anchor"] = (vv + hv) or "center"
    return a


class FloatLayout(Widget): pass


class Layout(Widget):
    padding = Property([0])
    spacing = Property(0)
    _LAYOUT = Widget._LAYOUT + ()

    def _prop_changed(self, name, value):
        if name in ("padding", "spacing", "orientation", "cols", "rows") and self._w is not None: self._relayout()
        else: Widget._prop_changed(self, name, value)


class BoxLayout(Layout):
    orientation = Property("horizontal")

    def _relayout(self):
        if self._w is None: return
        kids = [c for c in self._kids if c._w is not None]
        vert = str(self.orientation).startswith("v")
        pl, pt, pr, pb = _pad4(self.padding)
        sp = _num(self.spacing) or 0
        n = len(kids)
        for i, c in enumerate(kids):
            first, last = i == 0, i == n - 1
            if vert:
                kw = dict(row=i, column=0, sticky="nsew", padx=(pl, pr), pady=(pt if first else sp, pb if last else 0))
                self._w.rowconfigure(i, **_track(c.size_hint_y, c.height))
            else:
                kw = dict(row=0, column=i, sticky="nsew", padx=(pl if first else sp, pr if last else 0), pady=(pt, pb))
                self._w.columnconfigure(i, **_track(c.size_hint_x, c.width))
            c._w.grid(**kw)
        old = self.__dict__.get("_n", 0)
        for i in range(n, old):                      # clear leftover tracks of removed children
            (self._w.rowconfigure if vert else self._w.columnconfigure)(i, weight=0, minsize=0)
        if vert: self._w.columnconfigure(0, weight=1)
        else: self._w.rowconfigure(0, weight=1)
        self.__dict__["_n"] = n


def _track(hint, size):
    if hint is None: return {"weight": 0, "minsize": int(size or 0)}
    return {"weight": max(1, int(float(hint) * 1000)), "minsize": 0}


class GridLayout(Layout):
    cols = NumericProperty(None)
    rows = NumericProperty(None)

    def _relayout(self):
        if self._w is None: return
        kids = [c for c in self._kids if c._w is not None]
        n = len(kids)
        cols = int(self.cols) if self.cols else 0
        rows = int(self.rows) if self.rows else 0
        if not cols and not rows: cols = 1
        if not cols: cols = int(math.ceil(n / float(rows)))
        nrows = int(math.ceil(n / float(cols))) if n else 0
        pl, pt, pr, pb = _pad4(self.padding)
        sp = self.spacing
        spx, spy = (sp[0], sp[1]) if isinstance(sp, (list, tuple)) and len(sp) > 1 else ((sp[0] if isinstance(sp, (list, tuple)) and sp else sp) or 0,) * 2
        ch = {}; rh = {}
        for i, c in enumerate(kids):
            r, col = divmod(i, cols)
            kw = dict(row=r, column=col, sticky="nsew",
                      padx=(pl if col == 0 else spx, pr if col == cols - 1 else 0),
                      pady=(pt if r == 0 else spy, pb if r == nrows - 1 else 0))
            c._w.grid(**kw)
            ch.setdefault(col, []).append(c); rh.setdefault(r, []).append(c)
        for col, cs in ch.items():
            fixed = [x for x in cs if x.size_hint_x is None]
            if fixed: self._w.columnconfigure(col, weight=0, minsize=int(max(x.width for x in fixed)))
            else: self._w.columnconfigure(col, weight=max(1, int(min(float(x.size_hint_x) for x in cs) * 1000)), minsize=0)
        for r, cs in rh.items():
            fixed = [x for x in cs if x.size_hint_y is None]
            if fixed: self._w.rowconfigure(r, weight=0, minsize=int(max(x.height for x in fixed)))
            else: self._w.rowconfigure(r, weight=max(1, int(min(float(x.size_hint_y) for x in cs) * 1000)), minsize=0)
        oc, orr = self.__dict__.get("_nc", 0), self.__dict__.get("_nr", 0)
        for i in range(cols, oc): self._w.columnconfigure(i, weight=0, minsize=0)
        for i in range(nrows, orr): self._w.rowconfigure(i, weight=0, minsize=0)
        self.__dict__["_nc"], self.__dict__["_nr"] = cols, nrows


class Label(Widget):
    text = StringProperty("")
    font_size = NumericProperty(15)
    color = ListProperty([1, 1, 1, 1])
    bold = BooleanProperty(False)
    italic = BooleanProperty(False)
    halign = Property("center")
    valign = Property("middle")
    text_size = ListProperty([None, None])
    markup = BooleanProperty(False)
    font_name = StringProperty("Roboto")
    padding = Property([0])
    size_hint_x = NumericProperty(1)

    def _font(self):
        st = " ".join(x for x, on in (("bold", self.bold), ("italic", self.italic)) if on)
        return (self.font_name if self.font_name != "Roboto" else "Roboto", -int(self.font_size or 15)) + ((st,) if st else ())

    def _bgc(self): return _hex(_st["clear"])

    def _cfg(self):
        h = str(self.halign)
        an = {"left": "w", "right": "e", "center": "center", "justify": "w"}.get(h, "center")
        va = str(self.valign)
        if va == "top": an = ("n" if an == "center" else "n" + an)
        elif va == "bottom": an = ("s" if an == "center" else "s" + an)
        c = {"text": self.text, "fg": _hex(self.color), "bg": self._bgc(), "font": self._font(),
             "anchor": an, "justify": {"left": "left", "right": "right"}.get(h, "center")}
        ts = self.text_size
        if ts and ts[0]: c["wraplength"] = int(ts[0])
        return c

    def _make(self, master): return tk.Label(master, bd=0, **self._cfg())


class Button(Label):
    __events__ = ("on_press", "on_release")
    background_color = ListProperty([1, 1, 1, 1])
    background_normal = StringProperty("atlas://data/images/defaulttheme/button")
    background_down = StringProperty("atlas://data/images/defaulttheme/button_pressed")
    disabled_color = ListProperty([1, 1, 1, .3])
    state = Property("normal")

    def _bgc(self):
        if self.background_normal == "": return _hex(self.background_color)      # no image: the exact color
        return _mix(self.background_color, .3)

    def _cfg(self):
        c = Label._cfg(self)
        c.update(anchor="center", relief="flat", bd=0,
                 activebackground=_mix(self.background_color, .18) if self.background_normal else _hex([x * .7 for x in self.background_color[:3]]),
                 activeforeground=_hex(self.color),
                 state="disabled" if self.disabled else "normal")
        if self.disabled: c["fg"] = _hex(self.disabled_color)
        return c

    def _make(self, master): return tk.Button(master, command=self._press, **self._cfg())

    def _press(self):
        self.state = "down"
        self.dispatch("on_press")
        self.state = "normal"
        self.dispatch("on_release")

    def on_press(self, *a): pass
    def on_release(self, *a): pass
    def trigger_action(self, duration=0.1): self._press()


class ToggleButton(Button):
    group = Property(None)
    def _press(self):
        self.state = "normal" if self.state == "down" else "down"
        self.dispatch("on_press"); self.dispatch("on_release")
    def _bgc(self): return _mix(self.background_color, .18 if self.state == "down" else .3)


class TextInput(Widget):
    __events__ = ("on_text_validate",)
    text = StringProperty("")
    hint_text = StringProperty("")
    multiline = BooleanProperty(True)
    password = BooleanProperty(False)
    readonly = BooleanProperty(False)
    font_size = NumericProperty(15)
    foreground_color = ListProperty([0, 0, 0, 1])
    background_color = ListProperty([1, 1, 1, 1])
    focus = BooleanProperty(False)
    halign = Property("left")

    def _cfg(self):
        c = {"fg": _hex(self.foreground_color), "bg": _hex(self.background_color),
             "font": ("Roboto", -int(self.font_size or 15)),
             "state": "disabled" if (self.disabled or self.readonly) else "normal"}
        if self.multiline and not self.password: c.pop("state")
        if not self.multiline and self.password: c["show"] = "*"
        return c

    def _make(self, master):
        self._lock = False
        if self.multiline:
            w = tk.Text(master, bd=1, relief="solid", wrap="word", **self._cfg())
            w.insert("1.0", self.text)
            w.bind("<KeyRelease>", lambda e: self._from_widget())
        else:
            self._var = tk.StringVar(value=self.text)
            w = tk.Entry(master, textvariable=self._var, bd=1, relief="solid", **self._cfg())
            self._var.trace_add("write", lambda *a: self._from_widget())
            w.bind("<Return>", lambda e: self.dispatch("on_text_validate"))
        return w

    def _built(self):
        if self.focus: self._w.focus_set()

    def _get_widget_text(self):
        if self.multiline: return self._w.get("1.0", "end-1c")
        return self._var.get()

    def _from_widget(self):
        if self._w is None or self._lock: return
        self._lock = True
        try: self.text = self._get_widget_text()
        finally: self._lock = False

    def _prop_changed(self, name, value):
        if self._w is not None and name == "text" and not self._lock:
            self._lock = True
            try:
                if self.multiline:
                    self._w.delete("1.0", "end"); self._w.insert("1.0", value)
                else:
                    self._var.set(value)
            finally: self._lock = False
        elif self._w is not None and name == "focus":
            if value: self._w.focus_set()
        else: Widget._prop_changed(self, name, value)

    def on_text_validate(self, *a): pass
    def insert_text(self, s): self.text += s
    def select_all(self): pass


class CheckBox(Widget):
    active = BooleanProperty(False)
    group = Property(None)
    color = ListProperty([1, 1, 1, 1])
    size_hint_x = NumericProperty(1)

    def _cfg(self): return {"bg": _hex(_st["clear"]), "activebackground": _hex(_st["clear"]), "text": ""}

    def _make(self, master):
        self._var = tk.IntVar(value=1 if self.active else 0); self._lock = False
        w = tk.Checkbutton(master, variable=self._var, bd=0, **self._cfg())
        self._var.trace_add("write", lambda *a: self._from_widget())
        return w

    def _from_widget(self):
        if self._lock: return
        self._lock = True
        try: self.active = bool(self._var.get())
        finally: self._lock = False

    def _prop_changed(self, name, value):
        if name == "active" and self._w is not None:
            if not self._lock:
                self._lock = True
                try: self._var.set(1 if value else 0)
                finally: self._lock = False
        else: Widget._prop_changed(self, name, value)


class Switch(CheckBox): pass


class Slider(Widget):
    min = NumericProperty(0); max = NumericProperty(100)
    value = NumericProperty(0); step = NumericProperty(0)
    orientation = Property("horizontal")

    def _cfg(self): return {"bg": _hex(_st["clear"]), "highlightthickness": 0}

    def _make(self, master):
        self._lock = False
        res = self.step if self.step else 0.01
        w = tk.Scale(master, from_=self.min, to=self.max, resolution=res, showvalue=0,
                     orient="vertical" if str(self.orientation).startswith("v") else "horizontal",
                     command=self._moved, **self._cfg())
        w.set(self.value)
        return w

    def _moved(self, v):
        if self._lock: return
        self._lock = True
        try:
            f = float(v)
            self.value = int(f) if (self.step and float(self.step) >= 1) else f
        finally: self._lock = False

    def _prop_changed(self, name, value):
        if name == "value" and self._w is not None:
            if not self._lock:
                self._lock = True
                try: self._w.set(value)
                finally: self._lock = False
        else: Widget._prop_changed(self, name, value)


class ProgressBar(Widget):
    max = NumericProperty(100); value = NumericProperty(0)

    def _make(self, master):
        return tk.ttk.Progressbar(master, maximum=self.max, value=self.value)

    def _prop_changed(self, name, value):
        if self._w is not None and name in ("value", "max"):
            self._w.config(maximum=self.max, value=self.value)
        else: Widget._prop_changed(self, name, value)


# =====================================================================
#                               App
# =====================================================================
class App(EventDispatcher):
    title = StringProperty("")
    icon = StringProperty("")
    root = ObjectProperty(None)
    kv_file = StringProperty("")

    def __init__(self, **kw):
        EventDispatcher.__init__(self, **kw)
        if not self.title: self.title = type(self).__name__.replace("App", "") or "App"
        self.__dict__["_opts"] = {}

    @classmethod
    def get_running_app(cls): return _st["app"]

    def build(self): return None
    def build_config(self, config): pass
    def build_settings(self, settings): pass
    def on_start(self): pass
    def on_stop(self): pass
    def on_pause(self): return True
    def on_resume(self): pass
    def load_config(self): return Config
    def open_settings(self, *a): pass
    def close_settings(self, *a): pass

    @property
    def user_data_dir(self):
        import os
        d = os.environ.get("PYVORA_DIR") or os.getcwd()
        return d

    def stop(self, *a):
        tk._st["quit"] = True

    def run(self):
        _st["app"] = self
        r = self.build()
        if r is not None: self.root = r
        if self.root is None:
            raise RuntimeError("build() must return a widget / لازم دالة build ترجّع ودجت")
        t = tk._st["root"] or tk.Tk()
        t.title(self.title)
        t.configure(bg=_hex(_st["clear"]))
        t.rowconfigure(0, weight=1); t.columnconfigure(0, weight=1)
        self.root._realize(t)
        self.root._w.grid(row=0, column=0, sticky="nsew")
        tk._cb(self.on_start)
        tk._mainloop()
        tk._cb(self.on_stop)


# =====================================================================
#                      Clock / metrics / window
# =====================================================================
class ClockEvent:
    def __init__(self, cb, timeout, interval):
        self.callback = cb; self.timeout = timeout; self.interval = interval
        self._id = None; self._t = time.time(); self.cancelled = False

    def _arm(self, ms):
        tk._st["aid"] += 1; self._id = "kvclock#%d" % tk._st["aid"]
        tk._after.append((time.time() + ms / 1000.0, self._id, self._fire, ()))

    def _fire(self):
        if self.cancelled: return
        now = time.time(); dt = now - self._t; self._t = now
        try: r = self.callback(dt)
        except SystemExit: tk._st["quit"] = True; return
        except BaseException as e: runner.report_exc(e); r = False
        if self.interval and r is not False and not self.cancelled: self._arm(self.timeout * 1000.0)
        elif self in Clock._ev: Clock._ev.remove(self)

    def cancel(self):
        self.cancelled = True
        for a in list(tk._after):
            if a[1] == self._id: tk._after.remove(a)
        if self in Clock._ev: Clock._ev.remove(self)

    def __call__(self, *a):
        if not self.cancelled: self._fire()


class _Clock:
    _ev = []
    def schedule_once(self, cb, timeout=0):
        e = ClockEvent(cb, float(timeout or 0), False); e._arm(e.timeout * 1000.0); self._ev.append(e); return e
    def schedule_interval(self, cb, timeout):
        e = ClockEvent(cb, float(timeout), True); e._arm(e.timeout * 1000.0); self._ev.append(e); return e
    def create_trigger(self, cb, timeout=0, interval=False):
        class _T:
            ev = None
            def __call__(s, *a):
                if s.ev is None or s.ev.cancelled or s.ev not in Clock._ev:
                    s.ev = Clock.schedule_once(cb, timeout)
            def cancel(s):
                if s.ev: s.ev.cancel()
        return _T()
    def unschedule(self, cb):
        for e in list(self._ev):
            if e is cb or e.callback == cb: e.cancel()
    def get_time(self): return time.time()
    get_boottime = get_time
    def tick(self): pass


Clock = _Clock()


def mainthread(f):
    def w(*a, **k): Clock.schedule_once(lambda dt: f(*a, **k), 0)
    return w


def dp(v): return float(_num(v) or 0)
sp = dp
def mm(v): return float(v) * 3.78
def cm(v): return float(v) * 37.8
def inch(v): return float(v) * 96.0
def pt(v): return float(v) * 1.33


class _Metrics:
    density = 1.0; dpi = 96.0; fontscale = 1.0


class _Win(EventDispatcher):
    clearcolor = ListProperty([0, 0, 0, 1])
    softinput_mode = Property("")
    fullscreen = Property(False)
    def _changed(self, name, value):
        if name == "clearcolor":
            _st["clear"] = tuple(value)
            r = tk._st.get("root")
            if r is not None: r.configure(bg=_hex(value))
            for w in list(_ALL):
                if w._w is None: continue
                try:
                    if type(w)._make is Widget._make: w._w.config(bg=_hex(value))
                    else: w._restyle_self()
                except Exception: pass
        EventDispatcher._changed(self, name, value)
    @property
    def size(self): return (tk._st["w"], tk._st["h"])
    @property
    def width(self): return tk._st["w"]
    @property
    def height(self): return tk._st["h"]
    def add_widget(self, w, *a):
        if _st["app"]: _st["app"].root.add_widget(w)
    def close(self): tk._st["quit"] = True
    def request_keyboard(self, *a, **k): return None
    def release_all_keyboards(self): pass


Window = _Win()


class _Cfg:
    def set(self, *a, **k): pass
    def get(self, *a, **k): return ""
    def getint(self, *a, **k): return 0
    def getboolean(self, *a, **k): return False
    def write(self): pass
    def adddefaultsection(self, *a): pass
    def setdefaults(self, *a): pass
    def read(self, *a): pass


Config = _Cfg()


class _Builder:
    def load_string(self, s, **k):
        raise NotImplementedError("لغة KV لسه مش مدعومة هنا - اكتب الواجهة بكود بايثون.\n"
                                  "KV language is not supported yet - build the UI in Python code.")
    load_file = load_string
    def unload_file(self, *a): pass


Builder = _Builder()


class _Logger:
    def _p(self, lv, m, *a): print("[%-7s] %s" % (lv, m))
    def info(self, m, *a, **k): self._p("INFO", m)
    def debug(self, m, *a, **k): self._p("DEBUG", m)
    def warning(self, m, *a, **k): self._p("WARNING", m)
    def error(self, m, *a, **k): self._p("ERROR", m)
    def exception(self, m, *a, **k): self._p("ERROR", m)
    def critical(self, m, *a, **k): self._p("CRITICAL", m)


Logger = _Logger()


def get_color_from_hex(h):
    h = str(h).lstrip("#")
    if len(h) == 3: h = "".join(c * 2 for c in h)
    if len(h) == 6: h += "ff"
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))


def get_hex_from_color(c):
    return "#" + "".join("%02x" % int(round(float(x) * 255)) for x in list(c)[:4])


# =====================================================================
#                        module registration
# =====================================================================
def _m(name, pkg=False, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs)
    if pkg: m.__path__ = []
    sys.modules[name] = m
    return m


def _install():
    if "kivy" in sys.modules and getattr(sys.modules["kivy"], "_pyvora", False): return
    k = _m("kivy", True, __version__="2.3.0", _pyvora=True, require=lambda *a, **kw: None)
    uix = _m("kivy.uix", True)
    k.uix = uix
    subs = {
        "kivy.app": dict(App=App),
        "kivy.event": dict(EventDispatcher=EventDispatcher),
        "kivy.properties": dict(Property=Property, StringProperty=StringProperty, NumericProperty=NumericProperty,
                                BooleanProperty=BooleanProperty, ObjectProperty=ObjectProperty, ListProperty=ListProperty,
                                DictProperty=DictProperty, OptionProperty=OptionProperty, AliasProperty=AliasProperty,
                                ReferenceListProperty=ReferenceListProperty, BoundedNumericProperty=NumericProperty,
                                ColorProperty=ListProperty, VariableListProperty=ListProperty),
        "kivy.clock": dict(Clock=Clock, mainthread=mainthread, ClockEvent=ClockEvent),
        "kivy.metrics": dict(dp=dp, sp=sp, mm=mm, cm=cm, inch=inch, pt=pt, Metrics=_Metrics()),
        "kivy.lang": dict(Builder=Builder),
        "kivy.config": dict(Config=Config, ConfigParser=_Cfg),
        "kivy.logger": dict(Logger=Logger),
        "kivy.utils": dict(get_color_from_hex=get_color_from_hex, get_hex_from_color=get_hex_from_color, platform="android"),
        "kivy.uix.widget": dict(Widget=Widget),
        "kivy.uix.layout": dict(Layout=Layout),
        "kivy.uix.label": dict(Label=Label),
        "kivy.uix.button": dict(Button=Button),
        "kivy.uix.togglebutton": dict(ToggleButton=ToggleButton),
        "kivy.uix.boxlayout": dict(BoxLayout=BoxLayout),
        "kivy.uix.gridlayout": dict(GridLayout=GridLayout),
        "kivy.uix.floatlayout": dict(FloatLayout=FloatLayout),
        "kivy.uix.textinput": dict(TextInput=TextInput),
        "kivy.uix.checkbox": dict(CheckBox=CheckBox),
        "kivy.uix.switch": dict(Switch=Switch),
        "kivy.uix.slider": dict(Slider=Slider),
        "kivy.uix.progressbar": dict(ProgressBar=ProgressBar),
    }
    for name, attrs in subs.items():
        m = _m(name, **attrs)
        setattr(sys.modules[name.rsplit(".", 1)[0]], name.rsplit(".", 1)[1], m)
    core = _m("kivy.core", True)
    k.core = core
    cw = _m("kivy.core.window", True, Window=Window)
    core.window = cw
    k.Logger = Logger
    k.kivy_data_dir = ""
