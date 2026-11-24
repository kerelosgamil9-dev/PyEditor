"""More Kivy widgets for the emulation: ScrollView, AnchorLayout, StackLayout, RelativeLayout, ScreenManager,
Popup/ModalView/DropDown, Spinner, TabbedPanel, Carousel, Image, RecycleView, behaviors, transitions."""
import time
import tkshim as tk
import kivyshim as K
from kivyshim import (Widget, Layout, BoxLayout, FloatLayout, GridLayout, Label, Button, ToggleButton, TextInput,
                      EventDispatcher, Property, NumericProperty, StringProperty, BooleanProperty, ObjectProperty,
                      ListProperty, DictProperty, AliasProperty, _hex, _num, _pad4, _track, _place_args, _st, Clock, _CLEAR)


# ===================================================================== layouts
class RelativeLayout(FloatLayout): pass


class AnchorLayout(Layout):
    anchor_x = Property("center")
    anchor_y = Property("center")

    def _relayout(self):
        if self._w is None: return
        rx = {"left": 0, "center": .5, "right": 1}.get(str(self.anchor_x), .5)
        ry = {"top": 0, "center": .5, "bottom": 1}.get(str(self.anchor_y), .5)
        hx = {"left": "w", "center": "", "right": "e"}.get(str(self.anchor_x), "")
        hy = {"top": "n", "center": "", "bottom": "s"}.get(str(self.anchor_y), "")
        for c in self._kids:
            if c._w is None: continue
            a = {"relx": rx, "rely": ry, "anchor": (hy + hx) or "center"}
            if c.size_hint_x is not None: a["relwidth"] = float(c.size_hint_x)
            else: a["width"] = max(1, int(c.width))
            if c.size_hint_y is not None: a["relheight"] = float(c.size_hint_y)
            else: a["height"] = max(1, int(c.height))
            c._el.place(**a)


class StackLayout(Layout):
    orientation = Property("lr-tb")

    def _after_size(self):
        Widget._after_size(self)
        if self.__dict__.get("_lw") != self.width: self._relayout()

    def _relayout(self):
        if self._w is None: return
        self.__dict__["_lw"] = self.width
        kids = [c for c in self._kids if c._w is not None]
        pl, pt, pr, pb = _pad4(self.padding)
        sp = self.spacing
        spx, spy = (sp[0], sp[1]) if isinstance(sp, (list, tuple)) and len(sp) > 1 else ((sp[0] if isinstance(sp, (list, tuple)) and sp else sp) or 0,) * 2
        vert = str(self.orientation).startswith("tb")
        W, H = float(self.width or 0), float(self.height or 0)
        inner = (H if vert else W) - ((pt + pb) if vert else (pl + pr))
        pos = 0.0; line = 0.0; cross = 0.0; used_cross = 0.0
        for c in kids:
            cw = c.width if c.size_hint_x is None else (c.size_hint_x * (W - pl - pr))
            ch = c.height if c.size_hint_y is None else (c.size_hint_y * (H - pt - pb))
            main, sub = (ch, cw) if vert else (cw, ch)
            if pos > 0 and pos + main > inner + 0.5:
                cross += line + (spx if vert else spy); pos = 0.0; line = 0.0
            x = pl + (cross if vert else pos); y = pt + (pos if vert else cross)
            c._el.place(x=int(x), y=int(y), width=max(1, int(cw)), height=max(1, int(ch)), anchor="nw")
            pos += main + (spy if vert else spx); line = max(line, sub)
        total_cross = cross + line
        if vert: self.minimum_width, self.minimum_height = pl + pr + total_cross, 0
        else: self.minimum_width, self.minimum_height = 0, pt + pb + total_cross


