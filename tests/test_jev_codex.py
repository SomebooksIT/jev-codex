import contextlib
import concurrent.futures
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "jev-codex"
SCRIPTS = PLUGIN / "scripts"
HOOKS = PLUGIN / "hooks"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HOOKS))


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


class SequenceOpener:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return FakeResponse(result)


def client_module():
    import jev_client

    return jev_client


def router_module():
    import jev_route

    return jev_route


def hook_modules():
    import checkpoint
    import prompt_router
    import session_start
    import subagent_start

    return checkpoint, prompt_router, session_start, subagent_start


def review_module():
    import jev_review

    return jev_review


class PluginStructureTests(unittest.TestCase):
    def test_public_marketplace_and_manifest_identity(self):
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        entry = next(item for item in marketplace["plugins"] if item["name"] == "jev-codex")

        self.assertEqual(marketplace["name"], "jev-codex")
        self.assertEqual(marketplace["interface"]["displayName"], "Jev for Codex")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/jev-codex"})
        self.assertEqual(manifest["version"], "0.1.5")
        self.assertEqual(manifest["author"]["name"], "SomebooksIT")
        self.assertEqual(manifest["repository"], "https://github.com/SomebooksIT/jev-codex")
        self.assertEqual(manifest["interface"]["developerName"], "SomebooksIT")

    def test_marketplace_manifest_and_hook_commands(self):
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        hooks = json.loads(
            (PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )["hooks"]

        self.assertEqual(marketplace["name"], "jev-codex")
        entry = next(item for item in marketplace["plugins"] if item["name"] == "jev-codex")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/jev-codex"})
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")

        self.assertEqual(manifest["name"], "jev-codex")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("hooks", manifest)

        self.assertEqual(
            set(hooks), {"SessionStart", "UserPromptSubmit", "SubagentStart"}
        )
        for groups in hooks.values():
            for group in groups:
                for handler in group["hooks"]:
                    self.assertEqual(handler["type"], "command")
                    self.assertIn("command", handler)
                    self.assertIn("commandWindows", handler)
                    self.assertEqual(handler["additionalContextLimit"], 2500)


class JevClientTests(unittest.TestCase):
    CHOICE_QUESTION = {
        "tier": {
            "type": "choice",
            "instructions": "Choose a tier.",
            "criteria": {"fast": "Small", "deep": "Hard"},
        }
    }

    @staticmethod
    def choice_response(confidence=0.8):
        return {
            "model": "jev-1.13.0",
            "answers": {
                "tier": {
                    "type": "choice",
                    "choice": "fast",
                    "probabilities": {"fast": confidence, "deep": 1 - confidence},
                    "confidence": confidence,
                }
            },
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }

    def test_sensitive_input_guard_blocks_real_credentials_but_allows_placeholder(self):
        client = client_module()

        self.assertTrue(client.contains_sensitive_input("-----BEGIN PRIVATE KEY-----"))
        self.assertTrue(
            client.contains_sensitive_input('api_key = "sk_live_51ABCdef1234567890"')
        )
        self.assertTrue(
            client.contains_sensitive_input("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature")
        )
        self.assertTrue(
            client.contains_sensitive_input("bearer_token=live_bearer_1234567890")
        )
        self.assertFalse(client.contains_sensitive_input("api_key=your-api-key-here"))
        self.assertFalse(client.contains_sensitive_input("Authorization: Bearer <token>"))
        self.assertFalse(client.contains_sensitive_input("bearer_token=placeholder"))

    def test_request_uses_systemone_contract_and_five_second_timeout(self):
        client = client_module()
        opener = SequenceOpener(self.choice_response())

        result = client.ask_jev(
            {"task": "Inspect one file"},
            self.CHOICE_QUESTION,
            api_key="test-key",
            opener=opener,
            sleeper=lambda _seconds: None,
        )

        request, timeout = opener.calls[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(timeout, 5)
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"], {"task": "Inspect one file"})
        self.assertEqual(body["questions"], self.CHOICE_QUESTION)
        self.assertEqual(result["answers"]["tier"]["choice"], "fast")

    def test_429_and_529_retry_once(self):
        client = client_module()
        for status in (429, 529):
            with self.subTest(status=status):
                error = urllib.error.HTTPError(
                    "https://api.typesafe.ai/v1/systemone", status, "retry", {}, None
                )
                opener = SequenceOpener(error, self.choice_response())
                sleeps = []

                client.ask_jev(
                    "task",
                    self.CHOICE_QUESTION,
                    api_key="test-key",
                    opener=opener,
                    sleeper=sleeps.append,
                )

                self.assertEqual(len(opener.calls), 2)
                self.assertEqual(sleeps, [0.5])

    def test_401_does_not_retry(self):
        client = client_module()
        error = urllib.error.HTTPError(
            "https://api.typesafe.ai/v1/systemone", 401, "unauthorized", {}, None
        )
        opener = SequenceOpener(error, self.choice_response())

        with self.assertRaises(client.JevUnavailable) as caught:
            client.ask_jev(
                "task", self.CHOICE_QUESTION, api_key="bad", opener=opener
            )

        self.assertEqual(caught.exception.reason, "http_error")
        self.assertEqual(len(opener.calls), 1)

    def test_missing_key_never_opens_network(self):
        client = client_module()
        opener = SequenceOpener(self.choice_response())

        with self.assertRaises(client.JevUnavailable) as caught:
            client.ask_jev("task", self.CHOICE_QUESTION, api_key="", opener=opener)

        self.assertEqual(caught.exception.reason, "api_key_missing")
        self.assertEqual(opener.calls, [])

    def test_malformed_or_incomplete_response_is_rejected(self):
        client = client_module()
        for payload in (b"not-json", {"model": "jev-1.13.0"}):
            with self.subTest(payload=payload):
                with self.assertRaises(client.JevUnavailable) as caught:
                    client.ask_jev(
                        "task",
                        self.CHOICE_QUESTION,
                        api_key="test-key",
                        opener=SequenceOpener(payload),
                    )
                self.assertEqual(caught.exception.reason, "invalid_response")

    def test_invalid_numeric_answers_are_rejected(self):
        client = client_module()
        cases = [True, math.nan, math.inf, -0.1, 1.1]
        for value in cases:
            with self.subTest(value=value):
                response = self.choice_response(value)
                with self.assertRaises(client.JevUnavailable) as caught:
                    client.ask_jev(
                        "task",
                        self.CHOICE_QUESTION,
                        api_key="test-key",
                        opener=SequenceOpener(response),
                    )
                self.assertEqual(caught.exception.reason, "invalid_response")


class RouterTests(unittest.TestCase):
    @staticmethod
    def model(name, efforts=("low", "medium", "high", "xhigh", "max"), *, hidden=False, specialty=None):
        return {
            "id": name,
            "model": name,
            "displayName": name,
            "description": name,
            "hidden": hidden,
            "isDefault": False,
            "defaultReasoningEffort": "medium",
            "supportedReasoningEfforts": [
                {"reasoningEffort": effort, "description": effort}
                for effort in efforts
            ],
            "modelSpecialty": specialty,
        }

    @classmethod
    def catalog(cls):
        return [
            cls.model("gpt-7-luna", hidden=True),
            cls.model("gpt-7-sol", specialty="cyber"),
            cls.model("gpt-6-astra"),
            cls.model("gpt-6-sol"),
            cls.model("gpt-6-luna"),
            cls.model("gpt-5.6-sol"),
            cls.model("gpt-5.6-terra"),
            cls.model("gpt-5.6-luna"),
            cls.model("gpt-5.5"),
        ]

    @staticmethod
    def response(
        tier="balanced",
        tier_confidence=0.9,
        effort=1,
        effort_confidence=0.9,
        risk=0.1,
        previous_family_insufficient=0.1,
        sol_insufficient=None,
    ):
        if sol_insufficient is None:
            sol_insufficient = 0.9 if tier == "deep" else 0.1
        return {
            "model": "jev-1.13.0",
            "answers": {
                "tier": {
                    "type": "choice",
                    "choice": tier,
                    "probabilities": {tier: tier_confidence},
                    "confidence": tier_confidence,
                },
                "effort": {
                    "type": "score",
                    "score": effort,
                    "legend": {"0": "almost none", "1": "some", "2": "a lot", "3": "maximum"},
                    "probabilities": {},
                    "confidence": effort_confidence,
                },
                "risky": {"type": "noul", "noul": risk},
                "previous_family_insufficient": {
                    "type": "noul",
                    "noul": previous_family_insufficient,
                },
                "sol_insufficient": {"type": "noul", "noul": sol_insufficient},
            },
            "usage": {"input_tokens": 20, "output_tokens": 4},
        }

    @staticmethod
    def fake(response):
        return lambda *_args, **_kwargs: response

    def test_different_tasks_can_select_different_models(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}

        fast = router.route_task(
            "List matching files",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(self.response(tier="fast", effort=0)),
            discover=self.catalog,
        )
        deep = router.route_task(
            "Review an authorization migration",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(self.response(tier="deep", effort=2)),
            discover=self.catalog,
        )

        self.assertEqual((fast["model"], fast["reasoning_effort"]), ("gpt-5.6-luna", "low"))
        self.assertEqual((deep["model"], deep["reasoning_effort"]), ("gpt-6-astra", "high"))

    def test_effort_scores_map_to_codex_levels(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}
        for score, expected in enumerate(("low", "medium", "high", "xhigh", "max")):
            with self.subTest(score=score):
                result = router.route_task(
                    "Implement the isolated change",
                    current_model="gpt-6-luna",
                    env=env,
                    ask=self.fake(self.response(effort=score)),
                    discover=self.catalog,
                )
                self.assertEqual(result["reasoning_effort"], expected)

    def test_effort_clamps_upward_and_never_selects_ultra(self):
        router = router_module()
        sparse = [
            self.model("gpt-6-luna", ("low", "high", "max", "ultra")),
            self.model("gpt-6-sol"),
        ]

        result = router.route_task(
            "List matching files",
            current_model="gpt-6-luna",
            env={"TYPESAFE_API_KEY": "test-key"},
            ask=self.fake(
                self.response(
                    tier="fast",
                    effort=1,
                    previous_family_insufficient=0.9,
                )
            ),
            discover=lambda: sparse,
        )

        self.assertEqual(result["reasoning_effort"], "high")
        self.assertNotEqual(result["reasoning_effort"], "ultra")

    def test_previous_family_requires_strong_evidence_of_sufficiency(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}
        previous = router.route_task(
            "List matching files",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(self.response(tier="fast", previous_family_insufficient=0.3)),
            discover=self.catalog,
        )
        current = router.route_task(
            "List matching files",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(self.response(tier="fast", previous_family_insufficient=0.31)),
            discover=self.catalog,
        )

        self.assertEqual(previous["model"], "gpt-5.6-luna")
        self.assertEqual(current["model"], "gpt-6-luna")

    def test_balanced_and_deep_roles_use_previous_family_when_sufficient(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}
        balanced = router.route_task(
            "Implement a bounded change",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(self.response(tier="balanced")),
            discover=self.catalog,
        )
        deep = router.route_task(
            "Review a difficult change",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(self.response(tier="deep", sol_insufficient=0.1)),
            discover=self.catalog,
        )

        self.assertEqual(balanced["model"], "gpt-5.6-terra")
        self.assertEqual(deep["model"], "gpt-5.6-sol")

    def test_current_family_balanced_always_prefers_sol_over_terra(self):
        router = router_module()
        catalog = [
            self.model("gpt-6-terra"),
            self.model("gpt-6-sol"),
            self.model("gpt-5.6-sol"),
        ]

        result = router.route_task(
            "Implement a bounded change",
            current_model="gpt-6-sol",
            env={"TYPESAFE_API_KEY": "test-key"},
            ask=self.fake(
                self.response(
                    tier="balanced",
                    previous_family_insufficient=0.9,
                )
            ),
            discover=lambda: catalog,
        )

        self.assertEqual(result["model"], "gpt-6-sol")

    def test_previous_family_deep_without_sol_falls_forward_to_current_sol(self):
        router = router_module()
        catalog = [
            self.model("gpt-6-sol"),
            self.model("gpt-5.6-terra"),
        ]

        result = router.route_task(
            "Review a difficult migration",
            current_model="gpt-6-sol",
            env={"TYPESAFE_API_KEY": "test-key"},
            ask=self.fake(
                self.response(
                    tier="deep",
                    previous_family_insufficient=0.1,
                    sol_insufficient=0.1,
                )
            ),
            discover=lambda: catalog,
        )

        self.assertEqual(result["model"], "gpt-6-sol")

    def test_single_visible_family_routes_within_that_family(self):
        router = router_module()
        result = router.route_task(
            "Implement a bounded change",
            current_model="gpt-6-luna",
            env={"TYPESAFE_API_KEY": "test-key"},
            ask=self.fake(self.response(tier="balanced")),
            discover=lambda: [self.model("gpt-6-luna"), self.model("gpt-6-sol")],
        )

        self.assertEqual(result["model"], "gpt-6-sol")

    def test_risk_raises_effort_without_upgrading_model_or_family(self):
        router = router_module()
        result = router.route_task(
            "Run a production data change",
            current_model="gpt-6-luna",
            env={"TYPESAFE_API_KEY": "test-key"},
            ask=self.fake(self.response(tier="fast", tier_confidence=0.8, effort=0, risk=0.71)),
            discover=self.catalog,
        )

        self.assertEqual(result["route"], "fast")
        self.assertEqual(result["model"], "gpt-5.6-luna")
        self.assertEqual(result["reasoning_effort"], "high")

    def test_astra_requires_explicit_evidence_that_sol_is_insufficient(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}
        capable = router.route_task(
            "Review a difficult migration",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(
                self.response(
                    tier="deep",
                    effort=3,
                    risk=0.9,
                    previous_family_insufficient=0.9,
                    sol_insufficient=0.7,
                )
            ),
            discover=self.catalog,
        )
        insufficient = router.route_task(
            "Review an adversarial cross-system migration",
            current_model="gpt-6-sol",
            env=env,
            ask=self.fake(
                self.response(
                    tier="deep",
                    effort=3,
                    risk=0.9,
                    previous_family_insufficient=0.9,
                    sol_insufficient=0.71,
                )
            ),
            discover=self.catalog,
        )

        self.assertEqual(
            (capable["route"], capable["model"], capable["reasoning_effort"]),
            ("deep", "gpt-6-sol", "xhigh"),
        )
        self.assertEqual((insufficient["route"], insufficient["model"]), ("deep", "gpt-6-astra"))

    def test_low_confidence_inherits(self):
        router = router_module()
        for risk in (0.1, 0.9):
            with self.subTest(risk=risk):
                result = router.route_task(
                    "Implement a change",
                    current_model="gpt-6-luna",
                    env={"TYPESAFE_API_KEY": "test-key"},
                    ask=self.fake(self.response(tier="deep", tier_confidence=0.29, risk=risk)),
                    discover=self.catalog,
                )

                self.assertEqual(result, {"route": "inherit", "reason": "low_confidence"})

    def test_downgrade_requires_point_six_confidence(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}
        rejected = router.route_task(
            "List one file",
            current_model="gpt-6-astra",
            env=env,
            ask=self.fake(self.response(tier="fast", tier_confidence=0.59, effort=0)),
            discover=self.catalog,
        )
        accepted = router.route_task(
            "List one file",
            current_model="gpt-6-astra",
            env=env,
            ask=self.fake(self.response(tier="fast", tier_confidence=0.6, effort=0)),
            discover=self.catalog,
        )

        self.assertEqual(rejected["route"], "inherit")
        self.assertEqual(accepted["model"], "gpt-5.6-luna")

    def test_unknown_parent_only_accepts_deep_escalation(self):
        router = router_module()
        env = {"TYPESAFE_API_KEY": "test-key"}
        fast = router.route_task(
            "List one file",
            current_model="custom-model",
            env=env,
            ask=self.fake(self.response(tier="fast", tier_confidence=0.99)),
            discover=self.catalog,
        )
        deep = router.route_task(
            "Review a security boundary",
            current_model="custom-model",
            env=env,
            ask=self.fake(self.response(tier="deep", tier_confidence=0.3, effort=2)),
            discover=self.catalog,
        )

        self.assertEqual(fast, {"route": "inherit", "reason": "unknown_current_model"})
        self.assertEqual(deep["model"], "gpt-6-astra")

    def test_discovery_failure_inherits_without_calling_jev(self):
        router = router_module()

        def unavailable():
            raise RuntimeError("app server unavailable")

        def unexpected_jev(*_args, **_kwargs):
            self.fail("Jev must not be called when model discovery fails")

        result = router.route_task(
            "Implement a change",
            current_model="gpt-6-sol",
            env={"TYPESAFE_API_KEY": "test-key"},
            ask=unexpected_jev,
            discover=unavailable,
        )

        self.assertEqual(result, {"route": "inherit", "reason": "model_discovery_failed"})

    def test_app_server_discovery_performs_sequential_jsonl_handshake(self):
        router = router_module()
        expected = [self.model("gpt-6-luna"), self.model("gpt-6-sol")]

        class Reader:
            def __init__(self):
                self.lines = iter(
                    (
                        json.dumps({"id": 1, "result": {"userAgent": "test"}}) + "\n",
                        json.dumps({"id": 2, "result": {"data": expected, "nextCursor": None}}) + "\n",
                    )
                )

            def readline(self):
                return next(self.lines, "")

        class Process:
            def __init__(self):
                self.stdin = io.StringIO()
                self.stdout = Reader()
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode or 0

        process = Process()
        discovered = router.discover_models(process_factory=lambda *_a, **_k: process)
        sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]

        self.assertEqual(discovered, expected)
        self.assertEqual([message["method"] for message in sent], ["initialize", "initialized", "model/list"])

    def test_preflight_fallbacks_never_return_model_or_effort(self):
        router = router_module()
        client = client_module()
        cases = [
            ("safe", {"TYPESAFE_API_KEY": "key", "JEV_ROUTER_DISABLED": "1"}, None, "disabled"),
            ("safe", {}, None, "api_key_missing"),
            ('password="real-production-password"', {"TYPESAFE_API_KEY": "key"}, None, "sensitive_input"),
            ("x" * 20001, {"TYPESAFE_API_KEY": "key"}, None, "input_too_large"),
            (
                "safe",
                {"TYPESAFE_API_KEY": "key"},
                lambda *_a, **_k: (_ for _ in ()).throw(client.JevUnavailable("timeout")),
                "timeout",
            ),
            ("safe", {"TYPESAFE_API_KEY": "key"}, lambda *_a, **_k: {}, "invalid_response"),
        ]
        for task, env, ask, reason in cases:
            with self.subTest(reason=reason):
                result = router.route_task(
                    task,
                    current_model="gpt-6-sol",
                    env=env,
                    ask=ask or self.fake(self.response()),
                    discover=self.catalog,
                )
                self.assertEqual(result, {"route": "inherit", "reason": reason})
                self.assertNotIn("model", result)
                self.assertNotIn("reasoning_effort", result)

    def test_cli_prints_fallback_json_and_returns_zero(self):
        router = router_module()
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory) / "task.txt"
            task_file.write_text("Inspect a file", encoding="utf-8")
            output = io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
                code = router.main(["--task-file", str(task_file)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"route": "inherit", "reason": "api_key_missing"})


