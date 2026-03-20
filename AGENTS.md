# AGENTS.md — Caduceus Private (Development)

## What This Is
Internal development/testing ground for Caduceus. All new skills, features, and experiments land here first.

## Repo Structure
```
caduceus_private/
├── skills/              # All Caduceus Hermes skills
│   ├── caduceus-orchestrator/
│   ├── caduceus-engineer/
│   ├── caduceus-researcher/
│   ├── caduceus-writer/
│   ├── caduceus-monitor/
│   ├── caduceus-themis/
│   └── caduceus-kairos/
├── caduceus/            # Python package (queries, utils)
│   └── db/
├── qmd-collections/    # Shared coordination layer
├── scripts/
│   └── install.sh      # Dev installer (local run only)
└── README.md
```

## Two-Repo Strategy

| Repo | Role | Access |
|------|------|--------|
| `caduceus_private` | Dev, test, iterate | Private |
| `caduceus` (public) | GA releases only | Public |

**The public repo MUST be fully self-contained.** Its install script, skills, and assets live entirely in the public repo. It never references or depends on `caduceus_private`.

## Promotion Workflow (Private → Public)

When something in private is GA-ready, manually promote it:

### Step 1: Verify in Private
```bash
cd ~/Documents/GitHub/caduceus_private
# ... build, test, iterate ...
```

### Step 2: Copy GA-Ready Files to Public
Manually copy only the stable files from private to public:

```bash
# Skills that are GA
cp -r skills/caduceus-orchestrator/ ~/Documents/GitHub/caduceus/skills/
cp -r skills/caduceus-engineer/      ~/Documents/GitHub/caduceus/skills/
cp -r skills/caduceus-researcher/    ~/Documents/GitHub/caduceus/skills/
cp -r skills/caduceus-writer/        ~/Documents/GitHub/caduceus/skills/
cp -r skills/caduceus-monitor/       ~/Documents/GitHub/caduceus/skills/
cp -r skills/caduceus-themis/        ~/Documents/GitHub/caduceus/skills/
cp -r skills/caduceus-kairos/        ~/Documents/GitHub/caduceus/skills/

# QMD starter templates
cp -r qmd-collections/agenda/ ~/Documents/GitHub/caduceus/

# Python package (if GA)
cp -r caduceus/db/            ~/Documents/GitHub/caduceus/caduceus/db/

# GitHub Pages site lives in public only — never copy site files from private
```

### Step 3: Push Public
```bash
cd ~/Documents/GitHub/caduceus
git add -A
git commit -m "Release v0.X.Y"
git push origin main
```

## What Stays in Private Only
- Experimental skills not yet GA
- `scripts/install.sh` (private dev installer — not for end users)
- Any test/mock skills or debugging tools
- The `caduceus_private/` Python package internals (queries.py, threat_scan.py, etc. — these are implementation details, not public API)

## What Lives in Public Only
- `index.html`, `pricing.html`, `get.html` (GitHub Pages site)
- `docs/` (documentation)
- `css/styles.css`, `js/main.js`
- `scripts/install.sh` (GA installer — different from private's)
- All skills (GA versions only)
- `qmd-collections/` (starter templates only)

## GitHub Pages Deployment
The public `caduceus/` repo is deployed to GitHub Pages. Push to `main` and Pages auto-deploys.

## Version Policy
- Private: no version constraints (dev)
- Public: follows semver, tagged releases
- Version is defined in `scripts/install.sh` as `CADUCEUS_VERSION`
