#!/usr/bin/env python3
"""Analyze validated Phase 1 measurement CSV files.

It accepts only the strict Phase 1 CSV schema, rejects failed or incomplete rows before any
aggregation, and reports descriptive statistics only. It never fills missing
measurements, invents values, or performs inferential tests.
"""

from __future__ import annotations

import argparse
import csv
import html
import statistics
import sys
from pathlib import Path
from typing import Iterable

from experiments.schema import MeasurementValidationError, read_valid_csv
from topology.core import CANDIDATE_PATHS, configured_path_params

METRICS = (
    ("ping_rtt_avg_ms", "Ping RTT", "ms"),
    ("ping_loss_pct", "Ping loss", "%"),
    ("udp_throughput_mbit", "UDP throughput", "Mbit/s"),
    ("udp_loss_pct", "UDP loss", "%"),
    ("udp_jitter_ms", "UDP jitter", "ms"),
    ("tcp_throughput_mbit", "TCP throughput", "Mbit/s"),
)


def _mean_std(rows: Iterable[dict[str, object]], field: str) -> tuple[float, float]:
    values = [float(row[field]) for row in rows]
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else 0.0


def summarize_route(route: str, rows: list[dict[str, object]]) -> dict[str, object]:
    """Return one descriptive summary row for one route or all routes."""
    result: dict[str, object] = {"route": route, "trial_count": len(rows)}
    if route == "ALL_ROUTES":
        result.update(
            {
                "path": "all candidate paths",
                "cfg_bottleneck_bw_mbit": "",
                "cfg_oneway_delay_ms": "",
                "cfg_loss_pct_per_direction": "",
            }
        )
    else:
        path = CANDIDATE_PATHS[route]
        result.update({"path": "-".join(str(node) for node in path), **configured_path_params(path)})
    for field, _, _ in METRICS:
        mean, std = _mean_std(rows, field)
        result[f"{field}_mean"] = round(mean, 6)
        result[f"{field}_std"] = round(std, 6)
    return result


def _summary_fields() -> list[str]:
    fields = [
        "route",
        "path",
        "trial_count",
        "cfg_bottleneck_bw_mbit",
        "cfg_oneway_delay_ms",
        "cfg_loss_pct_per_direction",
    ]
    for field, _, _ in METRICS:
        fields.extend((f"{field}_mean", f"{field}_std"))
    return fields


