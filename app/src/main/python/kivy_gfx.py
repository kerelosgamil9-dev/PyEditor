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
    def tpts(self, p, st):
        """points in Kivy coords -> transformed by the current matrix -> canvas coords"""
        mt = st.get("m")
        out = []
        for i in range(0, len(p) - 1, 2):
            x, y = float(p[i]), float(p[i + 1])
            if mt is not None:
                x, y = mt[0] * x + mt[2] * y + mt[4], mt[1] * x + mt[3] * y + mt[5]
            out.extend(self.xy(x, y))
        return out


def _ident(st): return st.get("m") is None


def _mul(a, b):
    """affine a applied AFTER b  (a*b), tuples (a,b,c,d,e,f): x'=a*x+c*y+e ; y'=b*x+d*y+f"""
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _apply_mat(st, t):
    cur = st.get("m") or (1, 0, 0, 1, 0, 0)
    st["m"] = _mul(cur, t)


def _ellipse_pts(x, y, w, h, a0=0, a1=360, n=72):
    cx, cy, rx, ry = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
    pts = []
    steps = max(8, int(n * abs(a1 - a0) / 360.0))
    for i in range(steps + 1):
        a = math.radians(90 - (a0 + (a1 - a0) * i / float(steps)))     # Kivy angles: 0 = up, clockwise
        pts += [cx + rx * math.cos(a), cy + ry * math.sin(a)]
    return pts


def _rrect_pts(x, y, w, h, r, n=10):
    r = max(0.0, min(float(r), w / 2.0, h / 2.0))
    if r <= 0.5: return [x, y, x + w, y, x + w, y + h, x, y + h]
    pts = []
    for (cx, cy, a0) in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90.0 * i / n); pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return pts


def _bezier_pts(p, n=40):
    pts = []
    pairs = [(p[i], p[i + 1]) for i in range(0, len(p) - 1, 2)]
    if len(pairs) < 2: return list(p)
    for k in range(n + 1):
        t = k / float(n); q = pairs
        while len(q) > 1: q = [((1 - t) * q[i][0] + t * q[i + 1][0], (1 - t) * q[i][1] + t * q[i + 1][1]) for i in range(len(q) - 1)]
        pts += [q[0][0], q[0][1]]
    return pts


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
    def simple_bg(self):
        """True when the canvas is only a plain background (Color + one Rectangle): no drawing layer needed."""
        shapes = [i for i in self._all() if not isinstance(i, Color)]
        return len(shapes) <= 1 and all(isinstance(i, (Rectangle, RoundedRectangle)) for i in shapes)

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


class GraphicException(Exception): pass


def _hsv2rgb(h, s, v):
    import colorsys
    return colorsys.hsv_to_rgb(h, s, v)


class Color(Instruction):
    r = NumericProperty(1); g = NumericProperty(1); b = NumericProperty(1); a = NumericProperty(1)
    rgba = ReferenceListProperty(r, g, b, a)
    rgb = ReferenceListProperty(r, g, b)
    hsv = Property(None)
    def __init__(self, *args, **kw):
        mode = kw.pop("mode", "rgb")
        if args:
            args = list(args)
            if len(args) == 1 and isinstance(args[0], (list, tuple)): args = list(args[0])
            if mode == "hsv" and len(args) >= 3:
                args[:3] = list(_hsv2rgb(args[0], args[1], args[2]))
            for n, v in zip("rgba", args): kw[n] = v
        Instruction.__init__(self, **kw)
    def _render(self, cv, st, m): st["c"] = (self.r, self.g, self.b, self.a)


class _Shape(Instruction):
    def _fill(self, st, m): return _col(st["c"], m.bg)
    def _poly(self, cv, st, m, pts, fill=None, outline="", width=1):
        """draw a polygon given in Kivy coords through the current matrix"""
        if len(pts) < 6: return
        o = {"fill": fill or self._fill(st, m), "outline": outline}
        if outline: o["width"] = width
        cv.create_polygon(*m.tpts(pts, st), **o)


class Rectangle(_Shape):
    pos = ListProperty([0, 0]); size = ListProperty([100, 100]); source = StringProperty(""); texture = Property(None)
    tex_coords = ListProperty([0, 0, 1, 0, 1, 1, 0, 1])
    def _render(self, cv, st, m):
        x, y, w, h = self.pos[0], self.pos[1], self.size[0], self.size[1]
        if _ident(st):
            x1, y1, x2, y2 = m.box(x, y, w, h)
            cv.create_rectangle(x1, y1, x2, y2, fill=self._fill(st, m), outline="")
        else:
            self._poly(cv, st, m, [x, y, x + w, y, x + w, y + h, x, y + h])
        _draw_source(self, cv, st, m)


