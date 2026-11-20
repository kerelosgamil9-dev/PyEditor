"""turtle for Pyvora.

The same turtle API you know from desktop Python (forward, left, circle, begin_fill, Screen, onkey ...),
drawn on the tkinter canvas of the app. The screen is centred at (0, 0), y goes up, heading 0 = east.
"""
import math
import time
import sys
import tkinter as _tk

__all__ = ["Turtle", "RawTurtle", "Pen", "Screen", "TurtleScreen", "Vec2D", "Shape", "Terminator",
           "TurtleGraphicsError", "mainloop", "done", "bye", "exitonclick", "textinput", "numinput"]


class TurtleGraphicsError(Exception):
    pass


class Terminator(Exception):
    pass


class Vec2D(tuple):
    def __new__(cls, x, y): return tuple.__new__(cls, (x, y))
    def __add__(self, o): return Vec2D(self[0] + o[0], self[1] + o[1])
    def __mul__(self, o):
        if isinstance(o, Vec2D): return self[0] * o[0] + self[1] * o[1]
        return Vec2D(self[0] * o, self[1] * o)
    def __rmul__(self, o):
        if isinstance(o, (int, float)): return Vec2D(self[0] * o, self[1] * o)
        return NotImplemented
    def __sub__(self, o): return Vec2D(self[0] - o[0], self[1] - o[1])
    def __neg__(self): return Vec2D(-self[0], -self[1])
    def __abs__(self): return math.hypot(self[0], self[1])
    def rotate(self, angle):
        a = math.radians(angle); c, s = math.cos(a), math.sin(a)
        return Vec2D(self[0] * c - self[1] * s, self[0] * s + self[1] * c)
    def __repr__(self): return "(%.2f,%.2f)" % self


class Shape:
    def __init__(self, type_, data=None): self._type = type_; self._data = data
    def addcomponent(self, poly, fill, outline=None): self._data = [tuple(p) for p in poly]


_circle = [(10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a))) for a in range(0, 360, 20)]
_SHAPES = {
    "classic": [(0, 0), (-5, -9), (0, -7), (5, -9)],
    "arrow": [(-10, 0), (10, 0), (0, 10)],
    "turtle": [(0, 16), (-2, 14), (-1, 10), (-4, 7), (-7, 9), (-9, 8), (-6, 5), (-7, 1), (-5, -3), (-8, -6), (-6, -8), (-4, -5),
               (0, -7), (4, -5), (6, -8), (8, -6), (5, -3), (7, 1), (6, 5), (9, 8), (7, 9), (4, 7), (1, 10), (2, 14)],
    "circle": [(p[1], p[0]) for p in _circle],
    "square": [(10, -10), (10, 10), (-10, 10), (-10, -10)],
    "triangle": [(10, -5.77), (0, 11.55), (-10, -5.77)],
}

_SPEEDS = {"fastest": 0, "fast": 10, "normal": 6, "slow": 3, "slowest": 1}


