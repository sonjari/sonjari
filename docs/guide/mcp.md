# Use Sonjari from Claude Code, Codex and Cursor (MCP)

**English** · [한국어](mcp.ko.md)

Sonjari runs on your PC with a local model. Another AI — Claude Code, Claude Desktop, Codex or Cursor — can hand it a whole
task over [MCP](https://modelcontextprotocol.io): "find these on the web and put them in a spreadsheet", "fix this test in
my repo". Sonjari reads the pages and files **on this PC**, so that text never enters the other AI's context window. The
other AI gets back the answer, the files it made, the sources it read, and what it could not confirm.

- [Connect](#connect)
- [Tools](#tools)
- [What comes back](#what-comes-back)
- [Status flow](#status-flow)
- [Recipes](#recipes)
- [Limits and safety](#limits-and-safety)
- [Troubleshooting](#troubleshooting)

---

## Connect

### The easy way — the Connect button

Open Sonjari → **Settings › Connect** → press **Connect** next to the app you use. Sonjari backs up the original config
file first, then adds one entry named `sonjari`.

| App | Where the entry goes | How |
|---|---|---|
| Claude Code | user scope (`claude mcp add-json … --scope user`) | through the `claude` command — Sonjari does not edit `.claude.json` by hand |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` → `mcpServers` (Store build of Claude: the same file under its package folder too) | file edit, original backed up |
| Cursor | `~/.cursor/mcp.json` → `mcpServers` | file edit, original backed up |
| Codex | `codex mcp add` if available, otherwise `~/.codex/config.toml` → `[mcp_servers.sonjari]` | CLI or file edit |

Restart the app after connecting (Claude Desktop has to be fully closed — Sonjari offers to wait for that).

Connecting also installs a short usage guide for the other AI:

| App | Guide file | Pointer added to |
|---|---|---|
| Claude Code | `~/.claude/skills/sonjari-guide/SKILL.md` | `~/.claude/CLAUDE.md` |
| Codex | `~/.codex/sonjari-guide.md` | `~/.codex/AGENTS.md` |
| Cursor | — (user rules live inside the app; Sonjari shows text to paste) | — |
| Claude Desktop | — (apps cannot install skills there) — call the `sonjari_guide` tool once instead | — |

### By hand

The entry has no secrets. With the Microsoft Store build it looks like this (Sonjari fills in your real paths when you
press Connect — copy them from there if you can):

```json
{
  "mcpServers": {
    "sonjari": {
      "command": "%LOCALAPPDATA%\\Microsoft\\WindowsApps\\sonjari-mcp.exe",
      "args": ["-m", "alture_jarvis.mcp_server"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "JARVIS_BASE_URL": "http://127.0.0.1:8091",
        "JARVIS_TOKEN_FILE": "<path to Sonjari's control.token>",
        "JARVIS_MCP_MAX_RISK": "L1"
      }
    }
  }
}
```

Built from source, `command` is your `.venv\Scripts\python.exe` and `env` also has `PYTHONPATH` pointing at `src`.

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.sonjari]
command = "<same command>"
args = ["-m", "alture_jarvis.mcp_server"]
env = { PYTHONIOENCODING = "utf-8", JARVIS_BASE_URL = "http://127.0.0.1:8091", JARVIS_TOKEN_FILE = "<path>", JARVIS_MCP_MAX_RISK = "L1" }
```

| Variable | Meaning |
|---|---|
| `JARVIS_BASE_URL` | Sonjari's local backend. Only `127.0.0.1` — nothing listens on the network. |
| `JARVIS_TOKEN_FILE` | file holding the local token; the token itself is never written into the config |
| `JARVIS_MCP_MAX_RISK` | highest risk level exported. `L1` (default) never exposes irreversible actions |
| `JARVIS_MCP_INCLUDE` / `JARVIS_MCP_EXCLUDE` | comma-separated tool names to force in / out (include wins) |
| `JARVIS_MCP_EXCLUDE_PREFIXES` | name prefixes hidden by default: `camera_`, `ui_` |

---

## Tools

Three tools are always there. Domain packs add their own when switched on (for example the game pack adds `unity_*`).

### `sonjari_task` — hand over one whole task

Returns a `job_id` immediately. Put **what, where and which file you want back** in one sentence. One call here is faster
and cheaper than driving low-level browser tools step by step.

| Field | Type | Required | What it does |
|---|---|---|---|
| `task` | string | yes | the task in one sentence, in the user's language (up to 4,000 characters) |
| `needs` | string[] | no | up to 12 item names that must come back, e.g. `["product", "price", "address"]`. The result says per item whether it was filled (`met: true / false / null`). Phone numbers and e-mail addresses are only returned when you name them here; ID numbers, card numbers and secret keys are always masked |
| `repo` | string | no | **code jobs:** absolute path of a git repo (or a folder in it) on this PC. Sonjari works on a **new branch in its own worktree** and never touches your folder. Uncommitted changes to tracked files come along |
| `check` | string | no | with `repo`: one command that decides "done" (run in that folder, exit code 0 = pass), e.g. `python -m pytest -q tests/test_x.py`. Sonjari fixes until it passes or says it could not |
| `skill` | string | no | name of a skill to use; leave empty if unsure |

Leave the save folder out — results go to `Documents\Sonjari` and the paths come back in `files`. If you name another
folder, a person has to approve it in the Sonjari window, and the job waits until they do.

### `sonjari_task_status` — progress and result

| Field | Type | Required | What it does |
|---|---|---|---|
| `job_id` | string | yes | from `sonjari_task` |
| `wait_sec` | integer | no | waits up to this long before answering. Default and cap: 240 s for Claude Code, 50 s for other apps. Leave it empty — every poll makes the calling AI re-read its whole conversation |

### `sonjari_guide` — read once before the first task

Returns the same guide that Connect installs as a skill: how to phrase tasks, how to relay results, what to do when Sonjari
is stuck. Read-only.

---

## What comes back

From `sonjari_task_status` when the job has finished:

| Field | What it is |
|---|---|
| `status` | see [Status flow](#status-flow) |
| `answer` | Sonjari's answer |
| `files` | paths of files it made |
| `sources` | addresses and files it actually read |
| `unsupported_numbers` | numbers in the answer or files that **no tool ever returned** — do not pass them on as facts |
| `needs` | per item you named: `met` = `true` (a value is there), `false` (the slot is empty), `null` (could not find the slot — check the answer yourself) |
| `completion_state` | `complete` or `partial` |
| `review_notes` | short notes to read before relaying the answer |
| `resume` | present when the job is unfinished: `evidence` (already read — do not reopen) and `next` (what is left) |
| `branch` | code jobs: `name`, `changed`, `changed_count`, `stat`, `check` (passed or not), `wording_only` (files where only docstrings or comments changed), `take_home` (`review` / `take` / `discard` commands) |
| `cost` | seconds, pages read on this PC, and `host_context_kept_out.tokens_at_least` — a **lower bound**, with its `basis` |
| `receipt` | one line to show the user |

While the job runs you get `progress.doing` (what it is doing now), `progress.requested` (items done n/m), `steps`, and
`jobs_ahead` while queued. Sonjari does one job at a time.

---

## Status flow

| `status` | Meaning | What the calling AI should do |
|---|---|---|
| `queued` | waiting behind another job | poll again |
| `running` | working | relay `progress.doing` in one line; poll again |
| `needs_approval` | an irreversible step, or a question, waits for the person in the Sonjari window | tell the user to look at the Sonjari window. Do not answer on their behalf |
| `needs_decision` | stuck in the same place, or a sign-in / CAPTCHA / payment page | relay `message` as is. For sign-in and CAPTCHA, Sonjari resumes on its own once the person is done — keep polling |
| `done` | finished | relay `answer`, `files`, `sources` |
| `needs_review` | finished, but the answer has numbers no tool returned | say they need checking |
| `failed` / `cancelled` | stopped | still use `files`, `sources`, `resume` — that is the work done before it stopped |

---

## Recipes

**Research into a file**

```text
sonjari_task(task="Find 3 marketing job posts in Seoul on Saramin and put company, deadline and link in an Excel file",
             needs=["company", "deadline", "link"])
sonjari_task_status(job_id=...)   # leave wait_sec empty
```

**A narrow code change, checked by a command**

```text
sonjari_task(task="Make test_parse_dates pass without changing the test",
             repo="C:/work/myapp",
             check="python -m pytest -q tests/test_dates.py")
```

When it is done, look before you take it:

```powershell
git -C C:/work/myapp diff <base>..sonjari/task-<n>         # branch.take_home.review
git -C C:/work/myapp cherry-pick -n <base>..sonjari/task-<n>  # branch.take_home.take
```

Give Sonjari narrow jobs with a clear check — one or two files. Large designs and unfamiliar APIs are better written by the
calling AI and handed to Sonjari to apply and test.

---

## Limits and safety

- Sonjari only listens on `127.0.0.1`. The MCP entry carries a token **file path**, not the token.
- Irreversible actions (sending mail, publishing, paying, deleting) are **not exported** at the default `L1`. A person does
  them in the Sonjari window.
- Sign-in pages, CAPTCHAs and payment pages are handed to the person. Sonjari never solves CAPTCHAs.
- Code jobs never change your working folder — only a separate branch you can review or throw away.
- Local models are slower than cloud models. Sonjari saves the calling AI's context and usage; it does not promise to be
  faster.
- What leaves your PC is drawn out in [What leaves your PC](privacy.md).

---

## Troubleshooting

| Symptom | Check |
|---|---|
| The app does not list `sonjari` | restart the app after connecting; Claude Desktop must be fully closed first |
| Tools are listed but calls fail with a connection error | Sonjari is not running — open it (the backend starts with it) |
| Every call waits in `queued` | another job is running; Sonjari does one at a time |
| A job waits forever at `needs_approval` | someone has to answer the card in the Sonjari window |
| Code job refused | `repo` must be a git repository on this PC, inside a folder Sonjari is allowed to use |
