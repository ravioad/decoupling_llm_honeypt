from __future__ import annotations

import copy
from typing import Any, Dict
from core.types import ExecResult
from core.fs_model import FsModel
from core.permissions import PermissionChecker
from core.path_resolver import resolve_path
from datetime import datetime, timezone


def _utc_now_z() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parent_path(path: str) -> str:
    if path == "/":
        return "/"
    parent = path.rsplit("/", 1)[0]
    return parent if parent else "/"


def mode_to_symbolic(mode_str: str, node_type: str) -> str:
    """Convert octal mode string (e.g. "0644") to symbolic (e.g. "-rw-r--r--")."""
    try:
        mode = int(mode_str, 8)
    except Exception:
        mode = 0

    type_ch = "d" if node_type == "dir" else "-"

    def tri(bits_read: int, bits_write: int, bits_exec: int) -> str:
        r = "r" if (mode & bits_read) else "-"
        w = "w" if (mode & bits_write) else "-"
        x = "x" if (mode & bits_exec) else "-"
        return r + w + x

    owner = tri(0o400, 0o200, 0o100)
    group = tri(0o040, 0o020, 0o010)
    other = tri(0o004, 0o002, 0o001)

    return type_ch + owner + group + other


SUPPORTED = {
    "pwd",
    "whoami",
    "ls",
    "cat",
    "cd",
    "hostname",
    "uname",
    "id",
    "echo",
    "date",
    "uptime",
    "env",
    "which",
    "clear",
    "ps",
    "touch",
    "mkdir",
    "rm",
    "mv",
    "cp",
    "ip",
    "ifconfig",
    "sudo",
}

BIN_PATHS = {
    "ls": "/usr/bin/ls",
    "cat": "/usr/bin/cat",
    "cd": "cd",
    "pwd": "/usr/bin/pwd",
    "echo": "/usr/bin/echo",
    "date": "/usr/bin/date",
    "uname": "/usr/bin/uname",
    "hostname": "/usr/bin/hostname",
    "id": "/usr/bin/id",
    "whoami": "/usr/bin/whoami",
    "env": "/usr/bin/env",
    "uptime": "/usr/bin/uptime",
    "which": "/usr/bin/which",
    "clear": "/usr/bin/clear",
    "touch": "/usr/bin/touch",
    "mkdir": "/usr/bin/mkdir",
    "rm": "/usr/bin/rm",
    "mv": "/usr/bin/mv",
    "cp": "/usr/bin/cp",
    "ip": "/usr/sbin/ip",
    "ifconfig": "/usr/sbin/ifconfig",
    "sudo": "/usr/bin/sudo",
}


def _family(raw: str) -> str:
    s = raw.strip()
    return s.split()[0] if s else "empty"


def _args(raw: str) -> list[str]:
    s = raw.strip()
    return s.split()[1:] if s else []


def _result(
    raw: str,
    family: str,
    outcome: str,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    target_path: str | None = None,
) -> ExecResult:
    return ExecResult(
        "exec_result.v1", raw, family, outcome, exit_code, stdout, stderr, target_path
    )


def _exec_hostname(raw: str, state: Dict[str, Any]) -> ExecResult:
    host = (state.get("meta") or {}).get("hostname", "web01")
    return _result(raw, "hostname", "success", 0, f"{host}\n", "")


def _exec_uname(raw: str, state: Dict[str, Any], args: list[str]) -> ExecResult:
    meta = state.get("meta") or {}
    host = meta.get("hostname", "ubuntu-22")
    kernel = meta.get("kernel", "5.15.0-88-generic")

    if "-a" in args:
        out = f"Linux {host} {kernel} #1-Ubuntu SMP x86_64 x86_64 x86_64 GNU/Linux\n"
        return _result(raw, "uname", "success", 0, out, "")

    # Individual flags: -s kernel name, -n nodename, -r release, -m machine
    if "-r" in args:
        return _result(raw, "uname", "success", 0, f"{kernel}\n", "")
    if "-n" in args:
        return _result(raw, "uname", "success", 0, f"{host}\n", "")
    if "-m" in args:
        return _result(raw, "uname", "success", 0, "x86_64\n", "")
    if "-s" in args:
        return _result(raw, "uname", "success", 0, "Linux\n", "")

    return _result(raw, "uname", "success", 0, "Linux\n", "")


