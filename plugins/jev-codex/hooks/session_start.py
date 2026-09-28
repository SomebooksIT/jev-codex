"""Inject checkpoint discipline and bounded compact recovery context."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from checkpoint import checkpoint_path, python_command, validate_checkpoint


RECOVERY_LIMIT = 6_000


def session_context(event: dict, plugin_root: Path) -> dict:
    session_id = event.get("session_id")
    cwd = event.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return {}
    checkpoint = checkpoint_path(Path(cwd), session_id)
    helper = (plugin_root / "scripts" / "checkpoint.py").resolve()
    python = python_command()
    context = (
        "Maintain a preventive Jev checkpoint after material progress, before long work, and before ending a modifying turn. "
        f'Use {python} "{helper}" --workspace "{Path(cwd).resolve()}" --session-id "{session_id}" --content-file "<absolute-content-file>". '
        "Preserve exact technical values and never store secrets."
    )
    if event.get("source") == "compact":
        try:
            content = checkpoint.read_text(encoding="utf-8")
            validate_checkpoint(content)
            if len(content) > RECOVERY_LIMIT:
                content = content[:RECOVERY_LIMIT] + "\n[checkpoint truncated]"
            context += "\n\nRecovered checkpoint:\n" + content
        except (OSError, UnicodeError, ValueError):
            context += " Continue without checkpoint recovery because no readable checkpoint is available."
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def main() -> int:
    result = {}
    try:
        event = json.load(sys.stdin)
        if isinstance(event, dict):
            root = Path(os.environ.get("PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
            result = session_context(event, root)
    except Exception:
        pass
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
