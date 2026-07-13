import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from envpool.install import parallel_install
from envpool.manager import EnvironmentPool
from pacs import PACSBuilder
from resolver.combinations import generate_combinations
from resolver.constraint_graph import ConstraintGraph
from resolver.dep_parser import parse_dependencies
from resolver.failure_parser import RULES, parse_failure
from resolver.version_index import VersionIndex
from skills.loader import load_skills
from tools.base import build_default_registry
from tools.resolver_tools import generate_candidates, parse_deps
from tools.skill_tools import skill_read


def _wheel(wheelhouse: Path, distribution: str, version: str, requires=()) -> Path:
    normalized = distribution.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    filename = wheelhouse / f"{normalized}-{version}-py3-none-any.whl"
    files = {
        f"{normalized}/__init__.py": f"__version__ = {version!r}\n".encode(),
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {distribution}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {item}\n" for item in requires)
            + "\n"
        ).encode(),
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: pacs-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    records = []
    for path, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        records.append(f"{path},sha256={digest},{len(content)}")
    records.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(records) + "\n").encode()
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return filename


class DependencyParserTests(unittest.TestCase):
    def test_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text("torch>=2.0,<3.0\nnumpy==1.26.4 ; python_version >= '3.10'\n", encoding="utf-8")
            deps = parse_dependencies(directory)
            self.assertEqual(deps[0].as_dict()["specifier"], ">=2.0,<3.0")
            self.assertEqual(deps[1].name, "numpy")
            self.assertIn("python_version", deps[1].marker)

    def test_pyproject(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pyproject.toml"
            path.write_text('[project]\ndependencies = ["httpx>=0.27", "rich==13.7.0"]\n', encoding="utf-8")
            self.assertEqual([d.name for d in parse_dependencies(path)], ["httpx", "rich"])

    def test_parenthesized_and_direct_reference_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pyproject.toml"
            path.write_text(
                '[project]\ndependencies = ["build (>=1.2,<2)", "core @ git+https://example.test/core.git"]\n',
                encoding="utf-8",
            )
            deps = parse_dependencies(path)
            self.assertEqual(deps[0].specifier, ">=1.2,<2")
            self.assertEqual(deps[1].specifier, "@ git+https://example.test/core.git")

    def test_missing_dependency_file_is_a_tool_error(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn("error", json.loads(parse_deps(directory)))


class CombinationTests(unittest.TestCase):
    def test_limit_and_lower_bound_candidates(self):
        combos = generate_combinations([{"name": "torch", "specifier": ">=2.0,<3.0"}], max_candidates=3)
        self.assertEqual(len(combos), 3)
        self.assertEqual([item["torch"] for item in combos], ["2.0", "2.0.1", "2.1.0"])

    def test_conflicting_pair_is_pruned(self):
        deps = [{"name": "torch", "specifier": "==2.0"}, {"name": "numpy", "specifier": "==2.0"}]
        conflict = [{"pkg_a": "torch", "ver_a": "==2.0", "pkg_b": "numpy", "ver_b": "==2.0"}]
        self.assertEqual(generate_combinations(deps, conflict), [])
        self.assertEqual(json.loads(generate_candidates(deps, conflict, 1)), [])

    def test_transient_failures_do_not_poison_candidates(self):
        deps = [{"name": "a", "specifier": "==1"}, {"name": "b", "specifier": "==2"}]
        transient = [{"pkg_a": "a", "ver_a": "==1", "pkg_b": "b", "ver_b": "==2", "error_type": "network_timeout"}]
        self.assertEqual(generate_combinations(deps, transient), [{"a": "1", "b": "2"}])

    def test_real_catalog_replaces_guessed_versions(self):
        combos = generate_combinations(
            [{"name": "demo", "specifier": ">=1,<3"}], max_candidates=5,
            version_catalog={"demo": ["0.9", "1.4", "2.7", "3.0"]}, newest_first=True,
        )
        self.assertEqual(combos, [{"demo": "2.7"}, {"demo": "1.4"}])


class VersionIndexTests(unittest.TestCase):
    def test_exact_pin_needs_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            index = VersionIndex(Path(directory) / "cache.json")
            self.assertEqual(index.versions("anything", "==1.2.3"), ["1.2.3"])
            self.assertEqual(index.versions("core", "@ git+https://example.test/core.git"), ["@ git+https://example.test/core.git"])

    @patch("resolver.version_index.urllib.request.urlopen")
    def test_yanked_releases_are_excluded(self, urlopen):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"releases": {
                    "1.0": [{"yanked": True}],
                    "1.1": [{"yanked": False}],
                }}).encode()
        urlopen.return_value = Response()
        with tempfile.TemporaryDirectory() as directory:
            versions = VersionIndex(Path(directory) / "cache.json").versions("demo", ">=1")
        self.assertEqual(versions, ["1.1"])


