# envpool

Phase 1 provides a restart-safe virtual-environment pool rooted at
`<workdir>/.miniopenclaw_envs`, argv-only installer execution, and serial or
`ThreadPoolExecutor` installation.

## Design

- Each environment has an `env.json` manifest; status is reconstructed by
  scanning manifests after restart.
- Environment IDs are restricted and every create/status/cleanup path is
  checked against the fixed pool root. Symlinked roots and environments are
  rejected.
- `InstallSpec` accepts either package names or a validated installer argv,
  never shell text. Custom argv must invoke the target venv's Python/pip and
  use the install form; a narrowly scoped test mode permits `python -c`.
- Full stdout/stderr is stored in a durable PACS log under
  `<workdir>/.mini-openclaw/pacs-runs/<batch-id>/<index>-<safe-env>.log`; returned
  summaries are compact. Logs survive `env_cleanup`, including timeout cases.
- One install call uses one `batch_id`, returned both for the batch and every result.
  Results expose original/stored character and UTF-8 byte counts, SHA-256 hashes, and
  redaction state for the durable log.
- PACS logs redact likely credentials by default (secret-named fields/assignments,
  Bearer/Basic values, and URL credentials). Set `MINIOPENCLAW_TRACE_SENSITIVE=1`
  only for an intentional forensic investigation to retain exact sensitive content;
  this warning state is returned and is never enabled automatically.
- PACS log directories/files use best-effort `0700`/`0600` permissions. There is no
  automatic retention cleanup: remove `.mini-openclaw/pacs-runs/` manually under your
  retention policy.

## Sandbox boundary

When `bwrap` exists **and passes a capability probe**, the host root and project are read-only, only the venv is writable, `/proc` and `/dev` are mounted, the child dies with its parent, and network remains enabled for package indexes. The project remains readable so local source/wheel installs work. A trusted argv-only `resource_runner.py` process applies POSIX CPU, memory, file-size, and process limits before `execvpe` starts the installer; this avoids `preexec_fn` in `ThreadPoolExecutor` workers and works both inside bwrap and in fallback mode. The parent launches the bwrap/runner process in its own session; timeouts terminate, then kill, that process group so installer descendants do not survive.

If bubblewrap is missing or installed but unusable (common inside nested containers with user namespaces disabled), execution falls back to resource limits only. Results explicitly set `filesystem_isolated=false` and include the probe failure in `warning`; the fallback must not be described as a sandbox. A post-launch fallback is permitted only for an anchored first-line bwrap launcher diagnostic (`bwrap: Creating new namespace failed:` or `bwrap: No permissions to create new namespace`); arbitrary installer stderr, including `operation not permitted`, never triggers a retry. Bwrap and fallback executions are recorded as separate attempts in the durable log. Set `MINIOPENCLAW_REQUIRE_PIP_SANDBOX=1` for fail-closed operation (including the rubric B4 malicious-package demonstration): absence or runtime failure of bubblewrap then rejects the install rather than running without filesystem isolation. This implementation reduces installer exposure but is not a boundary against a hostile kernel-level adversary.
