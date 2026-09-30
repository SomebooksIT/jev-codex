# Changelog

All notable changes to Jev for Codex are documented here.

## 0.1.6 - 2026-09-30

- Calibrated model-family thresholds and reasoning-effort ranges from a 66-run study.
- Kept Astra behind explicit evidence that current-family Sol is insufficient.
- Validated the calibrated router in a separate 22-task, 44-run holdout: 22/22 exact-quality passes in both arms and 22.978% fewer paired geometric total execution tokens than `gpt-5.6-sol/medium`.
- Added public benchmark methodology, a machine-readable result summary, and a social-preview asset.
- Moved Quick start ahead of Requirements and clarified the workload-scoped token claim.

## 0.1.5 - 2026-09-28

- Fixed `JEV_ROUTER_DISABLED=1` so nested `SubagentStart` hooks also return no policy.
- Aligned the App Server client version with the plugin release.

## 0.1.4 - 2026-09-28

- Added delegation-first subagent creation for non-trivial independently delegable work.
- Added dynamic discovery of visible Codex models and supported reasoning efforts.
- Added routing across the newest two available numeric GPT families.
- Reserved Astra for deep tasks where Jev reports current-family Sol is insufficient.
- Excluded `ultra` effort and added conservative inheritance fallbacks.
- Added deterministic fourteen-check Jev code review with fail-closed unavailable states.
- Added preventive validated checkpoints and bounded recovery after compaction.
- Added opt-out through `JEV_ROUTER_DISABLED=1` and safe missing-key behavior.
- Documented external data flow, local trust boundaries, installation, and maintenance.
