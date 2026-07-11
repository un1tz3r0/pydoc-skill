#!/usr/bin/env python3
"""pydoc_tool.py — dump Python documentation as markdown, for the /pydoc skill.

Introspects the *system* Python interpreter that runs this script. Stdlib only;
no third-party dependencies, no virtualenv. The point is to document whatever is
actually installed for `python3` on this machine.

Three call forms (dispatched by looking for --list / --find, else a NAME):

  pydoc_tool.py NAME [-r|--recursive|--deep | --depth N | -dN] [--private]
      Dump the docstring / signature / annotations for a fully-qualified,
      importable name (module, class, function, method, or attribute), then
      list its immediate children. With a recursion flag, also dump docs for
      descendants up to the given depth, listing children at the boundary.

  pydoc_tool.py --list [TYPE-FILTERS] [--depth N] [--private] [ROOT]
      List packages / contents. With no ROOT and no filters, list every
      top-level package on sys.path (no imports). With a ROOT and/or filters,
      import and walk it, emitting each child's name + type (signatures for
      callables, annotations where supported), filtered by TYPE-FILTERS.

  pydoc_tool.py --find [TYPE-FILTERS] [--depth N] [--glob|--regex] [ROOT] QUERY
      Same traversal as --list, filtered to items whose short or qualified name
      matches QUERY (plain substring by default, or a glob / regex pattern).

TYPE-FILTERS (combine freely): --all --packages --modules --classes
--functions --methods --members. Default is every category.

Run with no arguments (or -h/--help) for a short usage message.
"""

from __future__ import annotations

import builtins
import contextlib
import fnmatch
import importlib
import inspect
import io
import os
import pkgutil
import pydoc
import re
import sys
import warnings
from typing import Any

# ---------------------------------------------------------------------------
# Configuration / constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_CHARS = 50_000  # output budget; overridable with --max-chars
INF = float("inf")

# Category order used when grouping listings.
CATEGORY_ORDER = ["package", "module", "class", "function", "method", "property", "member"]
CATEGORY_PLURAL = {
    "package": "Packages",
    "module": "Modules",
    "class": "Classes",
    "function": "Functions",
    "method": "Methods",
    "property": "Properties",
    "member": "Members",
}

# Map user-facing type-filter flags to the categories they select.
FILTER_TO_CATEGORIES = {
    "--packages": {"package"},
    "--modules": {"module", "package"},
    "--classes": {"class"},
    "--functions": {"function"},
    "--methods": {"method"},
    "--members": {"member", "property"},
    "--all": set(CATEGORY_ORDER),
}


# ---------------------------------------------------------------------------
# Output budget
# ---------------------------------------------------------------------------

class Emitter:
    """Collects markdown, enforcing a character budget with a clean cutoff."""

    def __init__(self, max_chars: int):
        self.max_chars = max_chars
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False

    def add(self, text: str) -> bool:
        """Append text. Returns False once the budget is exhausted."""
        if self.truncated:
            return False
        if self.size + len(text) > self.max_chars:
            self.truncated = True
            remaining = self.max_chars - self.size
            if remaining > 0:
                self.parts.append(text[:remaining])
                self.size += remaining
            self.parts.append(
                "\n\n> **… output truncated** (hit the ~{:,}-char budget). "
                "Narrow with a `ROOT`, `--depth N`, a type filter "
                "(`--classes`/`--functions`/…), or `--find QUERY`; "
                "raise it with `--max-chars N`.\n".format(self.max_chars)
            )
            return False
        self.parts.append(text)
        self.size += len(text)
        return True

    def render(self) -> str:
        return "".join(self.parts)


# ---------------------------------------------------------------------------
# Resolution: fully-qualified name -> object
# ---------------------------------------------------------------------------

def quiet_import(modname: str) -> Any:
    """Import a module, suppressing warnings and any import-time stdout/stderr.

    Keeps stray prints/warnings emitted while a third-party package is imported
    out of the markdown we write to stdout.
    """
    with warnings.catch_warnings(), \
            contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        return importlib.import_module(modname)


