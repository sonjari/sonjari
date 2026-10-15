"""결과 목록 판정기를 **여덟 곳에서 동시에** 잰다 — 한 곳만 보고 고치지 못하게.

## 왜 이 시험이 생겼나 (2026-08-12)

하루에 되돌린 것이 셋이다.

    묶음 상한(group_cap)          당근마켓 12건 → 0건
    자기 페이지를 앞 두 칸으로 판정   당근마켓 매물 60개 증발
    카드 대표 링크                 사람인은 깨끗해졌는데(80→38) 교보·다나와 1번이
                                  "바로펀딩"·"Bravotec 브랜드로그"로 바뀜

셋 다 **한 곳만 보고 고쳐서** 딴 데가 깨진 것이다. 인수인계서는 "새 기준을 넣기 전에
세 사이트를 함께 재라"고 적었지만, 그것은 사람의 규율이라 지켜지지 않는다 — 살아있는
사이트 여덟 곳을 치는 데 십수 분이 들고, 그 사이 사이트가 바뀌면 어제와 오늘을
비교할 수조차 없다.

## 기존 시험과 무엇이 다른가

`test_browser_result_list.py` 는 두 가지를 한다: ① 손으로 쓴 가짜 행(`{"name": "항목 1"}`)
으로 고리를 확인하고 ② JS 원문에 특정 문자열이 있는지 본다. 둘 다 필요하지만
**교보·다나와가 깨진 것은 원리적으로 못 잡는다** — 그 사이트가 깨진 이유가
"그 카드에선 제일 긴 글자가 제목이 아니었다"인데, 그런 성질은 합성 표본에 없다.

이 시험은 **진짜 화면**을 얼려 놓고 **진짜 판정기**를 태운다.

## 얼린 표본은 낡지 않는다

바깥으로 나가는 요청이 하나도 없다(`result_list_bench.detect_all` 참고). 사이트가 개편돼도
이 시험의 답은 안 바뀐다. 그래서 이것은 "지금 사이트가 어떤가"가 아니라
**"우리 판정기가 그때 그 화면을 여전히 제대로 읽는가"** 를 묻는다. 사이트가 바뀌었는지는
`scripts/capture_result_list_fixtures.py` 로 다시 떠서 확인할 일이지, 시험이 할 일이 아니다.

## 빨간불로 들고 가는 자리

**쿠팡은 지금 못 푼다**(`known_failing`, xfail). 상품 목록 대신 카테고리 메뉴를 골라
1번이 "전체"로 나온다. 이 벤치가 생긴 첫날에 잡아낸 고장이다.

빼지 않고 빨간불로 들고 가는 이유는, 빼는 순간 "일곱 곳 다 통과"가 여덟 번째를 덮기
때문이다. 고쳐지면 `xfail(strict=True)` 가 xpass 로 알려 준다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import result_list_bench as bench_module

playwright = pytest.importorskip("playwright", reason="얼린 표본을 재생하려면 playwright 가 필요하다")

FIXTURES = bench_module.names()


@pytest.fixture(scope="module")
def bench():
    """자식 프로세스에서 **한 번에 전부** 재고 결과만 받는다.

    같은 프로세스에서 재면 전체 시험을 돌릴 때만 깨진다(앞선 시험들이 이벤트 루프를
    돌려 놓아 sync API 가 안 잡힌다) — 그리고 그 결과는 조용한 건너뜀 16건이다.
    이유는 `result_list_bench` 문서에.
    """
    if not FIXTURES:
        pytest.skip("얼려 둔 표본이 없다 — scripts/capture_result_list_fixtures.py 로 뜬다")
    # ★ 자식에게 **UTF-8 로 말하라고 시킨다** (2026-08-24).
    #
    #   여기서 `encoding="utf-8"` 로 읽는데, 윈도우의 파이썬 자식은 아무 말이 없으면
    #   cp949 로 쓴다. 그러면 부모의 읽기 스레드가 `UnicodeDecodeError` 로 죽고,
    #   `done.stdout` 이 **빈 문자열**로 온다 → 바로 아래에서 "재생 프로세스가 못
    #   떴다"로 건너뛴다. 실측: 이 한 줄이 없어서 벤치 16건이 통째로 건너뛰고 있었다
    #   (같은 자리에서 두 번째다 — 앞의 것은 PYTHONPATH 였다).
    #
    #   조용한 건너뜀이라 초록불이 났고, 그건 아무것도 안 하고 성공하는 모양이다.
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sys.executable, str(bench_module.__file__), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # 그래도 한 바이트가 어긋나면, 죽지 말고 글자만 버린다
        env=child_env,
        timeout=600,
    )
    if done.returncode != 0 and not done.stdout.strip():
        # ★ 건너뛰지 않는다. 크롬이 없으면 자식이 `{"error": ...}` 를 stdout 으로
        #   주고 rc 3 으로 끝난다(바로 아래에서 건너뛴다). **stdout 조차 없다**는 것은
        #   환경이 아니라 이 하네스가 깨졌다는 뜻이고, 그때 건너뛰면 아무도 모른다.
        raise AssertionError(
            "재생 프로세스가 아무것도 못 내놨다 — 벤치 하네스가 깨졌다. "
            f"rc={done.returncode} stderr={(done.stderr or '')[-500:]}"
        )
    payload = json.loads(done.stdout.strip().splitlines()[-1])
    if "error" in payload:
        pytest.skip(f"크롬을 띄울 수 없다: {payload['error'][:160]}")
    return payload


def test_there_are_fixtures_at_all() -> None:
    """표본이 통째로 사라지면 위의 시험들이 전부 '건너뜀'이 되어 초록불이 된다.

    2026-07-28 CI 사고와 같은 모양이다 — 아무것도 안 하고 성공하는 것이 제일 나쁘다.
    """
    # 공개판에는 남의 사이트 화면을 얼려 싣지 않는다(우리 저작물이 아니다) — 기대값(.json)만 간다. 내보내기 스크립트가 남긴 표시가
    # 있을 때만 건너뛴다: 표시 없는 곳(우리 저장소)에서 표본이 사라지면 그대로 실패한다.
    if not FIXTURES and (Path(__file__).resolve().parents[1] / ".sonjari-public-export").is_file():
        pytest.skip("공개판 — 얼린 화면은 싣지 않는다. scripts/capture_result_list_fixtures.py 로 직접 떠서 잰다")
    assert len(FIXTURES) >= 7, f"표본이 모자란다: {FIXTURES}"


@pytest.mark.parametrize("name", FIXTURES)
def test_the_first_result_is_a_real_item(name: str, bench, request) -> None:
    """1번이 엉뚱해지는 것은 답을 통째로 틀리게 만든다 — 여기가 이 벤치의 핵심이다."""
    fixture = bench_module.load(name)
    if fixture.known_failing:
        # 못 고친 자리는 **빼지 않고** 이렇게 들고 간다. 고쳐지면 xpass 로 알려 준다.
        request.node.add_marker(pytest.mark.xfail(strict=True, reason=fixture.meta["note"][:120]))
    assert fixture.expect_top1, (
        f"{name}: 기대 1번이 비어 있다. 얼린 화면을 보고 .json 의 expect_top1_contains 를 채워라"
    )

    rows = bench[name]

    assert rows, f"{name}: 목록을 통째로 못 찾았다 (판정기가 None 을 돌려줬다)"
    top = rows[0]["name"]
    assert fixture.expect_top1 in top, (
        f"{name}: 1번이 바뀌었다\n"
        f"  기대: …{fixture.expect_top1}…\n"
        f"  실제: {top[:120]!r}\n"
        f"  주소: {rows[0]['href'][:100]}\n"
        f"  참고: {fixture.meta.get('note') or '-'}"
    )


@pytest.mark.parametrize("name", FIXTURES)
def test_the_list_does_not_collapse(name: str, bench) -> None:
    """1번만 맞고 나머지가 사라지는 고장이 실제로 있었다(당근 12건 → 0건)."""
    fixture = bench_module.load(name)
    if fixture.known_failing:
        # 엉뚱한 묶음을 골랐으면 그 묶음의 **개수는 아무것도 말해 주지 않는다.**
        # 쿠팡은 카테고리 메뉴 80개로 이 시험을 통과해 버린다 — 초록불이 거짓이 된다.
        pytest.skip("1번부터 틀린 곳이다 — 개수를 세는 것이 의미가 없다")
    rows = bench[name]

    assert len(rows) >= fixture.expect_min_items, (
        f"{name}: 항목이 {len(rows)}건뿐이다 (최소 {fixture.expect_min_items}, "
        f"얼릴 때 {fixture.meta.get('observed_items')}건)\n"
        f"  참고: {fixture.meta.get('note') or '-'}"
    )


def test_the_fixtures_are_hermetic() -> None:
    """표본이 바깥 세상을 부르는 순간 이것은 시험이 아니라 관측이 된다.

    스크립트는 얼릴 때 지웠고(`scripts_stripped`), 스타일시트는 본문에 녹여 넣었다
    (`stylesheets_missing == 0`). 못 받은 스타일시트가 있으면 `getComputedStyle` 이
    살아있는 화면과 다른 값을 내고, 그러면 이 벤치의 답 전체를 믿을 수 없다.
    """
    for name in FIXTURES:
        meta = bench_module.load(name).meta
        assert meta["stylesheets_missing"] == 0, f"{name}: 못 받은 스타일시트가 있다"
        assert meta["stylesheets_inlined"] > 0, f"{name}: 스타일시트를 하나도 못 녹였다"
        assert meta["scripts_stripped"] > 0, f"{name}: 스크립트가 남아 있다"
