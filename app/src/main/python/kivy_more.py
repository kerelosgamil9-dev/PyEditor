"""kivy_more: the rest of the Kivy API for the PYVORA emulation.

Adds (on top of kivyshim / kivy_ui / kivy_gfx / kivy_extra):
  kivy.resources, kivy.base (EventLoop, runTouchApp), kivy.core.text, kivy.core.image, kivy.core.window.Keyboard,
  kivy.config (working Config / ConfigParser + App.config), kivy.cache, kivy.weakmethod, kivy.compat, kivy.parser,
  kivy.context, kivy.modules, kivy.loader, kivy.atlas, kivy.storage.dictstore, kivy.effects.*, kivy.utils (full),
  kivy.uix.treeview, kivy.uix.stencilview, kivy.uix.recyclegridlayout, kivy.uix.recycleview.views / layout / datamodel,
  kivy.uix.rst, kivy.uix.vkeyboard, kivy.uix.effectwidget, kivy.uix.behaviors.* (real DragBehavior ...),
  and the properties / methods that were missing on Widget, Label, Button, TextInput, ScrollView, Slider, ...
"""
import os, sys, re, time, json, weakref, struct
import kivyshim as K
import kivy_ui as U
from kivyshim import (EventDispatcher, Widget, Label, Button, BoxLayout, GridLayout, FloatLayout, Property,
                      StringProperty, NumericProperty, BooleanProperty, ListProperty, ObjectProperty, DictProperty,
                      AliasProperty, ReferenceListProperty, Clock, Window)
import kivy_gfx as G

tk = K.tk


# ===================================================================== small helpers
def _addprop(cls, name, prop):
    """add a Property to an existing class (only if the class does not know the name yet)"""
    if hasattr(cls, name): return
    prop.__set_name__(cls, name)
    setattr(cls, name, prop)


def _addattr(cls, name, value):
    if not hasattr(cls, name): setattr(cls, name, value)


# ===================================================================== kivy.resources
resource_paths = []


def resource_add_path(path):
    path = os.path.abspath(path)
    if path in resource_paths: resource_paths.remove(path)
    resource_paths.insert(0, path)


def resource_remove_path(path):
    path = os.path.abspath(path)
    if path in resource_paths: resource_paths.remove(path)


def resource_find(filename, use_cache=True):
    if not filename: return None
    filename = str(filename)
    if filename.startswith(("data:", "http://", "https://")): return filename
    if os.path.isabs(filename): return filename if os.path.exists(filename) else None
    dirs = list(resource_paths) + [os.getcwd(), os.environ.get("PYVORA_DIR") or ""]
    try:
        import runner
        sd = os.path.dirname(os.path.abspath(runner._SRC.get("path", "")))
        if sd: dirs.append(sd)
    except Exception: pass
    for d in dirs:
        if not d: continue
        p = os.path.join(d, filename)
        if os.path.exists(p): return os.path.abspath(p)
    return None


# Image(source="x.png") also looks into resource paths
def _image_img(self):
    src = self.source
    if not src: return None
    if not os.path.isfile(src):
        p = resource_find(src)
        if p: src = p
    try: return tk.PhotoImage(file=src)
    except Exception: return None


U.Image._img = _image_img


