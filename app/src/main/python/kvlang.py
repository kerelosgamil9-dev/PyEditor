"""KV language for the Kivy emulation: rules, ids, property bindings, event handlers, canvas blocks.

Supported: <Rule>:, <A@Base>:, <A,B>:, root widgets, children, id:, property expressions (auto-bound to
self/root/app/ids/other widgets), on_<event>: handlers (also multi-line), canvas / canvas.before / canvas.after,
#:import, #:set, #:include (ignored)."""
import re, os, sys, textwrap, importlib, ast
import kivyshim as K
import runner

RULES = []          # [(class_name, node, filename)]
_BY = {}            # class_name -> [node, ...]
_GLOBALS = {}       # names from #:import / #:set
LAST_ROOT = [None]  # root widget of the last load_string / load_file


class KVError(Exception): pass


class Node:
    __slots__ = ("cls", "props", "handlers", "children", "canvas", "line")
    def __init__(self, cls=None, line=0):
        self.cls = cls; self.props = []; self.handlers = []; self.children = []; self.canvas = {}; self.line = line


# ---------------------------------------------------------------- parsing
def _strip_comment(line):
    out = []; q = None; i = 0
    while i < len(line):
        c = line[i]
        if q:
            out.append(c)
            if c == "\\": out.append(line[i + 1:i + 2]); i += 1
            elif c == q: q = None
        elif c in "'\"": q = c; out.append(c)
        elif c == "#": break
        else: out.append(c)
        i += 1
    return "".join(out).rstrip()


def _tokenize(text):
    lines = []
    for n, raw in enumerate(text.replace("\t", "    ").splitlines(), 1):
        st = raw.strip()
        if st.startswith("#:"): lines.append((-1, st[2:].strip(), n)); continue
        if not st or st.startswith("#"): continue
        s = _strip_comment(raw)
        if not s.strip(): continue
        lines.append((len(s) - len(s.lstrip()), s.strip(), n))
    return lines


_KEY = re.compile(r"^([A-Za-z_][\w.]*)\s*:\s*(.*)$")


def _parse_body(lines, i, node, parent_ind):
    """Parse the lines indented deeper than parent_ind into node. Returns the next index."""
    if i >= len(lines) or lines[i][0] <= parent_ind or lines[i][0] < 0: return i
    base = lines[i][0]
    while i < len(lines):
        ind, txt, ln = lines[i]
        if ind < base or ind < 0: break
        if ind > base: raise KVError("line %d: unexpected indentation" % ln)
        m = _KEY.match(txt)
        if m: key, val = m.group(1), m.group(2)
        elif re.fullmatch(r"[A-Z][\w.]*", txt): key, val = txt, ""      # bare class name (PushMatrix / PopMatrix ...), like Kivy
        else: raise KVError("line %d: cannot parse %r" % (ln, txt))
        i += 1
        j = i
        while j < len(lines) and lines[j][0] > base: j += 1
        deeper = lines[i:j]
        if val == "":
            if key in ("canvas", "canvas.before", "canvas.after"):
                tmp = Node(); _parse_body(lines, i, tmp, base); node.canvas.setdefault(key, []).extend(tmp.children); i = j
            elif key[0].isupper():
                ch = Node(key, ln); i = _parse_body(lines, i, ch, base); node.children.append(ch)
            elif deeper:
                code = textwrap.dedent("\n".join(" " * (d[0] - base - 1) + d[1] for d in deeper))
                (node.handlers if key.startswith("on_") else node.props).append((key, code, ln)); i = j
        else:
            if deeper and not key[0].isupper():          # continuation lines of a handler / expression
                val = val + "\n" + textwrap.dedent("\n".join(" " * (d[0] - base - 1) + d[1] for d in deeper)); i = j
            (node.handlers if key.startswith("on_") else node.props).append((key, val, ln))
    return i


