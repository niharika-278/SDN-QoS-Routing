"""Phase 1 topology package; imports are dependency-free by default."""

from .core import (
    CANDIDATE_PATHS,
    PathValidationError,
    candidate_paths,
    configured_link_params,
    configured_path_params,
    deterministic_candidate_paths,
    select_candidate_path,
    topology_neighbors,
    validate_path,
)

__all__ = [
    "CANDIDATE_PATHS",
    "PathValidationError",
    "candidate_paths",
    "configured_link_params",
    "configured_path_params",
    "deterministic_candidate_paths",
    "select_candidate_path",
    "topology_neighbors",
    "validate_path",
]
