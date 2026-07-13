"""Small, conservative version comparator and specifier matcher."""
from __future__ import annotations

import re
from functools import total_ordering


_TOKEN = re.compile(r"(\d+|[a-zA-Z]+)")
_PRE = {"dev": -4, "a": -3, "alpha": -3, "b": -2, "beta": -2, "rc": -1, "pre": -1}
_POST = {"post": 1, "rev": 1, "r": 1}
_OPERATOR = re.compile(r"^(===|~=|==|!=|>=|<=|>|<)\s*(\S+)$")
_WILDCARD = re.compile(r"^(\d+(?:\.\d+)*)\.\*$")


@total_ordering
class Version:
    """Comparable dotted numeric version with common pre/post-release suffixes."""

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("版本不能为空")
        self.original = value.strip()
        public = self.original.split("+", 1)[0].lower().replace("-", ".").replace("_", ".")
        tokens = _TOKEN.findall(public)
        if not tokens or not tokens[0].isdigit():
            raise ValueError(f"不支持的版本: {value!r}")
        release: list[int] = []
        index = 0
        while index < len(tokens) and tokens[index].isdigit():
            release.append(int(tokens[index]))
            index += 1
        self.release = tuple(release)
        self.stage = 0
        self.stage_number = 0
        if index < len(tokens):
            label = tokens[index]
            index += 1
            if label in _PRE:
                self.stage = _PRE[label]
            elif label in _POST:
                self.stage = _POST[label]
            else:
                raise ValueError(f"不支持的版本后缀: {label!r}")
            if index < len(tokens) and tokens[index].isdigit():
                self.stage_number = int(tokens[index])
                index += 1
        if index != len(tokens):
            raise ValueError(f"不支持的版本: {value!r}")

    def _key(self, width: int) -> tuple[tuple[int, ...], int, int]:
        return self.release + (0,) * (width - len(self.release)), self.stage, self.stage_number

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        width = max(len(self.release), len(other.release))
        return self._key(width) == other._key(width)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        width = max(len(self.release), len(other.release))
        return self._key(width) < other._key(width)

    def __repr__(self) -> str:
        return f"Version({self.original!r})"


def compare_versions(left: str, right: str) -> int:
    first, second = Version(left), Version(right)
    return -1 if first < second else (1 if first > second else 0)


def _compatible_upper(value: str) -> Version:
    parsed = Version(value)
    parts = list(parsed.release)
    if len(parts) == 1:
        return Version(str(parts[0] + 1))
    prefix = parts[:-1]
    prefix[-1] += 1
    return Version(".".join(str(part) for part in prefix))


def _matches_wildcard(candidate: Version, expected: str) -> bool:
    match = _WILDCARD.fullmatch(expected)
    if not match:
        raise ValueError(f"非法通配版本说明符: {expected!r}")
    prefix = tuple(int(part) for part in match.group(1).split("."))
    return candidate.release[:len(prefix)] == prefix


def matches(version: str, specifier: str | None) -> bool:
    """Match comma-separated comparison clauses using AND semantics.

    ``===`` compares the literal supplied version string. ``==X.*`` and
    ``!=X.*`` use release-prefix semantics and retain the wildcard instead of
    passing it through the numeric version parser.
    """
    if not specifier or not specifier.strip():
        return True
    candidate: Version | None = None
    for clause in specifier.split(","):
        match = _OPERATOR.fullmatch(clause.strip())
        if not match:
            raise ValueError(f"非法版本说明符: {clause!r}")
        operator, expected_text = match.groups()
        if operator == "===":
            if version.strip() != expected_text:
                return False
            continue
        if candidate is None:
            candidate = Version(version)
        wildcard = expected_text.endswith(".*")
        if wildcard:
            if operator not in {"==", "!="}:
                raise ValueError(f"通配版本只支持 == 或 !=: {clause!r}")
            matched = _matches_wildcard(candidate, expected_text)
            if (operator == "==" and not matched) or (operator == "!=" and matched):
                return False
            continue
        expected = Version(expected_text)
        if operator == "==" and candidate != expected:
            return False
        if operator == "!=" and candidate == expected:
            return False
        if operator == ">=" and candidate < expected:
            return False
        if operator == "<=" and candidate > expected:
            return False
        if operator == ">" and candidate <= expected:
            return False
        if operator == "<" and candidate >= expected:
            return False
        if operator == "~=" and not (candidate >= expected and candidate < _compatible_upper(expected_text)):
            return False
    return True
