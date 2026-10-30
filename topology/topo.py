"""Mininet runtime builder for the fixed Phase 1 topology.

Importing this module is safe on machines without Mininet. The optional
runtime dependency is imported only when :func:`build` is called; pure path
helpers are re-exported from :mod:`topology.core` for offline use.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core import (
    CANDIDATE_PATHS,
    DST,
    DST_SWITCH,
    HOST_LINK,
    SRC,
    SRC_SWITCH,
    SWITCH_LINKS,
    configured_link_params,
    configured_path_params,
    candidate_paths,
    deterministic_candidate_paths,
    select_candidate_path,
    topology_neighbors,
    validate_path,
)


def build(state_dir: str | os.PathLike[str], controller_port: int = 6653):
    """Build and return the live Mininet network.

    Mininet, Open vSwitch, and TCLink are runtime-only dependencies. Keeping
    their imports here lets ``python -m unittest`` exercise Phase 1 without
    privileged networking packages.
    """

    try:
        from mininet.link import TCLink
        from mininet.net import Mininet
        from mininet.node import OVSSwitch, RemoteController
    except ImportError as exc:
        raise RuntimeError(
            "Mininet is required only to build the live topology; "
            "offline helpers do not need it"
        ) from exc

    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    net = Mininet(
        controller=None,
        link=TCLink,
        autoSetMacs=True,
        build=False,
        switch=lambda n, **kw: OVSSwitch(
            n,
            datapath=os.environ.get("SDN_DATAPATH", "kernel"),
            protocols="OpenFlow13",
            **kw,
        ),
    )
    net.addController(
        "c0", controller=RemoteController, ip="127.0.0.1", port=controller_port
    )
    switches = {switch_id: net.addSwitch(f"s{switch_id}") for switch_id in range(1, 7)}
    h1 = net.addHost(SRC, ip="10.0.0.1/24")
    h2 = net.addHost(DST, ip="10.0.0.2/24")
    net.addLink(h1, switches[SRC_SWITCH], **HOST_LINK)
    net.addLink(h2, switches[DST_SWITCH], **HOST_LINK)
    for left, right, bandwidth, delay, loss in SWITCH_LINKS:
        if os.environ.get("SDN_NO_NETEM") == "1":
            net.addLink(switches[left], switches[right], bw=bandwidth)
        else:
            net.addLink(
                switches[left],
                switches[right],
                bw=bandwidth,
                delay=f"{delay}ms",
                loss=loss,
            )
    net.build()
    net.staticArp()

    ports: dict[str, dict[str, int]] = {}
    for link in net.links:
        for interface, neighbour in (
            (link.intf1, link.intf2),
            (link.intf2, link.intf1),
        ):
            if interface.node.name.startswith("s"):
                ports.setdefault(interface.node.name, {})[
                    neighbour.node.name
                ] = interface.node.ports[interface]
    (state_path / "ports.json").write_text(
        json.dumps(
            {
                "ports": ports,
                "src": SRC,
                "dst": DST,
                "src_ip": "10.0.0.1",
                "dst_ip": "10.0.0.2",
            },
            indent=1,
        )
    )
    return net


__all__ = [
    "CANDIDATE_PATHS",
    "DST",
    "DST_SWITCH",
    "HOST_LINK",
    "SRC",
    "SRC_SWITCH",
    "SWITCH_LINKS",
    "build",
    "candidate_paths",
    "configured_link_params",
    "configured_path_params",
    "deterministic_candidate_paths",
    "select_candidate_path",
    "topology_neighbors",
    "validate_path",
]
