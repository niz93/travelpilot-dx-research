#!/usr/bin/env python3
"""Render a recovered TPNAV2 node/link cluster in internal integer units."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def plot_graph(graph: dict, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 12), dpi=150)
    fig.patch.set_facecolor("#111827")
    ax.set_facecolor("#111827")

    bounds = graph["bounds_coordinates"]
    if bounds:
        bx = [point["x"] for point in bounds] + [bounds[0]["x"]]
        by = [point["y"] for point in bounds] + [bounds[0]["y"]]
        ax.plot(bx, by, color="#64748b", linestyle="--", linewidth=1.1, label="cluster bounds")

    for link in graph["links"]:
        points = link.get("path_coordinates", [])
        if not points:
            continue
        x = [point["x"] for point in points]
        y = [point["y"] for point in points]
        if link["resolved_first"] == link["resolved_second"]:
            ax.add_patch(plt.Circle((x[0], y[0]), 0.018, fill=False, color="#f59e0b",
                                    linewidth=1.1, zorder=2))
        else:
            ax.plot(x, y, color="#38bdf8", linewidth=1.25, zorder=2)

    node_x = [node["coordinate"]["x"] for node in graph["nodes"]]
    node_y = [node["coordinate"]["y"] for node in graph["nodes"]]
    ax.scatter(node_x, node_y, s=34, color="#f8fafc", edgecolors="#0f172a", linewidths=0.7,
               zorder=3)
    for node in graph["nodes"]:
        ax.annotate(str(node["index"]), (node["coordinate"]["x"], node["coordinate"]["y"]),
                    textcoords="offset points", xytext=(4, 4), color="#e2e8f0", fontsize=8,
                    zorder=4)

    validation = graph["validation"]
    title = (
        f"TPNAV2 cluster: nodes {validation['node_count']}, links {validation['link_count']}\n"
        f"internal integer coordinates — not WGS84"
    )
    ax.set_title(title, color="#f8fafc", fontsize=12, pad=12)
    ax.set_xlabel("internal X", color="#cbd5e1")
    ax.set_ylabel("internal Y", color="#cbd5e1")
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, color="#1f2937", linewidth=0.6)
    ax.legend(loc="upper right", facecolor="#0f172a", edgecolor="#334155", labelcolor="#e2e8f0")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graphs", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for path in args.graphs:
        graph = json.loads(path.read_text(encoding="utf-8"))
        output = args.output_dir / f"{path.stem}.png"
        plot_graph(graph, output)
        print(output)


if __name__ == "__main__":
    main()
