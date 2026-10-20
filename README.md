<p align="center">
  <img src="docs/img/working.png" width="880"
       alt="Sonjari at work: the request on the left, and on the right 'Sonjari's computer' showing the page it is reading and how much of the task is done">
</p>

<h1 align="center">Sonjari (손자리)</h1>

<p align="center">
  <b>Your PC does the work. You get the proof.</b><br>
  It works right in front of you, in your own Chrome and your own files — and leaves the proof.<br>
  A free local AI agent for Windows: it researches the web, builds Excel and Word files, and reads and fixes code —<br>
  on its own, or as the hands for Claude Code, Codex and Cursor. No subscription, no usage meter.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <img alt="Windows 10/11 x64" src="https://img.shields.io/badge/Windows-10%20%7C%2011%20x64-0078D4">
  <a href="https://apps.microsoft.com/detail/9N458V8HPTR2"><img alt="Microsoft Store" src="https://img.shields.io/badge/Microsoft%20Store-free-107C10"></a>
  <img alt="Runs on your GPU" src="https://img.shields.io/badge/runs%20on-your%20GPU-76B900">
</p>

<p align="center">
  <a href="README.ko.md">한국어</a> ·
  <a href="https://sonjari.com">sonjari.com</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="https://github.com/sonjari/sonjari/discussions">Discussions</a> ·
  <a href="SECURITY.md">Security</a>
</p>

---

## Documentation

