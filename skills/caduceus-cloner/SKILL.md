---
name: caduceus-cloner
description: Autonomous SaaS product cloning workflow — give it any URL, it inspects the product, generates a PRD, implements features with TDD, and QA-verifies the clone. Three-phase pipeline: Inspect → Build → QA, with bounded retries and git backup.
version: 0.1.0
author: Studio Yeehaw LLC
license: MIT
platforms: [macos, linux]
prerequisites:
  commands: [ever, npx, claude, codex]
metadata:
  hermes:
    tags: [saas, cloning, product, autonomous, caduceus, theoi, ralph-to-ralph]
    related_skills: [caduceus-browser, caduceus-engineer, caduceus-orchestrator, caduceus-researcher]
triggers:
  - "clone"
  - "cloner"
  - "saas clone"
  - "product clone"
  - "build a saas from url"
---

# Caduceus Cloner — Autonomous SaaS Product Cloner

Inspired by Ralph-to-Ralph (winner, Ralphthon Seoul 2026). Caduceus Cloner is an
autonomous three-phase pipeline that inspects any SaaS product URL and produces a
fully functional, tested, and deployed full-stack clone — zero human intervention
after the initial URL.

## What It Does

1. **Inspect** — Browse the target product like a human, extract docs, map the UI,
   screenshot every page, generate a structured PRD with 50+ features
2. **Build** — Implement features one-by-one using TDD (write test first, then code),
   run `make check && make test` before every commit
3. **QA** — Verify every feature against the original product, fix bugs, re-test

Ralph-to-Ralph proved this works: 52 features, 24K LOC, 388 passing tests, ~$30-60
in API credits, ~4 hours fully autonomous on Resend.com.

## Usage

### Research Mode (no building — just competitive insights)
```bash
cd ~/Documents/GitHub/caduceus_private
./scripts/caduceus-research/start-research.sh "email API platforms like Resend and Mailgun"
./scripts/caduceus-research/start-research.sh "prayer and spiritual wellness apps"
```
This finds top 2-3 products in the space, inspects them via Ever CLI, and outputs
`research/competitive-insight.md` + screenshots. Zero building — just research.

### Full Clone Mode (inspect + build + QA)
```bash
cd ~/Documents/GitHub/caduceus_private
./scripts/caduceus-cloner/start-cloner.sh https://target-saas.com [project-name]
```

Or via the orchestrator:
```
Use the caduceus-cloner skill to launch: caduceus launch <url>
```

## Directory Structure

```
projects/<project>/              # project dir created by cloner
├── prd.json                    # feature manifest (id, category, behavior, passes, dependent_on)
├── build-spec.md               # full spec: design system, data models, build order
├── inspect-progress.txt        # running log of what was inspected
├── build-progress.txt          # running log of what was built
├── qa-report.json              # per-feature test results + bugs
├── qa-hints.json               # build agent's own QA notes
├── verification-log.json       # cross-phase verification tracking
├── clone-product-docs/         # extracted docs from target product
├── screenshots/
│   ├── inspect/                # from original product
│   ├── build/                  # from clone during build
│   └── qa/                     # from clone during QA
├── tests/
│   ├── unit/                   # Vitest unit tests
│   └── e2e/                    # Playwright E2E tests
└── <clone-product>/           # the actual cloned product source
    ├── src/app/                # Next.js App Router
    ├── src/components/
    ├── src/lib/
    ├── package.json
    ├── Makefile
    └── ...
```

## Phase 1: Inspect

**Agent**: Inspector (Claude + Ever CLI)
**Script**: `inspect-cloner.sh`
**Iterations**: One page/feature per invocation, HARD STOP after each

1. Extract all docs (bulk, via Jina Reader — 1-2 iterations max)
2. Map site structure (`sitemap.md`)
3. Deep-dive pages one-by-one: navigate, snapshot, screenshot, click-test every interaction
4. Write findings incrementally to `build-spec.md`
5. Append feature entries to `prd.json`
6. Output `<promise>NEXT</promise>` or `<promise>INSPECT_COMPLETE</promise>`

Key constraints:
- **ONE page per invocation** — enforced by prompt HARD STOP
- Screenshots of every page
- `dependent_on` on every PRD entry (what it depends on, 3-5 max)
- Final `prd.json` sorted: infrastructure → core features → secondary → polish
- Commit after every iteration

## Phase 2: Build