class ScrollView(Widget):
    do_scroll_x = BooleanProperty(True)
    do_scroll_y = BooleanProperty(True)
    scroll_x = NumericProperty(0)
    scroll_y = NumericProperty(1)
    bar_width = NumericProperty(4)
    bar_color = ListProperty([.7, .7, .7, .9])
    scroll_type = ListProperty(["content"])
    effect_cls = ObjectProperty(None)
    scroll_distance = NumericProperty(20)
    scroll_timeout = NumericProperty(55)

    def _mode(self): return ("x" if self.do_scroll_x else "") + ("y" if self.do_scroll_y else "")
    def _make(self, master):
        return tk.Frame(master, bg=_CLEAR, bd=0, highlightthickness=0, pvscroll=self._mode())
    def _cfg(self): return {"pvscroll": self._mode()}

    def _relayout(self):
        if self._w is None: return
        for c in self._kids:
            if c._w is None: continue
            c._el.grid(row=0, column=0, sticky="nsew")
            self._w.rowconfigure(0, **_track(c.size_hint_y, c.height))
            self._w.columnconfigure(0, **_track(c.size_hint_x, c.width))

    def _prop_changed(self, name, value):
        if name in ("scroll_x", "scroll_y") and self._w is not None:
            tk._send("pvsc", self._w._id, value if name == "scroll_x" else None, value if name == "scroll_y" else None)
        else: Widget._prop_changed(self, name, value)

    def scroll_to(self, widget, padding=10, animate=True):
        if self._w is not None and getattr(widget, "_w", None) is not None: tk._send("pvsee", self._w._id, widget._w._id)

    def convert_distance_to_scroll(self, dx, dy): return (0, 0)


# ===================================================================== switching containers
class _OneAtATime(FloatLayout):
    """Container that keeps all children in Python but only realizes (draws) the current one."""
    def __init__(self, **kw):
        self.__dict__["_shown"] = None
        FloatLayout.__init__(self, **kw)

    def _current_item(self): return None

    def _realize_kids(self):
        it = self._current_item()
        self.__dict__["_shown"] = it
        if it is not None: it._realize(self._w)

    def _swap(self, new, on_enter_leave=True):
        old = self.__dict__.get("_shown")
        if old is new: return
        if self._w is None: self.__dict__["_shown"] = new; return
        if on_enter_leave:
            if old is not None: old.dispatch("on_pre_leave")
            if new is not None: new.dispatch("on_pre_enter")
        if old is not None: old._unrealize()
        self.__dict__["_shown"] = new
        if new is not None: new._realize(self._w)
        self._relayout()
        if on_enter_leave:
            if old is not None: old.dispatch("on_leave")
            if new is not None: new.dispatch("on_enter")

    def add_widget(self, w, index=0, **k):
        if w in self._kids: return
        w.parent = self; self._kids.append(w); self._item_added(w)

    def remove_widget(self, w):
        if w not in self._kids: return
        was = self.__dict__.get("_shown") is w
        if was: w._unrealize(); self.__dict__["_shown"] = None
        self._kids.remove(w); w.parent = None; self._item_removed(w)
        if was and self._w is not None: self._swap(self._current_item(), False)

    def _item_added(self, w): pass
    def _item_removed(self, w): pass


class Screen(FloatLayout):
    __events__ = ("on_pre_enter", "on_enter", "on_pre_leave", "on_leave")
    name = StringProperty("")
    manager = ObjectProperty(None)
    transition_progress = NumericProperty(0)
    transition_state = Property("out")
    def on_pre_enter(self, *a): pass
    def on_enter(self, *a): pass
    def on_pre_leave(self, *a): pass
    def on_leave(self, *a): pass


class TransitionBase(EventDispatcher):
    duration = NumericProperty(.4)
    direction = Property("left")
    def __init__(self, **kw): EventDispatcher.__init__(self, **kw)

class NoTransition(TransitionBase): pass
class SlideTransition(TransitionBase): pass
class SwapTransition(TransitionBase): pass
class FadeTransition(TransitionBase): pass
class WipeTransition(TransitionBase): pass
class FallOutTransition(TransitionBase): pass
class RiseInTransition(TransitionBase): pass
class CardTransition(TransitionBase): pass


class ScreenManagerException(Exception): pass


