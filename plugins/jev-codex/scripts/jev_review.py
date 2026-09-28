"""Deterministic policy evaluation for Jev code review."""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from jev_client import JevUnavailable, ask_jev, contains_sensitive_input


def load_review_data(root: Path) -> tuple[dict, dict]:
    checks = json.loads((root / "checks.json").read_text(encoding="utf-8"))
    policy = json.loads((root / "policy.json").read_text(encoding="utf-8"))
    return checks, policy


def _value(answer: object, check: dict) -> float | str:
    if not isinstance(answer, dict) or answer.get("type") != check["type"]:
        raise ValueError
    kind = check["type"]
    if kind == "choice":
        value = answer.get("choice")
        if value not in check["criteria"]:
            raise ValueError
        return value
    field = "noul" if kind == "noul" else "score"
    value = answer.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    number = float(value)
    maximum = 1 if kind == "noul" else len(check["criteria"]) - 1
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError
    return number


def _matches(rule: dict, values: dict[str, float | str]) -> bool:
    actual = values[rule["check"]]
    expected = rule["value"]
    return actual >= expected if rule["op"] == "gte" else actual <= expected


def evaluate_policy(answers: dict, checks: dict, policy: dict) -> dict:
    try:
        values = {check_id: _value(answers[check_id], check) for check_id, check in checks.items()}
    except (KeyError, TypeError, ValueError):
        return {"verdict": "UNAVAILABLE", "exit_code": policy["exit_codes"]["UNAVAILABLE"], "triggered": [], "escalation": []}

    minimum = policy["uncertainty"]["minimum"]
    maximum = policy["uncertainty"]["maximum"]
    escalation = [
        {"check": check_id, "value": values[check_id]}
        for check_id, check in checks.items()
        if check["critical"] and minimum <= values[check_id] <= maximum
    ]
    for lane in policy["lanes"]:
        triggered = []
        for rule in lane["rules"]:
            if "unless" in rule and _matches(rule["unless"], values):
                continue
            if _matches(rule, values):
                triggered.append(
                    {
                        "check": rule["check"],
                        "actual": values[rule["check"]],
                        "op": rule["op"],
                        "threshold": rule["value"],
                    }
                )
        if triggered or not lane["rules"]:
            return {
                "verdict": lane["verdict"],
                "exit_code": lane["exit_code"],
                "triggered": triggered,
                "escalation": escalation,
            }
    raise ValueError("policy has no default lane")


def _changed_files(diff: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"^diff --git a/.+? b/(.+)$", diff, re.MULTILINE)))


def _relevant_files(check: dict, changed_files: list[str]) -> list[str]:
    patterns = check["escalation_patterns"]
    return [
        path
        for path in changed_files
        if any(
            pattern == "*"
            or fnmatch.fnmatch(path.lower(), pattern.lower())
            or pattern.strip("*").lower() in path.lower()
            for pattern in patterns
        )
    ]


def _unavailable(reason: str, policy: dict, milliseconds: int = 0) -> dict:
    return {
        "verdict": "UNAVAILABLE",
        "exit_code": policy["exit_codes"]["UNAVAILABLE"],
        "reason": reason,
        "triggered": [],
        "answers": {},
        "escalation": [],
        "omitted_files": 0,
        "milliseconds": milliseconds,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "cost_usd": 0.0,
    }