class FailureParserTests(unittest.TestCase):
    def test_at_least_fifteen_rules_and_unknown_fallback(self):
        self.assertGreaterEqual(len(RULES), 15)
        combo = {"torch": "2.0", "numpy": "2.0"}
        for pattern, error_type, _ in RULES:
            # Each rule is independently reachable using a representative phrase.
            samples = {
                "dependency_conflict": "ResolutionImpossible: conflicting dependencies",
                "installed_version_conflict": "foo requires bar<2 but you have bar 2",
                "no_matching_distribution": "No matching distribution found for foo",
                "version_unavailable": "Could not find a version that satisfies foo",
                "python_version_mismatch": "Requires-Python >=3.12",
                "wheel_incompatible": "not a supported wheel on this platform",
                "invalid_wheel": "wheel package is invalid",
                "wheel_build_failed": "Failed building wheel for foo",
                "metadata_generation_failed": "metadata-generation-failed",
                "build_subprocess_failed": "subprocess-exited-with-error",
                "compiler_missing": "gcc not found",
                "system_library_missing": "fatal error: ssl.h: No such file",
                "cuda_incompatible": "CUDA version mismatch",
                "certificate_error": "SSL: CERTIFICATE_VERIFY_FAILED",
                "network_dns_error": "Temporary failure in name resolution",
                "network_timeout": "Connection timed out",
                "permission_error": "Permission denied",
                "disk_full": "No space left on device",
                "hash_mismatch": "hash mismatch",
                "externally_managed": "externally-managed-environment",
            }
            parsed = parse_failure(samples[error_type], combo)
            self.assertIn(error_type, {item["error_type"] for item in parsed}, pattern)
            self.assertTrue(all("pkg_a" in item and "confidence" in item for item in parsed))
        self.assertEqual(parse_failure("unclassified failure")[0]["error_type"], "unknown")


