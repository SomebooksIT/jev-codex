"""Small, validated client for the TypeSafe System One API."""

from __future__ import annotations

import json
import math
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


API_URL = "https://api.typesafe.ai/v1/systemone"
_PLACEHOLDERS = (
    "your-api-key",
    "changeme",
    "example",
    "placeholder",
    "<token>",
    "<secret>",
    "dummy",
    "sk-test",
)
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|password|secret)\b"
    r"\s*[:=]\s*[\"']?([^\s\"';,}]+)"
)
_BEARER_HEADER = re.compile(
    r"(?i)\bauthorization\s*:\s*bearer\s+([^\s\"';,}]+)"
)


class JevUnavailable(RuntimeError):
    """A stable, non-sensitive failure reason for callers and CLIs."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def contains_sensitive_input(text: str) -> bool:
    lowered = text.lower()
    if "-----begin " in lowered and "private key-----" in lowered:
        return True
    if re.search(r"\bAKIA[0-9A-Z]{16}\b", text):
        return True
    for pattern in (_ASSIGNMENT, _BEARER_HEADER):
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            value_lower = value.lower()
            if any(marker in value_lower for marker in _PLACEHOLDERS):
                continue
            if value.startswith(("$", "${", "<")):
                continue
            if len(value) >= 8:
                return True
    return False


def _number(value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevUnavailable("invalid_response")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise JevUnavailable("invalid_response")
    return number


def _validate_response(payload: object, questions: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise JevUnavailable("invalid_response")
    answers = payload["answers"]
    for question_id, raw_question in questions.items():
        if not isinstance(raw_question, dict) or not isinstance(answers.get(question_id), dict):
            raise JevUnavailable("invalid_response")
        question = raw_question
        answer = answers[question_id]
        answer_type = question.get("type")
        if answer.get("type") != answer_type:
            raise JevUnavailable("invalid_response")
        if answer_type == "noul":
            _number(answer.get("noul"), minimum=0, maximum=1)
        elif answer_type == "choice":
            criteria = question.get("criteria")
            choice = answer.get("choice")
            if not isinstance(criteria, dict) or choice not in criteria:
                raise JevUnavailable("invalid_response")
            _number(answer.get("confidence"), minimum=0, maximum=1)
        elif answer_type == "score":
            criteria = question.get("criteria")
            if not isinstance(criteria, list) or len(criteria) < 2:
                raise JevUnavailable("invalid_response")
            _number(answer.get("score"), minimum=0, maximum=len(criteria) - 1)
            _number(answer.get("confidence"), minimum=0, maximum=1)
        else:
            raise JevUnavailable("invalid_response")
    return payload


def ask_jev(
    state: object,
    questions: dict[str, object],
    *,
    api_key: str | None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if not api_key:
        raise JevUnavailable("api_key_missing")

    try:
        data = json.dumps(
            {"state": state, "model": "jev-latest", "questions": questions},
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JevUnavailable("invalid_request") from exc

    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(2):
        try:
            with opener(request, timeout=5) as response:
                raw = response.read()
            try:
                payload = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise JevUnavailable("invalid_response") from exc
            return _validate_response(payload, questions)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 529) and attempt == 0:
                sleeper(0.5)
                continue
            raise JevUnavailable("http_error") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise JevUnavailable("timeout") from exc
        except urllib.error.URLError as exc:
            reason = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "http_error"
            raise JevUnavailable(reason) from exc

    raise JevUnavailable("http_error")