# ======================================================================= screen
class TurtleScreen:
    _inst = None

    def __init__(self):
        self._root = _tk.Tk()
        self._root.title("Python Turtle Graphics")
        self._cv = _tk.Canvas(self._root, bg="white", highlightthickness=0)
        self._cv.pack(fill="both", expand=True)
        self._root.update()
        try:
            w, h = self._cv.winfo_width(), self._cv.winfo_height()
        except Exception:
            w, h = 0, 0
        if w < 50 or h < 50:
            w, h = self._root.winfo_screenwidth(), self._root.winfo_screenheight()
        self._w, self._h = int(w), int(h)
        self._turtles = []
        self._tracing = 1
        self._delay = 10
        self._cmode = 1.0
        self._bg = "white"
        self._keys = {}
        self._shapes = dict(_SHAPES)
        self._clickfn = {}
        TurtleScreen._inst = self

    # ---- helpers
    def _px(self, x, y): return self._w / 2.0 + x, self._h / 2.0 - y

    def _alive(self):
        try:
            if _tk._st.get("quit"): raise SystemExit
            if _tk._st.get("root") is None: raise SystemExit
        except AttributeError:
            pass

    def _color(self, c):
        if isinstance(c, (tuple, list)):
            if len(c) == 1: return self._color(c[0])
            r, g, b = c[:3]
            k = 255.0 if self._cmode == 1.0 else 1.0
            if self._cmode == 1.0: r, g, b = r * k, g * k, b * k
            return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in (r, g, b))
        s = str(c).strip()
        low = s.lower().replace(" ", "")
        if low.startswith(("gray", "grey")) and low[4:].isdigit():
            v = int(round(int(low[4:]) * 2.55)); return "#%02x%02x%02x" % (v, v, v)
        if s.startswith("#") or not s: return s
        return low

    # ---- window
    def bgcolor(self, *c):
        if not c: return self._bg
        self._bg = self._color(c[0] if len(c) == 1 else c)
        self._cv.config(bg=self._bg)

    def title(self, t): self._root.title(str(t))
    def setup(self, width=0.5, height=0.75, startx=None, starty=None): pass
    def screensize(self, canvwidth=None, canvheight=None, bg=None):
        if bg: self.bgcolor(bg)
        return (self._w, self._h)
    def window_width(self): return self._w
    def window_height(self): return self._h
    def getcanvas(self): return self._cv
    def getshapes(self): return sorted(self._shapes)
    def colormode(self, cmode=None):
        if cmode is None: return self._cmode
        self._cmode = 255 if cmode == 255 else 1.0
    def mode(self, mode=None): return "standard"
    def setworldcoordinates(self, llx, lly, urx, ury): pass
    def turtles(self): return list(self._turtles)
    def register_shape(self, name, shape=None):
        if shape is not None and not isinstance(shape, str):
            self._shapes[name] = list(shape._data if isinstance(shape, Shape) else shape)
    addshape = register_shape

    def tracer(self, n=None, delay=None):
        if n is None: return self._tracing
        self._tracing = int(n)
        if delay is not None: self._delay = int(delay)
        if self._tracing: self.update()

    def delay(self, delay=None):
        if delay is None: return self._delay
        self._delay = int(delay)

    def update(self):
        for t in self._turtles: t._draw_sprite()
        self._alive()
        self._root.update()

    def clear(self):
        self._cv.delete("all")
        for t in self._turtles: t._reset_items()
    clearscreen = clear

    def reset(self):
        self._cv.delete("all")
        for t in self._turtles: t._full_reset()
    resetscreen = reset

    def ontimer(self, fun, t=0): self._root.after(int(t), fun)

    def listen(self, xdummy=None, ydummy=None): self._root.focus_set()

    def _bindkey(self, fun, key, ev):
        key = "space" if key == " " else key
        for seq in (("<%s-%s>" % (ev, key),) if ev else ("<KeyPress-%s>" % key,)):
            if fun is None: self._root.unbind(seq)
            else: self._root.bind(seq, lambda e, f=fun: f())
    def onkey(self, fun, key): self._bindkey(fun, key, "KeyRelease")
    onkeyrelease = onkey
    def onkeypress(self, fun, key=None):
        if key is None: self._root.bind("<KeyPress>", lambda e, f=fun: f())
        else: self._bindkey(fun, key, "KeyPress")

    def onclick(self, fun, btn=1, add=None):
        if fun is None: self._cv.unbind("<Button-%d>" % btn); return
        def h(e, f=fun):
            f(e.x - self._w / 2.0, self._h / 2.0 - e.y)
        self._cv.bind("<Button-%d>" % btn, h)
    onscreenclick = onclick

    def textinput(self, title, prompt):
        import tkinter.simpledialog as sd
        return sd.askstring(title, prompt)

    def numinput(self, title, prompt, default=None, minval=None, maxval=None):
        import tkinter.simpledialog as sd
        return sd.askfloat(title, prompt, initialvalue=default, minvalue=minval, maxvalue=maxval)

    def mainloop(self):
        for t in self._turtles: t._draw_sprite()
        _tk.mainloop()
    done = mainloop

    def exitonclick(self):
        def bye_(x, y): self.bye()
        self.onclick(bye_, 1)
        self.mainloop()

    def bye(self):
        try: self._root.destroy()
        except Exception: pass
        try: _tk._st["quit"] = True
        except Exception: pass
        TurtleScreen._inst = None
        _Turtle_state["pen"] = None


Screen_ = TurtleScreen


def Screen():
    """the one window (created on first use, and again after it was closed or a new program started)"""
    inst = TurtleScreen._inst
    if inst is None or _tk._st.get("root") is not inst._root:
        TurtleScreen._inst = None
        _Turtle_state["pen"] = None
        TurtleScreen()
    return TurtleScreen._inst


_Turtle_state = {"pen": None}


