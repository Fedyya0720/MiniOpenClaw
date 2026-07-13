"""Discover released package versions through the PyPI JSON API."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .combinations import version_matches, version_sort_key


class VersionIndex:
    def __init__(self, cache_path: str | Path | None = None, base_url: str = "https://pypi.org/pypi") -> None:
        self.cache_path = Path(cache_path or ".miniopenclaw/version-index.json").expanduser().resolve()
        self.base_url = base_url.rstrip("/")
        self._cache = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def versions(self, package: str, specifier: str = "", refresh: bool = False) -> list[str]:
        if specifier.strip().startswith("@"):
            return [specifier.strip()]
        exact = re.fullmatch(r"\s*={2,3}\s*([^,;\s]+)\s*", specifier)
        if exact and "*" not in exact.group(1):
            return [exact.group(1)]
        key = package.lower().replace("_", "-")
        cached = self._cache.get(key, {})
        if not refresh and cached.get("versions"):
            versions = cached["versions"]
        else:
            url = f"{self.base_url}/{urllib.parse.quote(package)}/json"
            request = urllib.request.Request(url, headers={"User-Agent": "MiniOpenClaw-PACS/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.load(response)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if cached.get("versions"):
                    versions = cached["versions"]
                else:
                    raise RuntimeError(f"无法查询 {package} 的 PyPI 版本：{exc}") from exc
            else:
                versions = [
                    version
                    for version, files in payload.get("releases", {}).items()
                    if files and any(not bool(file.get("yanked", False)) for file in files)
                ]
                self._cache[key] = {"versions": versions, "updated_at": time.time()}
                self._save()
        stable = [version for version in versions if re.fullmatch(r"\d+(?:\.\d+)*", version)]
        return sorted(
            {version for version in stable if version_matches(version, specifier)},
            key=version_sort_key,
        )

    def catalog(self, deps: list[dict[str, str]], refresh: bool = False) -> dict[str, list[str]]:
        return {dep["name"]: self.versions(dep["name"], dep.get("specifier", ""), refresh) for dep in deps}
