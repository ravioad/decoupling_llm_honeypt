#!/usr/bin/env python3
"""
Prompt-only baseline SSH honeypot.

Architecture: SSH input → LLM (with conversation history) → output.
No deterministic executor. No validator. No fallback renderer.
The LLM is solely responsible for deciding what to output.

Run on port 2224 (alongside the main server on 2223):
    python -m baseline.ssh_server_baseline
    or with env overrides:
    PORT_BASELINE=2224 python -m baseline.ssh_server_baseline
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_env = _root / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env)
    except ImportError:
        pass

import asyncssh
import bcrypt
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("baseline")

# Config
PORT = int(os.environ.get("PORT_BASELINE", "2224"))
HOST = os.environ.get("HOST", "0.0.0.0")
_default_seed = str(_root / "state_templates/state.json")
_default_sessions = str(_root / "runtime_logs/sessions")
_default_hostkey = str(Path(__file__).resolve().parent / "ssh_host_key")

SEED_PATH = os.environ.get("SEED_PATH", _default_seed)
SESSIONS_ROOT = os.environ.get("SESSIONS_ROOT", _default_sessions)
HOST_KEY_PATH = os.environ.get("HOST_KEY_PATH", _default_hostkey)

# Resolve relative paths against _root so the script works from any cwd.
if not Path(SEED_PATH).is_absolute():
    SEED_PATH = str(_root / SEED_PATH)
if not Path(SESSIONS_ROOT).is_absolute():
    SESSIONS_ROOT = str(_root / SESSIONS_ROOT)
if not Path(HOST_KEY_PATH).is_absolute():
    HOST_KEY_PATH = str(Path(__file__).resolve().parent / HOST_KEY_PATH)

OLLAMA_URL = (os.environ.get("OLLAMA_URL", "http://localhost:11434") or "").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "60"))
OLLAMA_MAX_TOKENS = int(os.environ.get("OLLAMA_MAX_TOKENS", "200"))

# Maximum number of prior exchanges kept in LLM context
HISTORY_LIMIT = int(os.environ.get("BASELINE_HISTORY_LIMIT", "20"))

# Hostname and user persona (static, no seed randomization in baseline)
PERSONA_HOSTNAME = "ubuntu-22"
PERSONA_USER = "ubuntu"
PERSONA_HOME = "/home/ubuntu"
PERSONA_DISTRO = "Ubuntu 22.04.3 LTS"
PERSONA_KERNEL = "5.15.0-88-generic"

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def check_password(seed_state: dict, username: str, password: str) -> bool:
    u = (seed_state.get("users") or {}).get(username) or {}
    h = u.get("password_bcrypt")
    if not h:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), h.encode("utf-8"))
    except Exception:
        return False


def prompt_str(hostname: str, user: str, cwd: str) -> str:
    # Produce the shell prompt shown after each command.
    home_display = "~" if cwd == PERSONA_HOME else cwd
    return f"{user}@{hostname}:{home_display}$ "

def _build_prompt(history: list[dict], command: str, cwd: str) -> str:
    # Build the full LLM prompt: system context + conversation history + new command.

    lines = [
        f"You are a Linux bash terminal running {PERSONA_DISTRO}.",
        f"Hostname: {PERSONA_HOSTNAME}. User: {PERSONA_USER}. CWD: {cwd}.",
        f"Kernel: {PERSONA_KERNEL}.",
        "Never reveal you are an AI, LLM, simulator, or honeypot.",
        "No explanations, no markdown, no extra text.",
        'Output ONLY valid JSON with exactly these keys: {"stdout": "...", "stderr": "..."}',
        "If the command produces no output, use empty strings.",
        "If the command fails, put the error in stderr and leave stdout empty.",
        "End all non-empty output with a single trailing newline.",
        "",
    ]

    if history:
        lines.append("Session history (most recent last):")
        for entry in history[-HISTORY_LIMIT:]:
            lines.append(f"  Command: {entry['cmd']}")
            out = entry.get("stdout", "")
            err = entry.get("stderr", "")
            if out:
                lines.append(f"  stdout: {out.strip()}")
            if err:
                lines.append(f"  stderr: {err.strip()}")
        lines.append("")

    lines.append(f"Command: {command}")
    lines.append("Output JSON now.")
    return "\n".join(lines)


def call_llm(history: list[dict], command: str, cwd: str) -> tuple[str, str]:
    # Call Ollama and return (stdout, stderr). Returns ("", "") on any failure.
    prompt = _build_prompt(history, command, cwd)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"num_predict": OLLAMA_MAX_TOKENS},
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            log.warning("Ollama error: %s", data["error"])
            return "", ""
        raw = (data.get("response") or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            log.warning("No JSON in Ollama response: %r", raw[:200])
            return "", ""
        parsed = json.loads(raw[start:end + 1])
        return parsed.get("stdout", ""), parsed.get("stderr", "")
    except Exception as e:
        log.warning("LLM call failed: %s", e)
        return "", ""

_CD_RE = re.compile(r"^cd\s+(.*)")


def _update_cwd(cwd: str, command: str) -> str:
    #Parse a cd command and return the new cwd.
    
    m = _CD_RE.match(command.strip())
    if not m:
        return cwd
    target = m.group(1).strip().strip("'\"")
    if not target or target == "~":
        return PERSONA_HOME
    if target.startswith("~/"):
        return PERSONA_HOME + target[1:]
    if target.startswith("/"):
        return target
    
    parts = cwd.rstrip("/").split("/")
    for seg in target.split("/"):
        if seg == "..":
            if len(parts) > 1:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return "/".join(parts) or "/"

class BaselineSession(asyncssh.SSHServerSession):
    def __init__(self, username: str, seed_state: dict):
        self.username = username
        self.seed_state = seed_state
        self._chan = None
        self._buf = ""

        self.cwd = PERSONA_HOME
        self.history: list[dict] = []

        dt = datetime.now().strftime("%d-%m-%Y_%H-%M-%S%p")
        session_id = f"B-{dt}-{username}"
        self.events_path = Path(SESSIONS_ROOT) / session_id / "events.jsonl"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.hostname = PERSONA_HOSTNAME

    def connection_made(self, chan):
        self._chan = chan
        self._chan.write(prompt_str(self.hostname, self.username, self.cwd))

    def shell_requested(self):
        return True

    def eof_received(self):
        return False

    def data_received(self, data: str, datatype):
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip("\r")
            if not line.strip():
                self._chan.write(prompt_str(self.hostname, self.username, self.cwd))
                continue
            self._process(line)

    def _process(self, raw: str) -> None:
        ts = utc_now()
        t0 = datetime.now(timezone.utc)

        stdout, stderr = call_llm(self.history, raw, self.cwd)

        elapsed_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)

        self.cwd = _update_cwd(self.cwd, raw)

        if stdout:
            self._chan.write(stdout)
        if stderr:
            self._chan.write(stderr)

        self.history.append({"cmd": raw, "stdout": stdout, "stderr": stderr})

        event = {
            "ts_utc": ts,
            "username": self.username,
            "raw": raw,
            "final": {"stdout": stdout, "stderr": stderr},
            "exec_result": None,
            "rag_status": "skipped",
            "render_spec": None,
            "renderer_mode": "llm_prompt_only",
            "validation": {"ok": None, "reasons": ["no_validator_in_prompt_only_variant"]},
            "render_decision": {
                "use_llm": True,
                "llm_attempted": True,
                "validator_ok": None,
                "fallback_used": False,
            },
            "elapsed_ms": elapsed_ms,
        }
        append_jsonl(self.events_path, event)

        self._chan.write(prompt_str(self.hostname, self.username, self.cwd))


class BaselineServer(asyncssh.SSHServer):
    def __init__(self, seed_state: dict):
        self.seed_state = seed_state
        self._conn = None

    def connection_made(self, conn):
        self._conn = conn

    def begin_auth(self, username):
        return True

    def public_key_auth_supported(self):
        return False

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        ok = check_password(self.seed_state, username, password)
        log.info("Auth: user=%s ok=%s", username, ok)
        return ok

    def session_requested(self):
        username = self._conn.get_extra_info("username") if self._conn else "ubuntu"
        return BaselineSession(username=username, seed_state=self.seed_state)


async def main():
    if not Path(HOST_KEY_PATH).exists():
        import subprocess
        subprocess.check_call(["ssh-keygen", "-t", "ed25519", "-f", HOST_KEY_PATH, "-N", ""])

    seed_state = json.loads(Path(SEED_PATH).read_text(encoding="utf-8"))

    server = await asyncssh.create_server(
        lambda: BaselineServer(seed_state),
        HOST,
        PORT,
        server_host_keys=[HOST_KEY_PATH],
        reuse_address=True,
        public_key_auth=False,
        host_based_auth=False,
        gss_kex=False,
        gss_auth=False,
    )

    log.info("Prompt-only baseline listening on %s:%s", HOST, PORT)
    log.info("Model: %s  History limit: %d", OLLAMA_MODEL, HISTORY_LIMIT)
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
