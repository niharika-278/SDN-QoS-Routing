"""Optional OpenFlow runtime controller for the Phase 1 route protocol.

The Ryu/os-ken imports are isolated behind :func:`_build_route_controller`.
Importing this module for offline validation therefore works without either
framework installed. The dependency-free request validator lives in
:mod:`controller.core`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

try:
    from .core import RouteRequestError, read_route_request_file
except ImportError:  # Ryu may load this file as a top-level module.
    from controller.core import RouteRequestError, read_route_request_file


class RuntimeDependencyError(RuntimeError):
    """Raised when the live controller is used without Ryu or os-ken."""


def _state_dir() -> Path:
    state_dir = Path(os.environ.get("SDN_STATE_DIR", "/tmp/sdnstate"))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _write(name: str, obj: Any) -> None:
    state_dir = _state_dir()
    temporary = state_dir / f"{name}.tmp"
    temporary.write_text(json.dumps(obj))
    temporary.replace(state_dir / name)


def _build_route_controller():
    """Create the framework-specific class only when a runtime imports it."""

    try:
        from ryu.base import app_manager
        from ryu.controller import ofp_event
        from ryu.controller.handler import (
            CONFIG_DISPATCHER,
            MAIN_DISPATCHER,
            set_ev_cls,
        )
        from ryu.lib import hub
        from ryu.ofproto import ofproto_v1_3

        base_app = app_manager.RyuApp
    except ImportError:
        try:
            from os_ken.base import app_manager
            from os_ken.controller import ofp_event
            from os_ken.controller.handler import (
                CONFIG_DISPATCHER,
                MAIN_DISPATCHER,
                set_ev_cls,
            )
            from os_ken.lib import hub
            from os_ken.ofproto import ofproto_v1_3

            base_app = app_manager.OSKenApp
        except ImportError as exc:
            raise RuntimeDependencyError(
                "Ryu or os-ken is required only for the live OpenFlow controller"
            ) from exc

    class RouteController(base_app):
        """Install a validated symmetric h1<->h2 route and poll counters."""

        OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.dps: dict[int, Any] = {}
            self.stats: dict[str, Any] = {}
            self.cfg: dict[str, Any] | None = None
            self.last_req: int | None = None
            hub.spawn(self._poll_routes)
            hub.spawn(self._poll_stats)

        @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
        def _features(self, event):
            datapath = event.msg.datapath
            self.dps[datapath.id] = datapath
            _write("connected.json", sorted(self.dps))

        @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
        def _port_stats(self, event):
            self.stats[str(event.msg.datapath.id)] = {
                str(stat.port_no): {
                    "rx_packets": stat.rx_packets,
                    "tx_packets": stat.tx_packets,
                    "rx_bytes": stat.rx_bytes,
                    "tx_bytes": stat.tx_bytes,
                    "rx_dropped": stat.rx_dropped,
                    "tx_dropped": stat.tx_dropped,
                }
                for stat in event.msg.body
            }
            _write("port_stats.json", {"t": time.time(), "stats": self.stats})

        @staticmethod
        def _flow(datapath, ip: str, port: int) -> None:
            parser, ofproto = datapath.ofproto_parser, datapath.ofproto
            match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
            actions = [parser.OFPActionOutput(port)]
            instructions = [
                parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)
            ]
            datapath.send_msg(
                parser.OFPFlowMod(
                    datapath=datapath,
                    priority=10,
                    match=match,
                    instructions=instructions,
                )
            )

        def _install(self, path: list[int]) -> None:
            if self.cfg is None:
                self.cfg = json.loads((_state_dir() / "ports.json").read_text())
            ports = self.cfg["ports"]
            for datapath in self.dps.values():
                parser, ofproto = datapath.ofproto_parser, datapath.ofproto
                datapath.send_msg(
                    parser.OFPFlowMod(
                        datapath=datapath,
                        command=ofproto.OFPFC_DELETE,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        match=parser.OFPMatch(),
                    )
                )
            for index, switch_id in enumerate(path):
                name = f"s{switch_id}"
                next_hop = (
                    f"s{path[index + 1]}"
                    if index + 1 < len(path)
                    else self.cfg["dst"]
                )
                previous_hop = (
                    f"s{path[index - 1]}"
                    if index
                    else self.cfg["src"]
                )
                self._flow(self.dps[switch_id], self.cfg["dst_ip"], ports[name][next_hop])
                self._flow(self.dps[switch_id], self.cfg["src_ip"], ports[name][previous_hop])

        def _poll_routes(self):
            while True:
                hub.sleep(0.2)
                try:
                    canonical = read_route_request_file(_state_dir() / "route_request.json")
                except RouteRequestError as exc:
                    _write("route_error.json", {"error": str(exc), "t": time.time()})
                    continue
                if canonical["id"] == self.last_req:
                    continue
                try:
                    self._install(canonical["path"])
                except (KeyError, OSError, TypeError) as exc:
                    _write("route_error.json", {"id": canonical["id"], "error": str(exc), "t": time.time()})
                    continue
                self.last_req = canonical["id"]
                _write(
                    "route_ack.json",
                    {
                        "id": canonical["id"],
                        "route": canonical["route"],
                        "path": canonical["path"],
                        "t": time.time(),
                    },
                )

        def _poll_stats(self):
            while True:
                hub.sleep(1.0)
                for datapath in list(self.dps.values()):
                    parser, ofproto = datapath.ofproto_parser, datapath.ofproto
                    datapath.send_msg(
                        parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
                    )

    return RouteController


try:
    RouteController = _build_route_controller()
except RuntimeDependencyError as exc:
    _RUNTIME_ERROR = exc

    class RouteController:  # type: ignore[no-redef]
        """Import-safe placeholder when no OpenFlow framework is installed."""

        def __init__(self, *args, **kwargs):
            raise RuntimeDependencyError(str(_RUNTIME_ERROR)) from _RUNTIME_ERROR


__all__ = ["RouteController", "RuntimeDependencyError"]
