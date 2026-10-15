"""MS 스토어 과제(2026-09-29 새벽, 레시피 없는 섀도 DOM 사이트)에서 나온 **우리 버그 셋**.

M1·M2·M3 세 판 모두 엑셀 3행의 이름·가격·평점이 스토어 정답(상세 페이지 구조화 데이터)과 **전부 일치**했는데, 세 판 모두 답 끝에
우리 검사기가 틀린 경고를 붙였다 — 맞는 답을 「지어냈을 수 있다」고 했다(대표가 M2 를 보고 「실패다」라고 읽었다).

1. 「이번에 열지 않은 주소」: 줄 `…/detail/9n92mc09db30` ↔ 연 주소 `…/detail/9n92mc09db30?hl=ko-KR&gl=KR`. 열쇠가 쿼리를 남겨 다른 페이지였다.
2. 「읽지 않고 적은 것: SamsungNotes, Simplenote」 · 「시킨 것 ❌」: 그 두 상세의 추출 본문은 설명뿐이라 앱 이름이 없었고, 모델은 같은
   결과의 제목·structured_data 로 맞게 채웠다. 검사기의 원문 해석기는 본문(`text`)만 돌려줬다.
3. (같은 새벽, 대표 스크린샷) 큰 화면이 **재시작 전 마지막 장**(12일 전 YTN 기사)을 붙든 채 멈춰 보였다 — 서버는 새 장을 보내는데,
   창이 재시작 전 번호(수만)를 들고 「이것보다 새 것」을 달라고 했고 새 프로세스의 번호는 0 부터라 「새 장 없음」만 돌아갔다.
"""
from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.live_view import LiveView

OPENED = {
    "9n92mc09db30": "Goodnotes: AI 노트, 문서, PDF - Windows에서 무료 다운로드 및 설치 | Microsoft Store",
    "9nblggh43vhv": "Samsung Notes - Windows에서 무료 다운로드 및 설치 | Microsoft Store",
    "9nxqq40ldw3x": "Simplenote - Windows에서 무료 다운로드 및 설치 | Microsoft Store",
}


def _steps(opened: dict[str, str] = OPENED) -> list[dict]:
    steps = [{"ok": True, "tool": "browser_open", "evidence": {
        "url": "https://apps.microsoft.com/search?query=%EB%A9%94%EB%AA%A8&hl=ko-KR&gl=KR", "title": "메모 - Microsoft Apps"},
        "evidence_record": {"type": "page_open"}}]
    for app, title in opened.items():
        url = f"https://apps.microsoft.com/detail/{app}?hl=ko-KR&gl=KR"
        steps.append({"ok": True, "tool": "browser_open_result", "evidence": {"url": url, "title": title},
                      "evidence_record": {"type": "page_open"}})
        steps.append({"ok": True, "tool": "browser_extract", "evidence": {"url": url, "title": title},
                      "evidence_record": {"type": "body_read"}})
    return steps


ANSWER = (
    "| 순위 | 앱 이름 | 가격 | 평점 | 출처 URL |\n|---|---|---|---|---|\n"
    "| 1 | Goodnotes: AI 노트, 문서, PDF | 무료 | 4.1 | https://apps.microsoft.com/detail/9n92mc09db30 |\n"
    "| 2 | Samsung Notes | 무료 | 2.9 | https://apps.microsoft.com/detail/9nblggh43vhv |\n"
    "| 3 | Simplenote | 무료 | 4.1 | https://apps.microsoft.com/detail/9nxqq40ldw3x |\n"
)


def test_the_rows_of_m2_are_bound_to_the_pages_it_opened() -> None:
    note = BrowserAgent._row_page_binding_check(ANSWER, _steps())
    assert "열지 않은 주소" not in note, note


def test_a_row_with_an_app_that_was_never_opened_is_still_flagged() -> None:
    answer = ANSWER.replace("9nxqq40ldw3x", "9n6g3485n1rg")    # M3 가 기억으로 조립해 404 를 맞은 id
    note = BrowserAgent._row_page_binding_check(answer, _steps())
    assert "이번에 열지 않은 주소" in note and "9n6g3485n1rg" in note


def test_the_query_is_only_ignored_when_the_row_has_none_and_ends_in_an_id() -> None:
    titles = {"apps.microsoft.com/detail/9nblggh43vhv?hl=ko-KR&gl=KR": "Samsung Notes",
              "prod.danawa.com/info/?pcode=222": "다른 상품", "example.com/list?page=2": "목록"}
    assert BrowserAgent._opened_key("https://apps.microsoft.com/detail/9nblggh43vhv", titles) \
        == "apps.microsoft.com/detail/9nblggh43vhv?hl=ko-KR&gl=KR"
    assert BrowserAgent._opened_key("https://apps.microsoft.com/detail/9NBLGGH43VHV/", titles)   # 대소문자·끝 빗금
    # 쿼리가 곧 상품 번호인 곳은 그대로 — 다른 번호를 같은 페이지로 보면 안 된다.
    assert BrowserAgent._opened_key("https://prod.danawa.com/info/?pcode=111", titles) == ""
    # 끝 칸이 식별자처럼 생기지 않았으면(목록 주소) 묶지 않는다.
    assert BrowserAgent._opened_key("https://example.com/list", titles) == ""


class _Store:
    """원문 해석기가 받는 저장소 모양 — 추출 본문에 앱 이름이 없고 제목·구조화 데이터에만 있는 판(M2 Simplenote)."""

    def get_for_artifact(self, job_id, step):
        return {"payload": {"text": "텍스트 중심의 가벼운 메모 앱. 빠른 동기화."},
                "raw_result_json": '{"title": "Simplenote - Windows에서 무료 다운로드 및 설치 | Microsoft Store", '
                                   '"structured_data": {"items": [{"type": "softwareapplication", '
                                   '"fields": ["name: Simplenote", "aggregateRating.ratingValue: 4.1"]}]}}'}

    def get(self, job_id, step):
        return {"payload": {"text": "텍스트 중심의 가벼운 메모 앱."}}


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names: set[str] = set()
    ollama_tools: list = []


def test_what_was_read_includes_the_title_and_the_structured_data(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    agent = BrowserAgent(config, object(), object(), _Browser(), _Tools(), JobStore(tmp_path / "j.db"), EventBus())
    agent.observations = _Store()
    _, resolve, _ = agent._evidence_view([], "job")
    body = resolve("job", 7)
    assert "빠른 동기화" in body and "Simplenote - Windows" in body and "ratingValue: 4.1" in body


def test_a_window_holding_a_number_from_before_the_restart_gets_the_current_frame() -> None:
    view = LiveView(worker=object())
    view._watch = lambda: None   # 스트림 스레드는 띄우지 않는다
    view._seq = 5108
    view._frame = {"seq": 5108, "jpeg": b"notion", "url": "https://apps.microsoft.com/detail/xpdbvss44r0l9h"}
    # 재시작 전 창이 들고 있던 번호 — 새 프로세스의 번호보다 크다.
    got = view.frame(after=38_000, wait=0.05)
    assert got is not None and got["jpeg"] == b"notion"
    # 평소 롱 폴은 그대로: 받은 장이 최신이면 새 장이 올 때까지 기다리다 없으면 None.
    assert view.frame(after=5108, wait=0.05) is None
    assert view.frame(after=5000, wait=0.05)["seq"] == 5108
