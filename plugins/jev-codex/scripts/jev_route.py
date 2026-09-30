"""Choose a Codex subagent model for one task, or inherit safely."""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from jev_client import JevUnavailable, ask_jev, contains_sensitive_input


EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = {"fast": "low", "balanced": "medium", "deep": "high"}
MIN_EFFORT = {"fast": "low", "balanced": "low", "deep": "high"}
MAX_EFFORT = {"fast": "low", "balanced": "medium", "deep": "max"}
PREVIOUS_FAMILY_MAX = {"fast": 0.5, "balanced": 0.5, "deep": 0.3}
ASTRA_MIN_SOL_INSUFFICIENT = 0.7
MODEL_ID = re.compile(r"^gpt-(\d+(?:\.\d+)?)-(luna|terra|sol|astra)$")
TIERS = ("fast", "balanced", "deep")
CURRENT_ROLES = {
    "fast": ("luna", "sol"),
    "balanced": ("sol",),
    "deep": ("sol",),
}
PREVIOUS_ROLES = {
    "fast": ("luna",),
    "balanced": ("terra", "sol"),
    "deep": ("sol",),
}
QUESTIONS = {
    "tier": {
        "type": "choice",
        "instructions": "Choose the least costly Codex tier that can complete this subtask reliably.",
        "criteria": {
            "fast": "Mechanical lookup, narrow edit, or simple verification.",
            "balanced": "Ordinary implementation, debugging, or review with bounded complexity.",
            "deep": "Architecture, security, migration, ambiguity, or high-consequence reasoning.",
        },
    },
    "effort": {
        "type": "score",
        "instructions": "Score the least reasoning effort that can complete this subtask reliably.",
        "criteria": [
            "Almost none: direct mechanical work.",
            "Some: normal bounded reasoning.",
            "A lot: multi-step or cross-cutting reasoning.",
            "Very high: unusually difficult or adversarial reasoning.",
            "Maximum: the hardest tasks that still do not require automatic delegation.",
        ],
    },
    "risky": {
        "type": "noul",
        "instructions": "Estimate the probability that an underpowered model could cause material harm.",
        "criteria": {
            "false": "Low consequence and readily reversible.",
            "true": "Security, data, production, or irreversible consequence.",
        },
    },
    "previous_family_insufficient": {
        "type": "noul",
        "instructions": "Estimate whether the previous available GPT model family cannot complete this subtask reliably at the selected effort.",
        "criteria": {
            "false": "The previous family is sufficient; prefer it to conserve compute.",
            "true": "The previous family is likely insufficient; use the current family.",
        },
    },
    "sol_insufficient": {
        "type": "noul",
        "instructions": "Estimate whether current-family Sol, even with high, xhigh, or max reasoning effort, cannot complete this subtask reliably and Astra is strictly necessary.",
        "criteria": {
            "false": "Current-family Sol can complete the task reliably; prefer Sol even when the task is important or high risk.",
            "true": "The task exceeds current-family Sol despite high, xhigh, or max effort, so Astra is strictly necessary.",
        },
    },
}


def _fallback(reason: str) -> dict[str, object]:
    return {"route": "inherit", "reason": reason}


def _number(value: object, minimum: float = 0, maximum: float = 1) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError
    return number


