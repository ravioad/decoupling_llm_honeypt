from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def pct(num: int, den: int) -> str:
    if den == 0:
        return "0.0%"
    return f"{(100.0 * num / den):.1f}%"


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[warn] skipping bad json on line {line_no}: {e}")
    return events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events_path", help="Path to events.jsonl")
    parser.add_argument("--top", type=int, default=10, help="Top N families to print")
    args = parser.parse_args()

    path = Path(args.events_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing events file: {path}")

    events = load_events(path)

    total = 0
    llm_attempted = 0
    validator_ok_count = 0
    fallback_forced = 0
    fallback_skipped = 0
    llm_mode_count = 0

    family_total = Counter()
    family_attempted = Counter()
    family_accepted = Counter()
    family_forced_fallback = Counter()
    family_skipped = Counter()

    render_type_total = Counter()
    render_type_attempted = Counter()
    render_type_accepted = Counter()
    render_type_forced_fallback = Counter()
    render_type_skipped = Counter()

    renderer_mode_total = Counter()
    validation_reason_total = Counter()
    outcome_total = Counter()

    for ev in events:
        exec_result = ev.get("exec_result") or {}
        render_spec = ev.get("render_spec") or {}
        render_decision = ev.get("render_decision") or {}
        validation = ev.get("validation") or {}

        family = exec_result.get("family", "unknown")
        outcome = exec_result.get("outcome", "unknown")
        render_type = render_spec.get("render_type", "unknown")
        renderer_mode = ev.get("renderer_mode", "unknown")

        attempted = bool(render_decision.get("llm_attempted", False))
        validator_ok = bool(render_decision.get("validator_ok", False))
        used_fallback = bool(render_decision.get("fallback_used", False))

        total += 1
        family_total[family] += 1
        render_type_total[render_type] += 1
        renderer_mode_total[renderer_mode] += 1
        outcome_total[outcome] += 1

        if attempted:
            llm_attempted += 1
            family_attempted[family] += 1
            render_type_attempted[render_type] += 1

        if validator_ok:
            validator_ok_count += 1
            family_accepted[family] += 1
            render_type_accepted[render_type] += 1

        if used_fallback:
            fallback_forced += 1
            family_forced_fallback[family] += 1
            render_type_forced_fallback[render_type] += 1

        if renderer_mode == "fallback_skipped":
            fallback_skipped += 1
            family_skipped[family] += 1
            render_type_skipped[render_type] += 1

        if renderer_mode == "llm":
            llm_mode_count += 1

        for reason in validation.get("reasons", []):
            validation_reason_total[reason] += 1

    print("\n=== OVERALL ===")
    print(f"total_commands         : {total}")
    print(f"llm_attempted          : {llm_attempted} ({pct(llm_attempted, total)})")
    print(f"llm_accepted           : {llm_mode_count} ({pct(llm_mode_count, total)})")
    print(
        f"validator_ok           : {validator_ok_count} ({pct(validator_ok_count, total)})"
    )
    print(f"fallback_forced        : {fallback_forced} ({pct(fallback_forced, total)})")
    print(
        f"fallback_skipped       : {fallback_skipped} ({pct(fallback_skipped, total)})"
    )

    print("\n=== RATES ===")
    print(f"accept_rate_given_llm  : {pct(llm_mode_count, llm_attempted)}")
    print(f"forced_fallback_rate   : {pct(fallback_forced, llm_attempted)}")
    print(f"skip_rate              : {pct(fallback_skipped, total)}")

    print("\n=== BY RENDERER MODE ===")
    for mode, count in renderer_mode_total.most_common():
        print(f"{mode:<18} {count:>5} ({pct(count, total)})")

    print("\n=== BY OUTCOME ===")
    for outcome, count in outcome_total.most_common():
        print(f"{outcome:<18} {count:>5} ({pct(count, total)})")

    print("\n=== BY FAMILY ===")
    header = (
        f"{'family':<14} {'total':>5} {'attempted':>10} "
        f"{'accepted':>10} {'forced_fb':>10} {'skipped':>8}"
    )
    print(header)
    print("-" * len(header))
    for family, count in family_total.most_common(args.top):
        print(
            f"{family:<14} "
            f"{count:>5} "
            f"{family_attempted[family]:>10} "
            f"{family_accepted[family]:>10} "
            f"{family_forced_fallback[family]:>10} "
            f"{family_skipped[family]:>8}"
        )

    print("\n=== BY RENDER TYPE ===")
    header = (
        f"{'render_type':<14} {'total':>5} {'attempted':>10} "
        f"{'accepted':>10} {'forced_fb':>10} {'skipped':>8}"
    )
    print(header)
    print("-" * len(header))
    for rt, count in render_type_total.most_common():
        print(
            f"{rt:<14} "
            f"{count:>5} "
            f"{render_type_attempted[rt]:>10} "
            f"{render_type_accepted[rt]:>10} "
            f"{render_type_forced_fallback[rt]:>10} "
            f"{render_type_skipped[rt]:>8}"
        )

    if validation_reason_total:
        print("\n=== VALIDATION FAILURE REASONS ===")
        for reason, count in validation_reason_total.most_common():
            print(f"{reason:<40} {count:>5}")


if __name__ == "__main__":
    main()
