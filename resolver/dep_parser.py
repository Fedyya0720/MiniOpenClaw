"""Conservative dependency-file parsing without third-party packages."""
from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_SPEC = re.compile(r"^(===|==|!=|~=|>=|<=|>|<)(?!\s*$)\s*\S+$")
_INCLUDE = re.compile(r"^(?:-r|--requirement)(?:\s+|=)?(.+)$")
_EGG_NAME = re.compile(r"[#&]egg=([A-Za-z0-9][A-Za-z0-9._-]*)")
_DIRECT_URL = ("git+", "http://", "https://", "file:")


@dataclass(frozen=True)
class DepSpec:
    name: str
    specifier: str = ""
    extras: list[str] = field(default_factory=list)
    marker: str | None = None
    source: str = ""
    raw: str = ""
    direct_reference: str | None = None
    non_searchable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strip_inline_comment(value: str) -> str:
    return value.split(" #", 1)[0].strip()


def _direct_dependency(requirement: str, *, source: str, raw: str) -> DepSpec | None:
    """Parse named PEP 508 direct references and legacy VCS URLs with egg names."""
    core, separator, marker_text = requirement.partition(";")
    marker = marker_text.strip() if separator and marker_text.strip() else None
    if " @ " in core:
        name_part, reference = core.split(" @ ", 1)
        match = _NAME.fullmatch(name_part.strip())
        if match and reference.strip():
            return DepSpec(
                name=match.group(0), marker=marker, source=source, raw=raw,
                direct_reference=reference.strip(), non_searchable=True,
            )
    if core.startswith(_DIRECT_URL):
        egg = _EGG_NAME.search(core)
        if egg:
            return DepSpec(
                name=egg.group(1), marker=marker, source=source, raw=raw,
                direct_reference=core.strip(), non_searchable=True,
            )
    return None


def parse_requirement(value: str, *, source: str = "") -> DepSpec | None:
    """Parse a safe PEP-508 subset, preserving markers instead of evaluating them."""
    raw = value.strip()
    if not raw or raw.startswith("#") or raw.startswith("-"):
        return None
    requirement = _strip_inline_comment(raw)
    direct = _direct_dependency(requirement, source=source, raw=raw)
    if direct is not None:
        return direct
    core, separator, marker_text = requirement.partition(";")
    marker = marker_text.strip() if separator and marker_text.strip() else None
    match = _NAME.match(core.strip())
    if not match:
        return None
    name = match.group(0)
    rest = core[match.end():].strip()
    extras: list[str] = []
    if rest.startswith("["):
        closing = rest.find("]")
        if closing < 0:
            return None
        extras = [item.strip() for item in rest[1:closing].split(",") if item.strip()]
        if not all(_NAME.fullmatch(item) for item in extras):
            return None
        rest = rest[closing + 1:].strip()
    # PEP 508 permits the legacy parenthesized form used by Poetry projects,
    # e.g. ``build (>=1.2,<2)``.
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1].strip()
    specifier = rest.replace(" ", "")
    if specifier and not all(_SPEC.fullmatch(part) for part in specifier.split(",") if part):
        return None
    return DepSpec(
        name=name,
        specifier=specifier,
        extras=extras,
        marker=marker,
        source=source,
        raw=raw,
    )


def _warning(warnings: list[dict[str, Any]], source: Path, line: int, raw: str, reason: str) -> None:
    warnings.append({"source": str(source), "line": line, "raw": raw, "reason": reason})


def _included_path(value: str, current: Path, root: Path) -> Path:
    include = value.strip().strip("'\"")
    if not include:
        raise ValueError("requirement include 不能为空")
    candidate = (current.parent / include).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"requirement include 越过项目根目录: {include}")
    return candidate


def parse_requirements(
    path: str | Path,
    *,
    root: str | Path | None = None,
    warnings: list[dict[str, Any]] | None = None,
    files: list[str] | None = None,
    _active: set[Path] | None = None,
) -> list[DepSpec]:
    """Recursively parse ``-r`` / ``--requirement`` files below a trusted root.

    Standalone parsing trusts the top-level file's parent. ``parse_project``
    supplies its project directory, so included files cannot escape that project.
    """
    file_path = Path(path).expanduser().resolve()
    include_root = Path(root).expanduser().resolve() if root is not None else file_path.parent
    if not file_path.is_relative_to(include_root):
        raise ValueError(f"requirements 文件越过项目根目录: {file_path}")
    warnings = warnings if warnings is not None else []
    files = files if files is not None else []
    active = _active if _active is not None else set()
    if file_path in active:
        raise ValueError(f"检测到 requirements include 循环: {file_path}")
    if not file_path.is_file():
        raise FileNotFoundError(f"requirements include 不存在: {file_path}")
    if str(file_path) not in files:
        files.append(str(file_path))
    active.add(file_path)
    dependencies: list[DepSpec] = []
    try:
        for line_number, original in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            raw = original.strip()
            if not raw or raw.startswith("#"):
                continue
            include = _INCLUDE.fullmatch(raw)
            if include:
                try:
                    dependencies.extend(parse_requirements(
                        _included_path(include.group(1), file_path, include_root),
                        root=include_root, warnings=warnings, files=files, _active=active,
                    ))
                except (FileNotFoundError, ValueError) as error:
                    _warning(warnings, file_path, line_number, raw, str(error))
                continue
            if raw.startswith("-"):
                _warning(warnings, file_path, line_number, raw, "不支持的 pip 选项")
                continue
            dependency = parse_requirement(raw, source=str(file_path))
            if dependency is None:
                _warning(warnings, file_path, line_number, raw, "不支持的 requirement 语法")
            else:
                dependencies.append(dependency)
    finally:
        active.remove(file_path)
    return dependencies


