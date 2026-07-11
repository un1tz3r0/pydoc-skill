# pydoc-skill — `/pydoc`

A Claude Code skill that pulls **real Python documentation from the system
Python** and dumps it into the conversation as markdown. Signatures, type
annotations, and docstrings for any importable object; package-contents
listings; and symbol search — all grounded in what is actually installed for
`python3` on this machine.

Standard library only. No third-party dependencies, no virtualenv.

## Install

```bash
./install.sh                 # copy pydoc/ -> ~/.claude/skills/pydoc/  (then /pydoc works)
./install.sh --symlink       # symlink instead, so edits here stay live
./install.sh --dry-run       # preview
./install.sh --uninstall     # remove
```

`~/.claude/skills/` is already watched, so `/pydoc` should register in the current
session (restart Claude Code if it doesn't appear).

## Use

```
/pydoc os.path.join                 # signature + docstring, then siblings
/pydoc collections.OrderedDict      # class doc + its methods
/pydoc json --depth 1               # also document one level of children
/pydoc numpy -r                     # recurse docstrings through the subtree

/pydoc --list                       # every top-level package (no imports)
/pydoc --list numpy                 # public contents of numpy
/pydoc --list --classes numpy       # only classes
/pydoc --list --functions --depth 2 json

/pydoc --find json dumps            # substring search under json  (ROOT then QUERY)
/pydoc --find --glob numpy 'array*' # glob
/pydoc --find --regex asyncio '^Async'
```

Type filters: `--all --packages --modules --classes --functions --methods
--members`. Other flags: `--depth N` / `-dN`, `-r`/`--recursive`/`--deep`,
`--private`/`-a`, `--glob`/`--regex`, `--max-chars N`. Run `/pydoc` with no
arguments for the built-in usage message.

`--find` takes `[ROOT] QUERY` (scope first, pattern last); if you reverse them and
only one is an importable package, it auto-corrects.

## Layout

```
pydoc-skill/            this repo — dev-meta + build tooling (not shipped)
├── pydoc/              the shippable skill  ->  ~/.claude/skills/pydoc/  ->  /pydoc
│   ├── SKILL.md
│   └── scripts/pydoc_tool.py     the introspection engine
├── scripts/            install.py · package.py · clean.py · update.py
├── install.sh · package.sh · clean.sh · update.sh
├── .skillignore · .cleanup · .gitignore
└── DESIGN.md · TODO.md · CHANGELOG.md · README.md
```

Only `pydoc/` is installed or packaged; everything else is development tooling.

## Maintenance

```bash
./package.sh     # build pydoc.skill (zip) for upload; runs update first, obeys .skillignore
./clean.sh       # remove caches, .venv, CACHEDIR.TAG dirs, *.skill/*.zip (source is protected)
./update.sh      # git pull --ff-only if this is a checkout with a remote (else no-op)
```

Each `*.sh` is a thin wrapper over the matching `scripts/*.py`; pass `--help` for
full flags, `--dry-run` to preview `install` / `package` / `clean`.

See **DESIGN.md** for architecture and decisions; **Milestone 2** (a local
resource server that serves the same markdown at fetchable URLs) is deferred.