class ScreenManager(_OneAtATime):
    current = StringProperty("")
    transition = ObjectProperty(None)

    def __init__(self, **kw):
        _OneAtATime.__init__(self, **kw)
        if self.transition is None: self.transition = SlideTransition()

    @property
    def screens(self): return list(self._kids)
    @property
    def screen_names(self): return [s.name for s in self._kids]
    @property
    def current_screen(self): return self.get_screen(self.current) if self.current else None

    def get_screen(self, name):
        for s in self._kids:
            if s.name == name: return s
        raise ScreenManagerException("No Screen with name %r." % name)

    def has_screen(self, name): return any(s.name == name for s in self._kids)
    def _current_item(self):
        for s in self._kids:
            if s.name == self.current: return s
        return None

    def add_widget(self, w, index=0, **k):
        if not isinstance(w, Screen): raise ScreenManagerException("ScreenManager accepts only Screen widget.")
        if self.has_screen(w.name): raise ScreenManagerException("Name %r already exists." % w.name)
        w.manager = self
        _OneAtATime.add_widget(self, w)

    def _item_added(self, w):
        if not self.current: self.current = w.name
        elif self.current == w.name: self._swap(w)

    def remove_widget(self, w):
        _OneAtATime.remove_widget(self, w)
        if self.current == w.name: self.current = self._kids[0].name if self._kids else ""

    def switch_to(self, screen, **kw):
        if screen not in self._kids: self.add_widget(screen)
        self.current = screen.name

    def next(self):
        n = self.screen_names
        return n[(n.index(self.current) + 1) % len(n)] if n else ""
    def previous(self):
        n = self.screen_names
        return n[(n.index(self.current) - 1) % len(n)] if n else ""

    def _prop_changed(self, name, value):
        if name == "current":
            if self._w is not None: self._swap(self._current_item())
        else: _OneAtATime._prop_changed(self, name, value)


class Carousel(_OneAtATime):
    index = NumericProperty(0)
    loop = BooleanProperty(False)
    direction = Property("right")
    anim_move_duration = NumericProperty(.5)
    min_move = NumericProperty(.2)

    @property
    def slides(self): return list(self._kids)
    @property
    def current_slide(self):
        return self._kids[int(self.index)] if 0 <= int(self.index) < len(self._kids) else None
    @property
    def previous_slide(self):
        i = int(self.index) - 1
        return self._kids[i] if 0 <= i < len(self._kids) else None
    @property
    def next_slide(self):
        i = int(self.index) + 1
        return self._kids[i] if 0 <= i < len(self._kids) else None

    def _current_item(self): return self.current_slide
    def _hook_events(self):
        _OneAtATime._hook_events(self)
        w = self._w
        d = self.__dict__
        w.bind("<ButtonPress-1>", lambda e: d.__setitem__("_sx", e.x), add="+")
        w.bind("<ButtonRelease-1>", lambda e: self._swipe(e.x - d.get("_sx", e.x)), add="+")
    def _swipe(self, dx):
        if dx < -50: self.load_next()
        elif dx > 50: self.load_previous()
    def load_next(self, mode="next"):
        n = len(self._kids)
        if not n: return
        i = int(self.index) + 1
        if i >= n:
            if not self.loop: return
            i = 0
        self.index = i
    def load_previous(self):
        n = len(self._kids)
        if not n: return
        i = int(self.index) - 1
        if i < 0:
            if not self.loop: return
            i = n - 1
        self.index = i
    def load_slide(self, slide):
        if slide in self._kids: self.index = self._kids.index(slide)
    def _prop_changed(self, name, value):
        if name == "index":
            if self._w is not None: self._swap(self.current_slide, False)
        else: _OneAtATime._prop_changed(self, name, value)