def resolve(name: str) -> Any:
    """Resolve a dotted name to an object.

    Import the longest importable dotted prefix, then getattr the remainder.
    Falls back to builtins and, finally, pydoc.locate. Raises LookupError.
    """
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        modname = ".".join(parts[:i])
        try:
            mod = quiet_import(modname)
        except Exception:
            continue
        obj = mod
        ok = True
        for attr in parts[i:]:
            try:
                obj = getattr(obj, attr)
            except AttributeError:
                ok = False
                break
        if ok:
            return obj

    # builtins (list, str.join, etc.)
    if hasattr(builtins, parts[0]):
        obj = getattr(builtins, parts[0])
        ok = True
        for attr in parts[1:]:
            try:
                obj = getattr(obj, attr)
            except AttributeError:
                ok = False
                break
        if ok:
            return obj

    located = pydoc.locate(name)
    if located is not None:
        return located

    raise LookupError(name)


# ---------------------------------------------------------------------------
# Classification / formatting
# ---------------------------------------------------------------------------

def classify(obj: Any, *, in_class: bool = False) -> str:
    """Return a category string for an object."""
    if inspect.ismodule(obj):
        return "package" if hasattr(obj, "__path__") else "module"
    if inspect.isclass(obj):
        return "class"
    if isinstance(obj, (staticmethod, classmethod)):
        return "method"
    if isinstance(obj, property):
        return "property"
    if inspect.isroutine(obj):  # functions, builtins, methods, descriptors
        return "method" if in_class else "function"
    if inspect.isdatadescriptor(obj):
        return "property"
    return "member"


def top_package(name: str) -> str:
    return name.split(".", 1)[0]


def safe_getdoc(obj: Any) -> str | None:
    """inspect.getdoc that never raises (weird __doc__ descriptors exist)."""
    try:
        return inspect.getdoc(obj)
    except Exception:
        return None


def get_signature(obj: Any) -> str | None:
    """Best-effort signature string, or None if unavailable.

    On 3.14+, ``inspect.signature`` evaluates annotations eagerly and can raise
    almost anything (e.g. ``NameError`` for unresolvable forward refs), so we
    catch broadly and fall back to a docstring-derived signature.
    """
    try:
        return str(inspect.signature(obj))
    except Exception:
        pass
    doc = safe_getdoc(obj)
    if doc:
        first = doc.strip().splitlines()[0].strip()
        # Accept "name(...)" or "(...)" shaped first lines as a signature hint.
        m = re.search(r"\(.*\)", first)
        if m and (first.startswith(getattr(obj, "__name__", "\0")) or first.startswith("(")):
            return first[m.start():]
    return None


def _fmt_annotation(value: Any) -> str:
    if isinstance(value, type):
        return value.__qualname__
    if isinstance(value, str):
        return value  # PEP 563 / forward-ref string
    return str(value).replace("typing.", "")


def get_annotations(obj: Any) -> dict[str, Any]:
    """Annotations dict, robust to 3.14 lazy-annotation evaluation failures.

    Both ``inspect.get_annotations`` and even ``getattr(obj, '__annotations__')``
    can raise (the ``__annotate__`` descriptor is executed on access), so guard
    each attempt independently.
    """
    for attempt in (
        lambda: inspect.get_annotations(obj),
        lambda: dict(getattr(obj, "__annotations__", {}) or {}),
    ):
        try:
            return attempt() or {}
        except Exception:
            continue
    return {}


def class_header(cls: type) -> str:
    bases = [b.__name__ for b in getattr(cls, "__bases__", ()) if b is not object]
    base_str = f"({', '.join(bases)})" if bases else ""
    return f"class {cls.__name__}{base_str}"


# ---------------------------------------------------------------------------
# Children enumeration
# ---------------------------------------------------------------------------

class Child:
    __slots__ = ("name", "qualname", "obj", "category", "lazy_modname")

    def __init__(self, name, qualname, obj, category, lazy_modname=None):
        self.name = name
        self.qualname = qualname
        self.obj = obj
        self.category = category
        self.lazy_modname = lazy_modname  # set for not-yet-imported submodules

    def resolve_obj(self) -> Any:
        if self.obj is None and self.lazy_modname:
            self.obj = quiet_import(self.lazy_modname)
        return self.obj