def write_summary(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_summary_fields(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _svg_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def write_bar_chart(path: Path, rows: list[dict[str, object]], field: str, label: str, unit: str) -> None:
    """Write a dependency-free SVG chart with mean and sample-SD bars."""
    width, height = 1060, 620
    left, right, top, bottom = 105, 35, 95, 105
    plot_width, plot_height = width - left - right, height - top - bottom
    values = [float(row[f"{field}_mean"]) + float(row[f"{field}_std"]) for row in rows]
    maximum = max(1.0, max(values) * 1.2)
    group_width = plot_width / len(rows)
    bar_width = min(120.0, group_width * 0.48)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f'<title>{_svg_escape("Validated Phase 1 measurements: " + label)}</title>',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2:.1f}" y="32" text-anchor="middle" font-family="sans-serif" font-size="23" font-weight="bold">{_svg_escape(label)}</text>',
        f'<text x="{width / 2:.1f}" y="59" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#374151">validated successful rows; error bars = ± sample SD; unit: {_svg_escape(unit)}</text>',
    ]
    for tick in range(6):
        value = maximum * tick / 5
        y = top + plot_height - plot_height * value / maximum
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 10}" y="{y + 5:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{value:.2f}</text>')
    parts.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827" stroke-width="2"/>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{width - right}" y2="{top + plot_height}" stroke="#111827" stroke-width="2"/>',
            f'<text x="24" y="{top + plot_height / 2:.1f}" transform="rotate(-90 24 {top + plot_height / 2:.1f})" text-anchor="middle" font-family="sans-serif" font-size="14">{_svg_escape(label + " (" + unit + ")")}</text>',
        ]
    )
    for index, row in enumerate(rows):
        mean = float(row[f"{field}_mean"])
        std = float(row[f"{field}_std"])
        center = left + group_width * (index + 0.5)
        x = center - bar_width / 2
        bar_height = plot_height * mean / maximum
        y = top + plot_height - bar_height
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" fill="#2563eb"/>')
        error_top = top + plot_height - plot_height * min(maximum, mean + std) / maximum
        error_bottom = top + plot_height - plot_height * max(0.0, mean - std) / maximum
        parts.extend(
            [
                f'<line x1="{center:.2f}" y1="{error_top:.2f}" x2="{center:.2f}" y2="{error_bottom:.2f}" stroke="#111827" stroke-width="2"/>',
                f'<line x1="{center - 8:.2f}" y1="{error_top:.2f}" x2="{center + 8:.2f}" y2="{error_top:.2f}" stroke="#111827" stroke-width="2"/>',
                f'<line x1="{center - 8:.2f}" y1="{error_bottom:.2f}" x2="{center + 8:.2f}" y2="{error_bottom:.2f}" stroke="#111827" stroke-width="2"/>',
                f'<text x="{center:.2f}" y="{max(top + 15, y - 6):.2f}" text-anchor="middle" font-family="sans-serif" font-size="12">{mean:.3f}</text>',
                f'<text x="{center:.2f}" y="{top + plot_height + 28}" text-anchor="middle" font-family="sans-serif" font-size="13">{_svg_escape(row["route"])}</text>',
                f'<text x="{center:.2f}" y="{top + plot_height + 48}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#4b5563">n={row["trial_count"]}</text>',
            ]
        )
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_report(path: Path, input_path: Path, rows: list[dict[str, object]], summaries: list[dict[str, object]]) -> None:
    lines = [
        "# Phase 1 Measurement Analysis",
        "",
        "> This report is generated only from rows that passed the strict Phase 1 result schema. It contains descriptive statistics, not inferential tests.",
        "",
        "## Provenance",
        "",
        f"- Input CSV: `{input_path}`",
        f"- Validated successful rows: **{len(rows)}**",
        "- Failed runs and incomplete measurements: rejected before aggregation; no values were filled or converted to zero.",
        "- Synthetic data are not accepted by this analyzer; use `synthetic_demo/analyze_synthetic_data.py` for the separate demonstration.",
        "",
        "## Descriptive summary",
        "",
        "| Route | n | Ping RTT (ms) mean ± SD | UDP throughput (Mbit/s) mean ± SD | UDP loss (%) mean ± SD | TCP throughput (Mbit/s) mean ± SD |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            f"| {summary['route']} | {summary['trial_count']} | "
            f"{float(summary['ping_rtt_avg_ms_mean']):.3f} ± {float(summary['ping_rtt_avg_ms_std']):.3f} | "
            f"{float(summary['udp_throughput_mbit_mean']):.3f} ± {float(summary['udp_throughput_mbit_std']):.3f} | "
            f"{float(summary['udp_loss_pct_mean']):.3f} ± {float(summary['udp_loss_pct_std']):.3f} | "
            f"{float(summary['tcp_throughput_mbit_mean']):.3f} ± {float(summary['tcp_throughput_mbit_std']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation policy",
            "",
            "These summaries describe the supplied successful rows only. They do not establish a route ranking, causal effect, statistical significance, or generalization beyond the measured setup. The raw CSV, commands, runtime versions, and number of repetitions must accompany any empirical use.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="validated Phase 1 CSV")
    parser.add_argument("--out-dir", type=Path, default=Path("results/analysis"))
    args = parser.parse_args(argv)
    try:
        rows = read_valid_csv(args.input)
        missing_routes = [route for route in CANDIDATE_PATHS if not any(row["route"] == route for row in rows)]
        if missing_routes:
            raise MeasurementValidationError(f"input is missing complete rows for route(s): {', '.join(missing_routes)}")
    except (OSError, MeasurementValidationError) as exc:
        print(f"VALIDATION: FAIL — {exc}", file=sys.stderr)
        return 2

    summaries = [
        summarize_route(route, [row for row in rows if row["route"] == route])
        for route in CANDIDATE_PATHS
    ]
    all_summary = summarize_route("ALL_ROUTES", rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_summary(args.out_dir / "summary_by_route.csv", summaries)
    write_summary(args.out_dir / "summary_overall.csv", [all_summary])
    write_bar_chart(args.out_dir / "throughput_by_route.svg", summaries, "udp_throughput_mbit", "UDP throughput by route", "Mbit/s")
    write_bar_chart(args.out_dir / "latency_by_route.svg", summaries, "ping_rtt_avg_ms", "Ping RTT by route", "ms")
    write_report(args.out_dir / "analysis_report.md", args.input, rows, summaries)
    print(f"VALIDATION: PASS — {len(rows)} complete successful rows")
    print(f"Wrote descriptive summaries and figures to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
