from __future__ import annotations

from pathlib import PurePosixPath


def normalize_posix(path: str) -> str:
    # PurePosixPath keeps it POSIX and prevents OS path issues
    p = PurePosixPath(path)
    # resolve "." and ".." without touching filesystem
    parts = []
    for part in p.parts:
        if part in ("", ".", "/"):  # skip root anchor, will prepend for abs paths
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    # absolute if original started with "/"
    if path.startswith("/"):
        return "/" + "/".join(parts)
    return "/".join(parts) if parts else "."


def resolve_path(cwd: str, user_path: str | None) -> str:
    """
    Resolve user_path against cwd.
    """
    if user_path is None or user_path.strip() == "":
        return normalize_posix(cwd)

    up = user_path.strip()
    if up.startswith("/"):
        return normalize_posix(up)

    # relative
    joined = str(PurePosixPath(cwd) / up)
    return normalize_posix(joined)