def _public(name: str, include_private: bool) -> bool:
    if include_private:
        return True
    return not name.startswith("_")


def get_children(obj: Any, qualname: str, *, include_private: bool) -> list[Child]:
    """Enumerate the children of a module or class."""
    children: list[Child] = []
    seen: set[str] = set()

    if inspect.ismodule(obj):
        for name in dir(obj):
            if not _public(name, include_private):
                continue
            try:
                child = getattr(obj, name)
            except Exception:
                continue
            seen.add(name)
            children.append(
                Child(name, f"{qualname}.{name}", child, classify(child, in_class=False))
            )
        # Submodules of a package that aren't already attributes (not imported yet).
        if hasattr(obj, "__path__"):
            try:
                for info in pkgutil.iter_modules(obj.__path__):
                    sub = info.name
                    if sub in seen or not _public(sub, include_private):
                        continue
                    seen.add(sub)
                    cat = "package" if info.ispkg else "module"
                    children.append(
                        Child(sub, f"{qualname}.{sub}", None, cat,
                              lazy_modname=f"{obj.__name__}.{sub}")
                    )
            except Exception:
                pass

    elif inspect.isclass(obj):
        for name, raw in vars(obj).items():  # own members only (skip inherited noise)
            if not _public(name, include_private):
                continue
            try:
                child = getattr(obj, name)
            except Exception:
                child = raw
            children.append(
                Child(name, f"{qualname}.{name}", child, classify(raw, in_class=True))
            )

    children.sort(key=lambda c: (CATEGORY_ORDER.index(c.category)
                                 if c.category in CATEGORY_ORDER else 99, c.name))
    return children


def _child_detail(child: Child) -> str:
    """Trailing detail for a listing line: signature or annotation."""
    obj = child.obj
    if obj is None:
        return ""
    if child.category in ("function", "method"):
        sig = get_signature(obj)
        return f"`{sig}`" if sig else ""
    if child.category == "property":
        return ""
    if child.category in ("member",) and not callable(obj):
        t = type(obj).__name__
        return f"— *{t}*"
    return ""


# ---------------------------------------------------------------------------
# Rendering: single object documentation
# ---------------------------------------------------------------------------

def render_object(qualname: str, obj: Any, *, heading_level: int = 2) -> str:
    h = "#" * heading_level
    category = classify(obj)
    out: list[str] = []

    out.append(f"{h} {category} `{qualname}`\n")

    # Signature / class header block.
    if inspect.isclass(obj):
        header = class_header(obj)
        sig = get_signature(obj)
        code = header + (sig if sig else "")
        out.append(f"```python\n{code}\n```\n")
    elif callable(obj):
        sig = get_signature(obj)
        short = qualname.rsplit(".", 1)[-1]
        if sig:
            out.append(f"```python\n{short}{sig}\n```\n")

    # Annotations (dataclass fields, annotated module/class vars, etc.).
    ann = get_annotations(obj)
    if ann:
        lines = [f"- `{k}: {_fmt_annotation(v)}`" for k, v in ann.items()]
        out.append("**Annotations:**\n" + "\n".join(lines) + "\n")

    # Docstring.
    doc = safe_getdoc(obj)
    if doc:
        out.append(doc.strip() + "\n")
    else:
        out.append("*(no docstring)*\n")

    return "\n".join(out) + "\n"


def render_children_list(children: list[Child], *, categories: set[str],
                         heading: str = "Contents", heading_level: int = 3) -> str:
    kept = [c for c in children if c.category in categories]
    if not kept:
        return ""
    h = "#" * heading_level
    out = [f"{h} {heading}\n"]
    for cat in CATEGORY_ORDER:
        group = [c for c in kept if c.category == cat]
        if not group:
            continue
        out.append(f"**{CATEGORY_PLURAL[cat]}**\n")
        for c in group:
            detail = _child_detail(c)
            line = f"- `{c.qualname}`"
            if detail:
                line += f" {detail}"
            out.append(line)
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Mode: dump docs for a NAME (with optional recursion)
# ---------------------------------------------------------------------------