def _directive(txt):
    p = txt.split(None, 2)
    if not p: return
    if p[0] == "import" and len(p) >= 3:
        name, path = p[1], p[2].strip()
        try:
            mod, _, attr = path.rpartition(".")
            try: _GLOBALS[name] = getattr(importlib.import_module(mod), attr)
            except Exception: _GLOBALS[name] = importlib.import_module(path)
        except Exception as e: print("KV #:import failed:", path, e)
    elif p[0] == "include" and len(p) >= 2:
        try:
            import os
            path = p[-1].strip()
            try:
                import kivy_more
                path = kivy_more.resource_find(path) or path
            except Exception: pass
            if os.path.isfile(path): load_file(path)
            else: print("KV #:include: file not found:", p[-1])
        except Exception as e: print("KV #:include failed:", p[-1], e)
    elif p[0] == "set" and len(p) >= 3:
        try: _GLOBALS[p[1]] = eval(p[2], _base_globals())
        except Exception as e: print("KV #:set failed:", p[1], e)


def _split_rule_names(head):
    """'A,B@Base+Mix' -> [(name, [base,...] or None), ...]"""
    out = []
    for part in head.split(","):
        part = part.strip().lstrip("-")
        if "@" in part:
            n, b = part.split("@", 1); out.append((n.strip(), [x.strip() for x in b.split("+")]))
        elif part: out.append((part, None))
    return out


def load_string(text, filename=None):
    lines = _tokenize(text)
    roots = []; i = 0
    while i < len(lines):
        ind, txt, ln = lines[i]
        if ind == -1: _directive(txt); i += 1; continue
        if ind != 0: raise KVError("line %d: unexpected indentation" % ln)
        if txt.startswith("<"):
            m = re.match(r"^<([^>]+)>\s*:\s*$", txt)
            if not m: raise KVError("line %d: bad rule header %r" % (ln, txt))
            node = Node(None, ln); i = _parse_body(lines, i + 1, node, 0)
            for name, bases in _split_rule_names(m.group(1)):
                if bases:
                    cls = type(name, tuple(K.Factory.get(b) for b in bases), {})
                    K.Factory.register(name, cls)
                RULES.append((name, node, filename)); _BY.setdefault(name, []).append(node)
        else:
            m = _KEY.match(txt)
            if m and not m.group(2): rname = m.group(1)
            elif re.fullmatch(r"[A-Z][\w.]*", txt): rname = txt
            else: raise KVError("line %d: cannot parse %r" % (ln, txt))
            node = Node(rname, ln); i = _parse_body(lines, i + 1, node, 0); roots.append(node)
    last = None
    for r in roots: last = _build_root(r)
    LAST_ROOT[0] = last
    return last


def load_file(path, **kw):
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as f: txt = f.read()
    return load_string(txt, filename=path)


def unload_file(path):
    path = os.path.abspath(path)
    for r in [r for r in RULES if r[2] == path]:
        RULES.remove(r)
        if r[1] in _BY.get(r[0], []): _BY[r[0]].remove(r[1])


def reset():
    del RULES[:]; _BY.clear(); _GLOBALS.clear()


# ---------------------------------------------------------------- evaluation
def _base_globals():
    g = dict(dp=K.dp, sp=K.sp, mm=K.mm, cm=K.cm, inch=K.inch, pt=K.pt, Window=K.Window, Clock=K.Clock,
             Factory=K.Factory, platform="android")
    g.update(_GLOBALS)
    for n, c in K.Factory._classes.items():
        g.setdefault(n, c)
    return g


def _globals(selfobj, root):
    g = _base_globals()
    ids = getattr(root, "ids", None)
    if ids: g.update(ids)
    g["self"] = selfobj; g["root"] = root; g["app"] = K._st["app"]
    return g


_STR = re.compile(r"'[^'\\\n]*(?:\\.[^'\\\n]*)*'|\"[^\"\\\n]*(?:\\.[^\"\\\n]*)*\"")
_CHAIN = re.compile(r"(?<![\w.])([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)+)")


