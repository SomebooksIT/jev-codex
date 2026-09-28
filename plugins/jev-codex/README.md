# Jev for Codex plugin

This directory is the installable Codex Desktop plugin. Repository-level installation, privacy, maintenance, and contribution guidance is in the [root README](../../README.md).

## Hooks

- `SessionStart` injects preventive checkpoint rules and restores at most 6,000 validated characters after compaction.
- `UserPromptSubmit` activates delegation-first routing once on the first successful prompt.
- `SubagentStart` propagates routing and checkpoint rules to nested subagents.

`JEV_ROUTER_DISABLED=1` skips both mandatory delegation and Jev routing before activation.

## Subagent routing

For every non-trivial request containing an independent subtask, Codex creates at least one useful subagent. Before every spawn, it runs `scripts/jev_route.py` on only that subtask. The parent keeps coordination, integration, verification, and the final response.

The router discovers visible models and supported efforts from local App Server `model/list`, considers the newest two numeric GPT families, excludes `ultra`, and prefers the lightest reliable pair. The previous family is eligible when its insufficiency probability is at most `0.30`. Risk above `0.70` raises effort to at least `high`. Current-family Astra requires a `deep` task and probability above `0.70` that current-family Sol is insufficient even with high effort.

Missing key, TypeSafe or discovery failure, sensitive or oversized input, invalid response, or low confidence returns `route=inherit`. Delegation still occurs without model or effort overrides. A rejected explicit model retries once by inheritance without another Jev call.

See [subagent policy](../../docs/subagents.md) and [routing details](../../docs/routing.md).

## Code review

The `jev-review` skill and `scripts/jev_review.py` accept a tracked working diff, validated Git range, or explicit diff file. One TypeSafe request evaluates fourteen typed checks. `policy.json` computes `BLOCK`, `SECURITY REVIEW`, `NITS`, or `MERGE` locally.

Empty diffs return `NO_DIFF`. Missing credentials, sensitive content, input over 250,000 characters, unavailable service, or incomplete answers return `UNAVAILABLE`, never `MERGE`.

## Checkpoints

The `jev-checkpoint` skill and `scripts/checkpoint.py` maintain `.codex/jev-checkpoints/<session-id>.md`. The helper requires all nine handoff sections, rejects likely secrets, prevents path escape, and atomically replaces the destination.

## Privacy

Routing sends the subtask and five typed questions to TypeSafe System One. Review sends the diff metadata and fourteen typed questions. Model discovery and checkpoints stay local. See [security details](../../docs/security.md).

## Credits

This independent plugin is published by SomebooksIT and inspired by Dario Fontanel's [jev-claude-code](https://github.com/DarioFontanel/jev-claude-code). Dario is not the author or maintainer of this plugin, and the project is not endorsed by Dario Fontanel or TypeSafe AI. See [NOTICE](../../NOTICE.md).
