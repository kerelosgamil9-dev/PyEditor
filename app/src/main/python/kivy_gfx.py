"""kivy.graphics emulation: Canvas + Color / Rectangle / Ellipse / Line / Triangle / ... drawn on a tk.Canvas layer."""
import math
import kivyshim as K
from kivyshim import (EventDispatcher, Property, NumericProperty, ListProperty, BooleanProperty, StringProperty,
                      ReferenceListProperty, _hex, _st, Clock)

_STACK = []          # groups opened with "with canvas:"


class _M:
    """Maps Kivy (y up, window-ish) coordinates to the tk canvas of one widget."""
    def __init__(self, widget):
        self.H = float(widget.height or 0); self.wx = float(widget.x); self.wy = float(widget.y)
        self.bg = _st["clear"]
    def xy(self, x, y): return (x - self.wx, self.H - (y - self.wy))
    def box(self, x, y, w, h):
        x1 = x - self.wx; y2 = self.H - (y - self.wy); return (x1, y2 - h, x1 + w, y2)
    def pts(self, p):
        out = []
        for i in range(0, len(p) - 1, 2): out.extend(self.xy(p[i], p[i + 1]))
        return out


def _col(c, bg):
    r, g, b = [float(c[i]) for i in range(3)]
    a = float(c[3]) if len(c) > 3 else 1.0
    if a < 1.0:
        r = r * a + bg[0] * (1 - a); g = g * a + bg[1] * (1 - a); b = b * a + bg[2] * (1 - a)
    return _hex((r, g, b))


class _Group:
    """List of instructions; usable as 'with group:'"""
    def __init__(self, canvas):
        self._canvas = canvas; self.items = []
    def add(self, ins):
        if ins in self.items: return
        self.items.append(ins); ins._group = self; self._canvas._dirty()
        return ins
    def remove(self, ins):
        if ins in self.items: self.items.remove(ins); self._canvas._dirty()
    def clear(self):
        for i in self.items: i._group = None
        self.items = []; self._canvas._dirty()
    def insert(self, idx, ins): self.items.insert(idx, ins); ins._group = self; self._canvas._dirty()
    def __enter__(self): _STACK.append(self); return self
    def __exit__(self, *a): _STACK.pop()
    def _dirty(self): self._canvas._dirty()
    def __iter__(self): return iter(self.items)
    def __len__(self): return len(self.items)


class Canvas(_Group):
    def __init__(self, widget=None):
        self.widget = widget; self._canvas = self; self.items = []
        self.before = _Group(self); self.after = _Group(self); self._pending = False
    def empty(self): return not (self.items or self.before.items or self.after.items)
    def _all(self): return list(self.before.items) + list(self.items) + list(self.after.items)
    def ask_update(self): self._dirty()
    def clear(self):
        _Group.clear(self); self.before.clear(); self.after.clear()
    def _dirty(self):
        w = self.widget
        if w is None or w._w is None or self._pending: return
        self._pending = True
        Clock.schedule_once(self._flush, 0)
    def _flush(self, dt):
        self._pending = False
        w = self.widget
        if w is not None and w._w is not None: w._canvas_redraw()
    def _draw(self):
        w = self.widget
        cv = w.__dict__.get("_cv")
        if cv is None: return
        if w.width and w.height:
            try: cv.config(width=int(w.width), height=int(w.height))     # the page canvas must match the widget size
            except Exception: pass
        cv.delete("all")
        m = _M(w); st = {"c": (1, 1, 1, 1)}
        for ins in self._all():
            try: ins._render(cv, st, m)
            except Exception as e: print("canvas error:", type(ins).__name__, e)
    def background_color(self):
        """Color + Rectangle in the canvas -> a plain background (used for Label / Button / TextInput)."""
        col = None
        for ins in self._all():
            if isinstance(ins, Color): col = ins
            elif isinstance(ins, (Rectangle, RoundedRectangle)) and col is not None:
                return _col(col.rgba, _st["clear"])
        return None


class Instruction(EventDispatcher):
    def __init__(self, **kw):
        self.__dict__["_group"] = None
        EventDispatcher.__init__(self)
        self._apply_kw(kw)
        if _STACK: _STACK[-1].add(self)
    def _prop_changed(self, name, value):
        g = self.__dict__.get("_group")
        if g is not None: g._dirty()
    def _render(self, cv, st, m): pass


InstructionGroup = _Group


class Color(Instruction):
    r = NumericProperty(1); g = NumericProperty(1); b = NumericProperty(1); a = NumericProperty(1)
    rgba = ReferenceListProperty(r, g, b, a)
    rgb = ReferenceListProperty(r, g, b)
    hsv = Property(None)
    def __init__(self, *args, **kw):
        if args:
            args = list(args)
            if len(args) == 1 and isinstance(args[0], (list, tuple)): args = list(args[0])
            for n, v in zip("rgba", args): kw[n] = v
        Instruction.__init__(self, **kw)
    def _render(self, cv, st, m): st["c"] = (self.r, self.g, self.b, self.a)


class _Shape(Instruction):
    def _fill(self, st, m): return _col(st["c"], m.bg)


class Rectangle(_Shape):
    pos = ListProperty([0, 0]); size = ListProperty([100, 100]); source = StringProperty(""); texture = Property(None)
    def _render(self, cv, st, m):
        x1, y1, x2, y2 = m.box(self.pos[0], self.pos[1], self.size[0], self.size[1])
        cv.create_rectangle(x1, y1, x2, y2, fill=self._fill(st, m), outline="")