# ======================================================================= turtle
class RawTurtle:
    def __init__(self, canvas=None, shape="classic", undobuffersize=1000, visible=True):
        self.screen = Screen()
        self._cv = self.screen._cv
        self._x = 0.0; self._y = 0.0; self._h = 0.0
        self._down = True
        self._pc = "black"; self._fc = "black"; self._pcspec = "black"; self._fcspec = "black"
        self._size = 1; self._speed = 3; self._visible = visible; self._shape = shape
        self._stretch = (1.0, 1.0); self._outline = 1
        self._fillpath = None; self._stamps = {}
        self._sprite = None
        self._angle_scale = 1.0
        self.screen._turtles.append(self)
        self._draw_sprite()

    # ---- bookkeeping
    def getscreen(self): return self.screen
    def _animated(self): return self.screen._tracing > 0 and self._speed > 0

    def _reset_items(self):
        self._sprite = None; self._stamps = {}; self._fillpath = None
        self._draw_sprite()

    def _full_reset(self):
        self._x = self._y = 0.0; self._h = 0.0; self._down = True
        self._pc = self._fc = "black"; self._pcspec = self._fcspec = "black"
        self._size = 1; self._speed = 3; self._visible = True
        self._reset_items()

    def _pts(self):
        pts = self.screen._shapes.get(self._shape, _SHAPES["classic"])
        th = math.radians(self._h - 90.0); c, s = math.cos(th), math.sin(th)
        sx, sy = self._stretch
        out = []
        for px, py in pts:
            px *= sx; py *= sy
            x = self._x + px * c - py * s; y = self._y + px * s + py * c
            out.extend(self.screen._px(x, y))
        return out

    def _draw_sprite(self):
        cv = self._cv
        try:
            if self._sprite is None:
                self._sprite = cv.create_polygon(self._pts(), fill=self._fc, outline=self._pc, width=self._outline,
                                                 state="normal" if self._visible else "hidden")
            else:
                cv.coords(self._sprite, self._pts())
                cv.itemconfig(self._sprite, fill=self._fc, outline=self._pc,
                              state="normal" if self._visible else "hidden")
                cv.tag_raise(self._sprite)
        except Exception:
            pass

    def _frame(self):
        self.screen._alive()
        self._draw_sprite()
        self.screen._root.update()
        d = self.screen._delay / 1000.0
        if d > 0: time.sleep(min(d, 0.05) * (0.5 if self._speed >= 6 else 1.0))

    # ---- movement
    def _go_to(self, nx, ny):
        ox, oy = self._x, self._y
        if nx == ox and ny == oy: return
        line = None
        if self._down:
            x0, y0 = self.screen._px(ox, oy)
            line = self._cv.create_line(x0, y0, x0, y0, fill=self._pc, width=self._size, capstyle="round", joinstyle="round")
        if self._animated():
            dist = math.hypot(nx - ox, ny - oy)
            step = 2 + self._speed * 3
            n = max(1, int(dist / step))
            for i in range(1, n + 1):
                f = i / float(n)
                self._x = ox + (nx - ox) * f; self._y = oy + (ny - oy) * f
                if line is not None:
                    x0, y0 = self.screen._px(ox, oy); x1, y1 = self.screen._px(self._x, self._y)
                    self._cv.coords(line, x0, y0, x1, y1)
                self._frame()
        else:
            self._x, self._y = nx, ny
            if line is not None:
                x0, y0 = self.screen._px(ox, oy); x1, y1 = self.screen._px(nx, ny)
                self._cv.coords(line, x0, y0, x1, y1)
        self._x, self._y = nx, ny
        if self._fillpath is not None: self._fillpath.append((nx, ny))

    def _turn(self, deg):
        start = self._h
        if self._animated() and abs(deg) > 0:
            step = 6 + self._speed * 6
            n = max(1, int(abs(deg) / step))
            for i in range(1, n + 1):
                self._h = start + deg * i / float(n)
                self._frame()
        self._h = (start + deg) % 360.0

    def forward(self, distance):
        a = math.radians(self._h)
        self._go_to(self._x + distance * math.cos(a), self._y + distance * math.sin(a))
    fd = forward
    def back(self, distance): self.forward(-distance)
    backward = bk = back
    def left(self, angle): self._turn(angle * self._angle_scale)
    lt = left
    def right(self, angle): self._turn(-angle * self._angle_scale)
    rt = right

    def goto(self, x, y=None):
        if y is None: x, y = x
        self._go_to(float(x), float(y))
    setpos = setposition = goto
    def setx(self, x): self._go_to(float(x), self._y)
    def sety(self, y): self._go_to(self._x, float(y))
    def setheading(self, to_angle): self._turn(((to_angle * self._angle_scale - self._h + 180.0) % 360.0) - 180.0)
    seth = setheading
    def home(self): self.goto(0, 0); self.setheading(0)

    def circle(self, radius, extent=None, steps=None):
        if extent is None: extent = 360.0
        frac = abs(extent) / 360.0
        if steps is None: steps = 1 + int(min(11 + abs(radius) / 6.0, 59.0) * frac)
        w = 1.0 * extent / steps; w2 = 0.5 * w
        l = 2.0 * radius * math.sin(math.radians(w * 0.5))
        if radius < 0: l, w, w2 = -l, -w, -w2
        speed = self._speed
        self._turn(w2)
        for _ in range(steps):
            self.forward(l); self._turn(w)
        self._turn(-w2)

    def dot(self, size=None, *color):
        if size is None: size = max(self._size + 4, 2 * self._size)
        col = self.screen._color(color) if color else self._pc
        x, y = self.screen._px(self._x, self._y); r = size / 2.0
        self._cv.create_oval(x - r, y - r, x + r, y + r, fill=col, outline=col)
        if self._animated(): self._frame()

    def stamp(self):
        pts = self._pts()
        i = self._cv.create_polygon(pts, fill=self._fc, outline=self._pc)
        self._stamps[i] = 1
        return i

    def clearstamp(self, stampid):
        if stampid in self._stamps:
            self._cv.delete(stampid); del self._stamps[stampid]

    def clearstamps(self, n=None):
        for i in list(self._stamps)[:n] if n else list(self._stamps): self.clearstamp(i)

    def write(self, arg, move=False, align="left", font=("Arial", 8, "normal")):
        x, y = self.screen._px(self._x, self._y)
        anchor = {"left": "sw", "center": "s", "right": "se"}.get(align, "sw")
        f = tuple(font) if isinstance(font, (list, tuple)) else font
        self._cv.create_text(x, y, text=str(arg), anchor=anchor, fill=self._pc, font=f)
        if move and align == "left": self._x += len(str(arg)) * (f[1] if isinstance(f, tuple) and len(f) > 1 else 8) * 0.6
        if self._animated(): self._frame()

    # ---- pen
    def pendown(self): self._down = True
    pd = down = pendown
    def penup(self): self._down = False
    pu = up = penup
    def isdown(self): return self._down
    def pensize(self, width=None):
        if width is None: return self._size
        self._size = width
    width = pensize

    def pencolor(self, *c):
        if not c: return self._pcspec
        self._pcspec = c[0] if len(c) == 1 else tuple(c); self._pc = self.screen._color(c); self._draw_sprite()
    def fillcolor(self, *c):
        if not c: return self._fcspec
        self._fcspec = c[0] if len(c) == 1 else tuple(c); self._fc = self.screen._color(c); self._draw_sprite()
    def color(self, *args):
        if not args: return (self._pcspec, self._fcspec)
        if len(args) == 1: self.pencolor(args[0]); self.fillcolor(args[0])
        elif len(args) == 2: self.pencolor(args[0]); self.fillcolor(args[1])
        else: self.pencolor(*args); self.fillcolor(*args)

    def pen(self, pen=None, **pendict):
        if pen is None and not pendict:
            return {"shown": self._visible, "pendown": self._down, "pencolor": self._pcspec, "fillcolor": self._fcspec,
                    "pensize": self._size, "speed": self._speed, "resizemode": "noresize", "stretchfactor": self._stretch,
                    "outline": self._outline, "tilt": 0.0}
        d = dict(pen or {}); d.update(pendict)
        if "pendown" in d: self._down = bool(d["pendown"])
        if "pencolor" in d: self.pencolor(d["pencolor"])
        if "fillcolor" in d: self.fillcolor(d["fillcolor"])
        if "pensize" in d: self._size = d["pensize"]
        if "speed" in d: self.speed(d["speed"])
        if "shown" in d: self._visible = bool(d["shown"]); self._draw_sprite()

    def speed(self, speed=None):
        if speed is None: return self._speed
        if isinstance(speed, str): speed = _SPEEDS.get(speed, 3)
        speed = int(speed)
        self._speed = 0 if (speed > 10 or speed < 0.5) else speed

    def begin_fill(self): self._fillpath = [(self._x, self._y)]
    def filling(self): return self._fillpath is not None
    def end_fill(self):
        pts = self._fillpath
        self._fillpath = None
        if pts and len(pts) >= 3:
            flat = []
            for x, y in pts: flat.extend(self.screen._px(x, y))
            i = self._cv.create_polygon(flat, fill=self._fc, outline=self._pc if self._down else "", width=self._size)
            self._cv.tag_lower(i)
            self._draw_sprite()

    # ---- state
    def hideturtle(self): self._visible = False; self._draw_sprite()
    ht = hideturtle
    def showturtle(self): self._visible = True; self._draw_sprite()
    st = showturtle
    def isvisible(self): return self._visible
    def shape(self, name=None):
        if name is None: return self._shape
        if name not in self.screen._shapes: raise TurtleGraphicsError("There is no shape named %s" % name)
        self._shape = name; self._draw_sprite()
    def shapesize(self, stretch_wid=None, stretch_len=None, outline=None):
        if stretch_wid is None and stretch_len is None and outline is None: return (self._stretch[0], self._stretch[1], self._outline)
        sw = stretch_wid if stretch_wid is not None else 1.0
        sl = stretch_len if stretch_len is not None else sw
        self._stretch = (float(sl), float(sw))
        if outline is not None: self._outline = outline
        self._draw_sprite()
    turtlesize = shapesize
    def resizemode(self, rmode=None): return "noresize"
    def degrees(self, fullcircle=360.0): self._angle_scale = 360.0 / fullcircle
    def radians(self): self._angle_scale = 180.0 / math.pi
    def undobufferentries(self): return 0
    def undo(self): pass
    def setundobuffer(self, size): pass

    def position(self): return Vec2D(round(self._x, 6), round(self._y, 6))
    pos = position
    def xcor(self): return self._x
    def ycor(self): return self._y
    def heading(self): return self._h / self._angle_scale
    def distance(self, x, y=None):
        if y is None:
            x, y = (x.pos() if isinstance(x, RawTurtle) else x)
        return math.hypot(self._x - x, self._y - y)
    def towards(self, x, y=None):
        if y is None:
            x, y = (x.pos() if isinstance(x, RawTurtle) else x)
        return (math.degrees(math.atan2(y - self._y, x - self._x)) % 360.0) / self._angle_scale

    def clear(self): self._cv.delete("all"); [t._reset_items() for t in self.screen._turtles]
    def reset(self): self.clear(); self._full_reset()
    def clone(self):
        t = Turtle(); t._x, t._y, t._h = self._x, self._y, self._h; t._down = self._down
        t._pc, t._fc, t._pcspec, t._fcspec = self._pc, self._fc, self._pcspec, self._fcspec
        t._size, t._speed, t._shape, t._stretch, t._visible = self._size, self._speed, self._shape, self._stretch, self._visible
        t._draw_sprite(); return t

    # ---- events on the turtle
    def onclick(self, fun, btn=1, add=None): self.screen.onclick(lambda x, y: fun(x, y) if self.distance(x, y) < 20 else None, btn)
    def onrelease(self, fun, btn=1, add=None): pass
    def ondrag(self, fun, btn=1, add=None): pass


