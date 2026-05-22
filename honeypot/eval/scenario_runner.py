#!/usr/bin/env python3
"""
Scenario runner for honeypot evaluation.

Connects to the honeypot over SSH, executes commands from a YAML scenario file,
and writes a run_manifest.jsonl + run_summary.json to the output directory.

Usage:
    python -m eval.scenario_runner \\
        --scenario eval/scenarios/normal.yaml \\
        --output runtime_logs/eval/state_isolated/normal/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko
import yaml

PROMPT_RE = re.compile(r"[a-z_][a-z0-9_-]*@[a-zA-Z0-9_.-]+:[^\r\n]*[#$] $")

SUDO_PROMPT_RE = re.compile(r"\[sudo\] password for [^:]+:\s*$")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def _apply_backspaces(s: str) -> str:
    """Apply terminal backspace sequences."""
    out: list[str] = []
    for ch in s:
        if ch == "\x08":
            if out:
                out.pop()
        else:
            out.append(ch)
    return "".join(out)


def _read_until_prompt(
    chan: paramiko.Channel, timeout: float = 30.0
) -> tuple[str, str]:
    """Read channel output until a shell or sudo password prompt is detected."""
    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if chan.recv_ready():
            chunk = chan.recv(8192).decode("utf-8", errors="replace")
            buf += chunk
            if PROMPT_RE.search(buf):
                return buf, "shell"
            if SUDO_PROMPT_RE.search(buf):
                return buf, "sudo_password"
        else:
            time.sleep(0.05)
    raise TimeoutError(
        f"Prompt not detected within {timeout}s. Buffer tail: {buf[-200:]!r}"
    )


def _clean_output(raw: str, cmd: str) -> str:
    # 1. Simulate backspace sequences from PTY echo rewriting
    out = _apply_backspaces(raw)
    # 2. Strip ANSI escape codes
    out = ANSI_RE.sub("", out)
    # 3. Normalise line endings
    out = out.replace("\r\n", "\n").replace("\r", "\n")

    lines = out.split("\n")

    # 4. Drop any leading line that is just the echoed command
    if lines and lines[0].strip() == cmd.strip():
        lines = lines[1:]

    # 5. Drop trailing prompt line(s)
    while lines and PROMPT_RE.search(lines[-1]):
        lines.pop()

    return "\n".join(lines).strip("\n")


def run_scenario(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    scenario_path: Path,
    output_dir: Path,
    command_timeout: float = 30.0,
    verbose: bool = True,
) -> Path:
    """Run a scenario YAML against the honeypot and write run_manifest.jsonl + run_summary.json."""
    scenario = yaml.safe_load(scenario_path.read_text())
    commands: list[dict] = scenario.get("commands", [])
    variant = scenario.get("variant", scenario_path.stem)
    description = scenario.get("description", "")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "run_manifest.jsonl"
    summary_path = output_dir / "run_summary.json"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    run_start = datetime.now(timezone.utc)
    results: list[dict] = []

    try:
        client.connect(
            host,
            port=port,
            username=username,
            password=password,
            timeout=10,
            look_for_keys=False,
            allow_agent=False,
        )
        chan = client.invoke_shell(term="dumb", width=220, height=50)

        # Consume the initial prompt before sending any commands
        try:
            _read_until_prompt(chan, timeout=15.0)
        except TimeoutError as e:
            print(f"[WARN] Initial prompt not detected: {e}", file=sys.stderr)

        with manifest_path.open("w") as mf:
            for idx, entry in enumerate(commands):
                cmd: str = entry["cmd"]
                cmd_type: str = entry.get("type", "normal")
                sudo_password: str = entry.get("sudo_password", password)
                expect: dict = {
                    k: v for k, v in entry.items() if k.startswith("expect_")
                }

                ts = datetime.now(timezone.utc).isoformat()
                t0 = time.monotonic()

                chan.send(cmd + "\n")

                timeout_hit = False
                raw = ""
                try:
                    raw, kind = _read_until_prompt(chan, timeout=command_timeout)
                    # Handle sudo password challenge transparently
                    if kind == "sudo_password":
                        chan.send(sudo_password + "\n")
                        raw2, _ = _read_until_prompt(chan, timeout=command_timeout)
                        raw += raw2
                except TimeoutError as e:
                    raw = str(e)
                    timeout_hit = True

                elapsed_ms = int((time.monotonic() - t0) * 1000)
                clean = _clean_output(raw, cmd)

                record = {
                    "idx": idx,
                    "ts_utc": ts,
                    "cmd": cmd,
                    "type": cmd_type,
                    "output": clean,
                    "elapsed_ms": elapsed_ms,
                    "timeout_hit": timeout_hit,
                    "expect": expect,
                }
                results.append(record)
                mf.write(json.dumps(record, ensure_ascii=False) + "\n")
                mf.flush()

                if verbose:
                    status = "TIMEOUT" if timeout_hit else "ok"
                    print(
                        f"  [{idx+1:3d}/{len(commands)}] {elapsed_ms:5d}ms"
                        f"  {cmd_type:<12s}  [{status}]  {cmd[:70]}"
                    )
    finally:
        client.close()

    run_end = datetime.now(timezone.utc)
    duration_s = (run_end - run_start).total_seconds()

    summary = {
        "variant": variant,
        "scenario": scenario_path.stem,
        "description": description,
        "host": host,
        "port": port,
        "username": username,
        "run_start_utc": run_start.isoformat(),
        "run_end_utc": run_end.isoformat(),
        "duration_s": round(duration_s, 2),
        "n_commands": len(results),
        "n_timeout": sum(1 for r in results if r["timeout_hit"]),
        "output_dir": str(output_dir),
        "manifest": str(manifest_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2))

    print(
        f"\nScenario '{scenario_path.stem}' complete."
        f" {len(results)} commands in {duration_s:.1f}s."
        f" Output: {output_dir}"
    )
    return output_dir


def main() -> None:
    p = argparse.ArgumentParser(
        description="Run a YAML scenario against the honeypot over SSH."
    )
    p.add_argument("--host", default="localhost", help="Honeypot SSH host")
    p.add_argument("--port", type=int, default=2223, help="Honeypot SSH port")
    p.add_argument("--username", default="ubuntu", help="SSH username")
    p.add_argument("--password", default="helloworld", help="SSH password")
    p.add_argument("--scenario", required=True, help="Path to scenario YAML file")
    p.add_argument("--output", required=True, help="Output directory for results")
    p.add_argument(
        "--timeout", type=float, default=30.0, help="Per-command timeout in seconds"
    )
    p.add_argument("--quiet", action="store_true", help="Suppress per-command output")
    args = p.parse_args()

    run_scenario(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        scenario_path=Path(args.scenario),
        output_dir=Path(args.output),
        command_timeout=args.timeout,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
