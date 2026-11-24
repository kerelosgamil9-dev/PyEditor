"""Kivy emulation (basics): same Python API, widgets are drawn through tkshim in the WebView (tk.html).

Supported: App, Widget, Label, Button, TextInput, CheckBox, Switch, Slider, ProgressBar,
           BoxLayout, GridLayout, FloatLayout, properties, events (bind / on_<name>), Clock, dp/sp, Window.
Not supported yet: canvas drawing, KV language, ScrollView, Image, Popup, ScreenManager, touch events.
"""
import sys, time, types, math
import tkshim as tk
import runner

_MISSING = object()
_CLEAR = "rgba(0,0,0,0)"        # widgets are transparent (the window color shows through, like in Kivy)
_ALL = []                      # every realized widget (so a Window.clearcolor change can restyle them)
_st = {"app": None, "clear": (0, 0, 0, 1)}


def _reset():
    kv = sys.modules.get("kvlang")
    if kv is not None: kv.reset()
    del _ALL[:]
    _st.update(app=None, clear=(0, 0, 0, 1), host=None)
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


def _with_alpha(h, a):
    if a >= 1: return h
    return "rgba(%d,%d,%d,%.2f)" % (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), max(0.0, a))


_MK = None


def _markup_html(t):
    """Kivy markup ([b] [i] [u] [s] [sub] [sup] [color=] [size=] [font=] [ref=]) -> HTML for the label"""
    import re, html
    global _MK
    if _MK is None: _MK = re.compile(r"\[(/?)(b|i|u|s|sub|sup|color|size|font|font_family|ref|anchor)(?:=([^\]]*))?\]")
    def esc(x): return (html.escape(x, quote=False).replace("&amp;bl;", "[").replace("&amp;br;", "]").replace("&amp;amp;", "&")
                        .replace("\n", "<br>"))
    out = []; stack = []; pos = 0
    for m in _MK.finditer(t):
        out.append(esc(t[pos:m.start()])); pos = m.end()
        close, tag, arg = m.groups(); arg = (arg or "").strip()
        if close:
            if any(x[0] == tag for x in stack):
                while stack:
                    top = stack.pop(); out.append(top[1])
                    if top[0] == tag: break
            continue
        if tag in ("b", "i", "u", "s", "sub", "sup"): o, c = "<%s>" % tag, "</%s>" % tag
        elif tag == "color":
            a = arg.lstrip("#")
            if len(a) in (6, 8): a = "#" + a[:6]
            o, c = '<span style="color:%s">' % html.escape(a if a.startswith("#") else arg), "</span>"
        elif tag == "size":
            n = re.sub(r"[^0-9.]", "", arg) or "15"
            o, c = '<span style="font-size:%spx">' % n, "</span>"
        elif tag in ("font", "font_family"): o, c = '<span style="font-family:%s">' % html.escape(arg), "</span>"
        elif tag == "ref": o, c = '<span data-ref="%s" style="text-decoration:underline;cursor:pointer">' % html.escape(arg), "</span>"
        else: out.append('<a id="%s"></a>' % html.escape(arg)); continue
        out.append(o); stack.append((tag, c))
    out.append(esc(t[pos:]))
    while stack: out.append(stack.pop()[1])
    return "".join(out)


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


def _notifier(name):
    def deco(f):
        def g(self, *a, **k):
            r = f(self, *a, **k)
            o = self.__dict__.get("_owner")
            if o is not None: o._changed(self.__dict__["_pname"], self)
            return r
        return g
    return deco


class _OList(list):
    """list that notifies its owner property (so  widget.pos += [..]  / points.append(..) work like in Kivy)"""
    def __init__(self, it=(), owner=None, pname=None):
        list.__init__(self, it); self.__dict__["_owner"] = owner; self.__dict__["_pname"] = pname
    for _n in ("append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse", "__setitem__", "__delitem__", "__iadd__", "__imul__"):
        locals()[_n] = _notifier(_n)(getattr(list, _n))
    del _n


class _ODict(dict):
    def __init__(self, it=(), owner=None, pname=None):
        dict.__init__(self, it); self.__dict__["_owner"] = owner; self.__dict__["_pname"] = pname
    for _n in ("update", "pop", "popitem", "clear", "setdefault", "__setitem__", "__delitem__"):
        locals()[_n] = _notifier(_n)(getattr(dict, _n))
    del _n


class ListProperty(Property):
    def __init__(self, defaultvalue=None, **kw): Property.__init__(self, defaultvalue or [], **kw)
    def _default(self, inst): return _OList(self.default, inst, self.name)
    def _conv(self, inst, v): return _OList(v, inst, self.name) if isinstance(v, (list, tuple)) else v


class DictProperty(Property):
    def __init__(self, defaultvalue=None, **kw): Property.__init__(self, defaultvalue or {}, **kw)
    def _default(self, inst): return _ODict(self.default, inst, self.name)
    def _conv(self, inst, v): return _ODict(v, inst, self.name) if isinstance(v, dict) else v


