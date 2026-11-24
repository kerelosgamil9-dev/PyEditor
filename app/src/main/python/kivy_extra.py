"""Extra Kivy modules for the emulation: Animation, JsonStore, Vector, UrlRequest, Clipboard, SoundLoader, utils."""
import json, math, os, random, threading, time
import kivyshim as K
from kivyshim import EventDispatcher, Clock, Property, NumericProperty

# ===================================================================== Animation
class AnimationTransition:
    @staticmethod
    def linear(p): return p
    @staticmethod
    def in_quad(p): return p * p
    @staticmethod
    def out_quad(p): return -1.0 * p * (p - 2.0)
    @staticmethod
    def in_out_quad(p):
        p *= 2
        if p < 1: return 0.5 * p * p
        p -= 1.0; return -0.5 * (p * (p - 2.0) - 1.0)
    @staticmethod
    def in_cubic(p): return p * p * p
    @staticmethod
    def out_cubic(p): p -= 1.0; return p * p * p + 1.0
    @staticmethod
    def in_out_cubic(p):
        p *= 2
        if p < 1: return 0.5 * p * p * p
        p -= 2; return 0.5 * (p * p * p + 2.0)
    @staticmethod
    def in_sine(p): return -1.0 * math.cos(p * (math.pi / 2.0)) + 1.0
    @staticmethod
    def out_sine(p): return math.sin(p * (math.pi / 2.0))
    @staticmethod
    def in_out_sine(p): return -0.5 * (math.cos(math.pi * p) - 1.0)
    @staticmethod
    def in_expo(p): return 0.0 if p == 0 else math.pow(2, 10 * (p - 1.0))
    @staticmethod
    def out_expo(p): return 1.0 if p == 1.0 else -math.pow(2, -10 * p) + 1.0
    @staticmethod
    def in_back(p): s = 1.70158; return p * p * ((s + 1.0) * p - s)
    @staticmethod
    def out_back(p): s = 1.70158; p -= 1.0; return p * p * ((s + 1.0) * p + s) + 1.0
    @staticmethod
    def out_bounce(p):
        if p < (1.0 / 2.75): return 7.5625 * p * p
        if p < (2.0 / 2.75): p -= (1.5 / 2.75); return 7.5625 * p * p + .75
        if p < (2.5 / 2.75): p -= (2.25 / 2.75); return 7.5625 * p * p + .9375
        p -= (2.625 / 2.75); return 7.5625 * p * p + .984375
    @staticmethod
    def in_bounce(p): return 1.0 - AnimationTransition.out_bounce(1.0 - p)
    @staticmethod
    def in_out_bounce(p):
        if p < .5: return AnimationTransition.in_bounce(p * 2.0) * .5
        return AnimationTransition.out_bounce(p * 2.0 - 1.0) * .5 + .5
    @staticmethod
    def out_elastic(p):
        if p == 0 or p == 1: return p
        return math.pow(2, -10 * p) * math.sin((p - .075) * (2 * math.pi) / .3) + 1.0
    @staticmethod
    def in_elastic(p): return 1.0 - AnimationTransition.out_elastic(1.0 - p)


def _lerp(a, b, t):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return type(b)(_lerp(x, y, t) for x, y in zip(a, b)) if isinstance(b, tuple) else [_lerp(x, y, t) for x, y in zip(a, b)]
    try: return a + (b - a) * t
    except Exception: return b


class Animation(EventDispatcher):
    __events__ = ("on_start", "on_progress", "on_complete")
    _runs = []          # [(animation, widget, ev)]

    def __init__(self, **kw):
        EventDispatcher.__init__(self)
        self._duration = float(kw.pop("duration", kw.pop("d", 1.0)))
        tr = kw.pop("transition", kw.pop("t", "linear"))
        self._transition = getattr(AnimationTransition, tr, AnimationTransition.linear) if isinstance(tr, str) else tr
        self._step = float(kw.pop("step", kw.pop("s", 0)))
        self._props = kw
        self.repeat = False

    @property
    def duration(self): return self._duration
    def on_start(self, *a): pass
    def on_progress(self, *a): pass
    def on_complete(self, *a): pass

    def start(self, widget):
        self.stop(widget)
        start = {k: getattr(widget, k, None) for k in self._props}
        t0 = time.time(); st = {"ev": None}
        self.dispatch("on_start", widget)

        def tick(dt):
            p = 1.0 if self._duration <= 0 else min(1.0, (time.time() - t0) / self._duration)
            v = self._transition(p)
            for k, end in self._props.items():
                try: setattr(widget, k, _lerp(start[k], end, v))
                except Exception: pass
            self.dispatch("on_progress", widget, p)
            if p >= 1.0:
                self._finish(widget, st["ev"], True)
                return False
        ev = Clock.schedule_interval(tick, 1.0 / 45)
        st["ev"] = ev
        Animation._runs.append((self, widget, ev))
        return self

    def _finish(self, widget, ev, done):
        for r in list(Animation._runs):
            if r[0] is self and r[1] is widget: Animation._runs.remove(r)
        if ev is not None: ev.cancel()
        if done:
            self.dispatch("on_complete", widget)
            if self.repeat: self.start(widget)

    def stop(self, widget):
        for r in list(Animation._runs):
            if r[0] is self and r[1] is widget: self._finish(widget, r[2], False)

    def cancel(self, widget): self.stop(widget)

    @staticmethod
    def cancel_all(widget, *props):
        for r in list(Animation._runs):
            if r[1] is widget and (not props or any(p in r[0]._props for p in props)): r[0]._finish(widget, r[2], False)

    stop_all = cancel_all

    def have_properties_to_animate(self, widget): return any(r[1] is widget for r in Animation._runs)
    def __add__(self, other): return _Sequence(self, other)
    def __and__(self, other): return _Parallel(self, other)


