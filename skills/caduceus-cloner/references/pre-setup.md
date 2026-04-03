# Pre-configured Stack — Clone Default Tech Choices

These are the default technology choices for a cloned SaaS product.
They are already configured — the builder does NOT reinstall or reconfigure these.

## Framework & Language

- **Next.js 16** — `next.config.js` (standalone output for Docker, Turbopack)
- **TypeScript strict mode** — `tsconfig.json` (`@/` path aliases, no `any`)
- **App Router** — `src/app/` for pages and API routes

## Styling & UI

- **Tailwind CSS** — `tailwind.config.ts` (dark mode, src paths)
- **Radix UI** — headless UI components (accessible dropdowns, dialogs, etc.)

## Database & ORM

- **Postgres** — RDS Postgres via Drizzle ORM
- **Drizzle** — `drizzle.config.ts`, `src/lib/db/schema.ts`
- **Connection**: `DATABASE_URL` env var (set by preflight)

## Testing

- **Vitest** — `vitest.config.ts` (jsdom, path aliases, `tests/*.test.ts`)
- **Playwright** — `playwright.config.ts` + Chromium (`tests/e2e/*.spec.ts`)

## Linting & Formatting

- **Biome** — `biome.json` (lint + format, replaces ESLint/Prettier)
- **Makefile** — standardized commands

## Deployment

- **Docker** — `Dockerfile` (multi-stage, standalone output)
- **AWS ECR** — Docker image registry
- **AWS App Runner** — deployment (or Fly.io as alternative)

## Infrastructure (optional)

- **AWS SES** — email sending/receiving (`@aws-sdk/client-sesv2`)
- **AWS S3** — file storage
- **Cloudflare API** — DNS auto-configuration

## Standardized Makefile Commands

```bash
make check          # typecheck + Biome lint/format
make test          # unit tests (Vitest)
make test-e2e      # E2E tests (Playwright, needs dev server)
make all           # check + test
make fix           # auto-fix lint/format issues
make db-push       # push Drizzle schema to Postgres
npm run dev        # dev server (port defined per project)
npm run build      # production build
```

## Project Structure

```
src/app/           — Next.js App Router (layout, pages, API routes)
src/components/    — React components
src/lib/           — Backend clients (db, ses, s3, etc.)
src/lib/db/        — Drizzle ORM (index.ts + schema.ts)
src/types/         — TypeScript types
tests/unit/        — Unit tests (Vitest)
tests/e2e/         — E2E tests (Playwright)
packages/sdk/      — TypeScript SDK (if target product has one)
scripts/           — Infrastructure and deploy scripts
```

## Out of Scope — DO NOT Build

- Login / signup / authentication (use API key auth wall)
- Billing, payments, subscriptions
- Account settings, profile management
- OAuth / SSO
- Payment processing
