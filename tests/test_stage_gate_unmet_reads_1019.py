"""접기 전 산출물 차례에서도 **시킨 것이 남은 곳**은 읽게 한다 (2026-10-19 · 8b90144f · d0d36f19).

아픔 넷 × 제품 둘의 홈페이지 조사(8b90144f)는 아픔 ④의 Ollama · LM Studio 홈페이지를 열려는 순간 걸음 상한에 닿았고,
접기 전 산출물 차례가 두 열기를 `not_this_stage` 로 되돌려 보내 그 칸이 「확인 못 함」으로 나갔다. inline AI 조사(d0d36f19)는
대조표에 「네이버 블로그에서 하기」가 못 채운 채 남았는데, 그 블로그 글을 여는 걸음이 같은 문에 막혔다.

그 차례가 안 읽은 사이트로 가는 길까지 막는 까닭(10-02 · 9d6942f2 — 글 여섯을 읽고도 더 열다 엑셀 0개)은 지킨다:
대조표의 읽기 칸이 다 찼고 요청이 이름으로 댄 곳도 아니면 예전처럼 막힌다. 이미 읽은 사이트로 되돌아가는 손도 막힌다.

걸음의 모양은 운영 기록 그대로다(도구 · 성공 여부 · 인자 · `evidence.url`). 주소의 번호 · 글 번호는 지어낸 것이다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.plan_nudges import (
    _OWED_READ_CALLS_PER_SITE,
    _OWED_READ_REWRITE_NOTE,
    _OWED_READ_SITES,
    _owed_read_site,
    _site_named_in,
    _with_owed_read_note,
)

from test_agent import FakeBrowser

PAIN_PROMPT = (
    "아픔 넷마다 그 문제를 푼다는 제품을 두 개 이상 찾아 공식 홈페이지 첫 화면을 직접 열어 읽고 엑셀로 정리해 줘. "
    "④ 로컬 모델(Ollama 등)을 설치하고 돌리기가 어려움."
)


def _step(tool: str, landed: str = "", /, *, ok: bool = True, error: str = "", **arguments: Any) -> dict[str, Any]:
    return {"tool": tool, "ok": ok, "error": error, "arguments": arguments,
            "evidence": {"url": landed} if landed and ok else {}}


def _req(kind: str, target: Any = None, *, source_scope: str = "") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, label=kind, target=target, source_scope=source_scope)


def _read_three_homepages() -> list[dict[str, Any]]:
    """8b90144f 의 앞 걸음 모양 — 홈페이지를 열고 그 자리에서 읽기를 세 번."""
    steps: list[dict[str, Any]] = []
    for home in ("https://router.example.com/", "https://coder.example.org/", "https://answers.example.net/"):
        steps.append(_step("browser_open", home, url=home.rstrip("/")))
        steps.append(_step("browser_extract", home))
    return steps


# (a) 못 채운 읽기 요구가 있으면 그 읽기는 열린다 — 파일을 쓴 뒤에도.

def test_an_unmet_site_requirement_opens_that_site_even_after_the_file_is_written() -> None:
    """d0d36f19 의 모양: 대조표의 「네이버 블로그에서 하기」가 못 채운 채 남았는데 블로그 글 열기가 막혔다."""
    steps = _read_three_homepages() + [_step("local_write_document", ok=True, path="조사.docx")]
    plan = [(_req("site", ("blog.naver.com",)), False, "거기서 아무것도 안 함"), (_req("artifact"), True, "1개 존재")]
    blog = {"url": "https://blog.naver.com/someone/100000001"}
    assert _owed_read_site("browser_open", blog, steps, plan, "후기도 몇 개 읽어 줘") == "naver.com"
    # 그 사이트를 이미 읽었으면(받아 온 본문이 있으면) 더 열 까닭이 없다.
    read_blog = steps + [_step("browser_open", blog["url"], url=blog["url"]), _step("browser_extract", blog["url"])]
    assert _owed_read_site("browser_open", {"url": "https://blog.naver.com/other/100000002"}, read_blog, plan, "") == ""


def test_an_unmet_count_or_observe_requirement_opens_a_new_site() -> None:
    steps = _read_three_homepages()
    target = {"url": "https://tool.example.io"}
    for requirement in (_req("count", 8, source_scope="web"), _req("count", 8), _req("observe", "web")):
        assert _owed_read_site("browser_open", target, steps, [(requirement, False, "3개 읽음")], "") == "example.io"


def test_a_site_requirement_for_another_site_does_not_open_this_one() -> None:
    plan = [(_req("site", ("blog.naver.com",)), False, "거기서 아무것도 안 함")]
    assert _owed_read_site("browser_open", {"url": "https://tool.example.io"}, _read_three_homepages(), plan, "") == ""


def test_a_requirement_about_this_pc_does_not_open_web_sites() -> None:
    """8b90144f 의 대조표는 「로컬 자료 2개 이상」으로 잘못 읽혔다 — 이 PC 를 보라는 칸이 웹을 열 핑계가 되면 안 된다."""
    steps = _read_three_homepages()
    plan = [(_req("count", 2, source_scope="local"), False, "1개 읽음"), (_req("observe", "local"), False, "0개")]
    assert _owed_read_site("browser_open", {"url": "https://tool.example.io"}, steps, plan, "") == ""


# (b) 요구를 다 채웠으면 원래대로 막힌다 — 차례를 둔 까닭(끝없이 더 읽기)을 지키는 시험.

def test_when_every_read_requirement_is_met_new_sites_stay_refused() -> None:
    steps = _read_three_homepages()
    plan = [
        (_req("count", 3, source_scope="web"), True, "3개 읽음"),
        (_req("site", ("router.example.com",)), True, "1건"),
        (_req("observe", "web"), True, "3개 실제로 읽음"),
        (_req("artifact"), False, "열 수 있는 산출물 없음"),
    ]
    for target in ("https://tool.example.io", "https://another.example.dev"):
        assert _owed_read_site("browser_open", {"url": target}, steps, plan, PAIN_PROMPT) == "", target


def test_going_back_to_a_site_already_read_stays_refused_even_with_requirements_left() -> None:
    """9d6942f2 의 모양: 읽은 글의 사이트로 되돌아가 더 찾는 손. 남은 칸이 있어도 이미 읽은 곳은 「더 찾기」다."""
    steps = _read_three_homepages()
    plan = [(_req("count", 8, source_scope="web"), False, "3개 읽음")]
    assert _owed_read_site("browser_open", {"url": "https://router.example.com/pricing"}, steps, plan, "") == ""
    for hand in ("browser_read", "browser_extract", "browser_snapshot", "browser_page_data"):
        assert _owed_read_site(hand, {}, steps, plan, "") == "", hand


def test_web_search_and_search_engine_results_stay_refused() -> None:
    steps = _read_three_homepages() + [
        _step("browser_search", "https://search.naver.com/search.naver?query=x", query="x 후기"),
    ]
    plan = [(_req("count", 8, source_scope="web"), False, "3개 읽음")]
    assert _owed_read_site("browser_search", {"query": "x 사용 후기"}, steps, plan, "") == ""
    assert _owed_read_site("browser_open_result", {"rank": 1}, steps, plan, "") == ""


def test_the_grant_is_bounded() -> None:
    """받아 주는 곳은 둘 · 한 곳에 넷까지 — 열기 · 그 안의 검색 · 결과 열기 · 읽기. 넘으면 부르는 쪽이 예전처럼 막는다."""
    assert _OWED_READ_SITES == 2
    assert _OWED_READ_CALLS_PER_SITE == 4


# (c) 요청이 이름으로 댄 대상이 남은 경우.

def test_a_target_the_request_named_is_opened_even_when_the_checklist_does_not_know_it() -> None:
    """8b90144f: 대조표는 아픔 ④를 몰랐지만 요청이 「Ollama」를 이름으로 댔다."""
    steps = _read_three_homepages()
    plan = [(_req("count", 2, source_scope="local"), True, "6개 읽음"), (_req("artifact"), False, "없음")]
    assert _owed_read_site("browser_open", {"url": "https://ollama.com"}, steps, plan, PAIN_PROMPT) == "ollama.com"
    # 요청이 이름으로 대지 않은 곳(LM Studio 는 요청에 없었다)은 예전처럼 막힌다.
    assert _owed_read_site("browser_open", {"url": "https://lmstudio.ai"}, steps, plan, PAIN_PROMPT) == ""


def test_a_named_shop_only_touched_and_never_read_is_still_owed() -> None:
    """4cfe1fba(10-13)의 모양: 「다나와에서 하기」는 검색 화면을 연 것만으로 채워졌는데, 상품을 여는 걸음 다섯이 막혀
    파일 없이 끝났다. 요청이 댄 가게에서 본문을 하나도 못 받아 왔으면 그 가게 안의 걸음은 받는다."""
    st11_item = "https://www.11st.co.kr/products/9000000001"
    danawa_search = "https://www.danawa.com/shop/search?query=x"
    steps = [
        _step("browser_open", "https://www.11st.co.kr/", url="https://www.11st.co.kr"),
        _step("browser_open_result", st11_item, rank=1),
        _step("browser_extract", st11_item),
        _step("browser_open", danawa_search, url=danawa_search),
    ]
    plan = [(_req("site", ("danawa.com",)), True, "www.danawa.com 에서 작업"), (_req("site", ("11st.co.kr",)), True, "1건")]
    assert _owed_read_site("browser_open_result", {"rank": 1}, steps, plan, "다나와, 11번가에서 찾아") == "danawa.com"
    # 본문을 받아 온 가게(11번가)로 되돌아가는 것은 막힌다.
    assert _owed_read_site("browser_open", {"url": "https://www.11st.co.kr/products/9000000002"}, steps, plan, "") == ""


def test_named_means_the_whole_word_not_a_piece_of_another() -> None:
    assert _site_named_in("Ollama 를 깔아 보고", "ollama.com")
    assert _site_named_in("inline-ai.com 을 조사해", "inline-ai.com")
    assert not _site_named_in("ollamas 라는 낱말", "ollama.com")
    assert not _site_named_in("AI 도구", "ai.com"), "세 글자 미만 몸통은 안 본다"
    assert not _site_named_in("", "ollama.com") and not _site_named_in("Ollama", "")


def test_a_named_site_already_read_stays_refused() -> None:
    steps = _read_three_homepages() + [
        _step("browser_open", "https://ollama.com/", url="https://ollama.com"),
        _step("browser_extract", "https://ollama.com/"),
    ]
    assert _owed_read_site("browser_open", {"url": "https://ollama.com/download"}, steps, [], PAIN_PROMPT) == ""


def test_the_rewrite_note_rides_inside_the_result_the_model_sees() -> None:
    observation = {"ok": True, "tool": "browser_open", "result": {"url": "https://ollama.com/", "instruction": "앞 안내"}}
    noted = _with_owed_read_note(observation, _OWED_READ_REWRITE_NOTE)
    assert noted["result"]["instruction"].startswith(_OWED_READ_REWRITE_NOTE) and "앞 안내" in noted["result"]["instruction"]
    assert "다시 써서" in noted["result"]["instruction"]
    assert _with_owed_read_note(observation, "") is observation


# 판 하나를 끝까지: 접기 전 산출물 차례에서 이름 댄 곳은 열리고, 이름 안 댄 새 곳은 막힌 채로 파일이 써진다.

def _fn(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object", "properties": {}}}}


class _Tools:
    names = {"browser_open", "browser_read", "local_write_document"}
    ollama_tools = [_fn("browser_open"), _fn("browser_read"), _fn("local_write_document")]


class _Gateway:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.calls: list[tuple[str, str]] = []

    def execute(self, name, arguments, *, job_id=""):
        url = str(arguments.get("url") or f"https://board.example.com/p/{len(self.calls)}")
        self.calls.append((name, url))
        if name == "local_write_document":
            self.out.parent.mkdir(parents=True, exist_ok=True)
            self.out.write_text("| 제품 | 주소 |\n|---|---|\n| a | b |\n", encoding="utf-8")
            return ToolResult(True, name, result={"action": "written", "path": str(self.out), "output_path": str(self.out)})
        return ToolResult(True, name, result={"action": "read", "url": url, "title": url,
                                              "char_count": 3000, "text": f"{url} 본문 " * 40})


class _ReaderThenNewSite:
    """같은 게시판을 계속 읽다가, 「차례」 안내를 받으면 새 곳(`then_open`)을 열려 하고, 그 뒤에 파일을 쓴다."""

    def __init__(self, out: Path, then_open: str) -> None:
        self.out, self.then_open, self.n, self.tried = out, then_open, 0, False

    def chat_messages(self, messages, **kwargs) -> dict[str, Any]:
        self.n += 1
        text = " ".join(str(m.get("content") or "") for m in messages)
        if any("written" in str(m.get("content") or "") for m in messages[-3:]):
            return {"role": "assistant", "content": f"정리했습니다: {self.out}"}
        if ("차례 규칙" in text or "더 찾아도 진전이 없다" in text) and not self.tried:
            self.tried = True
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "browser_open", "arguments": {"url": self.then_open}}}]}
        if "차례 규칙" in text or "더 찾아도 진전이 없다" in text:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "local_write_document", "arguments": {"path": str(self.out), "content": "표"}}}]}
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "browser_read", "arguments": {"url": f"https://board.example.com/p/{self.n}"}}}]}


def _run(tmp_path: Path, prompt: str, then_open: str) -> tuple[_Gateway, list[str], Path]:
    out = tmp_path / "out" / "products.md"
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60, agent_autonomous_max_steps=30)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(out)
    bus = EventBus()
    seen: list[str] = []
    bus.add_listener(lambda record: seen.append(record.event))
    agent = BrowserAgent(config, _ReaderThenNewSite(out, then_open), gateway, FakeBrowser(), _Tools(), store, bus)
    full = prompt.format(out=out.as_posix())
    job = store.create_job("chat", "agent", {"prompt": full})
    store.claim_next()
    agent.run(full, job_id=job["id"], origin="chat", must_observe=True, observe_reasons=frozenset({"web"}))
    return gateway, seen, out


def test_in_the_deliver_turn_a_named_target_is_opened_and_the_file_still_gets_written(tmp_path) -> None:
    gateway, seen, out = _run(
        tmp_path, "게시판 글을 열어 읽고, Ollama 홈페이지도 열어 읽어서 {out} 에 정리해줘", "https://ollama.com",
    )
    assert "agent_deliver_before_wrap_up" in seen, seen
    assert ("browser_open", "https://ollama.com") in gateway.calls, gateway.calls
    assert "agent_owed_read_allowed" in seen
    assert out.exists(), gateway.calls


def test_in_the_deliver_turn_an_unnamed_new_site_stays_refused_and_the_file_gets_written(tmp_path) -> None:
    gateway, seen, out = _run(
        tmp_path, "게시판 글을 열어 읽고 {out} 에 정리해줘", "https://unnamed-tool.example.io",
    )
    assert "agent_deliver_before_wrap_up" in seen, seen
    assert ("browser_open", "https://unnamed-tool.example.io") not in gateway.calls, gateway.calls
    assert "agent_owed_read_allowed" not in seen
    assert out.exists(), gateway.calls