class _Sequence(Animation):
    def __init__(self, a, b):
        EventDispatcher.__init__(self); self.a, self.b = a, b; self.repeat = False; self._props = {}; self._duration = a._duration + b._duration
    def start(self, widget):
        self.dispatch("on_start", widget)
        def after_a(anim, w):
            self.b.bind(on_complete=lambda i, ww: (self.dispatch("on_complete", widget), self.repeat and self.start(widget)))
            self.b.start(widget)
        self.a.bind(on_complete=after_a); self.a.start(widget); return self
    def stop(self, widget): self.a.stop(widget); self.b.stop(widget)
    def cancel(self, widget): self.stop(widget)


class _Parallel(Animation):
    def __init__(self, a, b):
        EventDispatcher.__init__(self); self.a, self.b = a, b; self.repeat = False; self._props = {}; self._duration = max(a._duration, b._duration)
    def start(self, widget):
        self.dispatch("on_start", widget); self._left = 2
        def done(anim, w):
            self._left -= 1
            if self._left == 0: self.dispatch("on_complete", widget)
        self.a.bind(on_complete=done); self.b.bind(on_complete=done)
        self.a.start(widget); self.b.start(widget); return self
    def stop(self, widget): self.a.stop(widget); self.b.stop(widget)
    def cancel(self, widget): self.stop(widget)


# ===================================================================== JsonStore
class JsonStore:
    def __init__(self, filename, **kw):
        self.filename = filename; self._data = {}
        if os.path.exists(filename):
            try:
                with open(filename, encoding="utf-8") as f: self._data = json.load(f)
            except Exception: self._data = {}
    def _save(self):
        d = os.path.dirname(os.path.abspath(self.filename))
        if d and not os.path.isdir(d): os.makedirs(d, exist_ok=True)
        with open(self.filename, "w", encoding="utf-8") as f: json.dump(self._data, f, ensure_ascii=False, indent=2)
    def put(self, key, **values): self._data[key] = values; self._save(); return True
    def get(self, key):
        if key not in self._data: raise KeyError(key)
        return dict(self._data[key])
    def exists(self, key): return key in self._data
    def delete(self, key):
        if key not in self._data: raise KeyError(key)
        del self._data[key]; self._save()
    def keys(self): return list(self._data.keys())
    def count(self): return len(self._data)
    def clear(self): self._data = {}; self._save()
    def find(self, **filters):
        for k, v in self._data.items():
            if all(v.get(f) == x for f, x in filters.items()): yield k, dict(v)
    def __contains__(self, k): return k in self._data
    def __getitem__(self, k): return self.get(k)
    def __setitem__(self, k, v): self.put(k, **v)
    def __delitem__(self, k): self.delete(k)
    def __len__(self): return len(self._data)
    def __iter__(self): return iter(self._data)


