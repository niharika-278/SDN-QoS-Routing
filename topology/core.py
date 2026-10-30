"""Dependency-free Phase 1 topology model and route helpers.

The runtime topology in :mod:`topology.topo` uses Mininet when it is
explicitly built. This module intentionally contains only data validation
and deterministic path calculations so it can be imported in an offline test
environment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


SWITCH_LINKS = (
    (1, 2, 10, 5, 0),
    (1, 3, 10, 20, 0),
    (2, 4, 5, 5, 0),
    (3, 4, 10, 5, 0),
    (2, 5, 10, 10, 2),
    (4, 6, 10, 5, 0),
    (5, 6, 10, 5, 0),
)
HOST_LINK = {"bw": 100}
SRC = "h1"
DST = "h2"
SRC_SWITCH = 1
DST_SWITCH = 6

# A tuple of pairs gives callers a stable order without exposing mutable
# global state. The public helper below returns a fresh dictionary.
CANDIDATE_PATHS = {
    "P1_1-2-4-6": (1, 2, 4, 6),
    "P2_1-2-5-6": (1, 2, 5, 6),
    "P3_1-3-4-6": (1, 3, 4, 6),
}


class PathValidationError(ValueError):
    """Raised when a path is malformed or not connected in the topology."""


def _link_map(links: Iterable[Sequence[Any]]) -> dict[frozenset[int], tuple[float, float, float]]:
    result: dict[frozenset[int], tuple[float, float, float]] = {}
    for link in links:
        if len(link) != 5:
            raise ValueError(f"link must have five fields: {link!r}")
        left, right, bandwidth, delay, loss = link
        if isinstance(left, bool) or isinstance(right, bool):
            raise ValueError(f"switch identifiers must be integers: {link!r}")
        if not isinstance(left, int) or not isinstance(right, int) or left == right:
            raise ValueError(f"invalid switch endpoints: {link!r}")
        values = (float(bandwidth), float(delay), float(loss))
        if values[0] <= 0 or values[1] < 0 or not 0 <= values[2] <= 100:
            raise ValueError(f"invalid link parameters: {link!r}")
        key = frozenset((left, right))
        if key in result:
            raise ValueError(f"duplicate link: {link!r}")
        result[key] = values
    return result


def candidate_paths() -> dict[str, tuple[int, ...]]:
    """Return all candidate paths in their canonical deterministic order."""

    return {name: tuple(path) for name, path in CANDIDATE_PATHS.items()}


def deterministic_candidate_paths() -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Return ordered ``(name, path)`` pairs for repeatable experiments."""

    return tuple((name, tuple(path)) for name, path in CANDIDATE_PATHS.items())


def validate_path(
    path: Sequence[int] | Iterable[int],
    *,
    source: int = SRC_SWITCH,
    destination: int = DST_SWITCH,
    links: Iterable[Sequence[Any]] = SWITCH_LINKS,
) -> tuple[int, ...]:
    """Validate and canonicalize a switch path.

    A valid path is a simple sequence that starts at ``source``, ends at
    ``destination``, and uses only links present in ``links``. A
    :class:`PathValidationError` gives callers a stable failure type instead
    of allowing a later port lookup to fail with a cryptic ``KeyError``.
    """

    try:
        values = tuple(path)
    except TypeError as exc:
        raise PathValidationError("path must be an iterable of switch IDs") from exc
    if len(values) < 2:
        raise PathValidationError("path must contain at least two switches")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        raise PathValidationError("path switch IDs must be integers")
    if values[0] != source or values[-1] != destination:
        raise PathValidationError(
            f"path must start at {source} and end at {destination}: {values!r}"
        )
    if len(set(values)) != len(values):
        raise PathValidationError(f"path must not repeat a switch: {values!r}")
    available = _link_map(tuple(links))
    for left, right in zip(values, values[1:]):
        if frozenset((left, right)) not in available:
            raise PathValidationError(f"switches {left} and {right} are not linked")
    return values


def select_candidate_path(
    selection: str | Sequence[int] | Iterable[int],
    candidates: Mapping[str, Sequence[int]] | None = None,
) -> tuple[int, ...]:
    """Select a candidate by name or validate an explicitly supplied path."""

    available = CANDIDATE_PATHS if candidates is None else candidates
    if isinstance(selection, str):
        if selection not in available:
            raise PathValidationError(f"unknown candidate path: {selection!r}")
        selected = available[selection]
    else:
        selected = selection
    return validate_path(selected)


def configured_link_params(
    left: int,
    right: int,
    *,
    links: Iterable[Sequence[Any]] = SWITCH_LINKS,
) -> dict[str, float | int]:
    """Return configured (not measured) parameters for one switch link."""

    params = _link_map(links).get(frozenset((left, right)))
    if params is None:
        raise PathValidationError(f"switches {left} and {right} are not linked")
    bandwidth, delay, loss = params
    return {
        "bw_mbit": _number_like(bandwidth),
        "delay_ms": _number_like(delay),
        "loss_pct": _number_like(loss),
    }


def configured_path_params(
    path: Sequence[int] | Iterable[int],
    *,
    links: Iterable[Sequence[Any]] = SWITCH_LINKS,
) -> dict[str, float | int]:
    """Calculate configured path characteristics, never measurement data."""

    link_data = tuple(links)
    valid = validate_path(path, links=link_data)
    params = _link_map(link_data)
    hops = [params[frozenset(edge)] for edge in zip(valid, valid[1:])]
    survival = 1.0
    for _, _, loss in hops:
        survival *= 1.0 - loss / 100.0
    return {
        "cfg_bottleneck_bw_mbit": _number_like(min(hop[0] for hop in hops)),
        "cfg_oneway_delay_ms": _number_like(sum(hop[1] for hop in hops)),
        "cfg_loss_pct_per_direction": round((1.0 - survival) * 100.0, 3),
    }


def topology_neighbors(
    *, links: Iterable[Sequence[Any]] = SWITCH_LINKS
) -> dict[int, tuple[int, ...]]:
    """Return sorted undirected adjacency for connectivity tests and callers."""

    result: dict[int, set[int]] = {}
    for left, right, *_ in links:
        result.setdefault(left, set()).add(right)
        result.setdefault(right, set()).add(left)
    return {switch: tuple(sorted(neighbors)) for switch, neighbors in sorted(result.items())}


def _number_like(value: float) -> float | int:
    return int(value) if value.is_integer() else value


# Compatibility aliases make the intent discoverable without duplicating
# calculations in runtime modules.
select_path = select_candidate_path
link_params = configured_link_params
