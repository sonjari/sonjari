"""상자가 만든 **결과물**은 사람이 찾을 수 있어야 한다.

★ 2026-09-01 라이브 사고. 「나래 이력서 정리해 줘」에 자비스는
`local_write_document` 가 아니라 `sandbox_run` 으로 python-docx 를 직접 돌렸다.
어제 붙인 자리·미리보기·띄우기는 전부 `local_write_document` 쪽에만 있었으므로
셋 다 안 먹었고, 파일은

    outputs/workspace/e30e5408-e95e-4bd7-9699-d073b3e6c7b6/나래_이력서_수정제안본.docx

에 떨어졌다. 사용자님은 "미리보기도 안되고 아무것도 안되는데"를 봤다.

이 저장소가 여섯 번 겪은 병이다 — **도구를 만들어도 갈래가 없으면 다른 길로 샌다.**
그래서 결과물의 대접을 **만든 도구**에 붙이면 또 샌다. 상자에서 호스트로 건너오는
문(`fetch`)에 붙였고, 이 검사가 그 문을 지킨다.
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.sandbox import SandboxBox


def _parts(tmp_path: Path) -> tuple[LocalComputerTools, SandboxBox]:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "내문서" / "JARVIS",
        local_computer_enabled=True,
        sandbox_enabled=True,
    )
    local = LocalComputerTools(config)
    return local, SandboxBox(config, local_computer=local)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    """진짜 docx 를 만든다. 가짜 바이트로는 미리보기가 되는지 알 수 없다."""
    from docx import Document

    document = Document()
    for line in paragraphs:
        document.add_paragraph(line)
    blob = tmp = Path(__file__).parent / "_tmp_deliverable.docx"
    document.save(str(tmp))
    blob = tmp.read_bytes()
    tmp.unlink()
    return blob


def test_a_document_from_the_sandbox_lands_where_a_person_can_find_it(
    tmp_path: Path, monkeypatch
) -> None:
    local, box = _parts(tmp_path)
    blob = b"docx-bytes"
    monkeypatch.setattr(
        box, "_exec", lambda script, timeout: (0, base64.b64encode(blob).decode("ascii"), "")
    )

    result = box.fetch({"run_id": "abc123", "name": "나래_이력서.docx", "__job_id": "job-1"})

    assert result["ok"] is True
    assert result["deliverable"] is True
    # 잡별 UUID 폴더가 **아니다.**
    assert Path(result["path"]).parent == local.documents_root
    assert "workspace" not in result["path"]
    assert Path(result["path"]).read_bytes() == blob


def test_scratch_files_still_stay_in_the_job_workspace(tmp_path: Path, monkeypatch) -> None:
    """중간 산출물까지 「내 문서」로 보내면 그 폴더가 쓰레기통이 된다."""
    local, box = _parts(tmp_path)
    monkeypatch.setattr(
        box, "_exec", lambda script, timeout: (0, base64.b64encode(b"{}").decode("ascii"), "")
    )

    result = box.fetch({"run_id": "abc123", "name": "중간계산.json", "__job_id": "job-2"})

    assert result.get("deliverable") is False
    assert Path(result["path"]).parent == local.job_workspace("job-2")


def test_the_answer_carries_the_content_not_just_a_path(tmp_path: Path, monkeypatch) -> None:
    """미리보기가 실려야 사람이 **열기 전에** 제대로 들어갔는지 안다."""
    local, box = _parts(tmp_path)
    blob = _docx_bytes(["이력서 수정 제안본", "연구비 관리 3년차 · 42억 규모 예산 집행"])
    monkeypatch.setattr(
        box, "_exec", lambda script, timeout: (0, base64.b64encode(blob).decode("ascii"), "")
    )
    monkeypatch.setattr(box, "_list_outputs", lambda work: [{"name": "제안본.docx", "bytes": len(blob)}])
    opened: list[str] = []
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda path: opened.append(path))

    saved = box.run({"code": "print(1)", "__job_id": "job-3"})["saved_to"]

    assert len(saved) == 1
    assert "42억 규모 예산 집행" in saved[0]["preview"]
    # ★ 띄우기는 **판 끝**이다. 만드는 도중에 띄우면 한글·엑셀이 파일을 붙잡아
    #   다음 걸음이 죽는다(`local_write_document` 에서 겪은 그대로).
    assert saved[0]["opened"] == "deferred"
    assert opened == [], "만드는 도중에 띄웠다"

    assert local.open_pending("job-3") == "opened"
    assert opened == [saved[0]["path"]]


def test_hwpx_previews_too(tmp_path: Path) -> None:
    """국내에서 제일 자주 나올 형식인데 `DocumentReader` 의 표에 없었다."""
    from alture_jarvis.sandbox import _preview_of_file

    target = tmp_path / "제안서.hwpx"
    with zipfile.ZipFile(target, "w") as bundle:
        bundle.writestr(
            "Contents/section0.xml",
            '<?xml version="1.0"?><s><p><t>한글 문서 본문이다</t></p></s>',
        )

    assert "한글 문서 본문이다" in _preview_of_file(target)


def test_a_broken_file_does_not_turn_making_into_a_failure(tmp_path: Path) -> None:
    from alture_jarvis.sandbox import _preview_of_file

    broken = tmp_path / "깨진.docx"
    broken.write_bytes(b"not really a docx")

    assert _preview_of_file(broken) == ""


def test_the_two_places_that_name_the_documents_folder_agree(tmp_path: Path) -> None:
    """자리를 두 곳에 적으면 갈린다 — 하루에 네 번 겪은 그 모양이다."""
    from alture_jarvis.runtime import JarvisRuntime

    local, _ = _parts(tmp_path)
    made = local.documents_root / "결과물.docx"
    made.parent.mkdir(parents=True, exist_ok=True)
    made.write_bytes(b"x")

    assert JarvisRuntime._inside_outputs(
        type("_C", (), {"config": local.config})(), made
    ) is True


def test_the_screen_can_read_a_document_it_only_has_a_path_for(tmp_path: Path) -> None:
    """화면 안 미리보기(`/v1/outputs/preview`) 는 **장부와 폴더를 둘 다** 본다.

    바이트를 주는 `/v1/outputs/file` 과 같은 검사를 쓴다 — 새 통로를 여는 것이지
    새 권한을 여는 것이 아니다.
    """
    from alture_jarvis.runtime import JarvisRuntime

    local, _ = _parts(tmp_path)
    made = local.documents_root / "제안본.docx"
    made.parent.mkdir(parents=True, exist_ok=True)
    made.write_bytes(_docx_bytes(["연구비 관리 3년차"]))

    holder = type(
        "_R",
        (),
        {
            "config": local.config,
            "job_output_file": lambda self, job_id, path: made,
            "job_output_preview": JarvisRuntime.job_output_preview,
        },
    )()

    got = holder.job_output_preview("job-9", str(made))

    assert got["readable"] is True
    assert "연구비 관리 3년차" in got["text"]
    assert got["format"] == "docx"


def test_preview_says_so_when_it_cannot_read(tmp_path: Path) -> None:
    """빈 값 하나가 두 가지를 뜻하면 조용히 고장난다 — "못 읽었다"를 말한다."""
    from alture_jarvis.runtime import JarvisRuntime

    local, _ = _parts(tmp_path)
    broken = local.documents_root / "깨진.docx"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"not a docx")
    holder = type(
        "_R",
        (),
        {
            "config": local.config,
            "job_output_file": lambda self, job_id, path: broken,
            "job_output_preview": JarvisRuntime.job_output_preview,
        },
    )()

    got = holder.job_output_preview("job-9", str(broken))

    assert got["readable"] is False
    assert got["text"] == ""


def test_preview_is_built_in_one_place_only() -> None:
    """두 곳에 적으면 갈린다 — 화면과 도구 결과가 같은 글을 보여야 한다."""
    import inspect

    from alture_jarvis import runtime, sandbox

    assert "preview_of_file" in inspect.getsource(sandbox._preview_of_file)
    assert "preview_of_file" in inspect.getsource(runtime.JarvisRuntime.job_output_preview)
