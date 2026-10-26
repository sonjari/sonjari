"""자료 낱말을 자모 하나 틀리게 옮긴 오타 표시(사다리 3단 · 10-26). 지난 장표 + 문서 쓰기 1,045번: 걸림 3 · 진짜 1(크로드)."""

from pathlib import Path

from alture_jarvis import near_typos
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

SOURCE = "클로드 앱 · 클로드 코드가 MCP로 손자리를 불러 맡긴다. 클라우드에 올리지 않는다. 학원에 보낸다. 조사해 정리한다. 문서를 쓴다."


def test_the_real_typo_is_found() -> None:
    assert near_typos.find("크로드 앱에서 조사 일을 맡긴다", SOURCE) == [("크로드", "클로드")]
    assert ("크라우드", "클라우드") in near_typos.find("크라우드에 묻지 않아도 된다", SOURCE)


def test_particle_and_ending_differences_are_not_typos() -> None:
    for text in ("학원이 받는다", "조사하고 정리했다", "순서를 바꾼다", "손자리를 부른다", "클로드가 부른다"):
        assert near_typos.find(text, SOURCE) == [], text


def test_known_false_alarm_shapes_stay_visible_only() -> None:
    """지난 기록의 헛걸림 둘(공공기관/공고기관 · 레이지/페이지)은 여전히 걸린다 — 그래서 고치지 않고 표시만 한다."""
    assert near_typos.find("공공기관 지원", "공고기관 목록") == [("공공기관", "공고기관")]


def _tools(tmp_path: Path, prompt: str) -> LocalComputerTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=str(tmp_path / "docs"))
    tools = LocalComputerTools(config)
    tools.publish = lambda event, payload: None
    tools.job_info = lambda job_id: {"payload": {"prompt": prompt}}
    return tools


def test_a_slide_with_the_typo_gets_a_note_but_is_saved(tmp_path: Path, monkeypatch) -> None:
    from alture_jarvis import slides

    monkeypatch.setattr(slides, "fit_in_subprocess", lambda path, **_: {"overflow": 0, "base_px": 20})
    tools = _tools(tmp_path, SOURCE)
    out = tools.make_slide({"title": "x", "index": 1, "total": 2, "theme": "paper", "__job_id": "j",
                            "parts": {"frame": "cover", "title": "크로드 앱에서 맡긴다"}})
    assert out["saved"] and out["typo_check"] == ["확인 필요: 『크로드』 — 자료엔 『클로드』"]


def test_a_document_with_the_typo_is_written_with_a_note(tmp_path: Path) -> None:
    tools = _tools(tmp_path, SOURCE)
    out = tools.write_document_file({"path": "소개.md", "format": "md", "__job_id": "j",
                                     "blocks": [{"type": "paragraph", "text": "크로드 앱이 손자리를 부른다."}]})
    assert "typo_check" in out and "클로드" in out["typo_check"][0]
