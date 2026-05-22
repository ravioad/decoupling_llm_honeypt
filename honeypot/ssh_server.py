from __future__ import annotations

import argparse
from pathlib import Path

_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    from dotenv import load_dotenv

    load_dotenv(_env)
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[ssh] %(message)s")
log = logging.getLogger(__name__)

import asyncssh
import bcrypt

from core.state_store import StateStore
from executor.executor import execute_with_state
from rag.rag_client import get_ragctx
from core.render_spec_builder import build_render_spec
from core.renderer_fallback import render_fallback
from validator.validate import validate_output
from renderer.renderer_llm import should_use_llm

SEED_PATH = os.environ.get("SEED_PATH", "state_templates/state.json")
SESSIONS_ROOT = os.environ.get("SESSIONS_ROOT", "runtime_logs/sessions")
HOST_KEY_PATH = os.environ.get("HOST_KEY_PATH", "ssh_host_key")
FORCE_NEW_SESSION = os.environ.get("FORCE_NEW_SESSION", "false").lower() == "true"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "2222"))

@dataclass
class _ShellSeg:
    cmd: str
    op_before: str = ""     
    redirect_to: Optional[str] = None
    is_append: bool = False


def _parse_shell_line(raw: str) -> list[_ShellSeg]:
    """
    Parse a shell input line into executable segments.

    Handles:
    - ; && ||  : command chaining with exit-code semantics
    - |        : pipe, execute left side only, discard right side
    - > >>     : redirect stdout to virtual FS file
    """
    if not raw.strip():
        return [_ShellSeg(cmd="")]

    # split on chain operators to get (chunk, op_after) pairs
    chain_parts: list[tuple[str, str]] = []
    current = ""
    i = 0
    while i < len(raw):
        if raw[i : i + 2] in ("&&", "||"):
            chain_parts.append((current.strip(), raw[i : i + 2]))
            current = ""
            i += 2
        elif raw[i] == ";":
            chain_parts.append((current.strip(), ";"))
            current = ""
            i += 1
        else:
            current += raw[i]
            i += 1
    chain_parts.append((current.strip(), ""))

    # for each chunk, strip pipe right side and extract redirect
    segments: list[_ShellSeg] = []
    for idx, (chunk, _op_after) in enumerate(chain_parts):
        if not chunk:
            continue

        op_before = chain_parts[idx - 1][1] if idx > 0 else ""

        # Strip pipe right side, execute left command only
        if "|" in chunk:
            chunk = chunk.split("|")[0].strip()

        # Extract redirect, check >> before >
        redirect_to: Optional[str] = None
        is_append = False

        m = re.search(r">>\s*(\S+)", chunk)
        if m:
            redirect_to = m.group(1)
            is_append = True
            chunk = chunk[: m.start()].strip()
        else:
            m = re.search(r"(?<![>])>\s*(\S+)", chunk)
            if m:
                redirect_to = m.group(1)
                chunk = chunk[: m.start()].strip()

        segments.append(
            _ShellSeg(
                cmd=chunk,
                op_before=op_before,
                redirect_to=redirect_to,
                is_append=is_append,
            )
        )

    return segments if segments else [_ShellSeg(cmd="")]


def _apply_redirect(
    stdout: str,
    target: str,
    is_append: bool,
    state: dict,
    cwd: str,
    user: str,
) -> None:
    """Write or append stdout to a file in the virtual filesystem."""
    from core.path_resolver import resolve_path

    path = resolve_path(cwd, target)
    now_z = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    nodes = state.setdefault("fs", {}).setdefault("nodes", {})
    content_store = state.setdefault("content_store", {})

    existing_node = nodes.get(path)
    if is_append and existing_node and existing_node.get("content_ref"):
        content_ref = existing_node["content_ref"]
        new_content = content_store.get(content_ref, "") + stdout
    else:
        content_ref = f"content/redir_{hashlib.md5(path.encode()).hexdigest()[:8]}"
        new_content = stdout

    content_store[content_ref] = new_content

    users = state.get("users") or {}
    u = users.get(user) or {}
    gid = u.get("gid", 1000)
    groups_map = state.get("groups") or {}
    g = groups_map.get(str(gid)) or groups_map.get(gid) or {}
    group_name = g.get("name", user)

    nodes[path] = {
        "type": "file",
        "mode": "0644",
        "owner": user,
        "group": group_name,
        "size": len(new_content),
        "mtime": now_z,
        "content_ref": content_ref,
    }

    parent = path.rsplit("/", 1)[0] if "/" in path else "/"
    parent = parent if parent else "/"
    parent_node = nodes.get(parent)
    if isinstance(parent_node, dict):
        children = parent_node.setdefault("children", [])
        if path not in children:
            children.append(path)
        parent_node["mtime"] = now_z