class Turtle(RawTurtle):
    pass


Pen = Turtle


# ============================================================= module functions
def _pen():
    scr = Screen()
    p = _Turtle_state["pen"]
    if p is None or p.screen is not scr:
        p = _Turtle_state["pen"] = Turtle()
    return p


def _make(name, owner):
    def f(*a, **k):
        target = _pen() if owner == "turtle" else Screen()
        return getattr(target, name)(*a, **k)
    f.__name__ = name
    return f


_TURTLE_FUNCS = ("forward fd back backward bk left lt right rt goto setpos setposition setx sety setheading seth home circle dot "
                 "stamp clearstamp clearstamps write pendown pd down penup pu up isdown pensize width pencolor fillcolor color pen "
                 "speed begin_fill filling end_fill hideturtle ht showturtle st isvisible shape shapesize turtlesize resizemode "
                 "degrees radians position pos xcor ycor heading distance towards clear reset clone undo setundobuffer "
                 "undobufferentries getscreen").split()
_SCREEN_FUNCS = ("bgcolor title setup screensize window_width window_height getcanvas getshapes colormode mode setworldcoordinates "
                 "turtles register_shape addshape tracer delay update clearscreen resetscreen ontimer listen onkey onkeyrelease "
                 "onkeypress onclick onscreenclick textinput numinput").split()

for _n in _TURTLE_FUNCS:
    globals()[_n] = _make(_n, "turtle")
for _n in _SCREEN_FUNCS:
    globals()[_n] = _make(_n, "screen")


def onclick(fun, btn=1, add=None): return Screen().onclick(fun, btn, add)
def textinput(title, prompt): return Screen().textinput(title, prompt)
def numinput(title, prompt, default=None, minval=None, maxval=None): return Screen().numinput(title, prompt, default, minval, maxval)
def mainloop(): Screen().mainloop()
done = mainloop
def exitonclick(): Screen().exitonclick()
def bye(): Screen().bye()
def getscreen(): return Screen()
