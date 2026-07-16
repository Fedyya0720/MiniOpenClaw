"""Tests for the evaluation-only PACS ablation harness."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from eval.fixtures.pacs_projects import (
    create_clean_project,
    create_conflict_project,
    create_parallel_speed_project,
    create_pruning_amplifier_project,
    create_real_package_conflict_project,
)
from eval.pacs_agent_ablation import (
    _agent_completed,
    _fixture_hash,
    _installation_requests,
    _isolated_constraint_graph,
    _run_trial_subprocess,
    build_variant_dependencies,
    summarize,
)
from eval.pacs_factorial_ablation import (
    NoLearningConstraintGraph,
    _serial_mode,
    summarize as summarize_factorial,
)
from backend.fake_backend import FakeBackend
import tools.resolver_tools as resolver_tools
from resolver.failure_parser import parse_failure
from resolver.solver import solve_candidates


class AblationFixtureTests(unittest.TestCase):
    def test_conflict_fixture_has_prunable_cartesian_slice(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = create_conflict_project(Path(parent) / "fixture")
            catalog = fixture["catalog"]
            unconstrained = solve_candidates(catalog, [], limit=20)["combinations"]
            constrained = solve_candidates(catalog, [{
                "pkg_a": "demo-core",
                "ver_a": "2.0.0",
                "pkg_b": "demo-plugin",
                "ver_b": "1.0.0",
                "kind": "observed",
                "confidence": 0.9,
            }], limit=20)["combinations"]
            self.assertEqual(len(unconstrained), 6)
            self.assertEqual(len(constrained), 3)
            self.assertEqual(fixture["validation_modules"], [
                "demo_core", "demo_plugin", "demo_addon"
            ])
            self.assertIn("--progress-bar", fixture["pip_args"])

    def test_semantically_identical_fixtures_have_same_hash(self):
        with tempfile.TemporaryDirectory() as parent:
            left = create_conflict_project(Path(parent) / "left")
            right = create_conflict_project(Path(parent) / "right")
            self.assertEqual(_fixture_hash(left), _fixture_hash(right))

    def test_parallel_speed_fixture_has_ordered_validation_failures(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = create_parallel_speed_project(
                Path(parent) / "speed", payload_mib=0.001
            )
            self.assertEqual(fixture["catalog"]["speed-candidate"], [
                "4.0.0", "3.0.0", "2.0.0", "1.0.0"
            ])
            self.assertEqual(fixture["expected_winner_rank"], 4)
            self.assertEqual(fixture["max_attempts"], 4)
            self.assertGreater(fixture["payload_bytes"], 0)
            self.assertEqual(len(list(Path(fixture["wheelhouse"]).glob("*.whl"))), 4)

    def test_pruning_amplifier_scales_exact_pair_exclusion(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = create_pruning_amplifier_project(
                Path(parent) / "amplifier", addon_count=3
            )
            edge = {
                "pkg_a": "amp-core", "ver_a": "2.0.0",
                "pkg_b": "amp-plugin", "ver_b": "1.0.0",
                "kind": "observed", "confidence": 0.9,
            }
            unconstrained = solve_candidates(fixture["catalog"], [], limit=20)["combinations"]
            constrained = solve_candidates(fixture["catalog"], [edge], limit=20)["combinations"]
            self.assertEqual((len(unconstrained), len(constrained)), (6, 3))
            self.assertEqual(fixture["expected_excluded_by_constraints"], 3)
            self.assertEqual(fixture["max_attempts"], 4)

    def test_real_package_fixture_pins_conflicting_candidate_slice(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = create_real_package_conflict_project(Path(parent) / "real")
            self.assertEqual(fixture["catalog"]["requests"], ["2.25.0"])
            self.assertEqual(fixture["catalog"]["urllib3"], ["2.0.0", "1.26.20"])
            self.assertIn("requests", fixture["validation_modules"])
            self.assertIn("version('urllib3') in", fixture["smoke_code"])
            self.assertIn("version('certifi') in", fixture["smoke_code"])
            self.assertIn("version('urllib3') == '1.26.20'", fixture["smoke_code"])
            self.assertIn("--progress-bar", fixture["pip_args"])

    def test_clean_fixture_is_installable_project(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = create_clean_project(Path(parent) / "clean")
            project = Path(fixture["project"])
            self.assertTrue((project / "pyproject.toml").is_file())
            self.assertTrue((project / "demo_clean" / "__init__.py").is_file())


class AgentVariantTests(unittest.TestCase):
    def test_agent_completion_requires_verified_environment_path(self):
        path = "/tmp/trial/.miniopenclaw_envs/winner"
        self.assertTrue(_agent_completed(f"环境已验证通过：{path}", None, [path]))
        self.assertTrue(_agent_completed("环境：/tmp/second", None, [path, "/tmp/second"]))
        self.assertTrue(_agent_completed("环境：.miniopenclaw_envs/winner", None, [path]))
        self.assertTrue(_agent_completed("环境：/tmp/.../winner", None, [path]))
        self.assertFalse(_agent_completed("环境已验证通过。", None, [path]))
        self.assertFalse(_agent_completed("", None, [path]))
        self.assertFalse(_agent_completed("[达到最大轮数上限，未完成任务]", None, [path]))
        self.assertFalse(_agent_completed(f"依赖冲突，无法完成任务。{path}", None, [path]))
        self.assertFalse(_agent_completed(f"环境已验证通过：{path}", "RuntimeError: failed", [path]))
        self.assertFalse(_agent_completed(f"环境已验证通过：{path}", None, []))

    def test_worker_imports_security_inside_trial_directory(self):
        repository = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as parent:
            trial_root = Path(parent) / "trial"
            fixture = create_clean_project(trial_root)
            workdir = Path(fixture["project"])
            config_path = trial_root / "worker-config.json"
            result_path = trial_root / "worker-result.json"
            config_path.write_text(json.dumps({
                "variant": "pacs-agent",
                "trial_root": str(trial_root),
                "fixture_kind": "clean",
                "max_turns": 1,
                "fixture": fixture,
                "result_path": str(result_path),
                "fake_backend": True,
            }), encoding="utf-8")
            environment = os.environ.copy()
            environment["DEEPSEEK_API_KEY"] = ""
            environment["PYTHONPATH"] = str(repository)
            completed = subprocess.run(
                [sys.executable, "-m", "eval.pacs_agent_ablation", "--_worker-config", str(config_path)],
                cwd=str(workdir), env=environment, capture_output=True, text=True,
                timeout=30, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            record = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(record["isolation"]["ok"])
            self.assertEqual(record["isolation"]["cwd"], str(workdir.resolve()))
            self.assertEqual(record["isolation"]["write_root"], str(workdir.resolve()))
            self.assertEqual(record["termination_reason"], "max_turns")
            self.assertTrue(record["cap_reached"])
            self.assertEqual(record["turns_remaining"], 0)

    def test_parent_records_worker_timeout(self):
        with tempfile.TemporaryDirectory() as parent:
            record = _run_trial_subprocess(
                "pacs-agent", Path(parent) / "trial",
                fixture_kind="clean", max_turns=60, timeout=0.001,
            )
        self.assertFalse(record["success"])
        self.assertEqual(record["termination_reason"], "subprocess_timeout")
        self.assertFalse(record["isolation"]["ok"])

    def test_installation_requests_exclude_verification_specs(self):
        spans = [
            {"name": "env_run", "arguments": {"specs": [
                {"packages": ["requests==2.25.0"]},
                {"argv": ["-m", "pip", "check"]},
                {"argv": ["-c", "import requests"]},
                {"argv": ["-m", "pip", "install", "flask"]},
            ]}},
            {"name": "bash", "arguments": {"command": "python -m pip check"}},
            {"name": "bash", "arguments": {"command": "python -m pip install flask"}},
        ]
        self.assertEqual(_installation_requests(spans), 3)
        self.assertEqual(
            _installation_requests([{"name": "pacs_build", "arguments": {}}]),
            1,
        )

    def test_traditional_variant_removes_only_pacs_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend()
            _, traditional, prompt = build_variant_dependencies(
                "traditional-agent", directory, backend=backend
            )
            _, pacs, pacs_prompt = build_variant_dependencies(
                "pacs-agent", directory, backend=backend
            )
        self.assertNotIn("pacs_build", traditional.names())
        self.assertIn("pacs_build", pacs.names())
        self.assertIn("env_run", traditional.names())
        self.assertIn("parse_failure", traditional.names())
        self.assertNotIn("python-env-builder", prompt)
        self.assertIn("不得调用 `pacs_build`", prompt)
        self.assertIn("python-env-builder", pacs_prompt)
        self.assertIn("第一次工具调用必须是 `pacs_build", pacs_prompt)
    def test_constraint_graph_is_trial_local_and_restored(self):
        previous = resolver_tools._constraint_graph
        with tempfile.TemporaryDirectory() as directory:
            with _isolated_constraint_graph(directory):
                self.assertIsNot(resolver_tools._constraint_graph, previous)
                self.assertTrue(str(resolver_tools._constraint_graph._db_path).startswith(directory))
        self.assertIs(resolver_tools._constraint_graph, previous)

    def test_summary_reports_iqr_and_paired_reductions(self):
        records = []
        for block, traditional_seconds, pacs_seconds in ((1, 12.0, 4.0), (2, 18.0, 6.0)):
            records.extend([
                {
                    "block": block,
                    "variant": "traditional-agent",
                    "success": False,
                    "cap_reached": True,
                    "termination_reason": "max_turns",
                    "isolation": {"ok": True},
                    "worker": {"returncode": 0},
                    "duration_seconds": traditional_seconds,
                    "metrics": {
                        "turns": 30, "tool_calls": 20, "total_tokens": 1000,
                        "installation_requests": 2, "candidate_attempts": None,
                    },
                },
                {
                    "block": block,
                    "variant": "pacs-agent",
                    "success": True,
                    "cap_reached": False,
                    "termination_reason": "completed",
                    "isolation": {"ok": True},
                    "worker": {"returncode": 0},
                    "duration_seconds": pacs_seconds,
                    "metrics": {
                        "turns": 10, "tool_calls": 8, "total_tokens": 400,
                        "installation_requests": 1, "candidate_attempts": 4,
                    },
                },
            ])
        result = summarize(records)
        self.assertEqual(result["traditional-agent"]["terminal_seconds"], {
            "median": 15.0, "iqr": 3.0,
        })
        self.assertEqual(result["paired"]["pacs_only_successful"], 2)
        self.assertEqual(
            result["paired"]["all_measurable_blocks_terminal_resource_contrast"]
            ["time_ratio_traditional_over_pacs"]["median"],
            3.0,
        )
        self.assertEqual(
            result["paired"]["all_measurable_blocks_terminal_resource_contrast"]
            ["turn_reduction_traditional_minus_pacs"]["median"],
            20.0,
        )
        self.assertEqual(
            result["paired"]["both_successful_blocks"],
            {"blocks": 0, "completion_performance": None},
        )
        self.assertFalse(result["cap_assessment"]["accepted_for_completion_time_comparison"])

    def test_summary_uses_strict_trial_success(self):
        records = [{
            "variant": "traditional-agent",
            "success": False,
            "cap_reached": True,
            "termination_reason": "max_turns",
            "isolation": {"ok": True},
            "duration_seconds": 1.0,
            "metrics": {
                "turns": 30, "tool_calls": 30, "total_tokens": 100,
                "installation_requests": 2, "candidate_attempts": None,
            },
        }]
        self.assertEqual(summarize(records)["traditional-agent"]["success_rate"], 0.0)


class FactorialHarnessTests(unittest.TestCase):
    def test_factorial_summary_reports_paired_main_effects(self):
        durations = {
            "serial-naive": 10.0,
            "serial-pruning": 8.0,
            "parallel-naive": 7.0,
            "parallel-pruning": 4.0,
        }
        records = [{
            "block": 1,
            "variant": {
                "name": name,
                "parallel": 1 if name.startswith("serial") else 2,
                "pruning": name.endswith("pruning"),
            },
            "success": True,
            "duration_seconds": seconds,
            "attempted": 2,
            "preflight_calls": 2,
            "excluded_by_constraints": 3 if name.endswith("pruning") else 0,
        } for name, seconds in durations.items()]
        result = summarize_factorial(records)
        self.assertEqual(result["paired_effects"]["blocks"], 1)
        self.assertEqual(
            result["paired_effects"]["parallel_seconds_saved"]["median"],
            3.5,
        )
        self.assertEqual(
            result["paired_effects"]["pruning_seconds_saved"]["median"],
            2.5,
        )
        self.assertEqual(
            result["paired_effects"]["parallel_by_pruning_interaction_seconds"]["median"],
            1.0,
        )

    def test_factorial_summary_partitions_mixed_fixtures(self):
        records = []
        for fixture in ("parallel-speed", "pruning-amplifier"):
            records.append({
                "fixture": fixture,
                "block": 1,
                "variant": {"name": "serial-naive", "parallel": 1, "pruning": False},
                "success": True,
                "duration_seconds": 1.0,
                "attempted": 1,
                "preflight_calls": 1,
                "excluded_by_constraints": 0,
                "acceptance_checks": {"verified_success": True},
            })
        result = summarize_factorial(records)
        self.assertEqual(set(result["fixtures"]), {
            "parallel-speed", "pruning-amplifier"
        })
        self.assertTrue(
            result["fixtures"]["parallel-speed"]["acceptance_checks"]["all_verified"]
        )

    def test_no_learning_graph_drops_edges(self):
        graph = NoLearningConstraintGraph()
        self.assertEqual(graph.load_all(), [])
        self.assertEqual(graph.insert([{"pkg_a": "a", "pkg_b": "b"}]), 0)
        self.assertEqual(graph.infer_transitive(), 0)
        graph.close()

    def test_serial_mode_restores_environment(self):
        key = "MINIOPENCLAW_PACS_SERIAL"
        previous = os.environ.get(key)
        try:
            os.environ[key] = "original"
            with _serial_mode(True):
                self.assertEqual(os.environ[key], "1")
            self.assertEqual(os.environ[key], "original")
            with _serial_mode(False):
                self.assertNotIn(key, os.environ)
            self.assertEqual(os.environ[key], "original")
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

    def test_real_pip_error_is_structured(self):
        text = """
ERROR: Cannot install demo-core==2.0.0 and demo-plugin==1.0.0 because these package versions have conflicting dependencies.
The conflict is caused by:
    demo-plugin 1.0.0 depends on demo-core<2
"""
        failures = parse_failure(text)
        self.assertEqual(failures[0]["error_type"], "version_conflict")
        self.assertTrue(failures[0]["constraints"])


if __name__ == "__main__":
    unittest.main()
