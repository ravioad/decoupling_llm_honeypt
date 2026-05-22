from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List


@dataclass
class FsModel:
    nodes: Dict[str, Dict[str, Any]]
    content_store: Dict[str, str]

    @staticmethod
    def from_state(state: Dict[str, Any]) -> "FsModel":
        nodes = (state.get("fs") or {}).get("nodes") or {}
        content_store = state.get("content_store") or {}
        return FsModel(nodes=nodes, content_store=content_store)

    def exists(self, path: str) -> bool:
        return path in self.nodes

    def node(self, path: str) -> Optional[Dict[str, Any]]:
        return self.nodes.get(path)

    def is_dir(self, path: str) -> bool:
        n = self.node(path)
        return bool(n) and n.get("type") == "dir"

    def is_file(self, path: str) -> bool:
        n = self.node(path)
        return bool(n) and n.get("type") == "file"

    def list_dir_basenames(self, path: str) -> List[str]:
        n = self.node(path) or {}
        children = n.get("children") or []
        # return basenames only
        out = []
        for c in children:
            if not isinstance(c, str):
                continue
            out.append(c.rsplit("/", 1)[-1] if "/" in c else c)
        return sorted(out)

    def read_file(self, path: str) -> Optional[str]:
        n = self.node(path)
        if not n or n.get("type") != "file":
            return None
        ref = n.get("content_ref")
        if not ref:
            return ""
        return self.content_store.get(ref, "")
