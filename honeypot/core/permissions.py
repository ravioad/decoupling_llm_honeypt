from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


def _mode_to_int(mode_str: str) -> int:
    # mode_str like "0755"
    try:
        return int(mode_str, 8)
    except Exception:
        return 0o000


def _can_read(mode: int, who: str) -> bool:
    if who == "owner":
        return bool(mode & 0o400)
    if who == "group":
        return bool(mode & 0o040)
    return bool(mode & 0o004)


def _can_exec(mode: int, who: str) -> bool:
    if who == "owner":
        return bool(mode & 0o100)
    if who == "group":
        return bool(mode & 0o010)
    return bool(mode & 0o001)


def _who_bucket(
    node_owner: str, node_group: str, user: str, user_groups: set[str]
) -> str:
    if user == node_owner:
        return "owner"
    if node_group in user_groups:
        return "group"
    return "other"


@dataclass
class PermissionChecker:
    users: Dict[str, Any]
    groups: Dict[str, Any]

    @staticmethod
    def from_state(state: Dict[str, Any]) -> "PermissionChecker":
        return PermissionChecker(
            users=state.get("users") or {}, groups=state.get("groups") or {}
        )

    def user_groups(self, username: str) -> set[str]:
        """
        Returns the set of group identifiers for a user.
        """
        u = self.users.get(username) or {}
        gids = u.get("groups") or []
        result: set[str] = set()
        for g in gids:
            gid_str = str(g)
            result.add(gid_str)
            group_info = self.groups.get(gid_str) or self.groups.get(g) or {}
            name = group_info.get("name")
            if name:
                result.add(name)
        return result

    def can_list_dir(self, username: str, node: Dict[str, Any]) -> bool:
        mode = _mode_to_int(node.get("mode", "0000"))
        owner = node.get("owner", "")
        group = node.get("group", "")
        bucket = _who_bucket(owner, group, username, self.user_groups(username))
        # list directory requires read + execute on directory
        return _can_read(mode, bucket) and _can_exec(mode, bucket)

    def can_cd_dir(self, username: str, node: Dict[str, Any]) -> bool:
        mode = _mode_to_int(node.get("mode", "0000"))
        owner = node.get("owner", "")
        group = node.get("group", "")
        bucket = _who_bucket(owner, group, username, self.user_groups(username))
        # cd requires execute bit on directory
        return _can_exec(mode, bucket)

    def can_read_file(self, username: str, node: Dict[str, Any]) -> bool:
        mode = _mode_to_int(node.get("mode", "0000"))
        owner = node.get("owner", "")
        group = node.get("group", "")
        bucket = _who_bucket(owner, group, username, self.user_groups(username))
        return _can_read(mode, bucket)
