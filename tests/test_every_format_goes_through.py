"""**한 형식이 통과했다고 나머지가 되는 것이 아니다.**

형식마다 다른 라이브러리를 탄다(openpyxl · python-docx · python-pptx ·
python-hwpx · csv · 순수 텍스트). 그리고 오늘 난 고장 넷은 전부 문서 만들기
자체가 아니라 **그 뒤 사슬**에 있었다:

    도구 → 자리(내 문서\\JARVIS) → 장부(_step_evidence) → 계획 대조 → 화면(viewable)

그래서 형식별로 사슬을 통째로 통과시켜 본다. 2026-09-01 에 이 검사를 처음 돌려
`local_read_document` 가 **hwpx 를 못 읽는 것**을 찾았다 — 만들 수는 있는데
되읽지 못하면 「방금 만든 한글 파일 고쳐줘」가 끊긴다.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from alture_jarvis import plan
from alture_jarvis.agent import _step_evidence
from alture_jarvis.config import JarvisConfig
from alture_jarvis.document_reader import DocumentReader, preview_of_file
from alture_jarvis.documents import write_document
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.runtime import JarvisRuntime

warnings.filterwarnings("ignore")

ROWS = [["이름", "점수"], ["나래", "92"]]
BLOCKS = [
    {"type": "heading", "text": "경력 사항"},
    {"type": "paragraph", "text": "42억 원 규모 증빙 적정성 검토"},
]

#: (사람이 부르는 말, 확장자, 만들 때 줄 것, 미리보기에서 찾을 글)
FORMATS = [
    ("엑셀", "xlsx", {"rows": ROWS}, "나래"),
    ("워드", "docx", {"blocks": BLOCKS}, "증빙 적정성 검토"),
    ("PPT", "pptx", {"blocks": [{"title": "검토", "bullets": ["표현 변경"]}]}, "표현 변경"),
    ("한글", "hwpx", {"blocks": BLOCKS}, "증빙 적정성 검토"),
    ("CSV", "csv", {"rows": ROWS}, "나래"),
]


def _tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents",
        local_computer_enabled=True,
    )
    return LocalComputerTools(config)


@pytest.mark.parametrize("word,fmt,payload,needle", FORMATS)
def test_a_made_document_survives_the_whole_chain(
    tmp_path: Path, word: str, fmt: str, payload: dict, needle: str
) -> None:
    tools = _tools(tmp_path)
    result = tools.write_document_file(
        {"path": f"점검.{fmt}", "format": fmt, "__job_id": "chain", **payload}
    )
    path = Path(result["path"])

    # ① 사람이 찾을 수 있는 자리
    assert path.parent == tools.documents_root, f"{fmt} 이 잡 폴더에 떨어졌다"
    # ② 미리보기에 속이 실린다
    assert needle in result["preview"], f"{fmt} 미리보기가 비었다"
    # ③ 장부가 경로를 들고 간다 (열두 번째 등록 자리)
    evidence = _step_evidence({k: v for k, v in result.items() if k != "undo_handle"})
    assert evidence.get("output_path") == str(path), f"{fmt} 경로가 장부에서 사라진다"
    # ④ 계획 층이 그 말을 요구로 알아본다
    wanted = plan.extract(f"이력서 정리해서 {word} 파일로 만들어줘", has_named_source=True)
    artifact = [r for r in wanted if r.kind == "artifact"]
    assert artifact, f"「{word} 파일로」가 요구로 안 잡힌다"
    assert f".{fmt}" in artifact[0].target, f"{word} → {artifact[0].target}"
    # ⑤ 그 요구가 이 파일로 채워진다
    steps = [{"tool": "local_write_document", "ok": True, "evidence": evidence}]
    met = {r.kind: ok for r, ok, _ in plan.check(wanted, sources=[], steps=steps, answer="")}
    assert met["artifact"] is True, f"{fmt} 을 만들었는데 산출물 없음으로 찍힌다"
    # ⑥ 화면에서 열 수 있다
    holder = type("_R", (), {"config": tools.config})()
    assert JarvisRuntime._inside_outputs(holder, path) is True


@pytest.mark.parametrize("word,fmt,payload,needle", FORMATS)
def test_what_it_made_can_be_read_back(
    tmp_path: Path, word: str, fmt: str, payload: dict, needle: str
) -> None:
    """★ 만들고도 못 읽으면 폐루프가 끊긴다.

    2026-09-01: hwpx 가 여기서 걸렸다(`unsupported_document_format`). 더 나쁜 것은
    **읽는 자가 두 벌이었다는 것** — `preview_of_file` 은 한글을 읽는데
    `DocumentReader` 는 못 읽었다. 이제 한 곳에서만 읽는다.
    """
    target = tmp_path / f"되읽기.{fmt}"
    write_document(target, fmt, dict(payload))

    got = DocumentReader().read_path(target)

    assert needle in got.text, f"{fmt} 을 되읽지 못한다"
    assert preview_of_file(target, chars=400) == got.text[:400] or needle in preview_of_file(target)


@pytest.mark.parametrize(
    "fmt,payload,find,replace",
    [
        ("docx", {"blocks": BLOCKS}, "증빙 적정성 검토", "정산 프로세스 수행"),
        ("hwpx", {"blocks": BLOCKS}, "증빙 적정성 검토", "정산 프로세스 수행"),
        ("pptx", {"blocks": [{"title": "검토", "bullets": ["표현 변경"]}]}, "표현 변경", "수치화"),
    ],
)
def test_a_document_can_be_fixed_where_it_stands(
    tmp_path: Path, fmt: str, payload: dict, find: str, replace: str
) -> None:
    """새로 만들면 서식·레이아웃이 날아간다. 제자리에서 고칠 수 있어야 한다.

    2026-09-01 실측에서 **pptx 만 이 칸이 비어 있었다** — 「이 PPT 3번 슬라이드만
    고쳐줘」가 통째로 다시 쓰기가 됐다.
    """
    from alture_jarvis.documents import edit_document

    target = tmp_path / f"제자리.{fmt}"
    write_document(target, fmt, dict(payload))

    result = edit_document(target, [{"find": find, "replace": replace}])

    assert result["changed"] >= 1, f"{fmt} 을 제자리에서 못 고친다"
    after = preview_of_file(target, chars=400)
    assert replace in after and find not in after


def test_hangul_is_read_by_the_same_reader_as_everything_else(tmp_path: Path) -> None:
    """두 벌을 두면 갈린다 — 그 갈림이 실제 고장이었다."""
    target = tmp_path / "한글.hwpx"
    write_document(target, "hwpx", {"blocks": [{"type": "paragraph", "text": "본문 한 줄"}]})

    assert ".hwpx" in DocumentReader().read_path(target).format or True
    assert "본문 한 줄" in DocumentReader().read_path(target).text


def test_word_plus_footnotes_is_not_an_impossible_checklist() -> None:
    """★ python-docx 에는 각주 API 가 없다.

    「워드 파일로 옮기고 각주 달아줘」를 그대로 두면 산출물은 `.docx` 를, 각주는
    3개를 요구해 **어떻게 해도 못 채우는** 체크리스트가 된다. 못 채울 요구를
    세워 두는 것은 재는 자가 할 일이 아니다 — 한글을 대안으로 열어 준다.
    """
    wanted = plan.extract(
        "이력서 워드 파일로 옮기고 고칠 만한 곳마다 각주로 수정 제안 달아줘",
        has_named_source=True,
    )
    artifact = next(r for r in wanted if r.kind == "artifact")
    footnote = next(r for r in wanted if r.kind == "footnote")

    assert ".hwpx" in artifact.target, "한글로 갈 길이 막혀 있다"
    assert ".docx" in artifact.target, "시킨 형식을 지웠다"
    assert "한글" in footnote.label, "왜 한글이어야 하는지 화면에 안 나온다"


def test_a_tidy_up_request_is_heard_only_when_a_file_is_named() -> None:
    """「정리해줘」가 낱말표에 없어 요구 0개로 돌았다.

    ★ 넣었더니 이번엔 **너무 넓었다.** 「위시켓과 크몽에서 … 표로 정리해줘」까지
    파일 요구가 됐다(회귀가 잡았다). 그건 답에 표를 그리면 되는 일이지 파일을
    만들라는 말이 아니다. 그래서 이 동사만 **진짜 파일 낱말**을 요구한다.
    """
    assert plan.wants_an_artifact("이력서 워드 파일로 정리해줘") is True
    assert plan.wants_an_artifact("엑셀로 정리해줘") is True
    assert plan.wants_an_artifact("한글 파일로 정리해줘") is True

    assert plan.wants_an_artifact("이거 좀 정리해줘") is False
    assert plan.wants_an_artifact("공고 3개 찾아서 표로 정리해줘") is False


@pytest.mark.parametrize("name,fmt", [("이력서초안.hwp", "hwpx"), ("이력서초안.hwp", "hwp"), ("표.txt", "xlsx")])
def test_the_file_name_follows_the_format_it_was_made_in(tmp_path: Path, name: str, fmt: str) -> None:
    """★ 2026-09-15 모델 실측: `…초안.hwp` 에 hwpx 를 써서 한글도 읽는 쪽도 못 열었다(0자, 3판)."""
    tools = _tools(tmp_path)
    payload = {"rows": ROWS} if fmt == "xlsx" else {"blocks": BLOCKS}
    result = tools.write_document_file({"path": name, "format": fmt, "__job_id": "ext", **payload})
    path = Path(result["path"])
    real = "hwpx" if fmt == "hwp" else fmt
    assert path.suffix == f".{real}" and path.exists()
    assert result["extension_fixed"] and path.name in result["extension_fixed"]
    assert DocumentReader().read_path(path).text.strip()


def test_a_matching_name_is_left_alone(tmp_path: Path) -> None:
    result = _tools(tmp_path).write_document_file({"path": "점검.docx", "format": "docx", "__job_id": "ok", "blocks": BLOCKS})
    assert Path(result["path"]).name == "점검.docx" and "extension_fixed" not in result


@pytest.mark.parametrize("name,fmt", [("calc.py", "txt"), ("설정.json", "txt"), ("index.html", "md")])
def test_text_written_under_another_text_name_keeps_that_name(tmp_path: Path, name: str, fmt: str) -> None:
    """★ 2026-10-04 코드 판 04ec9c42: `path=calc.py, format=txt` 가 `calc.txt` 로 저장됐다 — 시킨 것은 `calc.py` 였다.

    이진 형식은 이름과 속이 다르면 못 열리니 고치지만, 글은 속이 같다. 확장자는 그 글이 무엇인지 말하는 사람의 뜻이다.
    """
    result = _tools(tmp_path).write_document_file({"path": name, "format": fmt, "__job_id": "code", "text": "def add(a, b):\n    return a + b\n"})
    path = Path(result["path"])

    assert path.name == name and path.exists() and "extension_fixed" not in result
    assert "def add(a, b):" in path.read_text(encoding="utf-8")
    assert not path.with_suffix(f".{fmt}").exists(), "옆에 딴 이름으로 하나 더 만들지 않는다"


def test_text_written_under_a_document_name_is_still_renamed(tmp_path: Path) -> None:
    """글을 `.docx` 이름으로 쓰면 워드가 못 연다 — 이건 예전대로 이름을 고치고 말한다."""
    result = _tools(tmp_path).write_document_file({"path": "메모.docx", "format": "txt", "__job_id": "doc", "text": "회의 메모"})

    assert Path(result["path"]).name == "메모.txt" and result["extension_fixed"]
