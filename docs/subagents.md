# Subagent creation policy

Model routing is useful only when Codex creates a subagent. Jev for Codex therefore injects a delegation-first policy on the first successful prompt instead of waiting for the parent to opt in independently.

## Decision sequence

Before substantive work, the parent must:

1. Classify the request as trivial or non-trivial.
2. Identify whether any part is a bounded, independent subtask.
3. When both conditions hold, create at least one routed subagent before doing that work in the parent.
4. When independent branches exist, create only the smallest useful set and avoid duplicate work.
5. Give each subagent a self-contained brief with objective, scope, expected output, constraints, and relevant technical facts. Never include secrets.
6. Collect and verify results in the parent. The parent owns coordination, integration, and the final response.

Implementation, debugging, code review, repository research, and multi-step analysis are non-trivial by default.

## Parent-only exceptions

Keep work in the parent when it is:

- a brief factual answer;
- a clarification or coordination message;
- intrinsically indivisible;
- unsupported by the available subagent capability;
- forbidden from delegation by a higher-priority instruction.

Do not create a ceremonial subagent only to satisfy a count. Delegation must isolate useful work.

## Routing each spawn

Immediately before every `spawn_agent`, save only the concrete subtask as UTF-8 and run the installed `jev_route.py` for that brief. Never reuse a decision for a different subtask.

- A selected route supplies `model` and `reasoning_effort` to that spawn only.
- `route=inherit` still creates the useful subagent but omits both overrides.
- If Codex rejects the selected model, retry that subtask once by inheritance without calling Jev again.
- Every nested subagent receives the same creation, routing, checkpoint, and verification rules through `SubagentStart`.

## Opt-out

`JEV_ROUTER_DISABLED=1` disables both the mandatory-creation policy and Jev routing before first-prompt activation. Codex then uses its normal delegation behavior. Removing the variable before a later prompt allows activation because opt-out does not consume the one-time marker.

## Examples

### Implementation

Request: implement a feature with code and tests. The parent delegates a bounded implementation or verification branch, routes that brief, integrates the result, runs the full suite, and responds.

### Review

Request: review a meaningful diff. The parent may delegate focused inspection, then validates findings against the real diff. A review-only task does not authorize code changes.

### Repository research

Request: trace several independent subsystems. The parent delegates the smallest useful set of separate traces and combines evidence without making agents scan the same files.

### Brief factual answer

Request: state a known command or explain one local fact. The parent answers directly; no useful independent subtask exists.

### Indivisible work

Request: perform one atomic action whose state cannot safely be split. The parent performs it directly and records why delegation was not applicable.