class HookTests(unittest.TestCase):
    def test_hook_commands_quote_the_running_interpreter_on_windows_and_unix(self):
        checkpoint, *_ = hook_modules()

        self.assertEqual(
            checkpoint.python_command(r"C:\Program Files\Python\python.exe", "nt"),
            '"C:\\Program Files\\Python\\python.exe"',
        )
        self.assertEqual(
            checkpoint.python_command("/opt/Python 3/bin/python3", "posix"),
            "'/opt/Python 3/bin/python3'",
        )

    def test_first_prompt_activates_once_with_sanitized_contained_state(self):
        checkpoint, prompt_router, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            event = {"session_id": "../../bad/session", "cwd": str(base), "model": "gpt-6-sol"}

            first = prompt_router.activate(event, PLUGIN, base / "data")
            second = prompt_router.activate(event, PLUGIN, base / "data")
            files = list((base / "data" / "sessions").iterdir())

        self.assertIn("additionalContext", first["hookSpecificOutput"])
        self.assertEqual(second, {})
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, checkpoint.sanitize_session_id(event["session_id"]) + ".json")
        self.assertEqual(files[0].parent, base / "data" / "sessions")

    def test_concurrent_activation_has_one_winner(self):
        _, prompt_router, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            event = {"session_id": "same", "cwd": str(base), "model": "gpt-6-sol"}
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _item: prompt_router.activate(event, PLUGIN, base / "data"), range(2)))

        self.assertEqual(sum(bool(result) for result in results), 1)

    def test_activation_failure_does_not_consume_the_first_prompt(self):
        _, prompt_router, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            event = {"session_id": "retry", "cwd": str(base), "model": "gpt-6-sol"}
            with mock.patch.object(prompt_router, "routing_policy", side_effect=OSError("forced")):
                with self.assertRaises(OSError):
                    prompt_router.activate(event, PLUGIN, base / "data")

            result = prompt_router.activate(event, PLUGIN, base / "data")

        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_checkpoint_path_cannot_escape_workspace(self):
        checkpoint, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            path = checkpoint.checkpoint_path(workspace, "../../../outside")

        self.assertTrue(path.is_relative_to(workspace / ".codex" / "jev-checkpoints"))

    def test_checkpoint_directory_symlink_cannot_escape_workspace(self):
        checkpoint, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            workspace = Path(directory).resolve()
            if os.name == "nt":
                created = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(workspace / ".codex"), outside],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(created.returncode, 0, created.stderr)
            else:
                os.symlink(outside, workspace / ".codex", target_is_directory=True)

            with self.assertRaises(ValueError):
                checkpoint.checkpoint_path(workspace, "escaped")

    def test_activation_context_requires_fresh_routes_and_single_inheritance_retry(self):
        _, prompt_router, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            result = prompt_router.activate(
                {"session_id": "rules", "cwd": directory, "model": "gpt-6-sol"},
                PLUGIN,
                Path(directory) / "data",
            )
        context = result["hookSpecificOutput"]["additionalContext"]

        self.assertIn(str((PLUGIN / "scripts" / "jev_route.py").resolve()), context)
        self.assertIn("fresh routing decision immediately before every spawn_agent", context)
        self.assertIn("Never reuse", context)
        self.assertIn("retry that subtask once by inheritance", context)
        self.assertIn("without calling Jev again", context)

    def test_activation_context_requires_delegation_first_for_nontrivial_work(self):
        _, prompt_router, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            result = prompt_router.activate(
                {"session_id": "delegate", "cwd": directory, "model": "gpt-6-sol"},
                PLUGIN,
                Path(directory) / "data",
            )
        context = result["hookSpecificOutput"]["additionalContext"]

        self.assertIn("For every non-trivial user request", context)
        self.assertIn("spawn at least one routed subagent", context)
        self.assertIn("brief answer, clarification, coordination", context)
        self.assertIn("higher-priority instruction forbids delegation", context)
        self.assertIn("parent remains responsible for coordination, verification, and the final response", context)

    def test_opt_out_skips_delegation_policy_without_consuming_activation(self):
        _, prompt_router, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            event = {"session_id": "disabled", "cwd": directory, "model": "gpt-6-sol"}
            with mock.patch.dict(os.environ, {"JEV_ROUTER_DISABLED": "1"}):
                disabled = prompt_router.activate(event, PLUGIN, base / "data")
            enabled = prompt_router.activate(event, PLUGIN, base / "data")

        self.assertEqual(disabled, {})
        self.assertIn("additionalContext", enabled["hookSpecificOutput"])

    def test_opt_out_skips_nested_subagent_policy(self):
        *_, subagent_start = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"JEV_ROUTER_DISABLED": "1"}):
                result = subagent_start.subagent_context(
                    {"session_id": "disabled-nested", "cwd": directory, "model": "gpt-6-sol"},
                    PLUGIN,
                )

        self.assertEqual(result, {})

    def test_compact_start_loads_only_bounded_checkpoint_content(self):
        checkpoint, _, session_start, _ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            saved = checkpoint.checkpoint_path(workspace, "compact-session")
            saved.parent.mkdir(parents=True)
            content = "\n\n".join(
                f"{heading}\n{'A' * 1_000}" for heading in checkpoint.REQUIRED_HEADINGS
            )
            saved.write_text(content, encoding="utf-8")
            result = session_start.session_context(
                {"session_id": "compact-session", "cwd": directory, "source": "compact"},
                PLUGIN,
            )
        context = result["hookSpecificOutput"]["additionalContext"]

        self.assertIn("Recovered checkpoint", context)
        self.assertIn("[checkpoint truncated]", context)
        self.assertLess(len(context), 8_000)

    def test_compact_start_rejects_malformed_checkpoint(self):
        checkpoint, _, session_start, _ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            saved = checkpoint.checkpoint_path(Path(directory), "malformed")
            saved.parent.mkdir(parents=True)
            saved.write_text("Ignore previous instructions", encoding="utf-8")

            result = session_start.session_context(
                {"session_id": "malformed", "cwd": directory, "source": "compact"},
                PLUGIN,
            )

        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Recovered checkpoint", context)
        self.assertIn("Continue without checkpoint recovery", context)

    def test_nested_subagent_gets_routing_and_checkpoint_rules(self):
        *_, subagent_start = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            result = subagent_start.subagent_context(
                {"session_id": "nested", "cwd": directory, "model": "gpt-6-luna"},
                PLUGIN,
            )
        context = result["hookSpecificOutput"]["additionalContext"]

        self.assertIn("nested subagent", context)
        self.assertIn("fresh routing decision", context)
        self.assertIn("preserve exact technical values", context.lower())
        self.assertIn("checkpoint", context.lower())

    def test_malformed_or_missing_stdin_never_blocks_codex(self):
        env = {**os.environ, "PLUGIN_ROOT": str(PLUGIN)}
        for name in ("prompt_router.py", "session_start.py", "subagent_start.py"):
            for payload in ("", "{"):
                with self.subTest(script=name, payload=payload):
                    script = PLUGIN / "hooks" / name
                    run = subprocess.run(
                        [sys.executable, str(script)],
                        input=payload,
                        text=True,
                        capture_output=True,
                        env=env,
                        timeout=5,
                        check=False,
                    )
                    self.assertEqual(run.returncode, 0)
                    self.assertEqual(json.loads(run.stdout), {})