# ===================================================================== modal windows
class ModalView(BoxLayout):
    __events__ = ("on_pre_open", "on_open", "on_pre_dismiss", "on_dismiss")
    auto_dismiss = BooleanProperty(True)
    background_color = ListProperty([0, 0, 0, .7])
    overlay_color = ListProperty([0, 0, 0, .6])
    attach_to = ObjectProperty(None)
    _panel_bg = "rgba(0,0,0,0)"

    def __init__(self, **kw):
        self.__dict__["_ov"] = None
        BoxLayout.__init__(self, orientation="vertical")
        self.size_hint_x = .7; self.size_hint_y = .7
        self._apply_kw(kw)

    def _make(self, master): return tk.Frame(master, bg=self._panel_bg, bd=0, highlightthickness=0)
    def _cfg(self): return {}
    @property
    def _is_open(self): return self.__dict__.get("_ov") is not None

    def open(self, *a, **k):
        if self._is_open: return
        root = tk._st["root"]
        if root is None: return
        self.dispatch("on_pre_open")
        o = self.overlay_color
        ov = tk.Frame(root, bg="rgba(%d,%d,%d,%.2f)" % (o[0] * 255, o[1] * 255, o[2] * 255, o[3] if len(o) > 3 else .6), bd=0)
        ov.place(relx=0, rely=0, relwidth=1, relheight=1)
        ov.bind("<Button-1>", self._bg_tap)
        self.__dict__["_ov"] = ov
        self.parent = None
        self._realize(ov)
        a = {"relx": .5, "rely": .5, "anchor": "center"}
        if self.size_hint_x is not None: a["relwidth"] = float(self.size_hint_x)
        else: a["width"] = max(1, int(self.width))
        if self.size_hint_y is not None: a["relheight"] = float(self.size_hint_y)
        else: a["height"] = max(1, int(self.height))
        self._el.place(**a)
        self.dispatch("on_open")

    def _bg_tap(self, e):
        if e.widget is self.__dict__.get("_ov") and self.auto_dismiss: self.dismiss()

    def dismiss(self, *a, **k):
        ov = self.__dict__.get("_ov")
        if ov is None: return
        self.dispatch("on_pre_dismiss")
        self._unrealize()
        try: ov.destroy()
        except Exception: pass
        self.__dict__["_ov"] = None
        self.dispatch("on_dismiss")

    def on_pre_open(self, *a): pass
    def on_open(self, *a): pass
    def on_pre_dismiss(self, *a): pass
    def on_dismiss(self, *a): pass


class Popup(ModalView):
    title = StringProperty("No title")
    title_size = NumericProperty(16)
    title_color = ListProperty([1, 1, 1, 1])
    separator_color = ListProperty([.2, .6, .9, 1])
    content = ObjectProperty(None)
    _panel_bg = "#262626"

    def __init__(self, **kw):
        self.__dict__["_tl"] = None
        ModalView.__init__(self)
        self.size_hint_x = .8; self.size_hint_y = .8
        self.__dict__["_tl"] = Label(text=self.title, size_hint_y=None, height=44, font_size=self.title_size, color=self.title_color)
        BoxLayout.add_widget(self, self._tl)
        self._apply_kw(kw)

    def add_widget(self, w, *a, **k):
        if w is self._tl or w is self.content: return BoxLayout.add_widget(self, w, *a, **k)
        self.content = w

    def _prop_changed(self, name, value):
        tl = self.__dict__.get("_tl")
        if name == "content" and tl is not None:
            old = [c for c in self._kids if c is not tl]
            for c in old: BoxLayout.remove_widget(self, c)
            if value is not None: BoxLayout.add_widget(self, value)
        elif name in ("title", "title_size", "title_color") and tl is not None:
            tl.text = self.title; tl.font_size = self.title_size; tl.color = self.title_color
        else: ModalView._prop_changed(self, name, value)


class DropDown(ModalView):
    __events__ = ModalView.__events__ + ("on_select",)
    max_height = NumericProperty(None)
    dismiss_on_select = BooleanProperty(True)
    container = ObjectProperty(None)

    def __init__(self, **kw):
        ModalView.__init__(self)
        self.size_hint_x = .7; self.size_hint_y = None; self.height = 120
        self._panel_bg = "#262626"
        self.__dict__["_box"] = BoxLayout(orientation="vertical", size_hint_y=None, height=0)
        self.__dict__["_sv"] = ScrollView(do_scroll_x=False)
        self._sv.add_widget(self._box)
        BoxLayout.add_widget(self, self._sv)
        self.container = self._box
        self._apply_kw(kw)

    def add_widget(self, w, *a, **k):
        self._box.add_widget(w)
        h = sum((c.height or 0) for c in self._box._kids)
        self._box.height = h
        self.height = min(h + 4, self.max_height or 420)

    def remove_widget(self, w): self._box.remove_widget(w)
    def clear_widgets(self, *a): self._box.clear_widgets(); self._box.height = 0
    def open(self, widget=None, *a, **k): ModalView.open(self)
    def select(self, data):
        self.dispatch("on_select", data)
        if self.dismiss_on_select: self.dismiss()
    def on_select(self, *a): pass


