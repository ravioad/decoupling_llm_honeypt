# Aggregated Evaluation Results — 31 Runs

_Parsed from 31 independent evaluation runs in `evaluation_runs.csv`._
_Mean ± population std across all runs. Range shows [min–max]._

## Aggregate Metrics Table

_Format: mean ± std (range)_

| Variant | Scenario | CCR | LLM% | FBK% | SDR | INJ | INJ\* |
|---|---|---|---|---|---|---|---|
| `state_isolated` | `normal` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 8.3% ± 0.0%<br>_[8.3%–8.3%]_ | 13.7% ± 15.3%<br>_[0.0%–50.0%]_ | 13.7% ± 15.3%<br>_[0.0%–50.0%]_ | N/A | N/A |
|  | `state_mod` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 23.5% ± 0.0%<br>_[23.5%–23.5%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A |
|  | `injection` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 30.0% ± 0.0%<br>_[30.0%–30.0%]_ | 4.7% ± 5.5%<br>_[0.0%–11.1%]_ | 4.7% ± 5.5%<br>_[0.0%–11.1%]_ | 18.5% ± 0.0%<br>_[18.5%–18.5%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ |
|  | `long_session` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 2.9% ± 0.0%<br>_[2.9%–2.9%]_ | 14.5% ± 22.7%<br>_[0.0%–50.0%]_ | 14.5% ± 22.7%<br>_[0.0%–50.0%]_ | N/A | N/A |
| `deterministic_only` | `normal` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A | N/A |
|  | `state_mod` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A | N/A |
|  | `injection` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | 18.5% ± 0.0%<br>_[18.5%–18.5%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ |
|  | `long_session` | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A | N/A |
| `prompt_only` | `normal` | 16.6% ± 4.1%<br>_[12.5%–31.2%]_ | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A | N/A |
|  | `state_mod` | 11.0% ± 7.4%<br>_[2.9%–32.4%]_ | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A | N/A |
|  | `injection` | 9.0% ± 5.0%<br>_[0.0%–20.0%]_ | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | 27.3% ± 12.6%<br>_[0.0%–48.1%]_ | 27.3% ± 12.6%<br>_[0.0%–48.1%]_ |
|  | `long_session` | 16.3% ± 3.8%<br>_[10.1%–24.6%]_ | 100.0% ± 0.0%<br>_[100.0%–100.0%]_ | 0.0% ± 0.0%<br>_[0.0%–0.0%]_ | N/A | N/A | N/A |

_CCR=Command Correctness Rate, LLM%=LLM Invocation Rate, FBK%=Fallback Activation Rate,_
_SDR=State Deviation Rate, INJ=Injection Rate (raw), INJ\*=Injection Rate (corrected, excl. echo/printf)_

## Guaranteed vs Probabilistic Metrics

### Guaranteed (zero variance by architecture)

| Metric | state_isolated | deterministic_only | prompt_only |
|---|---|---|---|
| CCR | 100.0% ± 0.0% | 100.0% ± 0.0% | 13.2% ± 6.2% |
| INJ* | 0.0% ± 0.0% | 0.0% ± 0.0% | 27.3% ± 12.6% |

### Probabilistic (vary across runs)

| Metric | state_isolated | deterministic_only | prompt_only |
|---|---|---|---|
| FBK% | 8.2% ± 15.3%, range [0.0%–50.0%] | 0.0% ± 0.0%, range [0.0%–0.0%] | 0.0% ± 0.0%, range [0.0%–0.0%] |
| SDR | 8.2% ± 15.3%, range [0.0%–50.0%] | N/A | N/A |
| INJ\* (prompt_only only) | — | — | 27.3% ± 12.6%, range [0.0%–48.1%] |

## prompt_only CCR — Per Scenario

_CCR is N/A for prompt_only without the executor oracle. These values use the oracle._

| Scenario | CCR mean ± std | Range |
|---|---|---|
| `normal` | 16.6% ± 4.1% | [12.5%–31.2%] |
| `state_mod` | 11.0% ± 7.4% | [2.9%–32.4%] |
| `injection` | 9.0% ± 5.0% | [0.0%–20.0%] |
| `long_session` | 16.3% ± 3.8% | [10.1%–24.6%] |

## prompt_only INJ\* Distribution (injection scenario)

- **Mean ± std:** 27.3% ± 12.6%
- **Range:** [0.0%–48.1%]
- **Runs with INJ\* = 0%:** 1/31
- **Runs with INJ\* > 0%:** 30/31

_For state_isolated and deterministic_only, INJ\* = 0.0% in every run (architectural guarantee)._

## state_isolated FBK% — Per Scenario

| Scenario | FBK% mean ± std | Range |
|---|---|---|
| `normal` | 13.7% ± 15.3% | [0.0%–50.0%] |
| `state_mod` | 0.0% ± 0.0% | [0.0%–0.0%] |
| `injection` | 4.7% ± 5.5% | [0.0%–11.1%] |
| `long_session` | 14.5% ± 22.7% | [0.0%–50.0%] |

## Latency — Mean ± Std

| Variant | Scenario | Duration | Avg ms/cmd | LLM% |
|---|---|---|---|---|
| `state_isolated` | `normal` | 19.5s ± 1.3s | 405ms ± 26ms | 8.3% ± 0.0% |
|  | `state_mod` | 25.3s ± 0.4s | 744ms ± 13ms | 23.5% ± 0.0% |
|  | `injection` | 26.8s ± 0.3s | 893ms ± 8ms | 30.0% ± 0.0% |
|  | `long_session` | 12.4s ± 0.1s | 180ms ± 1ms | 2.9% ± 0.0% |
| `deterministic_only` | `normal` | 3.8s ± 0.1s | 79ms ± 1ms | 0.0% ± 0.0% |
|  | `state_mod` | 3.6s ± 0.1s | 107ms ± 3ms | 0.0% ± 0.0% |
|  | `injection` | 2.8s ± 0.1s | 93ms ± 2ms | 0.0% ± 0.0% |
|  | `long_session` | 4.0s ± 0.0s | 58ms ± 0ms | 0.0% ± 0.0% |
| `prompt_only` | `normal` | 180.2s ± 9.0s | 3755ms ± 189ms | 100.0% ± 0.0% |
|  | `state_mod` | 68.6s ± 17.6s | 2019ms ± 516ms | 100.0% ± 0.0% |
|  | `injection` | 61.0s ± 6.9s | 2034ms ± 228ms | 100.0% ± 0.0% |
|  | `long_session` | 265.6s ± 18.3s | 3849ms ± 266ms | 100.0% ± 0.0% |

_Duration and avg ms/cmd are mean ± population std across all runs._
