"""Validate and atomically write preventive Jev checkpoints."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from jev_client import contains_sensitive_input


REQUIRED_HEADINGS = (
    "## Current objective",
    "## Current plan and active task",
    "## Verified results",
    "## Discarded attempts and causes",
    "## Modified files",
    "## Most recent valid checkpoint",
    "## Exact resume command or procedure",
    "## Remaining verification",
    "## Update timestamp and session identifier",
)


def sanitize_session_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")[:160]
    return "session" if sanitized in {"", ".", ".."} else sanitized


def python_command(executable: str = sys.executable, platform: str = os.name) -> str:
    return subprocess.list2cmdline([executable]) if platform == "nt" else shlex.quote(executable)


def checkpoint_path(workspace: Path, session_id: str) -> Path:
    workspace = workspace.resolve()
    directory = (workspace / ".codex" / "jev-checkpoints").resolve()
    if not directory.is_relative_to(workspace):
        raise ValueError("checkpoint directory escapes workspace")
    candidate = (directory / f"{sanitize_session_id(session_id)}.md").resolve()
    if not candidate.is_relative_to(directory):
        raise ValueError("checkpoint path escapes workspace")
    return candidate


def validate_checkpoint(content: str) -> None:
    if contains_sensitive_input(content):
        raise ValueError("checkpoint contains sensitive input")
    lines = set(content.splitlines())
    if any(heading not in lines for heading in REQUIRED_HEADINGS):
        raise ValueError("checkpoint is missing required headings")


def write_checkpoint(workspace: Path, session_id: str, content: str) -> Path:
    validate_checkpoint(content)
    destination = checkpoint_path(workspace, session_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
        os.replace(temporary, destination)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--content-file", required=True)
    args = parser.parse_args(argv)
    try:
        content = Path(args.content_file).read_text(encoding="utf-8")
        path = write_checkpoint(Path(args.workspace), args.session_id, content)
    except (OSError, UnicodeError, ValueError):
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