_NAMED = {"red": (1, 0, 0, 1), "green": (0, 0.5, 0, 1), "lime": (0, 1, 0, 1), "blue": (0, 0, 1, 1), "white": (1, 1, 1, 1),
          "black": (0, 0, 0, 1), "yellow": (1, 1, 0, 1), "cyan": (0, 1, 1, 1), "magenta": (1, 0, 1, 1), "orange": (1, .65, 0, 1),
          "gray": (.5, .5, .5, 1), "grey": (.5, .5, .5, 1), "purple": (.5, 0, .5, 1), "pink": (1, .75, .8, 1),
          "brown": (.65, .16, .16, 1), "transparent": (0, 0, 0, 0)}


class ColorProperty(ListProperty):
    def __init__(self, defaultvalue=None, **kw):
        ListProperty.__init__(self, [1, 1, 1, 1], **kw)
        self.default = self._plain(defaultvalue if defaultvalue is not None else [1, 1, 1, 1])
    @staticmethod
    def _plain(v):
        if isinstance(v, str): v = _NAMED.get(v.lower()) or get_color_from_hex(v)
        v = list(v)
        return v + [1] if len(v) == 3 else v
    def _conv(self, inst, v):
        if isinstance(v, str):
            v = _NAMED.get(v.lower()) or get_color_from_hex(v)
        if isinstance(v, (list, tuple)) and len(v) == 3: v = list(v) + [1]
        return ListProperty._conv(self, inst, v)


class BoundedNumericProperty(NumericProperty):
    def __init__(self, defaultvalue=0, **kw):
        NumericProperty.__init__(self, defaultvalue); self.min = kw.get("min"); self.max = kw.get("max")
    def _conv(self, inst, v):
        v = _num(v)
        if v is not None:
            if self.min is not None and v < self.min: v = self.min
            if self.max is not None and v > self.max: v = self.max
        return v


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


class _Factory:
    """Factory.Label() / Factory.get('Label') / Factory.register(...). All widget classes register themselves."""
    _classes = {}
    def register(self, name, cls=None, **k):
        if cls is not None: self._classes[name] = cls
    def get(self, name):
        try: return self._classes[name]
        except KeyError: raise KeyError("Unknown class <%s> (Factory)" % name)
    def unregister(self, name): self._classes.pop(name, None)
    def __getattr__(self, name):
        try: return self._classes[name]
        except KeyError: raise AttributeError(name)


Factory = _Factory()


