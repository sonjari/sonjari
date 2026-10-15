"""**빈 폴더에 새로 만드는 일**이 막혀 있었다 (2026-09-20 실전에서 드러남).

## 어떻게 찾았나

사장님 기준대로 프론트를 시켜 봤다 — "학원 원장이 보는 오늘의 현황 랜딩 페이지를 리액트로".
빈 폴더를 작업 자리로 주고 980초를 돌렸는데 **파일이 하나도 안 나왔다.** 걸음 13개 중:

     1 O local_index_codebase          (빈 폴더라 나올 게 없다)
     2 X local_write_file   code_recon_required
     3 O local_list_directory          (비어 있다)
     4 X local_write_file   code_recon_required
     5 X local_read_text_file  path_not_found: index.html   ← **아직 안 만들었으니 당연히 없다**
     6 X local_write_file   code_recon_required
     ...                                (같은 벽에 다섯 번)
    11 X local_write_document  format_not_writable:html
    13 O local_grep

`code_recon_ready` 가 **`local_read_text_file` 성공 한 번**만 인정했다. 그런데 빈 폴더에는
읽을 파일이 없다. 모델은 색인·목록·glob·grep 으로 **네 번 정찰해 비어 있다는 사실을
확인했는데도**, 「먼저 읽어라」에 걸려 한 글자도 못 썼다.

★ 규칙 자체는 옳다 — 남의 코드를 안 읽고 고치면 안 된다. 잘못된 것은 **「고치기」와 「새로
  만들기」를 구별하지 않은 것**이다. 없는 파일은 읽을 수 없다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent


def test_an_empty_folder_lets_you_create_the_first_file() -> None:
    """★ 이것이 980초를 날린 그 자리다."""
    assert BrowserAgent._code_recon_ready([
        {"ok": True, "tool": "local_index_codebase", "evidence": {"count": 0}},
        {"ok": True, "tool": "local_list_directory", "evidence": {"count": 0}},
    ]) is True


def test_a_folder_with_files_still_demands_a_real_read() -> None:
    """훑어봤는데 **뭔가 있었다면** 읽고 나서 고쳐야 한다 — 규칙의 원래 뜻은 그대로."""
    assert BrowserAgent._code_recon_ready([
        {"ok": True, "tool": "local_list_directory", "evidence": {"count": 12}},
    ]) is False
    assert BrowserAgent._code_recon_ready([
        {"ok": True, "tool": "local_grep", "evidence": {"matches": 3}},
    ]) is False


def test_reading_a_file_is_still_the_main_road() -> None:
    assert BrowserAgent._code_recon_ready([
        {"ok": True, "tool": "local_read_text_file"},
    ]) is True


def test_writing_without_looking_at_anything_is_still_refused() -> None:
    """아무것도 안 보고 쓰는 것은 그대로 막는다 — 넓히면 반대쪽으로 넘어간다."""
    assert BrowserAgent._code_recon_ready([]) is False
    assert BrowserAgent._code_recon_ready([
        {"ok": False, "tool": "local_list_directory"},   # 실패한 훑기는 훑은 것이 아니다
    ]) is False


def test_the_guard_still_covers_editing_and_deleting() -> None:
    """`local_apply_edit`·`local_delete_file` 은 대상이 이미 있으므로 읽을 수 있다 — 그대로 막힌다."""
    import inspect

    source = inspect.getsource(BrowserAgent.run)
    guarded = source.split("_code_recon_ready(steps)")[1][:600]
    for name in ("local_write_file", "local_apply_edit", "local_delete_file"):
        assert name in guarded, f"{name} 이 규칙 밖으로 빠졌다"


def test_asking_the_document_tool_for_html_points_at_the_right_door() -> None:
    """★ 막힌 자리에서 **어디로 가야 하는지**를 말해 준다 (2026-09-20 실전).

    프론트 과제가 `local_write_file` 에 막히자 문서 도구로 흘러와 `html` 을 요청했고,
    `format_not_writable:html` 다섯 글자만 받고 또 막혔다. 이 저장소가 여러 번 배운 그 자리다.
    """
    import pytest

    from alture_jarvis.documents import write_document

    with pytest.raises(ValueError) as blocked:
        write_document(Path("x.html"), "html", {"text": "<h1>x</h1>"})
    message = str(blocked.value)
    assert "local_write_file" in message, "넓히는 길을 같이 말해 줘야 한다"


# ── 2026-09-28: 큰 저장소 안에 **새 파일**을 만드는 일 ─────────────────────────────────────
#
# 코드 모드 「오픈메테오로 날씨 단일 페이지 만들어 줘」. 작업 자리가 모노레포라 색인·목록은 당연히
# 「뭔가 있다」였고, `local_write_file` 이 네 번 `code_recon_required` 에 막혀 판이 실패했다.
# 모델은 그 거절을 「정책 때문에 못 한다」로 읽었다. 기준은 폴더가 아니라 **그 파일이 이미 있나**다.


def test_a_new_file_inside_a_full_repo_is_creation_not_editing(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "existing.html").write_text("<h1>있음</h1>", encoding="utf-8")
    assert BrowserAgent._creates_new_file("local_write_file", {"path": "web/weather/index.html"}, str(tmp_path)) is True
    assert BrowserAgent._creates_new_file("local_write_file", {"path": str(tmp_path / "new.js")}, "") is True


def test_overwriting_an_existing_file_still_needs_a_read(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert BrowserAgent._creates_new_file("local_write_file", {"path": "app.py"}, str(tmp_path)) is False
    # 편집·삭제는 대상이 있어야 부른다 — 새로 만들기가 아니다.
    assert BrowserAgent._creates_new_file("local_apply_edit", {"path": "nope.py"}, str(tmp_path)) is False


def test_an_unresolvable_path_falls_back_to_the_old_guard() -> None:
    # 상대 경로인데 작업 자리를 모르면 판정할 수 없다 — 막는 쪽으로 넘어진다.
    assert BrowserAgent._creates_new_file("local_write_file", {"path": "index.html"}, "") is False
    assert BrowserAgent._creates_new_file("local_write_file", {}, "E:/x") is False


def test_the_refusal_does_not_read_as_a_policy_wall() -> None:
    import inspect

    source = inspect.getsource(BrowserAgent.run)
    guarded = source.split('"code_recon_required"')[1][:600]
    assert "정책" in guarded and "새로 만드는 것은 막지 않는다" in guarded
