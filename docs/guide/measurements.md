# What we measured — and where it falls short

**English** · [한국어](measurements.ko.md)

Moved here from the README on 2026-11-02, unchanged. Older runs and raw records are in [`measurements/`](../../measurements/).

We publish the runs that went badly too. These are small numbers; read them as that.

| Setup (fresh profile, store build) | Task | Result |
|---|---|---|
| Recommended 24 GB model | 5 different research → file tasks, one run each | 5 of 5 finished, 27–93 s |
| 12 GB-class model (9B) | GitHub trending top 3 → Excel | 7 of 7 runs finished, 38–65 s |
| 12 GB-class model (9B) | arXiv latest 3 → comparison table | 4 of 4 |
| 12 GB-class model (9B) | A Korean bookstore, 3 books → Excel | 3 of 3 |

In none of those runs did it report an unfinished job as finished.

### The same price task, on real cards

Visit three shops (Danawa, 11st, Gmarket), find the same product, and write name, price, shipping and the product-page
address into an Excel file. A row counts only if the value is on the page Sonjari actually read. Three products a round.

| Card · model | Rounds | Whole rows | Time per task |
|---|---|---|---|
| RTX 3090 24 GB · 27B | 3 | 26 of 27 | about 6 minutes (median) |
| RTX 5050 Laptop 8 GB · 9B, compressed, text only | 7 | 37 of 63 | about 7.5 minutes |
| RTX 3050 Laptop 6 GB · 4B, compressed, text only | 7 | 10 of 63 — weak (before a memory-leak fix) | — |

With picture reading on, neither small model fully fit on its card, which is why small cards default to text only. If you
send what you measure on your card, this table gets filled in — see [Contributing](../../CONTRIBUTING.md), door 1.

### With Claude Code — same task, clean setup

Claude Code (`claude-sonnet-5`) drove all four arms, each run in a clean folder with no instruction files above it. Sonjari
ran the 27B on an RTX 3090. 3 products × 3 rounds = 27 rows per arm.

| Arm | Whole rows | Claude cost per whole row | Median time per task |
|---|---|---|---|
| Claude Code + Sonjari's browser tools | 17–23 of 27 | $0.074–0.100 | 401 s |
| Claude Code hands the whole task to Sonjari | 15–18 of 27 | $0.075–0.090 | 391 s |
| Claude Code alone (web fetch and search) | 15 of 27 | $0.246 | 96 s |
| Claude Code + Playwright MCP | 11 of 27 | $0.635 | 162 s |

- The two Sonjari arms are shown as a range because some of their rows were graded by hand (6 for the browser tools,
  3 for the handoff). Automatic grading alone gives the lower number. Details are in the
  [measurement record](../../measurements/2026-10-19-head-to-head/README.md).
- Counting only automatically graded rows, no difference in correct rows is clear at this size: Sonjari's tools vs
  Playwright 10 vs 4 (sign test p = 0.18), vs Claude alone 7 vs 5 (p = 0.77). With the hand-graded rows the same pairs
  are 13 vs 1 (p = 0.0018) and 9 vs 1 (p = 0.022). An earlier version of this page quoted only the second set.
- It is slow: 6–7 minutes a task against about 1.5 for Claude alone.
- The handoff arm missed 9 rows counting the hand-graded ones (12 by the automatic grader alone; the extra 3 are hand-graded rows
  the saved files cannot confirm). 6 of the 9 were the agent waiting for an approval nobody was there to give; 3 were one shop page that
  never finished loading. Playwright lost most of its rows to one shop's bot block.
- Our own grader was wrong several times while we built this; each fix was re-run over every past row. Three of the 36
  cells were confirmed by hand, because the pages Sonjari had read were no longer stored at the time.

### Driving desktop apps through their own windows

Ten everyday jobs in ten apps (Notepad, Calculator, Paint, Excel, Word, PowerPoint, Hangul → PDF, File Explorer, VS Code,
Task Manager), each done through the app's own window, three runs each. A run passes only if the output is really there
(the file with the right content, or the right value), the window was actually operated, and the agent did not quietly
write the file with its own tool instead. 27B on an RTX 3090; approvals were auto-passed for the test.

| | Passed |
|---|---|
| Before the fixes (one run per app) | 5 of 10 |
| After the fixes (three runs per app) | 30 of 30 |

It is slow: about 1.5–3 minutes for Notepad, Calculator, Paint, File Explorer, Hangul and VS Code, 3.5–8 for Word and
PowerPoint, 5–10 for Excel, where a person needs under a minute. In normal use Sonjari writes
files directly and only drives a window when nothing else reaches. What broke and what changed:
[measurements/2026-10-17-desktop-apps](../../measurements/2026-10-17-desktop-apps/README.md).

### Coding on outside exercises

12 of the 34 Python exercises in the [Aider polyglot benchmark](https://github.com/Aider-AI/polyglot-benchmark), done by
Sonjari in code mode. One run per exercise, 64K window, 600-second cap, RTX 3090. The model never sees the reference
solution, and the tests are put back to the original before grading.

| Model | Passed | Median time per run |
|---|---|---|
| Swift 1.5 (Qwen3.8 27B), IQ3_S + MTP — recommended for 24 GB | 12 of 12 | 119 s |
| Qwen3.8 27B, same compression without the Swift finetune | 11 of 12 | 251 s |
| Ornith 1.5 35B-A3B, IQ4_XS | 9 of 12 | 136 s |
| Qwen3.5 9B, Q4_K_M (12 GB class), two rounds | 5 of 12 both times | 135 s / 485 s |

Not comparable with Aider's leaderboard (225 exercises, six languages, two tries). Every exercise, the runs that hit the cap,
and one 16 GB-class candidate: [measurements/2026-10-08-coding](../../measurements/2026-10-08-coding/README.md).

Where it falls short:

- **On a small card, long research gets about halfway.** Comparing across several shops tends to lose one or two of them.
  Finding one place, reading it and writing a document works.
- **Left alone, it can stop and wait for you.** If a task asks it to save a file outside the folders it may write to, it waits
  for your approval in the app. That is on purpose, but an unattended run sits there until you answer.
- **A wrong number can still land in a table.** One of the seven 9B runs wrote 8,000 where the page said 91.2k stars. The number
  was on the page (a different column), so the evidence check could not catch it. Check what matters against the sources it shows.
- **Fiddly page controls fail often.** Autocomplete boxes, date pickers and cookie overlays are where it breaks. On Online-Mind2Web
  (official setup, our own grading, 12 to 15 tasks a round, three rounds) it finished between a third and a half; 6 of 9 failures in
  the first round were this kind. Reading pages and writing a file is the part that works.
- **Times above are from an RTX 3090.** A real 12 GB card is slower. A local model is slower than cloud AI in general.
- **Takeover:** finding the stopped session is measured; how often it then *finishes* the job is not. It is listed as "takes over",
  not "finishes".
- **Windows and NVIDIA only.** No macOS, Linux or AMD/Intel GPU builds yet.