# ===================================================================== images / textures / text (kivy.core.*)
def _image_size(path):
    """(width, height) of a png / gif / jpeg file, read from its header"""
    try:
        with open(path, "rb") as f: h = f.read(32)
        if h[:8] == b"\x89PNG\r\n\x1a\n": return struct.unpack(">II", h[16:24])
        if h[:3] == b"GIF": return struct.unpack("<HH", h[6:10])
        if h[:2] == b"BM":
            with open(path, "rb") as f: f.seek(18); return struct.unpack("<ii", f.read(8))[0], abs(struct.unpack("<ii", f.read(0) or b"\0" * 8)[0]) or 0
        if h[:2] == b"\xff\xd8":
            with open(path, "rb") as f:
                f.read(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff": b = f.read(1)
                    while b == b"\xff": b = f.read(1)
                    if not b: break
                    t = b[0]
                    if 0xC0 <= t <= 0xCF and t not in (0xC4, 0xC8, 0xCC):
                        f.read(3); hh, ww = struct.unpack(">HH", f.read(4)); return ww, hh
                    n = struct.unpack(">H", f.read(2))[0]; f.read(n - 2)
    except Exception: pass
    return (0, 0)


class CoreImage(EventDispatcher):
    """kivy.core.image.Image"""
    def __init__(self, arg=None, ext=None, **kw):
        EventDispatcher.__init__(self)
        self.filename = arg if isinstance(arg, str) else kw.get("filename", "")
        self.width, self.height = 0, 0
        if self.filename:
            p = resource_find(self.filename) or self.filename
            self.width, self.height = _image_size(p)
        elif isinstance(arg, G.Texture): self.width, self.height = arg.size
        self.texture = G.Texture(self.width or 1, self.height or 1)
        self.anim_available = False; self.anim_delay = .25; self.keep_data = False
    @property
    def size(self): return (self.width, self.height)
    @property
    def nocache(self): return False
    def read_pixel(self, x, y): return (1, 1, 1, 1)
    def save(self, *a, **k): print("[kivy] Image.save is not supported in this editor"); return False
    @staticmethod
    def load(filename, **kw): return CoreImage(filename, **kw)


class CoreLabel(EventDispatcher):
    """kivy.core.text.Label (CoreLabel): measure text, no real texture"""
    def __init__(self, text="", font_size=12, font_name="Roboto", bold=False, italic=False, halign="left", valign="bottom",
                 text_size=None, padding=0, markup=False, **kw):
        EventDispatcher.__init__(self)
        self.options = dict(text=text, font_size=font_size, font_name=font_name, bold=bold, italic=italic, halign=halign,
                            valign=valign, text_size=text_size or (None, None), padding=padding, markup=markup, **kw)
        self.text = text; self.texture = None; self._size = (0, 0)
    def _w(self, t):
        fs = float(self.options.get("font_size") or 12)
        f = 0.6 if self.options.get("bold") else 0.55
        return len(t) * fs * f
    def get_extents(self, text):
        fs = float(self.options.get("font_size") or 12)
        return (self._w(text), fs * 1.35)
    get_cached_extents = lambda self: self.get_extents
    def refresh(self):
        txt = self.text or ""
        lines = txt.split("\n") or [""]
        ts = self.options.get("text_size") or (None, None)
        w = max(self._w(l) for l in lines)
        if ts[0]:
            import math
            n = sum(max(1, int(math.ceil(self._w(l) / float(ts[0])))) for l in lines)
            w = min(w, float(ts[0])); h = n * float(self.options.get("font_size") or 12) * 1.35
        else: h = len(lines) * float(self.options.get("font_size") or 12) * 1.35
        self._size = (w, h); self.texture = G.Texture(max(1, int(w)), max(1, int(h)))
    def render(self): self.refresh()
    @property
    def content_size(self): return self._size
    @property
    def content_width(self): return self._size[0]
    @property
    def content_height(self): return self._size[1]
    @property
    def size(self): return self._size
    @property
    def width(self): return self._size[0]
    @property
    def height(self): return self._size[1]
    @staticmethod
    def register(name, fn_regular, fn_italic=None, fn_bold=None, fn_bolditalic=None):
        _FONTS[name] = dict(regular=fn_regular, italic=fn_italic, bold=fn_bold, bolditalic=fn_bolditalic)
    @staticmethod
    def find_base_direction(text): return "ltr"
    @staticmethod
    def get_system_fonts_dir(): return []


_FONTS = {}
DEFAULT_FONT = "Roboto"


class MarkupLabel(CoreLabel):
    @property
    def markup(self):
        return re.findall(r"\[[^\]]*\]|[^\[]+", self.text or "")
    @property
    def unstripped_markup(self): return self.text
    @property
    def stripped_markup(self): return re.sub(r"\[/?[a-z_]+(?:=[^\]]*)?\]", "", self.text or "")


# ===================================================================== kivy.base
class _EventLoop(EventDispatcher):
    status = "idle"; window = None
    def ensure_window(self): self.window = Window; return Window
    def start(self): pass
    def close(self): tk._st["quit"] = True
    def stop(self): tk._st["quit"] = True
    def idle(self): pass
    def add_event_listener(self, l): pass
    def remove_event_listener(self, l): pass
    def add_input_provider(self, p, auto_remove=False): pass
    def remove_input_provider(self, p): pass
    def post_dispatch_input(self, *a): pass
    def add_postproc_module(self, m): pass
    def remove_postproc_module(self, m): pass
    @property
    def touches(self): return []


EventLoop = _EventLoop()


def runTouchApp(widget=None, embedded=False):
    if widget is None: return

    class _RunApp(K.App):
        def build(self): return widget
    _RunApp().run()


def stopTouchApp(): tk._st["quit"] = True


class ExceptionHandler:
    def handle_exception(self, inst): return 0


class ExceptionManager:
    handlers = []
    @classmethod
    def add_handler(cls, h): cls.handlers.append(h)
    @classmethod
    def remove_handler(cls, h):
        if h in cls.handlers: cls.handlers.remove(h)


# ===================================================================== kivy.config (a real in-memory config)
_DEFAULTS = {
    "kivy": {"log_level": "info", "log_enable": "1", "keyboard_mode": "", "exit_on_escape": "1", "desktop": "0",
             "window_icon": "", "pause_on_minimize": "0", "default_font": "['Roboto', 'data/fonts/Roboto-Regular.ttf']"},
    "graphics": {"width": "800", "height": "600", "fullscreen": "0", "resizable": "1", "borderless": "0", "rotation": "0",
                 "maxfps": "60", "position": "auto", "show_cursor": "1", "multisamples": "2", "vsync": "1"},
    "input": {}, "postproc": {}, "widgets": {"scroll_timeout": "55", "scroll_distance": "20"}, "modules": {},
}


class ConfigParser:
    def __init__(self, name="", **kw):
        self._d = {}; self._name = name; self._filename = None
        self._callbacks = []
    @staticmethod
    def get_configparser(name): return _CONFIGS.get(name)
    def add_section(self, section): self._d.setdefault(section, {})
    def has_section(self, section): return section in self._d
    def sections(self): return list(self._d)
    def has_option(self, section, option): return option in self._d.get(section, {})
    def options(self, section): return list(self._d.get(section, {}))
    def items(self, section): return list(self._d.get(section, {}).items())
    def set(self, section, option, value):
        self._d.setdefault(section, {})
        value = str(value)
        old = self._d[section].get(option)
        self._d[section][option] = value
        if old != value:
            for cb in list(self._callbacks):
                try: cb(section, option, value)
                except Exception: pass
        return value
    def setall(self, section, keyvalues):
        for k, v in keyvalues.items(): self.set(section, k, v)
    def setdefault(self, section, option, value):
        self._d.setdefault(section, {})
        if option not in self._d[section]: self._d[section][option] = str(value)
    def setdefaults(self, section, keyvalues):
        self.adddefaultsection(section)
        for k, v in keyvalues.items(): self.setdefault(section, k, v)
    def adddefaultsection(self, section): self._d.setdefault(section, {})
    def get(self, section, option, **kw):
        try: return self._d[section][option]
        except KeyError:
            if "fallback" in kw: return kw["fallback"]
            raise KeyError("No option %r in section %r" % (option, section))
    def getdefault(self, section, option, defaultvalue):
        try: return self.get(section, option)
        except KeyError: return defaultvalue
    def getint(self, section, option, **kw): return int(float(self.get(section, option, **kw)))
    def getfloat(self, section, option, **kw): return float(self.get(section, option, **kw))
    def getboolean(self, section, option, **kw):
        v = self.get(section, option, **kw)
        if isinstance(v, bool): return v
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    def getdefaultint(self, section, option, defaultvalue):
        try: return self.getint(section, option)
        except Exception: return defaultvalue
    def remove_option(self, section, option):
        return self._d.get(section, {}).pop(option, None) is not None
    def remove_section(self, section): return self._d.pop(section, None) is not None
    def read(self, filename):
        self._filename = filename
        if not (filename and os.path.isfile(filename)): return []
        sec = None
        try:
            with open(filename, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line[0] in "#;": continue
                    if line.startswith("[") and line.endswith("]"): sec = line[1:-1]; self._d.setdefault(sec, {}); continue
                    if sec is None: continue
                    for sep in ("=", ":"):
                        if sep in line:
                            k, v = line.split(sep, 1); self._d[sec][k.strip()] = v.strip(); break
        except OSError: return []
        return [filename]
    def write(self):
        fn = self._filename
        if not fn: return False
        try:
            d = os.path.dirname(os.path.abspath(fn))
            if d and not os.path.isdir(d): os.makedirs(d, exist_ok=True)
            with open(fn, "w", encoding="utf-8") as f:
                for sec, items in self._d.items():
                    f.write("[%s]\n" % sec)
                    for k, v in items.items(): f.write("%s = %s\n" % (k, v))
                    f.write("\n")
            return True
        except OSError: return False
    def update_config(self, filename, overwrite=False):
        other = ConfigParser(); other.read(filename)
        for s, items in other._d.items():
            for k, v in items.items():
                if overwrite or not self.has_option(s, k): self.set(s, k, v)
    def add_callback(self, callback, section=None, key=None): self._callbacks.append(callback)
    def remove_callback(self, callback, section=None, key=None):
        if callback in self._callbacks: self._callbacks.remove(callback)
    def read_dict(self, d):
        for s, items in d.items(): self.setall(s, items)


_CONFIGS = {}
Config = ConfigParser("kivy")
for _s, _items in _DEFAULTS.items():
    Config.adddefaultsection(_s)
    for _k, _v in _items.items(): Config.setdefault(_s, _k, _v)
K.Config = Config


# ---- App: config / name / directory / settings
def _app_name(self):
    n = type(self).__name__
    return (n[:-3] if n.endswith("App") else n).lower() or "app"


def _app_load_config(self):
    cfg = ConfigParser(self.name)
    _CONFIGS[self.name] = cfg
    try: self.build_config(cfg)
    except Exception as e: K.runner.report_exc(e)
    ini = self.get_application_config()
    if ini: cfg.read(ini)
    cfg._filename = ini
    return cfg


def _app_get_application_config(self, defaultpath="%(appdir)s/%(appname)s.ini"):
    d = self.user_data_dir
    return os.path.join(d, self.name + ".ini")


_orig_run = K.App.run


def _app_run(self):
    try: self.config = self.load_config()
    except Exception as e: K.runner.report_exc(e)
    return _orig_run(self)


K.App.name = property(_app_name)
K.App.directory = property(lambda self: os.getcwd())
K.App.kv_directory = None
K.App.use_kivy_settings = True
K.App.settings_cls = None
K.App.options = None
K.App.config = None
K.App.load_config = _app_load_config
K.App.get_application_config = _app_get_application_config
K.App.get_application_name = lambda self: self.title
K.App.get_application_icon = lambda self: self.icon
K.App.destroy_settings = lambda self: None
K.App.run = _app_run


# ===================================================================== utils / clock / small kivy.* modules
class QueryDict(dict):
    def __getattr__(self, attr):
        try: return self.__getitem__(attr)
        except KeyError: return super().__getattr__(attr)
    def __setattr__(self, attr, value): self.__setitem__(attr, value)


def deprecated(func=None, msg=""):
    def deco(f): return f
    return deco(func) if callable(func) else deco


class reify:
    def __init__(self, func): self.func = func; self.__doc__ = getattr(func, "__doc__", "")
    def __get__(self, inst, cls):
        if inst is None: return self
        v = self.func(inst); setattr(inst, self.func.__name__, v); return v


def is_color_transparent(c):
    if len(c) < 4: return False
    return float(c[3]) == 0.0


def intersection(set1, set2): return [s for s in set1 if s in set2]
def difference(set1, set2): return [s for s in set1 if s not in set2]


class SafeList(list):
    def clear(self): del self[:]
    def __iter__(self): return list.__iter__(list(self))


def get_color_from_hex(h): return K.get_color_from_hex(h)
def get_hex_from_color(c): return K.get_hex_from_color(c)


def triggered(timeout=0, interval=False):
    def deco(func):
        ev = []
        def wrapper(*a, **k):
            def cb(dt): return func(*a, **k)
            if ev and not ev[0].cancelled and ev[0] in Clock._ev: ev[0].cancel()
            ev[:] = [Clock.schedule_interval(cb, timeout) if interval else Clock.schedule_once(cb, timeout)]
        return wrapper
    return deco


class Cache:
    _categories = {}; _objects = {}
    @staticmethod
    def register(category, limit=None, timeout=None):
        Cache._categories[category] = dict(limit=limit, timeout=timeout); Cache._objects.setdefault(category, {})
    @staticmethod
    def append(category, key, obj, timeout=None):
        Cache._objects.setdefault(category, {})
        lim = Cache._categories.get(category, {}).get("limit")
        d = Cache._objects[category]
        if lim and len(d) >= lim and key not in d: d.pop(next(iter(d)))
        d[key] = dict(object=obj, lastaccess=time.time())
    @staticmethod
    def get(category, key, default=None):
        o = Cache._objects.get(category, {}).get(key)
        if o is None: return default
        o["lastaccess"] = time.time(); return o["object"]
    @staticmethod
    def remove(category, key=None):
        if key is None: Cache._objects.pop(category, None)
        else: Cache._objects.get(category, {}).pop(key, None)
    @staticmethod
    def clear_all(): Cache._objects.clear()
    @staticmethod
    def print_usage(): print("Cache:", {c: len(v) for c, v in Cache._objects.items()})
    @staticmethod
    def get_lastaccess(category, key, default=None):
        o = Cache._objects.get(category, {}).get(key); return o["lastaccess"] if o else default
    @staticmethod
    def get_timestamp(category, key, default=None): return Cache.get_lastaccess(category, key, default)


class WeakMethod:
    def __init__(self, method):
        self._obj = weakref.ref(method.__self__) if hasattr(method, "__self__") else None
        self._func = getattr(method, "__func__", method); self._method = method
    def is_dead(self): return self._obj is not None and self._obj() is None
    def __call__(self):
        if self._obj is None: return self._func
        o = self._obj()
        return None if o is None else getattr(o, self._func.__name__)
    def __eq__(self, other): return isinstance(other, WeakMethod) and self() == other()
    def __hash__(self): return hash((id(self._func), id(self._obj)))


def _parse_color(text):
    text = text.strip()
    if text.startswith("#"): return list(K.get_color_from_hex(text))
    return list(K.ColorProperty._plain(text)) if text.lower() in K._NAMED else [float(x) for x in text.strip("()[]").split(",")]


def parse_bool(text):
    if str(text).lower() in ("true", "1", "yes", "on"): return True
    if str(text).lower() in ("false", "0", "no", "off"): return False
    raise Exception("Invalid boolean: %r" % text)
def parse_int(text): return int(float(text))
def parse_float(text): return float(text)
def parse_string(text): return text[1:-1] if text[:1] in "'\"" and text[-1:] == text[:1] else text
def parse_int2(text): return tuple(int(x) for x in text.split())[:2]
def parse_float4(text): return tuple(float(x) for x in text.split())[:4]
def parse_filename(filename): return resource_find(filename) or filename


class _Context(dict):
    def sandbox(self, *a): return self
    def push(self): pass
    def pop(self): pass
    def get_context(self): return self
    def register_context(self, name, cls, *a, **k): self[name] = cls(*a, **k)


class _Modules:
    def __init__(self): self.mods = {}
    def register_args(self, *a, **k): pass
    def add_module(self, name, mod): self.mods[name] = mod
    def usage_list(self): return []
    def list(self): return dict(self.mods)
    def activate_module(self, *a, **k): pass
    def deactivate_module(self, *a, **k): pass
    def configure(self): pass


class _Loader:
    loading_image = None; error_image = None; num_workers = 2; max_upload_per_frame = 2
    def image(self, filename, load_callback=None, post_callback=None, **kw):
        im = CoreImage(filename)
        if post_callback: Clock.schedule_once(lambda dt: post_callback(im), 0)
        return im
    def start(self): pass
    def stop(self): pass
    def pause(self): pass
    def resume(self): pass


class Atlas(EventDispatcher):
    """kivy.atlas.Atlas: reads the .atlas json (region names / sizes); textures are placeholders"""
    def __init__(self, filename, **kw):
        EventDispatcher.__init__(self)
        self.filename = filename; self.textures = {}; self.uvmap = {}
        f = resource_find(filename) or filename
        try:
            with open(f, encoding="utf-8") as fh: data = json.load(fh)
            for img, regions in data.items():
                for name, (x, y, w, h) in regions.items():
                    self.textures[name] = G.Texture(w, h)
        except Exception: pass
    def __getitem__(self, k): return self.textures[k]
    def __contains__(self, k): return k in self.textures
    def keys(self): return self.textures.keys()


class AbstractStore(EventDispatcher):
    def __init__(self, **kw):
        EventDispatcher.__init__(self)
        self._data = {}
    def put(self, key, **values): self._data[key] = dict(values); return True
    def get(self, key):
        if key not in self._data: raise KeyError(key)
        return dict(self._data[key])
    def exists(self, key): return key in self._data
    def delete(self, key):
        if key not in self._data: raise KeyError(key)
        del self._data[key]
    def keys(self): return list(self._data)
    def count(self): return len(self._data)
    def clear(self): self._data = {}
    def find(self, **filters):
        for k, v in self._data.items():
            if all(v.get(f) == x for f, x in filters.items()): yield k, dict(v)
    def __contains__(self, k): return k in self._data
    def __getitem__(self, k): return self.get(k)
    def __setitem__(self, k, v): self.put(k, **v)
    def __delitem__(self, k): self.delete(k)
    def __len__(self): return len(self._data)
    def __iter__(self): return iter(self._data)


class DictStore(AbstractStore):
    def __init__(self, data=None, **kw):
        AbstractStore.__init__(self)
        if data: self._data = {k: dict(v) for k, v in data.items()}


# ---- scroll effects (accepted by ScrollView(effect_cls=...))
class ScrollEffect(EventDispatcher):
    scroll = NumericProperty(0); velocity = NumericProperty(0); friction = NumericProperty(0.015)
    min = NumericProperty(0); max = NumericProperty(0); overscroll = NumericProperty(0); is_manual = BooleanProperty(False)
    def start(self, val, t=None): pass
    def update(self, val, t=None): pass
    def stop(self, val, t=None): pass
    def reset(self, pos): pass
    def cancel(self): pass
    def update_velocity(self, dt): pass
class DampedScrollEffect(ScrollEffect):
    spring_constant = NumericProperty(2.0); edge_damping = NumericProperty(0.25)
class OpacityScrollEffect(DampedScrollEffect): pass
class KineticEffect(ScrollEffect): pass


# ===================================================================== kivy.core.window: Keyboard (+ missing Window API)
class Keyboard(EventDispatcher):
    keycodes = {"backspace": 8, "tab": 9, "enter": 13, "escape": 27, "spacebar": 32, "delete": 127, "left": 276, "right": 275,
                "up": 273, "down": 274, "home": 278, "end": 279, "pageup": 280, "pagedown": 281, "insert": 277,
                "shift": 304, "rshift": 303, "lctrl": 306, "rctrl": 305, "alt": 308, "capslock": 301,
                "f1": 282, "f2": 283, "f3": 284, "f4": 285, "f5": 286, "f6": 287, "f7": 288, "f8": 289, "f9": 290, "f10": 291,
                "f11": 292, "f12": 293}
    keycodes.update({chr(c): c for c in range(97, 123)}); keycodes.update({str(n): 48 + n for n in range(10)})
    def __init__(self, **kw):
        EventDispatcher.__init__(self)
        self.window = Window; self.callback = None; self.target = None; self.widget = None
    def release(self): pass
    def keycode_to_string(self, value):
        for k, v in self.keycodes.items():
            if v == value: return k
        return ""
    def string_to_keycode(self, value): return self.keycodes.get(value, -1)


def _win_patches():
    W = type(Window)
    for n, v in dict(keyboard_height=0, rotation=0, borderless=False, always_on_top=False, mouse_pos=(0, 0), allow_screensaver=True,
                     focus=True, position="auto", shape_image="", opacity=1.0, resizable=True, minimum_width=0, minimum_height=0,
                     show_cursor=True, grab_mouse_pos=False).items():
        _addattr(W, n, v)
    _addattr(W, "system_size", property(lambda s: (s.width, s.height)))
    _addattr(W, "center", property(lambda s: (s.width / 2.0, s.height / 2.0)))
    _addattr(W, "children", property(lambda s: list(K._st["app"].root._kids) if K._st.get("app") and K._st["app"].root else []))
    _addattr(W, "remove_widget", lambda s, w: K._st["app"].root.remove_widget(w) if K._st.get("app") else None)
    _addattr(W, "show_keyboard", lambda s, *a, **k: None)
    _addattr(W, "hide_keyboard", lambda s, *a, **k: None)
    _addattr(W, "set_icon", lambda s, *a, **k: None)
    _addattr(W, "raise_window", lambda s, *a, **k: None)
    _addattr(W, "release_keyboard", lambda s, *a, **k: None)
    _addattr(W, "screenshot", lambda s, *a, **k: print("[kivy] Window.screenshot is not supported in this editor"))
    _addattr(W, "set_system_cursor", lambda s, *a, **k: None)
    _addattr(W, "toggle_fullscreen", lambda s, *a, **k: None)
    _addattr(W, "get_size", lambda s: (s.width, s.height))
    # events that Window.bind(...) callers expect to exist
    ev = tuple(getattr(W, "__events__", ()) or ())
    W.__events__ = ev + tuple(e for e in ("on_resize", "on_key_down", "on_key_up", "on_keyboard", "on_touch_down", "on_touch_move",
                                          "on_touch_up", "on_request_close", "on_dropfile", "on_drop_file", "on_motion",
                                          "on_draw", "on_flip", "on_rotate", "on_close", "on_minimize", "on_maximize",
                                          "on_restore", "on_show", "on_hide", "on_cursor_enter", "on_cursor_leave") if e not in ev)


_win_patches()


def _win_resize_hook():
    """Window.bind(on_resize=...) really fires when the page size changes"""
    W = type(Window)
    _orig_bind = W.bind

    def _hook(self, tries=0):
        host = K._st.get("host")
        if host is None:
            if tries < 20: Clock.schedule_once(lambda dt: _hook(self, tries + 1), 0.1)
            return
        if self.__dict__.get("_rz"): return
        self.__dict__["_rz"] = True
        last = [None]
        def on_cfg(e):
            try: size = (int(getattr(e, "width", 0) or tk._st["w"]), int(getattr(e, "height", 0) or tk._st["h"]))
            except Exception: return
            if size[0] <= 1 or size[1] <= 1 or size == last[0]: return
            last[0] = size
            self.dispatch("on_resize", size[0], size[1])
        try: host.bind("<Configure>", on_cfg, add="+")
        except Exception: pass

    def bind(self, **kw):
        _orig_bind(self, **kw)
        if "on_resize" in kw or "size" in kw or "width" in kw or "height" in kw:
            Clock.schedule_once(lambda dt: _hook(self), 0)
    W.bind = bind


_win_resize_hook()


# ===================================================================== missing properties / methods on existing classes
def _patch_widgets():
    # ---- Widget
    for n, p in (("size_hint_min_x", Property(None)), ("size_hint_min_y", Property(None)), ("size_hint_max_x", Property(None)),
                 ("size_hint_max_y", Property(None)), ("motion_filter", DictProperty({}))):
        _addprop(Widget, n, p)
    _addattr(Widget, "size_hint_min", property(lambda s: [s.size_hint_min_x, s.size_hint_min_y]))
    _addattr(Widget, "size_hint_max", property(lambda s: [s.size_hint_max_x, s.size_hint_max_y]))
    _addattr(Widget, "proxy_ref", property(lambda s: s))
    _addattr(Widget, "cls", property(lambda s: [type(s).__name__]))
    _addattr(Widget, "walk_reverse", lambda s, loopback=False: reversed(list(s.walk())))
    _addattr(Widget, "collide_widget", lambda s, w: not (s.right < w.x or s.x > w.right or s.top < w.y or s.y > w.top))
    _addattr(Widget, "apply_class_lang_rules", lambda s, *a, **k: K.Builder.apply(s))
    _addattr(Widget, "export_as_image", lambda s, *a, **k: CoreImage(G.Texture(int(s.width), int(s.height))))
    _addattr(Widget, "events", lambda s: list(type(s)._all_events()))
    _addattr(Widget, "property", lambda s, name, quiet=False: type(s).__dict__.get(name) or next((vars(c)[name] for c in type(s).__mro__ if name in vars(c)), None))

    def create_property(self, name, value=None, default_value=True, *a, **k):
        p = Property(value); p.__set_name__(type(self), name); setattr(type(self), name, p)
        if value is not None: setattr(self, name, value)
        return p
    _addattr(EventDispatcher, "create_property", create_property)
    _addattr(EventDispatcher, "apply_property", lambda self, **kw: [self.create_property(k, v) for k, v in kw.items()])
    _addattr(EventDispatcher, "unbind_uid", lambda self, name, uid: None)
    _addattr(EventDispatcher, "refresh_property", lambda self, name: self._notify(name, getattr(self, name)))

    # ---- Label
    for n, p in (("underline", BooleanProperty(False)), ("strikethrough", BooleanProperty(False)),
                 ("shorten", BooleanProperty(False)), ("shorten_from", Property("center")), ("max_lines", NumericProperty(0)),
                 ("line_height", NumericProperty(1.0)), ("padding_x", NumericProperty(0)), ("padding_y", NumericProperty(0)),
                 ("refs", DictProperty({})), ("anchors", DictProperty({})), ("disabled_color", ListProperty([1, 1, 1, .3])),
                 ("outline_width", NumericProperty(0)), ("outline_color", ListProperty([0, 0, 0, 1])), ("mipmap", BooleanProperty(False)),
                 ("strip", BooleanProperty(False)), ("split_str", StringProperty(" ")), ("unicode_errors", StringProperty("replace")),
                 ("font_family", StringProperty("")), ("font_hinting", Property("normal")), ("font_kerning", BooleanProperty(True)),
                 ("font_blended", BooleanProperty(True)), ("base_direction", Property(None)), ("text_language", Property(None)),
                 ("is_shortened", BooleanProperty(False)), ("ellipsis_options", DictProperty({})), ("limit_render_to_text_bbox", BooleanProperty(False))):
        _addprop(Label, n, p)
    _addattr(Label, "texture", property(lambda s: G.Texture(int(s.texture_size[0]), int(s.texture_size[1]))))
    _addattr(Label, "texture_update", lambda s, *a: s._notify("texture_size", s.texture_size))
    # underline / strikethrough really drawn
    def _font(self):
        st = " ".join(x for x, on in (("bold", self.bold), ("italic", self.italic), ("underline", self.underline),
                                      ("overstrike", self.strikethrough)) if on)
        return (self.font_name if self.font_name != "Roboto" else "Roboto", -int(self.font_size or 15)) + ((st,) if st else ())
    Label._font = _font
    # Label padding / max_lines / shorten
    _orig_shown = Label._shown
    def _shown(self):
        t = _orig_shown(self)
        ml = int(self.max_lines or 0)
        if ml > 0:
            ls = t.split("\n")
            if len(ls) > ml: t = "\n".join(ls[:ml])
        if self.shorten and self.text_size and self.text_size[0]:
            lim = int(self.text_size[0] / max(1.0, (self.font_size or 15) * .55))
            if len(t) > lim > 3: t = t[:lim - 3] + "..."
        return t
    Label._shown = _shown

    # ---- Button
    for n, p in (("background_disabled_normal", StringProperty("")), ("background_disabled_down", StringProperty("")),
                 ("border", ListProperty([16, 16, 16, 16])), ("always_release", BooleanProperty(False)),
                 ("min_state_time", NumericProperty(0)), ("last_touch", ObjectProperty(None))):
        _addprop(Button, n, p)
    _addattr(Button, "trigger_action", lambda s, duration=0.1: (s.dispatch("on_press"), s.dispatch("on_release")))

    # ---- TextInput
    TI = K.TextInput
    for n, p in (("hint_text_color", ListProperty([.5, .5, .5, 1])), ("cursor_color", ListProperty([1, 0, 0, 1])),
                 ("selection_color", ListProperty([.18, .65, .83, .5])), ("keyboard_suggestions", BooleanProperty(True)),
                 ("password_mask", StringProperty("*")), ("scroll_x", NumericProperty(0)), ("scroll_y", NumericProperty(0)),
                 ("tab_width", NumericProperty(4)), ("line_height", NumericProperty(1.0)), ("unfocus_on_touch", BooleanProperty(True)),
                 ("use_bubble", BooleanProperty(False)), ("use_handles", BooleanProperty(False)), ("allow_copy", BooleanProperty(True)),
                 ("base_direction", Property(None)), ("lines_to_scroll", NumericProperty(3)), ("cursor_width", NumericProperty(1)),
                 ("cursor_blink", BooleanProperty(True)), ("handle_image_left", StringProperty("")), ("handle_image_right", StringProperty("")),
                 ("handle_image_middle", StringProperty("")), ("text_validate_unfocus", BooleanProperty(True)),
                 ("do_wrap", BooleanProperty(True)), ("replace_crlf", BooleanProperty(True)), ("write_tab", BooleanProperty(True)),
                 ("padding_x", NumericProperty(6)), ("padding_y", NumericProperty(6)), ("selection_from", NumericProperty(0)),
                 ("selection_to", NumericProperty(0)), ("is_focusable", BooleanProperty(True)), ("keyboard_mode", Property("auto")),
                 ("minimum_height", NumericProperty(0)), ("scroll_distance", NumericProperty(20))):
        _addprop(TI, n, p)

    def _ti_pos(self):
        w = self._w
        if w is None: return len(self.text)
        try:
            if self.multiline: return len(w.get("1.0", "insert"))
            return int(w.index("insert"))
        except Exception: return len(self.text)

    def _ti_set_pos(self, i):
        w = self._w
        if w is None: return
        i = max(0, min(int(i), len(self.text)))
        try:
            if self.multiline: w.mark_set("insert", "1.0+%dc" % i)
            else: w.icursor(i)
        except Exception: pass

    def _ti_sel(self):
        """(start, end) of the selection or None"""
        w = self._w
        if w is None: return None
        try:
            if self.multiline:
                r = w.tag_ranges("sel")
                if r:
                    a = len(w.get("1.0", r[0])); b = len(w.get("1.0", r[1])); return (min(a, b), max(a, b))
            elif w.selection_present():
                a = int(w.index("sel.first")); b = int(w.index("sel.last")); return (min(a, b), max(a, b))
        except Exception: pass
        return None

    def _ti_select_text(self, start, end):
        w = self._w
        if w is None: return
        a, b = sorted((max(0, int(start)), min(len(self.text), int(end))))
        try:
            if self.multiline:
                w.tag_remove("sel", "1.0", "end"); w.tag_add("sel", "1.0+%dc" % a, "1.0+%dc" % b)
            else: w.selection_range(a, b)
        except Exception: pass

    def _ti_select_all(self): _ti_select_text(self, 0, len(self.text))

    def _ti_cancel_selection(self):
        w = self._w
        if w is None: return
        try:
            if self.multiline: w.tag_remove("sel", "1.0", "end")
            else: w.selection_clear()
        except Exception: pass

    def _ti_sel_text(self):
        s = _ti_sel(self)
        return self.text[s[0]:s[1]] if s else ""

    def _ti_copy(self, data=""):
        t = data or _ti_sel_text(self)
        if t:
            try: tk._st.get("root").clipboard_clear(); tk._st.get("root").clipboard_append(t)
            except Exception: pass
            _CLIP[0] = t

    _CLIP = [""]

    def _ti_paste(self):
        t = ""
        try: t = tk._st.get("root").clipboard_get()
        except Exception: pass
        t = t or _CLIP[0]
        if t: self.insert_text(t)

    def _ti_cut(self):
        s = _ti_sel(self)
        if s:
            _ti_copy(self); self.text = self.text[:s[0]] + self.text[s[1]:]; _ti_set_pos(self, s[0])

    def _ti_insert_text(self, substring, from_undo=False):
        s = _ti_sel(self); i = _ti_pos(self)
        if s: t = self.text[:s[0]] + substring + self.text[s[1]:]; i = s[0] + len(substring)
        else: t = self.text[:i] + substring + self.text[i:]; i += len(substring)
        self.text = t
        _ti_set_pos(self, i)

    def _ti_backspace(self, from_undo=False, mode="bkspc"):
        s = _ti_sel(self); i = _ti_pos(self)
        if s: self.text = self.text[:s[0]] + self.text[s[1]:]; _ti_set_pos(self, s[0]); return
        if mode == "del":
            self.text = self.text[:i] + self.text[i + 1:]; _ti_set_pos(self, i)
        elif i > 0:
            self.text = self.text[:i - 1] + self.text[i:]; _ti_set_pos(self, i - 1)

    def _ti_rowcol(self):
        i = _ti_pos(self); before = self.text[:i]
        row = before.count("\n"); col = i - (before.rfind("\n") + 1)
        return col, row

    def _ti_cursor_index(self, cursor=None):
        if cursor is None: return _ti_pos(self)
        col, row = cursor
        lines = self.text.split("\n"); row = max(0, min(row, len(lines) - 1))
        return sum(len(l) + 1 for l in lines[:row]) + max(0, min(col, len(lines[row])))

    def _ti_from_index(self, i):
        i = max(0, min(int(i), len(self.text))); before = self.text[:i]
        return (i - (before.rfind("\n") + 1), before.count("\n"))

    def _ti_undo(self):
        try: self._w.edit_undo()
        except Exception: pass

    def _ti_redo(self):
        try: self._w.edit_redo()
        except Exception: pass

    TI.cursor_index = _ti_cursor_index
    TI.cursor = property(lambda s: _ti_rowcol(s), lambda s, v: _ti_set_pos(s, _ti_cursor_index(s, tuple(v))))
    TI.cursor_col = property(lambda s: _ti_rowcol(s)[0])
    TI.cursor_row = property(lambda s: _ti_rowcol(s)[1])
    TI.selection_text = property(lambda s: _ti_sel_text(s), lambda s, v: None)
    TI.select_all = _ti_select_all
    TI.select_text = _ti_select_text
    TI.cancel_selection = _ti_cancel_selection
    TI.copy = _ti_copy; TI.paste = _ti_paste; TI.cut = _ti_cut
    TI.insert_text = _ti_insert_text
    TI.do_backspace = _ti_backspace
    TI.get_cursor_from_index = _ti_from_index
    TI.undo = _ti_undo; TI.redo = _ti_redo
    _addattr(TI, "do_cursor_movement", lambda s, action, control=False, alt=False: None)
    _addattr(TI, "get_cursor_from_xy", lambda s, x, y: (0, 0))
    _addattr(TI, "on_double_tap", lambda s, *a: None)
    _addattr(TI, "on_triple_tap", lambda s, *a: None)
    _addattr(TI, "on_quadruple_tap", lambda s, *a: None)

    # ---- GridLayout
    _addprop(GridLayout, "cols_minimum", DictProperty({})); _addprop(GridLayout, "rows_minimum", DictProperty({}))
    _addprop(GridLayout, "minimum_width", NumericProperty(0)); _addprop(GridLayout, "minimum_height", NumericProperty(0))
    for cls in (FloatLayout, BoxLayout, GridLayout, U.StackLayout, U.AnchorLayout):
        _addattr(cls, "do_layout", lambda s, *a: s._relayout())
        _addattr(cls, "layout_hint_with_bounds", lambda s, *a, **k: None)

    # ---- ScrollView
    SV = U.ScrollView
    for n, p in (("viewport_size", ListProperty([0, 0])), ("bar_inactive_color", ListProperty([.7, .7, .7, .2])),
                 ("bar_pos_y", Property("right")), ("bar_pos_x", Property("bottom")), ("bar_margin", NumericProperty(0)),
                 ("effect_x", ObjectProperty(None)), ("effect_y", ObjectProperty(None)), ("smooth_scroll_end", Property(None)),
                 ("scroll_wheel_distance", NumericProperty(20)), ("always_overscroll", BooleanProperty(True)),
                 ("do_scroll", ListProperty([True, True])), ("scroll_to_end", BooleanProperty(False))):
        _addprop(SV, n, p)
    _addattr(SV, "update_from_scroll", lambda s, *a: None)
    _addattr(SV, "update_from_motion", lambda s, *a: None)

    # ---- Slider / CheckBox / ProgressBar / Image / Popup / Spinner
    for n, p in (("value_track", BooleanProperty(False)), ("value_track_color", ListProperty([1, 1, 1, 1])),
                 ("value_track_width", NumericProperty(3)), ("cursor_size", ListProperty([32, 32])),
                 ("cursor_image", StringProperty("")), ("cursor_disabled_image", StringProperty("")),
                 ("sensitivity", Property("all")), ("padding", NumericProperty(16)), ("step", NumericProperty(0)),
                 ("background_width", NumericProperty(36)), ("background_horizontal", StringProperty("")),
                 ("background_vertical", StringProperty(""))):
        _addprop(K.Slider, n, p)
    _addattr(K.Slider, "value_normalized", property(lambda s: (s.value - s.min) / float((s.max - s.min) or 1),
                                                    lambda s, v: setattr(s, "value", s.min + v * (s.max - s.min))))
    _addattr(K.Slider, "value_pos", property(lambda s: (s.x + (s.value_normalized * s.width), s.center_y)))
    _addattr(K.Slider, "range", property(lambda s: (s.min, s.max), lambda s, v: (setattr(s, "min", v[0]), setattr(s, "max", v[1]))))
    _addprop(K.CheckBox, "allow_no_selection", BooleanProperty(True))
    _addprop(K.CheckBox, "state", Property("normal"))
    _addprop(K.CheckBox, "background_checkbox_normal", StringProperty(""))
    _addprop(K.ProgressBar, "min", NumericProperty(0))
    _addattr(K.ProgressBar, "value_normalized", property(lambda s: s.value / float(s.max or 1),
                                                         lambda s, v: setattr(s, "value", v * (s.max or 1))))
    for n, p in (("mipmap", BooleanProperty(False)), ("anim_delay", NumericProperty(.25)), ("anim_loop", NumericProperty(0)),
                 ("image_ratio", NumericProperty(1)), ("fit_mode", StringProperty("scale-down")), ("mipmap", BooleanProperty(False)),
                 ("texture_size_", ListProperty([0, 0]))):
        _addprop(U.Image, n, p)
    _addattr(U.Image, "texture", property(lambda s: G.Texture(int(s.texture_size[0]), int(s.texture_size[1]))))
    for n, p in (("title_align", Property("left")), ("separator_height", NumericProperty(2)), ("background", StringProperty("")),
                 ("background_color", ListProperty([1, 1, 1, 1])), ("border", ListProperty([16, 16, 16, 16])),
                 ("title_font", StringProperty("Roboto")), ("title_size", NumericProperty(14)), ("title_color", ListProperty([1, 1, 1, 1]))):
        _addprop(U.Popup, n, p)
    _addprop(U.Spinner, "sync_height", BooleanProperty(False))
    _addprop(U.Spinner, "text_autoupdate", BooleanProperty(False))


_patch_widgets()


# ===================================================================== new widgets
class StencilView(FloatLayout): pass


# ---- TreeView
class TreeViewNode(EventDispatcher):
    is_leaf = BooleanProperty(True); is_open = BooleanProperty(False); is_loaded = BooleanProperty(False)
    is_selected = BooleanProperty(False); no_selection = BooleanProperty(False); level = NumericProperty(0)
    odd = BooleanProperty(False); even = BooleanProperty(False)
    color_selected = ListProperty([.3, .3, .3, 1]); odd_color = ListProperty([1, 1, 1, .0]); even_color = ListProperty([.5, .5, .5, .1])
    parent_node = ObjectProperty(None)
    nodes = AliasProperty(lambda s: s.__dict__.setdefault("_tv_nodes", []), None)


class TreeViewLabel(Label, TreeViewNode):
    halign = Property("left")


class TreeViewException(Exception): pass


class TreeView(BoxLayout):
    __events__ = ("on_node_expand", "on_node_collapse")
    hide_root = BooleanProperty(False)
    indent_level = NumericProperty(16)
    indent_start = NumericProperty(24)
    selected_node = ObjectProperty(None)
    root_options = DictProperty({})
    load_func = ObjectProperty(None)
    minimum_width = NumericProperty(0)
    node_height = NumericProperty(30)

    def __init__(self, **kw):
        BoxLayout.__init__(self)
        self.orientation = "vertical"
        self.__dict__["_root"] = None
        self.__dict__["_busy"] = False
        root_kw = {"text": "Root", "is_open": True}
        root_kw.update(kw.pop("root_options", None) or {})
        self._apply_kw(kw)
        r = TreeViewLabel(**root_kw); r.is_leaf = False
        r.__dict__["_tv_nodes"] = []; r.level = 0
        self.__dict__["_root"] = r
        self._rows_refresh()

    @property
    def root(self): return self.__dict__["_root"]

    def on_node_expand(self, node): pass
    def on_node_collapse(self, node): pass

    # --- tree structure
    def add_node(self, node, parent=None):
        if parent is None: parent = self.root
        node.parent_node = parent
        node.level = parent.level + 1
        parent.__dict__.setdefault("_tv_nodes", []).append(node)
        node.__dict__.setdefault("_tv_nodes", [])
        parent.is_leaf = False
        self._style(node)
        self._rows_refresh()
        return node

    def remove_node(self, node):
        p = node.parent_node
        if p is None: return
        lst = p.__dict__.get("_tv_nodes", [])
        if node in lst: lst.remove(node)
        if not lst: p.is_leaf = True
        if self.selected_node is node: self.selected_node = None
        self._drop_row(node)
        self._rows_refresh()

    def toggle_node(self, node):
        node.is_open = not node.is_open
        if node.is_open:
            if self.load_func and not node.is_loaded:
                try:
                    for n in (self.load_func(self, node) or []): self.add_node(n, node)
                except Exception as e: K.runner.report_exc(e)
                node.is_loaded = True
            self.dispatch("on_node_expand", node)
        else: self.dispatch("on_node_collapse", node)
        self._rows_refresh()

    def select_node(self, node):
        if node.no_selection: return
        old = self.selected_node
        if old is not None: old.is_selected = False; self._paint(old)
        node.is_selected = True; self.selected_node = node; self._paint(node)

    def deselect_node(self, *a):
        if self.selected_node is not None:
            self.selected_node.is_selected = False; self._paint(self.selected_node); self.selected_node = None

    def iterate_all_nodes(self, node=None):
        node = node or self.root
        if node is not self.root or not self.hide_root: yield node
        for c in list(node.__dict__.get("_tv_nodes", [])):
            for x in self.iterate_all_nodes(c): yield x

    def iterate_open_nodes(self, node=None):
        node = node or self.root
        if node is not self.root or not self.hide_root: yield node
        if node.is_open or (node is self.root and self.hide_root):
            for c in list(node.__dict__.get("_tv_nodes", [])):
                for x in self.iterate_open_nodes(c): yield x

    def get_node_at_pos(self, pos): return None

    # --- drawing rows
    def _style(self, node):
        try:
            if node.size_hint_y is not None and node.size_hint_y == 1 and node.height in (100, 0): node.size_hint_y = None; node.height = self.node_height
            elif node.size_hint_y == 1: pass
        except Exception: pass

    def _paint(self, node):
        try:
            if node.__dict__.get("_tv_hl") is None:
                with node.canvas.before:
                    c = G.Color(0, 0, 0, 0); G.Rectangle(pos=node.pos, size=node.size)
                node.__dict__["_tv_hl"] = c
            c = node.__dict__["_tv_hl"]
            c.rgba = list(node.color_selected) if node.is_selected else [0, 0, 0, 0]
        except Exception: pass

    def _drop_row(self, node):
        row = node.__dict__.pop("_tv_row", None)
        if row is not None:
            try: row.remove_widget(node)
            except Exception: pass

    def _row(self, node):
        lv = node.level - (1 if self.hide_root else 0)
        row = node.__dict__.get("_tv_row")
        if row is not None and node.__dict__.get("_tv_lv") == lv and row.__dict__.get("_tv_open") == node.is_open and row.__dict__.get("_tv_leaf") == node.is_leaf:
            return row
        if row is not None:
            try: row.remove_widget(node)
            except Exception: pass
        h = node.height if node.size_hint_y is None else self.node_height
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=h)
        sp = Widget(size_hint_x=None, width=max(0, self.indent_start + lv * self.indent_level - 24))
        arrow = Button(text="" if node.is_leaf else ("v" if node.is_open else ">"), size_hint_x=None, width=24,
                       background_color=[0, 0, 0, 0], color=[.8, .8, .8, 1], font_size=13)
        if not node.is_leaf: arrow.bind(on_release=lambda *a, n=node: self.toggle_node(n))
        row.add_widget(sp); row.add_widget(arrow)
        if node.parent is not None and node.parent is not row:
            try: node.parent.remove_widget(node)
            except Exception: pass
        row.add_widget(node)
        node.size_hint_y = 1; node.size_hint_x = 1
        if not node.__dict__.get("_tv_bound"):
            node.__dict__["_tv_bound"] = True
            node.bind(on_touch_down=lambda inst, touch: (self.select_node(inst), False)[1])
        row.__dict__["_tv_open"] = node.is_open; row.__dict__["_tv_leaf"] = node.is_leaf
        node.__dict__["_tv_row"] = row; node.__dict__["_tv_lv"] = lv
        self._paint(node)
        return row

    def _rows_refresh(self):
        if self.__dict__.get("_busy") or self.root is None: return
        self.__dict__["_busy"] = True
        try:
            order = list(self.iterate_open_nodes())
            rows = [self._row(n) for n in order]
            for r in list(self._kids):
                if r not in rows: BoxLayout.remove_widget(self, r)
            for r in rows:
                if r.parent is not self: BoxLayout.add_widget(self, r)
            self.minimum_width = 0
        finally: self.__dict__["_busy"] = False

    def _prop_changed(self, name, value):
        BoxLayout._prop_changed(self, name, value)
        if name in ("hide_root", "indent_level", "indent_start") and self.root is not None:
            for n in list(self.iterate_all_nodes()): self._drop_row(n)
            self._rows_refresh()


# ---- RecycleView helpers (RecycleDataViewBehavior, LayoutSelectionBehavior, RecycleGridLayout)
class RecycleDataViewBehavior(EventDispatcher):
    index = Property(None)
    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        for k, v in data.items():
            if k == "viewclass": continue
            try: setattr(self, k, v)
            except Exception: pass
    def refresh_view_layout(self, rv, index, layout, viewport): pass
    def on_touch_down(self, touch): return False


class LayoutSelectionBehavior(EventDispatcher):
    selected_nodes = ListProperty([])
    multiselect = BooleanProperty(False)
    touch_multiselect = BooleanProperty(False)
    touch_deselect_last = BooleanProperty(False)
    keyboard_select = BooleanProperty(True)
    nodes_order_reversed = BooleanProperty(True)
    def _view(self, index):
        for c in self._kids:
            if getattr(c, "index", None) == index: return c
        return None
    def _apply(self, index, on):
        rv = getattr(self, "recycleview", None) or getattr(self, "parent", None)
        v = self._view(index)
        if v is not None and hasattr(v, "apply_selection"):
            try: v.apply_selection(rv, index, on)
            except Exception as e: K.runner.report_exc(e)
    def select_node(self, node):
        if node not in self.selected_nodes: self.selected_nodes.append(node)
        self._apply(node, True); return True
    def deselect_node(self, node, *a):
        if node in self.selected_nodes: self.selected_nodes.remove(node)
        self._apply(node, False)
    def clear_selection(self):
        for n in list(self.selected_nodes): self.deselect_node(n)
    def select_with_touch(self, node, touch=None):
        if node in self.selected_nodes and (self.multiselect or self.touch_deselect_last):
            self.deselect_node(node); return True
        if not self.multiselect and not self.touch_multiselect:
            for n in list(self.selected_nodes):
                if n != node: self.deselect_node(n)
        return self.select_node(node)
    def get_selectable_nodes(self): return [getattr(c, "index", None) for c in self._kids]
    def goto_node(self, key, last_node, last_node_idx): return last_node
    def select_with_key_down(self, *a, **k): return False
    def select_with_key_up(self, *a, **k): return False


class RecycleGridLayout(GridLayout):
    default_size = Property((None, 56))
    default_size_hint = Property((1, None))
    key_size = StringProperty(None)
    key_size_hint = StringProperty(None)
    key_viewclass = StringProperty("viewclass")
    orientation = Property("lr-tb")
    def __init__(self, **kw):
        GridLayout.__init__(self)
        self.cols = 1
        self._apply_kw(kw)


# patch RecycleView: accepts RecycleGridLayout, recycleview attr, RecycleDataViewBehavior, selection state
_RV = U.RecycleView
_rv_add_orig = _RV.add_widget


def _rv_add(self, w, *a, **k):
    if isinstance(w, RecycleGridLayout):
        self.layout_manager = w; w.recycleview = self
        U.ScrollView.add_widget(self, w, *a, **k); self.refresh_from_data(); return
    if isinstance(w, U.RecycleBoxLayout): w.recycleview = self
    return _rv_add_orig(self, w, *a, **k)


def _rv_refresh(self, *a, **k):
    lm = self.layout_manager
    if lm is None: return
    sel = list(getattr(lm, "selected_nodes", []) or [])
    lm.clear_widgets()
    vc = self.viewclass
    for i, item in enumerate(self.data):
        d = dict(item); cls = vc
        if "viewclass" in d: cls = d["viewclass"]
        if isinstance(cls, str): cls = K.Factory.get(cls)
        w = cls()
        dw, dh = lm.default_size; hx, hy = lm.default_size_hint
        w.size_hint_x, w.size_hint_y = hx, hy
        if dw is not None: w.width = dw
        if dh is not None: w.height = dh
        if hasattr(w, "refresh_view_attrs"):
            try: w.refresh_view_attrs(self, i, d)
            except Exception as e: K.runner.report_exc(e)
        else:
            for k2, v in d.items():
                if k2 == "viewclass": continue
                try: setattr(w, k2, v)
                except Exception: pass
            try: w.index = i
            except Exception: pass
        lm.add_widget(w)
        if hasattr(w, "apply_selection"):
            try: w.apply_selection(self, i, i in sel)
            except Exception as e: K.runner.report_exc(e)
    try: lm.minimum_height = lm.minimum_height
    except Exception: pass


_RV.add_widget = _rv_add
_RV.refresh_from_data = _rv_refresh
_addattr(_RV, "refresh_from_viewport", lambda s, *a: None)
_addattr(_RV, "refresh_from_layout", lambda s, *a: None)
_addattr(_RV, "scroll_to_index", lambda s, i: None)
_addattr(_RV, "key_viewclass", "viewclass")


class RecycleDataModel(EventDispatcher):
    data = ListProperty([])
class RecycleDataAdapter(EventDispatcher): pass
class RecycleLayoutManagerBehavior(EventDispatcher): pass


# ---- RstDocument (simple text version)
class RstDocument(U.ScrollView):
    text = StringProperty(""); source = StringProperty(""); title = StringProperty("")
    base_font_size = NumericProperty(31); colors = DictProperty({}); underline_color = StringProperty("")

    def __init__(self, **kw):
        U.ScrollView.__init__(self)
        self.__dict__["_lbl"] = None
        self._apply_kw(kw)
        self._build()

    @staticmethod
    def _rst(t):
        out = []; lines = t.split("\n")
        for i, l in enumerate(lines):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if re.fullmatch(r"[=\-~^\"#*+]{3,}", l.strip()): continue
            if l.strip() and re.fullmatch(r"[=\-~^\"#*+]{3,}", nxt.strip()) and len(nxt.strip()) >= len(l.strip()) - 1:
                out.append("[b]%s[/b]" % l.strip()); continue
            l = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", l)
            l = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"[i]\1[/i]", l)
            l = re.sub(r"``(.+?)``", r"[font=RobotoMono-Regular]\1[/font]", l)
            out.append(l)
        return "\n".join(out)

    def _build(self):
        t = self.text
        if not t and self.source:
            p = resource_find(self.source) or self.source
            try:
                with open(p, encoding="utf-8") as f: t = f.read()
            except OSError: t = ""
        try:
            for c in list(self._kids): self.remove_widget(c)
            lbl = Label(text=self._rst(t), markup=True, halign="left", valign="top", size_hint_y=None, height=max(60, 22 * (t.count("\n") + 2)),
                        text_size=[None, None], font_size=15)
            self.add_widget(lbl)
        except Exception: pass

    def _prop_changed(self, name, value):
        U.ScrollView._prop_changed(self, name, value)
        if name in ("text", "source") and self._w is not None: self._build()

    def render(self): self._build()


