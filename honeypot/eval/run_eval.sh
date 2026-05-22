#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# decop-llm-honey Full evaluation runner
#
# Runs all 3 variants x 4 scenarios and produces metrics.jsonl.
#
# Usage (from project root or honeypot/ directory):
#   bash eval/run_eval.sh [--variant <state_isolated|deterministic_only|prompt_only>]
#
# If --variant is omitted, all three variants are run in sequence.
# The script automatically restarts the honeypot container with the
# correct FORCE_DETERMINISTIC setting between variants.
#
# FORCE_NEW_SESSION is enforced by this script, do not override it externally.
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve to honeypot/ directory regardless of where the script is called from
cd "${SCRIPT_DIR}/.."

# docker-compose.yml is one level up
COMPOSE_FILE="../docker-compose.yml"

SESSIONS_ROOT="runtime_logs/sessions"
EVAL_OUTPUT="runtime_logs/eval"
RESULTS_DIR="results"
METRICS_OUT="${RESULTS_DIR}/metrics.jsonl"
SCENARIOS=(normal state_mod injection long_session)

# FORCE_NEW_SESSION must always be true during evaluation
export FORCE_NEW_SESSION=true

mkdir -p "${RESULTS_DIR}"

# Parse --variant argument
VARIANT_FILTER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant) VARIANT_FILTER="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

restart_honeypot() {
  local force_det="$1"
  echo ""
  echo "--- Restarting honeypot container (FORCE_DETERMINISTIC=${force_det}) ---"
  FORCE_DETERMINISTIC="${force_det}" docker compose -f "${COMPOSE_FILE}" up -d honeypot
  # Wait until the SSH server is ready by checking for the SSH protocol banner.
  local retries=60
  echo -n "    Waiting for SSH server"
  until nc -w 2 localhost 2223 2>/dev/null | grep -q "^SSH"; do
    echo -n "."
    sleep 2
    (( retries-- ))
    if [[ $retries -eq 0 ]]; then
      echo ""
      echo "ERROR: honeypot SSH server did not become ready in time"
      exit 1
    fi
  done
  echo " ready"
  echo "--- Honeypot ready ---"
}


latest_session() {
  local prefix="$1"   # "S" for main server, "B" for baseline
  local username="$2"
  local latest
  latest="$(ls -dt "${SESSIONS_ROOT}/${prefix}-"*"-${username}"/ 2>/dev/null | head -1)"
  echo "${latest%/}"
}

run_scenario() {
  local variant="$1"
  local scenario="$2"
  local port="$3"
  local username="${4:-ubuntu}"
  local sess_prefix="${5:-S}"   # "S" for main server, "B" for baseline
  local output_dir="${EVAL_OUTPUT}/${variant}/${scenario}"

  echo ""
  echo ">>> ${variant} / ${scenario}  (port ${port})"

  # Run scenario, connects to the live server over SSH
  python -m eval.scenario_runner \
    --scenario "eval/scenarios/${scenario}.yaml" \
    --output "${output_dir}" \
    --port "${port}" \
    --username "${username}"

  # Find the session the server created for this run
  local session_dir
  session_dir="$(latest_session "${sess_prefix}" "${username}")"
  if [[ -z "${session_dir}" ]]; then
    echo "ERROR: no session directory found for ${username} (prefix ${sess_prefix}) after scenario run"
    exit 1
  fi
  local events="${session_dir}/events.jsonl"
  if [[ ! -f "${events}" ]]; then
    echo "ERROR: events.jsonl not found at ${events}"
    exit 1
  fi

  # Compute and append metrics
  # For prompt_only, pass --seed so the executor replay oracle can compute CCR
  local seed_arg=""
  if [[ "${variant}" == "prompt_only" ]]; then
    seed_arg="--seed state_templates/state.json"
  fi
  python -m eval.metrics \
    --events "${events}" \
    --manifest "${output_dir}/run_manifest.jsonl" \
    --variant "${variant}" \
    --scenario "${scenario}" \
    ${seed_arg} \
    --output "${METRICS_OUT}"
}

# Variant: state_isolated
# FORCE_DETERMINISTIC=false (default)
run_state_isolated() {
  echo ""
  echo "========================================"
  echo " VARIANT: state_isolated  (port 2223)"
  echo "========================================"
  restart_honeypot "false"
  for scenario in "${SCENARIOS[@]}"; do
    run_scenario "state_isolated" "${scenario}" 2223 ubuntu S
  done
}

# Variant: deterministic_only
# FORCE_DETERMINISTIC=true
run_deterministic_only() {
  echo ""
  echo "========================================"
  echo " VARIANT: deterministic_only  (port 2223)"
  echo "========================================"
  restart_honeypot "true"
  for scenario in "${SCENARIOS[@]}"; do
    run_scenario "deterministic_only" "${scenario}" 2223 ubuntu S
  done
}

run_prompt_only() {
  echo ""
  echo "========================================"
  echo " VARIANT: prompt_only  (port 2224)"
  echo "========================================"
  for scenario in "${SCENARIOS[@]}"; do
    run_scenario "prompt_only" "${scenario}" 2224 ubuntu B
  done
}

# Run selected variants
case "${VARIANT_FILTER}" in
  state_isolated)     run_state_isolated ;;
  deterministic_only) run_deterministic_only ;;
  prompt_only)        run_prompt_only ;;
  "")
    # Full run, clear previous metrics so per-variant summary isn't double-counted
    rm -f "${METRICS_OUT}"
    run_state_isolated
    run_deterministic_only
    run_prompt_only
    # Restore container to default state_isolated config after full run
    restart_honeypot "false"
    ;;
  *)
    echo "Unknown variant: ${VARIANT_FILTER}"
    echo "Valid values: state_isolated, deterministic_only, prompt_only"
    exit 1
    ;;
esac

echo ""
echo "========================================"
echo " Generating report"
echo "========================================"
python -m eval.report --input "${METRICS_OUT}" --format markdown

echo ""
echo "Done."
echo "  Metrics: ${METRICS_OUT}"
echo "  Run 'python -m eval.report --input ${METRICS_OUT}' to regenerate the report."