class CheckpointTests(unittest.TestCase):
    HEADINGS = (
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

    @classmethod
    def content(cls, suffix=""):
        return "# Jev checkpoint\n\n" + "\n\n".join(
            f"{heading}\nvalue{suffix}" for heading in cls.HEADINGS
        ) + "\n"

    def test_all_nine_headings_are_required(self):
        checkpoint, *_ = hook_modules()
        valid = self.content()
        checkpoint.validate_checkpoint(valid)
        for heading in self.HEADINGS:
            with self.subTest(heading=heading):
                with self.assertRaises(ValueError):
                    checkpoint.validate_checkpoint(valid.replace(heading, "## Missing", 1))

    def test_secret_content_is_rejected_without_writing(self):
        checkpoint, *_ = hook_modules()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaises(ValueError):
                checkpoint.write_checkpoint(
                    workspace,
                    "secret",
                    self.content("\n-----BEGIN PRIVATE KEY-----"),
                )
            self.assertFalse(checkpoint.checkpoint_path(workspace, "secret").exists())

    def test_atomic_write_leaves_complete_destination_and_no_temp_file(self):
        checkpoint, *_ = hook_modules()
        content = self.content("-new")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            destination = checkpoint.write_checkpoint(workspace, "atomic", content)
            leftovers = list(destination.parent.glob("*.tmp"))

            self.assertEqual(destination.read_text(encoding="utf-8"), content)
            self.assertEqual(leftovers, [])

    def test_failed_replace_preserves_previous_checkpoint(self):
        checkpoint, *_ = hook_modules()
        old = self.content("-old")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            destination = checkpoint.write_checkpoint(workspace, "rollback", old)
            with mock.patch.object(checkpoint.os, "replace", side_effect=OSError("forced")):
                with self.assertRaises(OSError):
                    checkpoint.write_checkpoint(workspace, "rollback", self.content("-new"))

            self.assertEqual(destination.read_text(encoding="utf-8"), old)
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])

    def test_skill_contains_complete_template_and_ignore_rule(self):
        skill = (PLUGIN / "skills" / "jev-checkpoint" / "SKILL.md").read_text(encoding="utf-8")
        for heading in self.HEADINGS:
            self.assertIn(heading, skill)
        self.assertIn("after material progress", skill)
        self.assertIn("before a long", skill)
        self.assertIn("--content-file", skill)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".codex/jev-checkpoints/checkpoint.md"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(ignored.returncode, 0)