def _draw_source(ins, cv, st, m):
    """Rectangle/Ellipse/... with source='image.png' (axis-aligned only)"""
    src = getattr(ins, "source", "")
    if not src or not _ident(st): return
    try:
        import tkshim as tk
        im = tk.PhotoImage(file=src)
        keep = ins.__dict__.setdefault("_imgs", [])
        keep[:] = [im]
        x1, y1, x2, y2 = m.box(ins.pos[0], ins.pos[1], ins.size[0], ins.size[1])
        cv.create_image(x1, y1, image=im, anchor="nw")
    except Exception: pass


class BorderImage(Rectangle):
    border = ListProperty([10, 10, 10, 10])


class RoundedRectangle(Rectangle):
    radius = ListProperty([10])
    segments = NumericProperty(10)
    def _render(self, cv, st, m):
        x, y, w, h = self.pos[0], self.pos[1], self.size[0], self.size[1]
        r = self.radius[0] if self.radius else 10
        if isinstance(r, (list, tuple)): r = r[0]
        if not _ident(st):
            self._poly(cv, st, m, _rrect_pts(x, y, w, h, r)); return
        x1, y1, x2, y2 = m.box(x, y, w, h)
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
    segments = NumericProperty(180); texture = Property(None)
    def _render(self, cv, st, m):
        x, y, w, h = self.pos[0], self.pos[1], self.size[0], self.size[1]
        full = abs(self.angle_end - self.angle_start) >= 360
        if not _ident(st):
            pts = _ellipse_pts(x, y, w, h, self.angle_start, self.angle_end)
            if not full: pts = [x + w / 2.0, y + h / 2.0] + pts
            self._poly(cv, st, m, pts); return
        x1, y1, x2, y2 = m.box(x, y, w, h)
        f = self._fill(st, m)
        if full: cv.create_oval(x1, y1, x2, y2, fill=f, outline="")
        else: cv.create_arc(x1, y1, x2, y2, start=90 - self.angle_end, extent=self.angle_end - self.angle_start, style="pieslice", fill=f, outline="")


class Line(_Shape):
    points = ListProperty([]); width = NumericProperty(1); close = BooleanProperty(False)
    circle = Property(None); ellipse = Property(None); rectangle = Property(None); rounded_rectangle = Property(None)
    bezier = Property(None); dash_length = NumericProperty(0); dash_offset = NumericProperty(0)
    dashes = Property(None)
    cap = Property("round"); joint = Property("round")
    def _line(self, cv, st, m, pts, f, w, close=False):
        if len(pts) < 4: return
        if close: pts = list(pts) + list(pts[:2])
        o = dict(fill=f, width=w, capstyle="round", joinstyle="round")
        dl = float(self.dash_length or 0)
        if dl > 0: o["dash"] = (max(1, int(dl)), max(1, int(self.dash_offset or dl)))
        try: cv.create_line(*m.tpts(pts, st), **o)
        except TypeError:
            o.pop("dash", None); cv.create_line(*m.tpts(pts, st), **o)
    def _render(self, cv, st, m):
        f = self._fill(st, m); w = max(1, float(self.width))
        if self.circle:
            c = self.circle; cx, cy, r = c[0], c[1], c[2]
            a0 = c[3] if len(c) > 3 else 0; a1 = c[4] if len(c) > 4 else 360
            self._line(cv, st, m, _ellipse_pts(cx - r, cy - r, 2 * r, 2 * r, a0, a1), f, w)
        if self.ellipse:
            e = self.ellipse; a0 = e[4] if len(e) > 4 else 0; a1 = e[5] if len(e) > 5 else 360
            self._line(cv, st, m, _ellipse_pts(e[0], e[1], e[2], e[3], a0, a1), f, w)
        if self.rectangle:
            x, y, ww, hh = self.rectangle[:4]
            self._line(cv, st, m, [x, y, x + ww, y, x + ww, y + hh, x, y + hh], f, w, True)
        if self.rounded_rectangle:
            rr = self.rounded_rectangle; r = rr[4] if len(rr) > 4 else 10
            self._line(cv, st, m, _rrect_pts(rr[0], rr[1], rr[2], rr[3], r), f, w, True)
        if self.bezier:
            self._line(cv, st, m, _bezier_pts(list(self.bezier)), f, w)
        p = list(self.points)
        if len(p) >= 4: self._line(cv, st, m, p, f, w, bool(self.close))


class SmoothLine(Line): pass


