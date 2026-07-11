# Changelog — `/pydoc` skill

All notable changes to this skill are recorded here. Grouped by
Added / Changed / Fixed / Removed, newest first.

## 2026-07-10 — initial build (Milestone 1)

### Added
- Introspection engine `pydoc/scripts/pydoc_tool.py` (system Python, stdlib only):
  - Dump docstring + signature + annotations for any fully-qualified importable
    name, then list its children; recurse with `--depth N` / `-dN` / `-r`.
  - `--list` top-level package index (no imports) and filtered package traversal
    (`--packages --modules --classes --functions --methods --members --all`).
  - `--find` with plain-substring, `--glob`, and `--regex` matching, including
    automatic `[ROOT] QUERY` order-correction.
  - `--private`, `--depth`, and `--max-chars` output-budget controls.
- `pydoc/SKILL.md`: dynamic `!`-injection of the engine with `$ARGUMENTS`;
  user- and model-invocable; `allowed-tools: Bash(python3:*)`.
- Lifecycle tooling (thin `*.sh` wrappers over `scripts/*.py`):
  `install` (copy/symlink into a Claude config dir), `package` (build a
  `.skillignore`-filtered `pydoc.skill` bundle, updating first), `clean` (remove
  regenerable artifacts with a source/VCS protect-list), `update` (tolerant
  `git pull`).
- Config: `.skillignore`, `.cleanup`, `.gitignore`.
- Dev-meta: DESIGN.md, TODO.md, CHANGELOG.md, README.md.

### Fixed
- Python 3.14 robustness: `inspect.signature` / `inspect.get_annotations` (and
  even `getattr(obj, "__annotations__")`) can raise `NameError` and other
  exceptions via lazy annotation evaluation — now caught broadly with docstring /
  empty-dict fallbacks so no object crashes the dump.
- Suppressed import-time warnings and stray stdout/stderr from third-party
  packages so they never pollute the injected markdown.
- Excluded the engine's own `scripts/` directory from the top-level package index
  so `pydoc_tool` doesn't self-report.