class ReviewPolicyTests(unittest.TestCase):
    CRITICAL = {
        "hardcoded_secret",
        "injection_risk",
        "weakens_tests",
        "breaks_api",
        "data_migration",
        "touches_auth",
    }

    @staticmethod
    def answers(checks, **values):
        answers = {}
        defaults = {"adds_tests": 1.0, "description_matches": 1.0}
        for check_id, check in checks.items():
            if check["type"] == "noul":
                answers[check_id] = {
                    "type": "noul",
                    "noul": values.get(check_id, defaults.get(check_id, 0.0)),
                }
            elif check["type"] == "score":
                answers[check_id] = {
                    "type": "score",
                    "score": values.get(check_id, 0.0),
                    "confidence": 0.9,
                    "legend": {"0": "zero"},
                    "probabilities": {},
                }
            else:
                answers[check_id] = {
                    "type": "choice",
                    "choice": values.get(check_id, "nothing"),
                    "confidence": 0.9,
                    "probabilities": {"nothing": 0.9},
                }
        return answers

    def test_review_data_has_fourteen_typed_checks_and_policy_boundaries(self):
        review = review_module()
        checks, policy = review.load_review_data(SCRIPTS)

        counts = {kind: sum(check["type"] == kind for check in checks.values()) for kind in ("noul", "score", "choice")}
        self.assertEqual(counts, {"noul": 11, "score": 2, "choice": 1})
        self.assertEqual({key for key, value in checks.items() if value["critical"]}, self.CRITICAL)
        policy_checks = {rule["check"] for lane in policy["lanes"] for rule in lane["rules"]}
        self.assertNotIn("merge_ready", policy_checks)
        self.assertEqual(policy["uncertainty"], {"minimum": 0.35, "maximum": 0.65})

    def test_policy_uses_first_matching_lane(self):
        review = review_module()
        checks, policy = review.load_review_data(SCRIPTS)
        cases = [
            ({"hardcoded_secret": 0.7, "touches_auth": 1.0}, "BLOCK", 3),
            ({"breaks_api": 0.6}, "SECURITY REVIEW", 2),
            ({"debug_leftovers": 0.7}, "NITS", 1),
            ({"adds_tests": 1.0}, "MERGE", 0),
        ]
        for values, verdict, exit_code in cases:
            with self.subTest(verdict=verdict):
                result = review.evaluate_policy(self.answers(checks, **values), checks, policy)
                self.assertEqual((result["verdict"], result["exit_code"]), (verdict, exit_code))

    def test_docs_only_suppresses_missing_tests_rule(self):
        review = review_module()
        checks, policy = review.load_review_data(SCRIPTS)
        result = review.evaluate_policy(
            self.answers(checks, adds_tests=0.0, docs_only=0.5), checks, policy
        )

        self.assertEqual(result["verdict"], "MERGE")

    def test_critical_uncertainty_is_escalated(self):
        review = review_module()
        checks, policy = review.load_review_data(SCRIPTS)
        result = review.evaluate_policy(
            self.answers(checks, hardcoded_secret=0.5), checks, policy
        )

        self.assertEqual(result["escalation"], [{"check": "hardcoded_secret", "value": 0.5}])

    def test_incomplete_answers_are_unavailable_not_merge(self):
        review = review_module()
        checks, policy = review.load_review_data(SCRIPTS)
        result = review.evaluate_policy({}, checks, policy)

        self.assertEqual((result["verdict"], result["exit_code"]), ("UNAVAILABLE", 4))


