"""「모르는 앱」 측정(2026-10-18 새벽)에서 나온 고침 — 시스템 정보 · 설정 화면을 이름으로 열고, 그런 요청은 직접 보고 답하게 한다."""
from __future__ import annotations

import os

import pytest

from alture_jarvis.local_computer import launchable_app, settings_page
from alture_jarvis.plan import names_a_desktop_source


@pytest.mark.parametrize("name, page", [
    ("설정", "ms-settings:"),
    ("윈도우 설정", "ms-settings:"),
    ("시스템 → 정보", "ms-settings:about"),
    ("시스템 > 정보", "ms-settings:about"),
    ("about", "ms-settings:about"),
    ("ms-settings:about", "ms-settings:about"),
    ("디스플레이 설정", "ms-settings:display"),
])
def test_named_settings_pages_open_by_name(name: str, page: str) -> None:
    assert settings_page(name) == page


@pytest.mark.parametrize("name", ["ms-settings:windowsupdate-action", "ms-settings:privacy-webcam", "notepad", "", "시스템 정보"])
def test_other_settings_addresses_are_not_taken(name: str) -> None:
    # 모델 글의 아무 ms-settings 주소나 받지 않는다 — 정해 둔 화면만. 「시스템 정보」는 설정이 아니라 msinfo32 다.
    assert settings_page(name) is None


@pytest.mark.skipif(os.name != "nt", reason="윈도우 전용")
def test_system_information_is_launchable_by_name() -> None:
    for name in ("msinfo32", "시스템 정보", "msinfo32.exe"):
        found = launchable_app(name)
        assert found and found.lower().endswith("msinfo32.exe")
    assert launchable_app(r"D:\elsewhere\msinfo32.exe") is None


@pytest.mark.parametrize("prompt", [
    "윈도우의 「시스템 정보」 프로그램(msinfo32)을 열어서 BIOS 버전을 읽어 알려 줘.",
    "윈도우 설정의 「시스템 → 정보」 화면을 열어서 Windows 에디션을 읽어 알려 줘.",
    "장치 관리자를 열어서 그래픽 카드 이름 확인해 줘.",
])
def test_naming_a_desktop_screen_means_look_at_it(prompt: str) -> None:
    assert names_a_desktop_source(prompt)


@pytest.mark.parametrize("prompt", [
    "윈도우 11 에서 BIOS 버전 확인하는 방법 알려 줘.",
    "설정을 바꾸는 법을 설명해 줘.",
    "오늘 날씨 알려 줘.",
])
def test_how_to_questions_are_not_desktop_sources(prompt: str) -> None:
    assert not names_a_desktop_source(prompt)


def test_a_read_only_command_on_this_pc_counts_as_looking() -> None:
    # 「시스템 정보를 열어서 BIOS 버전을 읽어 줘」에 systeminfo 로 맞는 값을 읽은 판이 「0개 실제로 읽음 ❌」로 나갔다(2026-10-18).
    from alture_jarvis.plan import Requirement, _saw_en, check

    local = [Requirement("observe", "근거가 되는 대상 실제로 읽기", "local")]
    probed = [{"tool": "shell_probe", "ok": True, "arguments": {"command": "systeminfo"}}]
    [(_, ok, saw)] = check(local, sources=[], steps=probed)
    assert ok and saw == "이 PC 상태를 읽기 전용 명령으로 1번 읽음"
    assert _saw_en(saw) == "read this PC's state with read-only commands 1 time(s)"
    # 실패한 명령 · 웹을 보라는 판은 그대로다.
    assert not check(local, sources=[], steps=[{"tool": "shell_probe", "ok": False}])[0][1]
    web = [Requirement("observe", "근거가 되는 대상 실제로 읽기", "browser")]
    assert not check(web, sources=[], steps=probed)[0][1]


@pytest.mark.parametrize("prompt, screen", [
    ("윈도우의 「시스템 정보」 프로그램(msinfo32)을 열어서 BIOS 버전을 읽어 알려 줘.", "시스템 정보"),
    ("윈도우 설정의 「시스템 → 정보」 화면을 열어서 Windows 에디션을 읽어 알려 줘.", "시스템 → 정보"),
    ("윈도우 설정을 열어서 화면 밝기 봐 줘.", "설정"),
    ("설정 바꾸는 법 알려 줘.", None),
    ("메모장을 열어 줘.", None),
])
def test_screens_that_open_by_name_are_named_to_the_model(prompt: str, screen: str | None) -> None:
    # 모델이 「msinfo32 를 띄우는 도구가 없어」라고 쓰고 셸로만 읽어 설정 화면에만 있는 값을 빠뜨렸다(2026-10-18).
    from alture_jarvis.local_computer import launchable_app, settings_page
    from alture_jarvis.plan import named_screen_to_open

    assert named_screen_to_open(prompt) == screen
    if screen:  # 알려 준 이름은 실제로 여는 길이 받는 이름이어야 한다.
        assert settings_page(screen) or (os.name != "nt" or launchable_app(screen))


@pytest.mark.parametrize("prompt", [
    "윈도우 설정의 「시스템 → 정보」 화면을 열어서 Windows 에디션과 버전 번호를 읽어 알려 줘. 아무것도 바꾸지 마.",
    "윈도우의 「시스템 정보」 프로그램(msinfo32)을 열어서 BIOS 버전을 읽어 알려 줘.",
])
def test_opening_a_windows_screen_keeps_the_window_hands(prompt: str) -> None:
    # 웹 갈래로 가 창 도구가 빠졌다 — 모델이 「windows_open_path 도구가 지금 제 목록에 없다」고 답했다(2026-10-18).
    from alture_jarvis.plan import Requirement
    from alture_jarvis.tool_roster import _is_web_research_job

    observe = [Requirement("observe", "근거가 되는 대상 실제로 읽기", "local")]
    assert not _is_web_research_job(observe, prompt)
    assert _is_web_research_job(observe, "오늘 서울 날씨 알려 줘")


def test_a_place_name_is_not_learned_as_a_portal_site(tmp_path) -> None:
    # 「여수 아파트 매물 - 네이버 부동산」 같은 제목 네 장으로 「여수 → naver.com」을 배워 「여수에서 하기」가 섰다(2026-10-18 디스코드).
    from alture_jarvis.site_atlas import SiteAtlas

    atlas = SiteAtlas(tmp_path / "atlas.json")
    for n in range(3):
        atlas.learn("여수", f"https://new.land.naver.com/complexes?ms={n}", "여수 아파트 매물 - 네이버 부동산")
        atlas.learn("번개장터", f"https://m.bunjang.co.kr/products/{n}", "번개장터 | 중고거래")
    assert atlas.host_for("여수") == ""
    assert atlas.host_for("번개장터") == "bunjang.co.kr"  # 사용자 글 주소가 아닌 가게는 그대로 배운다
