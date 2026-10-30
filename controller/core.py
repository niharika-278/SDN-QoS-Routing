"""Dependency-free route request and acknowledgement validation."""

from __future__ import annotations

import json
from pathlib import Path

from collections.abc import Mapping, Sequence
from typing import Any

from topology.core import CANDIDATE_PATHS, PathValidationError, select_candidate_path


class RouteRequestError(ValueError):
    """Raised when an IPC route request or acknowledgement is unusable."""


def _request_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RouteRequestError("route request id must be a positive integer")
    return value


def _candidate_name(path: tuple[int, ...], candidates: Mapping[str, Sequence[int]]) -> str:
    for name, candidate in candidates.items():
        if tuple(candidate) == path:
            return name
    raise RouteRequestError(f"path is not one of the configured candidates: {path!r}")


def validate_route_request(
    request: Mapping[str, Any],
    *,
    candidates: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, Any]:
    """Validate an IPC route request and return a canonical JSON-safe dict.

    Requests must contain a positive integer ``id`` and either a candidate
    name in ``route`` or a connected ``path`` matching one of the configured
    candidates. Extra fields are ignored so callers can add metadata without
    changing the controller protocol.
    """

    if not isinstance(request, Mapping):
        raise RouteRequestError("route request must be a JSON object")
    request_id = _request_id(request.get("id"))
    available = CANDIDATE_PATHS if candidates is None else candidates
    if "route" in request:
        try:
            path = select_candidate_path(request["route"], available)
        except (PathValidationError, TypeError) as exc:
            raise RouteRequestError(str(exc)) from exc
        route_name = request["route"] if isinstance(request["route"], str) else _candidate_name(path, available)
    elif "path" in request:
        try:
            path = select_candidate_path(request["path"], available)
        except (PathValidationError, TypeError) as exc:
            raise RouteRequestError(str(exc)) from exc
        route_name = _candidate_name(path, available)
    else:
        raise RouteRequestError("route request must contain route or path")
    return {"id": request_id, "route": route_name, "path": list(path)}


def read_route_request_file(
    path: str | Path,
    *,
    candidates: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, Any]:
    """Read and validate one JSON route request from the controller IPC file."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouteRequestError(f"cannot read route request file: {path}") from exc
    return validate_route_request(payload, candidates=candidates)


def make_route_request(
    request_id: int,
    selection: str | Sequence[int],
    *,
    candidates: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, Any]:
    """Build a canonical route request for deterministic experiment IPC."""

    request = {"id": request_id}
    if isinstance(selection, str):
        request["route"] = selection
    else:
        request["path"] = list(selection)
    return validate_route_request(request, candidates=candidates)


def validate_route_ack(
    acknowledgement: Mapping[str, Any],
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a controller acknowledgement and optionally match its request."""

    canonical = validate_route_request(acknowledgement)
    if request is not None:
        expected = validate_route_request(request)
        if canonical["id"] != expected["id"] or canonical["path"] != expected["path"]:
            raise RouteRequestError("route acknowledgement does not match request")
    return canonical


# Short aliases keep imports readable for tests and experiment code.
validate_request = validate_route_request
validate_ack = validate_route_ack
