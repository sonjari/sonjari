# Head-to-head measurements, audited — collected 2026-10-19

Every comparison we ran between Sonjari and another tool, checked again against the raw records.
What still holds is here with its conditions. What did not hold is listed at the end with the reason.
[한국어](README.ko.md)

## What holds

| Measurement | Result | How sure |
|---|---|---|
| Claude Code on Korean shopping sites, with and without Sonjari (10-15) | Claude's cost was lower in **9 of 9** paired runs with Sonjari ($1.71 vs $3.69 alone). Correct rows did not drop (15 alone, 17 file-graded / 23 with hand-graded rows) | Cost: sure (sign test p ≈ 0.004). Correctness: no clear difference |
| One research job handed from Claude Code to Sonjari (10-19) | 218,131 characters read on this PC, at least 48,473 tokens that never entered Claude's window | Counted, a floor |
| Sonjari vs Hermes Agent, same model and GPU (09-28~29) | Code task 3/3 vs 3/3, **Hermes about twice as fast**. Meeting notes to Word 2/3 vs 2/3. Bookstore to Excel 5/6 vs 1/3, with five conditions that favour Sonjari | Small n, one PC |
| Do Claude Code and Codex call Sonjari when they should (09-16) | Claude Code 3/3, no false calls. Codex chose to call 3/3 but its headless mode refused every call, so 0 ran | n = 3 per class |
| Kyobo "990p" (09-06) | Two models read reward points as page counts on a listing page | Reproducible with two commands |

## 1. Claude Code with and without Sonjari — `price_claude_code_1015.json`

**Task:** find one product on Danawa, 11st and Gmarket and answer with a table, one row per shop (shop, product, price, shipping, URL).
Products: Logitech MX Master 3S, Samsung Galaxy Buds3 Pro, Nintendo Switch 2. 3 rounds × 3 products × 3 shops = **27 rows per arm**.

**Setup:** claude-sonnet-5 in every arm (Claude Code `-p`, caching on). Sonjari ran Swift-1.5-Qwen3.8-27B (IQ3, window 131072) on one RTX 3090.
Arm order rotated each round. The working folder had no CLAUDE.md or skills above it.

**A row counts** only if that shop's row exists, its URL is that shop's product page, and the value is in the text that arm actually read.
It checks copying from what was read, not whether the price was live. Cost is Claude's API cost only; the GPU is not priced.

| Arm | Correct rows (file / with hand-graded) | Claude cost | Per correct row (file / hand) | Median time |
|---|---|---|---|---|
| Claude Code + Sonjari's browser tools | 17 / 23 of 27 | $1.71 | $0.100 / $0.074 | 401 s |
| Claude Code hands the whole task to Sonjari | 15 / 18 of 27 | $1.34 | $0.090 / $0.075 | 391 s |
| Claude Code alone (WebFetch, WebSearch) | 15 of 27 | $3.69 | $0.246 | 96 s |
| Claude Code + Playwright MCP | 11 of 27 | $6.98 | $0.635 | 162 s |

**Hand-graded rows.** Three Sonjari cells (6 rows for browser tools, 3 for handoff) were scored by hand. That night the grader read only the
first column, missed a 판매가 (sale price) header and missed URLs without `https`. We fixed it and checked those rows against the page text,
but a backend restart then wiped that text, so they cannot be regraded from files. Both columns are published; the file column is what the files support.

**Paired sign tests** (rows paired by round, product and shop; two-sided; six comparisons, no correction):

| Pair | File-graded | With hand-graded |
|---|---|---|
| Browser tools vs Playwright | 10 vs 4, p = 0.18 | 13 vs 1, p = 0.0018 |
| Browser tools vs Claude alone | 7 vs 5, p = 0.77 | 9 vs 1, p = 0.022 |
| Handoff vs Claude alone | 7 vs 7, p = 1.0 | 9 vs 6, p = 0.61 |

Cost, paired by run: with Sonjari, Claude's cost was lower than Claude alone in 9 of 9 runs, for both Sonjari arms.

**Earlier public posts** (r/LLMDevs 10-16, r/ClaudeCode 10-19) quoted 23/27 and p ≈ 0.002 without saying 6 rows were hand-graded. This record corrects that.

