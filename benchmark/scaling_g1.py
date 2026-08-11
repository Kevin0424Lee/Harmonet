"""
HarmoNet agent scaling probe.

Measures the non-LLM resonance substrate at 10/50/100 agents. This does not
judge answer quality; it is a scalability gate for field propagation and
agent resonance scanning.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import math
import os
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

import numpy as np

from harmonet.agent import AgentRole, HarmoAgent, SOCController
from harmonet.field import DataUniverseField, Seed
from harmonet.resonance import KuraMotoCoupler


@dataclass
class ScalingMeasurement:
    agents: int
    seeds: int
    ticks: int
    scan_every: int
    avg_tick_ms: float
    p99_tick_ms: float
    max_tick_ms: float
    resonance_events: int
    events_per_tick: float
    events_per_agent_tick: float
    scanned_agent_ticks: int
    events_per_scanned_agent_tick: float


def _p99(values: List[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * 0.99) - 1)]


def _unit(rng: np.random.Generator, dim: int) -> np.ndarray:
    vec = rng.normal(size=dim).astype(np.float32)
    return vec / (np.linalg.norm(vec) + 1e-8)


def _run_case(
    agent_count: int,
    seed_count: int,
    ticks: int,
    dim: int,
    grid_size: int,
    scan_every: int,
) -> ScalingMeasurement:
    os.environ.setdefault("HARMONET_DISABLE_REDIS", "1")
    scan_every = max(1, scan_every)
    rng = np.random.default_rng(42 + agent_count + seed_count)

    with contextlib.redirect_stdout(io.StringIO()):
        universe = DataUniverseField(dim=dim, grid_size=grid_size)
        soc = SOCController(threshold=0.7)
        kuramoto = KuraMotoCoupler(coupling_strength=0.5)
        agents = []
        roles = [AgentRole.ARCHITECT, AgentRole.BUILDER, AgentRole.VALIDATOR]
        tags = [
            ["python", "implementation", "code"],
            ["testing", "validation", "review"],
            ["api", "architecture", "system"],
            ["debugging", "performance", "refactor"],
        ]
        for i in range(agent_count):
            agents.append(
                HarmoAgent(
                    agent_id=f"scale-agent-{i:03d}",
                    role=roles[i % len(roles)],
                    domain_tags=tags[i % len(tags)],
                    universe=universe,
                    soc_controller=soc,
                    kuramoto_coupler=kuramoto,
                    resonance_threshold=0.12,
                    grid_position=i % grid_size,
                )
            )

        for i in range(seed_count):
            freq = _unit(rng, dim)
            payload = _unit(rng, dim)
            seed = Seed(
                id=f"scale-seed-{i:05d}",
                creator_id="scaling-probe",
                frequency=freq,
                payload=payload,
                rule_description=f"scaling synthetic seed {i}",
                energy=0.5 + 0.5 * float(rng.random()),
                phase=float(rng.random() * 2 * np.pi),
                ttl_seconds=3600,
            )
            universe.deposit_seed(seed, i % grid_size)

    tick_ms = []
    events = 0
    scanned_agent_ticks = 0
    for tick in range(ticks):
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            universe.propagate(dt=0.3)
            for agent_index, agent in enumerate(agents):
                agent.sync_phase(dt=0.1)
                agent.drift_position()
                if (tick + agent_index) % scan_every != 0:
                    continue
                scanned_agent_ticks += 1
                found = agent.detector.scan_field(
                    universe=universe,
                    scan_position=agent.grid_position,
                    scan_radius=5,
                )
                events += len(found)
            kuramoto.step(dt=0.1)
        tick_ms.append((time.perf_counter() - t0) * 1000.0)

    return ScalingMeasurement(
        agents=agent_count,
        seeds=seed_count,
        ticks=ticks,
        scan_every=scan_every,
        avg_tick_ms=round(statistics.mean(tick_ms), 3),
        p99_tick_ms=round(_p99(tick_ms), 3),
        max_tick_ms=round(max(tick_ms), 3),
        resonance_events=events,
        events_per_tick=round(events / max(1, ticks), 3),
        events_per_agent_tick=round(events / max(1, ticks * agent_count), 6),
        scanned_agent_ticks=scanned_agent_ticks,
        events_per_scanned_agent_tick=round(events / max(1, scanned_agent_ticks), 6),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HarmoNet scaling G1 probe.")
    parser.add_argument("--agents", default="10,50,100")
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--ticks", type=int, default=20)
    parser.add_argument("--dim", type=int, default=256)
    parser.add_argument("--grid-size", type=int, default=128)
    parser.add_argument(
        "--scan-every",
        type=int,
        default=1,
        help="Scan each agent once every N ticks in a round-robin duty cycle.",
    )
    parser.add_argument("--output", default="g1_scaling_results.json")
    args = parser.parse_args()

    counts = [int(v.strip()) for v in args.agents.split(",") if v.strip()]
    results = []
    print("HarmoNet scaling probe")
    for count in counts:
        print(
            f"agents={count} seeds={args.seeds} ticks={args.ticks} "
            f"scan_every={args.scan_every} ...",
            end=" ",
            flush=True,
        )
        m = _run_case(count, args.seeds, args.ticks, args.dim, args.grid_size, args.scan_every)
        results.append(m)
        print(
            f"avg={m.avg_tick_ms:.2f}ms p99={m.p99_tick_ms:.2f}ms "
            f"events={m.resonance_events} scanned={m.scanned_agent_ticks}"
        )

    payload = {"measurements": [asdict(m) for m in results]}
    path = Path(args.output)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(list(asdict(results[0]).keys()))
        for m in results:
            writer.writerow(list(asdict(m).values()))

    print(f"Saved: {path}")
    print(f"Saved: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
