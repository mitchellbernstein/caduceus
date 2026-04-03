---
name: caduceus-browser
description: Browser automation for Caduceus — wraps Ever CLI and Playwright for product inspection, UI testing, and QA verification. Used by caduceus-cloner for SaaS cloning and by any agent that needs to see/interact with a live web product.
version: 0.1.0
author: Studio Yeehaw LLC
license: MIT
platforms: [macos, linux]
prerequisites:
  commands: [ever, npx]
metadata:
  hermes:
    tags: [browser, automation, ever-cli, playwright, caduceus-cloner, inspection]
    related_skills: [caduceus-cloner, caduceus-researcher]
triggers:
  - "browser"
  - "ever cli"
  - "playwright"
  - "inspect"
  - "screenshot"
---

# Caduceus Browser — Ever CLI + Playwright Wrapper

This skill provides browser automation for Caduceus agents. It wraps **Ever CLI**
for product inspection (navigating, screenshotting, clicking, filling forms) and
**Playwright** for automated test/QA execution.

## Why Ever CLI + Playwright?

Ralph-to-Ralph proved that cloning a real SaaS product requires actually *using*
the product — not just reading docs. Ever CLI gives agents eyes and hands on a
live web UI. Playwright gives deterministic automated verification.

**Ever CLI** = control plane (agent-driven browser)
**Playwright** = QA plane (automated regression testing)

Both are used together in the caduceus-cloner workflow.

## Prerequisites

```bash
# Install Ever CLI
npm install -g @damianholroyd/ever-cli
# or: npm install -g ever-cli

# Install Playwright
npm install -g playwright
npx playwright install chromium
```

## Ever CLI Commands

Start a browser session pointing at a URL:
```bash
ever start --url https://example.com
ever start --url https://example.com --browser chromium
```

Take a screenshot:
```bash
ever screenshot --output screenshots/inspect/home.jpg
ever screenshot --output screenshots/inspect/dashboard.jpg --full-page
```

Snapshot (accessibility tree — interactive elements):
```bash
ever snapshot
# Returns interactive elements with ref IDs (@e1, @e2, ...)
```

Click an element:
```bash
ever click @e5   # click by accessibility ref ID
```

Fill an input:
```bash
ever input @e3 "test@example.com"
```

Navigate:
```bash
ever navigate https://new-page.com
```

Extract (read page content):
```bash
ever extract
# Returns page text/markdown
```

Stop session:
```bash
ever stop
```

## Playwright Commands

Run all E2E tests:
```bash
npx playwright test
npx playwright test --reporter=list
```

Run a specific test file:
```bash
npx playwright test tests/e2e/smoke.spec.ts
```

Run with UI (headed) for debugging:
```bash
npx playwright test --headed
```

Run a single test:
```bash
npx playwright test tests/e2e/login.spec.ts --grep "renders login form"
```

Interactive debugging:
```bash
npx playwright test --debug
```

## Usage in Caduceus Agents

### Product Inspection (Ever CLI)
```bash
# In a sub-agent spawned by cloner Inspector:
ever start --url https://target-product.com
ever snapshot           # see interactive elements
ever screenshot --output screenshots/inspect/dashboard.jpg
ever click @e7          # click a nav item
ever snapshot           # see new page
ever screenshot --output screenshots/inspect/settings.jpg
ever stop
```

### QA Verification (Playwright)
```bash
# In a sub-agent spawned by cloner QA:
npm run dev &           # start dev server
sleep 5
npx playwright test --reporter=list  # run regression suite
npx playwright test tests/e2e/smoke.spec.ts  # smoke tests
```

## Screenshots Directory Convention

All screenshots go in the project QMD under:
```
~/.hermes/caduceus/projects/<project>/screenshots/
├── inspect/   # from original product during inspection
├── build/     # from clone during build verification
└── qa/        # from clone during QA verification
```

## Important Rules

1. **Always `ever stop` when done** — sessions persist until stopped
2. **Use `trap 'ever stop' EXIT`** — ensure cleanup on script exit
3. **One page per invocation** — don't try to inspect the whole site in one go
4. **Screenshots are artifacts** — commit them to git for downstream agents
5. **Ever CLI for inspection, Playwright for testing** — they're complementary tools