def review_diff(
    diff: str,
    *,
    title: str,
    description: str,
    ask: Callable[..., dict] = ask_jev,
) -> dict:
    started = time.perf_counter()
    checks, policy = load_review_data(Path(__file__).resolve().parent)

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    if not diff.strip():
        return _no_diff(policy)
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return _unavailable("api_key_missing", policy, elapsed())
    if len(diff) > policy["limits"]["max_input_chars"]:
        return _unavailable("input_too_large", policy, elapsed())
    if contains_sensitive_input(diff):
        return _unavailable("sensitive_input", policy, elapsed())

    state = {
        "pr_title": title,
        "pr_description": description,
        "changed_files": _changed_files(diff),
        "omitted_files": 0,
        "diff": diff,
    }
    questions = {
        check_id: {key: check[key] for key in ("type", "instructions", "criteria")}
        for check_id, check in checks.items()
    }
    try:
        response = ask(state, questions, api_key=api_key)
        answers = response["answers"]
        result = evaluate_policy(answers, checks, policy)
        if result["verdict"] == "UNAVAILABLE":
            return _unavailable("invalid_response", policy, elapsed())
        for item in result["escalation"]:
            item["files"] = _relevant_files(checks[item["check"]], state["changed_files"])
    except JevUnavailable as exc:
        return _unavailable(exc.reason, policy, elapsed())
    except (KeyError, TypeError, ValueError):
        return _unavailable("invalid_response", policy, elapsed())
    except Exception:
        return _unavailable("unexpected_error", policy, elapsed())

    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    if isinstance(input_tokens, bool) or not isinstance(input_tokens, (int, float)):
        input_tokens = 0
    if isinstance(output_tokens, bool) or not isinstance(output_tokens, (int, float)):
        output_tokens = 0
    result.update(
        {
            "answers": answers,
            "omitted_files": 0,
            "milliseconds": elapsed(),
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "cost_usd": round(
                input_tokens * policy["pricing"]["input_per_million_usd"] / 1_000_000
                + output_tokens * policy["pricing"]["output_per_million_usd"] / 1_000_000,
                8,
            ),
        }
    )
    return result


def _git_output(arguments: list[str]) -> str:
    completed = subprocess.run(
        arguments,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise OSError("git diff failed")
    return completed.stdout


def _git_reference(reference: str) -> str:
    if not reference or reference.startswith("-"):
        raise OSError("invalid git reference")
    resolved = _git_output(["git", "rev-parse", "--verify", f"{reference}^{{commit}}"]).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", resolved):
        raise OSError("invalid git reference")
    return resolved


def _git_metadata(reference: str) -> tuple[str, str]:
    raw = _git_output(["git", "log", "--format=%s%x1f%b%x1e", f"{reference}..HEAD", "--"])
    records = []
    for record in raw.split("\x1e"):
        if record.strip():
            title, _, body = record.strip().partition("\x1f")
            records.append((title.strip(), body.strip()))
    if not records:
        return "", ""
    if len(records) == 1:
        return records[0]
    return records[0][0], "\n".join(f"- {title}" for title, _body in records)


def _no_diff(policy: dict) -> dict:
    return {
        "verdict": "NO_DIFF",
        "exit_code": policy["exit_codes"]["NO_DIFF"],
        "triggered": [],
        "answers": {},
        "escalation": [],
        "omitted_files": 0,
        "milliseconds": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "cost_usd": 0.0,
    }


def _print_text(result: dict) -> None:
    print(result["verdict"])
    for trigger in result.get("triggered", []):
        symbol = ">=" if trigger["op"] == "gte" else "<="
        print(f'{trigger["check"]} {trigger["actual"]:.2f} {symbol} {trigger["threshold"]}')
    if result.get("reason"):
        print(f'reason: {result["reason"]}')
    if result.get("escalation"):
        print("escalation: " + ", ".join(f'{item["check"]}={item["value"]:.2f}' for item in result["escalation"]))
    else:
        print("no escalation: all critical checks are outside the configured band")
    print(f'{result.get("milliseconds", 0)} ms; input_tokens={result.get("usage", {}).get("input_tokens", 0)}; cost=${result.get("cost_usd", 0):.5f}')


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff")
    source.add_argument("--git")
    source.add_argument("--working", action="store_true")
    parser.add_argument("--title", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--escalate", action="store_true")
    args = parser.parse_args(argv)
    _, policy = load_review_data(Path(__file__).resolve().parent)
    try:
        if args.diff:
            diff = Path(args.diff).read_text(encoding="utf-8")
        elif args.working:
            diff = _git_output(["git", "diff", "--no-ext-diff", "HEAD"])
        else:
            reference = _git_reference(args.git)
            diff = _git_output(["git", "diff", "--no-ext-diff", f"{reference}..HEAD", "--"])
            derived_title, derived_description = _git_metadata(reference)
            args.title = args.title or derived_title
            args.description = args.description or derived_description
        result = _no_diff(policy) if not diff.strip() else review_diff(
            diff,
            title=args.title,
            description=args.description,
            ask=ask_jev,
        )
    except (OSError, UnicodeError):
        result = _unavailable("input_error", policy)

    if args.escalate and result.get("escalation"):
        result["escalation_prompt"] = "\n".join(
            f'Review {item["check"]} at probability {item["value"]:.2f} in the changed files.'
            for item in result["escalation"]
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    else:
        _print_text(result)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
