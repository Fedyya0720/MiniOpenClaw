"""Focused tests for the fast high-level PACS demo path."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent.permissions import check
from pacs import PACSBuilder
from resolver.scoring import score_candidates
from resolver.solver import solve_candidates
from resolver.version_index import VersionIndex
from tools.base import build_default_registry
from skills.loader import load_skills


_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "demo" / "pacs_demo" / "make_fixture.py"
_SPEC = importlib.util.spec_from_file_location("pacs_demo_fixture", _FIXTURE_PATH)
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


class SolverAndScoringTests(unittest.TestCase):
    def test_pypi_catalog_queries_overlap_and_retry_transient_error(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "releases": {
                        "1.0.0": [{
                            "yanked": False,
                            "filename": "demo-1.0.0-py3-none-any.whl",
                            "requires_python": ">=3.9",
                        }]
                    }
                }).encode()

        with tempfile.TemporaryDirectory() as directory:
            index = VersionIndex(
                Path(directory) / "versions.json",
                max_retries=1,
                max_workers=2,
            )
            lock = threading.Lock()
            active = 0
            max_active = 0
            calls = 0

            def urlopen(*_args, **_kwargs):
                nonlocal active, max_active, calls
                with lock:
                    calls += 1
                    current = calls
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.1)
                with lock:
                    active -= 1
                if current == 1:
                    raise urllib.error.URLError("transient")
                return Response()

            with mock.patch("resolver.version_index.urllib.request.urlopen", side_effect=urlopen):
                catalog = index.catalog([
                    {"name": "alpha", "specifier": ">=1"},
                    {"name": "beta", "specifier": ">=1"},
                ])
            self.assertEqual(catalog["versions"], {"alpha": ["1.0.0"], "beta": ["1.0.0"]})
            self.assertEqual(calls, 3)
            self.assertEqual(max_active, 2)

    def test_injected_and_exact_version_catalogs_are_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            index = VersionIndex(Path(directory) / "versions.json", top_k=2)
            with mock.patch("resolver.version_index.urllib.request.urlopen", side_effect=AssertionError):
                exact, _, source, _ = index.versions("demo", "==1.2.3")
            self.assertEqual(exact, ["1.2.3"])
            self.assertEqual(source, "exact")
            catalog = index.catalog(
                [{"name": "demo", "specifier": ">=0,<3"}],
                injected={"demo": ["2.0.0", "1.0.0", "0.9.0"]},
            )
            self.assertEqual(catalog["versions"]["demo"], ["2.0.0", "1.0.0"])
            self.assertTrue(catalog["has_more"]["demo"])
            expanded = index.catalog(
                [{"name": "demo", "specifier": ">=0"}],
                injected={"demo": ["2.0.0", "1.0.0", "0.9.0"]},
                limit=3,
            )
            self.assertEqual(expanded["versions"]["demo"], ["2.0.0", "1.0.0", "0.9.0"])
            self.assertFalse(expanded["has_more"]["demo"])

    def test_solver_prunes_observed_pair_and_scores_newest_first(self):
        catalog = {"core": ["2.0.0", "1.0.0"], "plugin": ["1.0.0"]}
        solved = solve_candidates(catalog, [{
            "pkg_a": "core", "ver_a": "2.0.0", "pkg_b": "plugin", "ver_b": "1.0.0",
            "kind": "observed", "confidence": 0.9,
        }])
        self.assertEqual(solved["combinations"], [{"core": "1.0.0", "plugin": "1.0.0"}])

        scored = score_candidates(
            [{"core": "1.0.0"}, {"core": "2.0.0"}], catalog,
            {"core": {"1.0.0": {"has_wheel": True}, "2.0.0": {"has_wheel": True}}},
        )
        self.assertEqual(scored[0]["combination"]["core"], "2.0.0")
        self.assertIn("freshness", scored[0]["score_parts"])


class ToolIntegrationTests(unittest.TestCase):
    def test_builtin_skills_load_outside_repository_cwd(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "pathlib.Path.cwd", return_value=Path(directory)
        ):
            self.assertIn("python-env-builder", [skill.name for skill in load_skills()])

    def test_high_level_tool_registered_and_confined(self):
        self.assertIn("pacs_build", build_default_registry().names())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(check("pacs_build", {"project_path": "."}, root), "confirm")
            self.assertEqual(check("pacs_build", {"project_path": "/etc"}, root), "deny")


class RealPipDemoTests(unittest.TestCase):
    @staticmethod
    def _successful_install(_pool, specs, **_kwargs):
        return SimpleNamespace(results=[SimpleNamespace(
            success=True,
            cancelled=False,
            log_path="",
            sandbox={"kind": "test"},
        ) for _ in specs])

    def test_builder_parallel_preflight_fills_one_install_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "parallel"
            project.mkdir()
            (project / "requirements.txt").write_text("demo-core>=1,<3\n", encoding="utf-8")
            lock = threading.Lock()
            active = 0
            max_active = 0
            installed_count = 0

            def overlapping_preflight(*_args, **_kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.2)
                with lock:
                    active -= 1
                return {"success": True, "stdout": "", "stderr": "", "resolved": []}

            def successful_install(pool, specs, **kwargs):
                nonlocal installed_count
                installed_count = len(specs)
                self.assertEqual(kwargs["max_workers"], 2)
                return self._successful_install(pool, specs, **kwargs)

            with mock.patch("pacs.builder.preflight", side_effect=overlapping_preflight), \
                 mock.patch("pacs.builder.install_for_environment", side_effect=successful_install):
                result = PACSBuilder(project).build(
                    max_parallel=2,
                    max_attempts=2,
                    version_catalog={"demo-core": ["2.0.0", "1.0.0"]},
                )
            self.assertTrue(result["success"], result)
            self.assertEqual(max_active, 2, "Builder preflight did not overlap")
            self.assertEqual(installed_count, 2, "Builder did not submit a full parallel batch")

    def test_builder_expands_to_older_versions_after_window_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "old-project"
            project.mkdir()
            (project / "requirements.txt").write_text("demo-core>=0\n", encoding="utf-8")

            def old_only_preflight(packages, **_kwargs):
                success = any(str(package).endswith("==0.5.0") for package in packages)
                return {
                    "success": success,
                    "stdout": "" if success else "old project compatibility failure",
                    "stderr": "",
                    "resolved": [],
                }

            with mock.patch("pacs.builder.preflight", side_effect=old_only_preflight), \
                 mock.patch(
                     "pacs.builder.install_for_environment",
                     side_effect=self._successful_install,
                 ):
                result = PACSBuilder(project).build(
                    max_parallel=2,
                    max_attempts=6,
                    version_batch_size=5,
                    max_versions_per_package=10,
                    version_catalog={
                        "demo-core": [
                            "5.0.0", "4.0.0", "3.0.0", "2.0.0", "1.0.0", "0.5.0"
                        ]
                    },
                )
            self.assertTrue(result["success"], result)
            self.assertEqual(result["version_expansions"], 1)
            self.assertEqual(result["version_limit"], 10)
            successful = [item for item in result["attempts"] if item["status"] == "ok"]
            self.assertTrue(any(item["combination"]["demo-core"] == "0.5.0" for item in successful))

    def test_empty_dependency_project_still_returns_verified_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "empty"
            project.mkdir()
            (project / "requirements.txt").write_text("# no dependencies\n", encoding="utf-8")
            result = PACSBuilder(project).build(timeout=30)
            self.assertTrue(result["success"], result)
            self.assertEqual(result["attempted"], 1)
            self.assertTrue(Path(result["lock_path"]).is_file())

    def test_failure_learns_constraint_then_real_install_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _FIXTURE.create_fixture(Path(directory) / "fixture")
            catalog = json.loads(Path(fixture["catalog"]).read_text(encoding="utf-8"))
            result = PACSBuilder(fixture["project"]).build(
                max_parallel=2,
                max_attempts=4,
                timeout=30,
                version_catalog=catalog,
                validation_modules=["demo_core", "demo_plugin"],
                pip_args=["--no-index", "--find-links", fixture["wheelhouse"]],
            )
            self.assertTrue(result["success"], result)
            self.assertGreaterEqual(result["rounds"], 1)
            self.assertGreaterEqual(result["constraints_learned"], 1)
            self.assertTrue(Path(result["environment_path"]).is_dir())
            self.assertTrue(Path(result["lock_path"]).is_file())
            self.assertTrue(Path(result["report_path"]).is_file())
            failed = [item for item in result["attempts"] if item["status"] == "failed"]
            self.assertTrue(failed)
            remaining = list((Path(fixture["project"]) / ".miniopenclaw_envs").iterdir())
            self.assertEqual([path.name for path in remaining], [result["environment_id"]])
