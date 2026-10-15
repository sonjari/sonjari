"""폼 작성 4종 — 되는 것보다 **안 되는 쪽**을 먼저 잠근다.

playwright-mcp 가 쓰는 도구 모양(fill_form / select_option / file_upload /
handle_dialog)을 우리 계층에 가져온 것이다. 밑바닥(프레임 인지 ref, 증거 검증,
읽기 전용 게이트)은 이미 같은 구조라 도구만 얹었다.

여기서 지키는 것:
  * 반쯤 채워진 폼은 반쯤 채워졌다고 말한다 (어디서 멈췄는지 모르면 사람이 처음부터 확인해야 한다)
  * 업로드는 허용된 폴더 밖으로 못 나간다 (승인만으로는 부족하다 — 경로만 보고 판단하기 어렵다)
  * 확인창은 자동으로 닫히지 않는다 (무엇을 물었는지 남지 않는 게 가장 나쁘다)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from test_browser_generic_control import El, Frame, Loc, Page, _worker


class FormEl(El):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.filled: str | None = None
        self.selected: list[str] = []
        self.files: list[str] = []


class FormLoc(Loc):
    def fill(self, value: str) -> None:
        el = self._el()
        if el is not None:
            el.filled = value

    def select_option(self, label: str = "", value: str = "") -> list[str]:
        el = self._el()
        chosen = label or value
        if el is not None:
            el.selected = [chosen]
        return [chosen]

    def set_input_files(self, paths: list[str]) -> None:
        el = self._el()
        if el is not None:
            el.files = list(paths)


class FormFrame(Frame):
    def locator(self, selector: str) -> Loc:
        if selector.startswith('[data-jarvis-ref='):
            wanted = selector.split('"')[1]
            return FormLoc([e for e in self.elements if e.ref == wanted])
        if selector == "body":
            return FormLoc([FormEl(tag="body", text=self.body)])
        return FormLoc(list(self.elements) if selector else [])


def _form_page(elements: list[FormEl]) -> Page:
    return Page([FormFrame(elements=elements)])


# ── 여러 칸을 한 번에 ────────────────────────────────────────────────────────
def test_a_form_is_filled_in_one_call(tmp_path: Path) -> None:
    name = FormEl(tag="input", text="이름")
    email = FormEl(tag="input", text="이메일")
    page = _form_page([name, email])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._fill_form(page, {"fields": [
        {"ref": name.ref, "value": "박가람"},
        {"ref": email.ref, "value": "garam@example.com"},
    ]})

    assert result["field_count"] == 2
    assert name.filled == "박가람"
    assert email.filled == "garam@example.com"


def test_a_half_filled_form_says_where_it_stopped(tmp_path: Path) -> None:
    """어디까지 들어갔는지 모르면 사람이 화면을 열어 처음부터 확인해야 한다."""
    first = FormEl(tag="input", text="이름")
    page = _form_page([first])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError) as failure:
        worker._fill_form(page, {"fields": [
            {"ref": first.ref, "value": "박가람"},
            {"ref": "j99", "value": "사라진 칸"},
        ]})

    message = str(failure.value)
    assert "fill_form_stopped_at:2/2" in message
    assert "앞의 1칸은 이미 채워져" in message
    assert first.filled == "박가람", "앞 칸은 실제로 들어가 있어야 한다"


def test_a_password_field_still_blocks_the_whole_form(tmp_path: Path) -> None:
    # 한 번에 채운다고 해서 비밀번호 차단이 느슨해지면 안 된다.
    secret = FormEl(tag="input", attrs={"type": "password"})
    page = _form_page([secret])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="sensitive_field_blocked"):
        worker._fill_form(page, {"fields": [{"ref": secret.ref, "value": "1234"}]})


# ── 드롭다운 ─────────────────────────────────────────────────────────────────
def test_a_native_select_is_chosen_by_visible_label(tmp_path: Path) -> None:
    box = FormEl(tag="select", text="학년")
    page = _form_page([box])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._select_option(page, {"ref": box.ref, "label": "고3"})

    assert box.selected == ["고3"]
    assert result["selected"] == ["고3"]
    assert result["verified"] is True


def test_pick_suggestion_routes_a_native_select_to_select_option(tmp_path: Path) -> None:
    """모델이 도구를 잘못 골라도 네이티브 select의 껍데기를 클릭하지 않는다."""
    box = FormEl(tag="select", text="Open this select menu One Two Three")
    page = _form_page([box])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._pick_suggestion(page, {"ref": box.ref, "choose": "Two"})

    assert box.selected == ["Two"]
    assert box.clicks == 0
    assert result["action"] == "option_selected"
    assert result["routed_from"] == "browser_pick_suggestion"
    assert result["verified"] is True


def test_a_custom_dropdown_is_named_rather_than_silently_failing(tmp_path: Path) -> None:
    """div 로 만든 드롭다운에 select_option 을 쓰면 아무 일도 안 일어난다.
    그걸 성공으로 돌려주면 모델은 골랐다고 믿고 다음으로 넘어간다."""
    fake = FormEl(tag="div", text="학년 선택")
    page = _form_page([fake])
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="not_a_select:div"):
        worker._select_option(page, {"ref": fake.ref, "label": "고3"})


# ── 파일 첨부 ────────────────────────────────────────────────────────────────
def _upload_worker(tmp_path: Path, roots: tuple[str, ...]) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_visual_overlay=False,
        browser_evidence_dir=tmp_path / "evidence",
        browser_upload_allowed_roots=roots,
    ))


def test_a_file_from_an_allowed_folder_is_attached(tmp_path: Path) -> None:
    allowed = tmp_path / "documents"
    allowed.mkdir()
    document = allowed / "계약서.pdf"
    document.write_bytes(b"PDF")
    field = FormEl(tag="input", attrs={"type": "file"})
    page = _form_page([field])
    worker = _upload_worker(tmp_path, (str(allowed),))
    worker._snapshot(page, {})

    result = worker._file_upload(page, {"ref": field.ref, "paths": [str(document)]})

    assert field.files == [str(document.resolve())]
    assert result["files"] == ["계약서.pdf"]


def test_a_file_outside_the_allowed_folders_is_refused(tmp_path: Path) -> None:
    """승인(L2)만으로는 부족하다. 승인 화면의 경로가 무엇을 가리키는지 사람이
    한눈에 판단하기 어렵고, 한 번 나간 파일은 되돌릴 수 없다."""
    allowed = tmp_path / "documents"
    allowed.mkdir()
    secret = tmp_path / "secrets" / "id_rsa"
    secret.parent.mkdir()
    secret.write_bytes(b"KEY")
    field = FormEl(tag="input", attrs={"type": "file"})
    page = _form_page([field])
    worker = _upload_worker(tmp_path, (str(allowed),))
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="upload_path_not_allowed"):
        worker._file_upload(page, {"ref": field.ref, "paths": [str(secret)]})
    assert field.files == []


def test_a_missing_file_is_named(tmp_path: Path) -> None:
    allowed = tmp_path / "documents"
    allowed.mkdir()
    field = FormEl(tag="input", attrs={"type": "file"})
    page = _form_page([field])
    worker = _upload_worker(tmp_path, (str(allowed),))
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="file_not_found"):
        worker._file_upload(page, {"ref": field.ref, "paths": [str(allowed / "없는파일.pdf")]})


def test_upload_is_the_one_browser_tool_that_needs_screen_approval(tmp_path: Path) -> None:
    from alture_jarvis.browser import BrowserTools
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.models import RiskLevel
    from alture_jarvis.tool_gateway import ToolGateway

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    gateway = ToolGateway(JobStore(config.database_path), EventBus())
    BrowserTools(config, BrowserWorker(config)).register(gateway)
    levels = {row["name"]: row["risk_level"] for row in gateway.list_tools()}

    assert levels["browser_file_upload"] == RiskLevel.L2.label()
    assert levels["browser_fill_form"] == RiskLevel.L1.label()
    assert levels["browser_snapshot"] == RiskLevel.L0.label()


# ── 브라우저 확인창 ──────────────────────────────────────────────────────────
class _Dialog:
    def __init__(self, message: str, kind: str = "confirm") -> None:
        self.message = message
        self.type = kind
        self.accepted: str | None = None
        self.dismissed = False

    def accept(self, text: str = "") -> None:
        self.accepted = text

    def dismiss(self) -> None:
        self.dismissed = True


# ── 읽기 전용을 꺼도 열리지 않는 것 ──────────────────────────────────────────
#
# 예전엔 위험 동작이 한 덩어리라 스위치 하나가 전부를 막았다. 폼을 쓰려고 스위치를
# 끄면 결제·삭제까지 같이 열렸다 — 전부 아니면 전무. 이제 갈라져 있다.


def _writable_worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_visual_overlay=False,
        browser_read_only=False,      # 폼을 쓰려고 끈 상태
        browser_evidence_dir=tmp_path / "evidence",
    ))


@pytest.mark.parametrize("label", ["신청하기", "저장", "제출", "등록하기", "확인"])
def test_form_buttons_open_up_when_read_only_is_off(tmp_path: Path, label: str) -> None:
    button = FormEl(tag="button", text=label)
    page = _form_page([button])
    worker = _writable_worker(tmp_path)
    worker._snapshot(page, {})

    worker._click(page, {"ref": button.ref})

    assert button.clicks == 1


@pytest.mark.parametrize("label", ["결제하기", "구매", "삭제", "탈퇴", "발행", "송금"])
def test_irreversible_buttons_stay_shut_even_then(tmp_path: Path, label: str) -> None:
    """스위치를 꺼도 돈이 나가거나 지워지는 건 안 눌린다. 사람이 화면에서 승인해야 한다."""
    button = FormEl(tag="button", text=label)
    page = _form_page([button])
    worker = _writable_worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError) as failure:
        worker._click(page, {"ref": button.ref})

    assert "irreversible_click_needs_approval" in str(failure.value)
    assert "browser_click_confirmed" in str(failure.value)
    assert button.clicks == 0


def test_a_textless_submit_input_cannot_bypass_approval(tmp_path: Path) -> None:
    """실측: inner_text가 빈 submit input이 L0 클릭으로 제출돼 버렸다."""
    submit = FormEl(tag="input", attrs={"type": "submit"})
    page = _form_page([submit])
    worker = _writable_worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="irreversible_click_needs_approval:submit"):
        worker._click(page, {"ref": submit.ref})

    assert submit.clicks == 0


def test_the_approved_path_can_press_a_textless_submit_input(tmp_path: Path) -> None:
    submit = FormEl(tag="input", attrs={"type": "submit"})
    page = _form_page([submit])
    worker = _writable_worker(tmp_path)
    worker._snapshot(page, {})

    worker._click_confirmed(page, {"ref": submit.ref})

    assert submit.clicks == 1


def test_the_approved_path_can_press_it(tmp_path: Path) -> None:
    # 승인을 받은 뒤에는 눌려야 한다 — 아니면 승인 흐름 자체가 무의미하다.
    button = FormEl(tag="button", text="결제하기")
    page = _form_page([button])
    worker = _writable_worker(tmp_path)
    worker._snapshot(page, {})

    worker._click_confirmed(page, {"ref": button.ref})

    assert button.clicks == 1


def test_the_approved_click_is_the_l2_one(tmp_path: Path) -> None:
    from alture_jarvis.browser import BrowserTools
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.models import RiskLevel
    from alture_jarvis.tool_gateway import ToolGateway

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    gateway = ToolGateway(JobStore(config.database_path), EventBus())
    BrowserTools(config, BrowserWorker(config)).register(gateway)
    levels = {row["name"]: row["risk_level"] for row in gateway.list_tools()}

    assert levels["browser_click_confirmed"] == RiskLevel.L2.label()
    assert levels["browser_click"] == RiskLevel.L0.label()


class _DialogPage:
    """확인창 리스너만 흉내 낸다 — page.on("dialog", handler) 로 붙는 그 함수."""

    def __init__(self) -> None:
        self.handler: Any = None

    def on(self, event: str, handler: Any) -> None:
        if event == "dialog":
            self.handler = handler


def _fire(worker: BrowserWorker, dialog: _Dialog) -> None:
    page = _DialogPage()
    worker._watch_dialogs(page)
    page.handler(dialog)


def test_a_dialog_is_cancelled_when_nothing_was_allowed(tmp_path: Path) -> None:
    """기본은 취소. 페이지 안 모달에 거는 잣대와 같다."""
    worker = _worker(tmp_path)
    dialog = _Dialog("계속하시겠습니까?")

    _fire(worker, dialog)

    assert dialog.dismissed is True
    assert dialog.accepted is None
    assert worker._last_dialog["message"] == "계속하시겠습니까?"


def test_an_allowance_must_be_given_before_the_click(tmp_path: Path) -> None:
    """확인창이 떠 있는 동안엔 답할 수 없다 — 그 창을 띄운 클릭이 브라우저 스레드를
    쥐고 있어서 뒤이은 명령이 실행되지 않는다(실브라우저에서 교착으로 실측). 그래서
    허가는 미리 둔다."""
    worker = _worker(tmp_path)
    worker._handle_dialog(_form_page([]), {"accept": True})
    # '제출'·'전송' 같은 문구는 읽기 전용에서 허가가 있어도 막힌다(아래 테스트).
    # 여기서 보는 것은 허가 자체가 동작하는가다.
    dialog = _Dialog("계속 진행하시겠습니까?")

    _fire(worker, dialog)

    assert dialog.accepted == ""
    assert dialog.dismissed is False


def test_the_allowance_is_used_up_after_one_dialog(tmp_path: Path) -> None:
    # 한 번 열어 준 문이 계속 열려 있으면, 다음에 뜬 전혀 다른 확인창까지 수락된다.
    worker = _worker(tmp_path)
    worker._handle_dialog(_form_page([]), {"accept": True})
    first, second = _Dialog("계속 진행하시겠습니까?"), _Dialog("한 번 더 진행할까요?")

    _fire(worker, first)
    _fire(worker, second)

    assert first.accepted == ""
    assert second.dismissed is True


def test_a_destructive_dialog_is_cancelled_even_with_an_allowance(tmp_path: Path) -> None:
    """확인창의 '확인'은 클릭과 같은 무게다. 삭제·결제 문구면 허가가 있어도 취소한다 —
    읽기 전용을 꺼도 마찬가지다. '정말 삭제하시겠습니까?'에 자동으로 확인을 누르는
    길은 어떤 모드에서도 열지 않는다."""
    worker = _writable_worker(tmp_path)
    worker._handle_dialog(_form_page([]), {"accept": True})
    dialog = _Dialog("정말 삭제하시겠습니까?")

    _fire(worker, dialog)

    assert dialog.dismissed is True
    assert dialog.accepted is None
    assert worker._last_dialog["blocked_by_read_only"] is True


def test_the_answered_dialog_shows_up_in_the_next_result(tmp_path: Path) -> None:
    """이게 없으면 '눌렀는데 아무 일도 안 일어났다'로 보이고, 무엇을 묻고 무엇으로
    답했는지가 사라진다."""
    worker = _worker(tmp_path)
    _fire(worker, _Dialog("저장하시겠습니까?"))

    evidence = worker._evidence("anything")

    assert evidence["dialog_answered"]["message"] == "저장하시겠습니까?"
    assert evidence["dialog_answered"]["accepted"] is False
