"""만든 파일은 **달라고 한 자리**로 간다 (2026-09-30 워드클라우드 판).

「바탕화면에 sonjari_wordcloud.png 로 저장해 줘」에 상자가 PNG 를 제대로 만들었는데 파일은 잡 작업 폴더에 떨어졌고,
모델은 「바탕화면에 두고 싶으시면 복사해서 붙여넣으세요」로 일을 사람에게 되돌렸다. 대조표는 「실제 산출물 ✅」였다.

- 사람이 **자리와 이름을 둘 다** 댔고 같은 이름이 나오면 코드가 거기로 보낸다(쓰기 범위는 넓히지 않는다).
- 대조표는 폴더까지 본다 — 작업 폴더에 떨어진 것은 「못 한 것」이다.
- 지난 요청 1,302개에 돌려 봤다: 걸린 것 2개(워드클라우드·QR) 뿐.
"""

from __future__ import annotations

import base64
from pathlib import Path

from alture_jarvis import plan
from alture_jarvis.agent import _forced_artifact_decision, requested_delivery
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.sandbox import SandboxBox

BLOB = b"\x89PNG\r\n\x1a\nfake-png"


def _tools(tmp_path: Path, monkeypatch) -> LocalComputerTools:
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    return LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents", local_computer_enabled=True,
    ))


class _Box(SandboxBox):
    """상자 안에서 파일을 꺼내는 부분만 흉내 낸다 — WSL 없이."""

    def _exec(self, script: str, *, timeout: int) -> tuple[int, str, str]:
        return 0, base64.b64encode(BLOB).decode("ascii"), ""


def _box(tmp_path: Path, tools: LocalComputerTools) -> _Box:
    config = JarvisConfig()
    config.sandbox_enabled = True
    config.sandbox_output_dir = tmp_path / "out"
    return _Box(config, local_computer=tools)


def test_place_and_name_are_both_needed() -> None:
    home = Path.home()
    assert requested_delivery(
        "'로컬 AI', '브라우저' 같은 단어로 워드클라우드 PNG 를 만들어서 바탕화면에 sonjari_wordcloud.png 로 저장해 줘."
    ) == home / "Desktop" / "sonjari_wordcloud.png"
    # 주소가 먼저 나와도 뒤의 파일 이름을 찾는다.
    assert requested_delivery(
        "robometafit.com 주소를 담은 QR 코드 PNG 를 만들어서 바탕화면에 qr_robometafit.png 로 저장해 줘."
    ) == home / "Desktop" / "qr_robometafit.png"
    # 읽을 자리·이름 없는 요청은 추측하지 않는다.
    assert requested_delivery("바탕화면에 있는 cloud.png 를 열어서 설명해 줘") is None
    assert requested_delivery("바탕화면에 워드클라우드를 만들어 줘") is None
    assert requested_delivery("cloud.png 로 저장해 줘") is None


def test_a_file_named_as_asked_goes_to_the_asked_place(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    wanted = tools.documents_root / "cloud.png"
    tools.expect_delivery("job-1", wanted)

    got = _box(tmp_path, tools).fetch({"run_id": "abc123", "name": "cloud.png", "__job_id": "job-1"})

    assert got["ok"] and got["delivered_to_request"]
    assert Path(got["path"]).resolve() == wanted.resolve()
    assert wanted.read_bytes() == BLOB


def test_a_different_name_is_not_guessed(tmp_path: Path, monkeypatch) -> None:
    """이름이 다르면 보내지 않는다 — 어느 파일이 그것인지 코드가 추측하지 않는다."""
    tools = _tools(tmp_path, monkeypatch)
    tools.expect_delivery("job-1", tools.documents_root / "cloud.png")

    got = _box(tmp_path, tools).fetch({"run_id": "abc123", "name": "draft.png", "__job_id": "job-1"})

    assert got["ok"] and not got.get("delivered_to_request")
    assert not (tools.documents_root / "draft.png").exists()


def test_a_place_outside_the_write_scope_stays_home_and_says_why(tmp_path: Path, monkeypatch) -> None:
    """쓰기 범위를 몰래 넓히지 않는다. 못 보냈으면 원래 자리에 두고 **왜인지** 말한다."""
    tools = _tools(tmp_path, monkeypatch)
    outside = Path("C:/Windows/sonjari_should_not_be_here.png")
    tools.expect_delivery("job-1", outside)

    got = _box(tmp_path, tools).fetch(
        {"run_id": "abc123", "name": "sonjari_should_not_be_here.png", "__job_id": "job-1"}
    )

    assert got["ok"] and "delivery_error" in got
    assert not outside.exists()
    assert Path(got["path"]).read_bytes() == BLOB


def test_someone_elses_file_at_the_place_is_kept(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    wanted = tools.documents_root / "cloud.png"
    wanted.parent.mkdir(parents=True, exist_ok=True)
    wanted.write_bytes(b"theirs")
    tools.expect_delivery("job-1", wanted)

    got = _box(tmp_path, tools).fetch({"run_id": "abc123", "name": "cloud.png", "__job_id": "job-1"})

    assert wanted.read_bytes() == b"theirs", "남의 파일을 덮었다"
    assert Path(got["path"]).name == "cloud (2).png"
    assert "덮지 않고" in got["renamed_because_exists"]


def _made(path: Path) -> list[dict]:
    return [{"tool": "sandbox_run", "ok": True, "evidence": {"exit_code": 0, "saved_to": [{"path": str(path)}]}}]


def test_a_file_in_the_wrong_folder_is_not_done(tmp_path: Path) -> None:
    made = tmp_path / "workspace" / "cloud.png"
    made.parent.mkdir()
    made.write_bytes(BLOB)
    req = plan.Requirement("artifact", "실제 산출물 파일 만들기", (".png",),
                           destination=str(tmp_path / "Desktop" / "cloud.png"))

    ((_, ok, saw),) = plan.check([req], sources=[], steps=_made(made))

    assert not ok
    assert saw.startswith("요청한 자리") and str(made) in saw


def test_a_file_in_the_asked_folder_is_done_even_if_renamed(tmp_path: Path) -> None:
    """폴더는 엄격하게, 이름은 너그럽게 — 남의 파일을 비켜 `(2)` 가 붙어도 된 것이다."""
    made = tmp_path / "Desktop" / "cloud (2).png"
    made.parent.mkdir()
    made.write_bytes(BLOB)
    req = plan.Requirement("artifact", "실제 산출물 파일 만들기", (".png",),
                           destination=str(tmp_path / "Desktop" / "cloud.png"))

    ((_, ok, _saw),) = plan.check([req], sources=[], steps=_made(made))

    assert ok


def test_a_misplaced_file_is_not_turned_into_a_word_document() -> None:
    """자리만 틀린 판에 「답을 문서로 옮기기」 안전망이 걸리면 PNG 를 달라는 요청에 워드가 하나 더 생긴다."""
    req = plan.Requirement("artifact", "실제 산출물 파일 만들기", (".png",), destination="C:/x/Desktop/cloud.png")
    call, why = _forced_artifact_decision(
        [(req, False, "요청한 자리(C:/x/Desktop)에 없음 — 만든 곳: C:/w/cloud.png")],
        [], "# 결과\n\n| 항목 | 값 |\n|---|---|\n| 해상도 | 1600×900 |\n" * 5, "바탕화면에 cloud.png 로 저장해 줘",
    )
    assert call is None and why == "made_elsewhere"
