"""Deterministic projects used only by the PACS ablation runners."""
from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def _deterministic_payload(size: int) -> bytes:
    """Return incompressible-looking, reproducible bytes without using randomness."""
    output = bytearray()
    counter = 0
    while len(output) < size:
        output.extend(hashlib.sha256(f"pacs-payload-{counter}".encode()).digest())
        counter += 1
    return bytes(output[:size])


def _build_eval_wheel(
    wheelhouse: Path,
    distribution: str,
    version: str,
    *,
    module_source: str | None = None,
    requires: tuple[str, ...] = (),
    payload_bytes: int = 0,
) -> Path:
    """Build a deterministic evaluation wheel with optional source and payload."""
    normalized = distribution.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    filename = wheelhouse / f"{normalized}-{version}-py3-none-any.whl"
    source = module_source if module_source is not None else f"__version__ = {version!r}\n"
    files = {
        f"{normalized}/__init__.py": source.encode(),
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {distribution}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {item}\n" for item in requires)
            + "\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: MiniOpenClaw-PACS-Eval\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    if payload_bytes:
        files[f"{normalized}/payload.bin"] = _deterministic_payload(payload_bytes)
    records = []
    for path, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        records.append(f"{path},sha256={digest},{len(content)}")
    records.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(records) + "\n").encode()
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_STORED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[path])
    return filename


def create_clean_project(root: str | Path) -> dict[str, Any]:
    """Create a tiny installable project with an independently verifiable CLI."""
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError(f"fixture root already exists: {root}")
    project = root / "project"
    package = project / "demo_clean"
    package.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "demo-clean"
