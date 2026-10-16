# 시험지 · Exam sheet (자동 생성 · generated)

> 「얼마나 잘했나」를 우리 말이 아니라 기록으로. 진 판도 지우지 않는다.
> How well it did — from the records, not our words. Runs that lost stay in.

가격 조사 꾸러미(가게 셋 × 물건 셋 = 한 판 9줄 · 페이지와 칸이 모두 맞아야 한 줄)의 결과를 카드 · 모델 · 창 · 조건마다 옮겼다.
손으로 쓰지 않았다 — `scripts/exam_sheet.py` 가 결과 파일의 `price_summary` 에서 뽑았다. 판이 셋 미만이면 「판이 적다」.

*One fixed price-research kit (3 Korean shops × 3 products = 9 rows per round; a row counts only when every cell matches
the page). Copied from each result file's `price_summary` by `scripts/exam_sheet.py` — not written by hand. Fewer than three
rounds is marked 「판이 적다」 (few rounds). Cause labels are explained at the bottom.*

**회귀 시험 · Regression suite**: 2026-10-16 · 7,358 passed · 0 failed · 3 skipped · 2 xfailed

| 카드 | 모델 | 창 | 조건 | 카드에 올라간 몫 | 판별(9줄 만점) | 가운데 값 | 과제 시간(가운데) | 진 까닭(많은 순) | 판(빌드) | 결과 파일 |
|---|---|---|---|---|---|---|---|---|---|---|
| RTX 3050 6GB Laptop GPU | `sonjari-text-qwen3.5-4b-ud-q3_k_xl` | 48K | 4b q3 text 48k | 100% | 0, 3, 2, 1, 0, 1, 3 | 1 | 351초 | 안 감 18 · 읽고 잃음 13 · 표 없이 끝남 10 | 23f6ec94 | [`laptop_6gb_rtx3050/kit__4b_q3_text_48k__measure_20261014-0209.json`](measurements/2026-10-14/laptop_6gb_rtx3050/kit__4b_q3_text_48k__measure_20261014-0209.json) |
| RTX 3090 | `Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp` | 128K | leak fixed2 1014 | 100% | 9 (판이 적다) | 9 | 336초 | - | d2f84111 | [`desktop_24gb_rtx3090/kit__leak_fixed2_1014__measure_20261014-1348.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__leak_fixed2_1014__measure_20261014-1348.json) |
| RTX 3090 | `Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp` | 128K | leak fixed 1014 | 100% | 9 (판이 적다) | 9 | 351초 | - | 6477cec7 | [`desktop_24gb_rtx3090/kit__leak_fixed_1014__measure_20261014-1316.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__leak_fixed_1014__measure_20261014-1316.json) |
| RTX 3090 | `Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp` | 128K | leak probe 1014 | 100% | 8 (판이 적다) | 8 | 421초 | 잘못 읽음 1 | 297d7064 | [`desktop_24gb_rtx3090/kit__leak_probe_1014__measure_20261014-1257.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__leak_probe_1014__measure_20261014-1257.json) |
| RTX 3090 | `qwen3.5:4b` | 32K | 4b 32k links on | 100% | 4, 1, 3, 4, 2, 4, 1 | 3 | 135초 | 안 감 16 · 읽고 잃음 15 · 목록에서 못 엶 6 | 23f6ec94 | [`desktop_24gb_rtx3090/kit__night_1013__4b_32k_links_on__measure_20261014-0300.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__night_1013__4b_32k_links_on__measure_20261014-0300.json) |
| RTX 3090 | `qwen3.5:9b` | 32K | 9b 32k links off | 100% | 1, 2, 6, 6, 3, 2, 3 | 3 | 286초 | 읽고 잃음 18 · 표 없이 끝남 15 · 목록에서 못 엶 3 | 23f6ec94 | [`desktop_24gb_rtx3090/…(7개 파일)`](measurements/2026-10-14/desktop_24gb_rtx3090/) |
| RTX 3090 | `qwen3.5:9b` | 32K | 9b 32k links on | 100% | 1, 5, 3, 3, 0, 3, 4 | 3 | 296초 | 읽고 잃음 20 · 표 없이 끝남 14 · 목록에서 못 엶 5 | 23f6ec94 | [`desktop_24gb_rtx3090/…(7개 파일)`](measurements/2026-10-14/desktop_24gb_rtx3090/) |
| RTX 3090 | `qwen3.5:9b` | 48K | 9b 48k links on | 100% | 6, 4, 2, 3, 0, 2, 2 | 2 | 356초 | 읽고 잃음 25 · 잘못 읽음 7 · 안 감 6 | 23f6ec94 | [`desktop_24gb_rtx3090/kit__night_1013__9b_48k_links_on__measure_20261014-0205.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__night_1013__9b_48k_links_on__measure_20261014-0205.json) |
| RTX 3090 | `sonjari-probe-qwen3.5-9b-nopenalty` | 48K | 9b official nopenalty 48k | 100% | 2, 2, 3, 4, 3, 4, 5 | 3 | 391초 | 읽고 잃음 18 · 표 없이 끝남 8 · 안 감 4 | f49b157d | [`desktop_24gb_rtx3090/kit__night_1014__9b_official_nopenalty_48k__measure_20261014-0522.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__night_1014__9b_official_nopenalty_48k__measure_20261014-0522.json) |
| RTX 3090 | `sonjari-text-unsloth-qwen3.5-9b-gguf-q3_k_m` | 48K | 9b unsloth q3 text 48k | 100% | 5, 4, 6, 4, 6, 4, 8 | 5 | 206초 | 읽고 잃음 12 · 잘못 읽음 11 · 목록에서 못 엶 3 | f49b157d | [`desktop_24gb_rtx3090/kit__night_1014__9b_unsloth_q3_text_48k__measure_20261014-0642.json`](measurements/2026-10-14/desktop_24gb_rtx3090/kit__night_1014__9b_unsloth_q3_text_48k__measure_20261014-0642.json) |
| RTX 5050 Laptop GPU | `qwen3.5:4b` | 76K | - | 100% | 3, 3, 4, 4, 3, 3, 4 | 3 | 278초 | 목록에서 못 엶 15 · 안 감 7 · 읽고 잃음 7 | 23f6ec94 | [`laptop_8gb_rtx5050/kit__measure_20261013-2210.json`](measurements/2026-10-14/laptop_8gb_rtx5050/kit__measure_20261013-2210.json) |
| RTX 5050 Laptop GPU | `sonjari-text-qwen3.5-9b-q3` | 48K | leak check2 9b | 100% | 7, 5, 8 | 7 | 487초 | 잘못 읽음 3 · 표 없이 끝남 2 · 가려다 막힘 1 | 3c363852 | [`laptop_8gb_rtx5050/kit__leak_check2_9b__measure_20261014-1820.json`](measurements/2026-10-14/laptop_8gb_rtx5050/kit__leak_check2_9b__measure_20261014-1820.json) |
| RTX 5050 Laptop GPU | `sonjari-text-unsloth-qwen3.5-9b-gguf-q3_k_m` | 48K | 9b q3 text 48k | 100% | 7, 8, 4, 5, 5, 4, 4 | 5 | 447초 | 잘못 읽음 11 · 읽고 잃음 8 · 가려다 막힘 3 | 23f6ec94 | [`laptop_8gb_rtx5050/kit__9b_q3_text_48k__measure_20261014-0338.json`](measurements/2026-10-14/laptop_8gb_rtx5050/kit__9b_q3_text_48k__measure_20261014-0338.json) |
| RTX 5050 Laptop GPU | `sonjari-text-unsloth-qwen3.5-9b-gguf-q3_k_m` | 64K | 9b q3 text 64k spill | 88% | 6, 5, 7, 3, 2, 5, 6 | 5 | 520초 | 잘못 읽음 11 · 목록에서 못 엶 8 · 안 감 6 | 23f6ec94 | [`laptop_8gb_rtx5050/kit__9b_q3_text_64k_spill__measure_20261014-0712.json`](measurements/2026-10-14/laptop_8gb_rtx5050/kit__9b_q3_text_64k_spill__measure_20261014-0712.json) |

까닭 낱말: 온전 = 맞음 · 안 감 / 목록에서 못 엶 / 가려다 막힘 = 상품 페이지까지 못 감 · 열고 안 읽음 · 읽고 잃음 = 읽고도 표에 못 옮김 · 잘못 읽음 · 표 없이 끝남 · 주소만 틀림.

*Causes: 안 감 / 목록에서 못 엶 / 가려다 막힘 = never reached the product page · 열고 안 읽음 = opened but didn't read · 읽고 잃음 = read it, then lost it from the window · 잘못 읽음 = misread · 표 없이 끝남 = ended without writing the sheet · 주소만 틀림 = only the URL was wrong.*
