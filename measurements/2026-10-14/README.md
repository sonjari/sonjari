# Sonjari measurement pack — 2026-10-13 to 10-14

Raw-ish results from measuring a local Windows agent (Sonjari) on three consumer PCs, including the runs that lost.
Published so others can check our numbers instead of trusting our summaries.

**Runtime for everything here: Ollama (llama.cpp) on Windows 11, driven by Sonjari.** Not vLLM or another server runtime —
the hidden costs differ, so please don't mix these with server-runtime numbers.

## What was measured

One fixed price-research kit. Each task asks for one product across three Korean shops (Danawa, 11st, Gmarket) and an
Excel file with shop, product name, price, shipping and the page URL — three rows per task. A **round** is three tasks
(a mouse, earbuds, a game console), so **nine rows per round**. A row counts as complete only when every cell matches what
the page showed. Each folder ran the same kit several rounds back to back.

## Folders

| Folder | Card | RAM | Model / quant / window | Notes |
|---|---|---|---|---|
| `desktop_24gb_rtx3090` | RTX 3090 24GB (display on a separate RTX 3060) | 64GB | 9B (official tag, with vision) 32K and 48K · 9B Q3_K_M text-only 48K · 4B 32K · 27B IQ3_S 128K (`leak_*`) | `links_on`/`links_off`: an A/B of one harness change, 7 rounds each, interleaved. `leak_*` are short runs used to find a memory leak. |
| `laptop_8gb_rtx5050` | RTX 5050 Laptop 8GB (an external monitor on the same card; it was off at night) | 16GB | 4B Q4 78K · 9B Q3_K_M text-only 48K (fully on GPU) · same at 64K (88% on GPU) | `leak_check.log` (build 1400, before the fix) and `leak_check2.log` + `kit__leak_check2_9b__*` (build 1615, after) are the memory comparison below. |
| `laptop_6gb_rtx3050` | RTX 3050 Laptop 6GB | 24GB | 4B UD-Q3_K_XL text-only 48K (fully on GPU) | Measured on the build before the leak fixes below; the runner crashed twice. `windows_events.txt` lists Windows' own memory and crash events. |

## Files

- `kit__*.json` — one per run. **Numbers and yes/no only, by design**: no page text, no URLs we read, no answers.
  - `price_summary.per_round` — complete rows per round (out of 9). `causes` — why the other rows failed.
  - `price[]` — one entry per task: `whole_rows` (0–3), `sec`, `steps`, `gen_tokens_per_sec`, `prefill_tokens_per_sec`,
    `largest_prompt_tokens`, `stop_reason`, the tool sequence with error codes (`tools`), and per-shop verdicts (`shops`, `causes`).
  - `pc` — card(s), memory on the card before and during the run, model tag, window, share of the model on the GPU, Sonjari build.
  - Cause labels are Korean: 온전 = complete · 못 찾음 / 목록에서 못 엶 / 안 감 / 가려다 막힘 = never reached the product page ·
    열고 안 읽음 = opened but didn't read · 읽고 잃음 = read it, then lost it from the window · 잘못 읽음 = misread ·
    표 없이 끝남 = ended without writing the sheet · 주소만 틀림 = only the URL was wrong.
- `runner_log_excerpt.txt` — only the Ollama / llama-server lines about loading and memory: layers offloaded, model / KV /
  compute buffer sizes, GPU memory available, prompt-cache size limit and saves, crashes, HTTP 500s.
  **Request lines and anything with message content were dropped.** User names in paths are masked as `<user>`.
- `leak_check*.log` — every 5 minutes during a run: the agent process's handle count and private memory, the browser
  automation ledger size, how often the browser connection was recycled, free RAM, and llama-server's private memory.
- `machine.txt` — card, RAM, Windows build, Ollama and Sonjari versions.

## What we took out

Request text, pages the agent read, answers, file paths with user names, PC names, tokens. We checked every file for user
names and paths before publishing.

## Caveats

- Two to three PCs, one task kit, about seven rounds per condition. Enough to see large differences, not small ones.
- The 8GB laptop's display was off during the night runs, so about 0.8 GB more was free on the card than in daytime use.
- `desktop_24gb_rtx3090` runs use a card larger than the condition they stand in for in some cases; the `pc` field says what
  was actually loaded.

## A memory leak we found while measuring

The overnight runs on the laptops grew the agent's own process (Python, not the model runner) until Windows ran out of
memory — the 8GB laptop reached 18GB private memory after 12 hours. Two causes, fixed on 2026-10-14:

1. Network response buffers kept per browser tab were never dropped when the tab closed, so each kept the old browser
   connection and everything it had touched alive.
2. The package shipped COM type definitions for Windows UI Automation generated on the build PC. Their last line checks
   that `UIAutomationCore.dll` has the same timestamp as on the build PC. On any other PC the 9,224-line module ran in
   full, failed on that last line, and left its classes behind — and a health check repeated this every few seconds.
   It also meant the Windows automation tools were silently unavailable everywhere except the build PC.

Same price kit, same model (9B Q3_K_M text-only, 48K), same 8GB laptop:

| | before (build 1400) | after (build 1615) |
|---|---|---|
| agent private memory | 3,280 → 5,434 MB in 101 min | 2,699 → 2,809 MB in 91 min (54 MB of it in the first 5 min) |
| ctypes `WinFunctionType` objects | grew to 1.3 million | 1,391, unchanged |

The "before" run was stopped by hand after 101 minutes, so it has no kit result file. The "after" run is 3 rounds:
7, 5 and 8 complete rows out of 9. That score is not compared with the other 9B runs here — the conditions differ.

## Short summary in Korean · 한국어 요약

손자리(윈도우 로컬 에이전트)를 PC 세 대에서 같은 가격 조사 과제로 잰 기록입니다. 진 결과도 그대로 넣었습니다. 결과 파일에는 숫자와
예/아니오만 들어 있고(읽은 글 · 주소 · 답은 없음), 실행기 기록은 모델 적재 · 메모리 · 꺼짐 줄만 남기고 사람 이름을 가렸습니다.
모든 기록은 Ollama(llama.cpp) · 윈도우 11 에서 잰 것입니다. 재는 도중 손자리 본체의 메모리가 새는 것을 찾아 고쳤고, 8GB 노트북에서 고치기 전과 후를 같은 과제로 견준 기록(101분 +2,154MB → 91분 +110MB)도 넣었습니다.

License: Apache-2.0 (same as this repository). If you use these numbers, a link back is appreciated.
