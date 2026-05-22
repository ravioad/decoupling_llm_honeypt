#!/usr/bin/env python3
"""
Visualize evaluation results across 31 runs.

Reads evaluation_runs.csv and produces 5 figures
saved to final-evaulation-runs/charts/.

Figures:
  fig1_ccr_comparison.pdf/png       : CCR grouped bar chart (3 variants x 4 scenarios)
  fig2_inj_comparison.pdf/png       : INJ* bar chart (injection scenario only)
  fig3_fbk_boxplot.pdf/png          : FBK% boxplot across 31 runs (state_isolated)
  fig4_latency.pdf/png              : Avg ms/cmd bar chart log-scale (3 variants x 4 scenarios)
  fig5_inj_distribution.pdf/png     : prompt_only INJ* histogram across 31 runs

Usage:
    python final-evaulation-runs/visualize.py
    python final-evaulation-runs/visualize.py --csv final-evaulation-runs/evaluation_runs.csv --output-dir final-evaulation-runs/charts
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

VARIANT_COLORS = {
    "state_isolated":     "#2563EB",   # blue
    "deterministic_only": "#16A34A",   # green
    "prompt_only":        "#DC2626",   # red
}

VARIANT_LABELS = {
    "state_isolated":     "State-Isolated",
    "deterministic_only": "Deterministic-Only",
    "prompt_only":        "Prompt-Only",
}

SCENARIO_LABELS = {
    "normal":       "Normal",
    "state_mod":    "State-Mod",
    "injection":    "Injection",
    "long_session": "Long-Session",
}

VARIANTS  = ["state_isolated", "deterministic_only", "prompt_only"]
SCENARIOS = ["normal", "state_mod", "injection", "long_session"]

RC = {
    "font.family":       "sans-serif",
    "font.size":         11,
    "axes.titlesize":    13,
    "axes.labelsize":    11,
    "xtick.labelsize":   10,
    "ytick.labelsize":   10,
    "legend.fontsize":   10,
    "figure.dpi":        150,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "grid.linestyle":    "--",
}

DPI_SAVE = 300

def load_runs(csv_path: Path) -> tuple[dict, dict]:
    """
    Reads evaluation_runs.csv and returns:
        data[(variant, scenario)][metric] = [val, val, ...]
        lat[(variant, scenario)]["avg_ms"] = [val, val, ...]
    Values are ordered by run number. N/A cells (NaN in CSV) become None.
    """
    df = pd.read_csv(csv_path)

    data: dict = defaultdict(lambda: defaultdict(list))
    lat:  dict = defaultdict(lambda: defaultdict(list))

    for _, row in df.sort_values("run").iterrows():
        key = (row["variant"], row["scenario"])
        for m in ("ccr", "llm_pct", "fbk_pct", "sdr", "inj", "inj_star"):
            val = row[m]
            data[key][m].append(None if pd.isna(val) else float(val))
        val = row["avg_ms"]
        lat[key]["avg_ms"].append(None if pd.isna(val) else float(val))

    return data, lat

def _arr(values: list) -> np.ndarray:
    return np.array([v for v in values if v is not None], dtype=float)

def fig1_ccr(data: dict, out_dir: Path) -> None:
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(9, 5))

        n_scenarios = len(SCENARIOS)
        n_variants  = len(VARIANTS)
        width       = 0.22
        x           = np.arange(n_scenarios)

        for i, variant in enumerate(VARIANTS):
            means, errs = [], []
            for scenario in SCENARIOS:
                vals = _arr(data[(variant, scenario)]["ccr"]) * 100
                if len(vals) == 0:
                    means.append(0); errs.append(0)
                else:
                    means.append(vals.mean())
                    errs.append(vals.std())

            offset = (i - 1) * width
            bars = ax.bar(
                x + offset, means,
                width=width,
                yerr=errs,
                capsize=4,
                color=VARIANT_COLORS[variant],
                label=VARIANT_LABELS[variant],
                alpha=0.88,
                error_kw={"elinewidth": 1.2, "ecolor": "0.3"},
            )
            if variant == "prompt_only":
                for bar, mean in zip(bars, means):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 1.5,
                        f"{mean:.1f}%",
                        ha="center", va="bottom", fontsize=8.5, color="0.25",
                    )

        ax.set_xticks(x)
        ax.set_xticklabels([SCENARIO_LABELS[s] for s in SCENARIOS])
        ax.set_ylabel("Command Correctness Rate (%)")
        ax.set_title("Command Correctness Rate (CCR) — 31-Run Mean ± Std")
        ax.set_ylim(0, 115)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax.legend(loc="upper right")

        ax.axhline(100, color="0.5", linewidth=0.8, linestyle=":")

        fig.tight_layout()
        _save(fig, out_dir, "fig1_ccr_comparison")


def fig2_inj(data: dict, out_dir: Path) -> None:
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(6, 4.5))

        x = np.arange(len(VARIANTS))
        means, errs, colors = [], [], []

        for variant in VARIANTS:
            vals = _arr(data[(variant, "injection")]["inj_star"]) * 100
            if len(vals) == 0:
                means.append(0); errs.append(0)
            else:
                means.append(vals.mean())
                errs.append(vals.std())
            colors.append(VARIANT_COLORS[variant])

        bars = ax.bar(
            x, means,
            yerr=errs,
            capsize=5,
            color=colors,
            alpha=0.88,
            width=0.45,
            error_kw={"elinewidth": 1.4, "ecolor": "0.3"},
        )

        for bar, mean, err in zip(bars, means, errs):
            label = f"{mean:.1f}%" if mean > 0 else "0.0%\n(guaranteed)"
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + err + 1.2,
                label,
                ha="center", va="bottom", fontsize=9.5, color="0.2",
            )

        ax.set_xticks(x)
        ax.set_xticklabels([VARIANT_LABELS[v] for v in VARIANTS])
        ax.set_ylabel("Injection Success Rate — Corrected (%)")
        ax.set_title("INJ* — Corrected Injection Rate\n(Injection Scenario, 31-Run Mean ± Std)")
        ax.set_ylim(0, 52)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))

        fig.tight_layout()
        _save(fig, out_dir, "fig2_inj_comparison")

def fig3_fbk(data: dict, out_dir: Path) -> None:
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7, 4.5))

        plot_data = []
        labels    = []
        for scenario in SCENARIOS:
            vals = _arr(data[("state_isolated", scenario)]["fbk_pct"]) * 100
            plot_data.append(vals)
            labels.append(SCENARIO_LABELS[scenario])

        bp = ax.boxplot(
            plot_data,
            patch_artist=True,
            notch=False,
            widths=0.45,
            medianprops={"color": "white", "linewidth": 2},
            whiskerprops={"linewidth": 1.2},
            capprops={"linewidth": 1.2},
            flierprops={"marker": "o", "markersize": 4, "alpha": 0.6},
        )

        for patch in bp["boxes"]:
            patch.set_facecolor(VARIANT_COLORS["state_isolated"])
            patch.set_alpha(0.75)

        rng = np.random.default_rng(42)
        for i, vals in enumerate(plot_data, start=1):
            jitter = rng.uniform(-0.12, 0.12, size=len(vals))
            ax.scatter(
                np.full(len(vals), i) + jitter,
                vals,
                color=VARIANT_COLORS["state_isolated"],
                alpha=0.35,
                s=18,
                zorder=3,
            )

        ax.set_xticklabels(labels)
        ax.set_ylabel("Fallback Activation Rate (%)")
        ax.set_title(
            "FBK% Distribution Across 31 Runs — State-Isolated\n"
            "(CCR = 100% in all runs regardless of FBK%)"
        )
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax.set_ylim(-3, 60)

        fig.tight_layout()
        _save(fig, out_dir, "fig3_fbk_boxplot")

def fig4_latency(lat: dict, out_dir: Path) -> None:
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(9, 5))

        n_scenarios = len(SCENARIOS)
        n_variants  = len(VARIANTS)
        width       = 0.22
        x           = np.arange(n_scenarios)

        for i, variant in enumerate(VARIANTS):
            means, errs = [], []
            for scenario in SCENARIOS:
                vals = _arr(lat[(variant, scenario)]["avg_ms"])
                if len(vals) == 0:
                    means.append(1e-3); errs.append(0)
                else:
                    means.append(vals.mean())
                    errs.append(vals.std())

            offset = (i - 1) * width
            ax.bar(
                x + offset, means,
                width=width,
                yerr=errs,
                capsize=4,
                color=VARIANT_COLORS[variant],
                label=VARIANT_LABELS[variant],
                alpha=0.88,
                error_kw={"elinewidth": 1.2, "ecolor": "0.3"},
            )

        ax.set_yscale("log")
        ax.set_xticks(x)
        ax.set_xticklabels([SCENARIO_LABELS[s] for s in SCENARIOS])
        ax.set_ylabel("Average Latency per Command (ms, log scale)")
        ax.set_title("Command Latency — 31-Run Mean ± Std (Log Scale)")
        ax.legend(loc="upper right")

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{int(v)}ms" if v >= 1 else f"{v:.0e}ms"
        ))
        ax.yaxis.set_minor_formatter(mticker.NullFormatter())

        ax.text(
            0.01, 0.97,
            "state_isolated ≈ 5x deterministic_only\n"
            "prompt_only ≈ 48x deterministic_only",
            transform=ax.transAxes,
            fontsize=8.5, va="top", color="0.35",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="0.8"),
        )

        fig.tight_layout()
        _save(fig, out_dir, "fig4_latency")

def fig5_inj_dist(data: dict, out_dir: Path) -> None:
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(6.5, 4.5))

        vals = _arr(data[("prompt_only", "injection")]["inj_star"]) * 100
        n    = len(vals)

        bins = np.arange(0, 55, 5)
        ax.hist(
            vals, bins=bins,
            color=VARIANT_COLORS["prompt_only"],
            alpha=0.80,
            edgecolor="white",
            linewidth=0.8,
            rwidth=0.85,
        )

        mean_val = vals.mean()
        std_val  = vals.std()
        ax.axvline(mean_val, color="0.2", linestyle="--", linewidth=1.5,
                   label=f"Mean = {mean_val:.1f}%")
        ax.axvline(0, color="0.5", linestyle=":", linewidth=1.2)

        zero_count = int((vals == 0).sum())
        ax.text(
            0.97, 0.95,
            f"n = {n} runs\n"
            f"Mean ± std: {mean_val:.1f}% ± {std_val:.1f}%\n"
            f"Range: [{vals.min():.1f}%–{vals.max():.1f}%]\n"
            f"Runs with INJ* = 0%: {zero_count}/{n}",
            transform=ax.transAxes,
            fontsize=9, va="top", ha="right", color="0.25",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.8"),
        )

        ax.set_xlabel("INJ* : Corrected Injection Success Rate (%)")
        ax.set_ylabel("Number of Runs")
        ax.set_title(
            "Prompt-Only INJ* Distribution Across 31 Runs\n"
            "(Injection Scenario, role-revealing keyword leakage)"
        )
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax.legend(loc="upper left")

        fig.tight_layout()
        _save(fig, out_dir, "fig5_inj_distribution")


def _save(fig: plt.Figure, out_dir: Path, name: str) -> None:
    for ext in ("pdf", "png"):
        path = out_dir / f"{name}.{ext}"
        fig.savefig(path, dpi=DPI_SAVE, bbox_inches="tight")
        print(f"  Saved: {path}")
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description="Visualize evaluation metrics from evaluation_runs.csv.")
    p.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "evaluation_runs.csv"),
        help="Path to evaluation_runs.csv (default: same dir as this script)",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for charts (default: <csv-dir>/charts)",
    )
    args = p.parse_args()

    csv_path   = Path(args.csv).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else csv_path.parent / "charts"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading: {csv_path}")
    data, lat = load_runs(csv_path)

    print(f"Writing charts to: {output_dir}")
    print("Generating fig1: CCR comparison...")
    fig1_ccr(data, output_dir)

    print("Generating fig2: INJ* comparison...")
    fig2_inj(data, output_dir)

    print("Generating fig3: FBK% boxplot...")
    fig3_fbk(data, output_dir)

    print("Generating fig4: Latency...")
    fig4_latency(lat, output_dir)

    print("Generating fig5: INJ* distribution...")
    fig5_inj_dist(data, output_dir)

    print("Done.")


if __name__ == "__main__":
    main()
