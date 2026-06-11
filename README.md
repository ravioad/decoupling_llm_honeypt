# decop-llm-honey

State-isolated LLM SSH honeypot. Emulates an Ubuntu 22.04 shell over SSH. A deterministic executor handles all state and produces ground-truth output, the LLM is used only as a renderer for phrasing variation. A validator checks every LLM response against ground-truth constraints, a fallback guarantees correct output when the LLM fails.

## Prerequisites

- Docker and Docker Compose
- [Ollama](https://ollama.ai) installed on the host machine, with `qwen2.5:7b` pulled
- Python 3.11+ (for running evaluation scripts outside Docker)

## Quick Start

```bash
# Step 1 — Start Ollama server
ollama serve

# Step 2 — Pull the model (one-time)
ollama pull qwen2.5:7b

# Step 3 — Create the environment file (required)
cp .env.example .env
```

> **Linux users:** `host.docker.internal` is macOS/Windows only. Open `.env` and set `OLLAMA_URL=http://172.17.0.1:11434`.

> **Why this step is required:** without `.env`, the server starts with hardcoded defaults — LLM renderer disabled (`USE_LLM_RENDERER=false`), port 2222 instead of 2223, and Ollama/ChromaDB pointed at `localhost` instead of the Docker network. The system runs but behaves as the `deterministic_only` variant with no LLM output.

```bash
# Step 4 — Start the stack (in a separate terminal)
docker compose up
```

Connect: `ssh ubuntu@localhost -p 2223` (password: `helloworld`)

## System Variants

| Variant              | Port | Activation                                           | Description                                        |
| -------------------- | ---- | ---------------------------------------------------- | -------------------------------------------------- |
| `state_isolated`     | 2223 | `USE_LLM_RENDERER=true`, `FORCE_DETERMINISTIC=false` | Full system — executor + LLM renderer + validator  |
| `deterministic_only` | 2223 | `FORCE_DETERMINISTIC=true`                           | Executor + fallback only, no LLM calls             |
| `prompt_only`        | 2224 | baseline server                                      | Ollama conversation loop, no executor or validator |

All three containers start automatically with `docker compose up`.

## Running Evaluation

Run from the `honeypot/` directory. The script handles all server restarts automatically — no manual config changes needed between variants.

```bash
cd honeypot

# Run a single variant
bash eval/run_eval.sh --variant state_isolated
bash eval/run_eval.sh --variant deterministic_only
bash eval/run_eval.sh --variant prompt_only

# Or run all three variants in sequence
bash eval/run_eval.sh
```

The script:

- Enforces `FORCE_NEW_SESSION=true` internally
- Automatically restarts the honeypot container with the correct `FORCE_DETERMINISTIC` value per variant
- Computes metrics after each scenario
- Generates a report at the end

Regenerate report from existing metrics at any time:

```bash
python -m eval.report --input results/metrics.jsonl --format markdown
```

## Local Development (no Docker)

```bash
# Start Ollama server
ollama serve

# Start ChromaDB (separate terminal)
docker run -d -p 8000:8000 chromadb/chroma

cd honeypot
cp .env.example .env   # required — defaults to localhost for Chroma/Ollama; adjust USE_LLM_RENDERER as needed
pip install -r requirements.txt
./run_local.sh
```

## Evaluation Data & Visualizations

Aggregate statistics and charts are generated from `final-evaulation-runs/evaluation_runs.csv` (372 rows — 31 runs × 3 variants × 4 scenarios).

```bash
cd final-evaulation-runs

python3 visualize.py          # bar/boxplot charts → charts/
python3 visualize_extra.py    # KDE/CDF/scatter/consistency charts → charts_extra/
```

## Key Files

| Path                                        | Description                                       |
| ------------------------------------------- | ------------------------------------------------- |
| `honeypot/ssh_server.py`                    | SSH server + session loop                         |
| `honeypot/executor/executor.py`             | Deterministic command executor (23 commands)      |
| `honeypot/validator/validate.py`            | Output validator                                  |
| `honeypot/baseline/ssh_server_baseline.py`  | Prompt-only baseline (port 2224)                  |
| `honeypot/eval/run_eval.sh`                 | Full evaluation runner                            |
| `final-evaulation-runs/evaluation_runs.csv` | Raw evaluation data (372 rows)                    |
| `final-evaulation-runs/aggregate.md`        | Aggregated statistics (mean ± std across 31 runs) |
| `rag-corpus/out/kb_docs_v1.jsonl`           | RAG knowledge base (26 documents)                 |

---

**If you have any questions or need help with installation, please feel free to contact me at s242513@dtu.dk**