def dump_docs(name: str, *, depth: float, include_private: bool, emit: Emitter) -> None:
    try:
        obj = resolve(name)
    except LookupError:
        emit.add(f"# `{name}` not found\n\nCould not import or resolve `{name}`. "
                 "Check the spelling and that the package is installed for "
                 f"`{sys.executable}`.\n\nTry `--list` to see top-level packages, "
                 f"or `--find {name.rsplit('.', 1)[-1]}` to search.\n")
        return

    root_pkg = top_package(name)
    visited: set[int] = set()

    def walk(qualname: str, o: Any, remaining: float, level: int) -> None:
        if not emit.add(render_object(qualname, o, heading_level=min(level + 2, 6))):
            return
        if id(o) in visited:
            return
        visited.add(id(o))

        is_namespace = inspect.ismodule(o) or inspect.isclass(o)
        if not is_namespace:
            return

        children = get_children(o, qualname, include_private=include_private)

        if remaining <= 0:
            # At the boundary: just list children.
            emit.add(render_children_list(children, categories=set(CATEGORY_ORDER),
                                          heading_level=min(level + 3, 6)))
            return

        # Recurse into namespace children that belong to this subtree.
        for c in children:
            child_obj = c.obj
            recurse = c.category in ("module", "package", "class")
            if recurse and child_obj is None and c.lazy_modname:
                try:
                    child_obj = c.resolve_obj()
                except Exception:
                    recurse = False
            if recurse:
                mod = getattr(child_obj, "__module__", None) or getattr(child_obj, "__name__", "")
                if not (mod == root_pkg or mod.startswith(root_pkg + ".")
                        or (c.lazy_modname and c.lazy_modname.startswith(root_pkg))):
                    recurse = False
            if recurse:
                walk(c.qualname, child_obj, remaining - 1, level + 1)
            else:
                emit.add(render_object(c.qualname, c.obj, heading_level=min(level + 3, 6))
                         if c.obj is not None else f"- `{c.qualname}` — {c.category}\n")
            if emit.truncated:
                return

    walk(name, obj, depth, 0)


# ---------------------------------------------------------------------------
# Mode: --list / --find traversal
# ---------------------------------------------------------------------------

def iter_toplevel(include_private: bool) -> list[tuple[str, str]]:
    """Return sorted (name, category) for every top-level importable name."""
    found: dict[str, str] = {}
    for name in sys.builtin_module_names:
        if _public(name, include_private):
            found[name] = "module"
    # Exclude this script's own directory so pydoc_tool doesn't self-report.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [p for p in sys.path if p and os.path.abspath(p) != script_dir]
    for info in pkgutil.iter_modules(paths):
        if info.name == "pydoc_tool":
            continue
        if _public(info.name, include_private):
            found.setdefault(info.name, "package" if info.ispkg else "module")
    return sorted(found.items())