def _randomize_session_seed(state: dict) -> None:
    suffix = "".join(random.choices("0123456789abcdef", k=4))

    meta = state.setdefault("meta", {})
    base_hostname = meta.get("hostname", "ubuntu-22")
    new_hostname = f"{base_hostname}-{suffix}"
    meta["hostname"] = new_hostname

    network = state.get("network") or {}
    for iface in network.get("interfaces") or []:
        if iface.get("name") not in ("lo", None):
            inet = iface.get("inet", "192.168.56.23/24")
            parts = inet.split(".")
            if len(parts) == 4:
                cidr = parts[3].split("/")[1] if "/" in parts[3] else "24"
                new_octet = random.randint(10, 254)
                parts[3] = f"{new_octet}/{cidr}"
                iface["inet"] = ".".join(parts)
                base = ".".join(p.split("/")[0] for p in parts[:3])
                iface["broadcast"] = f"{base}.255"
            break

    cs = state.get("content_store") or {}
    for key in ("content/hostname_v1", "content/hosts_v1", "content/proc_version_v1"):
        if key in cs:
            cs[key] = cs[key].replace(base_hostname, new_hostname)

def latest_session_id_for_username(username: str) -> Optional[str]:
    root = Path(SESSIONS_ROOT)
    if not root.exists():
        return None

    candidates = []

    for p in root.iterdir():
        if not p.is_dir():
            continue

        name = p.name

        if not name.startswith("S-") or not name.endswith(f"-{username}"):
            continue

        state_path = p / "state.json"
        if not state_path.exists():
            continue

        try:
            mtime = state_path.stat().st_mtime
        except Exception:
            continue

        candidates.append((mtime, name))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def format_cwd_for_prompt(state: dict) -> str:
    session = state.get("session") or {}
    users = state.get("users") or {}

    cwd = session.get("cwd", "/")
    user = session.get("active_user", "ubuntu")
    home = (users.get(user) or {}).get("home", f"/home/{user}")

    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        return "~" + cwd[len(home) :]
    return cwd


def prompt_str(state: dict) -> str:
    session = state.get("session") or {}
    meta = state.get("meta") or {}
    users = state.get("users") or {}

    user = session.get("active_user", "ubuntu")
    host = meta.get("hostname", "web01")
    cwd_display = format_cwd_for_prompt(state)

    is_root = (users.get(user) or {}).get("is_root", False)
    suffix = "#" if is_root else "$"

    return f"{user}@{host}:{cwd_display}{suffix} "


def check_password_bcrypt(seed_state: dict, username: str, password: str) -> bool:
    users = seed_state.get("users") or {}
    u = users.get(username)
    if not u:
        return False

    h = u.get("password_bcrypt")
    if not isinstance(h, str) or not h:
        return False

    try:
        return bcrypt.checkpw(password.encode("utf-8"), h.encode("utf-8"))
    except Exception:
        return False


class HoneyServer(asyncssh.SSHServer):
    """Auth-only server object returns a per-user session after auth."""

    def __init__(self, seed_state: dict, auth_log: Path):
        self.seed_state = seed_state
        self.auth_log = auth_log
        self._conn: Optional[asyncssh.SSHServerConnection] = None

    def connection_made(self, conn):
        self._conn = conn
        peer = conn.get_extra_info("peername")
        log.info("Connection from %s", peer)

    def begin_auth(self, username):
        return True

    def public_key_auth_supported(self):
        return False

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        ok = check_password_bcrypt(self.seed_state, username, password)
        log.info("Auth attempt: user=%s ok=%s", username, ok)

        peer = self._conn.get_extra_info("peername") if self._conn else None
        ip = peer[0] if isinstance(peer, (tuple, list)) and peer else None

        append_jsonl(
            self.auth_log,
            {
                "ts_utc": utc_now(),
                "event": "auth_attempt",
                "username": username,
                "remote_ip": ip,
                "ok": ok,
            },
        )

        return ok

    def session_requested(self):
        username = self._conn.get_extra_info("username") if self._conn else "ubuntu"
        return HoneySession(username=username)