version = "1.0.0"
dependencies = []
""",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        "def healthcheck():\n    return 'clean-environment-ok'\n",
        encoding="utf-8",
    )
    return {
        "kind": "clean",
        "project": str(project),
        "catalog": {},
        "pip_args": [],
        "validation_modules": ["demo_clean"],
        "smoke_code": "import demo_clean; assert demo_clean.healthcheck() == 'clean-environment-ok'",
    }


def create_real_package_conflict_project(root: str | Path) -> dict[str, Any]:
    """Create a small project whose candidates are real packages from PyPI."""
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError(f"fixture root already exists: {root}")
    project = root / "project"
    project.mkdir(parents=True)
    (project / "requirements.txt").write_text(
        "requests==2.25.0\nurllib3>=1.26,<3\ncertifi>=2023,<2026\n",
        encoding="utf-8",
    )
    catalog = {
        "requests": ["2.25.0"],
        "urllib3": ["2.0.0", "1.26.20"],
        "certifi": ["2025.1.31", "2024.12.14", "2023.11.17"],
    }
    catalog_path = root / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return {
        "kind": "real-conflict",
        "project": str(project),
        "catalog_path": str(catalog_path),
        "catalog": catalog,
        "pip_args": ["--progress-bar", "off"],
        "validation_modules": ["requests", "urllib3", "certifi"],
        "agent_hint": (
            "候选版本必须使用：requests=[2.25.0]，urllib3=[2.0.0,1.26.20]，"
            "certifi=[2025.1.31,2024.12.14,2023.11.17]。"
            f"catalog 文件位于 {catalog_path}。安装时传 --progress-bar off。"
        ),
        "smoke_code": (
            "import requests, urllib3, certifi; "
            "from importlib.metadata import version; "
            "assert version('requests') == '2.25.0'; "
            "assert version('urllib3') in {'2.0.0', '1.26.20'}; "
            "assert version('certifi') in {'2025.1.31', '2024.12.14', '2023.11.17'}; "
            "assert version('urllib3') == '1.26.20'"
        ),
    }


def create_parallel_speed_project(
    root: str | Path, *, payload_mib: float = 8.0
) -> dict[str, Any]:
    """Create four ordered installable candidates; only rank four imports cleanly."""
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError(f"fixture root already exists: {root}")
    project, wheelhouse = root / "project", root / "wheelhouse"
    project.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)
    payload_bytes = max(0, int(payload_mib * 1024 * 1024))
    versions = ["4.0.0", "3.0.0", "2.0.0", "1.0.0"]
    for rank, version in enumerate(versions, 1):
        source = (
            f"__version__ = {version!r}\n"
            + (f"raise RuntimeError('intentional health failure rank {rank}')\n" if rank < 4 else "def healthcheck():\n    return 'ok'\n")
        )
        _build_eval_wheel(
            wheelhouse, "speed-candidate", version,
            module_source=source, payload_bytes=payload_bytes,
        )
    (project / "requirements.txt").write_text("speed-candidate>=1,<=4\n", encoding="utf-8")
    catalog = {"speed-candidate": versions}
    return _write_catalog_fixture(root, project, wheelhouse, catalog, {
        "kind": "parallel-speed",
        "validation_modules": ["speed_candidate"],
        "smoke_code": (
            "import speed_candidate; "
            "assert speed_candidate.__version__ == '1.0.0'; "
            "assert speed_candidate.healthcheck() == 'ok'"
        ),
        "expected_winner_rank": 4,
        "stage_counts_expected": {"validation-failed": 3, "validation-ok": 1},
        "overlap_factor": 4,
        "payload_bytes": payload_bytes,
        "max_attempts": 4,
    })


def create_pruning_amplifier_project(
    root: str | Path, *, addon_count: int = 10
) -> dict[str, Any]:
    """Create one bad core/plugin exact pair repeated across many addon slices."""
    if addon_count < 1:
        raise ValueError("addon_count must be at least 1")
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError(f"fixture root already exists: {root}")
    project, wheelhouse = root / "project", root / "wheelhouse"
    project.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)
    _build_eval_wheel(wheelhouse, "amp-core", "1.0.0")
    _build_eval_wheel(wheelhouse, "amp-core", "2.0.0")
    _build_eval_wheel(wheelhouse, "amp-plugin", "1.0.0", requires=("amp-core (<2)",))
    addons = [f"{number}.0.0" for number in range(addon_count, 0, -1)]
    for version in addons:
        _build_eval_wheel(wheelhouse, "amp-addon", version)
    (project / "requirements.txt").write_text(
        f"amp-core>=1,<3\namp-plugin==1.0.0\namp-addon>=1,<={addon_count}\n",
        encoding="utf-8",
    )
    catalog = {
        "amp-core": ["2.0.0", "1.0.0"],
        "amp-plugin": ["1.0.0"],
        "amp-addon": addons,
    }
    return _write_catalog_fixture(root, project, wheelhouse, catalog, {
        "kind": "pruning-amplifier",
        "validation_modules": ["amp_core", "amp_plugin", "amp_addon"],
        "smoke_code": (
            "import amp_core, amp_plugin, amp_addon; "
            "assert amp_core.__version__ == '1.0.0'"
        ),
        "expected_excluded_by_constraints": addon_count,
        "overlap_factor": addon_count,
        # Naive search needs every bad slice plus one good candidate.
        "max_attempts": addon_count + 1,
    })


def _write_catalog_fixture(
    root: Path,
    project: Path,
    wheelhouse: Path,
    catalog: dict[str, list[str]],
    extra: dict[str, Any],
) -> dict[str, Any]:
    catalog_path = root / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    common = {
        "project": str(project),
        "wheelhouse": str(wheelhouse),
        "catalog_path": str(catalog_path),
        "catalog": catalog,
        "pip_args": ["--progress-bar", "off", "--no-index", "--find-links", str(wheelhouse)],
    }
    return {**common, **extra}


def create_conflict_project(root: str | Path) -> dict[str, Any]:
    """Create a real-pip conflict whose learned pair prunes an addon slice."""
    root = Path(root).resolve()
    if root.exists():
        raise FileExistsError(f"fixture root already exists: {root}")
    project = root / "project"
    wheelhouse = root / "wheelhouse"
    project.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)

    _build_eval_wheel(wheelhouse, "demo-core", "1.0.0")
    _build_eval_wheel(wheelhouse, "demo-core", "2.0.0")
    _build_eval_wheel(wheelhouse, "demo-plugin", "1.0.0", requires=("demo-core (<2)",))
    for version in ("1.0.0", "2.0.0", "3.0.0"):
        _build_eval_wheel(wheelhouse, "demo-addon", version)

    (project / "requirements.txt").write_text(
        "demo-core>=1,<3\ndemo-plugin==1.0.0\ndemo-addon>=1,<4\n",
        encoding="utf-8",
    )
    catalog = {
        "demo-core": ["2.0.0", "1.0.0"],
        "demo-plugin": ["1.0.0"],
        "demo-addon": ["3.0.0", "2.0.0", "1.0.0"],
    }
    catalog_path = root / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return {
        "kind": "conflict",
        "project": str(project),
        "wheelhouse": str(wheelhouse),
        "catalog_path": str(catalog_path),
        "catalog": catalog,
        "pip_args": [
            "--progress-bar", "off", "--no-index", "--find-links", str(wheelhouse)
        ],
        "validation_modules": ["demo_core", "demo_plugin", "demo_addon"],
        "agent_hint": (
            f"这是离线实验项目。调用安装工具时必须传 pip 参数 "
            f"--progress-bar off --no-index --find-links {wheelhouse}；"
            f"候选版本目录为 {catalog_path}。"
        ),
        "smoke_code": (
            "import demo_core, demo_plugin, demo_addon; "
            "assert tuple(map(int, demo_core.__version__.split('.'))) < (2, 0, 0)"
        ),
    }
