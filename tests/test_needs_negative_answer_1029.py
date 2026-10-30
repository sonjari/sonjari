"""「돌려받을 항목(needs)」에 손자리가 **「No」로 답했는데 「채움」으로 세지 않는다** (2026-10-29).

사고: 판 e7bae54b(10-29 광고 촬영) — 바깥 AI 가 needs 에 「reached Confirm and pay」를 넣었고, 손자리 답은
  「- **reached Confirm and pay:** No — I did not click Reserve, so the Confirm and pay page was not reached.」
였다. 검사는 「이름 옆에 값이 있다」만 봐서 met=True 로 셌고, 영수증은 「필요한 것 1/1」로 나갔다. 결제 화면에 못 갔는데
바깥 AI 는 「다 채웠다」를 받았다.

정한 규칙(대표 10-29 「오케이」): 이름 붙은 자리의 값이 **부정으로 시작하면**(No · Not · 아니요 · 못 …) 「채움」이 아니라
「확인 못 함」(met=None)으로 두고, 손자리가 쓴 그 말을 `negative` 칸에 그대로 붙인다.
- 「없다」(False)로 단정하지 않는다 — 「로그인 필요 여부: No」처럼 No 가 정답인 항목도 있다(10-19 「못 찾은 것을 없다로 단정하지 않는다」).
- 값 **가운데**의 부정(「$348.73 (…, no extra fees)」)이나 No 로 시작하는 다른 낱말(「Notes …」 · 「November …」)은 건드리지 않는다.
- 빈 값(「없음」 · 「-」)은 지금처럼 False.
표본은 판 e7bae54b 답 한 줄을 그대로 쓰고, 나머지는 지어낸 글이다.
"""

from __future__ import annotations

from alture_jarvis.outbound import check_needs, receipt

E7BAE54B = (
    "I opened the listing and checked the price.\n\n"
    "- **listing name:** Felicia Resort's apartment\n"
    "- **reached Confirm and pay:** No — I did not click Reserve, so the Confirm and pay page was not reached. The tab is left open.\n"
)


def _one(needs: list[str], answer: str) -> dict:
    out = check_needs(needs, answer)
    assert len(out) == len(needs)
    return {item["label"]: item for item in out}


def test_real_run_e7bae54b_no_is_not_met():
    got = _one(["listing name", "reached Confirm and pay"], E7BAE54B)
    assert got["listing name"]["met"] is True
    item = got["reached Confirm and pay"]
    assert item["met"] is None, "부정으로 시작한 답은 「채움」이 아니라 「확인 못 함」"
    assert str(item.get("negative") or "").startswith("No"), "손자리가 쓴 말을 그대로 붙인다"
    assert "Reserve" in item["negative"]


def test_receipt_does_not_say_all_filled():
    needs = check_needs(["listing name", "reached Confirm and pay"], E7BAE54B)
    line = receipt(needs, [])["line"]
    assert "2/2" not in line
    assert receipt(needs, [])["needs_met"] == 1


def test_korean_negative_line():
    answer = "- 결제 화면 도착: 아니요, 예약 단추를 누르지 않았습니다\n- 숙소 이름: 펠리시아 리조트\n"
    got = _one(["결제 화면 도착", "숙소 이름"], answer)
    assert got["결제 화면 도착"]["met"] is None
    assert got["결제 화면 도착"]["negative"].startswith("아니요")
    assert got["숙소 이름"]["met"] is True


def test_korean_could_not():
    answer = "- 로그인 확인: 못 했습니다(로그인 화면이 떠서 사람에게 넘김)\n"
    got = _one(["로그인 확인"], answer)
    assert got["로그인 확인"]["met"] is None
    assert "못" in got["로그인 확인"]["negative"]


def test_table_cell_negative():
    answer = "| 항목 | 값 |\n|---|---|\n| reached Confirm and pay | No |\n| total price | $348.73 |\n"
    got = _one(["reached Confirm and pay", "total price"], answer)
    assert got["reached Confirm and pay"]["met"] is None
    assert got["total price"]["met"] is True


def test_column_all_negative():
    answer = "| site | logged in |\n|---|---|\n| airbnb | No |\n| maps | No |\n"
    got = _one(["logged in"], answer)
    assert got["logged in"]["met"] is None


def test_column_mixed_counts_as_filled():
    # 한 칸이라도 긍정 값이면 지금처럼 채움
    answer = "| site | logged in |\n|---|---|\n| airbnb | No |\n| github | yes, as garam |\n"
    got = _one(["logged in"], answer)
    assert got["logged in"]["met"] is True


def test_negative_in_the_middle_is_still_filled():
    answer = "- **Total price:** $348.73 (2 nights × $174.37, no extra fees)\n"
    got = _one(["Total price"], answer)
    assert got["Total price"]["met"] is True
    assert not got["Total price"].get("negative")


def test_words_starting_with_no_are_not_negative():
    answer = "- Notes: the host replies fast\n- dates: November 14 – 16\n"
    got = _one(["Notes", "dates"], answer)
    assert got["Notes"]["met"] is True
    assert got["dates"]["met"] is True


def test_blank_stays_false():
    got = _one(["pick"], "- pick: 없음\n")
    assert got["pick"]["met"] is False


def test_positive_unchanged():
    got = _one(["pick"], "- pick: Felicia Resort's apartment (4.89 · 232 reviews)\n")
    assert got["pick"]["met"] is True
    assert not got["pick"].get("negative")
