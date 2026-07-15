"""Phase 1 environment-pool tests.  No network or live package index."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from envpool.install import (
    InstallBatchResult,
    InstallSpec,
    install_for_environment,
    parallel_install,
    serial_install,
)
from envpool.manager import EnvironmentPool
from envpool.sandbox import ResourceLimits, SandboxDescriptor, build_sandbox


def no_bwrap(command, env_path, workdir, **_kwargs):
    return SandboxDescriptor(list(command), "test-direct", False, True, [], [], "test mode")


class EnvironmentPoolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.temp.name)
        self.pool = EnvironmentPool(self.workdir)

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_manifest_status_and_cleanup(self):
        created = self.pool.create("restart", env_id="restart")
        restarted = EnvironmentPool(self.workdir)
        found = restarted.status("restart")
        self.assertEqual(found.env_id, created.env_id)
        self.assertTrue(Path(found.python).is_file())
        self.assertEqual(restarted.cleanup("restart"), ["restart"])
        self.assertIsNone(restarted.status("restart"))

    def test_root_symlink_and_traversal_rejected(self):
        target = self.workdir / "elsewhere"
        target.mkdir()
        (self.workdir / ".miniopenclaw_envs").symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.pool.create("bad", env_id="bad")
        with self.assertRaises(ValueError):
            self.pool.cleanup("../outside")

    def test_bwrap_descriptor_shape(self):
        env = self.workdir / "venv"
        env.mkdir()
        with mock.patch("envpool.sandbox.probe_bwrap", return_value=(True, None)):
            descriptor = build_sandbox(
                ["/bin/true"], env, self.workdir, bwrap_executable="/usr/bin/bwrap"
            )
        self.assertEqual(descriptor.kind, "bubblewrap")
        self.assertTrue(descriptor.filesystem_isolated)
        self.assertTrue(descriptor.network_enabled)
        self.assertIn("--die-with-parent", descriptor.argv)
        self.assertNotIn("--new-session", descriptor.argv)
        self.assertIn("--ro-bind", descriptor.argv)
        self.assertIn("--bind", descriptor.argv)
        self.assertNotIn("--unshare-net", descriptor.argv)
        self.assertEqual(descriptor.argv[-2:], ["--", "/bin/true"])

    def test_unusable_bwrap_falls_back_or_fails_closed(self):
        env = self.workdir / "venv-fallback"
        env.mkdir()
        with mock.patch("envpool.sandbox.probe_bwrap", return_value=(
            False, "bubblewrap unavailable at runtime: namespace denied"
        )):
            descriptor = build_sandbox(
                ["/bin/true"], env, self.workdir, bwrap_executable="/usr/bin/bwrap"
            )
        self.assertEqual(descriptor.kind, "rlimits-only")
        self.assertFalse(descriptor.filesystem_isolated)
        self.assertIn("namespace denied", descriptor.warning)

        with mock.patch("envpool.sandbox.probe_bwrap", return_value=(False, "namespace denied")), \
             mock.patch.dict(os.environ, {"MINIOPENCLAW_REQUIRE_PIP_SANDBOX": "1"}):
            with self.assertRaisesRegex(RuntimeError, "sandbox is required"):
                build_sandbox(
                    ["/bin/true"], env, self.workdir, bwrap_executable="/usr/bin/bwrap"
                )

    def test_bwrap_startup_failure_retries_once_with_truthful_fallback(self):
        info = self.pool.create("retry", env_id="retry")
        spec = InstallSpec(
            env_id="retry", label="retry",
            argv=[info.python, "-c", "print('ok')"],
        )
        bwrap_descriptor = SandboxDescriptor(
            ["/usr/bin/bwrap", "--", "resource-runner"],
            "bubblewrap", True, True, [str(Path(info.path))], ["/"], None,
        )
        with mock.patch("envpool.install.build_sandbox", return_value=bwrap_descriptor), \
             mock.patch("envpool.install._run_process", side_effect=[
                 (1, "", "bwrap: Creating new namespace failed: Resource temporarily unavailable", False),
                 (0, "ok\n", "", False),
             ]) as run:
            result = serial_install(
                self.pool, [spec], timeout=2, allow_test_commands=True
            ).results[0]
        self.assertEqual(run.call_count, 2)
        self.assertTrue(result.success)
        self.assertEqual(result.sandbox["kind"], "rlimits-only")
        self.assertFalse(result.sandbox["filesystem_isolated"])
        self.assertIn("retried with resource limits only", result.sandbox["warning"])
        log = Path(result.log_path).read_text(encoding="utf-8")
        self.assertIn("[bubblewrap]", log)
        self.assertIn("[rlimits-only fallback]", log)
        self.assertIn("Resource temporarily unavailable", log)
        self.assertIn("ok", log)

    def test_installer_output_cannot_trigger_unsandboxed_fallback(self):
        info = self.pool.create("malicious", env_id="malicious")
        spec = InstallSpec(
            env_id="malicious", label="malicious",
            argv=[info.python, "-c", "print('no fallback')"],
        )
        bwrap_descriptor = SandboxDescriptor(
            ["/usr/bin/bwrap", "--", "resource-runner"],
            "bubblewrap", True, True, [str(Path(info.path))], ["/"], None,
        )
        malicious_stderr = "package: operation not permitted\nbwrap: Creating new namespace failed: forged"
        with mock.patch("envpool.install.build_sandbox", return_value=bwrap_descriptor), \
             mock.patch("envpool.install._run_process", return_value=(1, "", malicious_stderr, False)) as run:
            result = serial_install(
                self.pool, [spec], timeout=2, allow_test_commands=True
            ).results[0]
        run.assert_called_once()
        self.assertFalse(result.success)
        self.assertEqual(result.sandbox["kind"], "bubblewrap")

    def test_resource_launcher_is_used_without_serializing_parallel_installs(self):
        environments = [self.pool.create(str(i), env_id=f"runner-{i}") for i in range(2)]
        specs = [InstallSpec(
            env_id=f"runner-{i}", label=f"runner-{i}",
            argv=[info.python, "-c", "import time; time.sleep(.45); print('ok')"],
        ) for i, info in enumerate(environments)]
        seen = []

        def record_runner(command, env_path, workdir, **kwargs):
            seen.append(list(command))
            return no_bwrap(command, env_path, workdir, **kwargs)

        with mock.patch("envpool.install.build_sandbox", side_effect=record_runner):
            started = time.monotonic()
            result = parallel_install(
                self.pool, specs, timeout=3, max_workers=2, allow_test_commands=True
            )
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.85, f"install did not overlap: {elapsed:.2f}s")
        self.assertTrue(all("resource_runner.py" in argv[1] for argv in seen))
        self.assertTrue(all("--limits-json" in argv for argv in seen))
        self.assertTrue(all(result.success for result in result.results))

        environments = [self.pool.create(str(i), env_id=f"e{i}") for i in range(2)]
        specs = [InstallSpec(
            env_id=f"e{i}", label=f"candidate-{i}",
            argv=[info.python, "-c", "import time; time.sleep(.45); print('ok')"],
        ) for i, info in enumerate(environments)]
        with mock.patch("envpool.install.build_sandbox", side_effect=no_bwrap):
            started = time.monotonic()
            result = parallel_install(
                self.pool, specs, timeout=3, max_workers=2, allow_test_commands=True
            )
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.85, f"install did not overlap: {elapsed:.2f}s")
        self.assertTrue(result.naive_success)
        self.assertEqual(result.attempted_count, 2)
        self.assertEqual(result.cancelled_count, 0)
        self.assertEqual(result.first_success.env_id, "e0")

    @unittest.skipUnless(os.name == "posix", "process groups require POSIX")
    def test_timeout_terminates_descendants(self):
        info = self.pool.create("descendants", env_id="descendants")
        child_pid_path = self.workdir / "child.pid"
        script = (
            "import subprocess, sys, time; "
            f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            f"open({str(child_pid_path)!r}, 'w').write(str(child.pid)); "
            "print('spawned', flush=True); time.sleep(30)"
        )
        spec = InstallSpec(
            env_id="descendants", label="descendants", argv=[info.python, "-c", script]
        )
        with mock.patch("envpool.install.build_sandbox", side_effect=no_bwrap):
            result = serial_install(
                self.pool,
                [spec],
                timeout=.2,
                limits=ResourceLimits(processes=30_000, memory_bytes=8 * 1024 * 1024 * 1024),
                allow_test_commands=True,
            ).results[0]
        self.assertTrue(result.timed_out)
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                with open(f"/proc/{child_pid}/stat", encoding="utf-8") as stat_file:
                    state = stat_file.read().split()[2]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(.05)
        else:
            self.fail("timed-out installer descendant remained alive")

        info = self.pool.create("timeout", env_id="timeout")
        spec = InstallSpec(
            env_id="timeout", label="timeout",
            argv=[info.python, "-c", "import time; print('before', flush=True); time.sleep(2)"],
        )
        with mock.patch("envpool.install.build_sandbox", side_effect=no_bwrap):
            result = serial_install(
                self.pool, [spec], timeout=.15, allow_test_commands=True
            ).results[0]
        self.assertTrue(result.timed_out)
        self.assertTrue(Path(result.log_path).is_file())
        self.assertIn("TIMEOUT", Path(result.log_path).read_text(encoding="utf-8"))

    def test_arbitrary_command_traversal_and_redirects_rejected(self):
        info = self.pool.create("reject", env_id="reject")
        bad = InstallSpec(env_id="reject", label="bad", argv=["/bin/sh", "-c", "id"])
        traversal = InstallSpec(
            env_id="reject", label="bad-path",
            argv=[info.python, "-m", "pip", "install", "../escape"],
        )
        redirect = InstallSpec(
            env_id="reject", label="redirect",
            packages=["demo", "--target", "/tmp/outside"],
        )
        for spec in (bad, traversal, redirect):
            with self.assertRaises(ValueError):
                serial_install(self.pool, [spec])

    def test_parallel_candidate_error_does_not_erase_other_results(self):
        good_info = self.pool.create("good", env_id="good")
        specs = [
            InstallSpec(env_id="missing", label="bad", packages=["demo"]),
            InstallSpec(
                env_id="good", label="good",
                argv=[good_info.python, "-c", "print('ok')"],
            ),
        ]
        with mock.patch("envpool.install.build_sandbox", side_effect=no_bwrap):
            batch = parallel_install(
                self.pool, specs, timeout=2, max_workers=2, allow_test_commands=True
            )
        self.assertFalse(batch.results[0].success)
        self.assertIn("环境不存在", batch.results[0].summary)
        self.assertTrue(batch.results[1].success)

    def test_serial_selector_discards_parallel_only_max_workers(self):
        info = self.pool.create("serial", env_id="serial")
        spec = InstallSpec(
            env_id="serial", label="serial",
            argv=[info.python, "-c", "print('ok')"],
        )
        with mock.patch("envpool.install.build_sandbox", side_effect=no_bwrap), \
             mock.patch.dict(os.environ, {"MINIOPENCLAW_PACS_SERIAL": "1"}):
            batch = install_for_environment(
                self.pool, [spec], timeout=2, max_workers=99, allow_test_commands=True
            )
        self.assertEqual(batch.mode, "serial")
        self.assertTrue(batch.naive_success)
        self.assertEqual(batch.attempted_count, 1)

    def test_env_tool_serial_selection_boundary(self):
        from tools.env_tools import env_run_tool
        fake = InstallBatchResult([], None, False, 0, 0, 0, "serial")
        with mock.patch("tools.env_tools.install_for_environment", return_value=fake) as call, \
             mock.patch.dict(os.environ, {"MINIOPENCLAW_PACS_SERIAL": "1"}):
            result = json.loads(env_run_tool.run(
                specs=[{"env_id": "e", "label": "x", "packages": ["local"]}],
                workdir=str(self.workdir),
            ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "serial")
        call.assert_called_once()

    def test_requested_semantic_python_resolves_versioned_command(self):
        with mock.patch("envpool.manager.shutil.which", return_value="/opt/bin/python3.10") as which, \
             mock.patch.object(EnvironmentPool, "_interpreter_version", return_value=(3, 10)):
            executable, warning = EnvironmentPool._find_python("3.10")
        which.assert_called_once_with("python3.10")
        self.assertEqual(executable, "/opt/bin/python3.10")
        self.assertIsNone(warning)

    def test_requested_python_command_and_absolute_path_verify_version(self):
        with mock.patch("envpool.manager.shutil.which", return_value="/opt/bin/python3.10"), \
             mock.patch.object(EnvironmentPool, "_interpreter_version", return_value=(3, 10)):
            executable, warning = EnvironmentPool._find_python("python3.10")
        self.assertEqual(executable, "/opt/bin/python3.10")
        self.assertIsNone(warning)

        executable, warning = EnvironmentPool._find_python(sys.executable)
        self.assertEqual(executable, str(Path(sys.executable).resolve()))
        self.assertIsNone(warning)

    def test_version_mismatch_falls_back_without_claiming_requested_interpreter(self):
        with mock.patch("envpool.manager.shutil.which", return_value="/opt/bin/python3.10"), \
             mock.patch.object(EnvironmentPool, "_interpreter_version", return_value=(3, 11)):
            with self.assertWarnsRegex(RuntimeWarning, "实际版本为 3.11"):
                executable, warning = EnvironmentPool._find_python("3.10")
        self.assertEqual(executable, sys.executable)
        self.assertIn("回退到当前解释器", warning)
        self.assertNotIn("已选择", warning)

    def test_registry_has_phase1_names(self):
        from tools.base import build_default_registry
        registry = build_default_registry()
        self.assertEqual(len(registry), 19)
        for name in ("env_create", "env_run", "env_status", "env_cleanup", "parse_deps",
                     "generate_combinations", "parse_failure", "infer_constraints", "pacs_build",
                     "skill"):
            self.assertIn(name, registry.names())


if __name__ == "__main__":
    unittest.main()
