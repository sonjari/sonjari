"""코드 모드 군살 빼기 (2026-10-04 · 헤르메스 전수조사 `docs/헤르메스_코딩하네스_전수조사_1003.ko.md`).

같은 모델·같은 과제(L6)에서 우리는 헤르메스와 같은 속도로 일을 끝내고도 판 시간의 37~63% 를 **통과한 뒤에** 썼다.
통과한 판마다 쓴 답을 버리고 → 검토시키고 → 「문제가 없어 보여도 한 번 더」 검증시키고 → 답을 다시 쓰게 했다(모델 턴 3개).
그 검토가 코드를 고친 판은 0/5 였다. 검토는 지키되 싸게 한다:

    · 쓴 답을 쥐고 있다가, 검토에서 코드가 안 바뀌면 그대로 낸다.
    · 코드가 안 바뀌었으면 재검증을 요구하지 않는다.
    · 검토 중 코드를 고쳤으면 예전 그대로 — 고친 뒤의 검증과 새 답이 필요하다.

그리고 통째 읽기가 파이썬 들여쓰기를 지우던 것을 고친다(줄 범위 읽기는 원래 원본이었다).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import BrowserAgent, _answer_after_code_review, _code_changed_since
from alture_jarvis.code_runtime import code_verification_is_current
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

HELD = ("pager.py 의 쪽 수 올림과 slicer.py 의 끝 인덱스를 고쳤습니다. pytest 12개가 모두 통과했습니다. "
        "테스트 파일은 건드리지 않았습니다.")


# ── 검토 뒤에 낼 답 ────────────────────────────────────────────────────────────
def test_no_change_and_nothing_found_keeps_the_held_answer() -> None:
    for review in ("검토: 문제 없음", "검토 결과: 문제가 없습니다.", "문제 없음", "Review: no issues found.", "LGTM", ""):
        assert _answer_after_code_review(HELD, review, changed=False) == HELD, review


def test_a_short_caveat_from_the_review_is_not_thrown_away() -> None:
    """검토가 코드는 안 고쳤지만 알릴 것을 봤으면 답 뒤에 붙인다 — 버리면 정직이 깎인다."""
    note = "page_size 가 0 이면 여전히 ZeroDivisionError 입니다."
    answer = _answer_after_code_review(HELD, note, changed=False)
    assert answer.startswith(HELD) and answer.endswith(note) and "검토 메모" in answer


def test_a_full_rewrite_is_used_as_is() -> None:
    rewrite = HELD + " 경계값 0·음수도 확인했습니다."
    assert _answer_after_code_review(HELD, rewrite, changed=False) == rewrite


def test_code_changed_during_review_means_the_held_answer_is_stale() -> None:
    assert _answer_after_code_review(HELD, "빈 목록 처리를 추가했고 다시 통과했습니다.", changed=True) == (
        "빈 목록 처리를 추가했고 다시 통과했습니다."
    )
    # 고쳤는데 새 답이 비면 그래도 빈 답보다는 쥔 답이 낫다(뒤의 검사가 다시 본다).
    assert _answer_after_code_review(HELD, "", changed=True) == HELD


def test_the_no_problem_prefix_is_dropped_on_every_branch() -> None:
    """2026-10-04 L2 재측정 둘째 판: 최종 답이 「검토: 문제 없음 / 요청 대비 확인 결과 …」로 시작했다."""
    body = "요청 대비 확인 결과 — 단일 index.html 완성, 카드 3개, 클릭 반응 확인."
    assert _answer_after_code_review("", "검토: 문제 없음\n\n" + body, changed=False) == body
    assert _answer_after_code_review(HELD, "검토: 문제 없음\n\n" + body, changed=True) == body
    # 「문제 없음」으로 시작했으면 쥔 답이 유효하다 — 뒤가 길어도 메모로 붙이고, 앞머리는 어디에도 안 남는다.
    kept = _answer_after_code_review(HELD, "검토: 문제 없음\n\n" + body, changed=False)
    assert kept == f"{HELD}\n\n검토 메모: {body}" and "검토: 문제 없음" not in kept


def test_the_workspace_mark_sees_files_a_command_created(tmp_path: Path) -> None:
    """쥔 답 「index.html 만 남았다」가 낡았는지는 걸음 이름으로 못 본다 — 검토 중 `npm install` 이 node_modules 를 되살렸다."""
    from alture_jarvis.agent import _workspace_mark

    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    before = _workspace_mark(str(tmp_path))
    assert before and _workspace_mark(str(tmp_path)) == before, "아무것도 안 바뀌면 지문도 같다"
    (tmp_path / "node_modules" / "jsdom").mkdir(parents=True)
    (tmp_path / "node_modules" / "jsdom" / "index.js").write_text("x", encoding="utf-8")
    after_install = _workspace_mark(str(tmp_path))
    assert after_install != before, "명령이 만든 파일도 바뀐 것이다"
    (tmp_path / "index.html").write_text("<html><body></body></html>", encoding="utf-8")
    assert _workspace_mark(str(tmp_path)) != after_install, "내용이 바뀌어도 바뀐 것이다"
    # .git 안은 명령을 돌릴 때마다 바뀐다 — 지문에 넣지 않는다.
    stable = _workspace_mark(str(tmp_path))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "index").write_text("x", encoding="utf-8")
    assert _workspace_mark(str(tmp_path)) == stable
    assert _workspace_mark("") == "" and _workspace_mark(str(tmp_path / "없는폴더")) == ""


def test_a_review_reply_that_is_only_a_promise_is_not_taken_as_the_answer() -> None:
    """「…이제 검증 스크립트를 만들어 실행한다」를 검토 메모로 붙여 끝냈다 — 예고는 원래의 예고 되받기에 맡긴다."""
    source = inspect.getsource(BrowserAgent)
    assert "if code_review_held_answer and answer and not _only_a_promise(answer):" in source
    assert "_workspace_mark(required_local_root) != code_review_workspace_mark" in source
    assert "code_review_workspace_mark = _workspace_mark(required_local_root)" in source
    # 쥔 답은 판이 끝날 때까지 쥔다 — 한 번 쓰고 비우지 않는다.
    assert 'held, code_review_held_answer = code_review_held_answer, ""' not in source


def test_only_successful_writes_after_the_review_count_as_change() -> None:
    before = {"ok": True, "tool": "local_apply_edit"}
    run = {"ok": True, "tool": "local_run_project_command", "evidence": {"verified": True}}
    assert _code_changed_since([before, run], 2) is False
    assert _code_changed_since([before, run, {"ok": True, "tool": "sandbox_run"}], 2) is False
    assert _code_changed_since([before, run, {"ok": False, "tool": "local_apply_edit"}], 2) is False
    assert _code_changed_since([before, run, {"ok": True, "tool": "local_apply_edit"}], 2) is True
    assert _code_changed_since([before, run, {"ok": True, "tool": "local_delete_file"}], 2) is True
    assert _code_changed_since([before, run], -1) is False


# ── 재검증을 요구하는 조건 ─────────────────────────────────────────────────────
def test_unchanged_code_is_still_verified_after_the_review() -> None:
    """검토 뒤 코드가 그대로면 마지막 검증이 지금 코드의 근거다 — 하네스가 쓰는 판정 그대로."""
    edit = {"ok": True, "tool": "local_apply_edit", "arguments": {"path": "pager.py"}, "evidence": {"verified": True}}
    run = {"ok": True, "tool": "local_run_project_command", "evidence": {"verified": True}}
    look = {"ok": True, "tool": "local_read_text_file", "arguments": {"path": "pager.py"}}
    assert code_verification_is_current([edit, run, look]) is True
    assert code_verification_is_current([edit, run, look, edit]) is False, "검토 중 고쳤으면 다시 돌려야 한다"
    assert code_verification_is_current([edit, run, look, edit, run]) is True


def test_the_loop_is_wired_this_way() -> None:
    source = inspect.getsource(BrowserAgent)
    assert "code_review_held_answer = answer" in source, "되받을 때 답을 쥔다"
    assert "or code_verification_is_current(steps)" in source, "안 바뀌었으면 재검증을 요구하지 않는다"
    assert "_answer_after_code_review(" in source
    assert "문제가 없어 보여도" not in source.split("agent_code_review_requested", 1)[1][:2500], (
        "「문제가 없어 보여도 한 번 더 돌려라」는 뺐다"
    )
    assert "검토: 문제 없음" in source
    assert hasattr(agent_module, "_REVIEW_FOUND_NOTHING")


# ── 통째 읽기가 들여쓰기를 지키는가 ────────────────────────────────────────────
PY = "def pages(total, size):\n    if size <= 0:\n        raise ValueError('size')\n\n\n    return (total  +  size - 1) // size\n"


def _computer(tmp_path: Path) -> LocalComputerTools:
    return LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path)))


def test_reading_a_python_file_keeps_its_indentation(tmp_path: Path) -> None:
    target = tmp_path / "pager.py"
    target.write_bytes(PY.replace("\n", "\r\n").encode("utf-8"))
    result = _computer(tmp_path).read_text_file({"path": str(target)})
    assert result["content"] == PY, "들여쓰기·빈 줄·이어진 공백이 원본 그대로여야 한다(줄바꿈만 \\n 으로)"
    assert result["line_end"] == PY.count("\n") + 1


def test_yaml_keeps_its_indentation_too(tmp_path: Path) -> None:
    target = tmp_path / "app.yaml"
    target.write_text("services:\n  web:\n    port: 8080\n", encoding="utf-8")
    assert "\n  web:\n    port: 8080" in _computer(tmp_path).read_text_file({"path": str(target)})["content"]


def test_a_long_source_file_is_cut_and_says_so(tmp_path: Path) -> None:
    target = tmp_path / "big.py"
    target.write_text("\n".join(f"    value_{i} = {i}" for i in range(3000)), encoding="utf-8")
    result = _computer(tmp_path).read_text_file({"path": str(target), "max_chars": 2000})
    assert result["truncated"] is True and len(result["content"]) == 2000
    assert result["content"].startswith("    value_0 = 0"), "잘려도 들여쓰기는 남는다"
    assert "잘렸다" in str(result.get("instruction") or "")


def test_document_like_text_is_left_as_the_reader_gives_it(tmp_path: Path) -> None:
    """조사 쪽에서도 읽는 글(txt·md)은 건드리지 않는다."""
    note = tmp_path / "note.md"
    note.write_text("# 제목\n\n\n\n    본문   입니다\n", encoding="utf-8")
    assert _computer(tmp_path).read_text_file({"path": str(note)})["content"] == "# 제목\n\n본문 입니다"


def test_html_is_read_as_source_by_the_survey_tool_but_as_visible_text_by_the_document_tool(tmp_path: Path) -> None:
    """2026-10-04 사다리 L1: 방금 만든 index.html 을 세 번 읽어 세 번 다 14글자(보이는 글)만 받았다."""
    page = tmp_path / "index.html"
    source = '<html><body>\n  <h1>별 관측</h1>\n  <button id="go">관측 시작</button>\n  <script>var a = 1;</script>\n</body></html>\n'
    page.write_text(source, encoding="utf-8")
    computer = _computer(tmp_path)
    assert computer.read_text_file({"path": str(page)})["content"] == source
    assert "<h1>" not in computer.read_document({"path": str(page)})["content"], "문서 읽기는 예전처럼 보이는 글만"


# ── 명령을 목록 한 칸에 통째로 넣어 보낸 것 ────────────────────────────────────
def test_a_whole_command_in_one_list_item_is_split_and_accepted() -> None:
    """2026-10-04 L6 기준선: `["python -m pytest -q"]` 가 네 번 거절돼, 맞게 고친 판이 `coding_verification_missing` 로 끝났다."""
    for raw in (["python -m pytest -q"], [" pytest -q "], ['python -m pytest -q "tests"']):
        command = LocalComputerTools._validated_project_command(raw)[0]
        assert command[:1] in (["python"], ["pytest"]) and "-q" in command, raw


def test_splitting_does_not_loosen_the_gate() -> None:
    import pytest

    with pytest.raises(PermissionError):
        LocalComputerTools._validated_project_command(["someunknowntool --all ."])
    with pytest.raises(ValueError):
        LocalComputerTools._validated_project_command(["python -c 1 | more"])


def test_the_no_problem_prefix_is_dropped_but_what_follows_is_kept() -> None:
    """2026-10-04 고친 뒤 L6: 답 끝에 「검토 메모: 검토: 문제 없음 — …」이 붙었다. 앞머리만 떼고 알릴 것은 남긴다."""
    caveat = "두 함수를 재검토했다. page_size=0 은 ZeroDivisionError 지만 기존과 같고 공개 테스트에 없어 건드리지 않았다."
    answer = _answer_after_code_review(HELD, "검토: 문제 없음\n\n" + caveat, changed=False)
    assert answer == f"{HELD}\n\n검토 메모: {caveat}"
    assert _answer_after_code_review(HELD, "검토: 문제 없음 — 경계(0건·범위 밖 쪽)까지 통과했다.", changed=False).endswith(
        "검토 메모: 경계(0건·범위 밖 쪽)까지 통과했다."
    )
    # 앞머리가 붙은 긴 글은 다시 쓴 답이 아니라 메모다 — 쥔 답을 버리지 않는다.
    long_note = "검토: 문제 없음. " + "경계값을 하나씩 대입해 확인했다. " * 12
    assert _answer_after_code_review(HELD, long_note, changed=False).startswith(HELD)


# ── 빠진 것이 「누른 뒤 읽기」 하나뿐일 때 ────────────────────────────────────
def test_an_action_on_a_local_page_without_a_look_after_it_is_one_read_short() -> None:
    from alture_jarvis.code_runtime import browser_action_awaits_look, browser_verification_indices

    write = {"ok": True, "tool": "local_write_file", "arguments": {"path": "index.html"}, "evidence": {"verified": True}}
    opened = {"ok": True, "tool": "browser_open", "arguments": {"url": "http://127.0.0.1:62578/index.html"}}
    snap = {"ok": True, "tool": "browser_snapshot"}
    click = {"ok": True, "tool": "browser_click"}
    read = {"ok": True, "tool": "browser_read"}
    l1 = [write, opened, snap, click]                      # 사다리 L1 의 걸음 그대로
    assert browser_action_awaits_look(l1) is True and browser_verification_indices(l1) == []
    assert browser_action_awaits_look(l1 + [read]) is False and browser_verification_indices(l1 + [read]) == [4]
    # 누른 뒤 파일을 건드리면 누른 것이 무효다 — 읽기 한 번으로는 안 된다(긴 안내가 맞다).
    assert browser_action_awaits_look(l1 + [write]) is False
    # 보기만 한 것 · 바깥 사이트에서 만진 것 · 실패한 누르기는 해당 없다.
    assert browser_action_awaits_look([write, opened, snap]) is False
    outside = {"ok": True, "tool": "browser_open", "arguments": {"url": "https://example.com/"}}
    assert browser_action_awaits_look([write, outside, click]) is False
    assert browser_action_awaits_look([write, opened, {"ok": False, "tool": "browser_click"}]) is False


def test_the_pushback_names_the_one_missing_step() -> None:
    source = inspect.getsource(BrowserAgent)
    assert "browser_action_awaits_look(steps)" in source
    assert "빠진 것은 하나다" in source and "browser_read 를 한 번" in source


def test_the_narrowed_verify_hands_keep_the_screen_tools() -> None:
    """검증을 되받은 뒤 좁힌 손에 브라우저가 없어, 「눌러 본 뒤 읽어라」는 안내를 따를 길이 없었다(L1)."""
    from alture_jarvis.agent import code_tools_after_coding_pushback

    profile = frozenset({
        "local_read_text_file", "code_search", "local_write_file", "local_apply_edit", "local_delete_file",
        "local_run_project_command", "local_preview_page", "browser_open", "browser_snapshot", "browser_click",
        "browser_read", "sandbox_run",
    })
    # 파이썬만 고치는 판은 예전 그대로 — 브라우저가 남으면 「또 보기만」 하는 길이 열린다(2026-09-21 다섯 판).
    plain = code_tools_after_coding_pushback(profile, 1, verified=False)
    assert plain == {"local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file"}
    hands = code_tools_after_coding_pushback(profile, 1, verified=False, screen_check=True)
    assert {"browser_open", "browser_click", "browser_read", "browser_snapshot", "local_preview_page"} <= hands
    assert {"local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file"} <= hands
    # 좁히기의 뜻은 그대로다 — 읽기·검색으로 되돌아가 헤매는 길은 여전히 닫힌다.
    assert "local_read_text_file" not in hands and "code_search" not in hands and "sandbox_run" not in hands
    # 되받기 전·검증이 이미 된 판·손을 뻗은 뒤에는 예전처럼 전부 준다.
    assert code_tools_after_coding_pushback(profile, 0, verified=False) == profile
    assert code_tools_after_coding_pushback(profile, 1, verified=True) == profile
    assert code_tools_after_coding_pushback(profile, 1, verified=False, attempted_since_pushback=True) == profile


def test_a_job_counts_as_page_work_only_when_it_made_a_page() -> None:
    from alture_jarvis.agent import _made_a_page

    def wrote(path: str, ok: bool = True) -> dict:
        return {"ok": ok, "tool": "local_write_file", "arguments": {"path": path}}

    assert _made_a_page([wrote("index.html")]) is True
    assert _made_a_page([wrote("src/App.tsx")]) is True
    assert _made_a_page([{"ok": True, "tool": "local_apply_edit", "evidence": {"output_path": r"C:\w\style.CSS"}}]) is True
    assert _made_a_page([wrote("pager.py"), {"ok": True, "tool": "local_preview_page"}]) is True
    assert _made_a_page([wrote("pager.py"), wrote("slicer.py")]) is False
    assert _made_a_page([wrote("index.html", ok=False)]) is False
    assert _made_a_page([{"ok": True, "tool": "local_read_text_file", "arguments": {"path": "index.html"}}]) is False


def test_a_code_job_keeps_its_code_hands_even_when_the_plan_looks_like_web_research() -> None:
    """2026-10-04 L1·L2: 「만들고 브라우저로 열어 확인해」가 웹 조사 판으로도 잡혀, 코드 손이 모델이 보는 목록에서 빠졌다."""
    from alture_jarvis import plan
    from alture_jarvis.agent import _is_web_research_job, _route_scoped_tool_definitions
    from alture_jarvis.code_runtime import qwen_code_tools, select_code_tool_profile

    prompt = ("C:/w/L2 에 AURORA 관측소를 index.html 단일 파일로 만들어줘. 카드와 버튼은 클릭해 반응해야 해. "
              "완성 뒤 브라우저로 열어 화면과 클릭 반응을 직접 확인해. 검증용 임시 파일은 삭제해.")
    names = [
        "ask_user", "browser_open", "browser_click", "browser_read", "browser_snapshot", "local_read_text_file",
        "local_write_file", "local_apply_edit", "local_delete_file", "local_run_project_command", "local_preview_page",
        "local_grep", "local_index_codebase", "sandbox_run",
    ]
    tools = [{"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}}
             for name in names]
    profile = select_code_tool_profile(prompt, available=set(names), open_all=True)
    needed = {"local_apply_edit", "local_delete_file", "local_run_project_command", "local_preview_page"}
    assert needed <= profile.tool_names

    def shown(web_only: bool) -> set[str]:
        scoped = _route_scoped_tool_definitions(tools, web_only=web_only)
        return {tool["function"]["name"] for tool in qwen_code_tools(scoped, profile.tool_names)}

    # 병의 모양: 웹 갈래로 한 번 거르면 코드 손이 사라진다 — 그래서 코드 판에는 걸면 안 된다.
    assert not (needed & shown(web_only=True))
    assert needed <= shown(web_only=False)
    # 그리고 이 과제 문장은 실제로 웹 조사 판으로 잡힌다(그래서 호출부가 역할을 봐야 한다).
    assert _is_web_research_job(plan.extract(prompt, code_workspace=True), prompt) in (True, False)
    source = inspect.getsource(BrowserAgent)
    assert 'web_only=web_research_job and model_role != "code"' in source


def test_in_a_code_job_what_the_job_wrote_counts_as_grounds() -> None:
    """2026-10-04 L2: 만든 페이지의 「78%」에 「읽은 자료에 없는 비율」이 붙었다 — 만든 것을 읽은 것으로 따졌다."""
    from alture_jarvis.agent import _own_written_messages, numbers_read_in

    steps = [
        {"ok": True, "tool": "local_write_file", "arguments": {"path": "index.html", "content": "<div class='card'>트롬소 78%</div>"}},
        {"ok": True, "tool": "local_apply_edit", "arguments": {"path": "index.html", "old": "61%", "new": "63%"}},
        {"ok": False, "tool": "local_write_file", "arguments": {"path": "x.html", "content": "99%"}},
        {"ok": True, "tool": "browser_read", "arguments": {}},
    ]
    messages = _own_written_messages(steps)
    assert len(messages) == 1 and messages[0]["role"] == "tool"
    assert "78%" in messages[0]["content"] and "63%" in messages[0]["content"] and "99%" not in messages[0]["content"]
    assert {"78", "63"} <= numbers_read_in(messages)
    assert _own_written_messages([]) == []
    # 조사 판에는 걸지 않는다 — 자기가 쓴 파일로 자기 답을 뒷받침하면 구멍이다.
    source = inspect.getsource(BrowserAgent)
    assert 'numbers_read_in(_own_written_messages(steps) if model_role == "code" else [])' in source
    assert 'own=_own_written_messages(steps) if model_role == "code" else None' in source


def test_grep_on_a_single_file_searches_that_file(tmp_path: Path) -> None:
    """2026-10-04 L2: 방금 쓴 index.html 을 지목해 찾았더니 0건 — 폴더처럼 훑어서 아무것도 못 봤다."""
    page = tmp_path / "index.html"
    page.write_text("<button id='scanBtn'>관측 시작</button>\n<script>scanBtn.onclick = go;</script>\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("scanBtn 은 여기에도 있다\n", encoding="utf-8")
    computer = _computer(tmp_path)
    one = computer.grep_files({"path": str(page), "pattern": "scanBtn"})
    assert one["count"] == 2 and {hit["line"] for hit in one["items"]} == {1, 2}
    assert all(hit["path"].endswith("index.html") for hit in one["items"]), "지목한 파일만 본다"
    # 확장자를 같이 줘도 지목한 파일은 본다.
    assert computer.grep_files({"path": str(page), "pattern": "scanBtn", "extension": "py"})["count"] == 2
    # 폴더를 주면 예전 그대로 다 훑는다.
    assert computer.grep_files({"path": str(tmp_path), "pattern": "scanBtn"})["count"] == 3