class RstVideoPlayer(U._Unsupported): _what = "RstVideoPlayer"


class VKeyboard(Widget):
    __events__ = ("on_key_down", "on_key_up", "on_textinput")
    target = ObjectProperty(None); layout = StringProperty("qwerty"); docked = BooleanProperty(True)
    margin_hint = ListProperty([.05, .06, .05, .06]); font_size = NumericProperty(20)
    def on_key_down(self, *a): pass
    def on_key_up(self, *a): pass
    def on_textinput(self, *a): pass
    def setup_mode(self, *a): pass
    def setup_mode_free(self): pass
    def setup_mode_dock(self): pass


class EffectBase(EventDispatcher):
    glsl = StringProperty(""); uniforms = DictProperty({})
class AdvancedEffectBase(EffectBase): pass
class MonochromeEffect(EffectBase): pass
class InvertEffect(EffectBase): pass
class ScanlinesEffect(EffectBase): pass
class ChannelMixEffect(EffectBase): pass
class PixelateEffect(EffectBase): pass
class HorizontalBlurEffect(EffectBase): pass
class VerticalBlurEffect(EffectBase): pass
class FXAAEffect(EffectBase): pass
class EffectWidget(FloatLayout):
    effects = ListProperty([]); background_color = ListProperty([0, 0, 0, 0])
    def add_widget(self, w, *a, **k): FloatLayout.add_widget(self, w, *a, **k)