def _exec_id(raw: str, state: Dict[str, Any], user: str) -> ExecResult:
    users = state.get("users") or {}
    groups_map = state.get("groups") or {}

    u = users.get(user) or {}
    uid = u.get("uid", 1000)
    gid = u.get("gid", 1000)

    def group_name(gid_val) -> str:
        g = groups_map.get(str(gid_val)) or groups_map.get(gid_val) or {}
        return g.get("name") or str(gid_val)

    primary_group_name = group_name(gid)
    groups = u.get("groups") or [gid]
    group_parts = [f"{g}({group_name(g)})" for g in groups]

    out = (
        f"uid={uid}({user}) "
        f"gid={gid}({primary_group_name}) "
        f"groups=" + ",".join(group_parts) + "\n"
    )
    return _result(raw, "id", "success", 0, out, "")


def _exec_echo(raw: str, state: Dict[str, Any]) -> ExecResult:
    """Parse echo args with quote awareness and basic $VAR expansion."""
    rest = raw.strip()[4:].strip()  # after "echo"

    # Build variable lookup from session/user state
    session = state.get("session") or {}
    user = session.get("active_user", "ubuntu")
    cwd = session.get("cwd", "/")
    u = (state.get("users") or {}).get(user) or {}
    env_vars: Dict[str, str] = {
        "HOME": u.get("home", f"/home/{user}"),
        "USER": user,
        "LOGNAME": user,
        "SHELL": u.get("shell", "/bin/bash"),
        "PWD": cwd,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
        "?": str(session.get("last_exit_code", 0)),
    }

    def _expand(token: str) -> str:
        """Expand $VAR and ${VAR} references in a token."""
        import re as _re
        def replacer(m: "re.Match[str]") -> str:
            name = m.group(1) or m.group(2)
            return env_vars.get(name, "")
        return _re.sub(r"\$\{(\w+)\}|\$(\w+)", replacer, token)

    echo_args: list[str] = []
    i = 0
    while i < len(rest):
        while i < len(rest) and rest[i] in " \t":
            i += 1
        if i >= len(rest):
            break
        if rest[i] == "'":
            # Single quotes: no expansion
            i += 1
            start = i
            while i < len(rest) and rest[i] != "'":
                i += 1
            echo_args.append(rest[start:i])
            if i < len(rest):
                i += 1
        elif rest[i] == '"':
            # Double quotes: expand variables
            i += 1
            start = i
            while i < len(rest) and rest[i] != '"':
                i += 1
            echo_args.append(_expand(rest[start:i]))
            if i < len(rest):
                i += 1
        else:
            start = i
            while i < len(rest) and rest[i] not in " \t":
                i += 1
            echo_args.append(_expand(rest[start:i]))
    out = " ".join(echo_args) + "\n"
    return _result(raw, "echo", "success", 0, out, "")


def _exec_pwd(raw: str, cwd: str) -> ExecResult:
    return _result(raw, "pwd", "success", 0, f"{cwd}\n", "")


def _exec_whoami(raw: str, user: str) -> ExecResult:
    return _result(raw, "whoami", "success", 0, f"{user}\n", "")