class SpinnerOption(Button): pass


class Spinner(Button):
    values = ListProperty([])
    text_autoupdate = BooleanProperty(False)
    is_open = BooleanProperty(False)
    option_cls = ObjectProperty(None)
    dropdown_cls = ObjectProperty(None)

    def _press(self):
        self.dispatch("on_press")
        self._open_list()
        self.dispatch("on_release")

    def _open_list(self):
        dd = DropDown()
        for v in self.values:
            b = SpinnerOption(text=str(v), size_hint_y=None, height=48)
            b.bind(on_release=lambda inst, val=v: dd.select(val))
            dd.add_widget(b)
        dd.bind(on_select=lambda inst, val: setattr(self, "text", str(val)),
                on_dismiss=lambda *a: setattr(self, "is_open", False))
        self.is_open = True
        dd.open(self)
        self.__dict__["_dd"] = dd

    def _on_dd(self): pass


# ===================================================================== tabs
class TabbedPanelItem(ToggleButton):
    content = ObjectProperty(None)
    def add_widget(self, w, *a, **k): self.content = w
    def remove_widget(self, w):
        if self.content is w: self.content = None


class TabbedPanelHeader(TabbedPanelItem): pass


class TabbedPanel(BoxLayout):
    do_default_tab = BooleanProperty(True)
    default_tab_text = StringProperty("Default tab")
    tab_pos = Property("top_left")
    tab_height = NumericProperty(48)
    tab_width = NumericProperty(100)
    current_tab = ObjectProperty(None)
    default_tab = ObjectProperty(None)

    def __init__(self, **kw):
        self.__dict__["_items"] = []
        BoxLayout.__init__(self, orientation="vertical")
        self.__dict__["_hdr"] = BoxLayout(size_hint_y=None, height=48)
        self.__dict__["_body"] = FloatLayout()
        BoxLayout.add_widget(self, self._hdr); BoxLayout.add_widget(self, self._body)
        self._apply_kw(kw)
        self._hdr.height = self.tab_height

    @property
    def tab_list(self): return list(self._items)

    def add_widget(self, w, *a, **k):
        if isinstance(w, TabbedPanelItem):
            self._items.append(w)
            w.size_hint_x = None; w.width = self.tab_width
            w.bind(on_release=lambda inst: self.switch_to(inst))
            self._hdr.add_widget(w)
            if self.current_tab is None: self.switch_to(w)
        elif w in (self._hdr, self._body): BoxLayout.add_widget(self, w, *a, **k)
        else:
            if self.default_tab is None and self.do_default_tab:
                t = TabbedPanelItem(text=self.default_tab_text); self.default_tab = t; self.add_widget(t)
            (self.default_tab or self.current_tab).content = w if (self.default_tab or self.current_tab) else None
            self.switch_to(self.current_tab) if self.current_tab else None

    def switch_to(self, tab, do_scroll=False):
        self._body.clear_widgets()
        for t in self._items: t.state = "down" if t is tab else "normal"
        self.current_tab = tab
        if tab is not None and tab.content is not None:
            if tab.content.parent is not None: tab.content.parent.remove_widget(tab.content)
            self._body.add_widget(tab.content)

    def clear_tabs(self):
        for t in list(self._items): self._hdr.remove_widget(t)
        del self._items[:]; self._body.clear_widgets(); self.current_tab = None