# ---- behaviors (real DragBehavior + friends)
class DragBehavior(EventDispatcher):
    drag_distance = NumericProperty(20); drag_timeout = NumericProperty(55)
    drag_rect_x = NumericProperty(0); drag_rect_y = NumericProperty(0)
    drag_rect_width = NumericProperty(100); drag_rect_height = NumericProperty(100)
    drag_rectangle = ReferenceListProperty(drag_rect_x, drag_rect_y, drag_rect_width, drag_rect_height)

    def on_touch_down(self, touch):
        try:
            if self.disabled: return False
            touch.ud["_drag"] = [touch.x, touch.y, False]
        except Exception: pass
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        d = touch.ud.get("_drag")
        if d is not None:
            if not d[2]:
                if abs(touch.x - d[0]) + abs(touch.y - d[1]) >= max(0, float(self.drag_distance or 0)): d[2] = True
            if d[2]:
                try: self.x += touch.dx; self.y += touch.dy
                except Exception: pass
                return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        d = touch.ud.get("_drag")
        if d is not None:
            touch.ud["_drag"] = None
            if d[2]: return True
        return super().on_touch_up(touch)


class CompoundSelectionBehavior(LayoutSelectionBehavior): pass


class EmacsBehavior(EventDispatcher):
    key_bindings = StringProperty("emacs")
    def delete_word_right(self): pass
    def delete_word_left(self): pass