def parse_pyproject(path: str | Path) -> list[DepSpec]:
    file_path = Path(path).expanduser().resolve()
    with file_path.open("rb") as handle:
        data = tomllib.load(handle)
    values = data.get("project", {}).get("dependencies", [])
    if not isinstance(values, list):
        raise ValueError("pyproject.toml 的 project.dependencies 必须是数组")
    return [
        dependency
        for value in values
        if isinstance(value, str)
        and (dependency := parse_requirement(value, source=str(file_path))) is not None
    ]


def _environment_lines(lines: Iterable[str]) -> tuple[list[str], list[str], dict[str, str]]:
    """Read the common environment.yml subset: dependencies and nested pip list."""
    conda: list[str] = []
    pip: list[str] = []
    hints: dict[str, str] = {}
    in_dependencies = False
    dependency_indent = 0
    in_pip = False
    pip_indent = 0
    for original in lines:
        if not original.strip() or original.lstrip().startswith("#"):
            continue
        indent = len(original) - len(original.lstrip(" "))
        text = original.strip()
        if indent == 0:
            in_pip = False
            if text == "dependencies:":
                in_dependencies = True
                dependency_indent = indent
                continue
            in_dependencies = False
            if ":" in text:
                key, value = text.split(":", 1)
                if key in {"name", "prefix"} and value.strip():
                    hints[key] = value.strip().strip("'\"")
            continue
        if not in_dependencies or indent <= dependency_indent or not text.startswith("-"):
            continue
        item = text[1:].strip()
        if item == "pip:":
            in_pip = True
            pip_indent = indent
            continue
        if in_pip and indent > pip_indent:
            pip.append(item)
        else:
            in_pip = False
            conda.append(item)
    return conda, pip, hints


def _conda_to_requirement(value: str) -> str:
    """Translate simple conda ``name=version`` pins to PEP-508 equality."""
    item = value.split("::", 1)[-1]
    if item.count("=") == 1 and not any(operator in item for operator in (">=", "<=", "!=", "==", "~=", "===")):
        name, version = item.split("=", 1)
        return f"{name}=={version}"
    return item


def parse_environment(path: str | Path) -> tuple[list[DepSpec], dict[str, Any]]:
    file_path = Path(path).expanduser().resolve()
    conda_values, pip_values, hints = _environment_lines(
        file_path.read_text(encoding="utf-8").splitlines()
    )
    dependencies: list[DepSpec] = []
    for value in conda_values:
        dependency = parse_requirement(_conda_to_requirement(value), source=f"{file_path}:conda")
        if dependency is not None:
            dependencies.append(dependency)
    for value in pip_values:
        dependency = parse_requirement(value, source=f"{file_path}:pip")
        if dependency is not None:
            dependencies.append(dependency)
    metadata = {"format": "conda-environment", "conda_hints": hints, "pip_count": len(pip_values)}
    return dependencies, metadata


def _deduplicate(dependencies: Iterable[DepSpec]) -> list[DepSpec]:
    """Keep the first occurrence of each normalized dependency declaration."""
    unique: list[DepSpec] = []
    seen: set[tuple[Any, ...]] = set()
    for dependency in dependencies:
        key = (
            dependency.name.lower(), tuple(item.lower() for item in dependency.extras),
            dependency.specifier, dependency.marker, dependency.direct_reference,
        )
        if key not in seen:
            seen.add(key)
            unique.append(dependency)
    return unique


def parse_project(project_path: str | Path) -> dict[str, Any]:
    """Parse a dependency file or discover supported files in a project directory."""
    target = Path(project_path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"项目或依赖文件不存在: {target}")
    project_root = target.parent if target.is_file() else target
    dependencies: list[DepSpec] = []
    metadata: dict[str, Any] = {"project_path": str(target), "files": [], "warnings": []}
    files = [target] if target.is_file() else [
        candidate for name in ("requirements.txt", "pyproject.toml", "environment.yml", "environment.yaml")
        if (candidate := target / name).is_file()
    ]
    if not files:
        raise FileNotFoundError(f"未找到支持的依赖文件: {target}")
    for file_path in files:
        if file_path.name == "requirements.txt":
            dependencies.extend(parse_requirements(
                file_path, root=project_root, warnings=metadata["warnings"], files=metadata["files"],
            ))
        else:
            metadata["files"].append(str(file_path))
            if file_path.name == "pyproject.toml":
                with file_path.open("rb") as handle:
                    project_data = tomllib.load(handle).get("project", {})
                if isinstance(project_data, dict) and project_data.get("requires-python"):
                    metadata["requires_python"] = str(project_data["requires-python"])
                dependencies.extend(parse_pyproject(file_path))
            elif file_path.name in {"environment.yml", "environment.yaml"}:
                parsed, environment_metadata = parse_environment(file_path)
                dependencies.extend(parsed)
                metadata["environment"] = environment_metadata
            else:
                raise ValueError(f"不支持的依赖文件: {file_path.name}")
    dependencies = _deduplicate(dependencies)
    return {"dependencies": [dependency.to_dict() for dependency in dependencies], "metadata": metadata}
