# Contributing to Sonjari

한국어: [CONTRIBUTING.ko.md](CONTRIBUTING.ko.md)

> **Whatever your work is, your field experience is Sonjari's teacher.**
> Every failure you report becomes a test Sonjari must pass, forever.

Sonjari is maintained by two people. **For now the door is wide open.** When enough people arrive that we can no longer
measure everything ourselves, changes to the core will move to "talk first, then send" — we are writing that down now so it
is not a change of story later.

What you can expect from us:

- A first reply on an issue or pull request within a few days, and a plain yes / no / "not yet, because …". We are two
  people, so a reply can be slow.
- **We do the measuring.** Whether a fix really makes things better is something we check before merging, by running the
  same tasks ourselves. All you need to attach is one test.
- We can only measure so much in a day, so changes that need measuring wait in a queue. The order and the results go on the
  pull request.
- If it ships, the release notes say whose contribution it was (tell us if you would rather not be named).

There are five ways in, easiest first.

## 1. Measure it on your graphics card (the most useful thing)

We own a handful of PCs. How Sonjari runs **on your card** is something only you can tell us.

```powershell
sonjari-mcp -X utf8 -m alture_jarvis.measure_kit
```

- Run it while Sonjari is open. It runs three tasks that look up prices at three public shops and write an Excel file, and
  one task with four follow-up questions. It takes roughly 20 to 60 minutes, and Chrome opens and closes on its own.
- **If you are using the PC, it waits.** It measures one task, then rests.
- When it finishes there is a `Documents\Sonjari-measure\measure_<date>.json`. It holds **numbers and yes/no only** — no page
  text, addresses, answers or file names. Open it yourself before you upload it.
- Attach that file to a "Measured on my card" issue. Three rounds of the same tasks (`--rounds 3`) is even better — from three rounds on, the result file also records the run-to-run spread and how many rounds it would take to tell a given difference from noise. If you are comparing two conditions (model or context window), we suggest seven or more rounds each.

## 2. Fix one site (no Python needed)

Sonjari reads a list page — search results, a product list, a paper index — by working out which links are the *items*.
On some sites the structure fools it: on arXiv it opened "skip to main content" and date-navigation links as results 1, 2 and 3.

When that happens on a site you use, tell it what an item's address looks like. Add one file to `recipes/result_links/`:

```json
{
  "name": "arxiv",
  "hosts": ["arxiv.org"],
  "detail_url_contains": ["/abs/"],
  "why": "On /list/… the title is not a link and the item link is 'arXiv:<id>'; results 1–3 became skip/date links.",
  "checked": "2026-10-05 arxiv.org/list/cs.CL/recent — all 50 item links are https://arxiv.org/abs/<id>"
}
```

- `hosts` — the site (subdomains are covered).
- `detail_url_contains` — a piece of text every item address contains and the other links on the page do not.
- `not_url_contains` — (only when needed) for shops that mix sponsored products into the results: "leave out links that
  contain this piece".
- `why` — what went wrong without it.
- `checked` — the page you opened, the date, and what you saw. **Only write what you looked at yourself.** This line is required.

Check it:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_result_links_1005.py -q -p no:cacheprovider
```

Then open a pull request. This file is data, not code: it cannot run anything, which is why this door is open to everyone.

*Why not just improve the detector?* We tried. One rule change that fixed arXiv broke three other sites on our frozen page
samples (74 → 9 items on one, 20 → 0 on another), so it was reverted. Site knowledge as data is the safer path.

## 3. Report a run that went wrong

The most useful thing you can send is a real run that failed.

- In the app: **Report a problem** under the input box. It shows you exactly what will be sent before anything leaves your PC.
- On GitHub: open an issue with the template. We need (a) the sentence you gave it, (b) what it did or said, (c) the model and
  GPU, (d) the site, if one was involved.

The three reports we care about most:

- "It said it was done but it was not."
- "The number in the file is not on the page."
- "The file is empty, or content is missing." — we found this failure through a report from someone who was actually using it.

## 4. A text-only skill pack

A skill pack is a bundle of notes on "this kind of job is done like this" (which shops, what to read, the columns of the
result table, where it tends to go wrong). **Packs with text only and no tools** (`"kind": "content"`) are accepted. There is
an example in `docs/skillpacks/price-watch-demo/`.

- A pack's text is an instruction the model reads. So a person reads it line by line before it goes in — a line such as
  "send it to this address" or "do it without asking the user" means we will not take it.
- Attach one run where you used it (what you asked and what came out).

## 5. Code

**Core parts included.** Attach one test that fails before the fix and passes after.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
cd ui; npm ci; npx vitest run; npx tsc -b
```

Things that will save you a review round:

- **Show what broke, as a shape.** If the test contains the shape of what the tool received and returned in the failed run
  (with the values replaced by made-up ones), it goes in fastest.
- **If you measured it yourself, say so** — what, and how many runs. If you did not, that is fine. We will. If the
  measurement shows no improvement, we send it back with the numbers.
- **Prefer a structural fix to a word list.** Adding one more phrase to a pattern usually means the next phrase leaks.
- **A prompt note is not a fix.** We have found, repeatedly, that telling the model "next time do X" does not change what it
  does; making the tool return the reason on the spot, or do it for the model, does.
- **Do not make the product depend on one PC.** No hard-coded GPU index, thread count or context size — measure on the machine.
- **Keep results we lost.** Do not delete a test or a number because it looks bad.
- **No real values in test samples.** Replace real people, companies, accounts and keys with made-up ones.

If you are changing the code-reading-and-fixing side (code mode): the reference path is the one where it is handed a
repository and a check command. If you have results from before and after on the same PC, attach them — if not, we will run it.

### Not accepted yet: packs that carry tools

A pack can add tools that touch files, the network or other programs. Today a pack's permission table is *shown* to the user
but not yet *enforced* at run time. Until what a pack did not declare is actually blocked, we do not take outside packs that
carry tools. This is a "not yet", not a "no" — the conformance check and enforcement come first.

### Not accepted

- Anything that skips the approval card (sending mail, publishing, paying and deleting are pressed by a person).
- Anything that gets around logins, CAPTCHAs or bot checks.
- Anything that sends usage records outside. Sonjari listens on `127.0.0.1` only.
- Anything that guesses a request's difficulty up front to pick a model. Try the cheap one first, check the evidence, and
  move up when it fails.

### Answered in advance

- **Linux and macOS**: Windows only for now. A port is a large piece of work, so please open an issue to talk first. Two
  people cannot look after three operating systems.
- **AMD and Intel graphics**: we have no card to measure on. That is why door 1 (measure it on your card) exists.
- **"Add my model to the list"**: send it together with a result file from door 1 and we will add it.

## Security

Please do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## AI-assisted contributions

Much of Sonjari is written with an AI coding collaborator, and you are welcome to do the same. Two rules: say so in the pull
request, and run it yourself before you send it — you are the one vouching for it. AI never gives the final approval on a
change here; a maintainer does.

## License

By contributing you agree that your contribution is licensed under the Apache License 2.0, the same as the project.