# ===================================================================== Vector
class Vector(list):
    def __init__(self, *largs):
        if len(largs) == 1: list.__init__(self, largs[0])
        elif len(largs) == 2: list.__init__(self, largs)
        else: raise Exception("Invalid vector")
    @property
    def x(self): return self[0]
    @x.setter
    def x(self, v): self[0] = v
    @property
    def y(self): return self[1]
    @y.setter
    def y(self, v): self[1] = v
    def __getslice__(self, i, j): return list.__getitem__(self, slice(i, j))
    def __add__(self, o): return Vector([a + b for a, b in zip(self, o)])
    __radd__ = __add__
    def __sub__(self, o): return Vector([a - b for a, b in zip(self, o)])
    def __rsub__(self, o): return Vector([b - a for a, b in zip(self, o)])
    def __mul__(self, o):
        if isinstance(o, (int, float)): return Vector([a * o for a in self])
        return Vector([a * b for a, b in zip(self, o)])
    __rmul__ = __mul__
    def __truediv__(self, o):
        if isinstance(o, (int, float)): return Vector([a / o for a in self])
        return Vector([a / b for a, b in zip(self, o)])
    def __neg__(self): return Vector([-a for a in self])
    def __iadd__(self, o): self[:] = [a + b for a, b in zip(self, o)]; return self
    def __isub__(self, o): self[:] = [a - b for a, b in zip(self, o)]; return self
    def length(self): return math.sqrt(sum(a * a for a in self))
    def length2(self): return sum(a * a for a in self)
    def distance(self, to): return Vector(to).__sub__(self).length()
    def distance2(self, to): return (Vector(to) - self).length2()
    def dot(self, a): return sum(x * y for x, y in zip(self, a))
    def normalize(self):
        l = self.length()
        return Vector([a / l for a in self]) if l else Vector(self)
    def rotate(self, angle):
        a = math.radians(angle); c, s = math.cos(a), math.sin(a)
        return Vector(self[0] * c - self[1] * s, self[0] * s + self[1] * c)
    def angle(self, a): return math.degrees(math.atan2(self[0] * a[1] - self[1] * a[0], self[0] * a[0] + self[1] * a[1]))
    def lerp(self, v, t): return Vector([a + (b - a) * t for a, b in zip(self, v)])
    @staticmethod
    def segment_intersection(*a): return None
    @staticmethod
    def in_bbox(point, a, b): return min(a[0], b[0]) <= point[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
    def __repr__(self): return "Vector(%s)" % ", ".join(repr(a) for a in self)


# ===================================================================== UrlRequest
class UrlRequest:
    """UrlRequest(url, on_success=..., on_failure=..., on_error=..., req_body=..., req_headers=..., method=...)"""
    def __init__(self, url, on_success=None, on_redirect=None, on_failure=None, on_error=None, on_progress=None,
                 req_body=None, req_headers=None, chunk_size=8192, timeout=None, method=None, decode=True,
                 debug=False, file_path=None, ca_file=None, verify=True, proxy_host=None, proxy_port=None,
                 proxy_headers=None, user_agent=None, on_cancel=None, cookies=None, auth=None):
        self.url = url; self.on_success = on_success; self.on_failure = on_failure; self.on_error = on_error
        self.on_progress = on_progress; self.req_body = req_body; self.req_headers = dict(req_headers or {})
        self.timeout = timeout; self.method = method or ("POST" if req_body else "GET"); self.decode = decode
        self.file_path = file_path; self.result = None; self.resp_status = None; self.resp_headers = None
        self.error = None; self.is_finished = False; self._ev = threading.Event(); self.on_cancel = on_cancel
        if user_agent: self.req_headers.setdefault("User-Agent", user_agent)
        t = threading.Thread(target=self._run, daemon=True); t.start()

    def _call(self, cb, *args):
        if cb is not None: Clock.schedule_once(lambda dt: cb(self, *args), 0)

    def _run(self):
        import urllib.request, urllib.error
        try:
            body = self.req_body
            if isinstance(body, str): body = body.encode("utf-8")
            req = urllib.request.Request(self.url, data=body, headers=self.req_headers, method=self.method)
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout or 30)
                status = resp.status
            except urllib.error.HTTPError as e:
                resp = e; status = e.code
            data = resp.read()
            self.resp_status = status; self.resp_headers = dict(resp.headers)
            if self.file_path:
                with open(self.file_path, "wb") as f: f.write(data)
                self.result = self.file_path
            else:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                res = data.decode("utf-8", "replace") if self.decode else data
                if self.decode and "json" in ctype:
                    try: res = json.loads(res)
                    except Exception: pass
                self.result = res
            self.is_finished = True
            self._call(self.on_progress, len(data), len(data))
            if 200 <= status < 400: self._call(self.on_success, self.result)
            else: self._call(self.on_failure, self.result)
        except Exception as e:
            self.error = e; self.is_finished = True
            self._call(self.on_error, e)
        finally: self._ev.set()

    def wait(self, delay=0.5):
        while not self._ev.wait(delay): pass
    def cancel(self): self._ev.set()


# ===================================================================== clipboard / sound
class _Clipboard:
    _t = ""
    def copy(self, data): self._t = data
    def paste(self): return self._t
    def get_types(self): return ["text/plain"]
    def put(self, data, mimetype="text/plain"): self._t = data if isinstance(data, str) else data.decode("utf-8", "replace")
    def get(self, mimetype="text/plain"): return self._t


