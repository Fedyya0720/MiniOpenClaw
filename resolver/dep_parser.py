"""Parse Python dependency declarations without third-party packages."""
from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DepSpec:
    name: str
    specifier: str = ""
    marker: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


_DEP_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^]]+\])?\s*(.*)$")


def _parse_line(line: str, source: str) -> DepSpec | None:
    clean = line.strip()
    if not clean or clean.startswith("#") or clean.startswith(("-r", "--requirement", "-c", "--constraint")):
        return None
    clean = re.split(r"\s+#", clean, maxsplit=1)[0].strip()
    requirement, _, marker = clean.partition(";")
    match = _DEP_RE.match(requirement)
    if not match:
        return None
    name, specifier = match.groups()
    specifier = specifier.strip()
    if specifier.startswith("(") and specifier.endswith(")"):
        specifier = specifier[1:-1].strip()
    if not specifier.startswith("@"):
        specifier = specifier.replace(" ", "")
    return DepSpec(name=name, specifier=specifier, marker=marker.strip(), source=source)


def _requirements(path: Path) -> list[DepSpec]:
    return [dep for line in path.read_text(encoding="utf-8").splitlines() if (dep := _parse_line(line, str(path)))]


def _pyproject(path: Path) -> list[DepSpec]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    raw = data.get("project", {}).get("dependencies", [])
    if not isinstance(raw, list):
        raise ValueError("pyproject.toml 的 project.dependencies 必须是数组")
    return [dep for item in raw if isinstance(item, str) and (dep := _parse_line(item, str(path)))]


def parse_dependencies(project_path: str | Path) -> list[DepSpec]:
    path = Path(project_path).expanduser()
    if path.is_file():
        if path.name == "pyproject.toml":
            return _pyproject(path)
        return _requirements(path)
    if not path.exists():
        raise FileNotFoundError(f"路径不存在：{path}")
    for name, parser in (("requirements.txt", _requirements), ("pyproject.toml", _pyproject)):
        candidate = path / name
        if candidate.exists():
            return parser(candidate)
    raise FileNotFoundError(f"未在 {path} 找到 requirements.txt 或 pyproject.toml")