class CodeNavigationBehavior(EventDispatcher): pass


class TouchRippleButtonBehavior(U.ButtonBehavior):
    ripple_color = ListProperty([.8, .8, .8, .3]); ripple_duration_in = NumericProperty(.7)
    ripple_duration_out = NumericProperty(.3); ripple_fade_from_alpha = NumericProperty(.5); ripple_fade_to_alpha = NumericProperty(.8)
    ripple_rad_default = NumericProperty(10); ripple_scale = NumericProperty(2)


class CoverBehavior(EventDispatcher):
    reference_size = ListProperty([]); cover_size = ListProperty([0, 0]); cover_pos = ListProperty([0, 0])


class _BehaviorsLegacy: pass


# ===================================================================== kivy.uix.settings (small, working version)
class SettingItem(BoxLayout):
    title = StringProperty(""); desc = StringProperty(""); key = StringProperty(""); section = StringProperty("")
    value = Property(None); panel = ObjectProperty(None)
class SettingString(SettingItem): pass
class SettingNumeric(SettingString): pass
class SettingBoolean(SettingItem): pass
class SettingOptions(SettingItem): options = ListProperty([])
class SettingPath(SettingItem): pass
class SettingTitle(Label): pass
class SettingSpacer(Widget): pass
class SettingsPanel(BoxLayout):
    title = StringProperty("Settings"); config = ObjectProperty(None); settings = ObjectProperty(None); section = StringProperty("")