class EventDispatcher:
    __events__ = ()
    _DERIVED = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if not cls.__name__.startswith("_"): Factory._classes[cls.__name__] = cls

    def __init__(self, **kw):
        self.__dict__.setdefault("_obs", {})
        self._apply_kw(kw)

    def _apply_kw(self, kw):
        ev = type(self)._all_events()
        for k, v in kw.items():
            attr = getattr(type(self), k, None)
            if callable(v) and k.startswith("on_") and not isinstance(attr, Property):
                if k in ev or attr is None or not isinstance(attr, Property):
                    if k in ev or k.startswith("on_touch"): self.bind(**{k: v}); continue
                    if isinstance(getattr(type(self), k[3:], None), Property): self.bind(**{k[3:]: v}); continue
            if isinstance(attr, Property) or attr is not None or k == "id":
                try: setattr(self, k, v)
                except AttributeError: pass

    def setter(self, name): return lambda inst, v: setattr(self, name, v)
    def getter(self, name): return lambda inst: getattr(self, name)
    def get_property_observers(self, name): return list(self.__dict__.get("_obs", {}).get(name, []))
    def properties(self): return {k: v for c in type(self).__mro__ for k, v in vars(c).items() if isinstance(v, Property)}

    def _notify(self, name, value):
        for cb in list(self.__dict__.get("_obs", {}).get(name, [])):
            tk._cb(cb, self, value)
        h = getattr(self, "on_" + name, None)
        if callable(h) and ("on_" + name) not in type(self)._all_events():
            tk._cb(h, self, value)

    def _changed(self, name, value):
        self._notify(name, value)
        for d in type(self)._DERIVED.get(name, ()):
            try: self._notify(d, getattr(self, d))
            except Exception: pass
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
class _Ids(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)


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
    _DERIVED = {"x": ("pos", "center_x", "right", "center"), "y": ("pos", "center_y", "top", "center"),
                "width": ("size", "center_x", "right", "center"), "height": ("size", "center_y", "top", "center")}

    def __init__(self, **kw):
        d = self.__dict__
        d["_kids"] = []; d["_w"] = None; d["ids"] = _Ids(); d["_in_sync"] = False; d["_th"] = False
        EventDispatcher.__init__(self)
        Builder.apply(self)               # KV class rules first, then the keyword arguments win
        self._apply_kw(kw)
        self.on_kv_post(self)

    def on_kv_post(self, base_widget): pass
    def to_window(self, x, y, initial=True, relative=False): return (x, y)
    def to_widget(self, x, y, relative=False): return (x, y)
    def to_parent(self, x, y, relative=False): return (x, y)
    def to_local(self, x, y, relative=False): return (x, y)
    def get_parent_window(self): return Window
    def export_to_png(self, filename, *a, **k): print("[kivy] export_to_png is not supported in this editor")

    @property
    def canvas(self):
        c = self.__dict__.get("_canvas")
        if c is None:
            import kivy_gfx
            c = self.__dict__["_canvas"] = kivy_gfx.Canvas(self)
        return c

    # -- size_hint as a pair (a ReferenceListProperty that allows None)
    @property
    def size_hint(self): return [self.size_hint_x, self.size_hint_y]
    @size_hint.setter
    def size_hint(self, v): self.size_hint_x, self.size_hint_y = v

    @property
    def children(self): return self._kids[::-1]
    center_x = AliasProperty(lambda s: s.x + s.width / 2.0, lambda s, v: setattr(s, "x", v - s.width / 2.0))
    center_y = AliasProperty(lambda s: s.y + s.height / 2.0, lambda s, v: setattr(s, "y", v - s.height / 2.0))
    right = AliasProperty(lambda s: s.x + s.width, lambda s, v: setattr(s, "x", v - s.width))
    top = AliasProperty(lambda s: s.y + s.height, lambda s, v: setattr(s, "y", v - s.height))
    center = AliasProperty(lambda s: [s.center_x, s.center_y], lambda s, v: (setattr(s, "center_x", v[0]), setattr(s, "center_y", v[1])))

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
    def _make(self, master): return tk.Frame(master, bg=_CLEAR, bd=0, highlightthickness=0)
    def _cfg(self): return {}

    @property
    def _el(self): return self.__dict__.get("_outer") or self._w

    def _wants_canvas_layer(self):
        if type(self)._make is not Widget._make:
            c = self.__dict__.get("_canvas")       # Label / Button / TextInput...: only when the canvas has real shapes
            return c is not None and not c.empty() and not c.simple_bg()
        c = self.__dict__.get("_canvas")
        if c is not None and not c.empty(): return True
        cls = type(self)           # drawing widgets usually override the touch handlers: give them a canvas up front
        return cls.on_touch_down is not Widget.on_touch_down or cls.on_touch_move is not Widget.on_touch_move

    def _realize(self, master):
        d = self.__dict__
        d["_master"] = master
        if self._wants_canvas_layer():
            outer = tk.Frame(master, bg=_CLEAR, bd=0, highlightthickness=0)
            cv = tk.Canvas(outer, bg=_CLEAR, highlightthickness=0, bd=0)
            cv.place(relx=0, rely=0, relwidth=1, relheight=1)
            d["_outer"] = outer; d["_cv"] = cv
            if type(self)._make is Widget._make:
                inner = tk.Frame(outer, bg="rgba(0,0,0,0)", bd=0, highlightthickness=0)
            else:
                inner = self._make(outer)            # the real label / button on top of the drawing
            inner.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._w = inner
        else:
            d["_outer"] = None; d["_cv"] = None
            self._w = self._make(master)
        _ALL.append(self)
        self._built()
        self._hook_events()
        self._realize_kids()
        self._relayout()
        self._canvas_ready()

    def _realize_kids(self):
        for c in self._kids: c._realize(self._w)

    # real size from the page (Kivy widgets always know their size)
    def _hook_events(self):
        w = self._el
        w.bind("<Configure>", self._on_configure)
        cls = type(self)
        if (cls.on_touch_down is not Widget.on_touch_down or cls.on_touch_move is not Widget.on_touch_move
                or cls.on_touch_up is not Widget.on_touch_up
                or any(self.__dict__.get("_obs", {}).get(n) for n in ("on_touch_down", "on_touch_move", "on_touch_up"))):
            self._hook_touch()

    def _on_configure(self, e):
        wd, ht = int(e.width or 0), int(e.height or 0)
        if wd <= 0 or ht <= 0: return
        self.__dict__["_in_sync"] = True
        try:
            if self.width != wd: self.width = wd
            if self.height != ht: self.height = ht
        finally: self.__dict__["_in_sync"] = False
        self._after_size()

    def _after_size(self):
        d = self.__dict__
        if self._kids and type(self)._relayout is Widget._relayout and d.get("_ls") != (self.width, self.height):
            d["_ls"] = (self.width, self.height); self._relayout()      # pixel positions depend on the size
        self._canvas_redraw()

    def _canvas_ready(self): self._canvas_redraw()
    def _canvas_redraw(self):
        c = self.__dict__.get("_canvas")
        if c is None or c.empty(): return
        if self.__dict__.get("_cv") is not None: c._draw(); return
        if self._wants_canvas_layer(): self._rebuild(); return        # drawing needs a canvas layer under the widget
        if self._w is not None and type(self)._make is not Widget._make:
            self._restyle_self()                                      # Label/Button...: simple canvas background -> color

    def _canvas_bg(self):
        c = self.__dict__.get("_canvas")
        if c is None or self.__dict__.get("_cv") is not None: return None
        return c.background_color()

    # touch (mouse) events -> on_touch_down / on_touch_move / on_touch_up
    def _hook_touch(self):
        d = self.__dict__
        if d.get("_th") or self._w is None: return
        d["_th"] = True
        w = self._el
        try: w.config(pvtouch=1)
        except Exception: pass
        w.bind("<ButtonPress-1>", lambda e: self._touch("on_touch_down", e), add="+")
        w.bind("<B1-Motion>", lambda e: self._touch("on_touch_move", e), add="+")
        w.bind("<ButtonRelease-1>", lambda e: self._touch("on_touch_up", e), add="+")

    def _touch(self, name, e):
        self.dispatch(name, _mk_touch(self, e, name))

    def bind(self, **kw):
        EventDispatcher.bind(self, **kw)
        if self._w is not None and any(k.startswith("on_touch") for k in kw): self._hook_touch()

    def on_touch_down(self, touch): return False
    def on_touch_move(self, touch): return False
    def on_touch_up(self, touch): return False

    def _built(self): pass

    def _unrealize(self):
        el = self._el
        self._unrealize_only(False)
        if el is not None:
            try: el.destroy()
            except Exception: pass

    def _unrealize_only(self, kids=True):
        d = self.__dict__
        self._w = None; d["_outer"] = None; d["_cv"] = None; d["_th"] = False
        if self in _ALL: _ALL.remove(self)
        for c in self._kids: c._unrealize_only()

    def _rebuild(self):
        """Re-create the tk widgets (needed when a canvas layer becomes necessary)."""
        d = self.__dict__
        m = d.get("_master")
        if self._w is None or m is None: return
        p = self.parent
        self._unrealize(); self._realize(m)
        if p is not None and p._w is not None: p._relayout()
        elif m is _st.get("host"): self._el.grid(row=0, column=0, sticky="nsew")

    def _restyle(self):
        if self._w is not None:
            c = self._cfg()
            if c: self._w.config(**c)
        for k in self._kids: k._restyle()

    def _prop_changed(self, name, value):
        if self._w is None: return
        if name in self._LAYOUT and not self.__dict__.get("_in_sync"):
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
            c._el.place(**_place_args(c, self))


