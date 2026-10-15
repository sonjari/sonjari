"""요약 비율이 답 자신의 표와 맞는가 · 읽은 자료에 없는 비율 (2026-10-01 밤 운영 판 e84ae679).

손자리가 Steam 표를 정확히 옮겨 놓고 요약에 「VRAM 8GB 이하가 약 41.3%」라고 썼다. 41.3 은 12+16+20GB 칸의 합
(12.99+26.92+1.37)에 엉뚱한 이름표를 붙인 값이었다 — 숫자는 자료에 있고 이름표가 틀려 「근거 없는 숫자」 검사로는
원리상 못 잡는다. 넣기 전에 운영 답 2,474개로 쟀다: 표 합계 어긋남은 이 판 하나(오탐 0).
"""

from __future__ import annotations

from alture_jarvis.number_checks import percent_warning, table_sum_mismatches, ungrounded_percents

STEAM = """| VRAM | 비율 |
|---|---|
| **4 GB** | **5.69%** |
| **6 GB** | **5.30%** |
| **8 GB** | **25.74%** |
| 10 GB | 1.96% |
| 12 GB | 12.99% |
| 16 GB | 26.92% |
| 20 GB | 1.37% |
| 24 GB | 5.41% |
| 32 GB | 1.34% |

**요약:** Steam 사용자 중 VRAM 8GB 이하가 약 **41.3%**, 12~16GB가 약 **39.9%**, 24GB 이상이 약 **5.4%**를 차지한다."""

SEEN = {"5.69", "5.3", "25.74", "1.96", "12.99", "26.92", "1.37", "5.41", "1.34"}


def test_a_summary_that_disagrees_with_its_own_table_is_named() -> None:
    found = {item["said"]: item for item in table_sum_mismatches(STEAM)}
    assert set(found) == {"8GB 이하 41.3%", "24GB 이상 5.4%"}
    assert found["8GB 이하 41.3%"]["table_sum"] == 36.73
    assert found["8GB 이하 41.3%"]["rows"] == ["4GB", "6GB", "8GB"]


def test_a_correct_range_sum_is_quiet() -> None:
    """12~16GB 39.9% 는 12.99+26.92 = 39.91 — 맞게 더한 값은 조용하다."""
    assert not any("12~16" in str(item["said"]) for item in table_sum_mismatches(STEAM))


def test_the_warning_shows_which_rows_were_added() -> None:
    note = percent_warning(STEAM, SEEN)
    assert "요약 숫자가 답의 표와 맞지 않습니다" in note
    assert "4GB + 6GB + 8GB" in note and "36.73%" in note
    assert "읽은 자료에 없는 비율" not in note  # 41.3·5.4 는 위에서 이미 말했다 — 두 번 울리지 않는다


def test_made_up_percent_is_named_but_arithmetic_is_not() -> None:
    answer = "3개 중 2개(67%)가 파이썬이다. 2582줄 중 약 700줄(약 27%)을 읽었다. AIME 2026 에서 92.7% 를 기록했다."
    assert ungrounded_percents(answer, set()) == ["92.7"]


def test_rounding_a_read_value_is_not_made_up() -> None:
    assert ungrounded_percents("NVIDIA 72.9% · AMD 18.7%", {"72.88", "18.68"}) == []


def test_english_answers_get_an_english_warning() -> None:
    note = percent_warning(STEAM, SEEN, english=True)
    assert "does not match its own table" in note