**Also in this run:** two handoff cells scored 0 were waiting for an approval card nobody was there to click (Claude asked Sonjari to save into a
folder Sonjari may not write to). The backend was restarted at 19:19 mid-run. One Playwright run hit `error_max_turns`; Gmarket blocked most
Playwright visits. One day, one PC, one card. The harness now saves the page text with each run.

## 2. One research job, counted — `reddit_research_receipt_1019.json`

Claude Code handed Sonjari a job over MCP: open top posts of the past month on r/ClaudeCode and r/LocalLLaMA and collect complaints into a spreadsheet.
Sonjari opened 16 post pages and 4 listing pages and read 218,131 characters. 218,131 ÷ 4.5 characters per token = **48,473 tokens at least**.
Claude got the answer and the sources. This is a floor: English text runs about 4 characters per token, and the re-sending a host would do at each step
if it read the pages itself is not counted. r/AI_Agents was in the request, but no post page from it was opened.

## 3. Sonjari vs Hermes Agent — `hermes_desktop_0928.json`

Same PC (RTX 3090), same Ollama runner and model (`qwen3.6:35b-a3b`) for both, same prompt text, a fresh session per run. Graded by hand from the
run records, except the code task (pytest passes and the test file is unchanged).

| Task | Window | Sonjari | Hermes |
|---|---|---|---|
| Meeting notes to a Word file with a decisions table | 32K | 2/3 · 45, 51, 64 s | 2/3 · 103, 127, 138 s |
| Code task with a pytest suite (two bugs, one symptom) | 64K | 3/3 · 78, 95, 62 s | 3/3 · **24, 46, 40 s** |
| Kyobo: 3 books, title / price / points into Excel | 64K | 5/6, no false "done" without a warning | 1/3, one false "done" |

**Read the bookstore row with these conditions.** Sonjari was tuned on this exact task over 32 earlier runs; Hermes saw it fresh. Sonjari had a
Kyobo-specific value recipe. We edited Hermes' config (context size, model alias) so both used the same 64K runner. Our watchdog and Sonjari's
start-up check took Hermes' runner more than once; those runs are marked invalid. n is 6 vs 3. Hermes runs H1–H3 are invalid because we had installed
Hermes inside the Claude desktop app's MSIX virtualization and its Chrome could not start; H4–H7 had a context mismatch.

In run 1 of the meeting-notes task Sonjari's document tool dropped the table and still reported the file as verified. That bug was fixed afterwards.

## 4. Do hosts call Sonjari? — `adoption_0916.json`

Three tasks that need a real browser and a file, three that do not. Claude Code called Sonjari 3/3 when it should, 0 false calls, and all three ran
on Sonjari's side. Codex chose to call 3/3, but headless `codex exec` refused every MCP call for approval, so none ran. Codex said so and did not
invent results.

## 5. Kyobo "990p" — `kyobo_990p_note.md`

Browser Use with two different models gave page counts of 990p, 990p and 2,250p. They were reward points on the search listing, which has no
page-count field. A grounding check ("is this number in what the agent read?") passes them; the missing check is whether it is the right field.

## Excluded, and why

| Measurement | Why it is not here |
|---|---|
| Claude Code cost experiment, 09-23 (incl. "simple tasks were cheaper with Claude alone", "MS Store 0/6 vs 6/6") | The working folder sat under the user profile, so the user's own instructions and skills loaded into every arm. No transcripts kept to check. Grader fixed later |
| Same comparison, 10-15 early morning (two-hands, first price run, verify) | Same leak; Claude-alone runs mentioned Sonjari. Replaced by section 1 |
| "48× cheaper" token comparison, 09-07 | No caching in arm A; with caching it was 7.9×, and the arm B answers invented values in 2 of 3. Replaced by section 1 |
| "Hermes did not answer for 35 minutes", 10-01 | Sonjari's model still held the cloud GPU |
| Claude Code `--resume` vs Sonjari takeover, 09-23 | Both arms contaminated, small n, the feature changed after |
| Sonjari vs GPT on a job board, 10-02 | No raw record, notes only |
| Sonnet + Browser Use vs Sonjari, 09-18 | No raw record |
| Browser Use showdown win/loss table, 09-06 | One run per task; only the 990p finding is kept |
| Online-Mind2Web, 10-03 | Our own grader and a Korean IP, not the leaderboard's conditions; task text cannot be redistributed. The README keeps one line |
| Tester impressions | Friends and family, n = 1 |

Raw transcripts are not published: they hold local paths, session ids and third-party page text. The files here keep the numbers and verdicts.
