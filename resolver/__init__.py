"""Dependency analysis and constraint propagation for PACS."""

from .combinations import generate_combinations
from .constraint_graph import ConstraintGraph
from .dep_parser import DepSpec, parse_dependencies
from .failure_parser import parse_failure
from .version_index import VersionIndex

__all__ = ["ConstraintGraph", "DepSpec", "VersionIndex", "generate_combinations", "parse_dependencies", "parse_failure"]