def traverse(root_obj: Any, root_name: str, *, max_depth: float, categories: set[str],
             include_private: bool, emit: Emitter) -> None:
    """Walk a package/module, emitting matching children as terse listing lines."""
    root_pkg = top_package(root_name)
    visited: set[int] = set()
    rows: list[Child] = []

    def walk(qualname: str, o: Any, remaining: float, level: int) -> None:
        if id(o) in visited or remaining <= 0:
            return
        visited.add(id(o))
        children = get_children(o, qualname, include_private=include_private)
        for c in children:
            rows.append(c)
            recurse = c.category in ("module", "package", "class") and remaining - 1 > 0
            child_obj = c.obj
            if recurse and child_obj is None and c.lazy_modname:
                try:
                    child_obj = c.resolve_obj()
                except Exception:
                    recurse = False
            if recurse and child_obj is not None:
                mod = getattr(child_obj, "__module__", None) or getattr(child_obj, "__name__", "")
                if not (mod == root_pkg or mod.startswith(root_pkg + ".")
                        or (c.lazy_modname and c.lazy_modname.startswith(root_pkg))):
                    recurse = False
                if recurse:
                    walk(c.qualname, child_obj, remaining - 1, level + 1)

    walk(root_name, root_obj, max_depth, 0)

    # Deduplicate by qualname, keep the matching categories.
    seen: set[str] = set()
    kept: list[Child] = []
    for c in rows:
        if c.category in categories and c.qualname not in seen:
            seen.add(c.qualname)
            kept.append(c)
    kept.sort(key=lambda c: c.qualname)

    emit.add(f"# Contents of `{root_name}`\n\n"
             f"{len(kept)} item(s) matching "
             f"[{', '.join(sorted(categories))}], depth {max_depth}.\n")
    for cat in CATEGORY_ORDER:
        group = [c for c in kept if c.category == cat]
        if not group:
            continue
        emit.add(f"\n### {CATEGORY_PLURAL[cat]}\n")
        for c in group:
            detail = _child_detail(c)
            line = f"- `{c.qualname}`" + (f" {detail}" if detail else "")
            if not emit.add(line + "\n"):
                return


def run_list(filters: set[str], root: str | None, depth: float,
             include_private: bool, emit: Emitter) -> None:
    categories = set()
    for f in filters:
        categories |= FILTER_TO_CATEGORIES[f]
    if not categories:
        categories = set(CATEGORY_ORDER)

    if root is None and not filters:
        # Fast path: top-level package index, no imports.
        items = iter_toplevel(include_private)
        emit.add(f"# Top-level packages ({len(items)}) on this Python\n\n"
                 f"`{sys.executable}` — {sys.version.split()[0]}\n\n"
                 "Drill in with `/pydoc <name>` or `--list <name>`.\n")
        pkgs = [n for n, c in items if c == "package"]
        mods = [n for n, c in items if c == "module"]
        emit.add(f"\n### Packages ({len(pkgs)})\n")
        emit.add(", ".join(f"`{n}`" for n in pkgs) + "\n")
        emit.add(f"\n### Modules ({len(mods)})\n")
        emit.add(", ".join(f"`{n}`" for n in mods) + "\n")
        return

    if root is None:
        # Deep traverse across all top-level packages (opt-in; can be slow).
        emit.add("# Contents of all top-level packages\n\n"
                 "> Importing every top-level package to introspect it — this can be "
                 "slow and may emit import warnings. Give a ROOT to scope it.\n\n")
        for name, _cat in iter_toplevel(include_private):
            try:
                obj = quiet_import(name)
            except Exception:
                continue
            traverse(obj, name, max_depth=depth, categories=categories,
                     include_private=include_private, emit=emit)
            if emit.truncated:
                return
        return

    try:
        obj = resolve(root)
    except LookupError:
        emit.add(f"# `{root}` not found\n\nCould not import `{root}`.\n")
        return
    traverse(obj, root, max_depth=depth, categories=categories,
             include_private=include_private, emit=emit)


