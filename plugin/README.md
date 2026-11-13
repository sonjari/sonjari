# Sonjari for Claude

Sonjari is a local AI that runs on your own graphics card. With it connected, Claude can hand it the token-heavy part of a
job (browsing many pages in your logged-in Chrome, reading files on your PC, narrow coding jobs in a repository) and get
back only the answer and the sources it read. Claude keeps the thinking; your GPU does the reading.

This plugin is the guide that tells Claude when a job is worth handing to Sonjari and how. The connection itself is made
by the Sonjari desktop app.

## Setup

1. Install the Sonjari desktop app from the [Microsoft Store](https://apps.microsoft.com/detail/9N458V8HPTR2) (free).
   Windows 10 (19041) or later, x64, NVIDIA graphics card. The app's first-run wizard picks a model that fits your card.
   macOS is in beta.
2. In the app, open **Settings › Connect** and press **Connect** next to Claude Code or Claude Desktop.
3. Start a new Claude session.

**This plugin does nothing on its own.** Until the app is connected, Claude will only tell you these three steps. It does
not install the app or change Claude's settings for you.

## What the plugin contains

- **A skill, `sonjari-guide`.** It tells Claude when a job is worth handing off, how to write the task, and how to treat the
  result (for example: numbers no tool returned are flagged, not passed on as fact).

The plugin ships no MCP server, no commands, no hooks and no code. The tools the guide talks about (`sonjari_task`,
`sonjari_task_status`, `sonjari_task_cancel`, `sonjari_guide`) come from the Sonjari app once you press Connect.

## What the app's connection runs, sends and reads

- **Connect** adds one entry to Claude's MCP settings (Claude Desktop's config file, or `claude mcp add` for Claude Code).
  That entry starts the app's own MCP server, which talks **only to the Sonjari app on this computer** (`127.0.0.1`).
- The app does the actual work (opening pages in your Chrome, reading and writing files you allow, running the local model)
  under its own approval rules. Irreversible actions (sending mail, publishing, paying, deleting) are not available
  through the connection; they need a person to approve them in the Sonjari window.
- The app does not send usage data anywhere. A problem report leaves the computer only when you choose "Report a problem"
  in the app and send it yourself.

Privacy policy: [sonjari.com/privacy](https://sonjari.com/privacy/).

## Where it works

| Surface | |
|---|---|
| Claude Code | the skill, plus Sonjari's tools after you press Connect |
| Claude Desktop | the skill, plus Sonjari's tools after you press Connect |
| Chat on the web or mobile | the skill only; Sonjari runs on your own computer |

## Source and license

Source: [github.com/sonjari/sonjari](https://github.com/sonjari/sonjari). License: Apache-2.0.
</content>
</invoke>
