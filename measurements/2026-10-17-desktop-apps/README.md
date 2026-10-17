# Desktop apps through their own windows — 2026-10-17

Can a local model drive ordinary Windows apps itself, not just call a tool that writes the file? Ten everyday jobs, each
done through the app's own window, three runs each. Published with the runs that failed before the fixes.

## Setup

- One PC: RTX 3090 24 GB, Windows 11, Ollama 0.35.1, one request at a time
- Model: Swift-1.5-Qwen3.8-27B-GSQ-RCO, IQ3_S GGUF (a Qwen3.8 27B finetune with vision), window 131072
- Window control: Windows UI Automation (pywinauto)
- **Approvals were auto-passed for this test.** With default settings each window action waits for an approval card,
  so a real run takes as long as the person takes to click.

## The jobs

| App | Job |
|---|---|
| Notepad | type one line and save it under a given name |
| Calculator | compute 1234 × 5678 and read the result off the screen |
| Paint | open a PNG and save it as a JPEG under the same name |
| Excel | new workbook, fill four cells, save under a given name |
| Word | new document, type one sentence, save |
| PowerPoint | new presentation, type the first slide's title, save |
| Hangul (HWP) | open a .hwp file and save it as PDF through Hangul's own menu |
| File Explorer | make a new folder through Explorer's "New folder" |
| VS Code | open a text file and add a line at the end, save |
| Task Manager | read the top memory users and the graphics-card memory, end nothing |

## How a run is judged

A run passes only if all three hold:

1. **The output is really there** — the file exists and holds the right content (cells, sentence, slide title, a real JPEG,
   a PDF of nonzero size, the new folder), or the answer contains the right value (7,006,652; Task Manager's GPU memory
   within ±15% of `nvidia-smi` at the same moment).
2. **The app window was operated** — at least one executed window action. Task Manager is a read-only job and is exempt.
3. **No shortcut** — the agent did not write the file with its own document tool or a shell command instead.

## Results

| Phase | Passed |
|---|---|
| Before the fixes (one run per app) | 5 of 10 |
| Some fixes in (one run per app) | 5 of 10 |
| After the fixes (three runs per app) | **30 of 30** |

Time per job after the fixes (three runs):

| App | Seconds | Steps |
|---|---|---|
| Notepad | 76–112 | 11–13 |
| Calculator | 116–132 | 24 |
| Paint | 96–124 | 14–19 |
| Excel | 297–614 | 51–69 |
| Word | 213–385 | 32–48 |
| PowerPoint | 213–498 | 27–64 |
| Hangul → PDF | 100–164 | 12–13 |
| File Explorer | 88–101 | 13 |
| VS Code | 108–193 | 14–26 |
| Task Manager | 44–52 | 2–3 |

A person does any of these in under a minute. Most of the time is the model thinking: one 10-minute Excel run made 70
model calls. In normal use Sonjari writes files directly and only drives a window when nothing else reaches; this test forced
the window on purpose.

## What broke, and what changed

- **Menus that ignore "invoke".** Hangul's menus accept the UI Automation invoke signal without error and do nothing. Visible
  menu items are now clicked for real.
- **Task Manager can't be read.** It runs elevated on Windows 11, so a normal process cannot read inside its window. The same
  numbers (private working set summed per app, which is what Task Manager shows) are now read directly and were checked
  against a screenshot taken at the same moment.
- **A HEIC file named .jpg.** Paint's file-type box is a list; the agent typed `.jpg` into the name and left the type alone.
  List boxes are now set by picking the item, and every saved file's first bytes are checked against its extension.
- **Window jobs routed away from the window tools.** PowerPoint, File Explorer and VS Code weren't recognized as "operate this
  program", so the window tools were unavailable and the agent made the file with its own tool (and said so).
- **The step limit hit right before saving.** Each window action is a preview plus an execution. Previews no longer use up the
  step budget, and executed window actions count as progress toward a file.
- **A shell command that never returned.** `code file.txt` started an editor that kept the output pipe open; the run hung for
  15 minutes. Commands now return a few seconds after they exit, whatever they started.
- **Opening a file in a chosen app.** Opening a PNG launched the default viewer, so the agent reached for the shell to start
  Paint. The open tool now takes an app name.

## Same jobs, normal wording (later the same night)

The runs above forced the window on purpose. Then the same ten jobs were asked the way a person would ("make a Word file
with this sentence", no "operate the window"), three runs each. A run passes when the output is really there; the agent may
use any route.

| App | Normal wording | Route the agent chose |
|---|---|---|
| Excel | 20 s | its own file tool, 3 of 3 |
| Word | 16 s | its own file tool, 3 of 3 |
| PowerPoint | 16–20 s | its own file tool, 3 of 3 |
| Calculator | 28–36 s | computed it, 3 of 3 |
| File Explorer | 40–44 s | its own file tool, 3 of 3 |
| Notepad | 92–144 s | the window, 3 of 3 |
| Paint | 84–160 s | the window in 2 of 3 |
| VS Code | 132–161 s | the window, 3 of 3 |
| Hangul to PDF | 145–281 s | the window, 3 of 3 |
| Task Manager | 56–164 s | its value-reading tool |

All 30 passed. For four apps the agent still drove the window and took minutes.

**Fix 1: naming an app means the result's format.** If the request names Notepad, Paint, VS Code or Hangul and does not ask
to operate the window, the agent is told to write the file with its file tools and offer to open it in that app afterwards.
Three runs each: Notepad 24–52 s, Paint 60–96 s, VS Code 24–28 s, all by file tools, all passed.

**Fix 2: Hangul to PDF got its own tool.** It copies the file, opens it in a hidden Hangul instance (never the user's open
window), saves as PDF and checks the result really starts with `%PDF`. The first three runs after adding it went **0 of 3**:
the tool was registered and its tests passed, but a routing rule classified "save this .hwp as PDF" as web research, and that
route drops the Hangul tools from the list the model sees. Asked directly, the model said the tool wasn't in its list. After
routing Hangul file jobs as local work: 3 of 3 in 40–76 s, but each was marked "partly done" because the planner read the
source `.hwp` as the format to produce. After fixing that: **3 of 3 in 20–24 s, one step.**

Lesson: a tool that passes its own tests can still be invisible to the model. Checking what the model actually receives
caught it in one run; the unit tests never could.

## Caveats

- One PC, the largest model, three runs per app. Smaller cards were not measured on these jobs.
- These are single-step jobs ("do one thing and save"). Longer multi-app work is not measured.
- Approvals were auto-passed (see Setup).

## File

- `runs.json` — one entry per run: phase, app, round, passed, output verified, number of executed window actions, whether the
  agent used its own file tool or a shell instead, seconds, steps, why it stopped, and model prefill / generation seconds.
  **Numbers and yes/no only**: no prompts, answers, file paths or page text.
- `runs-normal-wording.json` — the normal-wording runs and the fixes after them, one entry per run: phase, app, round,
  passed, route the agent chose (window / its own tool / hwp_export_pdf), window actions, seconds, steps, why it stopped,
  whether the agent's own plan check called it done, and model prefill / generation seconds. Same rule: numbers only.