class ConstraintGraphTests(unittest.TestCase):
    def test_persistence_and_transitive_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "constraints.db"
            graph = ConstraintGraph(db)
            graph.add([
                {"pkg_a": "A", "ver_a": "==1", "pkg_b": "B", "ver_b": "==2", "confidence": .9},
                {"pkg_a": "B", "ver_a": "==2", "pkg_b": "C", "ver_b": "==3", "confidence": .8},
                {"pkg_a": "C", "ver_a": "==3", "pkg_b": "D", "ver_b": "==4", "confidence": .7},
            ])
            graph.infer()
            related = ConstraintGraph(db).related("A")
            self.assertTrue(any(edge["pkg_b"] == "C" and edge["inferred"] for edge in related))
            self.assertTrue(any(edge["pkg_b"] == "D" and edge["inferred"] for edge in related))

    def test_prune(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = ConstraintGraph(Path(directory) / "constraints.db")
            graph.add([{"pkg_a": "A", "ver_a": "==1", "pkg_b": "B", "ver_b": "==2"}])
            candidates = [{"A": "1", "B": "2"}, {"A": "1", "B": "3"}]
            self.assertEqual(graph.prune(candidates), [{"A": "1", "B": "3"}])


class EnvironmentPoolTests(unittest.TestCase):
    def test_create_isolated_status_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = EnvironmentPool(Path(directory) / "pool")
            first = pool.create(label="one")
            second = pool.create(label="two")
            self.assertEqual(first.status, "idle")
            self.assertNotEqual(first.path, second.path)
            self.assertTrue(first.python.exists())
            self.assertEqual(len(pool.list()), 2)
            pool.cleanup(first.id)
            self.assertFalse(Path(first.path).exists())
            pool.cleanup()
            self.assertEqual(pool.list(), [])

    def test_parallel_result_shape_and_timeout_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = EnvironmentPool(Path(directory) / "pool")
            envs = [pool.create(label="one"), pool.create(label="two")]
            ok = subprocess.CompletedProcess([], 0, "ok", "")
            timeout = subprocess.TimeoutExpired([], 0.01)
            with patch("envpool.install.subprocess.run", side_effect=[timeout, ok]):
                results = parallel_install(envs, [["a"], ["b"]], timeout=.01)
            self.assertEqual({result.status for result in results}, {"ok", "timeout"})
            for result in results:
                self.assertEqual(set(result.as_dict()), {"env_id", "status", "stdout", "stderr", "returncode"})
            pool.cleanup()


class IntegrationTests(unittest.TestCase):
    def test_registry_contains_pacs_tools_returning_strings(self):
        registry = build_default_registry()
        names = {
            "env_create", "env_run", "env_status", "env_cleanup",
            "parse_deps", "generate_combinations", "parse_failure", "infer_constraints",
            "pacs_build",
        }
        self.assertTrue(names.issubset(registry.names()))
        self.assertIsInstance(registry.get("env_status").run(), str)
        self.assertIsInstance(registry.get("parse_failure").run(log_text="unknown"), str)

    def test_every_pacs_tool_returns_text(self):
        registry = build_default_registry()
        with tempfile.TemporaryDirectory() as directory, patch(
            "tools.env_tools._POOL", EnvironmentPool(Path(directory) / "pool")
        ):
            created = registry.get("env_create").run(label="tool-test")
            env_id = json.loads(created)["id"]
            calls = {
                "env_create": created,
                "env_run": registry.get("env_run").run(jobs=[]),
                "env_status": registry.get("env_status").run(env_id=env_id),
                "env_cleanup": registry.get("env_cleanup").run(env_id=env_id),
                "parse_deps": registry.get("parse_deps").run(project_path=directory),
                "generate_combinations": registry.get("generate_combinations").run(deps=[{"name": "x", "specifier": "==1"}]),
                "parse_failure": registry.get("parse_failure").run(log_text="unknown"),
                "infer_constraints": registry.get("infer_constraints").run(constraints=[], db_path=str(Path(directory) / "c.db")),
                "pacs_build": registry.get("pacs_build").run(project_path=directory),
            }
            self.assertTrue(all(isinstance(value, str) for value in calls.values()))

    def test_skill_is_discoverable(self):
        root = Path(__file__).parents[1] / "skills"
        self.assertIn("python-env-builder", {skill.name for skill in load_skills(str(root))})
        loaded = skill_read("python-env-builder", str(root))
        self.assertIn("pacs_build", loaded)
        self.assertIn("success=true", loaded)


class RealPIPWorkflowTests(unittest.TestCase):
    def test_two_real_pip_installs_run_as_one_parallel_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            wheelhouse = Path(directory) / "wheelhouse"
            wheelhouse.mkdir()
            package = _wheel(wheelhouse, "pacs-tiny", "1.0")
            pool = EnvironmentPool(Path(directory) / "pool")
            envs = [pool.create(label="parallel-1"), pool.create(label="parallel-2")]
            results = parallel_install(
                envs,
                [["--no-index", str(package)], ["--no-index", str(package)]],
                timeout=60,
                max_workers=2,
            )
            self.assertEqual([result.status for result in results], ["ok", "ok"])
            self.assertEqual({env.status for env in envs}, {"idle"})
            pool.cleanup()

    def test_failure_drives_next_real_candidate_then_locks_and_cleans(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            wheelhouse = Path(directory) / "wheelhouse"
            project.mkdir()
            wheelhouse.mkdir()
            _wheel(wheelhouse, "pacs-shared", "1.0")
            _wheel(wheelhouse, "pacs-shared", "2.0")
            _wheel(wheelhouse, "pacs-alpha", "1.0", ["pacs-shared==1.0"])
            _wheel(wheelhouse, "pacs-beta", "1.0", ["pacs-shared==2.0"])
            _wheel(wheelhouse, "pacs-beta", "2.0", ["pacs-shared==1.0"])
            (project / "requirements.txt").write_text(
                "pacs-alpha==1.0\npacs-beta>=1.0,<3.0\n", encoding="utf-8"
            )
            result = PACSBuilder(project).build(
                max_parallel=1,
                max_attempts=3,
                newest_first=False,
                version_catalog={"pacs-alpha": ["1.0"], "pacs-beta": ["1.0", "2.0"]},
                validation_modules=["pacs_alpha", "pacs_beta"],
                pip_args=["--no-index", "--find-links", str(wheelhouse)],
            )
            self.assertTrue(result.success, result.as_dict())
            self.assertEqual([a.status for a in result.attempts], ["fail", "ok"])
            self.assertIn("pacs-beta==2.0", Path(result.lock_path).read_text(encoding="utf-8"))
            self.assertIn("状态：成功", Path(result.report_path).read_text(encoding="utf-8"))
            env_dirs = list((project / ".miniopenclaw/pacs/envs").iterdir())
            self.assertEqual([path.resolve() for path in env_dirs], [Path(result.environment_path).resolve()])
            self.assertGreaterEqual(len(ConstraintGraph(result.constraint_db).all()), 1)


if __name__ == "__main__":
    unittest.main()