class RoundedRectangle(Rectangle):
    radius = ListProperty([10])
    def _render(self, cv, st, m):
        x1, y1, x2, y2 = m.box(self.pos[0], self.pos[1], self.size[0], self.size[1])
        r = self.radius[0] if self.radius else 10
        if isinstance(r, (list, tuple)): r = r[0]
        r = max(0, min(float(r), (x2 - x1) / 2.0, (y2 - y1) / 2.0))
        f = self._fill(st, m)
        if r <= 1:
            cv.create_rectangle(x1, y1, x2, y2, fill=f, outline=""); return
        cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=f, outline="")
        cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=f, outline="")
        d = 2 * r
        for (ax, ay) in ((x1, y1), (x2 - d, y1), (x1, y2 - d), (x2 - d, y2 - d)):
            cv.create_oval(ax, ay, ax + d, ay + d, fill=f, outline="")


class Ellipse(_Shape):
    pos = ListProperty([0, 0]); size = ListProperty([100, 100])
    angle_start = NumericProperty(0); angle_end = NumericProperty(360); source = StringProperty("")
    def _render(self, cv, st, m):
        x1, y1, x2, y2 = m.box(self.pos[0], self.pos[1], self.size[0], self.size[1])
        f = self._fill(st, m)
        if abs(self.angle_end - self.angle_start) >= 360: cv.create_oval(x1, y1, x2, y2, fill=f, outline="")
        else: cv.create_arc(x1, y1, x2, y2, start=90 - self.angle_end, extent=self.angle_end - self.angle_start, style="pieslice", fill=f, outline="")


class Line(_Shape):
    points = ListProperty([]); width = NumericProperty(1); close = BooleanProperty(False)
    circle = Property(None); ellipse = Property(None); rectangle = Property(None); rounded_rectangle = Property(None)
    dash_length = NumericProperty(0); dash_offset = NumericProperty(0)
    cap = Property("round"); joint = Property("round")
    def _render(self, cv, st, m):
        f = self._fill(st, m); w = max(1, float(self.width))
        if self.circle:
            cx, cy, r = self.circle[:3]
            x1, y1, x2, y2 = m.box(cx - r, cy - r, 2 * r, 2 * r)
            cv.create_oval(x1, y1, x2, y2, outline=f, width=w)
        if self.ellipse:
            x, y, ww, hh = self.ellipse[:4]; x1, y1, x2, y2 = m.box(x, y, ww, hh)
            cv.create_oval(x1, y1, x2, y2, outline=f, width=w)
        for r4 in (self.rectangle, self.rounded_rectangle):
            if r4:
                x, y, ww, hh = r4[:4]; x1, y1, x2, y2 = m.box(x, y, ww, hh)
                cv.create_rectangle(x1, y1, x2, y2, outline=f, width=w)
        p = list(self.points)
        if len(p) >= 4:
            if self.close: p = p + p[:2]
            cv.create_line(*m.pts(p), fill=f, width=w, capstyle="round", joinstyle="round")


class Triangle(_Shape):
    points = ListProperty([0, 0, 0, 0, 0, 0])
    def _render(self, cv, st, m): cv.create_polygon(*m.pts(self.points), fill=self._fill(st, m), outline="")


class Quad(Triangle):
    points = ListProperty([0, 0, 0, 0, 0, 0, 0, 0])


class Point(_Shape):
    points = ListProperty([]); pointsize = NumericProperty(1)
    def _render(self, cv, st, m):
        f = self._fill(st, m); r = max(0.5, float(self.pointsize))
        p = m.pts(self.points)
        for i in range(0, len(p) - 1, 2): cv.create_oval(p[i] - r, p[i + 1] - r, p[i] + r, p[i + 1] + r, fill=f, outline="")


class _Noop(Instruction):
    angle = NumericProperty(0); origin = ListProperty([0, 0]); axis = ListProperty([0, 0, 1])
    x = NumericProperty(0); y = NumericProperty(0); z = NumericProperty(1); xyz = ListProperty([1, 1, 1])


class PushMatrix(_Noop): pass
class PopMatrix(_Noop): pass
class Rotate(_Noop): pass
class Scale(_Noop): pass
class Translate(_Noop): pass
class MatrixInstruction(_Noop): pass
class BindTexture(_Noop): pass


MODULES = {
    "kivy.graphics": dict(Canvas=Canvas, InstructionGroup=InstructionGroup, Color=Color, Rectangle=Rectangle,
                          RoundedRectangle=RoundedRectangle, Ellipse=Ellipse, Line=Line, Triangle=Triangle, Quad=Quad,
                          Point=Point, PushMatrix=PushMatrix, PopMatrix=PopMatrix, Rotate=Rotate, Scale=Scale,
                          Translate=Translate, MatrixInstruction=MatrixInstruction, BindTexture=BindTexture),
    "kivy.graphics.instructions": dict(Canvas=Canvas, InstructionGroup=InstructionGroup),
    "kivy.graphics.context_instructions": dict(Color=Color, PushMatrix=PushMatrix, PopMatrix=PopMatrix, Rotate=Rotate,
                                               Scale=Scale, Translate=Translate),
    "kivy.graphics.vertex_instructions": dict(Rectangle=Rectangle, RoundedRectangle=RoundedRectangle, Ellipse=Ellipse,
                                              Line=Line, Triangle=Triangle, Quad=Quad, Point=Point),
}