class InterfaceWithNoMenu(BoxLayout): pass
class InterfaceWithSidebar(BoxLayout): pass
class InterfaceWithSpinner(BoxLayout): pass
class InterfaceWithTabbedPanel(BoxLayout): pass
class InterfaceWithAccordion(BoxLayout): pass


class Settings(BoxLayout):
    __events__ = ("on_config_change", "on_close")
    interface_cls = ObjectProperty(InterfaceWithSidebar)
    def __init__(self, **kw):
        BoxLayout.__init__(self)
        self.orientation = "vertical"; self._apply_kw(kw)
    def on_config_change(self, config, section, key, value): pass
    def on_close(self, *a): pass
    def add_json_panel(self, title, config, filename=None, data=None):
        items = []
        try:
            if data is None:
                with open(resource_find(filename) or filename, encoding="utf-8") as f: data = f.read()
            items = json.loads(data) if isinstance(data, str) else list(data)
        except Exception as e: print("[kivy] settings json error:", e)
        panel = SettingsPanel(title=title, config=config, settings=self, orientation="vertical")
        panel.add_widget(Label(text=title, size_hint_y=None, height=36, bold=True))
        for it in items:
            if it.get("type") == "title": panel.add_widget(Label(text=it.get("title", ""), size_hint_y=None, height=30)); continue
            sec, key = it.get("section", ""), it.get("key", "")
            row = BoxLayout(size_hint_y=None, height=44)
            row.add_widget(Label(text=it.get("title", key), halign="left"))
            val = ""
            try: val = config.get(sec, key)
            except Exception: pass
            typ = it.get("type", "string")
            if typ == "bool":
                cb = K.CheckBox(active=str(val).lower() in ("1", "true", "yes"))
                cb.bind(active=lambda i, v, s=sec, k=key: (config.set(s, k, "1" if v else "0"), config.write(), self.dispatch("on_config_change", config, s, k, int(v))))
                row.add_widget(cb)
            else:
                ti = K.TextInput(text=str(val), multiline=False)
                ti.bind(text=lambda i, v, s=sec, k=key: (config.set(s, k, v), config.write(), self.dispatch("on_config_change", config, s, k, v)))
                row.add_widget(ti)
            panel.add_widget(row)
        self.add_widget(panel)
    def add_kivy_panel(self): pass
    def create_json_panel(self, title, config, filename=None, data=None): self.add_json_panel(title, config, filename, data)
