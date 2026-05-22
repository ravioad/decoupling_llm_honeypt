#!/usr/bin/env python3
"""
Extended visualizations: distribution, CDF, scatter, run-consistency.

Reads final-evaulation-runs/evaluation_runs.csv and produces 4 figures:

  fig6_kde_ccr_prompt_only.pdf/png
      KDE + fitted normal overlay for prompt_only CCR across 31 runs,
      one subplot per scenario.

  fig7_cdf_inj_star.pdf/png
      Empirical CDF of prompt_only INJ* (injection scenario, 31 runs).
      Shows cumulative leakage probability, what fraction of runs had
      leakage below a given threshold.

  fig8_latency_vs_llm_scatter.pdf/png
      avg_ms vs LLM% scatter. Each point = one (variant x scenario)
      mean across 31 runs.

  fig9_run_consistency.pdf/png
      Run-by-run metric values across all 31 runs (two panels):
        Top: prompt_only CCR per scenario
        Bottom: state_isolated FBK% per scenario
      Shows run-to-run consistency across 31 runs.

Usage:
    python final-evaulation-runs/visualize_extra.py
    python final-evaulation-runs/visualize_extra.py --csv evaluation_runs.csv --output-dir charts_extra
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy import stats

VARIANT_COLORS = {
    "state_isolated":     "#2563EB",
    "deterministic_only": "#16A34A",
    "prompt_only":        "#DC2626",
}

SCENARIO_COLORS = {
    "normal":       "#7C3AED",
    "state_mod":    "#D97706",
    "injection":    "#DC2626",
    "long_session": "#0891B2",
}

SCENARIO_LABELS = {
    "normal":       "Normal",
    "state_mod":    "State-Mod",
    "injection":    "Injection",
    "long_session": "Long-Session",
}

VARIANT_LABELS = {
    "state_isolated":     "State-Isolated",
    "deterministic_only": "Deterministic-Only",
    "prompt_only":        "Prompt-Only",
}

RC = {
    "font.family":       "sans-serif",
    "font.size":         11,
    "axes.titlesize":    12,
    "axes.labelsize":    11,
    "xtick.labelsize":   10,
    "ytick.labelsize":   10,
    "legend.fontsize":   9.5,
    "figure.dpi":        150,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "grid.linestyle":    "--",
}

DPI_SAVE  = 300
SCENARIOS = ["normal", "state_mod", "injection", "long_session"]
VARIANTS  = ["state_isolated", "deterministic_only", "prompt_only"]

def _save(fig: plt.Figure, out_dir: Path, name: str) -> None:
    for ext in ("pdf", "png"):
        path = out_dir / f"{name}.{ext}"
        fig.savefig(path, dpi=DPI_SAVE, bbox_inches="tight")
        print(f"  Saved: {path}")
    plt.close(fig)

def fig6_kde_ccr(df: pd.DataFrame, out_dir: Path) -> None:
    po = df[df["variant"] == "prompt_only"].copy()
    po["ccr_pct"] = po["ccr"] * 100

    with plt.rc_context(RC):
        fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharey=False)
        axes = axes.flatten()

        for ax, scenario in zip(axes, SCENARIOS):
            vals = po[po["scenario"] == scenario]["ccr_pct"].dropna().values
            n = len(vals)
            mu, sigma = vals.mean(), vals.std(ddof=0)


            kde = stats.gaussian_kde(vals, bw_method="scott")
            x_range = np.linspace(max(0, vals.min() - 5), min(100, vals.max() + 5), 300)
            kde_y = kde(x_range)


            norm_y = stats.norm.pdf(x_range, loc=mu, scale=sigma)

            ax.fill_between(x_range, kde_y, alpha=0.25,
                            color=SCENARIO_COLORS[scenario], label="KDE")
            ax.plot(x_range, kde_y, color=SCENARIO_COLORS[scenario],
                    linewidth=2, label="KDE")
            ax.plot(x_range, norm_y, color="0.3", linewidth=1.5,
                    linestyle="--", label=f"Fitted normal\n(μ={mu:.1f}%, σ={sigma:.1f}%)")


            ax.scatter(vals, np.full_like(vals, -0.002), marker="|",
                       color=SCENARIO_COLORS[scenario], s=40, alpha=0.7,
                       clip_on=False, zorder=5)


            ax.axvline(mu, color=SCENARIO_COLORS[scenario], linewidth=1.2,
                       linestyle=":", alpha=0.8)

            ax.set_title(f"{SCENARIO_LABELS[scenario]}")
            ax.set_xlabel("CCR (%)")
            ax.set_ylabel("Density")
            ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
            ax.legend(loc="upper right", fontsize=8.5)

            ax.text(0.04, 0.96,
                    f"n={n}  mean={mu:.1f}%\nstd={sigma:.1f}%",
                    transform=ax.transAxes, fontsize=8.5, va="top",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor="0.8", alpha=0.9))

        fig.suptitle(
            "Prompt-Only CCR Distribution Across 31 Runs\n"
            "KDE with Fitted Normal Overlay — per Scenario",
            fontsize=13, y=1.01,
        )
        fig.tight_layout()
        _save(fig, out_dir, "fig6_kde_ccr_prompt_only")


def fig7_cdf_inj(df: pd.DataFrame, out_dir: Path) -> None:
    mask = (df["variant"] == "prompt_only") & (df["scenario"] == "injection")
    vals = df[mask]["inj_star"].dropna().sort_values().values * 100
    n    = len(vals)

    cdf_y = np.arange(1, n + 1) / n

    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(7, 5))

        ax.step(vals, cdf_y, where="post",
                color=VARIANT_COLORS["prompt_only"], linewidth=2.2,
                label="Empirical CDF (prompt-only, injection)")

        ax.fill_between(vals, 0, cdf_y,
                        step="post", alpha=0.12,
                        color=VARIANT_COLORS["prompt_only"])


        zero_frac = (vals == 0).sum() / n
        ax.axhline(zero_frac, color="0.5", linewidth=1, linestyle=":",
                   label=f"Runs with INJ*=0%: {int(zero_frac*n)}/{n} ({zero_frac*100:.0f}%)")

        mean_val = vals.mean()
        ax.axvline(mean_val, color="0.3", linewidth=1.4, linestyle="--",
                   label=f"Mean = {mean_val:.1f}%")


        for threshold, label_offset in [(10, 0.04), (20, 0.04), (40, 0.04)]:
            frac = (vals <= threshold).sum() / n
            ax.annotate(
                f"{frac*100:.0f}% of runs\n≤ {threshold}%",
                xy=(threshold, frac),
                xytext=(threshold + 2, frac - 0.12),
                fontsize=8, color="0.35",
                arrowprops=dict(arrowstyle="-", color="0.6", lw=0.8),
            )

        ax.axvline(0, color=VARIANT_COLORS["state_isolated"],
                   linewidth=2, linestyle="-", alpha=0.6,
                   label="State-Isolated INJ* = 0.0% (guaranteed)")

        ax.set_xlabel("INJ* — Corrected Injection Success Rate (%)")
        ax.set_ylabel("Cumulative Fraction of Runs")
        ax.set_title(
            "Empirical CDF — Prompt-Only INJ* (Injection Scenario, 31 Runs)\n"
            "How often does leakage stay below a given threshold?"
        )
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        ax.set_xlim(-3, 52)
        ax.set_ylim(-0.03, 1.08)
        ax.legend(loc="lower right", fontsize=9)

        fig.tight_layout()
        _save(fig, out_dir, "fig7_cdf_inj_star")

def fig8_latency_scatter(df: pd.DataFrame, out_dir: Path) -> None:
    summary = (
        df.groupby(["variant", "scenario"])
        .agg(avg_ms=("avg_ms", "mean"), llm_pct=("llm_pct", "mean"))
        .reset_index()
    )

    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(8, 5.5))

        all_x = summary["llm_pct"].values * 100
        all_y = summary["avg_ms"].values
        slope, intercept, r, p, _ = stats.linregress(all_x, all_y)
        x_fit = np.linspace(0, 102, 200)
        ax.plot(x_fit, intercept + slope * x_fit,
                color="0.55", linewidth=1.2, linestyle="--", zorder=0,
                label=f"Linear fit  R²={r**2:.3f}")

        for _, row in summary.iterrows():
            variant  = row["variant"]
            scenario = row["scenario"]
            x        = row["llm_pct"] * 100
            y        = row["avg_ms"]

            ax.scatter(x, y,
                       color=VARIANT_COLORS[variant],
                       s=90, zorder=4,
                       edgecolors="white", linewidths=0.6)

            x_offset = 1.5
            y_offset = 30
            ax.annotate(
                SCENARIO_LABELS[scenario],
                xy=(x, y), xytext=(x + x_offset, y + y_offset),
                fontsize=8, color="0.25",
                arrowprops=dict(arrowstyle="-", color="0.7", lw=0.7),
            )

        handles = [
            plt.Line2D([0], [0], marker="o", color="w",
                       markerfacecolor=VARIANT_COLORS[v], markersize=9,
                       label=VARIANT_LABELS[v])
            for v in VARIANTS
        ]
        handles.append(
            plt.Line2D([0], [0], color="0.55", linewidth=1.2,
                       linestyle="--", label=f"Linear fit  R²={r**2:.3f}")
        )
        ax.legend(handles=handles, loc="upper left", fontsize=9)

        ax.set_xlabel("LLM Invocation Rate (%)")
        ax.set_ylabel("Average Latency per Command (ms)")
        ax.set_title(
            "Latency vs LLM Invocation Rate\n"
            "Each point = one variant x scenario mean (31-run average)"
        )
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax.set_xlim(-3, 110)

        ax.text(0.98, 0.04,
                f"Slope ≈ {slope:.0f} ms per 1% LLM increase\n"
                f"Intercept ≈ {intercept:.0f} ms (deterministic baseline)",
                transform=ax.transAxes, fontsize=8.5, ha="right", va="bottom",
                color="0.35",
                bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                          edgecolor="0.8"))

        fig.tight_layout()
        _save(fig, out_dir, "fig8_latency_vs_llm_scatter")

def fig9_run_consistency(df: pd.DataFrame, out_dir: Path) -> None:
    runs = sorted(df["run"].unique())

    with plt.rc_context(RC):
        fig, (ax_top, ax_bot) = plt.subplots(
            2, 1, figsize=(11, 7), sharex=True,
            gridspec_kw={"hspace": 0.38},
        )

        po = df[df["variant"] == "prompt_only"]
        for scenario in SCENARIOS:
            sub  = po[po["scenario"] == scenario].set_index("run")
            vals = [sub.loc[r, "ccr"] * 100 if r in sub.index else np.nan
                    for r in runs]
            ax_top.plot(runs, vals,
                        color=SCENARIO_COLORS[scenario],
                        linewidth=1.6, marker="o", markersize=4,
                        label=SCENARIO_LABELS[scenario], alpha=0.85)

        po_all = po.groupby("run")["ccr"].mean() * 100
        rolling = po_all.rolling(window=5, center=True).mean()
        ax_top.plot(rolling.index, rolling.values,
                    color="0.2", linewidth=2, linestyle="--",
                    alpha=0.6, label="Rolling mean (w=5, all scenarios)")

        ax_top.set_ylabel("CCR (%)")
        ax_top.set_title("Prompt-Only CCR per Scenario — Run 1 to 31")
        ax_top.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax_top.set_ylim(-2, 45)
        ax_top.legend(loc="upper right", ncol=2, fontsize=9)

        si = df[df["variant"] == "state_isolated"]
        for scenario in SCENARIOS:
            sub  = si[si["scenario"] == scenario].set_index("run")
            vals = [sub.loc[r, "fbk_pct"] * 100 if r in sub.index else np.nan
                    for r in runs]
            ax_bot.plot(runs, vals,
                        color=SCENARIO_COLORS[scenario],
                        linewidth=1.6, marker="o", markersize=4,
                        label=SCENARIO_LABELS[scenario], alpha=0.85)

        ax_bot.set_ylabel("FBK% (%)")
        ax_bot.set_title(
            "State-Isolated FBK% per Scenario — Run 1 to 31\n"
            "(CCR = 100% in every run regardless of FBK%)"
        )
        ax_bot.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
        ax_bot.set_ylim(-2, 60)
        ax_bot.set_xlabel("Run Number")
        ax_bot.legend(loc="upper right", ncol=2, fontsize=9)

        ax_bot.set_xticks(runs[::2])
        ax_bot.set_xlim(0.5, len(runs) + 0.5)

        fig.suptitle(
            "Run-by-Run Consistency Across 31 Evaluation Runs",
            fontsize=13, y=1.01,
        )
        fig.tight_layout()
        _save(fig, out_dir, "fig9_run_consistency")

def main() -> None:
    p = argparse.ArgumentParser(
        description="Extended visualizations from evaluation_runs.csv."
    )
    p.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "evaluation_runs.csv"),
        help="Path to evaluation_runs.csv",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: <csv-dir>/charts_extra)",
    )
    args = p.parse_args()

    csv_path   = Path(args.csv).resolve()
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else csv_path.parent / "charts_extra"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading: {csv_path}")
    df = pd.read_csv(csv_path)

    print(f"Writing charts to: {output_dir}")

    print("Generating fig6 — KDE + normal overlay (prompt_only CCR)...")
    fig6_kde_ccr(df, output_dir)

    print("Generating fig7 — Empirical CDF (prompt_only INJ*)...")
    fig7_cdf_inj(df, output_dir)

    print("Generating fig8 — Latency vs LLM% scatter...")
    fig8_latency_scatter(df, output_dir)

    print("Generating fig9 — Run-by-run consistency...")
    fig9_run_consistency(df, output_dir)

    print("Done.")


if __name__ == "__main__":
    main()