def _place_args(c, parent=None):
    """FloatLayout style placement from size_hint / pos_hint (or the pixel pos when there is no pos_hint)."""
    ph = c.pos_hint or {}
    shx, shy = c.size_hint_x, c.size_hint_y
    a = {}
    if shx is not None: a["relwidth"] = float(shx)
    else: a["width"] = max(1, int(c.width))
    if shy is not None: a["relheight"] = float(shy)
    else: a["height"] = max(1, int(c.height))
    if not ph and (c.x or c.y) and parent is not None and parent.height:
        a["x"] = int(c.x); a["y"] = int(parent.height - c.y - c.height); a["anchor"] = "nw"
        return a
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
    minimum_width = NumericProperty(0)
    minimum_height = NumericProperty(0)
    minimum_size = ReferenceListProperty(minimum_width, minimum_height)
    _DERIVED = dict(Widget._DERIVED, minimum_width=("minimum_size",), minimum_height=("minimum_size",))
    _RELAY = ("padding", "spacing", "orientation", "cols", "rows", "row_default_height", "col_default_width",
              "row_force_default", "col_force_default", "anchor_x", "anchor_y")

    def do_layout(self, *a): self._relayout()
    def layout_hint_with_bounds(self, *a, **k): pass

    def _prop_changed(self, name, value):
        if name in self._RELAY and self._w is not None: self._relayout()
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
                cross = c.size_hint_x is None
                if cross: kw["sticky"] = _cross_sticky(c, True)
                _fix_size(c, "pvw", c.width if cross else None)
            else:
                kw = dict(row=0, column=i, sticky="nsew", padx=(pl if first else sp, pr if last else 0), pady=(pt, pb))
                self._w.columnconfigure(i, **_track(c.size_hint_x, c.width))
                cross = c.size_hint_y is None
                if cross: kw["sticky"] = _cross_sticky(c, False)
                _fix_size(c, "pvh", c.height if cross else None)
            c._el.grid(**kw)
        old = self.__dict__.get("_n", 0)
        for i in range(n + 1, old + 2):              # clear leftover tracks of removed children
            (self._w.rowconfigure if vert else self._w.columnconfigure)(i, weight=0, minsize=0)
        if vert: self._w.columnconfigure(0, weight=1)
        else:
            self._w.rowconfigure(0, weight=1)
            # all children have a fixed width: an empty stretching column keeps them at the left (Kivy), not centered
            spacer = not any(c.size_hint_x is not None for c in kids)
            self._w.columnconfigure(n, weight=1 if spacer else 0, minsize=0)
        self.__dict__["_n"] = n
        # minimum size (used with ScrollView: height: self.minimum_height)
        if vert:
            mh = pt + pb + sp * max(0, n - 1) + sum((c.height or 0) for c in kids if c.size_hint_y is None)
            mw = pl + pr + max([c.width for c in kids if c.size_hint_x is None] or [0])
        else:
            mw = pl + pr + sp * max(0, n - 1) + sum((c.width or 0) for c in kids if c.size_hint_x is None)
            mh = pt + pb + max([c.height for c in kids if c.size_hint_y is None] or [0])
        self.minimum_width, self.minimum_height = mw, mh


def _cross_sticky(c, vert):
    ph = c.pos_hint or {}
    if vert:      # fixed width inside a vertical box: left / center / right, stretch in height
        return "nsw" if "x" in ph else ("nse" if "right" in ph else "ns")
    return "wne" if "top" in ph else ("wse" if "y" in ph else "we")


def _fix_size(c, opt, v):
    el = c._el
    if el is None: return
    key = "_fx_" + opt
    val = int(v) if v else 0
    if c.__dict__.get(key) == val: return
    c.__dict__[key] = val
    try: el.config(**{opt: val})
    except Exception: pass