def _watch(obj, attrs, trigger):
    i = 0
    while i < len(attrs):
        a = attrs[i]
        if isinstance(obj, K.EventDispatcher) and isinstance(getattr(type(obj), a, None), K.Property):
            rest = attrs[i + 1:]; st = {}
            def rewire(*_, obj=obj, a=a, rest=rest, st=st):
                st["u"] = _watch(getattr(obj, a, None), rest, trigger) if rest else None
            def on_change(*_, rewire=rewire):
                rewire(); trigger()
            obj.bind(**{a: on_change}); rewire()
            return
        try: obj = getattr(obj, a)
        except Exception: return
        i += 1


def _ensure_prop(target, name):
    cls = type(target)
    if not hasattr(cls, name) and "." not in name:
        p = K.ObjectProperty(None); p.__set_name__(cls, name); setattr(cls, name, p)


def _assign(target, name, value):
    if "." in name:                                   # e.g. pos_hint.x is not supported; try attribute path
        head, _, tail = name.rpartition(".")
        o = target
        for part in head.split("."): o = getattr(o, part)
        setattr(o, tail, value)
    else:
        setattr(target, name, value)


def _err(what, ln):
    print("KV error (%s, line %s):" % (what, ln))
    runner.report_exc(sys.exc_info()[1])


def _set_prop(target, name, src, selfobj, root, ln):
    if name == "id": return
    _ensure_prop(target, name)
    try: code = compile(src.strip(), "<kv>", "eval")
    except SyntaxError: return _err(name, ln)
    def evaluate(*_):
        try:
            _assign(target, name, eval(code, _globals(selfobj, root)))
        except Exception: _err(name, ln)
    evaluate()
    clean = _STR.sub('""', src)
    g = _globals(selfobj, root)
    for first, rest in _CHAIN.findall(clean):
        if first in g: _watch(g[first], rest.lstrip(".").split("."), evaluate)


def _bind_handler(target, name, src, selfobj, root, ln):
    try: code = compile(textwrap.dedent(src).strip() + "\n", "<kv>", "exec")
    except SyntaxError: return _err(name, ln)
    def cb(*args):
        g = _globals(selfobj, root); g["args"] = args
        exec(code, g)
    attr = name[3:]
    if isinstance(getattr(type(target), attr, None), K.Property): target.bind(**{attr: cb})
    else: target.bind(**{name: cb})


# ---------------------------------------------------------------- building
def _create(cls_name):
    return K.Factory.get(cls_name)()


def _collect(widget, node, root, work):
    """Phase 1: create children, register ids."""
    work.append((widget, node))
    for ch in node.children:
        w = _create(ch.cls)
        for key, val, ln in ch.props:
            if key == "id": root.ids[val.strip()] = w
            else:                                   # constants first, so e.g. Screen.name is known when the child is added
                try: _assign(w, key, ast.literal_eval(val.strip()))
                except Exception: pass
        widget.add_widget(w)
        _collect(w, ch, root, work)


def _apply_canvas(widget, node, root):
    for key, instrs in node.canvas.items():
        grp = widget.canvas
        if key == "canvas.before": grp = grp.before
        elif key == "canvas.after": grp = grp.after
        for inode in instrs:
            ins = _create(inode.cls)
            for k, v, ln in inode.props: _set_prop(ins, k, v, widget, root, ln)
            grp.add(ins)


def _apply(widget, node, root):
    work = []
    _collect(widget, node, root, work)
    for w, n in work:
        for key, val, ln in n.props: _set_prop(w, key, val, w, root, ln)
        for key, val, ln in n.handlers: _bind_handler(w, key, val, w, root, ln)
        if n.canvas: _apply_canvas(w, n, root)


def apply_rules(widget):
    for cls in reversed(type(widget).__mro__):
        for node in list(_BY.get(cls.__name__, ())):
            _apply(widget, node, widget)


def _build_root(node):
    w = K.Factory.get(node.cls)()
    for key, val, ln in node.props:
        if key == "id": w.ids[val.strip()] = w
    _apply(w, node, w)
    return w