class HoneySession(asyncssh.SSHServerSession):
    def __init__(self, username: str):
        self.username = username
        self._chan = None
        self._buf = ""

        self.store: Optional[StateStore] = None
        self.events_path: Optional[Path] = None
        self._pending_sudo: Optional[dict] = None

    def connection_made(self, chan):
        self._chan = chan

        try:
            dt = datetime.now().strftime("%d-%m-%Y_%H-%M-%S%p")
            new_session_id = f"S-{dt}-{self.username}"

            existing = (
                None
                if FORCE_NEW_SESSION
                else latest_session_id_for_username(self.username)
            )
            session_id = existing if existing else new_session_id
            is_new_session = existing is None

            self.store = StateStore.open_or_create(
                seed_path=SEED_PATH,
                sessions_root=SESSIONS_ROOT,
                session_id=session_id,
                resume=existing is not None,
            )

            self.store.state.setdefault("session", {})["active_user"] = self.username

            u = (self.store.state.get("users") or {}).get(self.username) or {}
            home = u.get("home", f"/home/{self.username}")
            self.store.state["session"].setdefault("cwd", home)

            if is_new_session:
                _randomize_session_seed(self.store.state)

            self.store.save()

            self.events_path = self.store.ensure_events_log()

            self._chan.write(prompt_str(self.store.state))
        except Exception as e:
            log.exception("Session setup failed for %s: %s", self.username, e)
            try:
                self._chan.write(f"Session error: {e}\n")
            except Exception:
                pass
            raise

    def shell_requested(self):
        return True

    def eof_received(self):
        return False

    def _execute_and_render(self, cmd: str) -> tuple[str, str, int, dict]:
        exec_result = execute_with_state(cmd, self.store.state)

        USE_LLM = (
            os.getenv("USE_LLM_RENDERER", "false").lower() == "true"
            and os.getenv("FORCE_DETERMINISTIC", "false").lower() != "true"
        )

        spec = build_render_spec(exec_result, None)
        will_use_llm = USE_LLM and should_use_llm(exec_result, spec)
        ragctx = None

        if will_use_llm:
            ragctx = get_ragctx(
                collection="shell_context",
                family=exec_result.family,
                outcome=exec_result.outcome,
                wanted_types=["error_phrase", "format_hint"],
                query_text=f"{exec_result.family} {exec_result.outcome}",
                k=3,
            )
            spec = build_render_spec(exec_result, ragctx)

        llm_attempted = False
        validator_ok = False
        fallback_used = False
        reasons: list[str] = []

        if will_use_llm:
            from renderer.renderer_llm import render_llm

            llm_attempted = True
            if os.getenv("FORCE_BAD_LLM", "false").lower() == "true":
                candidate_stdout, candidate_stderr = "bad output\n", ""
            else:
                candidate_stdout, candidate_stderr = render_llm(spec)

            validator_ok, reasons = validate_output(
                spec, candidate_stdout, candidate_stderr
            )
            if validator_ok:
                stdout, stderr = candidate_stdout, candidate_stderr
                renderer_mode = "llm"
            else:
                stdout, stderr = render_fallback(spec)
                fallback_used = True
                renderer_mode = "fallback_forced"
        else:
            stdout, stderr = render_fallback(spec)
            validator_ok, reasons = validate_output(spec, stdout, stderr)
            renderer_mode = "fallback_skipped"

        log.debug(
            "family=%s render_type=%s llm=%s valid=%s mode=%s",
            spec.family,
            spec.render_type,
            llm_attempted,
            validator_ok,
            renderer_mode,
        )

        if stdout and not stdout.strip():
            stdout = ""
        if stderr and not stderr.strip():
            stderr = ""

        log_dict = {
            "cmd": cmd,
            "exec_result": exec_result.__dict__,
            "rag_status": ragctx.get("status") if ragctx else "skipped",
            "render_spec": spec.__dict__,
            "renderer_mode": renderer_mode,
            "validation": {"ok": validator_ok, "reasons": reasons},
            "render_decision": {
                "use_llm": will_use_llm,
                "llm_attempted": llm_attempted,
                "validator_ok": validator_ok,
                "fallback_used": fallback_used,
            },
        }

        return stdout, stderr, exec_result.exit_code, log_dict

    def _start_sudo_flow(self, raw: str) -> None:
        import shlex
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()

        args = tokens[1:]
        inner_tokens: list[str] = []
        kind = "run"
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-k":
                self.store.state.setdefault("session", {})["last_exit_code"] = 0
                self.store.save()
                self._chan.write(prompt_str(self.store.state))
                return
            elif a in ("-l", "--list"):
                kind = "list"
            elif a in ("-v", "--validate"):
                kind = "validate"
            elif a in ("-i", "--login", "-s", "--shell"):
                kind = "shell"
                inner_tokens = []
            elif a in ("su",):
                kind = "shell"
                inner_tokens = []
            elif a in ("-u", "--user"):
                i += 1
            elif a.startswith("-"):
                pass
            else:
                inner_tokens = args[i:]
                break
            i += 1

        if inner_tokens and inner_tokens[0] in ("su", "bash", "sh", "zsh"):
            kind = "shell"
            inner_tokens = []

        self._pending_sudo = {
            "raw": raw,
            "inner": " ".join(inner_tokens),
            "kind": kind,
            "attempts": 0,
        }
        user = (self.store.state.get("session") or {}).get("active_user", self.username)
        self._chan.write(f"[sudo] password for {user}: ")

    def _handle_sudo_password(self, password: str) -> None:
        pending = self._pending_sudo
        assert pending is not None

        seed_state = self.store.state
        user = (seed_state.get("session") or {}).get("active_user", self.username)
        correct = check_password_bcrypt(seed_state, user, password)

        if not correct:
            pending["attempts"] += 1
            if pending["attempts"] < 3:
                self._chan.write(f"\nSorry, try again.\n[sudo] password for {user}: ")
                return
            # Third failure
            self._pending_sudo = None
            self._chan.write(
                f"\nSorry, try again.\n"
                f"sudo: {pending['attempts']} incorrect password attempts\n"
            )
            self.store.state.setdefault("session", {})["last_exit_code"] = 1
            self.store.save()
            self._chan.write(prompt_str(self.store.state))
            return

        self._pending_sudo = None
        self._chan.write("\n")
        self._execute_sudo_inner(pending)

    def _execute_sudo_inner(self, pending: dict) -> None:
        kind = pending["kind"]
        session = self.store.state.setdefault("session", {})
        meta = self.store.state.get("meta") or {}
        hostname = meta.get("hostname", "ubuntu-22")
        users = self.store.state.get("users") or {}
        prev_user = session.get("active_user", self.username)

        if kind == "validate":
            # sudo -v: just refresh timestamp, no output
            session["last_exit_code"] = 0
            self.store.save()
            self._log_deterministic_event(pending["raw"], "", "", 0)
            self._chan.write(prompt_str(self.store.state))
            return

        if kind == "list":
            out = (
                f"Matching Defaults entries for {prev_user} on {hostname}:\n"
                f"    env_reset, mail_badpass,\n"
                f"    secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
                f"\nUser {prev_user} may run the following commands on {hostname}:\n"
                f"    (ALL : ALL) ALL\n"
            )
            self._chan.write(out)
            session["last_exit_code"] = 0
            self.store.save()
            self._log_deterministic_event(pending["raw"], out, "", 0)
            self._chan.write(prompt_str(self.store.state))
            return

        if kind == "shell":
            session["active_user"] = "root"
            root_home = (users.get("root") or {}).get("home", "/root")
            session["cwd"] = root_home
            session["last_exit_code"] = 0
            self.store.save()
            self._log_deterministic_event(pending["raw"], "", "", 0)
            self._chan.write(prompt_str(self.store.state))
            return

        inner = pending["inner"].strip()
        if not inner:
            session["active_user"] = "root"
            root_home = (users.get("root") or {}).get("home", "/root")
            session["cwd"] = root_home
            session["last_exit_code"] = 0
            self.store.save()
            self._log_deterministic_event(pending["raw"], "", "", 0)
            self._chan.write(prompt_str(self.store.state))
            return

        session["active_user"] = "root"
        try:
            stdout, stderr, exit_code, log_dict = self._execute_and_render(inner)
        finally:
            session["active_user"] = prev_user

        if stdout:
            self._chan.write(stdout if stdout.endswith("\n") else stdout + "\n")
        if stderr:
            self._chan.write(stderr if stderr.endswith("\n") else stderr + "\n")

        session["last_exit_code"] = exit_code
        self.store.save()

        event: dict = {
            "ts_utc": utc_now(),
            "username": self.username,
            "raw": pending["raw"],
            "sudo_inner": inner,
            "final": {"stdout": stdout, "stderr": stderr},
        }
        event.update({k: v for k, v in log_dict.items() if k != "cmd"})
        append_jsonl(self.events_path, event)

        self._chan.write(prompt_str(self.store.state))

    def _log_deterministic_event(
        self, raw: str, stdout: str, stderr: str, exit_code: int, family: str = "sudo"
    ) -> None:
        """Log sudo bypass paths (list/shell/validate) that skip _execute_and_render."""
        if not self.events_path:
            return
        event: dict = {
            "ts_utc": utc_now(),
            "username": self.username,
            "raw": raw,
            "final": {"stdout": stdout, "stderr": stderr},
            "exec_result": {"family": family, "outcome": "ok", "exit_code": exit_code},
            "render_decision": {
                "use_llm": False,
                "llm_attempted": False,
                "validator_ok": True,
                "fallback_used": False,
            },
            "renderer_mode": "deterministic_sudo",
        }
        append_jsonl(self.events_path, event)

    def data_received(self, data, datatype):
        self._buf += data

        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            raw = line.rstrip("\r")

            if self._pending_sudo is not None:
                self._handle_sudo_password(raw.strip())
                continue

            if raw.strip() in {"exit", "logout"}:
                session = (self.store.state.get("session") or {}) if self.store else {}
                if session.get("active_user") == "root":
                    # Drop back to the original login user rather than disconnect
                    users = self.store.state.get("users") or {}
                    home = (users.get(self.username) or {}).get(
                        "home", f"/home/{self.username}"
                    )
                    self.store.state["session"]["active_user"] = self.username
                    self.store.state["session"]["cwd"] = home
                    self.store.state["session"]["last_exit_code"] = 0
                    self.store.save()
                    self._log_deterministic_event(raw.strip(), "", "", 0, "exit")
                    self._chan.write("exit\n")
                    self._chan.write(prompt_str(self.store.state))
                    continue
                self._chan.write("logout\n")
                self._chan.close()
                return

            if not self.store or not self.events_path:
                return

            if raw.strip().startswith("sudo") and (
                len(raw.strip()) == 4 or raw.strip()[4] in (" ", "\t")
            ):
                self._start_sudo_flow(raw.strip())
                continue

            try:
                segments = _parse_shell_line(raw)
                combined_stdout = ""
                combined_stderr = ""
                sub_results: list[dict] = []
                last_exit_code = 0

                for i, seg in enumerate(segments):
                    if i > 0:
                        if seg.op_before == "&&" and last_exit_code != 0:
                            continue
                        if seg.op_before == "||" and last_exit_code == 0:
                            continue

                    stdout, stderr, exit_code, log_dict = self._execute_and_render(
                        seg.cmd
                    )
                    last_exit_code = exit_code

                    if seg.redirect_to and stdout is not None:
                        cwd = (self.store.state.get("session") or {}).get("cwd", "/")
                        user = (self.store.state.get("session") or {}).get(
                            "active_user", "ubuntu"
                        )
                        _apply_redirect(
                            stdout,
                            seg.redirect_to,
                            seg.is_append,
                            self.store.state,
                            cwd,
                            user,
                        )
                        stdout = ""

                    combined_stdout += stdout
                    combined_stderr += stderr
                    sub_results.append(log_dict)

                if combined_stdout:
                    self._chan.write(
                        combined_stdout
                        if combined_stdout.endswith("\n")
                        else combined_stdout + "\n"
                    )
                if combined_stderr:
                    self._chan.write(
                        combined_stderr
                        if combined_stderr.endswith("\n")
                        else combined_stderr + "\n"
                    )

                self.store.state.setdefault("session", {})[
                    "last_exit_code"
                ] = last_exit_code
                self.store.save()

                event: dict = {
                    "ts_utc": utc_now(),
                    "username": self.username,
                    "raw": raw,
                    "final": {"stdout": combined_stdout, "stderr": combined_stderr},
                }
                if len(sub_results) == 1:
                    event.update(
                        {k: v for k, v in sub_results[0].items() if k != "cmd"}
                    )
                else:
                    event["segments"] = sub_results

                append_jsonl(self.events_path, event)

                self._chan.write(prompt_str(self.store.state))
            except Exception as e:
                err_msg = f"Error: {e}\n{traceback.format_exc()}"
                self._chan.write(err_msg)
                self._chan.write(prompt_str(self.store.state))


def ensure_host_key():
    if Path(HOST_KEY_PATH).exists():
        return
    import subprocess

    subprocess.check_call(
        ["ssh-keygen", "-t", "ed25519", "-f", HOST_KEY_PATH, "-N", ""]
    )


async def main():
    global FORCE_NEW_SESSION

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Do not resume, always create a fresh session",
    )
    args = parser.parse_args()
    if args.new_session:
        FORCE_NEW_SESSION = True
    ensure_host_key()

    seed_state = json.loads(Path(SEED_PATH).read_text(encoding="utf-8"))
    auth_log = Path(SESSIONS_ROOT) / "_auth.jsonl"

    server = await asyncssh.create_server(
        lambda: HoneyServer(seed_state, auth_log),
        HOST,
        PORT,
        server_host_keys=[HOST_KEY_PATH],
        reuse_address=True,
        public_key_auth=False,
        host_based_auth=False,
        gss_kex=False,
        gss_auth=False,
    )

    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    log.info("Listening on %s", addrs)

    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
