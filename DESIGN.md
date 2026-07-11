# DESIGN — `/pydoc` skill

## Purpose & intent

A Claude Code skill, `/pydoc`, that pulls Python documentation from the
**system** Python interpreter and dumps it into the conversation as markdown
when invoked. It turns "what's the real signature / docstring / API of this
installed thing?" into one command, grounded in what is actually installed for
`python3` on this machine rather than recalled from training.

Original request (2026-07-10), faithfully summarized:

- Use the **system-wide** Python distro (not a project venv).
- Given a **fully-qualified importable name** (module / function / class / method /
  member), dump its docs as markdown into context.
- No argument → a brief usage message.
- `--list --packages` (or bare `--list`) → every top-level package on the Python path.
- `--list [--all|--modules|--classes|--members|--methods|--functions] [--depth N]
  [ROOT]` → recursive traversal of a package (or all packages), emitting each
  item's **name + type**; functions show **signatures**; annotated types show
  **annotations**.
- `--find [type-filters] [--depth N] [ROOT] QUERY` → the same listing, filtered by
  QUERY, which is a plain **substring** or a `--glob` / `--regex` pattern.
- A bare **NAME** with `[-r|--recursive|--deep | -dN | --depth N]` → dump the
  docstring/API for the name, then either list its children (no recursion flag) or
  recurse docs to the given depth (listing children at the boundary); `-r` =
  unbounded.
- Lives in `~/Projects/skills/pydoc-skill/`; command is `/pydoc`.
- **Milestone 2 (deferred):** a local-only web server on a free port serving the
  same markdown at stable URLs, so listings return links the assistant can fetch.

## Constraints

- **System `python3`, standard library only.** No third-party deps, no venv — the
  tool documents whatever is installed for the system interpreter, so wrapping it
  in an isolated environment would defeat the purpose. (Deliberate deviation from
  the usual "use uv" default, as the task requires.)
- Output is **markdown**, written to **stdout only**; diagnostics and any
  import-time noise are kept off stdout so the injected context stays clean.
- Output must be **bounded** — it lands in the model's context — so there is a
  character budget with a clean truncation notice.

## Architecture

Nested layout (mirrors the `use-yt-dlp` convention in this collection):

```
pydoc-skill/            dev repo — dev-meta + build tooling (NOT shipped)
├── scripts/            install.py · package.py · clean.py · update.py
├── {install,package,clean,update}.sh   thin wrappers -> scripts/*.py
├── .skillignore · .cleanup · .gitignore
├── DESIGN.md · TODO.md · CHANGELOG.md · README.md
└── pydoc/              THE SHIPPABLE SKILL  →  ~/.claude/skills/pydoc/  →  /pydoc
    ├── SKILL.md        name: pydoc; dynamically injects the engine
    └── scripts/pydoc_tool.py   the introspection engine (stdlib only)
```

Why nested: the inner dir name (`pydoc`) becomes the command, so `/pydoc` needs no
frontmatter tricks; and dev-meta/tooling never leak into the shipped `.skill`
because only `pydoc/` is packaged.

**Skill entrypoint (`pydoc/SKILL.md`).** Uses dynamic context injection:
`` !`python3 "${CLAUDE_SKILL_DIR}/scripts/pydoc_tool.py" $ARGUMENTS` ``. Claude Code
runs the engine at invoke time and replaces the line with its markdown output, so
the docs are in context the moment the skill fires. Both user- and model-invocable.
`allowed-tools: Bash(python3:*)` lets the assistant re-run the engine directly for
follow-ups (drilling into any fully-qualified name a listing surfaced).

**Engine (`pydoc/scripts/pydoc_tool.py`).** Self-contained, stdlib only. Sections:
resolution, classification, signature/annotation formatting, child enumeration,
single-object rendering, doc-dump recursion, list/find traversal, top-level index,
output budgeting, hand-rolled arg parsing + dispatch.

## CLI grammar (the contract)

Mode is chosen by scanning for `--list` / `--find`, else a NAME, else usage.

- `NAME [-r|--recursive|--deep | --depth N | -dN] [--private]`
- `--list [TYPE-FILTERS] [--depth N] [--private] [ROOT]`
- `--find [TYPE-FILTERS] [--depth N] [--glob|--regex] [--private] [ROOT] QUERY`

TYPE-FILTERS: `--all --packages --modules --classes --functions --methods --members`.
Common: `--depth N`/`-dN`, `-r`, `--private`/`-a`, `--glob`/`--regex`, `--max-chars N`.

## Key decisions & rationale

- **Hand-rolled arg parsing.** The mixed grammar (mode flags + repeatable type
  filters + optional positionals whose meaning depends on count) is simpler and
  clearer to dispatch by hand than to bend argparse subparsers around.
- **Depth semantics = "levels below the start."** list/find default 1; doc-mode
  default 0 (doc for NAME + list children). No-ROOT list at depth 1 = names only
  (no imports, fast); depth ≥2 imports to descend (opt-in, slower). `-r` = ∞.
- **Import safety.** Every import/getattr is guarded; `quiet_import` suppresses
  warnings and redirects import-time stdout/stderr; recursion is bounded by a
  `visited` id-set (cycles) and a subtree rule (`__module__` prefix) so it doesn't
  wander into re-exported foreign objects; hard output budget on top.
- **3.14 robustness.** `inspect.signature` / `get_annotations` can raise almost
  anything on 3.14 (lazy annotations, unresolvable forward refs — even reading
  `__annotations__` runs `__annotate__`). Both are caught broadly with fallbacks.
- **`--find` arg-order auto-correction.** Grammar is `[ROOT] QUERY` (ROOT first),
  which is easy to reverse. When the designated ROOT can't import but the QUERY
  can, they're swapped — reversal is then unambiguous, and both orders work.
- **Own-members for classes.** Class listings use `vars(cls)` (own `__dict__`),
  not `dir()`, to avoid drowning in inherited `object`/`dict` methods; base classes
  appear in the class header instead.
- **`.skillignore` honoring + clean protect-list.** `package.py` obeys
  gitignore-style `.skillignore`; `clean.py` deletes cache/`.venv`/CACHEDIR.TAG
  dirs and `.cleanup`/`.skillignore` matches, but a hardcoded protect-list
  (`.git`, source `*.py`/`*.sh`/`*.md`, the source dirs) means an over-broad
  pattern can never delete the skill itself.

## Milestone 2 (deferred) — local resource server

Serve the same markdown at stable URLs from a local-only HTTP server on an
ephemeral port, so listings return clickable links the assistant can fetch for
progressive drill-down. **Seam already in place:** every listing item carries its
fully-qualified name, which becomes the URL path (`/doc/<fqname>`), and SKILL.md
already tells the assistant to drill in by name. M2 swaps name-hints for links.

## Known limitations

- Deep traversal of *all* top-level packages (`--list --depth ≥2` with no ROOT)
  imports everything — slow and possibly noisy; scope with a ROOT.
- Docstrings are emitted verbatim (RST/Google/NumPy styles are not converted to
  markdown). Signatures with huge default reprs can be long.
- A module that prints to stdout *and* is imported outside `quiet_import` could in
  principle leak; all traversal paths use `quiet_import`.