def run_find(filters: set[str], root: str | None, query: str, depth: float,
             matcher_kind: str, include_private: bool, emit: Emitter) -> None:
    categories = set()
    for f in filters:
        categories |= FILTER_TO_CATEGORIES[f]
    if not categories:
        categories = set(CATEGORY_ORDER)

    # Build a predicate over (short name, qualname).
    if matcher_kind == "regex":
        rx = re.compile(query)
        pred = lambda short, qual: bool(rx.search(short) or rx.search(qual))
    elif matcher_kind == "glob":
        pred = lambda short, qual: (fnmatch.fnmatch(short, query)
                                    or fnmatch.fnmatch(qual, query))
    else:
        q = query.lower()
        pred = lambda short, qual: q in short.lower() or q in qual.lower()

    # Collect candidates (reuse traverse into a buffer, then filter).
    buffer = Emitter(max_chars=10 ** 12)
    collected: list[Child] = []

    def collect(root_obj, root_name):
        root_pkg = top_package(root_name)
        visited: set[int] = set()

        def walk(qualname, o, remaining):
            if id(o) in visited or remaining <= 0:
                return
            visited.add(id(o))
            for c in get_children(o, qualname, include_private=include_private):
                collected.append(c)
                recurse = c.category in ("module", "package", "class") and remaining - 1 > 0
                child_obj = c.obj
                if recurse and child_obj is None and c.lazy_modname:
                    try:
                        child_obj = c.resolve_obj()
                    except Exception:
                        recurse = False
                if recurse and child_obj is not None:
                    mod = getattr(child_obj, "__module__", None) or getattr(child_obj, "__name__", "")
                    if not (mod == root_pkg or mod.startswith(root_pkg + ".")
                            or (c.lazy_modname and c.lazy_modname.startswith(root_pkg))):
                        recurse = False
                    if recurse:
                        walk(c.qualname, child_obj, remaining - 1)

        walk(root_name, root_obj, depth if depth > 0 else 1)

    if root is not None:
        try:
            obj = resolve(root)
        except LookupError:
            emit.add(f"# `{root}` not found\n")
            return
        collect(obj, root)
    else:
        # No root: search top-level names, and (if depth>1) their contents.
        for name, cat in iter_toplevel(include_private):
            collected.append(Child(name, name, None, cat, lazy_modname=name))
            if depth > 1:
                try:
                    obj = quiet_import(name)
                except Exception:
                    continue
                collect(obj, name)

    # Filter and render.
    seen: set[str] = set()
    kept: list[Child] = []
    for c in collected:
        if c.category in categories and c.qualname not in seen and pred(c.name, c.qualname):
            seen.add(c.qualname)
            kept.append(c)
    kept.sort(key=lambda c: c.qualname)

    scope = f"`{root}`" if root else "all top-level packages"
    emit.add(f"# `--find {query}` in {scope}\n\n{len(kept)} match(es) "
             f"[{matcher_kind}], categories [{', '.join(sorted(categories))}], "
             f"depth {depth}.\n")
    for cat in CATEGORY_ORDER:
        group = [c for c in kept if c.category == cat]
        if not group:
            continue
        emit.add(f"\n### {CATEGORY_PLURAL[cat]}\n")
        for c in group:
            detail = _child_detail(c)
            line = f"- `{c.qualname}`" + (f" {detail}" if detail else "")
            if not emit.add(line + "\n"):
                return


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

USAGE = """\
# /pydoc — Python documentation lookup

Documents the **system** Python (`{exe}`, {ver}). Stdlib only.

## Dump docs for a name
    /pydoc os.path.join
    /pydoc collections.OrderedDict
    /pydoc json --depth 1        # also document one level of children
    /pydoc numpy -r              # recurse (docstrings for the whole subtree)

Shows the signature, annotations, and docstring, then lists immediate children.
Recursion flags: `-r` / `--recursive` / `--deep` (unbounded), `--depth N` / `-dN`.

## List packages / contents
    /pydoc --list                        # every top-level package (no imports)
    /pydoc --list numpy                  # public contents of numpy
    /pydoc --list --classes numpy        # only classes
    /pydoc --list --functions --depth 2 json

Type filters: `--all --packages --modules --classes --functions --methods --members`.

## Search
    /pydoc --find dumps json             # substring match under json
    /pydoc --find --glob 'to_*' pandas   # glob
    /pydoc --find --regex '^Async' asyncio

## Common flags
    --depth N / -dN   traversal / recursion depth (list default 1, doc default 0)
    -r --deep         unbounded recursion (doc mode)
    --private / -a    include names starting with '_'
    --glob --regex    QUERY is a glob / regex (default: plain substring)
    --max-chars N     output budget (default {budget:,})
"""


def print_usage(emit: Emitter) -> None:
    emit.add(USAGE.format(exe=sys.executable, ver=sys.version.split()[0],
                          budget=DEFAULT_MAX_CHARS))


# ---------------------------------------------------------------------------
# Argument parsing (hand-rolled for the mixed grammar) + dispatch
# ---------------------------------------------------------------------------