def _decision(payload: object) -> tuple[str, float, str, float, float, float]:
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise ValueError
    answers = payload["answers"]
    required = (
        answers.get("tier"),
        answers.get("effort"),
        answers.get("risky"),
        answers.get("previous_family_insufficient"),
        answers.get("sol_insufficient"),
    )
    if not all(isinstance(answer, dict) for answer in required):
        raise ValueError
    tier_answer, effort_answer, risk_answer, previous_answer, sol_answer = required

    tier = tier_answer.get("choice")
    if tier not in TIERS:
        raise ValueError
    confidence = _number(tier_answer.get("confidence"))
    effort_score = _number(effort_answer.get("score"), 0, 4)
    effort_confidence = _number(effort_answer.get("confidence"))
    risk = _number(risk_answer.get("noul"))
    previous_insufficient = _number(previous_answer.get("noul"))
    sol_insufficient = _number(sol_answer.get("noul"))
    effort = (
        EFFORTS[min(4, int(effort_score + 0.5))]
        if effort_confidence >= 0.3
        else DEFAULT_EFFORT[tier]
    )
    if risk > 0.7:
        effort = EFFORTS[max(2, EFFORTS.index(effort))]
    else:
        effort = EFFORTS[
            min(
                EFFORTS.index(MAX_EFFORT[tier]),
                max(EFFORTS.index(MIN_EFFORT[tier]), EFFORTS.index(effort)),
            )
        ]
    return tier, confidence, effort, risk, previous_insufficient, sol_insufficient


def _send(process: object, message: dict[str, object]) -> None:
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _receive(process: object, request_id: int) -> dict[str, object]:
    for _ in range(20):
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("app_server_eof")
        message = json.loads(line)
        if not isinstance(message, dict) or message.get("id") != request_id:
            continue
        if "error" in message or not isinstance(message.get("result"), dict):
            raise RuntimeError("app_server_error")
        return message["result"]
    raise RuntimeError("app_server_response_missing")


def discover_models(
    *,
    process_factory: Callable[..., object] = subprocess.Popen,
    timeout: float = 3.0,
) -> list[dict[str, object]]:
    """Read the visible Codex model catalog through one short-lived App Server."""
    child_env = dict(os.environ)
    child_env.pop("TYPESAFE_API_KEY", None)
    options: dict[str, object] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "env": child_env,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = process_factory(["codex", "app-server", "--stdio"], **options)
    result: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def transact() -> None:
        try:
            _send(
                process,
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "jev-codex", "version": "0.1.5"},
                        "capabilities": {"experimentalApi": True},
                    },
                },
            )
            _receive(process, 1)
            _send(process, {"method": "initialized"})
            _send(
                process,
                {
                    "id": 2,
                    "method": "model/list",
                    "params": {"includeHidden": False, "limit": 100},
                },
            )
            response = _receive(process, 2)
            models = response.get("data")
            if not isinstance(models, list) or response.get("nextCursor") is not None:
                raise RuntimeError("incomplete_model_catalog")
            result.put((True, models))
        except BaseException as exc:
            result.put((False, exc))

    threading.Thread(target=transact, daemon=True).start()
    try:
        try:
            ok, value = result.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("model_discovery_timeout") from exc
        if not ok:
            raise RuntimeError("model_discovery_failed") from value
        return value
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()


def _family_sort_key(family: str) -> tuple[int, ...]:
    return tuple(int(part) for part in family.split("."))


def _catalog(
    models: object,
) -> tuple[dict[str, dict[str, tuple[str, tuple[str, ...]]]], str, str | None]:
    if not isinstance(models, list):
        raise ValueError
    families: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {}
    for item in models:
        if not isinstance(item, dict) or item.get("hidden") is True or item.get("modelSpecialty") is not None:
            continue
        name = item.get("model")
        match = MODEL_ID.fullmatch(name) if isinstance(name, str) else None
        supported = item.get("supportedReasoningEfforts")
        if match is None or not isinstance(supported, list):
            continue
        efforts = tuple(
            effort
            for effort in EFFORTS
            if any(
                isinstance(option, dict) and option.get("reasoningEffort") == effort
                for option in supported
            )
        )
        if not efforts:
            continue
        family, role = match.groups()
        families.setdefault(family, {}).setdefault(role, (name, efforts))
    newest = sorted(families, key=_family_sort_key, reverse=True)[:2]
    if not newest:
        raise ValueError
    selected = {family: families[family] for family in newest}
    return selected, newest[0], newest[1] if len(newest) > 1 else None