def _track(hint, size):
    if hint is None: return {"weight": -1, "minsize": int(size or 0)}      # -1 = exactly this many pixels
    return {"weight": max(1, int(float(hint) * 1000)), "minsize": 0}


class GridLayout(Layout):
    cols = NumericProperty(None)
    rows = NumericProperty(None)
    row_default_height = NumericProperty(0)
    col_default_width = NumericProperty(0)
    row_force_default = BooleanProperty(False)
    col_force_default = BooleanProperty(False)

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
        rdh, cdw = float(self.row_default_height or 0), float(self.col_default_width or 0)
        rfd, cfd = bool(self.row_force_default), bool(self.col_force_default)
        ch = {}; rh = {}
        for i, c in enumerate(kids):
            r, col = divmod(i, cols)
            kw = dict(row=r, column=col, sticky="nsew",
                      padx=(pl if col == 0 else spx, pr if col == cols - 1 else 0),
                      pady=(pt if r == 0 else spy, pb if r == nrows - 1 else 0))
            c._el.grid(**kw)
            ch.setdefault(col, []).append(c); rh.setdefault(r, []).append(c)
        colw, rowh = {}, {}
        for col, cs in ch.items():
            fixed = [x for x in cs if x.size_hint_x is None]
            if cfd and cdw: self._w.columnconfigure(col, weight=-1, minsize=int(cdw)); colw[col] = cdw
            elif fixed: m = max(x.width for x in fixed); self._w.columnconfigure(col, weight=-1, minsize=int(m)); colw[col] = m
            else:
                self._w.columnconfigure(col, weight=max(1, int(min(float(x.size_hint_x) for x in cs) * 1000)), minsize=int(cdw))
                colw[col] = cdw
        for r, cs in rh.items():
            fixed = [x for x in cs if x.size_hint_y is None]
            if rfd and rdh: self._w.rowconfigure(r, weight=-1, minsize=int(rdh)); rowh[r] = rdh
            elif fixed: m = max(x.height for x in fixed); self._w.rowconfigure(r, weight=-1, minsize=int(m)); rowh[r] = m
            else:
                self._w.rowconfigure(r, weight=max(1, int(min(float(x.size_hint_y) for x in cs) * 1000)), minsize=int(rdh))
                rowh[r] = rdh
        oc, orr = self.__dict__.get("_nc", 0), self.__dict__.get("_nr", 0)
        for i in range(cols, oc): self._w.columnconfigure(i, weight=0, minsize=0)
        for i in range(nrows, orr): self._w.rowconfigure(i, weight=0, minsize=0)
        self.__dict__["_nc"], self.__dict__["_nr"] = cols, nrows
        self.minimum_width = pl + pr + spx * max(0, len(colw) - 1) + sum(colw.values())
        self.minimum_height = pt + pb + spy * max(0, len(rowh) - 1) + sum(rowh.values())


class Label(Widget):
    __events__ = ("on_ref_press",)
    _DERIVED = dict(Widget._DERIVED, text=("texture_size",), font_size=("texture_size",))
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

    def _bgc(self): return self._canvas_bg() or _CLEAR

    texture_size = AliasProperty(lambda s: [max(1.0, len(s.text or "") * (s.font_size or 15) * .55), (s.font_size or 15) * 1.35], None)

    def _shown(self):
        t = self.text
        if self.markup and "[" in t:
            import re
            t = re.sub(r"\[/?(?:b|i|u|s|sub|sup|font|size|color|ref|anchor|font_family|font_context|text_context|kerning)(?:=[^\]]*)?\]", "", t)
            t = t.replace("&bl;", "[").replace("&br;", "]").replace("&amp;", "&")
        return t

    def _cfg(self):
        h = str(self.halign)
        an = {"left": "w", "right": "e", "center": "c", "justify": "w"}.get(h, "c")
        va = str(self.valign)
        if va == "top": an = ("n" if an == "c" else "n" + an)
        elif va == "bottom": an = ("s" if an == "c" else "s" + an)
        c = {"text": self._shown(), "fg": _hex(self.color), "bg": self._bgc(), "font": self._font(),
             "anchor": an, "justify": {"left": "left", "right": "right"}.get(h, "center")}
        ts = self.text_size
        if ts and ts[0]: c["wraplength"] = int(ts[0])
        if self.markup and "[" in (self.text or ""): c["pvhtml"] = _markup_html(self.text)      # after "text": styled version
        return c

    def on_ref_press(self, *a): pass

    def _make(self, master):
        w = tk.Label(master, bd=0, **self._cfg())
        try: tk._pv[("ref", w._id)] = lambda e: self.dispatch("on_ref_press", e.get("ref"))
        except Exception: pass
        return w


