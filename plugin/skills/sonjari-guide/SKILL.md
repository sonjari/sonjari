---
name: sonjari-guide
description: How to use the Sonjari MCP. Use it when the user asks you to find and read things on the web and turn them into a table, document or spreadsheet, or hands you work that needs the real logged-in browser or files on this PC. Also use it for requests like "have Sonjari do it" or "do it with Sonjari".
---

> **If the Sonjari MCP tools (`sonjari_task` and the rest) are not available in this session**, Sonjari is not
> connected to this Claude yet. This plugin carries only this guide; the connection is made by the Sonjari desktop app.
> Tell the user these three steps, then stop and wait for them:
> 1. Install Sonjari from the Microsoft Store (https://apps.microsoft.com/detail/9N458V8HPTR2). Windows 10/11 with an NVIDIA GPU; macOS is in beta.
> 2. Open the app, go to **Settings › Connect**, and press **Connect** next to Claude Code or Claude Desktop.
> 3. Start a new Claude session (Claude Desktop restarts itself when you press Connect).
>
> Do not install the app, edit Claude's settings, or run any setup command yourself. The user does these steps.

<!-- sonjari-guide: generated -->
# Sonjari guide

Sonjari is a local AI work assistant that runs on the user's PC. It works directly with the user's **real Chrome** (sites they are logged in to), files,
and Word/Excel/Hangul documents. Use this skill only while the Sonjari MCP server is connected.

## What to hand off / what not to

Sonjari has three things. Your tools do not have them.

- **The user's real Chrome** — sites the user is logged in to open as they are. Your web search and automation browsers (Playwright etc.)
  are empty browsers with no login, and they are often blocked by the bot checks of Korean sites such as Naver, Coupang and Saramin.
- **Research read on this PC** — even when it reads many pages, the page text does not pile up in this conversation's context; only the result (summary, source URLs) comes back.
  Measured 2026-10-02 (n=1): the same job-post research cost $1.25 done by you alone · $0.19 handed to Sonjari.
- **Files and documents on this PC** — reading Word, Excel and Hangul (.hwp) files, and making new documents.

| Good for Sonjari | Good for you |
|---|---|
| Find and read on sites → organize into a file (job posts · products · prices · competitors) | Summarizing or translating text already in the conversation · general knowledge questions |
| Viewing sites that need a login · Korean sites with bot checks | Big design · fixes across many files · code for an API you have not seen before — see "When editing code on this PC" below |
| **Narrow** code work in a repository (one or two files · a command that means done when it passes) — see "Handing off code work in a repository" below | Designing how to split that work · reviewing and merging the branch that comes back |
| Research **while coding** that reads many pages — library docs · error messages · version differences | Design · hard debugging calls |
| Checking screens **while coding** that only show with the user's login (admin pages · deployed services) | Checking **an app you just started** (`http://localhost:…`) — your test tools are faster and you see the result directly |
| Reading code files on this PC · writing the fix you made into that file · documents on the user's PC | Reviewing what Sonjari returns |

### You can check the results you handed off

Results are not just words — you get `sources` (the URLs read and the original text at that spot), `files` (paths of the files made), and, when it says
"there was none", **the range it actually looked at** (search terms · counts). `unsupported_numbers` are numbers the tools never saw. Check with that
evidence, and fill only the missing cells yourself.

### Why hand off while coding, and in what order (2026-09-29)

If you do research yourself while coding, the page text piles up in **this conversation's context**. Hand it to Sonjari and the pages are read on the
user's PC; only the result (summary · source URLs) comes back. In exchange it is **slow**, because it is a local model (tens of seconds to a few minutes) —
hand off research you can keep working through while you wait. The order is **cheapest first → check the evidence → do it yourself if it falls short**:
hand it off, check with the `sources` that come back, and if there is a `resume` or the answer falls short, do only the remaining cells yourself.

### When editing code on this PC (2026-10-01 beta tester)

If you hand off "fix my 3ds Max script" whole, Sonjari (a local model) takes a long time **studying an API it has never seen, on the web**
(real use: "Sonjari is searching the internet a lot"). You already know that API. Split it:

1. Have Sonjari **read the file back** — "Return the contents of `D:\...\script.py` as they are (do not change them)".
2. **You** write the code changes.
3. Have Sonjari **write them as they are** — put the path and the new content directly in the task text. If the folder is not allowed, an approval card appears in the Sonjari window — tell the user to look at that window.

### Handing off code work in a repository — the `repo` and `check` fields (2026-10-09)

Narrow code work can be handed off whole. Give `sonjari_task` two more fields.

- `repo` — absolute path of the repository (or a folder inside it). Sonjari takes a **new branch** of that repository separately and edits only there.
  It does not touch the original folder. Uncommitted changes (to tracked files) come along — newly created files must be committed to be seen.
- `check` — a one-line command that means done when it passes (e.g. `python -m pytest -q tests/test_x.py`). **What counts as done is this command, not the task text.**
  Sonjari does not guess requirements from the text. When it is about to report, it runs this command itself, and if it fails, it reads the output and fixes.

Write the task text like this.

1. **Name the place to fix** — the file and the function. This finishes far more often than "put it wherever it fits".
2. **Put what counts as done in `check`.** The most solid way is to write the acceptance test yourself first, commit it, and give that test as `check`.
   If you hand off the tests too, write each thing to keep on its own line (one test comes back per line).
3. **One or two files at a time.** Design and split a big feature yourself, then hand the pieces off one by one — only one job runs at a time.

What comes back is in `branch`: `changed` (changed files) · `check` (did it pass · how many runs) · `take_home` (command to view · command to take it ·
command to discard). **Read what changed before taking it** — Sonjari does not merge into the original folder. Merging is your call.

There is no time limit. Instead, if it is going nowhere it stops and gives the reason in `branch.stopped_because` (the same failure repeats · rewrote the same
file without running it · nothing new was done). Handing it off again unchanged stops at the same place — split it smaller or fix the stuck spot yourself.
If the user gives another task in the Sonjari window while a handed-off job is running, the handed-off job steps aside between steps and then continues.

Measured (24GB graphics card · 27B model · 2026-10-09 · 1 run): one function and its six tests — 270 seconds, check command passed, no failed steps.
The day before, a big feature handed off as text only, without these fields (touching three 10,000-line files), did not finish either of two times. Not yet
measured with 9B or smaller models — for a small model, split it finer (one function) and always read the result.

### What to hand off depends on the Sonjari model size (2026-10-01 night)

The Sonjari model differs from PC to PC (4B · 9B · 27B · 35B). When you call `sonjari_guide`, **this PC's model and "good to hand off / do it yourself"**
are attached at the end — split the work by that table. If a result comes with `model_hint`, the Sonjari model is small for that job — pass it on to the user as is.

## Order

1. **Hand off one task whole with `sonjari_task`.** Do not call the low-level tools directly many times — each step
   makes the conversation longer, which is slow and expensive. Get the result with `sonjari_task_status` (call it again until it is done).
2. **Put three things in the task text**: what · where (site name) · which file (`.xlsx`·`.docx`·`.md`).
   E.g. "Find 3 marketing job posts in London on Indeed and put each one's company, deadline and requirements into an Excel file".
   **Write the task in the language the user is using with you.** The Sonjari model reads both Korean and English.
   **Do not write a save folder** — then it is saved in the Sonjari output folder (under Documents) and the path comes back in `files`.
   If you write some other place, such as your working folder, it stops at the approval card in the Sonjari window (if nobody is at the PC, it just waits).
   If the file has to be there, move it yourself after you receive it.
   **Keep the task short, with few items, and say what to do** (2026-11-09 · 1,197 browser jobs handed off by Claude): tasks under
   100 characters finished 67% of the time, tasks over 500 characters 23%. With 3 or fewer required items 67%, with more than 9 items 31%.
   Tasks containing "don't / not / except" finished 40% (60% without).
   - At most 3–4 required items per task. If there are more, split them and hand off the next one after the previous one finishes.
   - Stay under 500 characters. Leave out background and reasons; write only what to do.
   - Say what to do instead of what not to do: "don't summarize" → "copy the subtitle lines as they are", "don't make a file" → "write it in the answer".
   - Give counts as numbers ("one row for each of the three shops") so Sonjari can count what it has filled.
   - Split results that run to tens of thousands of characters (a full transcript) into parts. Asking for it in one go hits the output limit.
   - For an API or program it has not seen, put the confirmed names and paths in the task (game test: 47 minutes failed whole → 8 minutes with names and paths).
   **For code work, you own the "done" check** (2026-11-09 game test): keep the check outside files Sonjari can edit, and test it both ways
   before handing off (a wrong result fails, a right one passes). Have it print one line for each mismatch saying what differed — then even a small model fixes it in one pass.
   If failures drag on, suspect the check and your task text before Sonjari's code.
3. When you pass on the result:
   - Give the paths in `files` as they are. Do not make up the file contents in your description.
   - If there are `unsupported_numbers` (`status: needs_review`), do not state those numbers as facts —
     first say "there are numbers that could not be confirmed in the sources, so they need checking".
   - Give `sources` along with it as evidence.
4. **One task at a time.** Sonjari runs tasks one by one. If there are several, hand off the next one after the previous one finishes.

## When you hit a wall

- Login · CAPTCHA · payment · identity check: hand it to a person. Do not solve it for them or look for a tool to get around it.
  One exception — for a test app at **a development address on this PC** (`localhost`·`127.0.0.1`·`*.test`), if you write the test account
  (e.g. username "demo_user", password "demo1234") **as is** in the task text, Sonjari enters those values.
  It does not enter values that are not in the text.
- `needs_approval`: an irreversible action is waiting at the approval card in the Sonjari window. Tell the user to look at that window.
- Sending mail · publishing · deleting · paying cannot be done through this connection. Tell the user to do it directly in the Sonjari window.
- "Could not connect": Sonjari is off. Ask the user to turn it on — do not make up results.

## Capability cards — look up "can it do this?" (2026-11-12)

- What Sonjari can do is written as **one file per capability**. Do not memorize this guide; look things up when needed.
- Claude Code: `grep -ril "<word>" cards/` in this skill folder's `cards/` — words in English and Korean both match.
- Codex: the same in `~/.codex/sonjari-cards/`.
- If you cannot search files: call `sonjari_guide` with `query` (e.g. query="unity reference").
- Read the card's needs line (pack to turn on, program) first. Do not assume Sonjari can do something that has no card.

## Tools available now (taken from the tool list at install time)

### Hand off a whole task (4)

- `sonjari_guide` — Returns the Sonjari guide (how to write and hand off a task, how to pass on the result, what to do when stuck…
- `sonjari_task` — Hand one whole task to Sonjari, a local AI running on this PC. It works in the user's real Chrome (including …
- `sonjari_task_cancel` — Stop a task handed off with sonjari_task. Call it when the task was a mistake or the user asks to stop. Only …
- `sonjari_task_status` — Get the progress or result of a task handed off with sonjari_task. If it is not finished, it waits up to wait…