class Bezier(_Shape):
    points = ListProperty([]); segments = NumericProperty(180); loop = BooleanProperty(False); dash_length = NumericProperty(0)
    def _render(self, cv, st, m):
        p = list(self.points)
        if len(p) < 4: return
        if self.loop: p = p + p[:2]
        pts = _bezier_pts(p, max(8, min(int(self.segments or 40), 120)))
        cv.create_line(*m.tpts(pts, st), fill=self._fill(st, m), width=1, capstyle="round", joinstyle="round")


class Triangle(_Shape):
    points = ListProperty([0, 0, 0, 0, 0, 0])
    def _render(self, cv, st, m):
        if _ident(st): cv.create_polygon(*m.pts(self.points), fill=self._fill(st, m), outline="")
        else: self._poly(cv, st, m, list(self.points))


class Quad(Triangle):
    points = ListProperty([0, 0, 0, 0, 0, 0, 0, 0])


class Point(_Shape):
    points = ListProperty([]); pointsize = NumericProperty(1)
    def _render(self, cv, st, m):
        f = self._fill(st, m); r = max(0.5, float(self.pointsize))
        p = m.tpts(self.points, st)
        for i in range(0, len(p) - 1, 2): cv.create_oval(p[i] - r, p[i + 1] - r, p[i] + r, p[i + 1] + r, fill=f, outline="")


class Mesh(_Shape):
    """vertices = [x, y, u, v, ...] ; indices = [i0, i1, i2, ...] ; mode = 'triangles' | 'triangle_fan' | 'triangle_strip' | 'line_strip' | 'line_loop' | 'lines' | 'points'"""
    vertices = ListProperty([]); indices = ListProperty([]); mode = Property("points"); texture = Property(None)
    source = StringProperty(""); fmt = Property(None)
    def _render(self, cv, st, m):
        v = list(self.vertices); n = len(v) // 4
        if n == 0: return
        pos = [(v[i * 4], v[i * 4 + 1]) for i in range(n)]
        idx = list(self.indices) or list(range(n))
        pts = [pos[i] for i in idx if 0 <= i < n]
        f = self._fill(st, m); mode = str(self.mode)
        def flat(ps): return [c for q in ps for c in q]
        if mode == "triangles":
            for i in range(0, len(pts) - 2, 3): self._poly(cv, st, m, flat(pts[i:i + 3]), f)
        elif mode == "triangle_fan":
            for i in range(1, len(pts) - 1): self._poly(cv, st, m, flat([pts[0], pts[i], pts[i + 1]]), f)
        elif mode == "triangle_strip":
            for i in range(len(pts) - 2): self._poly(cv, st, m, flat(pts[i:i + 3]), f)
        elif mode in ("line_strip", "line_loop"):
            ps = pts + ([pts[0]] if mode == "line_loop" and pts else [])
            if len(ps) >= 2: cv.create_line(*m.tpts(flat(ps), st), fill=f, width=1)
        elif mode == "lines":
            for i in range(0, len(pts) - 1, 2): cv.create_line(*m.tpts(flat(pts[i:i + 2]), st), fill=f, width=1)
        else:
            q = m.tpts(flat(pts), st)
            for i in range(0, len(q) - 1, 2): cv.create_oval(q[i] - 1, q[i + 1] - 1, q[i] + 1, q[i + 1] + 1, fill=f, outline="")


class Callback(Instruction):
    """Callback(func): func(instruction) is called each time the canvas is drawn"""
    reset_context = Property(False)
    def __init__(self, func=None, **kw):
        self.__dict__["_func"] = func
        Instruction.__init__(self, **kw)
    def _render(self, cv, st, m):
        f = self.__dict__.get("_func")
        if f is not None:
            try: f(self)
            except Exception as e: print("canvas Callback error:", e)


class _Noop(Instruction):
    angle = NumericProperty(0); origin = ListProperty([0, 0]); axis = ListProperty([0, 0, 1])
    x = NumericProperty(0); y = NumericProperty(0); z = NumericProperty(1); xyz = ListProperty([1, 1, 1])
    matrix = Property(None)
    def _render(self, cv, st, m): pass


class PushMatrix(_Noop):
    def _render(self, cv, st, m): st.setdefault("stack", []).append(st.get("m"))
class PopMatrix(_Noop):
    def _render(self, cv, st, m):
        s = st.get("stack")
        if s: st["m"] = s.pop()
