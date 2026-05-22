import json
import subprocess
import time
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
SUITE = ROOT / "suite" / "suite_v1.yaml"

UBUNTU_IMAGE_TAG = "rag-ubuntu-runner:22.04"


def build_runner_image() -> None:
    dockerfile = ROOT / "docker" / "Dockerfile.ubuntu-runner"
    cmd = ["docker", "build", "-t", UBUNTU_IMAGE_TAG, "-f", str(dockerfile), str(ROOT)]
    subprocess.check_call(cmd)


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
            outcome = case.get("outcome", "unknown")
            tags = case.get("tags", [])

            exit_code, stdout, stderr, duration = run_in_container(cmd)

            record = {
                "id": case_id,
                "family": family,
                "outcome": outcome,
                "tags": tags,
                "cmd": cmd,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "duration_sec": round(duration, 4),
                "env": meta,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote raw dataset: {raw_path}")


if __name__ == "__main__":
    main()
