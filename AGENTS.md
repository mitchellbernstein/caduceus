# AGENTS.md — Caduceus (Public/GA)

## What This Is
Public GA release repo for Caduceus. This is what end users install.

**This repo is fully self-contained.** It never references `caduceus_private`. Everything a user needs is here.

## Repo Structure
```
caduceus/
├── skills/              # GA Caduceus skills
├── caduceus/           # Python package (db, utils)
├── qmd-collections/    # Starter QMD templates
├── docs/               # GitHub Pages documentation
├── css/, js/           # Site assets
├── index.html          # Landing page
├── pricing.html         # Pricing page
├── get.html            # Install redirect
├── scripts/
│   └── install.sh      # GA installer (curl | sh)
└── AGENTS.md           # This file
```

## Install
```bash
# Option 1: curl | sh
curl -fsSL https://raw.githubusercontent.com/studio-yeehaw/caduceus/main/scripts/install.sh | sh

# Option 2: clone and run
git clone https://github.com/studio-yeehaw/caduceus
cd caduceus && ./scripts/install.sh
```

## Relationship to Private
`caduceus_private` is the development ground. When features are GA-ready, they are copied here. See `caduceus_private/AGENTS.md` for the promotion workflow.

## How It Works
1. Installer copies skills to `~/.hermes/skills/`
2. Installer sets up QMD collections at `~/.hermes/caduceus/`
3. Installer initializes SQLite DB at `~/.hermes/caduceus.db`
4. Skills are auto-discovered by Hermes on next start

## GitHub Pages
The `docs/` folder + root HTML files are served at `get.caduceus.sh`. Push to `main` to deploy.
