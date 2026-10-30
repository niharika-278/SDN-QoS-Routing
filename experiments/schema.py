"""Standard-library validation for Phase 1 measurement CSV results."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from topology.core import PathValidationError, select_candidate_path


CSV_COLUMNS = (
    "run_id",
    "status",
    "route",
    "path",
    "seed",
    "shaping_mode",
    "cfg_bottleneck_bw_mbit",
    "cfg_oneway_delay_ms",
    "cfg_loss_pct_per_direction",
    "ping_rtt_avg_ms",
    "ping_loss_pct",
    "udp_offered_mbit",
    "udp_throughput_mbit",
    "udp_loss_pct",
    "udp_jitter_ms",
    "tcp_throughput_mbit",
    "wall_s",
)
REQUIRED_MEASUREMENT_COLUMNS = (
    "ping_rtt_avg_ms",
    "ping_loss_pct",
    "udp_throughput_mbit",
    "udp_loss_pct",
    "udp_jitter_ms",
    "tcp_throughput_mbit",
)
NUMERIC_COLUMNS = (
    "run_id",
    "seed",
    "cfg_bottleneck_bw_mbit",
    "cfg_oneway_delay_ms",
    "cfg_loss_pct_per_direction",
    "ping_rtt_avg_ms",
    "ping_loss_pct",
    "udp_offered_mbit",
    "udp_throughput_mbit",
    "udp_loss_pct",
    "udp_jitter_ms",
    "tcp_throughput_mbit",
    "wall_s",
)


class MeasurementValidationError(ValueError):
    """Raised when a result cannot be used as a complete measurement."""


def validate_csv_schema(fieldnames: Sequence[str] | None) -> tuple[str, ...]:
    """Require the exact Phase 1 header, including its deterministic order."""

    if fieldnames is None:
        raise MeasurementValidationError("CSV is missing a header")
    names = tuple(fieldnames)
    if len(set(names)) != len(names):
        raise MeasurementValidationError("CSV header contains duplicate columns")
    if names != CSV_COLUMNS:
        missing = [name for name in CSV_COLUMNS if name not in names]
        unexpected = [name for name in names if name not in CSV_COLUMNS]
        details = []
        if missing:
            details.append(f"missing columns: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected columns: {', '.join(unexpected)}")
        if not details:
            details.append("columns are in the wrong order")
        raise MeasurementValidationError("invalid CSV schema (" + "; ".join(details) + ")")
    return names


def _validate_row_columns(row: Mapping[str, Any]) -> None:
    names = set(row)
    expected = set(CSV_COLUMNS)
    missing = sorted(expected - names)
    unexpected = sorted(names - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing columns: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected columns: {', '.join(unexpected)}")
        raise MeasurementValidationError("invalid result row schema (" + "; ".join(details) + ")")


def _text(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if value is None or not str(value).strip():
        raise MeasurementValidationError(f"missing value for {name}")
    return str(value).strip()


def _number(
    row: Mapping[str, Any],
    name: str,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    raw = _text(row, name)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MeasurementValidationError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise MeasurementValidationError(f"{name} must be finite and{bound}")
    return value


def validate_result_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one complete successful measurement and return normalized data.

    Failed runs and blank measurement cells are deliberately rejected instead
    of being silently converted to zeros or treated as successful data.
    """

    if not isinstance(row, Mapping):
        raise MeasurementValidationError("result row must be a mapping")
    _validate_row_columns(row)
    status = _text(row, "status")
    if status != "ok":
        raise MeasurementValidationError(
            f"measurement row status is {status!r}; only 'ok' rows are usable"
        )
    run_id = _number(row, "run_id", minimum=1)
    if not run_id.is_integer():
        raise MeasurementValidationError("run_id must be a positive integer")
    seed = _number(row, "seed")
    if not seed.is_integer():
        raise MeasurementValidationError("seed must be an integer")
    route = _text(row, "route")
    shaping_mode = _text(row, "shaping_mode")
    path_text = _text(row, "path")
    try:
        path = select_candidate_path(tuple(int(part) for part in path_text.split("-")))
    except (ValueError, PathValidationError) as exc:
        raise MeasurementValidationError(f"invalid candidate path: {path_text!r}") from exc
    if route != _route_name(path):
        raise MeasurementValidationError(f"route {route!r} does not match path {path_text!r}")

    normalized: dict[str, Any] = {
        name: row[name] for name in CSV_COLUMNS
    }
    normalized.update(
        {
            "run_id": int(run_id),
            "seed": int(seed),
            "route": route,
            "path": "-".join(str(switch) for switch in path),
            "shaping_mode": shaping_mode,
        }
    )
    for name in NUMERIC_COLUMNS:
        if name in {"run_id", "seed"}:
            continue
        maximum = 100.0 if name in {"cfg_loss_pct_per_direction", "ping_loss_pct", "udp_loss_pct"} else None
        value = _number(row, name, maximum=maximum)
        normalized[name] = value
    return normalized


def _route_name(path: tuple[int, ...]) -> str:
    # Candidate selection has already validated the path. Importing the map
    # here avoids making CSV constants depend on runtime topology modules.
    from topology.core import CANDIDATE_PATHS

    for name, candidate in CANDIDATE_PATHS.items():
        if tuple(candidate) == path:
            return name
    raise MeasurementValidationError(f"path is not a configured candidate: {path!r}")


def validate_results(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate every row, rejecting failed or incomplete rows immediately."""

    validated = [validate_result_row(row) for row in rows]
    if not validated:
        raise MeasurementValidationError("result CSV contains no complete measurements")
    return validated


def partition_results(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Separate usable rows from explicit rejection reasons without fabricating data."""

    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    for index, row in enumerate(rows, start=2):
        try:
            accepted.append(validate_result_row(row))
        except MeasurementValidationError as exc:
            rejected.append(f"row {index}: {exc}")
    return accepted, rejected


def read_valid_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read and validate a Phase 1 result CSV from disk."""

    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        validate_csv_schema(reader.fieldnames)
        return validate_results(reader)


def write_valid_csv(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write only validated rows, refusing failed or incomplete measurements."""

    validated = validate_results(rows)
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(validated)
