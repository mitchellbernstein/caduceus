# Caduceus Directive Template

Inspired by AutoAgent's `program.md` — a human-authored contract that defines
what the meta-level agent (orchestrator/Kairos) is allowed to do, what it
cannot touch, and how it decides what to keep.

**This file is the source of truth.** The orchestrator reads it before
spawning any sub-agents. Changes here take effect on the next orchestration run.

---

## Project: <Project Name>

**Author**: <your name>
**Date**: <YYYY-MM-DD>
**Status**: draft | active | archived

---

## Directive

Write the single most important thing you want this project to achieve.
Be specific. This drives everything else.

> Example: "Build a profitable UGC video SaaS in the prayer/wellness space,
> targeting churches and individual Christians, without spending more than
> $200/month on infrastructure."

---

## What You CAN Do

List the specific actions the orchestrator/sub-agents are authorized to take
without asking for approval:

- [ ] Run researcher on competitor X
- [ ] Spawn Kairos experiments for pricing strategy
- [ ] Write and push code to `main` branch
- [ ] Deploy to Fly.io
- [ ] Create new QMD documents in the project collection
- [ ] Open GitHub PRs (require review before merge)

---

## What You CANNOT Do

List actions that require explicit human approval (draft-and-flag):

- [ ] Delete any data or records
- [ ] Push directly to `main` branch
- [ ] Spend more than $50/month without approval
- [ ] Access or modify credentials/secrets
- [ ] Modify this DIRECTIVE.md
- [ ] Spin up new cloud resources
- [ ] Contact any external API without documenting the call in QMD

---

## Success Criteria

How is success measured? Be specific:

| Metric | Current Baseline | Target | How Measured |
|--------|-----------------|--------|---------------|
| <metric 1> | <baseline> | <target> | <measurement method> |
| <metric 2> | <baseline> | <target> | <measurement method> |

---

## Evaluation Frequency

How often should the orchestrator report back?

- [ ] After every agent completion
- [ ] Every 24 hours
- [ ] Only on milestone completion
- [ ] Never — run fully autonomously

---

## Simplicity Constraint

**The Overfitting Rule (AutoAgent)**: If this exact task disappeared,
would this still be a worthwhile improvement?

> Example: "Adding a billing module for Stripe would be worth it even if
> the prayer app use case went away, because it's generally applicable."

---

## Experiment Boundaries

What is Kairos allowed to experiment with?

- [ ] Pricing models (test 3 tiers, measure conversion)
- [ ] Landing page copy (A/B test via deployment)
- [ ] Feature prioritization (which features to build first)
- [ ] Tech stack changes (database, deployment platform)
- [ ] NEW: <specific experiment>

What is off-limits for Kairos?

- [ ] Changing the core value proposition
- [ ] Adding third-party integrations without approval
- [ ] Modifying the agent/swarm architecture

---

## What to Do When Stuck

Priority order when the orchestrator encounters an obstacle:

1. Try a different approach (document failed attempt in QMD)
2. Escalate to human with a specific question + 3 options (A/B/C)
3. If no response in 24h, pick the safest option and document
4. **Never pause indefinitely** — if truly stuck, document why and move on

---

## NEVER STOP Rules

What should run continuously without prompting?

- [ ] Kairos experiment loops
- [ ] Competitive monitoring (weekly re-research on market)
- [ ] Cost monitoring (alert if approaching budget)
- [ ] New feature research (monthly scan of competitor changes)

What requires explicit restart?

- [ ] Full product launches
- [ ] Any change to this directive
- [ ] New market expansions

---

## Notes

<Anything else specific to this project — constraints, context, preferences>