**Agent**: Builder (Claude)
**Script**: `build-cloner.sh`
**Iterations**: One feature per invocation, TDD — write test first

1. Read `prd.json`, pick first `passes: false` entry
2. Write unit tests (Vitest) + E2E tests (Playwright) for this feature
3. Run tests — expect red (test written before code)
4. Implement the feature
5. Run `make check && make test` — expect green
6. Mark `passes: true` in `prd.json`
7. Log QA hints to `qa-hints.json` (what couldn't be fully tested)
8. Commit and push

Key constraints:
- **ONE feature per invocation**
- TDD: tests *before* implementation
- Never mock away the thing you're testing
- Commit after every feature

## Phase 3: QA

**Agent**: QA (Codex + Ever CLI)
**Script**: `qa-cloner.sh`
**Iterations**: One feature per invocation

1. Read `qa-hints.json` for this feature's entry
2. Run automated regression: `make test` + Playwright smoke suite
3. Manual verification: open clone, follow PRD steps, compare to original
4. Test real infrastructure (not mocks): send real email, hit real API
5. Fix all bugs found
6. Write `qa-report.json` entry
7. Commit

Key constraints:
- **ONE feature per invocation**
- Original product is the source of truth — open it when confused
- **Never weaken/delete tests to make them pass** — fix the code

## Cloner Watchdog (`cloner-watchdog.sh`)

Ralph-to-Ralph-style orchestrator:

```
Phase 1 (Inspect):  max 5 restarts
Phase 2 (Build):    max 10 restarts per cycle
Phase 3 (QA):       independent
Build→QA Cycles:     max 5
```

If QA finds bugs → restart Build → re-QA. If Build crashes → restart Build.
Every iteration commits to git (cron_backup pattern from Ralph-to-Ralph).

## Dependency Tracking

Every PRD entry has `dependent_on`:
```json
{
  "id": "feature-042",
  "dependent_on": ["feature-001", "design-001", "infra-001"]
}
```

QA bundles the feature + its dependencies, so regressions are caught together.

## Standardized Commands

```bash
make check          # typecheck + lint/format
make test           # unit tests (Vitest)
make test-e2e       # E2E tests (Playwright, needs dev server)
make all            # check + test
make db-push        # push schema to Postgres
npm run dev         # start dev server (port defined in clone)
```

## Tech Stack (Ralph-to-Ralph defaults, configurable)

- **Framework**: Next.js 16 (App Router, Turbopack)
- **Language**: TypeScript strict mode
- **Styling**: Tailwind CSS + Radix UI
- **Database**: Postgres via Drizzle ORM
- **Unit Tests**: Vitest
- **E2E Tests**: Playwright
- **Linting**: Biome
- **Cloud**: AWS (SES, RDS, S3) — or local-first alternatives

## Cloner Workflow Diagram

```
User: caduceus launch https://resend.com
  │
  ├─→ Phase 1: Inspect
  │     ever start --url https://resend.com
  │     → prd.json (50+ features)
  │     → build-spec.md
  │     → screenshots/inspect/
  │     → clone-product-docs/
  │
  ├─→ Phase 2: Build (TDD)
  │     For each feature (prd.json passes:false):
  │       1. Write test → red
  │       2. Implement → green
  │       3. make check && make test
  │       4. commit
  │
  └─→ Phase 3: QA
        For each feature:
          1. Automated regression
          2. Manual verify vs original
          3. Fix bugs
          4. qa-report.json
          5. commit

Watchdog loop: Build→QA cycles up to 5x
Git cron_backup after every iteration
```

## Key Files

| File | Purpose |
|------|---------|
| `prd.json` | Feature manifest with `passes`, `dependent_on`, `category` |
| `build-spec.md` | Full spec: design system, data models, build order |
| `qa-report.json` | Per-feature test results + bugs |
| `qa-hints.json` | Build agent's notes on what needs deeper QA |
| `cloner-watchdog.sh` | Phase orchestrator with bounded retries |

## Important Rules

1. **ONE item per invocation** — never try to do a whole phase in one shot
2. **Always commit after every iteration** — git is the watchdog's safety net
3. **TDD in Build** — test first, then code, then regression
4. **QA vs original** — the original product is always the source of truth
5. **No weakening tests** — fix the code, not the test
6. **Promise tags** — always output `<promise>NEXT</promise>` or `<promise>COMPLETE</promise>`