class Button(Label):
    __events__ = ("on_press", "on_release")
    background_color = ListProperty([1, 1, 1, 1])
    background_normal = StringProperty("atlas://data/images/defaulttheme/button")
    background_down = StringProperty("atlas://data/images/defaulttheme/button_pressed")
    disabled_color = ListProperty([1, 1, 1, .3])
    state = Property("normal")

    def _bgc(self):
        bc = self.background_color
        a = float(bc[3]) if len(bc) > 3 else 1.0
        if self.background_normal == "": base = _hex(bc)                              # no image: the exact color
        else: base = self._canvas_bg() or _mix(bc, .3)
        return _with_alpha(base, a)

    def _cfg(self):
        c = Label._cfg(self)
        c.update(anchor="c", relief="flat", bd=0,
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


_GROUPS = {}


def _group_add(g, w):
    L = _GROUPS.setdefault(g, [])
    if w not in L: L.append(w)


class ToggleButton(Button):
    group = Property(None)
    def _press(self):
        if self.group is not None:
            _group_add(self.group, self)
            if self.state == "down": self.dispatch("on_press"); self.dispatch("on_release"); return     # radio: cannot untoggle
            for o in _GROUPS[self.group]:
                if o is not self and o.state == "down": o.state = "normal"
            self.state = "down"
        else:
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
    input_filter = Property(None)
    input_type = Property("text")
    font_name = StringProperty("Roboto")
    padding = Property([6, 6, 6, 6])
    cursor_pos = ListProperty([0, 0])
    selection_text = StringProperty("")
    write_tab = BooleanProperty(True)

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
        w = self._w
        w.bind("<FocusIn>", lambda e: self._focus_changed(True), add="+")
        w.bind("<FocusOut>", lambda e: self._focus_changed(False), add="+")
        self.__dict__["_hint_on"] = False
        self._show_hint()
        if self.focus: self._w.focus_set()

    def _show_hint(self):
        """emulate hint_text: gray text shown while the field is empty and unfocused"""
        if self._w is None or not self.hint_text: return
        if self.text == "" and not self.__dict__.get("_focused"):
            self.__dict__["_hint_on"] = True; self._lock = True
            try:
                if self.multiline: self._w.delete("1.0", "end"); self._w.insert("1.0", self.hint_text)
                else: self._var.set(self.hint_text)
                self._w.config(fg="#999999")
            finally: self._lock = False

    def _focus_changed(self, on):
        self.__dict__["_focused"] = on
        if on and self.__dict__.get("_hint_on"):
            self.__dict__["_hint_on"] = False; self._lock = True
            try:
                if self.multiline: self._w.delete("1.0", "end")
                else: self._var.set("")
                self._w.config(fg=_hex(self.foreground_color))
            finally: self._lock = False
        elif not on: self._show_hint()
        if self.focus != on: self.focus = on

    def _get_widget_text(self):
        if self.multiline: return self._w.get("1.0", "end-1c")
        return self._var.get()

    def _filtered(self, new):
        f, old = self.input_filter, self.text
        if not f or new == old: return new
        if f == "int": return "".join(ch for ch in new if ch.isdigit())
        if f == "float":
            out = ""; dot = False
            for ch in new:
                if ch.isdigit(): out += ch
                elif ch == "." and not dot: out += ch; dot = True
            return out
        if callable(f):
            if new.startswith(old): return old + (f(new[len(old):], False) or "")
            return f(new, False) or ""
        return new

    def _from_widget(self):
        if self._w is None or self._lock or self.__dict__.get("_hint_on"): return
        self._lock = True
        try:
            raw = self._get_widget_text(); t = self._filtered(raw)
            if t != raw:                                   # rejected characters: write the filtered text back
                if self.multiline: self._w.delete("1.0", "end"); self._w.insert("1.0", t)
                else: self._var.set(t)
            self.text = t
        finally: self._lock = False

    def _prop_changed(self, name, value):
        if self._w is not None and name == "text" and not self._lock:
            self.__dict__["_hint_on"] = False
            self._lock = True
            try:
                if self.multiline:
                    self._w.delete("1.0", "end"); self._w.insert("1.0", value)
                else:
                    self._var.set(value)
            finally: self._lock = False
        elif self._w is not None and name == "focus":
            if value and not self.__dict__.get("_focused"): self._w.focus_set()
        else: Widget._prop_changed(self, name, value)

    def on_text_validate(self, *a): pass
    def insert_text(self, s, from_undo=False): self.text += s
    def select_all(self): pass
    def copy(self, data=""): pass
    def paste(self): pass
    def cut(self): pass
    def do_backspace(self, from_undo=False, mode="bkspc"): self.text = self.text[:-1]
    def cancel_selection(self): pass
    def get_cursor_from_index(self, i): return (i, 0)


class CheckBox(Widget):
    active = BooleanProperty(False)
    group = Property(None)
    color = ListProperty([1, 1, 1, 1])
    size_hint_x = NumericProperty(1)

    def _cfg(self): return {"bg": _CLEAR, "activebackground": _CLEAR, "text": ""}

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
        if name == "active" and value and self.group is not None:
            _group_add(self.group, self)
            for o in _GROUPS[self.group]:
                if o is not self and o.active: o.active = False
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

    def _cfg(self): return {"bg": _CLEAR, "highlightthickness": 0}

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


class Touch:
    def __init__(self):
        self.x = self.y = self.ox = self.oy = 0.0; self.dx = self.dy = 0.0; self.pos = (0.0, 0.0)
        self.ud = {}; self.is_mouse_scrolling = False; self.button = "left"; self.is_touch = True
        self.is_double_tap = False; self.is_triple_tap = False; self.profile = ["pos"]; self.uid = id(self)
        self.grab_current = None; self.time_start = time.time(); self._rx = self._ry = 0.0
    def grab(self, w, exclusive=False): self.grab_current = w
    def ungrab(self, w): self.grab_current = None
    def push(self, *a): pass
    def pop(self, *a): pass
    def apply_transform_2d(self, f): return self
    def scale_for_screen(self, *a, **k): pass
    @property
    def sx(self): return self.x / float(max(1, tk._st["w"]))
    @property
    def sy(self): return self.y / float(max(1, tk._st["h"]))
    @property
    def spos(self): return (self.sx, self.sy)


def _mk_touch(widget, e, name):
    d = widget.__dict__
    h = float(widget.height or 0) or float(getattr(e, "height", 0) or 0)
    x, y = float(widget.x) + float(e.x), float(widget.y) + h - float(e.y)
    t = d.get("_tobj")
    rx, ry = float(getattr(e, "x_root", 0) or 0), float(getattr(e, "y_root", 0) or 0)
    if name == "on_touch_down" or t is None:
        t = d["_tobj"] = Touch(); t.ox, t.oy = x, y
    else:
        t.dx, t.dy = rx - t._rx, -(ry - t._ry)           # window coordinates: correct even if the widget moves
    t._rx, t._ry = rx, ry
    t.x, t.y = x, y; t.pos = (x, y)
    if name == "on_touch_up": d["_tobj"] = None
    return t


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

    def _load_kv(self):
        """Kivy loads <appname>.kv (class name without 'App', lowercased) or kv_file automatically."""
        import os
        names = []
        if self.kv_file: names.append(self.kv_file)
        base = type(self).__name__
        if base.endswith("App"): base = base[:-3]
        names.append(base.lower() + ".kv")
        dirs = [os.getcwd()]
        try:
            import runner
            sd = os.path.dirname(os.path.abspath(runner._SRC.get("path", ""))) if hasattr(runner, "_SRC") else ""
            if sd: dirs.append(sd)
        except Exception: pass
        for d in dirs:
            for n in names:
                p = n if os.path.isabs(n) else os.path.join(d, n)
                if os.path.isfile(p):
                    return Builder.load_file(p)
        return None

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
        kvroot = self._load_kv()
        r = self.build()
        if r is None: r = kvroot
        if r is not None: self.root = r
        if self.root is None:
            raise RuntimeError("build() must return a widget / لازم دالة build ترجّع ودجت")
        t = tk._st["root"] or tk.Tk()
        t.title(self.title)
        t.configure(bg=_hex(_st["clear"]))
        # the app lives in a "host" frame placed over the whole window, so overlays (Popup...) can be placed beside it
        host = tk.Frame(t, bg=_hex(_st["clear"]), bd=0, highlightthickness=0)
        host.place(relx=0, rely=0, relwidth=1, relheight=1)
        host.rowconfigure(0, weight=1); host.columnconfigure(0, weight=1)
        _st["host"] = host
        Window._hook_keys()
        self.root._realize(host)
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
            if _st.get("host") is not None: _st["host"].configure(bg=_hex(value))
            for w in list(_ALL):
                if w._w is None: continue
                try:
                    if type(w)._make is Widget._make: w._w.config(bg=_hex(value))
                    else: w._restyle_self()
                except Exception: pass
        EventDispatcher._changed(self, name, value)
    @property
    def size(self): return (tk._st["w"], tk._st["h"])
    @size.setter
    def size(self, v): pass
    dpi = 96.0
    density = 1.0
    top = 0
    left = 0
    def minimize(self): pass
    def maximize(self): pass
    def restore(self): pass
    def set_title(self, t):
        r = tk._st.get("root")
        if r is not None: r.title(t)
    @property
    def width(self): return tk._st["w"]
    @property
    def height(self): return tk._st["h"]
    def add_widget(self, w, *a):
        if _st["app"]: _st["app"].root.add_widget(w)
    def _hook_keys(self):
        r = tk._st.get("root")
        if r is None or self.__dict__.get("_kb"): return
        if not any(self.__dict__.get("_obs", {}).get(n) for n in ("on_key_down", "on_key_up", "on_keyboard")): return
        self.__dict__["_kb"] = True
        r.bind("<KeyPress>", lambda e: self._key(e, True))
        r.bind("<KeyRelease>", lambda e: self._key(e, False))
    def _key(self, e, down):
        names = {"Return": 13, "Escape": 27, "BackSpace": 8, "Tab": 9, "space": 32, "Left": 276, "Right": 275, "Up": 273, "Down": 274, "Delete": 127}
        ks = getattr(e, "keysym", "") or ""
        code = names.get(ks, ord(ks.lower()) if len(ks) == 1 else 0)
        cp = getattr(e, "char", "") or ""
        if down:
            self.dispatch("on_key_down", code, code, cp, [])
            self.dispatch("on_keyboard", code, code, cp, [])
        else: self.dispatch("on_key_up", code, code)
    def bind(self, **kw):
        EventDispatcher.bind(self, **kw)
        self._hook_keys()
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
    def _kv(self):
        import kvlang
        return kvlang
    def load_string(self, s, **k): return self._kv().load_string(s, **k)
    def load_file(self, f, **k): return self._kv().load_file(f, **k)
    def unload_file(self, f): return self._kv().unload_file(f)
    def apply(self, widget):
        kv = sys.modules.get("kvlang")
        if kv is not None and kv.RULES: kv.apply_rules(widget)


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
                                ReferenceListProperty=ReferenceListProperty, BoundedNumericProperty=BoundedNumericProperty,
                                ColorProperty=ColorProperty, VariableListProperty=ListProperty),
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
    import kivy_ui as U
    subs.update({
        "kivy.factory": dict(Factory=Factory),
        "kivy.uix.scrollview": dict(ScrollView=U.ScrollView),
        "kivy.uix.anchorlayout": dict(AnchorLayout=U.AnchorLayout),
        "kivy.uix.stacklayout": dict(StackLayout=U.StackLayout),
        "kivy.uix.relativelayout": dict(RelativeLayout=U.RelativeLayout),
        "kivy.uix.screenmanager": dict(Screen=U.Screen, ScreenManager=U.ScreenManager, ScreenManagerException=U.ScreenManagerException,
                                       NoTransition=U.NoTransition, SlideTransition=U.SlideTransition, SwapTransition=U.SwapTransition,
                                       FadeTransition=U.FadeTransition, WipeTransition=U.WipeTransition,
                                       FallOutTransition=U.FallOutTransition, RiseInTransition=U.RiseInTransition,
                                       CardTransition=U.CardTransition),
        "kivy.uix.modalview": dict(ModalView=U.ModalView),
        "kivy.uix.popup": dict(Popup=U.Popup),
        "kivy.uix.dropdown": dict(DropDown=U.DropDown),
        "kivy.uix.spinner": dict(Spinner=U.Spinner, SpinnerOption=U.SpinnerOption),
        "kivy.uix.tabbedpanel": dict(TabbedPanel=U.TabbedPanel, TabbedPanelItem=U.TabbedPanelItem, TabbedPanelHeader=U.TabbedPanelHeader),
        "kivy.uix.carousel": dict(Carousel=U.Carousel),
        "kivy.uix.image": dict(Image=U.Image, AsyncImage=U.AsyncImage),
        "kivy.uix.scatter": dict(Scatter=U.Scatter, ScatterPlane=U.ScatterPlane),
        "kivy.uix.accordion": dict(Accordion=U.Accordion, AccordionItem=U.AccordionItem),
        "kivy.uix.bubble": dict(Bubble=U.Bubble, BubbleButton=U.BubbleButton),
        "kivy.uix.pagelayout": dict(PageLayout=U.PageLayout),
        "kivy.uix.actionbar": dict(ActionBar=U.ActionBar, ActionView=U.ActionView, ActionPrevious=U.ActionPrevious,
                                   ActionButton=U.ActionButton, ActionToggleButton=U.ActionToggleButton, ActionSeparator=U.ActionSeparator,
                                   ActionGroup=U.ActionGroup, ActionOverflow=U.ActionOverflow, ActionItem=U.ActionItem, ActionCheck=U.ActionCheck),
        "kivy.uix.splitter": dict(Splitter=U.Splitter),
        "kivy.uix.codeinput": dict(CodeInput=U.CodeInput),
        "kivy.uix.colorpicker": dict(ColorPicker=U.ColorPicker),
        "kivy.uix.filechooser": dict(FileChooserListView=U.FileChooserListView, FileChooserIconView=U.FileChooserIconView, FileChooser=U.FileChooser),
        "kivy.uix.video": dict(Video=U.Video),
        "kivy.uix.videoplayer": dict(VideoPlayer=U.VideoPlayer),
        "kivy.uix.camera": dict(Camera=U.Camera),
        "kivy.uix.recycleview": dict(RecycleView=U.RecycleView),
        "kivy.uix.recycleboxlayout": dict(RecycleBoxLayout=U.RecycleBoxLayout),
        "kivy.uix.behaviors": dict(ButtonBehavior=U.ButtonBehavior, ToggleButtonBehavior=U.ToggleButtonBehavior,
                                   FocusBehavior=U.FocusBehavior, CompoundSelectionBehavior=U.CompoundSelectionBehavior,
                                   DragBehavior=U.DragBehavior, CoverBehavior=U.CoverBehavior, TouchRippleBehavior=U.TouchRippleBehavior),
    })
    for mod in ("kivy_gfx", "kivy_extra", "kivy_more"):
        try:
            M = __import__(mod)
            subs.update(M.MODULES)
        except ImportError: pass
        except Exception as _e: print("[kivy] extra module %s could not load: %s" % (mod, _e))
    for name, attrs in subs.items():
        parent = name.rsplit(".", 1)[0]
        if parent not in sys.modules: _m(parent, True)
        m = _m(name, **attrs)
        setattr(sys.modules[parent], name.rsplit(".", 1)[1], m)
    core = sys.modules.get("kivy.core") or _m("kivy.core", True)
    k.core = core
    try:
        import kivy_more as _KM
        _cwx = _KM.CORE_WINDOW
    except ImportError: _cwx = {}
    cw = _m("kivy.core.window", True, Window=Window, **_cwx)
    core.window = cw
    k.Logger = Logger
    k.kivy_data_dir = ""
