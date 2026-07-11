# TODO — `/pydoc` skill

## Milestone 1 — core skill + tooling  ✅ (2026-07-10)

- [x] Introspection engine `pydoc/scripts/pydoc_tool.py` (stdlib only)
  - [x] Usage message (no args / `-h`)
  - [x] Doc dump for a fully-qualified NAME (signature + annotations + docstring)
  - [x] Children listing + recursion (`--depth N` / `-dN` / `-r`)
  - [x] `--list` top-level index + filtered package traversal
  - [x] `--find` substring / `--glob` / `--regex`, with arg-order auto-correction
  - [x] Type filters, `--private`, output budget (`--max-chars`)
  - [x] Import safety (quiet imports, cycle/subtree guards, broad exception catches)
- [x] `pydoc/SKILL.md` with dynamic `!`-injection; user + model invocable
- [x] Lifecycle tooling: `install` / `package` / `clean` / `update` (.py + .sh)
  - [x] `package.py` honors `.skillignore`; builds `pydoc.skill`; runs `update` first
  - [x] `clean.py` removes caches/.venv/CACHEDIR.TAG/`.cleanup`/`.skillignore`,
        with a source/VCS protect-list
  - [x] `update.py` tolerant `git pull` (no-ops without repo/remote)
- [x] Config: `.skillignore`, `.cleanup`, `.gitignore`
- [x] Dev-meta: DESIGN / TODO / CHANGELOG / README
- [x] End-to-end verification against json, os, collections, numpy, builtins

## Activation (do once)

- [ ] `./install.sh` → copies `pydoc/` to `~/.claude/skills/pydoc/`; then `/pydoc`
      is live. (Or `./install.sh --symlink` to keep edits live from this repo.)
- [x] `git init` + push to GitHub (un1tz3r0/pydoc-skill) — `update.sh` now has a remote.

## Milestone 2 — local resource server (deferred)

- [ ] Local-only HTTP server on an ephemeral port serving `/doc/<fqname>` etc.
- [ ] Listings emit real URLs (the fully-qualified names are already the seam)
- [ ] Server lifecycle (spawn on demand, idle-timeout, no external binding)

## Polish / maybe-later

- [ ] Truncate very long default-value reprs in rendered signatures
- [ ] Optional light RST/Google/NumPy-docstring → markdown normalization
- [ ] `--json` output mode for programmatic consumers
- [ ] Windows `.ps1` wrappers to match the collection's cross-platform skills