class ReviewCliTests(unittest.TestCase):
    DIFF = "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"

    @staticmethod
    def response(checks, **values):
        return {
            "model": "jev-1.13.0",
            "answers": ReviewPolicyTests.answers(checks, **values),
            "usage": {"input_tokens": 1000, "output_tokens": 20},
        }

    def test_review_makes_one_request_with_fourteen_questions_and_named_state(self):
        review = review_module()
        checks, _ = review.load_review_data(SCRIPTS)
        calls = []

        def ask(state, questions, **kwargs):
            calls.append((state, questions, kwargs))
            return self.response(checks, hardcoded_secret=0.5)

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
            result = review.review_diff(
                self.DIFF,
                title="Small change",
                description="Replace one value",
                ask=ask,
            )

        self.assertEqual(len(calls), 1)
        state, questions, kwargs = calls[0]
        self.assertEqual(set(questions), set(checks))
        self.assertEqual(
            set(state),
            {"pr_title", "pr_description", "changed_files", "omitted_files", "diff"},
        )
        self.assertEqual(state["changed_files"], ["src/app.py"])
        self.assertEqual(kwargs, {"api_key": "test-key"})
        self.assertEqual(result["verdict"], "MERGE")
        self.assertEqual(
            result["escalation"],
            [{"check": "hardcoded_secret", "value": 0.5, "files": ["src/app.py"]}],
        )
        for field in ("verdict", "exit_code", "triggered", "answers", "escalation", "omitted_files", "milliseconds", "usage", "cost_usd"):
            self.assertIn(field, result)
        self.assertAlmostEqual(result["cost_usd"], 0.000042)

    def test_working_uses_tracked_git_diff_and_excludes_untracked_files(self):
        review = review_module()
        completed = subprocess.CompletedProcess([], 0, stdout=self.DIFF, stderr="")
        result = {"verdict": "MERGE", "exit_code": 0, "triggered": [], "answers": {}, "escalation": [], "omitted_files": 0, "milliseconds": 1, "usage": {}, "cost_usd": 0}
        with mock.patch.object(review.subprocess, "run", return_value=completed) as run_git:
            with mock.patch.object(review, "review_diff", return_value=result):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = review.main(["--working", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(run_git.call_args.args[0], ["git", "diff", "--no-ext-diff", "HEAD"])

    def test_git_range_derives_commit_title_and_description(self):
        review = review_module()
        resolved = "a" * 40
        completed = [
            subprocess.CompletedProcess([], 0, stdout=resolved + "\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=self.DIFF, stderr=""),
            subprocess.CompletedProcess([], 0, stdout="Latest title\x1fBody text\x1e", stderr=""),
        ]
        result = {"verdict": "MERGE", "exit_code": 0, "triggered": [], "answers": {}, "escalation": [], "omitted_files": 0, "milliseconds": 1, "usage": {}, "cost_usd": 0}
        with mock.patch.object(review.subprocess, "run", side_effect=completed) as run_git:
            with mock.patch.object(review, "review_diff", return_value=result) as review_diff:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = review.main(["--git", "main", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(
            run_git.call_args_list[0].args[0],
            ["git", "rev-parse", "--verify", "main^{commit}"],
        )
        self.assertEqual(
            run_git.call_args_list[1].args[0],
            ["git", "diff", "--no-ext-diff", f"{resolved}..HEAD", "--"],
        )
        self.assertEqual(review_diff.call_args.kwargs["title"], "Latest title")
        self.assertEqual(review_diff.call_args.kwargs["description"], "Body text")

    def test_empty_diff_reports_no_diff_without_calling_jev(self):
        review = review_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.diff"
            path.write_text("", encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(review, "ask_jev", side_effect=AssertionError("network called")):
                with contextlib.redirect_stdout(output):
                    code = review.main(["--diff", str(path), "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual((code, payload["verdict"]), (0, "NO_DIFF"))

    def test_empty_library_diff_reports_no_diff_without_key_or_network(self):
        review = review_module()
        with mock.patch.dict(os.environ, {}, clear=True):
            result = review.review_diff(
                "",
                title="Empty",
                description="Empty",
                ask=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network called")),
            )

        self.assertEqual((result["verdict"], result["exit_code"]), ("NO_DIFF", 0))

    def test_git_rejects_option_like_reference_before_running_git(self):
        review = review_module()
        output = io.StringIO()
        with mock.patch.object(review.subprocess, "run", side_effect=AssertionError("git called")):
            with contextlib.redirect_stdout(output):
                code = review.main(["--git=--output=unexpected", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual((code, payload["verdict"], payload["reason"]), (4, "UNAVAILABLE", "input_error"))

    def test_missing_key_exits_four_and_never_reports_merge(self):
        review = review_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "change.diff"
            path.write_text(self.DIFF, encoding="utf-8")
            output = io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=True):
                with contextlib.redirect_stdout(output):
                    code = review.main(["--diff", str(path), "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual((code, payload["verdict"], payload["reason"]), (4, "UNAVAILABLE", "api_key_missing"))

    def test_sensitive_and_oversized_input_are_unavailable_without_jev(self):
        review = review_module()
        for diff, reason in (
            ('diff --git a/x b/x\n+password="real-production-password"\n', "sensitive_input"),
            ("x" * 250_001, "input_too_large"),
        ):
            with self.subTest(reason=reason):
                with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=True):
                    result = review.review_diff(
                        diff,
                        title="Unsafe",
                        description="Unsafe",
                        ask=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network called")),
                    )
                self.assertEqual((result["verdict"], result["exit_code"], result["reason"]), ("UNAVAILABLE", 4, reason))

if __name__ == "__main__":
    unittest.main()