def _select_model(
    families: dict[str, dict[str, tuple[str, tuple[str, ...]]]],
    current_family: str,
    previous_family: str | None,
    tier: str,
    previous_insufficient: float,
    sol_insufficient: float,
) -> tuple[str, tuple[str, ...]]:
    if tier == "deep" and sol_insufficient > ASTRA_MIN_SOL_INSUFFICIENT:
        target_families = ((current_family, ("astra",)),)
    else:
        use_previous = (
            previous_family is not None
            and previous_insufficient <= PREVIOUS_FAMILY_MAX[tier]
        )
        target_families = (
            ((previous_family, PREVIOUS_ROLES[tier]), (current_family, CURRENT_ROLES[tier]))
            if use_previous
            else ((current_family, CURRENT_ROLES[tier]),)
        )
    for family, family_roles in target_families:
        for role in family_roles:
            selected = families[family].get(role)
            if selected is not None:
                return selected
    raise ValueError


def _clamp_effort(requested: str, supported: tuple[str, ...]) -> str:
    index = EFFORTS.index(requested)
    for effort in EFFORTS[index:]:
        if effort in supported:
            return effort
    for effort in reversed(EFFORTS[:index]):
        if effort in supported:
            return effort
    raise ValueError


def _model_tier(model: str | None) -> str | None:
    match = MODEL_ID.fullmatch(model) if isinstance(model, str) else None
    if match is None:
        return None
    role = match.group(2)
    return "fast" if role == "luna" else "deep" if role == "astra" else "balanced"


def route_task(
    task: str,
    *,
    current_model: str | None,
    env: Mapping[str, str],
    ask: Callable[..., object] = ask_jev,
    discover: Callable[[], object] | None = None,
) -> dict[str, object]:
    if env.get("JEV_ROUTER_DISABLED") == "1":
        return _fallback("disabled")
    api_key = env.get("TYPESAFE_API_KEY")
    if not api_key:
        return _fallback("api_key_missing")
    if contains_sensitive_input(task):
        return _fallback("sensitive_input")
    if len(task) > 20_000:
        return _fallback("input_too_large")

    try:
        families, current_family, previous_family = _catalog(
            (discover or discover_models)()
        )
    except Exception:
        return _fallback("model_discovery_failed")

    try:
        tier, confidence, effort, risk, previous_insufficient, sol_insufficient = _decision(
            ask(
                {
                    "task": task,
                    "current_family": current_family,
                    "previous_family": previous_family,
                },
                QUESTIONS,
                api_key=api_key,
            )
        )
    except JevUnavailable as exc:
        return _fallback(exc.reason)
    except (KeyError, TypeError, ValueError):
        return _fallback("invalid_response")
    except Exception:
        return _fallback("unexpected_error")

    if confidence < 0.3:
        return _fallback("low_confidence")

    parent_tier = _model_tier(current_model)
    if parent_tier is None:
        if tier != "deep":
            return _fallback("unknown_current_model")
    elif TIERS.index(tier) < TIERS.index(parent_tier) and confidence < 0.6:
        return _fallback("low_confidence")

    try:
        model, supported = _select_model(
            families,
            current_family,
            previous_family,
            tier,
            previous_insufficient,
            sol_insufficient,
        )
        effort = _clamp_effort(effort, supported)
    except (KeyError, ValueError):
        return _fallback("model_discovery_failed")

    return {
        "route": tier,
        "model": model,
        "reasoning_effort": effort,
        "confidence": confidence,
        "risk": risk,
        "previous_family_insufficient": previous_insufficient,
        "sol_insufficient": sol_insufficient,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--current-model")
    args = parser.parse_args(argv)
    try:
        task = Path(args.task_file).read_text(encoding="utf-8")
        result = route_task(
            task,
            current_model=args.current_model or os.environ.get("CODEX_MODEL"),
            env=os.environ,
        )
    except Exception:
        result = _fallback("unexpected_error")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