| I want to … | Read |
|---|---|
| see how the maintainers use it day to day — research and coding with Claude Code, with real numbers | [How we use it](docs/guide/workflows.md) |
| use Sonjari from Claude Code, Codex or Cursor — connect, the three tools, what comes back, code jobs | [MCP guide](docs/guide/mcp.md) |
| know exactly what leaves my PC when another AI uses Sonjari | [What leaves your PC](docs/guide/privacy.md) |
| understand which model I got and what to do if it does not fit | [How Sonjari picks a model](docs/guide/models.md) |
| build from source and run the tests | [Developing](#developing) · [Contributing](CONTRIBUTING.md) |


## What it does

- **Proof you can check.** Every run leaves its steps, the pages it read and where each value came from. A number that no
  tool returned is flagged, and a job that did not finish says what it did and where it stopped.
- **Research → file.** Hand it one sentence — *"Open github.com/trending/python, read the top 3 repositories, and save a table
  of name, stars and description as an Excel file"* — and it opens the pages itself, reads them, and writes the table and the file.
- **You can watch it.** "Sonjari's computer" shows the page it is on and how much of the request is done. Add a note mid-task
  to change direction.
- **Your browser, your logins.** It works in a Chrome profile on your PC. When a page needs a login, a CAPTCHA or payment
  details, it stops and hands the screen to you.
- **The hands for your AI.** Claude Code, Claude Desktop, Codex and Cursor can hand it whole tasks over MCP (`sonjari_task`).
  The pages it reads stay on your PC; only the result goes back into the host's context, with a one-line receipt of which
  requested items were filled and what was masked (personal numbers, emails, keys).
- **Picks up where Claude Code stopped.** When Claude Code stops at a usage limit, Sonjari finds how far it got from the
  records left on this PC and asks how to continue. Code changes go to a separate branch; the original folder is not touched.
- **Documents on this PC.** Reads and writes docx / xlsx / pptx / hwpx / pdf inside folders you allow.

<p align="center">
  <img src="docs/img/result.png" width="430" alt="The finished table and the Excel file it saved, with the evidence for each step">
  <img src="docs/img/takeover.png" width="430" alt="Takeover: the Claude Code conversation that stopped at a usage limit, and the choices for how to continue">
</p>

## Install

**Use it** — [Microsoft Store](https://apps.microsoft.com/detail/9N458V8HPTR2) (free, updates itself).

| You need | |
|---|---|
| Windows | 10 (19041) or later, x64 |
| GPU | NVIDIA (see the table below) |
| [Ollama](https://ollama.com) | the first-run wizard offers to install it |
| Chrome | for browser tasks |

| Your graphics card | What Sonjari recommends |
|---|---|
| RTX 3090 · 4090 · 5090 (24 GB or more) | the largest model (27B) |
| RTX 4060 Ti 16GB · 4070 Ti Super · 4080 · 5070 Ti · 5080 (16 GB) | a compressed build of the same model |
| RTX 3060 12GB · 4070 · 5070 (12 GB) | the mid-size model (9B) |
| RTX 3060 Ti · 3070 · 4060 · laptop 4060 · 5050 (8 GB) | the mid-size model (9B), compressed, text only (no picture reading) |
| laptop 3050 · 4050 (6 GB) | the small model (4B), compressed, text only — weak; best shared with the AI you already use |

On first launch the wizard measures this PC, recommends one and downloads it (several GB). You do not need to know your
card's name — or pick any Hugging Face GGUF that fits. How far a small card gets is written out under "What we measured" below.

**Connect your AI** — press *Connect* in the app. It adds the `sonjari_task` MCP entry to Claude Code, Claude Desktop, Codex or
Cursor and backs up the original config first. Setting it up by hand, the tools and what comes back: [MCP guide](docs/guide/mcp.md).

**Build from source**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1
.venv\Scripts\python.exe -m alture_jarvis
```

## What we measured — and where it falls short

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
send what you measure on your card, this table gets filled in — see [Contributing](CONTRIBUTING.md), door 1.

### With Claude Code — same task, clean setup

Claude Code (`claude-sonnet-5`) drove all four arms, each run in a clean folder with no instruction files above it. Sonjari
ran the 27B on an RTX 3090. 3 products × 3 rounds = 27 rows per arm.

| Arm | Whole rows | Claude cost per whole row | Median time per task |
|---|---|---|---|
| Claude Code + Sonjari's browser tools | 23 of 27 | $0.074 | 401 s |
| Claude Code hands the whole task to Sonjari | 18 of 27 | $0.075 | 391 s |
| Claude Code alone (web fetch and search) | 15 of 27 | $0.246 | 96 s |
| Claude Code + Playwright MCP | 11 of 27 | $0.635 | 162 s |

- At this size only "Sonjari's tools vs Playwright" is a clear difference (13 rows only Sonjari got, 1 only Playwright got;
  exact sign test p ≈ 0.002). Against Claude alone it is borderline (9 vs 1, p ≈ 0.02 before correcting for several
  comparisons). The rest is within noise.
- It is slow: 6–7 minutes a task against about 1.5 for Claude alone.
- 6 of the handoff arm's 9 misses were the agent waiting for an approval nobody was there to give; 3 were one shop page that
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
[measurements/2026-10-17-desktop-apps](measurements/2026-10-17-desktop-apps/README.md).

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

## Principles

- **Local first.** The backend listens on `127.0.0.1` only. Conversations and files stay on the PC — the one exception is a
  problem report you choose to send, and it shows you exactly what will be sent first.
- **No meter.** The model runs on your hardware; there is no per-token charge from us.
- **Honest results.** Numbers that no tool actually returned are flagged instead of presented as facts. A job that did not
  finish says what it did and where it stopped.
- **Irreversible actions need you.** Sending mail, publishing, paying and deleting wait for an approval card in the app
  window. They cannot be approved from an outside AI.

## Contributing

> **Whatever your work is, your field experience is Sonjari's teacher.**
> Every failure you report becomes a test Sonjari must pass, forever.

That is already how it is built: tests are named after the day a real run failed — `test_an_unresponsive_runner_is_asked_once_more_1015`
is a 6 GB laptop that lost a task one night in October.

Five ways in, easiest first — details in [CONTRIBUTING.md](CONTRIBUTING.md):

1. **Measure it on your graphics card.** One command; it produces a file with numbers only. This is what we lack most.
2. **Fix one site.** If Sonjari reads the wrong links on a site you use, a two-line JSON file in `recipes/result_links/`
   usually fixes it. No Python needed.
3. **Report a run that went wrong.** Use *Report a problem* in the app, or open an issue with what you asked and what happened.
4. **A text-only skill pack.** A bundle of notes on "this kind of job is done like this". Packs that carry tools are not
   accepted yet — see why in CONTRIBUTING.
5. **Code.** Core parts included. Attach one test — we do the measuring.

The door is wide for now. As more people arrive, changes to the core will move to "talk first, then send".

## Developing

```powershell
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
cd ui; npm ci; npm run build
```

Copy `.env.example` to `.env` only if you need to change a default. Never commit `.env`, `data/`, OAuth tokens or browser
profiles. Internal names (`alture_jarvis` package, `JARVIS_*` variables, `X-JARVIS-TOKEN` header) come from the project's
earlier name and are kept so existing installs keep working.

## How this is built

Sonjari is maintained by two people, so replies can be slow. Much of the code is written with Claude (Anthropic) as a coding
collaborator — commits carry a `Co-Authored-By` line — and every change is run, checked and released by the maintainers.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Third-party components keep their own licenses; see `packaging/THIRD_PARTY_NOTICES.md`.
The optional camera module uses Ultralytics YOLO (AGPL-3.0); it is **not** installed by default.
"Sonjari", "손자리" and the Sonjari logo are trademarks. The license covers the code, not the name or logo
(Apache-2.0, section 6). Forks are welcome under a different name.
