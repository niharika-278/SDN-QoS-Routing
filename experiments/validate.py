"""Phase 1 live validation runner.

The command needs Mininet/Open vSwitch/Ryu (or os-ken) and root privileges.
Its imported helpers and validation rules remain standard-library-only so the
offline test suite can run without those runtime packages.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller.core import make_route_request
from experiments.schema import partition_results, write_valid_csv
from topology.core import (
    CANDIDATE_PATHS,
    SWITCH_LINKS,
    configured_path_params,
    deterministic_candidate_paths,
)
from topology.topo import build


ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("SDN_STATE_DIR", "/tmp/sdnstate"))


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--udp_mbit", type=float, default=8.0)
    parser.add_argument("--dur", type=int, default=5)
    parser.add_argument("--out", default="phase1_route_runs.csv")
    return parser.parse_args(argv)


def _die(message: str) -> None:
    raise RuntimeError(message)


def _wait_for(
    name: str,
    condition: Callable[[Any], bool],
    *,
    timeout: float = 30.0,
) -> bool:
    started = time.time()
    while time.time() - started < timeout:
        try:
            if condition(json.loads((STATE / name).read_text())):
                return True
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            pass
        time.sleep(0.3)
    return False


def _json_from_output(text: str) -> dict[str, Any]:
    try:
        start = text.index("{")
        value = json.loads(text[start:])
    except (ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _controller_binary() -> str:
    candidates = (
        os.environ.get("SDN_CONTROLLER_BIN"),
        os.path.expanduser("~/ryuenv/bin/ryu-manager"),
        shutil.which("ryu-manager"),
        shutil.which("osken-manager"),
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    _die("no controller found; install Ryu/os-ken or set SDN_CONTROLLER_BIN")
    raise AssertionError("unreachable")


def build_experiment_config(args: argparse.Namespace, controller: str, shaping: str) -> dict[str, Any]:
    """Return serializable configuration metadata before a live run starts."""

    if args.reps < 1 or args.dur < 1 or args.udp_mbit <= 0:
        raise ValueError("reps and dur must be positive and udp_mbit must be > 0")
    return {
        "provenance": "configured experiment metadata; not measurement data",
        "runtime": {
            "controller_binary": str(controller),
            "controller_port": 6653,
            "datapath": os.environ.get("SDN_DATAPATH", "kernel"),
            "netem_disabled": os.environ.get("SDN_NO_NETEM") == "1",
            "shaping_mode": shaping,
        },
        "sampling": {
            "repetitions_per_route": args.reps,
            "route_order_seed": args.seed,
            "udp_offered_mbit": args.udp_mbit,
            "iperf_duration_s": args.dur,
            "ping_probes": 10,
        },
        "topology": {
            "source": "h1",
            "destination": "h2",
            "switches": 6,
            "configured_switch_links": [list(link) for link in SWITCH_LINKS],
            "candidate_paths": {name: list(path) for name, path in CANDIDATE_PATHS.items()},
        },
        "measurement_policy": {
            "configured_parameters_are_not_measurements": True,
            "failed_or_incomplete_rows_are_rejected": True,
            "synthetic_data_used": False,
        },
    }


def _preflight() -> str:
    if os.geteuid() != 0:
        _die("run with root privileges: sudo python3 -m experiments.phase1_validate")
    for tool in ("mn", "ovs-vsctl", "iperf3", "ping", "tc"):
        if shutil.which(tool) is None:
            _die(f"{tool!r} not found in PATH (see ENVIRONMENT_SETUP.md)")
    if subprocess.run(
        ["ovs-vsctl", "--timeout=5", "show"], capture_output=True
    ).returncode != 0:
        _die("Open vSwitch is not running")
    try:
        import mininet  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("system Python cannot import Mininet") from exc
    return _controller_binary()


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if args.reps < 1 or args.dur < 1 or args.udp_mbit <= 0:
        _die("--reps and --dur must be positive and --udp_mbit must be > 0")
    controller = _preflight()
    smoke = os.environ.get("SDN_NO_NETEM") == "1"
    shaping = "bw_only_SMOKE_TEST_INVALID_FOR_RESULTS" if smoke else "bw+delay+loss"
    STATE.mkdir(parents=True, exist_ok=True)
    raw_dir = ROOT / "results" / "raw"
    logs_dir = ROOT / "results" / "logs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    config_path = raw_dir / "phase1_config.json"
    config_path.write_text(
        json.dumps(build_experiment_config(args, controller, shaping), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {config_path.relative_to(ROOT)}")
    for path in STATE.iterdir():
        if path.is_file():
            path.unlink()
    os.system("mn -c >/dev/null 2>&1")
    print(f"controller binary: {controller}\nlink shaping mode: {shaping}")
    if smoke:
        print("WARNING: smoke-test mode; delay/loss are not emulated")

    controller_log = (logs_dir / "controller.log").open("w")
    process = subprocess.Popen(
        [controller, "--ofp-tcp-listen-port", "6653", str(ROOT / "controller" / "route_controller.py")],
        env={**os.environ, "SDN_STATE_DIR": str(STATE)},
        stdout=controller_log,
        stderr=controller_log,
    )
    network = None
    rows: list[dict[str, Any]] = []
    request_id = 0
    try:
        listening = False
        for _ in range(40):
            if process.poll() is not None:
                break
            try:
                socket.create_connection(("127.0.0.1", 6653), timeout=1).close()
                listening = True
                break
            except OSError:
                time.sleep(0.5)
        if not listening:
            _die("controller did not start listening on port 6653")
        print("CHECK controller listening on 6653: PASS")
        network = build(STATE)
        network.start()
        if not _wait_for("connected.json", lambda value: len(value) == 6):
            _die("controller did not see all 6 switches")
        print("CHECK 6 switches connected to controller (OpenFlow 1.3): PASS")
        h1, h2 = network.get("h1"), network.get("h2")
        if os.environ.get("SDN_DISABLE_OFFLOAD") == "1":
            for node in network.hosts + network.switches:
                for interface in node.intfList():
                    if interface.name != "lo":
                        node.cmd(
                            f"ethtool -K {interface.name} tx off rx off tso off gso off gro off 2>/dev/null"
                        )
        h2.cmd("iperf3 -s -D -p 5201")
        time.sleep(1)
        plan = list(deterministic_candidate_paths()) * args.reps
        random.Random(args.seed).shuffle(plan)
        for route_name, path in plan:
            request_id += 1
            request = make_route_request(request_id, path)
            (STATE / "route_request.json").write_text(json.dumps(request))
            if not _wait_for("route_ack.json", lambda value: value.get("id") == request_id):
                _die("route was not acknowledged by controller")
            time.sleep(1.0)
            started = time.time()
            ping_output = h1.cmd("timeout 30 ping -c 10 -i 0.2 -W 2 10.0.0.2")
            ping_match = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", ping_output)
            loss_match = re.search(r"([\d.]+)% packet loss", ping_output)
            udp = _json_from_output(
                h1.cmd(
                    f"timeout {args.dur + 20} iperf3 -c 10.0.0.2 -p 5201 -u -b {args.udp_mbit}M -t {args.dur} -J"
                )
            ).get("end", {}).get("sum", {})
            tcp = _json_from_output(
                h1.cmd(
                    f"timeout {args.dur + 20} iperf3 -c 10.0.0.2 -p 5201 -t {args.dur} -J"
                )
            ).get("end", {}).get("sum_received", {})
            good = bool(ping_match and udp and tcp)
            rows.append(
                {
                    "run_id": request_id,
                    "status": "ok" if good else "FAILED",
                    "route": route_name,
                    "path": "-".join(map(str, path)),
                    "seed": args.seed,
                    "shaping_mode": shaping,
                    **configured_path_params(path),
                    "ping_rtt_avg_ms": float(ping_match.group(2)) if ping_match else "",
                    "ping_loss_pct": float(loss_match.group(1)) if loss_match else "",
                    "udp_offered_mbit": args.udp_mbit,
                    "udp_throughput_mbit": round(udp["bits_per_second"] / 1e6, 3) if udp else "",
                    "udp_loss_pct": udp.get("lost_percent", ""),
                    "udp_jitter_ms": udp.get("jitter_ms", ""),
                    "tcp_throughput_mbit": round(tcp["bits_per_second"] / 1e6, 3) if tcp else "",
                    "wall_s": round(time.time() - started, 2),
                }
            )
            print(rows[-1])
        valid_rows, rejected = partition_results(rows)
        if rejected:
            print(f"CHECK measurements collected: FAIL ({len(rejected)} rejected rows)")
            for reason in rejected:
                print(f"REJECTED: {reason}")
            return 1
        write_valid_csv(raw_dir / args.out, valid_rows)
        print(f"CHECK measurements collected: PASS ({len(valid_rows)}/{len(rows)} runs ok)")
        print(f"wrote results/raw/{args.out}")
        return 0
    finally:
        if (STATE / "port_stats.json").exists():
            shutil.copy(STATE / "port_stats.json", raw_dir / "phase1_port_stats.json")
        if network:
            try:
                network.get("h2").cmd("kill %iperf3; pkill -f 'iperf3 -s'")
            except Exception:
                pass
            network.stop()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        controller_log.close()
        os.system("mn -c >/dev/null 2>&1")
        print("CHECK cleanup done")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