_AID = [0]
_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".m4a": "audio/mp4",
         ".aac": "audio/aac", ".flac": "audio/flac", ".opus": "audio/ogg", ".webm": "audio/webm"}


class Sound(EventDispatcher):
    """Audio played by the page (HTML5 audio): mp3 / wav / ogg / m4a ..."""
    __events__ = ("on_play", "on_stop")
    volume = NumericProperty(1.0)
    loop = Property(False)
    source = Property("")
    state = Property("stop")
    length = NumericProperty(0)
    pitch = NumericProperty(1)

    def __init__(self, **kw):
        EventDispatcher.__init__(self)
        import tkshim as tk
        _AID[0] += 1; self._aid = _AID[0]; self._t0 = None; self._pos0 = 0.0
        self._tk = tk
        tk._pv[("aud", self._aid)] = self._ev
        self._apply_kw(kw)
        if self.source: self._load()

    def _load(self):
        src = self.source
        try:
            with open(src, "rb") as f: data = f.read()
        except Exception as ex:
            print("[kivy] cannot load sound %r: %s" % (src, ex)); return
        if len(data) > 20 * 1024 * 1024: print("[kivy] sound file too big (max 20 MB)"); return
        import base64
        mime = _MIME.get(os.path.splitext(src)[1].lower(), "audio/mpeg")
        self._tk._send("pvaud", self._aid, "load", "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii")))
        self._tk._send("pvaud", self._aid, "vol", float(self.volume))
        if self.loop: self._tk._send("pvaud", self._aid, "loop", 1)

    def _ev(self, e):
        if "dur" in e: self.length = float(e["dur"] or 0)
        if e.get("ended"):
            self.state = "stop"; self._t0 = None; self._pos0 = 0.0
            self.dispatch("on_stop")

    def _prop_changed(self, name, value):
        t = getattr(self, "_tk", None)
        if t is None: return
        if name == "volume": t._send("pvaud", self._aid, "vol", float(value))
        elif name == "loop": t._send("pvaud", self._aid, "loop", 1 if value else 0)
        elif name == "pitch": t._send("pvaud", self._aid, "rate", float(value))
        elif name == "source": self._load()

    def play(self):
        self._tk._send("pvaud", self._aid, "play")
        self.state = "play"; self._t0 = time.time(); self.dispatch("on_play")
    def stop(self):
        self._tk._send("pvaud", self._aid, "stop")
        self.state = "stop"; self._t0 = None; self._pos0 = 0.0
        self.dispatch("on_stop")
    def seek(self, pos):
        self._tk._send("pvaud", self._aid, "seek", float(pos)); self._pos0 = float(pos)
        if self.state == "play": self._t0 = time.time()
    def get_pos(self):
        if self.state == "play" and self._t0 is not None:
            p = self._pos0 + time.time() - self._t0
            return p % self.length if self.loop and self.length else p
        return self._pos0
    def unload(self):
        self._tk._send("pvaud", self._aid, "free"); self.state = "stop"
    def on_play(self, *a): pass
    def on_stop(self, *a): pass


class SoundLoader:
    @staticmethod
    def load(filename):
        if not os.path.exists(filename): return None
        return Sound(source=filename)
    @staticmethod
    def register(cls): pass


# ===================================================================== utils
def rgba(s, *args):
    if isinstance(s, str): return K.get_color_from_hex(s)
    return tuple(float(x) / 255.0 for x in ([s] + list(args)))


def boundary(value, minvalue, maxvalue): return max(min(value, maxvalue), minvalue)
def escape_markup(text): return text.replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")
def get_random_color(alpha=1.0): return [random.random(), random.random(), random.random(), alpha]
def strtotuple(s): return tuple(eval(s))
def interpolate(value_from, value_to, step=10): return value_from + (value_to - value_from) / float(step)


MODULES = {
    "kivy.animation": dict(Animation=Animation, AnimationTransition=AnimationTransition),
    "kivy.vector": dict(Vector=Vector),
    "kivy.storage": {},
    "kivy.storage.jsonstore": dict(JsonStore=JsonStore),
    "kivy.network": {},
    "kivy.network.urlrequest": dict(UrlRequest=UrlRequest),
    "kivy.core.clipboard": dict(Clipboard=_Clipboard()),
    "kivy.core.audio": dict(SoundLoader=SoundLoader, Sound=Sound),
    "kivy.utils": dict(get_color_from_hex=K.get_color_from_hex, get_hex_from_color=K.get_hex_from_color, platform="android",
                       rgba=rgba, boundary=boundary, escape_markup=escape_markup, get_random_color=get_random_color,
                       strtotuple=strtotuple, interpolate=interpolate),
}
