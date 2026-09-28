# Security policy

## Reporting a vulnerability

Use the repository's GitHub Security Advisories interface to submit a private report. Include affected versions, impact, reproduction steps, and a minimal non-sensitive example.

Do not post API keys, bearer tokens, private diffs, checkpoint contents, or other credentials in issues, discussions, pull requests, or logs. Revoke or rotate any credential that may have been exposed before reporting it.

## Scope

Security-relevant areas include credential handling, external TypeSafe requests, sensitive-input detection, Git and path validation, checkpoint confinement, hook activation, App Server parsing, and fail-safe review or routing behavior.

The project does not promise that its local sensitive-input guard detects every secret format. Users remain responsible for reviewing content before external analysis.
