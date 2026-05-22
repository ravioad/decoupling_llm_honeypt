import json
import subprocess
import time
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
SUITE = ROOT / "suite" / "suite_v1.yaml"
UBUNTU_IMAGE_TAG = "rag-ubuntu-runner:22.04"

RUN_AS_USER = "attacker"


def build_runner_image() -> None:
    dockerfile = ROOT / "docker" / "Dockerfile.ubuntu-runner"
    cmd = ["docker", "build", "-t", UBUNTU_IMAGE_TAG, "-f", str(dockerfile), str(ROOT)]
    subprocess.check_call(cmd)


def wrap_as_user(cmd: list[str]) -> list[str]:
    if len(cmd) >= 3 and cmd[0] == "bash" and cmd[1] == "-lc":
        shell_cmd = cmd[2]
    else:
        shell_cmd = " ".join(cmd)

    wrapped = [
        "bash",
        "-lc",
        f"LANG=C.UTF-8 LC_ALL=C.UTF-8 su -s /bin/bash {RUN_AS_USER} -c {json.dumps(shell_cmd)}",
    ]
    return wrapped


def run_in_container(command: list[str]) -> tuple[int, str, str, float]:
    """
    Runs a command inside the ubuntu runner container and returns:
    (exit_code, stdout, stderr, duration_sec)
    """
    t0 = time.time()

    docker_cmd = ["docker", "run", "--rm", UBUNTU_IMAGE_TAG, *command]

    proc = subprocess.run(docker_cmd, capture_output=True, text=True)
    dt = time.time() - t0
    return proc.returncode, proc.stdout, proc.stderr, dt


def main() -> None:
    OUT.mkdir(exist_ok=True)
    raw_path = OUT / "raw_outputs_v1.jsonl"

    with open(SUITE, "r", encoding="utf-8") as f:
        suite = yaml.safe_load(f)

    meta = suite.get("meta", {})
    cases = suite.get("cases", [])

    build_runner_image()

    with open(raw_path, "w", encoding="utf-8") as out:
        for case in cases:
            case_id = case["id"]
            cmd = case["cmd"]
            family = case.get("family", "unknown")
            declared_outcome = case.get("outcome", "unknown")
            tags = case.get("tags", [])

            wrapped_cmd = wrap_as_user(cmd)
            exit_code, stdout, stderr, duration = run_in_container(wrapped_cmd)

            record = {
                "id": case_id,
                "family": family,
                "declared_outcome": declared_outcome,
                "tags": tags,
                "cmd": cmd,  # original
                "cmd_wrapped": wrapped_cmd,  # what actually ran
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "duration_sec": round(duration, 4),
                "env": meta,
                "run_as_user": RUN_AS_USER,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote raw dataset: {raw_path}")


if __name__ == "__main__":
    main()
