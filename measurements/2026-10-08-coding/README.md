# Coding on outside exercises — 2026-10-08 (one row added 2026-10-23)

Our own task ladder was built around our own harness, and the big models all passed it, so it could not tell them apart.
We took exercises from outside instead: 12 of the 34 Python exercises in the
[Aider polyglot benchmark](https://github.com/Aider-AI/polyglot-benchmark) (each one comes from Exercism).

## Setup

- One PC: RTX 3090 24 GB, Windows 11, Ollama, one request at a time
- Sonjari in code mode, window 65,536 tokens, a new folder and a new session for every exercise
- **One run per exercise.** Cap of 600 seconds per run, counted from when the run actually started
- The folder given to the model holds the instructions, the empty function and the test file. The reference solution
  (`.meta/example.py`) is not given
- Grading: after the run, the test file is put back to the original and `pytest` runs. Editing the tests does not help
- Runner: [`bench/coding/run_polyglot.py`](../../bench/coding/run_polyglot.py). The exercises themselves are not in this
  repository (the benchmark repository has no license notice)

**Not comparable with Aider's public leaderboard.** That one runs 225 exercises in six languages through Aider, with two tries.

## Results

| Model (all GGUF) | Passed | Median time per run | Failed steps | Hit the cap |
|---|---|---|---|---|
| Swift-1.5-Qwen3.8-27B-GSQ-RCO, IQ3_S + MTP (our recommended 24 GB model) | **12 of 12** | 119 s | 0 | 0 |
| Same model, IQ3_XXS | 12 of 12 | 169 s | 4 | 0 |
| Qwen3.8 27B GSQ (same base and compression, without the Swift finetune), IQ3_S + MTP | 11 of 12 | 251 s | 6 | 2 |
| Ornith-1.5-35B-A3B, IQ4_XS | 9 of 12 | 136 s | 9 | 3 |
| Qwen3.5 9B, Q4_K_M — 2026-10-08 | 5 of 12 | 135 s | 13 | 4 (+3 stopped early) |
| Qwen3.5 9B, Q4_K_M — 2026-10-12, same setup again | 5 of 12 | 485 s | 13 | 6 |
| Qwen3.6-35B-A3B, Unsloth UD-IQ2_M, card limited to about 12 GB (2026-10-23) | 10 of 12 | 131 s | 6 | 1 |

- "Failed steps" are tool calls that returned an error during the run.
- The 27B general build passed `transpose` by the grader but the run itself was cut at the cap, and it was cut on `zipper`
  with 5 of 14 tests failing.
- The 9B on 2026-10-08 stopped twice to ask "continue?" (`forth`, `transpose`) and failed once (`react`). Those count as not passed.
- The last row was measured to see what a 16 GB card shared with another heavy app could run: llama-server was told to leave
  12 GB of the 3090 free (`LLAMA_ARG_FIT_TARGET`), so part of the model ran on the CPU. It is not the wizard's pick yet.
- Times are from the RTX 3090. A smaller card is slower.

## Per exercise

P = passed, F = not passed. Seconds of work for the run.

| Exercise | Swift 27B IQ3_S | Swift 27B IQ3_XXS | 27B general | Ornith 35B | 9B (10-08) | 9B (10-12) | Qwen3.6 35B IQ2_M |
|---|---|---|---|---|---|---|---|
| affine-cipher | P 88 | P 82 | P 80 | P 43 | P 30 | P 47 | P 57 |
| bottle-song | P 34 | P 78 | P 71 | P 30 | P 65 | P 107 | P 45 |
| dominoes | P 115 | P 98 | P 282 | P 314 | P 23 | P 41 | P 141 |
| forth | P 224 | P 482 | P 220 | F cap | F asked to continue | F cap | F cap |
| grep | P 72 | P 62 | P 83 | P 126 | P 205 | P 292 | P 58 |
| paasio | P 332 | P 343 | P 444 | F cap | F cap | F cap | P 137 |
| poker | P 124 | P 189 | P 184 | P 156 | F cap | F 369 | P 140 |
| react | P 215 | P 148 | P 137 | P 66 | F failed | F cap | P 195 |
| scale-generator | P 172 | P 471 | P 426 | F cap | F cap | F cap | P 125 |
| transpose | P 356 | P 223 | P (cut at cap) | P 146 | F asked to continue | F cap | F 333 |
| variable-length-quantity | P 44 | P 91 | P 283 | P 37 | P 34 | P 36 | P 43 |
| zipper | P 82 | P 191 | F cap | P 60 | F cap | F cap | P 89 |

Small numbers: one run per exercise, one PC. Read them as that.
