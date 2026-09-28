"""Activate Jev routing once, on the first prompt in a session."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from checkpoint import checkpoint_path, python_command, sanitize_session_id


def routing_policy(plugin_root: Path, current_model: str, checkpoint: Path) -> str:
    route = (plugin_root / "scripts" / "jev_route.py").resolve()
    python = python_command()
    return (
        "Jev subagent routing is active unless JEV_ROUTER_DISABLED=1. "
        "Use delegation-first execution. For every non-trivial user request containing work that can be expressed as an independent subtask, "
        "spawn at least one routed subagent before performing that work in the parent. "
        "Treat implementation, debugging, code review, repository research, and multi-step analysis as non-trivial. "
        "Keep execution in the parent only for a brief answer, clarification, coordination, intrinsically indivisible work, unavailable subagent capability, "
        "or when a higher-priority instruction forbids delegation. Do not spawn only to satisfy this policy for trivial work. "
        "The parent remains responsible for coordination, verification, and the final response. "
        "For each concrete subtask, save only that subtask as UTF-8 and make a fresh routing decision immediately before every spawn_agent with: "
        f'{python} "{route}" --task-file "<absolute-task-file>" --current-model "{current_model}". '
        "The router discovers the currently available Codex models and supported reasoning efforts locally, then chooses the lightest reliable pair across the newest two general GPT families. "
        "Astra is reserved for deep tasks where Jev reports that Sol is insufficient; ultra effort is never selected. "
        "Never reuse a routing result for another subtask. When route is inherit, omit model and reasoning_effort. "
        "Pass a selected model and reasoning_effort only to that spawn. If Codex rejects the selected model, retry that subtask once by inheritance without calling Jev again. "
        f"Maintain the preventive checkpoint at {checkpoint}."
    )


def activate(event: dict, plugin_root: Path, plugin_data: Path) -> dict:
    if os.environ.get("JEV_ROUTER_DISABLED") == "1":
        return {}
    session_id = event.get("session_id")
    cwd = event.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return {}
    sessions = plugin_data.resolve() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    marker = sessions / f"{sanitize_session_id(session_id)}.json"
    context = routing_policy(
        plugin_root.resolve(),
        str(event.get("model") or "<current-model>"),
        checkpoint_path(Path(cwd), session_id),
    )
    created = False
    try:
        with marker.open("x", encoding="utf-8") as stream:
            created = True
            stream.write("{}\n")
    except FileExistsError:
        return {}
    except Exception:
        if created:
            marker.unlink(missing_ok=True)
        raise
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def main() -> int:
    result = {}
    try:
        event = json.load(sys.stdin)
        plugin_data = os.environ.get("PLUGIN_DATA")
        if isinstance(event, dict) and plugin_data:
            root = Path(os.environ.get("PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
            result = activate(event, root, Path(plugin_data))
    except Exception:
        pass
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
