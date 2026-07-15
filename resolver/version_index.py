"""Small PyPI JSON version index with a persistent, injectable catalog."""
from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .specifier import Version, matches


_STABLE = re.compile(r"^\d+(?:\.\d+)*$")


class VersionIndex:
    """Discover a bounded version domain without coupling search to the network."""

    def __init__(
        self,
        cache_path: str | Path,
        *,
        base_url: str = "https://pypi.org/pypi",
        top_k: int = 5,
        timeout: float = 10.0,
        max_retries: int = 2,
        max_workers: int = 8,
    ) -> None:
        self.cache_path = Path(cache_path).expanduser().resolve()
        self.base_url = base_url.rstrip("/")
        self.top_k = max(1, int(top_k))
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.max_workers = max(1, int(max_workers))
        self._cache_lock = threading.Lock()
        self._cache = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        with self._cache_lock:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.cache_path)

    @staticmethod
    def _exact(specifier: str) -> str | None:
        match = re.fullmatch(r"\s*={2,3}\s*([^,;*\s]+)\s*", specifier or "")
        return match.group(1) if match else None

    @staticmethod
    def _python_matches(specifier: str | None) -> bool:
        if not specifier:
            return True
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        try:
            return matches(current, specifier)
        except ValueError:
            # PyPI may contain PEP 440 clauses outside MiniOpenClaw's conservative
            # subset. Let pip perform the authoritative check during preflight.
            return True

    def versions(
        self,
        package: str,
        specifier: str = "",
        *,
        refresh: bool = False,
        limit: int | None = None,
    ) -> tuple[list[str], dict[str, dict[str, Any]], str, list[str]]:
        cap = self.top_k if limit is None else max(1, int(limit))
        exact = self._exact(specifier)
        if exact:
            return [exact], {exact: {"has_wheel": False, "cached": True}}, "exact", []

        key = package.lower().replace("_", "-")
        cached = self._cache.get(key)
        warnings: list[str] = []
        source = "cache"
        if refresh or not isinstance(cached, dict) or not cached.get("versions"):
            url = f"{self.base_url}/{urllib.parse.quote(package, safe='')}/json"
            request = urllib.request.Request(url, headers={"User-Agent": "MiniOpenClaw-PACS/1.0"})
            payload: dict[str, Any] | None = None
            last_error: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        payload = json.load(response)
                    break
                except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        time.sleep(0.25 * (2 ** attempt))
            try:
                if payload is None:
                    raise RuntimeError(last_error or "unknown PyPI error")
                releases = payload.get("releases", {})
                metadata: dict[str, dict[str, Any]] = {}
                for version, files in releases.items():
                    if not _STABLE.fullmatch(version) or not isinstance(files, list) or not files:
                        continue
                    usable = [item for item in files if not bool(item.get("yanked", False))]
                    if not usable:
                        continue
                    python_ok = any(self._python_matches(item.get("requires_python")) for item in usable)
                    if not python_ok:
                        continue
                    metadata[version] = {
                        "has_wheel": any(str(item.get("filename", "")).endswith(".whl") for item in usable),
                        "cached": False,
                    }
                versions = sorted(metadata, key=Version, reverse=True)
                cached = {"versions": versions, "metadata": metadata, "updated_at": time.time()}
                with self._cache_lock:
                    self._cache[key] = cached
                self._save()
                source = "pypi-json"
            except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
                if not isinstance(cached, dict) or not cached.get("versions"):
                    raise RuntimeError(f"无法查询 {package} 的 PyPI 版本且没有缓存: {exc}") from exc
                warnings.append(f"PyPI 查询失败，使用缓存: {exc}")

        raw_versions = [str(item) for item in cached.get("versions", [])]
        try:
            selected = [item for item in raw_versions if matches(item, specifier)]
        except ValueError as exc:
            raise ValueError(f"{package} 的版本约束不受支持: {specifier}: {exc}") from exc
        metadata = {
            version: {**dict(cached.get("metadata", {}).get(version, {})), "cached": source == "cache"}
            for version in selected[:cap]
        }
        return selected[:cap], metadata, source, warnings

    def catalog(
        self,
        dependencies: list[dict[str, Any]],
        *,
        refresh: bool = False,
        injected: dict[str, list[str]] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        injected = injected or {}
        cap = self.top_k if limit is None else max(1, int(limit))
        versions: dict[str, list[str]] = {}
        metadata: dict[str, dict[str, dict[str, Any]]] = {}
        sources: dict[str, str] = {}
        has_more: dict[str, bool] = {}
        warnings: list[str] = []
        def discover(dep: dict[str, Any]) -> tuple[str, list[str], dict[str, dict[str, Any]], str, bool, list[str]] | None:
            name = str(dep["name"])
            canonical = name.lower().replace("_", "-")
            if dep.get("non_searchable"):
                return None
            supplied = injected.get(name, injected.get(canonical))
            if supplied is not None:
                try:
                    choices = [v for v in supplied if matches(str(v), str(dep.get("specifier", "")))]
                except ValueError as exc:
                    raise ValueError(f"{name} 的注入版本目录无效: {exc}") from exc
                selected = [str(v) for v in choices[:cap]]
                details = {
                    version: {"has_wheel": True, "cached": True} for version in selected
                }
                return canonical, selected, details, "injected", len(choices) > cap, []
            found, details, source, found_warnings = self.versions(
                name, str(dep.get("specifier", "")), refresh=refresh, limit=cap
            )
            if source == "exact":
                more = False
            else:
                cached = self._cache.get(canonical, {})
                raw_versions = [str(item) for item in cached.get("versions", [])]
                try:
                    matching = [
                        item for item in raw_versions
                        if matches(item, str(dep.get("specifier", "")))
                    ]
                except ValueError:
                    matching = found
                more = len(matching) > len(found)
            return canonical, found, details, source, more, found_warnings

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.max_workers, max(1, len(dependencies)))
        ) as executor:
            discovered = list(executor.map(discover, dependencies))
        for item in discovered:
            if item is None:
                continue
            canonical, found, details, source, more, found_warnings = item
            versions[canonical] = found
            metadata[canonical] = details
            sources[canonical] = source
            has_more[canonical] = more
            warnings.extend(found_warnings)
        return {
            "versions": versions,
            "metadata": metadata,
            "sources": sources,
            "has_more": has_more,
            "limit": cap,
            "warnings": warnings,
        }
