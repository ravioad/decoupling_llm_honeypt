import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from executor.executor import execute_with_state


def main():
    state = {
        "session": {"cwd": "/", "active_user": "ubuntu"},
        "users": {"ubuntu": {"uid": 1000, "gid": 1000, "groups": [27, 4]}},
        "groups": {
            "27": {"name": "sudo"},
            "4": {"name": "adm"},
            "1000": {"name": "ubuntu"},
        },
    }

    r = execute_with_state("id", state)

    print("exit_code:", r.exit_code)
    print("stdout_ground_truth:\n" + r.stdout_ground_truth)
    print("stderr_ground_truth:", repr(r.stderr_ground_truth))
    print("meta.headers:", (r.meta or {}).get("headers"))
    print("meta.rows:", (r.meta or {}).get("rows"))


if __name__ == "__main__":
    main()
