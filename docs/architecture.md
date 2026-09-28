# Architecture

Jev for Codex is a repository marketplace containing one plugin. It has no daemon, MCP server, telemetry service, or runtime dependency outside Python's standard library.

## Components

| Path | Responsibility |
|---|---|
| `.agents/plugins/marketplace.json` | Public marketplace identity and local plugin source. |
| `plugins/jev-codex/.codex-plugin/plugin.json` | Plugin metadata and UI capabilities. |
| `hooks/hooks.json` | Registers `SessionStart`, `UserPromptSubmit`, and `SubagentStart`. |
| `hooks/session_start.py` | Injects checkpoint discipline and restores at most 6,000 characters after compaction. |
| `hooks/prompt_router.py` | Activates delegation-first routing once on the first successful prompt. |
| `hooks/subagent_start.py` | Propagates policy to nested subagents. |
| `scripts/jev_client.py` | Validated TypeSafe System One HTTP client and sensitive-input guard. |
| `scripts/jev_route.py` | Discovers models, obtains one Jev decision, and selects a supported model/effort pair. |
| `scripts/jev_review.py` | Loads diffs, asks fourteen questions, and applies local review policy. |
| `scripts/checkpoint.py` | Validates, confines, and atomically replaces preventive checkpoints. |
| `skills/jev-review` | User-facing review workflow. |
| `skills/jev-checkpoint` | User-facing checkpoint workflow and nine-section handoff contract. |

## Data flow

For routing, Codex constructs a bounded subtask brief. `jev_route.py` discovers the local catalog, then sends the brief, current/previous family names, and typed routing questions to TypeSafe. It validates the response, applies local thresholds, and prints one compact JSON decision.

For review, `jev_review.py` reads a tracked working diff, a validated Git range, or an explicit diff file. It sends the review state and fourteen questions to TypeSafe, validates all answers, then calculates the verdict locally from `policy.json`.

For checkpoints, content never leaves the machine. `checkpoint.py` rejects malformed or likely sensitive handoffs, verifies the destination remains inside the workspace, writes a temporary file in the destination directory, and replaces atomically.

## Trust boundaries

- User prompts, subtask briefs, diffs, filenames, Git metadata, TypeSafe responses, App Server responses, and checkpoint files are untrusted input.
- The API key is read only from process environment and used only in the Authorization header.
- App Server model discovery is local and runs without the TypeSafe key.
- Review verdicts and routing thresholds are local deterministic policy after the external typed evaluation.
- Hook failures return empty context or inheritance so Codex is not blocked.
