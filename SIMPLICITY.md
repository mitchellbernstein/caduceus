# Caduceus Simplicity Criterion

Inspired by AutoAgent's simplicity rule: "equal performance + simpler harness = keep."

## The Rule

**Before adding any new skill, tool, pattern, or architectural layer to Caduceus,
ask: "Is this worth the complexity cost?"**

If the answer is no, don't add it.

## Why This Matters

AutoAgent found that "small gains that add ugly complexity should be judged
cautiously." This is especially true for Caduceus — it accumulates skills and
agents for multiple workflows. Without a simplicity filter, the framework becomes
the thing it was designed to replace: an unmaintainable monolith.

## The Test

Apply this before any Caduceus change:

### Question 1: Does this solve a real problem?
- Is there a concrete failure mode this addresses?
- Or is this speculative "might be useful someday" code?

### Question 2: What's the complexity cost?
- New skill file + reference docs
- New agent type in the swarm
- New coordination artifact (json/log file)
- New tooling dependency
- New concept for operators to learn

### Question 3: Is the gain worth the cost?

Use this rubric:

| Gain | Complexity Cost | Decision |
|------|----------------|----------|
| High | Low | **Add it** |
| High | High | **Consider carefully** — scope to minimum |
| Low | Low | **Consider** — marginal improvement |
| Low | High | **Reject** |
| Unknown | Any | **Reject** — don't add things you can't measure |

### Question 4: The Overfitting Check (AutoAgent's Rule)

Ask: **"If this exact use case disappeared tomorrow, would this still be worth it?"**

If no — it's probably overfitting to one workflow and should be a workflow-specific
override, not a framework addition.

## Examples

### Good: Adding `caduceus-browser` skill
- **Gain**: Browser automation for inspection — enables SaaS cloning
- **Cost**: One new skill + Ever CLI dependency
- **Verdict**: Add. The gain (cloning capability) is high, cost is low.

### Good: Adding promise tags to Kairos
- **Gain**: Cleaner agent signaling, prevents polling
- **Cost**: New convention in skill docs
- **Verdict**: Add. Gain is high (orchestration clarity), cost is near zero.

### Bad: Adding a new agent type for every workflow
- **Gain**: Seemingly cleaner separation
- **Cost**: New agent type, new coordination logic, new conceptual surface
- **Verdict**: Reject. Use existing agents with skill-specific prompts instead.

### Bad: Adding a dedicated "visualization" agent
- **Gain**: Nice charts of experiment metrics
- **Cost**: New agent + chart generation pipeline
- **Verdict**: Reject unless visualization is core to the workflow.
  A `make visualize` script achieves the same without adding to the swarm.

## Framework Addition Checklist

Before adding to Caduceus core (`skills/caduceus-*/`), answer:

- [ ] Does this solve a real, observed failure?
- [ ] What's the minimum version that solves it?
- [ ] Does this require a new agent type, or can existing agents handle it?
- [ ] What existing skill or pattern does this compete with?
- [ ] If this disappeared, would Caduceus still work?
- [ ] Is the complexity cost documented?

## What This Does NOT Mean

- Don't add things because they might be useful
- Don't generalize "just in case" — YAGNI applies
- Don't add abstraction layers until the second occurrence
- Framework changes are not free just because they're small

## Enforcement

This criterion is enforced by:
1. **Mitchell** — reviews all PRs to Caduceus core against this checklist
2. **AutoAgent-style review** — the orchestrator should flag when a new
   component has high complexity and low demonstrated gain