class SettingsWithSidebar(Settings): pass
class SettingsWithSpinner(Settings): pass
class SettingsWithTabbedPanel(Settings): pass
class SettingsWithNoMenu(Settings): pass


def _open_settings(self, *a):
    if getattr(self, "_settings", None) is not None: return
    try:
        s = Settings()
        self.build_settings(s); self.__dict__["_settings"] = s
        pop = U.Popup(title="Settings", content=s, size_hint=[.9, .9])
        s.bind(on_close=lambda *x: pop.dismiss())
        pop.bind(on_dismiss=lambda *x: self.__dict__.__setitem__("_settings", None))
        pop.open()
    except Exception as e: K.runner.report_exc(e)


K.App.open_settings = _open_settings


# ===================================================================== module table
def _all_utils():
    base = dict(get_color_from_hex=K.get_color_from_hex, get_hex_from_color=K.get_hex_from_color, platform="android")
    try:
        import kivy_extra as X
        base.update(rgba=X.rgba, boundary=X.boundary, escape_markup=X.escape_markup, get_random_color=X.get_random_color,
                    strtotuple=X.strtotuple, interpolate=X.interpolate)
    except ImportError: pass
    base.update(QueryDict=QueryDict, deprecated=deprecated, reify=reify, is_color_transparent=is_color_transparent,
                intersection=intersection, difference=difference, SafeList=SafeList, platform_=None)
    base.pop("platform_")
    return base