def _exec_cd(
    raw: str,
    state: Dict[str, Any],
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if args and args[-1].startswith("-"):
        return _result(raw, "cd", "error", 1, "", "", target_path=None)

    u = (state.get("users") or {}).get(user) or {}
    home = u.get("home", f"/home/{user}")

    if not args:
        target = resolve_path(cwd, home)
    else:
        # Expand ~ and ~/ to the user's home directory
        arg = args[-1]
        if arg == "~" or arg == "~/":
            arg = home
        elif arg.startswith("~/"):
            arg = home + arg[1:]
        target = resolve_path(cwd, arg)

    if not fs.exists(target):
        return _result(raw, "cd", "missing_path", 1, "", "", target_path=target)

    node = fs.node(target) or {}
    if node.get("type") != "dir":
        return _result(raw, "cd", "error", 1, "", "", target_path=target)

    if not perm.can_cd_dir(user, node):
        return _result(raw, "cd", "permission_denied", 1, "", "", target_path=target)

    state.setdefault("session", {})["cwd"] = target
    return _result(raw, "cd", "success", 0, "", "", target_path=target)


def _exec_ls(
    raw: str,
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    flags = [a for a in args if a.startswith("-")]
    nonflags = [a for a in args if not a.startswith("-")]

    show_all = any("a" in f for f in flags)
    long_fmt = any("l" in f for f in flags)
    show_dir = any("d" in f for f in flags)

    target_input = nonflags[-1] if nonflags else None
    target = resolve_path(cwd, target_input)

    if not fs.exists(target):
        return _result(raw, "ls", "missing_path", 2, "", "", target_path=target)

    node = fs.node(target) or {}
    # ls -d -> show directory itself instead of listing contents
    if show_dir:
        if target_input is not None:
            name = target_input
        else:
            name = target.rsplit("/", 1)[-1] if "/" in target else target
            if name == "":
                name = "/"

        if long_fmt:
            mode_sym = mode_to_symbolic(
                node.get("mode", "0755"), node.get("type", "dir")
            )
            owner = node.get("owner", "root")
            group = node.get("group", "root")
            size = node.get("size", 4096)
            stdout = f"{mode_sym} 1 {owner} {group} {size} {name}\n"
        else:
            stdout = f"{name}\n"

        return _result(raw, "ls", "success", 0, stdout, "", target_path=target)
    # ls <file>
    if node.get("type") == "file":
        name = target.rsplit("/", 1)[-1] if "/" in target else target
        if long_fmt:
            mode_sym = mode_to_symbolic(node.get("mode", "0000"), "file")
            owner = node.get("owner", "root")
            group = node.get("group", "root")
            size = node.get("size", 0)
            stdout = f"{mode_sym} 1 {owner} {group} {size} {name}\n"
            return _result(raw, "ls", "success", 0, stdout, "", target_path=target)
        return _result(raw, "ls", "success", 0, f"{name}\n", "", target_path=target)

    if node.get("type") != "dir":
        return _result(raw, "ls", "error", 2, "", "", target_path=target)

    if not perm.can_list_dir(user, node):
        return _result(raw, "ls", "permission_denied", 2, "", "", target_path=target)

    names = fs.list_dir_basenames(target)
    if not show_all:
        names = [n for n in names if not n.startswith(".")]

    if show_all:
        names = [".", ".."] + names

    if not long_fmt:
        stdout = ("\n".join(names) + "\n") if names else ""
        return _result(raw, "ls", "success", 0, stdout, "", target_path=target)

    # Long format (-l / -la)
    lines = []
    for name in names:
        if name in {".", ".."}:
            mode_sym = mode_to_symbolic("0755", "dir")
            owner = node.get("owner", "root")
            group = node.get("group", "root")
            size = 4096
            lines.append(f"{mode_sym} 1 {owner} {group} {size} {name}")
            continue

        child_path = target.rstrip("/") + "/" + name if target != "/" else "/" + name
        child = fs.node(child_path) or {}
        mode_sym = mode_to_symbolic(
            child.get("mode", "0000"), child.get("type", "file")
        )
        owner = child.get("owner", "root")
        group = child.get("group", "root")
        size = child.get("size", 0)
        lines.append(f"{mode_sym} 1 {owner} {group} {size} {name}")

    stdout = ("\n".join(lines) + "\n") if lines else ""
    return _result(raw, "ls", "success", 0, stdout, "", target_path=target)


def _exec_cat(
    raw: str,
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if not args or args[-1].startswith("-"):
        return _result(raw, "cat", "missing_path", 1, "", "", target_path=None)

    target = resolve_path(cwd, args[-1])

    if not fs.exists(target):
        return _result(raw, "cat", "missing_path", 1, "", "", target_path=target)

    node = fs.node(target) or {}
    if node.get("type") == "dir":
        return _result(raw, "cat", "is_a_directory", 1, "", "", target_path=target)

    if node.get("type") == "file":
        if not perm.can_read_file(user, node):
            return _result(
                raw, "cat", "permission_denied", 1, "", "", target_path=target
            )

        content = fs.read_file(target) or ""
        stdout = content if content.endswith("\n") or content == "" else content + "\n"
        return _result(raw, "cat", "success", 0, stdout, "", target_path=target)

    return _result(raw, "cat", "error", 1, "", "", target_path=target)


def _exec_date(raw: str, args: list[str]) -> ExecResult:
    allowed_flags = {"-u"}
    bad_flags = [a for a in args if a.startswith("-") and a not in allowed_flags]

    if bad_flags:
        flag = bad_flags[0].lstrip("-")[0] if len(bad_flags[0]) > 1 else bad_flags[0]
        err = (
            f"date: invalid option -- '{flag}'\n"
            "Try 'date --help' for more information.\n"
        )
        return _result(raw, "date", "error", 1, "", err)

    # Always use UTC, the simulated machine runs in UTC (meta.timezone = "UTC").
    # Using the host's local timezone would fingerprint the machine running the honeypot.
    now = datetime.now(timezone.utc)
    out = now.strftime("%a %b %e %H:%M:%S UTC %Y\n")
    return _result(raw, "date", "success", 0, out, "")


def _exec_uptime(raw: str, state: Dict[str, Any], args: list[str]) -> ExecResult:
    meta = state.get("meta") or {}
    boot_time_str = meta.get("boot_time", "2026-01-29T00:00:00Z")
    boot = datetime.fromisoformat(boot_time_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    uptime_seconds = max(0, int((now - boot).total_seconds()))
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60

    def _format_default() -> str:
        time_str = now.strftime("%H:%M:%S")
        if days > 0:
            up_str = f"{days} days, {hours}:{minutes:02d}"
        elif hours > 0:
            up_str = f"{hours}:{minutes:02d}"
        else:
            up_str = f"{minutes} min"
        return f"{time_str} up {up_str},  1 user,  load average: 0.01, 0.05, 0.03\n"

    def _format_pretty() -> str:
        parts = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        return ("up " + ", ".join(parts) + "\n") if parts else "up 0 min\n"

    if not args:
        return _result(raw, "uptime", "success", 0, _format_default(), "")

    flag = args[0]

    if flag in ("-p", "--pretty"):
        return _result(raw, "uptime", "success", 0, _format_pretty(), "")

    if flag in ("-s", "--since"):
        out = boot.strftime("%Y-%m-%d %H:%M:%S") + "\n"
        return _result(raw, "uptime", "success", 0, out, "")

    if flag in ("-h", "--help"):
        help_text = (
            "Usage: uptime [options]\n"
            "  -p, --pretty   show uptime in pretty format\n"
            "  -s, --since    show boot time\n"
            "  -V, --version  output version information\n"
            "  -h, --help     display this help\n"
        )
        return _result(raw, "uptime", "success", 0, help_text, "")

    if flag in ("-V", "--version"):
        return _result(raw, "uptime", "success", 0, "uptime from procps-ng 4.0.2\n", "")

    err = f"uptime: invalid option -- '{flag.lstrip('-')}'\n"
    return _result(raw, "uptime", "error", 1, "", err)


def _exec_env(raw: str, state: Dict[str, Any], args: list[str]) -> ExecResult:
    if args:
        flag = args[0].lstrip("-")
        err = f"env: invalid option -- '{flag}'\n"
        return _result(raw, "env", "error", 1, "", err)

    session = state.get("session") or {}
    user = session.get("active_user", "ubuntu")
    cwd = session.get("cwd", "/")
    u = (state.get("users") or {}).get(user) or {}

    env = {
        "USER": user,
        "HOME": u.get("home", f"/home/{user}"),
        "SHELL": u.get("shell", "/bin/bash"),
        "PWD": cwd,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
    }
    stdout = "\n".join(f"{k}={v}" for k, v in env.items()) + "\n"
    return _result(raw, "env", "success", 0, stdout, "")


def _exec_which(raw: str, args: list[str]) -> ExecResult:
    if not args:
        err = "which: missing argument\n"
        return _result(raw, "which", "error", 1, "", err)

    if args[0].startswith("-"):
        flag = args[0].lstrip("-")
        err = f"which: invalid option -- '{flag}'\n"
        return _result(raw, "which", "error", 1, "", err)

    cmd = args[0]
    path = BIN_PATHS.get(cmd)

    if path:
        return _result(raw, "which", "success", 0, f"{path}\n", "")
    return _result(raw, "which", "error", 1, "", "")


def _exec_clear(raw: str, args: list[str]) -> ExecResult:
    if args and args[0].startswith("-"):
        flag = args[0].lstrip("-")
        err = f"clear: invalid option -- '{flag}'\n"
        return _result(raw, "clear", "error", 1, "", err)

    return _result(raw, "clear", "success", 0, "\x1b[H\x1b[2J", "")


def _exec_ps(raw: str, state: Dict[str, Any], args: list[str]) -> ExecResult:
    processes = state.get("processes") or {}
    table = processes.get("table") or []

    valid = {(), ("-e",), ("-ef",), ("aux",), ("ax",)}
    if tuple(args) not in valid:
        if args and args[0].startswith("-"):
            flag = args[0].lstrip("-")
            return _result(
                raw, "ps", "error", 1, "", f"ps: invalid option -- '{flag}'\n"
            )
        return _result(raw, "ps", "error", 1, "", "ps: invalid option\n")

    if args == ["-ef"] or args == ["-e"]:
        lines = ["UID          PID    PPID  C STIME TTY          TIME CMD"]
        for p in table:
            uid = p.get("user", "?")
            pid = p.get("pid", 0)
            ppid = 0 if pid == 1 else 1
            stime_str = p.get("start_time", "2026-01-01T00:00:00Z")
            stime = stime_str[11:16] if len(stime_str) >= 16 else "00:00"
            cmd = p.get("cmd", "")
            tty = "pts/0" if cmd == "bash" else "?"
            lines.append(
                f"{uid:<12} {pid:>5} {ppid:>7}  0 {stime} {tty:<12} 00:00:00 {cmd}"
            )
    elif args == ["aux"] or args == ["ax"]:
        lines = ["USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND"]
        for p in table:
            uid = p.get("user", "?")
            pid = p.get("pid", 0)
            stime_str = p.get("start_time", "2026-01-01T00:00:00Z")
            stime = stime_str[11:16] if len(stime_str) >= 16 else "00:00"
            cmd = p.get("cmd", "")
            tty = "pts/0" if cmd == "bash" else "?"
            stat = "Ss" if cmd in ("bash", "sh") else "S"
            lines.append(
                f"{uid:<12} {pid:>5}  0.0  0.1  12345  4321 {tty:<8} {stat:<4} {stime}   0:00 {cmd}"
            )
    else:
        lines = ["PID TTY          TIME CMD"]
        for p in table:
            pid = p.get("pid", 0)
            cmd = p.get("cmd", "")
            cmd_name = cmd.split(":")[0] if cmd else ""
            tty = "pts/0" if cmd == "bash" else "?"
            lines.append(f"{pid:<3} {tty:<12} 00:00:00 {cmd_name}")

    return _result(raw, "ps", "success", 0, "\n".join(lines) + "\n", "")


def _exec_touch(
    raw: str,
    state: Dict[str, Any],
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if not args:
        return _result(raw, "touch", "missing_path", 1, "", "", target_path=None)

    if args[0].startswith("-"):
        flag = args[0].lstrip("-")
        return _result(
            raw, "touch", "error", 1, "", f"touch: invalid option -- '{flag}'\n"
        )

    target = resolve_path(cwd, args[-1])
    now_z = _utc_now_z()

    if fs.exists(target):
        node = state.get("fs", {}).get("nodes", {}).get(target)
        if isinstance(node, dict):
            node["mtime"] = now_z
        return _result(raw, "touch", "success", 0, "", "", target_path=target)

    parent = _parent_path(target)

    if not fs.exists(parent):
        return _result(raw, "touch", "missing_path", 1, "", "", target_path=target)

    parent_node = fs.node(parent) or {}
    if parent_node.get("type") != "dir":
        return _result(
            raw,
            "touch",
            "error",
            1,
            "",
            f"touch: cannot touch '{target}': Not a directory\n",
            target_path=target,
        )

    if not perm.can_list_dir(user, parent_node):
        return _result(raw, "touch", "permission_denied", 1, "", "", target_path=target)

    users = state.get("users") or {}
    u = users.get(user) or {}
    group_name = user
    gid = u.get("gid")
    groups_map = state.get("groups") or {}
    if gid is not None:
        g = groups_map.get(str(gid)) or groups_map.get(gid) or {}
        group_name = g.get("name", user)

    nodes = state.setdefault("fs", {}).setdefault("nodes", {})
    nodes[target] = {
        "type": "file",
        "mode": "0644",
        "owner": user,
        "group": group_name,
        "size": 0,
        "mtime": now_z,
        "content_ref": None,
    }

    # parent_node is the same dict as nodes[parent], update children and mtime
    if isinstance(parent_node, dict):
        children = parent_node.setdefault("children", [])
        if target not in children:
            children.append(target)
        parent_node["mtime"] = now_z

    return _result(raw, "touch", "success", 0, "", "", target_path=target)


def _exec_mkdir(
    raw: str,
    state: Dict[str, Any],
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if not args:
        return _result(raw, "mkdir", "missing_path", 1, "", "", target_path=None)

    if args[0].startswith("-"):
        flag = args[0].lstrip("-")
        return _result(
            raw, "mkdir", "error", 1, "", f"mkdir: invalid option -- '{flag}'\n"
        )

    target = resolve_path(cwd, args[-1])
    parent = _parent_path(target)

    if fs.exists(target):
        return _result(
            raw,
            "mkdir",
            "error",
            1,
            "",
            f"mkdir: cannot create directory '{target}': File exists\n",
            target_path=target,
        )

    if not fs.exists(parent):
        return _result(raw, "mkdir", "missing_path", 1, "", "", target_path=target)

    parent_node = fs.node(parent) or {}
    if parent_node.get("type") != "dir":
        return _result(
            raw,
            "mkdir",
            "error",
            1,
            "",
            f"mkdir: cannot create directory '{target}': Not a directory\n",
            target_path=target,
        )

    if not perm.can_list_dir(user, parent_node):
        return _result(raw, "mkdir", "permission_denied", 1, "", "", target_path=target)

    now_z = _utc_now_z()

    users = state.get("users") or {}
    u = users.get(user) or {}
    group_name = user
    gid = u.get("gid")
    groups_map = state.get("groups") or {}
    if gid is not None:
        g = groups_map.get(str(gid)) or groups_map.get(gid) or {}
        group_name = g.get("name", user)

    nodes = state.setdefault("fs", {}).setdefault("nodes", {})
    nodes[target] = {
        "type": "dir",
        "mode": "0755",
        "owner": user,
        "group": group_name,
        "mtime": now_z,
        "children": [],
    }

    # parent_node is the same dict as nodes[parent], update children and mtime
    if isinstance(parent_node, dict):
        children = parent_node.setdefault("children", [])
        if target not in children:
            children.append(target)
        parent_node["mtime"] = now_z

    return _result(raw, "mkdir", "success", 0, "", "", target_path=target)


def _exec_rm(
    raw: str,
    state: Dict[str, Any],
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if not args:
        return _result(raw, "rm", "missing_path", 1, "", "", target_path=None)

    if args[0].startswith("-"):
        flag = args[0].lstrip("-")
        return _result(raw, "rm", "error", 1, "", f"rm: invalid option -- '{flag}'\n")

    target = resolve_path(cwd, args[-1])

    if not fs.exists(target):
        return _result(raw, "rm", "missing_path", 1, "", "", target_path=target)

    node = fs.node(target) or {}

    if node.get("type") == "dir":
        return _result(
            raw,
            "rm",
            "is_a_directory",
            1,
            "",
            "",
            target_path=target,
        )

    parent = _parent_path(target)
    if not fs.exists(parent):
        return _result(raw, "rm", "missing_path", 1, "", "", target_path=target)

    parent_node = fs.node(parent) or {}
    if parent_node.get("type") != "dir":
        return _result(
            raw,
            "rm",
            "error",
            1,
            "",
            f"rm: cannot remove '{target}': Not a directory\n",
            target_path=target,
        )

    if not perm.can_list_dir(user, parent_node):
        return _result(raw, "rm", "permission_denied", 1, "", "", target_path=target)

    nodes = state.setdefault("fs", {}).setdefault("nodes", {})
    nodes.pop(target, None)

    parent_state_node = nodes.get(parent)
    if isinstance(parent_state_node, dict):
        children = parent_state_node.setdefault("children", [])
        if target in children:
            children.remove(target)
        parent_state_node["mtime"] = _utc_now_z()

    return _result(raw, "rm", "success", 0, "", "", target_path=target)


def _exec_mv(
    raw: str,
    state: Dict[str, Any],
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if len(args) < 2:
        return _result(raw, "mv", "missing_path", 1, "", "", target_path=None)

    if any(a.startswith("-") for a in args):
        flag = next(a for a in args if a.startswith("-")).lstrip("-")
        return _result(raw, "mv", "error", 1, "", f"mv: invalid option -- '{flag}'\n")

    src = resolve_path(cwd, args[0])
    dst_input = args[1]
    dst = resolve_path(cwd, dst_input)

    if not fs.exists(src):
        return _result(raw, "mv", "missing_path", 1, "", "", target_path=src)

    if src == dst:
        return _result(raw, "mv", "success", 0, "", "", target_path=dst)

    if fs.exists(dst):
        dst_node = fs.node(dst) or {}
        if dst_node.get("type") == "dir":
            base = src.rsplit("/", 1)[-1] if "/" in src else src
            base = base or "/"
            dst = dst.rstrip("/") + "/" + base if dst != "/" else "/" + base
        else:
            return _result(
                raw,
                "mv",
                "error",
                1,
                "",
                f"mv: cannot move '{src}' to '{dst}': File exists\n",
                target_path=dst,
            )

    dst_parent = _parent_path(dst)
    if not fs.exists(dst_parent):
        return _result(raw, "mv", "missing_path", 1, "", "", target_path=dst)

    dst_parent_node = fs.node(dst_parent) or {}
    if dst_parent_node.get("type") != "dir":
        return _result(
            raw,
            "mv",
            "error",
            1,
            "",
            f"mv: cannot move '{src}' to '{dst}': Not a directory\n",
            target_path=dst,
        )

    if not perm.can_list_dir(user, dst_parent_node):
        return _result(raw, "mv", "permission_denied", 1, "", "", target_path=dst)

    nodes = state.setdefault("fs", {}).setdefault("nodes", {})
    old_parent = _parent_path(src)
    old_parent_node = fs.node(old_parent) or {}

    moved_node = dict(nodes[src])
    moved_node["mtime"] = _utc_now_z()
    nodes[dst] = moved_node
    nodes.pop(src, None)

    if isinstance(old_parent_node, dict):
        children = old_parent_node.setdefault("children", [])
        if src in children:
            children.remove(src)
        old_parent_node["mtime"] = _utc_now_z()

    if isinstance(dst_parent_node, dict):
        children = dst_parent_node.setdefault("children", [])
        if dst not in children:
            children.append(dst)
        dst_parent_node["mtime"] = _utc_now_z()

    return _result(raw, "mv", "success", 0, "", "", target_path=dst)


def _exec_cp(
    raw: str,
    state: Dict[str, Any],
    cwd: str,
    user: str,
    fs: FsModel,
    perm: PermissionChecker,
    args: list[str],
) -> ExecResult:
    if len(args) < 2:
        return _result(raw, "cp", "missing_path", 1, "", "", target_path=None)

    if any(a.startswith("-") for a in args):
        flag = next(a for a in args if a.startswith("-")).lstrip("-")
        return _result(raw, "cp", "error", 1, "", f"cp: invalid option -- '{flag}'\n")

    src = resolve_path(cwd, args[0])
    dst = resolve_path(cwd, args[1])

    if not fs.exists(src):
        return _result(raw, "cp", "missing_path", 1, "", "", target_path=src)

    src_node = fs.node(src) or {}
    if src_node.get("type") == "dir":
        return _result(
            raw,
            "cp",
            "error",
            1,
            "",
            f"cp: -r not specified; omitting directory '{src}'\n",
            target_path=src,
        )

    if fs.exists(dst):
        dst_node = fs.node(dst) or {}
        if dst_node.get("type") == "dir":
            base = src.rsplit("/", 1)[-1]
            dst = dst.rstrip("/") + "/" + base if dst != "/" else "/" + base
        else:
            return _result(
                raw,
                "cp",
                "error",
                1,
                "",
                f"cp: cannot create regular file '{dst}': File exists\n",
                target_path=dst,
            )

    dst_parent = _parent_path(dst)
    if not fs.exists(dst_parent):
        return _result(raw, "cp", "missing_path", 1, "", "", target_path=dst)

    dst_parent_node = fs.node(dst_parent) or {}
    if dst_parent_node.get("type") != "dir":
        return _result(
            raw,
            "cp",
            "error",
            1,
            "",
            f"cp: cannot create regular file '{dst}': Not a directory\n",
            target_path=dst,
        )

    if not perm.can_list_dir(user, dst_parent_node):
        return _result(raw, "cp", "permission_denied", 1, "", "", target_path=dst)

    nodes = state.setdefault("fs", {}).setdefault("nodes", {})
    copied = dict(nodes[src])
    copied["mtime"] = _utc_now_z()
    nodes[dst] = copied

    parent_state_node = nodes.get(dst_parent)
    if isinstance(parent_state_node, dict):
        children = parent_state_node.setdefault("children", [])
        if dst not in children:
            children.append(dst)
        parent_state_node["mtime"] = _utc_now_z()

    return _result(raw, "cp", "success", 0, "", "", target_path=dst)


def _exec_ip(raw: str, state: Dict[str, Any], args: list[str]) -> ExecResult:
    if not args:
        return _result(raw, "ip", "error", 1, "", "ip: invalid option\n")

    subcommand = args[0]

    # ip route / ip r, show routing table
    if subcommand in ("route", "r"):
        network = state.get("network") or {}
        interfaces = network.get("interfaces") or []
        lines = []
        default_gw = network.get("default_gateway")
        if default_gw:
            for iface in interfaces:
                if iface.get("name") != "lo":
                    lines.append(f"default via {default_gw} dev {iface['name']} proto dhcp src {iface['inet'].split('/')[0]} metric 100")
                    break
        for iface in interfaces:
            inet = iface.get("inet")
            name = iface.get("name", "eth0")
            if inet and "/" in inet:
                ip_only, prefix = inet.rsplit("/", 1)
                parts = ip_only.split(".")
                if len(parts) == 4:
                    net = ".".join(parts[:3]) + ".0"
                    scope = "host" if name == "lo" else "link"
                    lines.append(f"{net}/{prefix} dev {name} proto kernel scope {scope} src {ip_only}")
        if not lines:
            lines = [""]
        return _result(raw, "ip", "success", 0, "\n".join(lines) + "\n", "")

    if subcommand not in ("a", "addr", "address"):
        return _result(raw, "ip", "error", 1, "", f"ip: invalid option\n")

    network = state.get("network") or {}
    interfaces = network.get("interfaces") or []

    lines = []
    for idx, iface in enumerate(interfaces, start=1):
        name = iface.get("name", "eth0")
        state_str = iface.get("state", "UNKNOWN")
        mtu = iface.get("mtu", 1500)

        lines.append(
            f"{idx}: {name}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu {mtu} qdisc fq_codel state {state_str} group default qlen 1000"
        )

        if name == "lo":
            lines.append("    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00")
        else:
            lines.append("    link/ether 08:00:27:12:34:56 brd ff:ff:ff:ff:ff:ff")

        inet = iface.get("inet")
        if inet:
            if name == "lo":
                lines.append(f"    inet {inet} scope host {name}")
            else:
                brd = iface.get("broadcast", "0.0.0.0")
                lines.append(f"    inet {inet} brd {brd} scope global dynamic {name}")

    stdout = "\n".join(lines) + "\n"
    return _result(raw, "ip", "success", 0, stdout, "")


def _exec_ifconfig(raw: str, state: Dict[str, Any], args: list[str]) -> ExecResult:
    if args:
        flag = args[0].lstrip("-")
        return _result(
            raw, "ifconfig", "error", 1, "", f"ifconfig: invalid option -- '{flag}'\n"
        )

    network = state.get("network") or {}
    interfaces = network.get("interfaces") or []

    lines = []
    for iface in interfaces:
        name = iface.get("name", "eth0")
        mtu = iface.get("mtu", 1500)
        inet = iface.get("inet")

        if name == "lo":
            lines.append(f"{name}: flags=73<UP,LOOPBACK,RUNNING>  mtu {mtu}")
            if inet:
                ip_only = inet.split("/")[0]
                lines.append(f"        inet {ip_only}  netmask 255.0.0.0")
        else:
            lines.append(
                f"{name}: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu {mtu}"
            )
            if inet:
                parts = inet.split("/")
                ip_only = parts[0]
                brd = iface.get("broadcast", "0.0.0.0")
                netmask = "255.255.255.0"
                lines.append(
                    f"        inet {ip_only}  netmask {netmask}  broadcast {brd}"
                )

        lines.append("")

    stdout = "\n".join(lines).rstrip() + "\n"
    return _result(raw, "ifconfig", "success", 0, stdout, "")


def _exec_sudo_stub(raw: str) -> ExecResult:
    # Stub, never called in practice.
    # ssh_server.py intercepts all sudo commands before they reach the executor.
    # Exists so that "which sudo" resolves via BIN_PATHS and SUPPORTED guards pass.
    return _result(raw, "sudo", "error", 1, "", "sudo: internal routing error\n")


def execute_with_state(raw: str, state: Dict[str, Any]) -> ExecResult:
    fam = _family(raw)
    args = _args(raw)

    if fam == "empty":
        return _result(raw, "empty", "success", 0, "", "")

    if fam not in SUPPORTED:
        return _result(raw, fam, "invalid_cmd", 127, "", f"{fam}: command not found\n")

    # Snapshot mutable state sections before execution.
    # Restored only on unexpected exception to prevent partially written corruption.
    _snapshot = {
        "fs": copy.deepcopy(state.get("fs") or {}),
        "content_store": copy.deepcopy(state.get("content_store") or {}),
        "session": copy.deepcopy(state.get("session") or {}),
    }

    session = state.get("session") or {}
    cwd = session.get("cwd", "/")
    user = session.get("active_user", "ubuntu")
    fs = FsModel.from_state(state)
    perm = PermissionChecker.from_state(state)

    handlers = {
        "hostname": lambda: _exec_hostname(raw, state),
        "uname": lambda: _exec_uname(raw, state, args),
        "id": lambda: _exec_id(raw, state, user),
        "echo": lambda: _exec_echo(raw, state),
        "pwd": lambda: _exec_pwd(raw, cwd),
        "whoami": lambda: _exec_whoami(raw, user),
        "cd": lambda: _exec_cd(raw, state, cwd, user, fs, perm, args),
        "ls": lambda: _exec_ls(raw, cwd, user, fs, perm, args),
        "cat": lambda: _exec_cat(raw, cwd, user, fs, perm, args),
        "date": lambda: _exec_date(raw, args),
        "uptime": lambda: _exec_uptime(raw, state, args),
        "env": lambda: _exec_env(raw, state, args),
        "which": lambda: _exec_which(raw, args),
        "clear": lambda: _exec_clear(raw, args),
        "ps": lambda: _exec_ps(raw, state, args),
        "touch": lambda: _exec_touch(raw, state, cwd, user, fs, perm, args),
        "mkdir": lambda: _exec_mkdir(raw, state, cwd, user, fs, perm, args),
        "rm": lambda: _exec_rm(raw, state, cwd, user, fs, perm, args),
        "mv": lambda: _exec_mv(raw, state, cwd, user, fs, perm, args),
        "cp": lambda: _exec_cp(raw, state, cwd, user, fs, perm, args),
        "ip": lambda: _exec_ip(raw, state, args),
        "ifconfig": lambda: _exec_ifconfig(raw, state, args),
        "sudo": lambda: _exec_sudo_stub(raw),
    }

    try:
        if fam in handlers:
            return handlers[fam]()
        return _result(raw, fam, "error", 2, "", "")
    except Exception:
        # Restore state to pre-command snapshot to prevent partial corruption
        state["fs"] = _snapshot["fs"]
        state["content_store"] = _snapshot["content_store"]
        state["session"] = _snapshot["session"]
        raise
