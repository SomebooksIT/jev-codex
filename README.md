# Jev for Codex

Jev for Codex is a delegation-first plugin for Codex Desktop. It asks Jev to choose the lightest reliable model and reasoning effort for each subagent, provides deterministic code-review policy, and preserves recoverable task checkpoints.

This is an independent community project. It is not an official project of, or endorsed by, Dario Fontanel, TypeSafe AI, or OpenAI.

## Features

| Feature | Behavior |
|---|---|
| Subagent policy | Requires useful delegation for non-trivial, independently delegable work while keeping coordination and final verification in the parent. |
| Model and effort routing | Discovers models available in the current Codex app and evaluates the newest two numeric GPT families. |
| Conservative Astra use | Selects current-family Astra only for deep work when Jev reports that current-family Sol is insufficient. |
| Safe fallback | Uses `route=inherit` when the key is missing, TypeSafe is unavailable, discovery fails, or confidence is insufficient. |
| Code review | Evaluates 14 typed checks and applies local deterministic policy to produce `BLOCK`, `SECURITY REVIEW`, `NITS`, or `MERGE`. |
| Checkpoints | Validates a nine-section handoff, rejects likely secrets, confines it to the workspace, and writes atomically. |

## Requirements

- Codex Desktop with plugin hooks and subagents.
- Python 3.10 or newer available to Codex.
- Git for review and installation workflows.
- A TypeSafe System One API key for Jev decisions. The plugin remains usable without one through inheritance fallback.

## Install

```powershell
codex plugin marketplace add SomebooksIT/jev-codex --ref main
codex plugin add jev-codex@jev-codex
```

Open a new Codex chat after installation. Hook and skill discovery occurs when a chat starts.

## Configure the TypeSafe key

Never put the key in a prompt, repository, checkpoint, issue, or log.

Windows PowerShell, current process:

```powershell
$env:TYPESAFE_API_KEY = "<YOUR_TYPESAFE_API_KEY>"
```

Windows, persistent user environment:

```powershell
[Environment]::SetEnvironmentVariable("TYPESAFE_API_KEY", "<YOUR_TYPESAFE_API_KEY>", "User")
```

Restart Codex Desktop after setting a persistent variable.

macOS or Linux, current shell:

```bash
export TYPESAFE_API_KEY="<YOUR_TYPESAFE_API_KEY>"
```

Add the same export to the shell profile used to launch Codex for persistence, then restart Codex.

## How routing behaves

The first successful prompt in a chat injects the delegation policy. Before every `spawn_agent`, Codex routes the exact subtask independently. A `route=inherit` result still permits the required subagent; Codex simply omits explicit model and effort overrides.

The router discovers visible general-purpose models and their supported reasoning efforts from a short-lived local `codex app-server --stdio` process. It considers the newest two numeric GPT families present at that time, so it does not depend on hard-coded current-version names. It excludes `ultra` and prefers the lowest-cost pair judged reliable. See [subagent policy](docs/subagents.md) and [routing policy](docs/routing.md).

To opt out of both mandatory delegation and Jev routing:

```powershell
$env:JEV_ROUTER_DISABLED = "1"
```

The opt-out is checked before first-prompt activation. Removing it during the same chat lets a later prompt activate the plugin.

## Code review and checkpoints

Ask Codex to review a diff with Jev or use the installed `jev-review` skill. Empty diffs return `NO_DIFF`; unavailable analysis returns `UNAVAILABLE`, never a false merge verdict.

For long work, the `jev-checkpoint` skill maintains `.codex/jev-checkpoints/<session-id>.md`. Checkpoints are local, ignored by Git, bounded during recovery, and must never contain credentials.

## Privacy

Routing sends the subtask description and five typed questions to `https://api.typesafe.ai/v1/systemone`. Review sends the diff, title, description, changed-file list, and fourteen typed questions. Model discovery and checkpoint handling stay local. The plugin does not intentionally log API keys, prompts, diffs, request bodies, or response bodies. The local sensitive-input guard is defensive, not a complete secret scanner. See [security and data flow](docs/security.md).

## Update

```powershell
codex plugin marketplace upgrade jev-codex
codex plugin remove jev-codex@jev-codex
codex plugin add jev-codex@jev-codex
```

Open a new chat after updating.

## Remove

```powershell
codex plugin remove jev-codex@jev-codex
codex plugin marketplace remove jev-codex
```

## Troubleshooting

- `route=inherit`, `api_key_missing`: set `TYPESAFE_API_KEY` in the environment that launches Codex and restart the app.
- `route=inherit`, `model_discovery_failed`: confirm the installed Codex app exposes `codex app-server --stdio`; inheritance remains safe.
- No policy in an existing chat: open a new chat after installation or update.
- Selected model rejected by Codex: the policy retries that subtask once by inheritance without another Jev call.
- Review returns `UNAVAILABLE`: check the key, connectivity, input size, and whether the diff contains secret-like data.

## Development

```powershell
py -3.12 -m unittest discover -s tests -v
py -3.12 "$env:USERPROFILE\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py" ".\plugins\jev-codex"
```

Runtime code uses only the Python standard library. Contribution and security guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Maintenance

This repository is maintained by `SomebooksIT` as an independent community plugin. Compatibility depends on the installed Codex plugin and App Server interfaces; releases are tested on Windows and Ubuntu with Python 3.10 and 3.12.

## Credits

Jev for Codex is inspired by Dario Fontanel's [jev-claude-code](https://github.com/DarioFontanel/jev-claude-code). Dario Fontanel is the author of that upstream work, not the author or maintainer of this Codex plugin. This project is not endorsed by Dario Fontanel or TypeSafe AI. See [NOTICE.md](NOTICE.md).

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
