# Kairos Trace Format (ATIF-Inspired)

Inspired by AutoAgent's ATIF (Agent Trajectory Intermediate Format).

Every Kairos iteration MUST emit a structured trace document. This is the
key difference from simple pass/fail: traces capture WHY something worked
or failed, enabling targeted improvement instead of scatter-shot iteration.

## Trace Document Location

`~/.hermes/caduceus/projects/<project>/experiments/<experiment-id>/traces/iteration-<N>.json`

## Trace Schema

```json
{
  "schema_version": "kairos-trace-v1",
  "experiment_id": "<experiment-id>",
  "iteration": 1,
  "timestamp": "ISO-8601",
  "model": "<model used>",
  "duration_ms": 0,

  "hypothesis": "<what we were testing>",
  "verification_spec": ["<criterion 1>", "<criterion 2>"],

  "steps": [
    {
      "step_id": 1,
      "source": "agent|tool|environment",
      "message": "<what happened>",
      "reasoning_content": "<internal reasoning if available>",
      "tool_calls": [{"tool": "name", "arguments": {...}}],
      "observation": "<result>"
    }
  ],

  "final_metrics": {
    "metric_value": 0,
    "baseline": 0,
    "delta": 0,
    "delta_pct": 0
  },

  "verification_result": {
    "status": "pass|fail|partial",
    "criteria_met": ["<criterion>"],
    "criteria_failed": ["<criterion>"]
  },

  "failure_analysis": {
    "root_cause": "<primary reason for failure>",
    "pattern": "misunderstanding|missing_capability|weak_gathering|bad_strategy|missing_verification|environment_issue|silent_failure",
    "affected_tasks": ["<what specifically broke>"]
  },

  "next_iteration_recommendation": {
    "change": "<specific change to try next>",
    "why": "<reasoning for this change>",
    "expected_impact": "<what should improve>"
  }
}
```

## Why Traces Over Pass/Fail

AutoAgent discovered: **traces are everything**. When they only gave scores
without trajectories, improvement rate dropped hard. Understanding WHY something
improved matters as much as knowing that it improved.

Caduceus applies this to Kairos experiments. Every iteration emits a trace.
Future iterations read prior traces to understand failure modes.

## Failure Pattern Reference

| Pattern | Description |
|---------|-------------|
| `misunderstanding` | Agent misunderstood the hypothesis or verification criteria |
| `missing_capability` | Agent lacked a tool or knowledge to execute |
| `weak_gathering` | Not enough data collected before deciding |
| `bad_strategy` | Right data, wrong approach |
| `missing_verification` | Didn't check the result before committing |
| `environment_issue` | External factor (network, tool failure, etc.) |
| `silent_failure` | Agent thought it succeeded but output was wrong |
| `missing_install_step` | Built something but never installed/copied it to the runtime location |
| `path_mismatch` | Registered in index.json but points to wrong location (dev vs runtime) |
| `curl_pipe_python` | curl | python3 pipe-to-interpreter pattern triggering security scan |

## Emitting Traces

Kairos emits a trace after every iteration:

```python
import json
from datetime import datetime

def emit_trace(iteration, hypothesis, steps, metrics, verification, failure_analysis):
    trace = {
        "schema_version": "kairos-trace-v1",
        "experiment_id": experiment_id,
        "iteration": iteration,
        "timestamp": datetime.now().isoformat(),
        "hypothesis": hypothesis,
        "steps": steps,
        "final_metrics": metrics,
        "verification_result": verification,
        "failure_analysis": failure_analysis,
    }
    path = f"traces/iteration-{iteration}.json"
    write_json(path, trace)
    return path
```

## Reading Prior Traces

Before starting a new iteration, Kairos reads all prior traces:

```python
def get_prior_traces(experiment_dir):
    traces = []
    for f in sorted(Path(experiment_dir, "traces").glob("iteration-*.json")):
        traces.append(read_json(f))
    return traces

def diagnose_from_traces(traces):
    """Group failures by root cause pattern."""
    patterns = {}
    for trace in traces:
        if trace.get("verification_result", {}).get("status") != "pass":
            pattern = trace.get("failure_analysis", {}).get("pattern", "unknown")
            patterns.setdefault(pattern, []).append(trace)
    return patterns
```
