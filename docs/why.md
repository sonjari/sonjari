# Why we built it — and the rules it keeps

**English** · [한국어](why.ko.md)


What do you use your subagents for?

Your main agent wants to take on most of your work. A subagent should take the part that is tedious and expensive: clicking
through a booking site, reading twenty pages, filling in a form. In most setups that part still runs on the same paid model and
the same usage limit.

So we built Sonjari to take that part off it. It runs on your own GPU, in your own browser. It is a full agent first, because it
has to work well on its own before it is worth handing anything to: it does web research, Excel, Word and Hangul documents, and
code by itself. Claude Code, Codex or Cursor can also hand it a task over MCP and get back only the answer, its sources and a
short receipt.

It acts, not just reads. It will take a booking up to the pay button and stop there. You press it.

It is not as smart as your main agent, and it is built not to pretend otherwise. Every result says where it looked, so you or
your main agent can check it.

We did not wrap an existing agent framework. The browser hands, the checks and the receipts were built for this from the start.

## Principles

- **Local first.** The backend listens on `127.0.0.1` only. Conversations and files stay on the PC — the one exception is a
  problem report you choose to send, and it shows you exactly what will be sent first.
- **No meter.** The model runs on your hardware; there is no per-token charge from us.
- **Honest results.** Numbers that no tool actually returned are flagged instead of presented as facts. A job that did not
  finish says what it did and where it stopped.
- **Irreversible actions need you.** Sending mail, publishing, paying and deleting wait for an approval card in the app
  window. They cannot be approved from an outside AI.