class Rotate(_Noop):
    def __init__(self, *a, **kw):
        # Rotate(angle, x, y, z) / Rotate(angle=.., origin=(..), axis=(0,0,1))
        if a: kw.setdefault("angle", a[0])
        if len(a) >= 3: kw.setdefault("origin", [a[1], a[2]])
        _Noop.__init__(self, **kw)
    def _render(self, cv, st, m):
        ox, oy = (list(self.origin) + [0, 0])[:2]
        ax = list(self.axis) + [0, 0, 1]
        sgn = -1.0 if ax[2] < 0 else 1.0
        a = math.radians(float(self.angle)) * sgn
        c, s_ = math.cos(a), math.sin(a)
        _apply_mat(st, (1, 0, 0, 1, ox, oy)); _apply_mat(st, (c, s_, -s_, c, 0, 0)); _apply_mat(st, (1, 0, 0, 1, -ox, -oy))
class Scale(_Noop):
    def __init__(self, *a, **kw):
        if len(a) == 1: kw.setdefault("x", a[0]); kw.setdefault("y", a[0]); kw.setdefault("z", a[0])
        elif len(a) >= 2: kw.setdefault("x", a[0]); kw.setdefault("y", a[1])
        _Noop.__init__(self, **kw)
    def _render(self, cv, st, m):
        sx, sy = float(self.x), float(self.y)
        xyz = self.xyz
        if (sx, sy) == (0.0, 0.0) and xyz: sx, sy = float(xyz[0]), float(xyz[1])
        ox, oy = (list(self.origin) + [0, 0])[:2]
        _apply_mat(st, (1, 0, 0, 1, ox, oy)); _apply_mat(st, (sx, 0, 0, sy, 0, 0)); _apply_mat(st, (1, 0, 0, 1, -ox, -oy))
class Translate(_Noop):
    def __init__(self, *a, **kw):
        if len(a) >= 1: kw.setdefault("x", a[0])
        if len(a) >= 2: kw.setdefault("y", a[1])
        _Noop.__init__(self, **kw)
    def _render(self, cv, st, m):
        tx, ty = float(self.x), float(self.y)
        xyz = self.xyz
        if (tx, ty) == (0.0, 0.0) and xyz and tuple(xyz) != (1, 1, 1): tx, ty = float(xyz[0]), float(xyz[1])
        _apply_mat(st, (1, 0, 0, 1, tx, ty))
class MatrixInstruction(_Noop): pass
class BindTexture(_Noop): pass
class ClearColor(_Noop): pass
class ClearBuffers(_Noop): pass
class ScissorPush(_Noop): pass
class ScissorPop(_Noop): pass
class StencilPush(_Noop): pass
class StencilPop(_Noop): pass
class StencilUse(_Noop): pass
class StencilUnUse(_Noop): pass
class PushState(_Noop): pass
class PopState(_Noop): pass
class ChangeState(_Noop): pass
class UpdateNormalMatrix(_Noop): pass
class LoadIdentity(_Noop):
    def _render(self, cv, st, m): st["m"] = None
class ApplyContextMatrix(_Noop): pass
class SmoothQuad(Quad): pass
class SmoothTriangle(Triangle): pass
class SmoothRectangle(Rectangle): pass
class SmoothEllipse(Ellipse): pass
class SmoothRoundedRectangle(RoundedRectangle): pass


class Texture:
    """Minimal texture: create(size=..), blit_buffer(..) are accepted (pixels are not drawn in this editor)."""
    def __init__(self, width=1, height=1, colorfmt="rgba"):
        self.width, self.height, self.colorfmt = width, height, colorfmt
        self.size = (width, height); self.wrap = "clamp_to_edge"; self.mag_filter = "linear"; self.min_filter = "linear"
        self.uvpos = (0, 0); self.uvsize = (1, 1); self.tex_coords = [0, 0, 1, 0, 1, 1, 0, 1]
    @classmethod
    def create(cls, size=(128, 128), colorfmt="rgba", **kw): return cls(size[0], size[1], colorfmt)
    @classmethod
    def create_from_data(cls, im, **kw): return cls(getattr(im, "width", 1), getattr(im, "height", 1))
    def blit_buffer(self, *a, **k): pass
    def blit_data(self, *a, **k): pass
    def flip_vertical(self): pass
    def flip_horizontal(self): pass
    def get_region(self, x, y, w, h): return Texture(w, h, self.colorfmt)
    def save(self, *a, **k): print("[kivy] Texture.save is not supported in this editor"); return False


class Fbo(_Group):
    """Fbo is accepted so code runs; off-screen rendering is not available."""
    def __init__(self, **kw):
        self.size = kw.get("size", (0, 0)); self.texture = Texture(int(self.size[0] or 1), int(self.size[1] or 1))
        self.clear_color = kw.get("clear_color", (0, 0, 0, 0))
        self._canvas = Canvas(); self.items = []
    def bind(self, *a): pass
    def release(self): pass
    def clear(self): self.items = []
    def clear_buffer(self): pass
    def ask_update(self): pass
    def draw(self): pass
    def get_pixel_color(self, x, y): return (0, 0, 0, 0)
    def add(self, ins): self.items.append(ins); return ins


