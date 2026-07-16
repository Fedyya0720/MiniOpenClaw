# Workspace pollution evidence

During the 2026-07-16 Agent A/B trials, some model-issued `write`/`edit` calls resolved against the repository launch directory rather than the trial-local `/tmp` worktree. The affected files were preserved here instead of deleted.

## Restored tracked file

- `requirements.trial-overwrite.txt` is the trial-generated three-line replacement of repository-root `requirements.txt`.
- The tracked repository `requirements.txt` was restored from Git after this evidence copy was made.

## Moved untracked paths

- `_test_write.txt`
- `_verify_pkg/`
- `_verify_setup/`
- `env_verify/`
- `install_deps.py`
- `pip.conf`
- `requirements_install.txt`
- `run_pip_check.py`
- `setup.py`
- `test_location.txt`
- `validate_env.py`
- `verify.py`
- `verify_env.py`
- `verify_pkg/`
- `verify_setup.py`

Their contents and timestamps identify them as environment-installation or verification artifacts produced by the 2026-07-16 requests/urllib3/certifi trials. They are not used to compute the canonical metrics.

## Deliberately not moved

- repository-root `.verify_pkg/`
- repository-root `setup_verify.py`

These existed before the 2026-07-16 trial sequence and their ownership was not established, so they remain untouched.

## Experimental implication

The canonical trial environments, independent verification, raw Agent traces, and PACS results were stored under trial-local `/tmp` directories. Root-directory pollution does not supply the independent success evidence, but it reveals incomplete filesystem isolation in the evaluation harness and is retained as a limitation/evidence artifact.
