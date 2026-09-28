"""Give subagents the nested routing and checkpoint rules."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from checkpoint import checkpoint_path
from prompt_router import routing_policy


def subagent_context(event: dict, plugin_root: Path) -> dict:
    session_id = event.get("session_id")
    cwd = event.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return {}
    context = (
        "For every nested subagent, "
        + routing_policy(
            plugin_root.resolve(),
            str(event.get("model") or "<current-model>"),
            checkpoint_path(Path(cwd), session_id),
        )
        + " Preserve exact technical values, code, commands, paths, errors, constraints, and ordering."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context,
        }
    }


def main() -> int:
    result = {}
    try:
        event = json.load(sys.stdin)
        if isinstance(event, dict):
            root = Path(os.environ.get("PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
            result = subagent_context(event, root)
    except Exception:
        pass
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