# ===================================================================== image
class Image(Widget):
    source = StringProperty("")
    color = ListProperty([1, 1, 1, 1])
    allow_stretch = BooleanProperty(False)
    keep_ratio = BooleanProperty(True)
    nocache = BooleanProperty(False)
    texture_size = AliasProperty(lambda s: [s.width, s.height], None)
    norm_image_size = AliasProperty(lambda s: [s.width, s.height], None)

    def _img(self):
        if not self.source: return None
        try: return tk.PhotoImage(file=self.source)
        except Exception: return None

    def _make(self, master):
        im = self._img()
        self.__dict__["_im"] = im
        kw = dict(bg=_CLEAR, bd=0)
        if im is not None: kw["image"] = im
        return tk.Label(master, **kw)

    def _prop_changed(self, name, value):
        if name == "source" and self._w is not None:
            im = self._img(); self.__dict__["_im"] = im
            self._w.config(image=im) if im is not None else self._w.config(image="")
        else: Widget._prop_changed(self, name, value)

    def reload(self): self._prop_changed("source", self.source)


class AsyncImage(Image): pass


# ===================================================================== recycle view (simple, no recycling)
class RecycleBoxLayout(BoxLayout):
    default_size = Property((None, 56))
    default_size_hint = Property((1, None))
    key_viewclass = StringProperty("viewclass")


class RecycleView(ScrollView):
    data = ListProperty([])
    viewclass = Property("Label")
    layout_manager = ObjectProperty(None)

    def add_widget(self, w, *a, **k):
        if isinstance(w, RecycleBoxLayout): self.layout_manager = w
        ScrollView.add_widget(self, w, *a, **k)
        if isinstance(w, RecycleBoxLayout): self.refresh_from_data()

    def _prop_changed(self, name, value):
        if name in ("data", "viewclass"): self.refresh_from_data()
        else: ScrollView._prop_changed(self, name, value)

    def refresh_from_data(self, *a, **k):
        lm = self.layout_manager
        if lm is None: return
        lm.clear_widgets()
        vc = self.viewclass
        for item in self.data:
            cls = K.Factory.get(vc) if isinstance(vc, str) else vc
            d = dict(item)
            if "viewclass" in d:
                v2 = d.pop("viewclass"); cls = K.Factory.get(v2) if isinstance(v2, str) else v2
            w = cls()
            dw, dh = lm.default_size
            hx, hy = lm.default_size_hint
            w.size_hint_x, w.size_hint_y = hx, hy
            if dw is not None: w.width = dw
            if dh is not None: w.height = dh
            for k2, v in d.items():
                try: setattr(w, k2, v)
                except Exception: pass
            lm.add_widget(w)
        lm.minimum_height = lm.minimum_height   # keep observers in sync


# ===================================================================== behaviors
class ButtonBehavior(EventDispatcher):
    __events__ = ("on_press", "on_release")
    state = Property("normal")
    always_release = BooleanProperty(False)
    min_state_time = NumericProperty(0)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos): return False
        self.state = "down"; self.dispatch("on_press")
        touch.ud["_btn"] = True
        return True

    def on_touch_up(self, touch):
        if not touch.ud.get("_btn"): return False
        touch.ud["_btn"] = False
        self.state = "normal"
        if self.collide_point(*touch.pos) or self.always_release: self.dispatch("on_release")
        return True

    def on_press(self, *a): pass
    def on_release(self, *a): pass
    def trigger_action(self, duration=0.1): self.dispatch("on_press"); self.dispatch("on_release")


class ToggleButtonBehavior(ButtonBehavior):
    group = Property(None)
    allow_no_selection = BooleanProperty(True)

    def on_touch_up(self, touch):
        if not touch.ud.get("_btn"): return False
        touch.ud["_btn"] = False
        self.state = "normal" if self.state == "down" else "down"
        self.dispatch("on_release")
        return True


class FocusBehavior(EventDispatcher):
    focus = BooleanProperty(False)
    focus_next = ObjectProperty(None)
    focus_previous = ObjectProperty(None)
    keyboard_mode = Property("auto")


class CompoundSelectionBehavior(EventDispatcher): pass
class DragBehavior(EventDispatcher): pass
class CoverBehavior(EventDispatcher): pass
class TouchRippleBehavior(EventDispatcher): pass
