---
name: pydoc
description: >-
  Look up Python documentation for any importable object in the system
  Python — signatures, type annotations, and docstrings, rendered as markdown.
  Resolves a fully-qualified name (module, package, class, function, method, or
  attribute) and dumps its docs; lists the contents of packages; and searches
  installed packages for symbols by substring, glob, or regex. Use when you need
  the actual API/signature/docstring of something installed (rather than
  guessing), to explore what a package exposes, or to find where a symbol lives.
  Invoke as `/pydoc <fully.qualified.name>`, `/pydoc --list [ROOT]`, or
  `/pydoc --find [ROOT] QUERY`.
when_to_use: >-
  Triggers: "what's the signature of X", "show the python docs for X", "what does
  module/package X contain", "how do I use function/class X of package Y", "find the function/class named Y", checking a real
  API before writing Python against it, exploring an unfamiliar installed
  library. Prefer this over recalling an API from memory when the package is
  installed locally.
compatibility: Requires python3
allowed-tools: Bash(python3:*)
disable-model-invocation: false
user-invocable: true

---

# /pydoc — Python documentation lookup

The block below is generated live by introspecting the **system** Python
interpreter (`python3`) for whatever name, listing, or search was requested. It
is the real, currently-installed API — signatures, annotations, and docstrings —
not recalled knowledge. Read it as authoritative for this machine's environment.

!`python3 "${CLAUDE_SKILL_DIR}/scripts/pydoc_tool.py" $ARGUMENTS`

---

**Following up.** Every listed item shows its fully-qualified name. To go deeper,
run the tool again directly (it is safe, read-only, and stdlib-only):

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/pydoc_tool.py" <name-or-flags>
```

- `<fully.qualified.name>` — docstring + signature + annotations, then its children.
  Add `--depth N` / `-dN` to document N levels of children, or `-r` for the whole subtree.
- `--list [ROOT]` — contents of ROOT (or every top-level package if omitted).
  Filter with `--packages --modules --classes --functions --methods --members`.
- `--find [ROOT] QUERY` — search (ROOT comes before QUERY); `--glob` / `--regex`
  switch QUERY from plain substring to a pattern.
- `--private` includes `_`-prefixed names; `--max-chars N` raises the output budget.

If a name isn't found, try `--list` for the top-level package index or
`--find QUERY` to locate the symbol first.
