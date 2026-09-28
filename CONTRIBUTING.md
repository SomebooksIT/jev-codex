# Contributing

Contributions should keep the plugin small, fail-safe, and compatible with Codex Desktop.

## Development rules

- Use Python 3.10 or newer and the standard library only for runtime code.
- Write a failing behavioral test before changing runtime behavior, then make the minimum change needed to pass it.
- Treat prompts, diffs, Git metadata, App Server output, and TypeSafe responses as untrusted input.
- Do not add telemetry or log API keys, prompts, diffs, request bodies, or response bodies.
- Keep missing-key, service-unavailable, and discovery failures non-blocking for routing.
- Keep review failures fail-closed: `UNAVAILABLE` must never be presented as `MERGE`.
- Update documentation when behavior, thresholds, installation, or data flow changes.

## Checks

```powershell
py -3.12 -m unittest discover -s tests -v
py -3.12 "$env:USERPROFILE\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py" ".\plugins\jev-codex"
git diff --check
```

On macOS or Linux, use `python3` and the equivalent Codex home path for `validate_plugin.py`.

## Versioning

The public manifest uses semantic versions without local cachebuster metadata. Update `CHANGELOG.md` with user-visible changes. Do not create a release tag until local checks and GitHub Actions pass for the exact target commit.

## Pull requests

Describe behavior, risk, tests, privacy impact, and fallback behavior. Never include real credentials or sensitive production diffs. Security reports belong in GitHub Security Advisories, not public issues.