def _kvlang_names():
    import kvlang
    return dict(Builder=K.Builder, ParserException=kvlang.KVError, Parser=object, BuilderException=kvlang.KVError)


def _clock_dict():
    try:
        W = type(Clock)
        for n, v in dict(frametime=1 / 60.0, frames=0, max_iteration=20, interupt_next_only=False).items(): _addattr(W, n, v)
        _addattr(W, "get_fps", lambda s: 60.0); _addattr(W, "get_rfps", lambda s: 60.0)
        _addattr(W, "schedule_once_free", lambda s, cb, timeout=0: s.schedule_once(cb, timeout))
        _addattr(W, "idle", lambda s: None); _addattr(W, "usleep", lambda s, t: time.sleep(t / 1e6))
        _addattr(W, "start_clock", lambda s: None); _addattr(W, "stop_clock", lambda s: None)
    except Exception: pass
    return dict(Clock=Clock, mainthread=K.mainthread, ClockEvent=K.ClockEvent, triggered=triggered, ClockBase=type(Clock),
                CyClockBase=type(Clock), ClockBaseBehavior=type(Clock), ClockBaseFreeInterruptAll=type(Clock))


def _build_modules():
    from kivy_ui import (ButtonBehavior, ToggleButtonBehavior, FocusBehavior, ScrollView)
    beh = dict(ButtonBehavior=ButtonBehavior, ToggleButtonBehavior=ToggleButtonBehavior, FocusBehavior=FocusBehavior,
               CompoundSelectionBehavior=CompoundSelectionBehavior, DragBehavior=DragBehavior, CoverBehavior=CoverBehavior,
               TouchRippleBehavior=U.TouchRippleBehavior, TouchRippleButtonBehavior=TouchRippleButtonBehavior,
               EmacsBehavior=EmacsBehavior, CodeNavigationBehavior=CodeNavigationBehavior)
    mods = {
        "kivy.resources": dict(resource_add_path=resource_add_path, resource_remove_path=resource_remove_path,
                               resource_find=resource_find, resource_paths=resource_paths),
        "kivy.base": dict(EventLoop=EventLoop, runTouchApp=runTouchApp, stopTouchApp=stopTouchApp,
                          ExceptionHandler=ExceptionHandler, ExceptionManager=ExceptionManager),
        "kivy.core.text": dict(Label=CoreLabel, LabelBase=CoreLabel, DEFAULT_FONT=DEFAULT_FONT, FONT_REGULAR=0, FONT_ITALIC=1,
                               FONT_BOLD=2, FONT_BOLDITALIC=3),
        "kivy.core.text.markup": dict(MarkupLabel=MarkupLabel),
        "kivy.core.image": dict(Image=CoreImage, ImageData=object, ImageLoader=object),
        "kivy.config": dict(Config=Config, ConfigParser=ConfigParser),
        "kivy.cache": dict(Cache=Cache),
        "kivy.weakmethod": dict(WeakMethod=WeakMethod),
        "kivy.compat": dict(PY2=False, string_types=(str,), text_type=str, unichr=chr, iterkeys=lambda d: iter(d.keys()),
                            itervalues=lambda d: iter(d.values()), iteritems=lambda d: iter(d.items()), xrange=range, clock=time.perf_counter),
        "kivy.parser": dict(parse_color=_parse_color, parse_bool=parse_bool, parse_int=parse_int, parse_float=parse_float,
                            parse_string=parse_string, parse_int2=parse_int2, parse_float4=parse_float4, parse_filename=parse_filename),
        "kivy.context": dict(Context=_Context, get_current_context=lambda: _Context(), register_context=lambda *a, **k: None),
        "kivy.modules": dict(Modules=_Modules, Modules_=_Modules()),
        "kivy.loader": dict(Loader=_Loader(), LoaderBase=_Loader, ProxyImage=CoreImage),
        "kivy.atlas": dict(Atlas=Atlas),
        "kivy.storage": dict(AbstractStore=AbstractStore),
        "kivy.storage.dictstore": dict(DictStore=DictStore),
        "kivy.effects": {},
        "kivy.effects.scroll": dict(ScrollEffect=ScrollEffect),
        "kivy.effects.dampedscroll": dict(DampedScrollEffect=DampedScrollEffect),
        "kivy.effects.opacityscroll": dict(OpacityScrollEffect=OpacityScrollEffect),
        "kivy.effects.kinetic": dict(KineticEffect=KineticEffect),
        "kivy.garden": {},
        "kivy.interactive": {},
        "kivy.utils": _all_utils(),
        "kivy.clock": _clock_dict(),
        "kivy.lang": _kvlang_names(),
        "kivy.core.window.keyboard": dict(Keyboard=Keyboard),
        "kivy.uix.stencilview": dict(StencilView=StencilView),
        "kivy.uix.treeview": dict(TreeView=TreeView, TreeViewNode=TreeViewNode, TreeViewLabel=TreeViewLabel, TreeViewException=TreeViewException),
        "kivy.uix.recyclegridlayout": dict(RecycleGridLayout=RecycleGridLayout),
        "kivy.uix.recycleview.views": dict(RecycleDataViewBehavior=RecycleDataViewBehavior),
        "kivy.uix.recycleview.layout": dict(LayoutSelectionBehavior=LayoutSelectionBehavior,
                                            RecycleLayoutManagerBehavior=RecycleLayoutManagerBehavior),
        "kivy.uix.recycleview.datamodel": dict(RecycleDataModel=RecycleDataModel, RecycleDataModelBehavior=RecycleDataModel),
        "kivy.uix.recycleview.recycleview": dict(RecycleView=U.RecycleView),
        "kivy.uix.recycleview": dict(RecycleView=U.RecycleView, RecycleDataModel=RecycleDataModel, RecycleDataAdapter=RecycleDataAdapter),
        "kivy.uix.rst": dict(RstDocument=RstDocument, RstVideoPlayer=RstVideoPlayer),
        "kivy.uix.vkeyboard": dict(VKeyboard=VKeyboard),
        "kivy.uix.effectwidget": dict(EffectWidget=EffectWidget, EffectBase=EffectBase, AdvancedEffectBase=AdvancedEffectBase,
                                      MonochromeEffect=MonochromeEffect, InvertEffect=InvertEffect, ScanlinesEffect=ScanlinesEffect,
                                      ChannelMixEffect=ChannelMixEffect, PixelateEffect=PixelateEffect,
                                      HorizontalBlurEffect=HorizontalBlurEffect, VerticalBlurEffect=VerticalBlurEffect, FXAAEffect=FXAAEffect),
        "kivy.uix.settings": dict(Settings=Settings, SettingsWithSidebar=SettingsWithSidebar, SettingsWithSpinner=SettingsWithSpinner,
                                  SettingsWithTabbedPanel=SettingsWithTabbedPanel, SettingsWithNoMenu=SettingsWithNoMenu,
                                  SettingItem=SettingItem, SettingString=SettingString, SettingNumeric=SettingNumeric,
                                  SettingBoolean=SettingBoolean, SettingOptions=SettingOptions, SettingPath=SettingPath,
                                  SettingTitle=SettingTitle, SettingSpacer=SettingSpacer, SettingsPanel=SettingsPanel,
                                  InterfaceWithNoMenu=InterfaceWithNoMenu, InterfaceWithSidebar=InterfaceWithSidebar,
                                  InterfaceWithSpinner=InterfaceWithSpinner, InterfaceWithTabbedPanel=InterfaceWithTabbedPanel,
                                  InterfaceWithAccordion=InterfaceWithAccordion),
        "kivy.uix.behaviors": beh,
        "kivy.uix.behaviors.button": dict(ButtonBehavior=ButtonBehavior),
        "kivy.uix.behaviors.togglebutton": dict(ToggleButtonBehavior=ToggleButtonBehavior),
        "kivy.uix.behaviors.focus": dict(FocusBehavior=FocusBehavior),
        "kivy.uix.behaviors.drag": dict(DragBehavior=DragBehavior),
        "kivy.uix.behaviors.compoundselection": dict(CompoundSelectionBehavior=CompoundSelectionBehavior),
        "kivy.uix.behaviors.cover": dict(CoverBehavior=CoverBehavior),
        "kivy.uix.behaviors.touchripple": dict(TouchRippleBehavior=U.TouchRippleBehavior, TouchRippleButtonBehavior=TouchRippleButtonBehavior),
        "kivy.uix.behaviors.emacs": dict(EmacsBehavior=EmacsBehavior),
        "kivy.uix.behaviors.codenavigation": dict(CodeNavigationBehavior=CodeNavigationBehavior),
        "kivy.uix.textinput.TextInput": {},
    }
    mods.pop("kivy.uix.textinput.TextInput")
    return mods


MODULES = _build_modules()

# a few modules must stay packages so "import a.b.c" keeps working
CORE_WINDOW = dict(Keyboard=Keyboard)
