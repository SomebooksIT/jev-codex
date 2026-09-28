---
name: jev-checkpoint
description: Use when a long or multi-step Codex task needs recoverable progress before compaction, interruption, or costly work.
---

# Jev Checkpoint

Keep one reproducible checkpoint for the current session. Update it after material progress, before a long command or simulation, before context-heavy work, and before ending a turn that changed files. Preserve exact facts, commands, paths, errors, conditions, and remaining work. Never include credentials or secrets.

Write the content to a temporary UTF-8 file, then use the exact helper command supplied by the session hook:

```powershell
py -3 "<plugin-root>/scripts/checkpoint.py" --workspace "<workspace>" --session-id "<session-id>" --content-file "<absolute-content-file>"
```

Use this complete shape:

```markdown
# Jev checkpoint

## Current objective

## Current plan and active task

## Verified results

## Discarded attempts and causes

## Modified files

## Most recent valid checkpoint

## Exact resume command or procedure

## Remaining verification

## Update timestamp and session identifier
```

Resume from the most recent verified checkpoint. Do not repeat completed work unless current evidence invalidates it.
