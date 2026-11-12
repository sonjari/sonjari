# Sonjari for Claude

Sonjari is a local AI that runs on your own graphics card. This plugin lets Claude hand it the token-heavy part of a job
(browsing many pages in your logged-in Chrome, reading files on your PC, narrow coding jobs in a repository) and get back
only the answer and the sources it read. Claude keeps the thinking; your GPU does the reading.

## What you need

| | |
|---|---|
| The Sonjari desktop app | [Microsoft Store](https://apps.microsoft.com/detail/9N458V8HPTR2) (free). macOS is in beta. |
| Windows | 10 (19041) or later, x64 |
| Graphics card | NVIDIA. The app's first-run wizard picks a model that fits your card. |

**This plugin does nothing on its own.** Without the app, the `sonjari` MCP server cannot start, and Claude will tell you
to install the app first.

## What the plugin contains

- **An MCP server, `sonjari`.** Claude Code and Cowork start it with the command `sonjari-mcp -m alture_jarvis.mcp_server`.
  `sonjari-mcp` is installed by the Sonjari app (on Windows it is an app execution alias from the Microsoft Store package).
  The plugin does not download or install anything.
- **A skill, `sonjari-guide`.** It tells Claude when a job is worth handing off, how to write the task, and how to treat the
  result (for example: numbers no tool returned are flagged, not passed on as fact).

Tools: `sonjari_task` (hand off one whole task), `sonjari_task_status` (get progress or the result), `sonjari_task_cancel`
(stop a task you handed off), `sonjari_guide` (the usage guide, or capability cards for one word).

## What it runs, sends and reads

- The MCP server talks **only to the Sonjari app on this computer** (port 8091 on `127.0.0.1`). It does not contact any other
  host.
- To authenticate to the app it reads the app's local token file (`%LOCALAPPDATA%\Sonjari\data\control.token` on Windows,
  `~/Library/Application Support/Sonjari/data/control.token` on macOS). The token is never printed or sent anywhere else.
- What the app itself does (open pages in your Chrome, read and write files you allow, run the local model) happens in the
  app, under its own approval rules. Irreversible actions (sending mail, publishing, paying, deleting) are not available
  through this connection; they need a person to approve them in the Sonjari window.
- The app does not send usage data anywhere. A problem report leaves the computer only when you choose "Report a problem"
  in the app and send it yourself.

## Where it works

| Surface | |
|---|---|
| Claude Code | MCP server and skill |
| Cowork (running on your computer) | MCP server and skill |
| Chat (claude.ai, Claude desktop chat) | skill only; the app connects itself to Claude desktop chat from its own settings |

## Source and license

Source: [github.com/sonjari/sonjari](https://github.com/sonjari/sonjari). License: Apache-2.0.