class RenderContext(Canvas):
    def __init__(self, *a, **kw):
        Canvas.__init__(self)
        self.shader = None; self.use_parent_projection = False; self.use_parent_modelview = False
    def __setitem__(self, k, v): pass
    def __getitem__(self, k): return None


class Matrix:
    def __init__(self): self.mat = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    def identity(self): self.__init__(); return self
    def translate(self, x, y, z=0): self.mat[12] += x; self.mat[13] += y; return self
    def scale(self, x, y, z=1): self.mat[0] *= x; self.mat[5] *= y; return self
    def rotate(self, angle, x=0, y=0, z=1): return self
    def get(self): return list(self.mat)
    def tolist(self): return [self.mat[i:i + 4] for i in range(0, 16, 4)]


MODULES = {
    "kivy.graphics": dict(Canvas=Canvas, InstructionGroup=InstructionGroup, Instruction=Instruction, GraphicException=GraphicException,
                          Color=Color, Rectangle=Rectangle, RoundedRectangle=RoundedRectangle, Ellipse=Ellipse, Line=Line,
                          SmoothLine=SmoothLine, Bezier=Bezier, Triangle=Triangle, Quad=Quad, Point=Point, Mesh=Mesh,
                          BorderImage=BorderImage, Callback=Callback, PushMatrix=PushMatrix, PopMatrix=PopMatrix,
                          Rotate=Rotate, Scale=Scale, Translate=Translate, MatrixInstruction=MatrixInstruction,
                          BindTexture=BindTexture, ClearColor=ClearColor, ClearBuffers=ClearBuffers,
                          ScissorPush=ScissorPush, ScissorPop=ScissorPop, StencilPush=StencilPush, StencilPop=StencilPop,
                          StencilUse=StencilUse, StencilUnUse=StencilUnUse, PushState=PushState, PopState=PopState,
                          ChangeState=ChangeState, UpdateNormalMatrix=UpdateNormalMatrix, LoadIdentity=LoadIdentity,
                          Texture=Texture, Fbo=Fbo, RenderContext=RenderContext, Matrix=Matrix,
                          SmoothQuad=SmoothQuad, SmoothTriangle=SmoothTriangle, SmoothRectangle=SmoothRectangle,
                          SmoothEllipse=SmoothEllipse, SmoothRoundedRectangle=SmoothRoundedRectangle),
    "kivy.graphics.instructions": dict(Canvas=Canvas, InstructionGroup=InstructionGroup, Instruction=Instruction,
                                       RenderContext=RenderContext, Callback=Callback, GraphicException=GraphicException),
    "kivy.graphics.context_instructions": dict(Color=Color, PushMatrix=PushMatrix, PopMatrix=PopMatrix, Rotate=Rotate,
                                               Scale=Scale, Translate=Translate, MatrixInstruction=MatrixInstruction,
                                               BindTexture=BindTexture, PushState=PushState, PopState=PopState,
                                               ChangeState=ChangeState, UpdateNormalMatrix=UpdateNormalMatrix,
                                               LoadIdentity=LoadIdentity, ApplyContextMatrix=ApplyContextMatrix),
    "kivy.graphics.vertex_instructions": dict(Rectangle=Rectangle, RoundedRectangle=RoundedRectangle, Ellipse=Ellipse,
                                              Line=Line, SmoothLine=SmoothLine, Bezier=Bezier, Triangle=Triangle, Quad=Quad,
                                              Point=Point, Mesh=Mesh, BorderImage=BorderImage, SmoothQuad=SmoothQuad,
                                              SmoothTriangle=SmoothTriangle, SmoothRectangle=SmoothRectangle,
                                              SmoothEllipse=SmoothEllipse, SmoothRoundedRectangle=SmoothRoundedRectangle),
    "kivy.graphics.texture": dict(Texture=Texture),
    "kivy.graphics.fbo": dict(Fbo=Fbo),
    "kivy.graphics.transformation": dict(Matrix=Matrix),
    "kivy.graphics.stencil_instructions": dict(StencilPush=StencilPush, StencilPop=StencilPop, StencilUse=StencilUse, StencilUnUse=StencilUnUse),
    "kivy.graphics.scissor_instructions": dict(ScissorPush=ScissorPush, ScissorPop=ScissorPop),
}