class Args:
    def __init__(self):
        self.mode = "doc"          # doc | list | find | usage
        self.filters: set[str] = set()
        self.depth: float | None = None
        self.recursive = False
        self.private = False
        self.matcher = "substring"  # substring | glob | regex
        self.max_chars = DEFAULT_MAX_CHARS
        self.positionals: list[str] = []


def parse_args(argv: list[str]) -> Args:
    a = Args()
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-h", "--help"):
            a.mode = "usage"
        elif tok == "--list":
            a.mode = "list"
        elif tok == "--find":
            a.mode = "find"
        elif tok in FILTER_TO_CATEGORIES:
            a.filters.add(tok)
        elif tok in ("-r", "--recursive", "--deep"):
            a.recursive = True
        elif tok in ("--private", "-a", "--all-members"):
            a.private = True
        elif tok == "--glob":
            a.matcher = "glob"
        elif tok == "--regex":
            a.matcher = "regex"
        elif tok == "--depth":
            i += 1
            a.depth = _parse_int(argv[i] if i < len(argv) else "", tok)
        elif tok.startswith("--depth="):
            a.depth = _parse_int(tok.split("=", 1)[1], tok)
        elif re.fullmatch(r"-d\d+", tok):
            a.depth = int(tok[2:])
        elif tok == "-d":
            i += 1
            a.depth = _parse_int(argv[i] if i < len(argv) else "", tok)
        elif tok == "--max-chars":
            i += 1
            a.max_chars = _parse_int(argv[i] if i < len(argv) else "", tok)
        elif tok.startswith("-") and tok != "-" and not _looks_like_name(tok):
            sys.stderr.write(f"pydoc_tool: unknown option {tok!r}\n")
        else:
            a.positionals.append(tok)
        i += 1
    return a


def _resolvable(name: str) -> bool:
    """True if `name` imports/resolves — used to auto-correct reversed --find args."""
    try:
        resolve(name)
        return True
    except Exception:
        return False


def _parse_int(val: str, flag: str) -> int:
    try:
        return int(val)
    except ValueError:
        sys.stderr.write(f"pydoc_tool: {flag} expects an integer, got {val!r}\n")
        raise SystemExit(2)


def _looks_like_name(tok: str) -> bool:
    # A negative number or something; treat leading-dash tokens as options otherwise.
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        emit = Emitter(DEFAULT_MAX_CHARS)
        print_usage(emit)
        sys.stdout.write(emit.render())
        return 0

    a = parse_args(argv)
    emit = Emitter(a.max_chars)

    if a.mode == "usage":
        print_usage(emit)

    elif a.mode == "list":
        root = a.positionals[0] if a.positionals else None
        depth = a.depth if a.depth is not None else 1
        depth = INF if a.recursive else depth
        run_list(a.filters, root, depth, a.private, emit)

    elif a.mode == "find":
        if not a.positionals:
            emit.add("# --find needs a QUERY\n\nUsage: "
                     "`--find [filters] [--glob|--regex] [ROOT] QUERY`\n"
                     "ROOT (a package to scope the search) comes *before* QUERY.\n")
        else:
            if len(a.positionals) == 1:
                root, query = None, a.positionals[0]
            else:
                root, query = a.positionals[0], a.positionals[-1]
                # Grammar is `[ROOT] QUERY`. If the caller reversed it — ROOT
                # doesn't import but QUERY does — swap so intent still works.
                if not _resolvable(root) and _resolvable(query):
                    root, query = query, root
            depth = a.depth if a.depth is not None else 1
            depth = INF if a.recursive else depth
            run_find(a.filters, root, query, depth, a.matcher, a.private, emit)

    else:  # doc
        if not a.positionals:
            print_usage(emit)
        else:
            name = a.positionals[0]
            depth = a.depth if a.depth is not None else 0
            depth = INF if a.recursive else depth
            dump_docs(name, depth=depth, include_private=a.private, emit=emit)

    sys.stdout.write(emit.render())
    if emit.render() and not emit.render().endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
