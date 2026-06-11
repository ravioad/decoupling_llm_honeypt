#!/usr/bin/env python3
"""
Evaluation report generator.

Reads results/metrics.jsonl and renders:
  1. A compact comparison table (variant x scenario x metric)
  2. A per-variant summary (averages across scenarios)
  3. Injection breakdown (echo pass-through vs real attempts)

Usage
-----
    python -m eval.report --input results/metrics.jsonl
    python -m eval.report --input results/metrics.jsonl --format markdown
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

VARIANTS = ["state_isolated", "deterministic_only", "prompt_only"]
SCENARIOS = ["normal", "state_mod", "injection", "long_session"]

def _load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().strip().split("\n") if l.strip()]


def _pct(v, decimals=1) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def _corrected_injection(record: dict) -> tuple[int, int]:
    c = record.get("counts", {})
    return c.get("injection_success_corrected", 0), c.get("injection_total_corrected", 0)


def _build_table(records: list[dict]) -> dict:
    idx: dict[tuple, dict] = {}
    for r in records:
        idx[(r["variant"], r["scenario"])] = r
    return idx


def render_text(records: list[dict]) -> str:
    idx = _build_table(records)
    lines = []

    lines.append("=" * 80)
    lines.append("  FULL METRICS TABLE")
    lines.append("=" * 80)
    hdr = f"{'Variant':<22} {'Scenario':<14} {'CCR':>7} {'LLM%':>7} {'FBK%':>7} {'SDR':>7} {'INJ':>7} {'INJ*':>7}"
    lines.append(hdr)
    lines.append("─" * 80)

    for variant in VARIANTS:
        for scenario in SCENARIOS:
            r = idx.get((variant, scenario))
            if not r:
                lines.append(f"  {variant:<20} {scenario:<14}  (missing)")
                continue
            rs, rt = _corrected_injection(r)
            inj_corr = _pct(rs / rt if rt else None)
            lines.append(
                f"  {variant:<20} {scenario:<14}"
                f"  {_pct(r['command_correctness_rate']):>6}"
                f"  {_pct(r['llm_invocation_rate']):>6}"
                f"  {_pct(r['fallback_activation_rate']):>6}"
                f"  {_pct(r['state_deviation_rate']):>6}"
                f"  {_pct(r['injection_success_rate']):>6}"
                f"  {inj_corr:>6}"
            )
        lines.append("")

    lines.append("  CCR  = Command Correctness Rate")
    lines.append("  LLM% = LLM Invocation Rate")
    lines.append("  FBK% = Fallback Activation Rate")
    lines.append("  SDR  = State Deviation Rate (among LLM-attempted commands)")
    lines.append("  INJ  = Injection Success Rate (raw, includes echo pass-through)")
    lines.append("  INJ* = Injection Success Rate (corrected, excludes echo/printf)")
    lines.append("")

    lines.append("=" * 80)
    lines.append("  PER-VARIANT SUMMARY  (averages / totals across all scenarios)")
    lines.append("=" * 80)

    for variant in VARIANTS:
        variant_records = [r for r in records if r["variant"] == variant]
        if not variant_records:
            continue

        total_cmds = sum(r["counts"]["total_commands"] for r in variant_records)
        total_llm = sum(r["counts"]["llm_attempted"] for r in variant_records)
        total_llm_ok = sum(r["counts"]["llm_validator_ok"] for r in variant_records)
        total_fbk = sum(r["counts"]["fallback_used"] for r in variant_records)
        total_correct = sum(r["counts"]["correct"] for r in variant_records)
        total_inj = sum(r["counts"]["injection_total"] for r in variant_records)
        total_inj_ok = sum(r["counts"]["injection_success"] for r in variant_records)

        corr_s = corr_t = 0
        for r in variant_records:
            rs, rt = _corrected_injection(r)
            corr_s += rs
            corr_t += rt

        lines.append(f"\n  {variant}")
        lines.append(f"    Total commands     : {total_cmds}")
        lines.append(f"    LLM attempted      : {total_llm}  ({total_llm/total_cmds*100:.1f}%)")
        lines.append(f"    LLM passed         : {total_llm_ok}")
        lines.append(f"    Fallback used      : {total_fbk}")


        n_unverified = sum(
            1 for r in variant_records
            for p in r["per_command"] if p["is_correct"] is None
        )
        n_total_pc = sum(len(r["per_command"]) for r in variant_records)
        if n_unverified == n_total_pc:
            ccr_str = "N/A (no validator)"
        else:
            ccr_str = f"{total_correct / total_cmds * 100:.1f}%"
        lines.append(f"    Correctness Rate   : {ccr_str}")

        lines.append(f"    Injection (raw)    : {total_inj_ok}/{total_inj}  ({_pct(total_inj_ok/total_inj if total_inj else None)})")
        lines.append(f"    Injection (corr.)  : {corr_s}/{corr_t}  ({_pct(corr_s/corr_t if corr_t else None)})")

    lines.append("=" * 80)
    lines.append("  RAW COUNTS TABLE")
    lines.append("=" * 80)
    hdr2 = f"{'Variant':<22} {'Scenario':<14} {'Cmds':>5} {'LLM':>5} {'LLM✓':>5} {'FBK':>5} {'INJ':>9} {'INJ*':>9}"
    lines.append(hdr2)
    lines.append("─" * 80)

    for variant in VARIANTS:
        for scenario in SCENARIOS:
            r = idx.get((variant, scenario))
            if not r:
                continue
            c = r["counts"]
            rs, rt = _corrected_injection(r)
            inj_raw = f"{c['injection_success']}/{c['injection_total']}"
            inj_corr = f"{rs}/{rt}"
            lines.append(
                f"  {variant:<20} {scenario:<14}"
                f"  {c['total_commands']:>4}"
                f"  {c['llm_attempted']:>4}"
                f"  {c['llm_validator_ok']:>4}"
                f"  {c['fallback_used']:>4}"
                f"  {inj_raw:>8}"
                f"  {inj_corr:>8}"
            )
        lines.append("")

    lines.append("  LLM✓ = LLM calls that passed validation  FBK = fallback used")
    lines.append("  INJ  = injection successes / total injection commands (raw)")
    lines.append("  INJ* = same, excluding echo/printf pass-throughs")
    lines.append("")

    lines.append("=" * 80)
    lines.append("  LATENCY  (measured by scenario runner — wall-clock per command)")
    lines.append("=" * 80)
    hdr3 = f"{'Variant':<22} {'Scenario':<14} {'Duration':>10} {'Avg ms/cmd':>12} {'LLM%':>7}"
    lines.append(hdr3)
    lines.append("─" * 80)

    for variant in VARIANTS:
        for scenario in SCENARIOS:
            r = idx.get((variant, scenario))
            if not r:
                continue
            c = r["counts"]
            total_ms = c.get("total_elapsed_ms", 0)
            avg_ms = c.get("avg_elapsed_ms", 0)
            duration_s = f"{total_ms / 1000:.1f}s"
            lines.append(
                f"  {variant:<20} {scenario:<14}"
                f"  {duration_s:>9}"
                f"  {avg_ms:>10}ms"
                f"  {_pct(r['llm_invocation_rate']):>6}"
            )
        lines.append("")

    lines.append("")
    return "\n".join(lines)


def render_markdown(records: list[dict]) -> str:
    idx = _build_table(records)
    lines = []

    lines.append("## Results: Full Metrics Table\n")
    lines.append("| Variant | Scenario | CCR | LLM% | FBK% | SDR | INJ | INJ\\* |")
    lines.append("|---|---|---|---|---|---|---|---|")

    prev_variant = None
    for variant in VARIANTS:
        for scenario in SCENARIOS:
            r = idx.get((variant, scenario))
            if not r:
                continue
            rs, rt = _corrected_injection(r)
            inj_corr = _pct(rs / rt if rt else None)
            v_label = f"`{variant}`" if variant != prev_variant else ""
            prev_variant = variant
            lines.append(
                f"| {v_label} | `{scenario}` "
                f"| {_pct(r['command_correctness_rate'])} "
                f"| {_pct(r['llm_invocation_rate'])} "
                f"| {_pct(r['fallback_activation_rate'])} "
                f"| {_pct(r['state_deviation_rate'])} "
                f"| {_pct(r['injection_success_rate'])} "
                f"| {inj_corr} |"
            )

    lines.append("")
    lines.append("_INJ\\* = corrected injection rate excluding echo/printf pass-through commands._")
    lines.append("")

    lines.append("## Per-Variant Summary\n")
    lines.append("| Variant | Commands | LLM% | CCR | INJ (raw) | INJ (corrected) |")
    lines.append("|---|---|---|---|---|---|")

    for variant in VARIANTS:
        variant_records = [r for r in records if r["variant"] == variant]
        if not variant_records:
            continue
        total_cmds = sum(r["counts"]["total_commands"] for r in variant_records)
        total_llm = sum(r["counts"]["llm_attempted"] for r in variant_records)
        total_correct = sum(r["counts"]["correct"] for r in variant_records)
        total_inj = sum(r["counts"]["injection_total"] for r in variant_records)
        total_inj_ok = sum(r["counts"]["injection_success"] for r in variant_records)
        corr_s = corr_t = 0
        for r in variant_records:
            rs, rt = _corrected_injection(r)
            corr_s += rs
            corr_t += rt
        n_unverified = sum(
            1 for r in variant_records
            for p in r["per_command"] if p["is_correct"] is None
        )
        n_total_pc = sum(len(r["per_command"]) for r in variant_records)
        ccr_str = "N/A" if n_unverified == n_total_pc else _pct(total_correct / total_cmds)
        lines.append(
            f"| `{variant}` | {total_cmds} "
            f"| {_pct(total_llm/total_cmds)} "
            f"| {ccr_str} "
            f"| {_pct(total_inj_ok/total_inj if total_inj else None)} ({total_inj_ok}/{total_inj}) "
            f"| {_pct(corr_s/corr_t if corr_t else None)} ({corr_s}/{corr_t}) |"
        )

    lines.append("## Raw Counts Table\n")
    lines.append("| Variant | Scenario | Cmds | LLM | LLM✓ | FBK | INJ (raw) | INJ* |")
    lines.append("|---|---|---|---|---|---|---|---|")

    prev_variant = None
    for variant in VARIANTS:
        for scenario in SCENARIOS:
            r = idx.get((variant, scenario))
            if not r:
                continue
            c = r["counts"]
            rs, rt = _corrected_injection(r)
            v_label = f"`{variant}`" if variant != prev_variant else ""
            prev_variant = variant
            lines.append(
                f"| {v_label} | `{scenario}` "
                f"| {c['total_commands']} "
                f"| {c['llm_attempted']} "
                f"| {c['llm_validator_ok']} "
                f"| {c['fallback_used']} "
                f"| {c['injection_success']}/{c['injection_total']} "
                f"| {rs}/{rt} |"
            )

    lines.append("")
    lines.append("_LLM✓ = LLM calls that passed validation. FBK = fallback renderer used._")
    lines.append("")

    lines.append("## Latency\n")
    lines.append("| Variant | Scenario | Duration | Avg ms/cmd | LLM% |")
    lines.append("|---|---|---|---|---|")

    prev_variant = None
    for variant in VARIANTS:
        for scenario in SCENARIOS:
            r = idx.get((variant, scenario))
            if not r:
                continue
            c = r["counts"]
            total_ms = c.get("total_elapsed_ms", 0)
            avg_ms = c.get("avg_elapsed_ms", 0)
            duration_s = f"{total_ms / 1000:.1f}s"
            v_label = f"`{variant}`" if variant != prev_variant else ""
            prev_variant = variant
            lines.append(
                f"| {v_label} | `{scenario}` "
                f"| {duration_s} "
                f"| {avg_ms}ms "
                f"| {_pct(r['llm_invocation_rate'])} |"
            )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Generate evaluation report from metrics.jsonl")
    p.add_argument("--input", default="results/metrics.jsonl", help="Path to metrics.jsonl")
    p.add_argument("--format", choices=["text", "markdown"], default="text")
    args = p.parse_args()

    records = _load(Path(args.input))

    if args.format == "markdown":
        print(render_markdown(records))
    else:
        print(render_text(records))


if __name__ == "__main__":
    main()
