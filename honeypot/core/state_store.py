from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class StateStore:
    seed_path: Path
    sessions_root: Path
    session_id: str
    session_dir: Path
    state_path: Path
    state: Dict[str, Any]

    @staticmethod
    def open_or_create(
        *,
        seed_path: str,
        sessions_root: str,
        session_id: str,
        resume: bool,
    ) -> "StateStore":
        seed = Path(seed_path).resolve()
        root = Path(sessions_root).resolve()
        root.mkdir(parents=True, exist_ok=True)

        sess_dir = root / session_id
        state_path = sess_dir / "state.json"
        sess_dir.mkdir(parents=True, exist_ok=True)

        if state_path.exists():
            if not resume:
                raise FileExistsError(
                    f"Session exists. Use resume=True to load: {state_path}"
                )
            state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            # Create fresh per-session copy from seed
            if not seed.exists():
                raise FileNotFoundError(f"Seed state not found: {seed}")
            shutil.copyfile(seed, state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))

        return StateStore(
            seed_path=seed,
            sessions_root=root,
            session_id=session_id,
            session_dir=sess_dir,
            state_path=state_path,
            state=state,
        )

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.state, indent=2, sort_keys=False), encoding="utf-8"
        )
        os.replace(tmp, self.state_path)

    def ensure_events_log(self) -> Path:
        p = self.session_dir / "events.jsonl"
        if not p.exists():
            p.touch()
        return p
