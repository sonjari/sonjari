"""파일을 쓴 **뒤에** 새로 읽은 페이지가 있으면 골라낸다 (2026-10-14)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# 그 이름만 쓰기로 둔다 — 그 외 이름은 쓰기가 아니다.
WRITE_TOOLS = {
    "local_write_document",
    "local_write_file",
    "local_edit_document",
    "local_edit_spreadsheet",
}

# 그 이름만 읽기로 둔다 — 그 외 이름은 읽기가 아니다.
READ_TOOLS = {"browser_extract", "browser_read"}


def _address(evidence: dict[str, Any]) -> str:
    # 빈 주소 · about:blank · file: 로 시작하는 주소는 세지 않는다.
    url = str(evidence.get("url") or "").strip()
    if not url or url == "about:blank" or url.startswith("file:"):
        return ""
    # 이 PC 안의 미리보기(localhost)는 자료가 아니라 자기가 만든 것을 확인한 것이다 — 운영 기록에서 웹페이지 · 코드를
    # 만드는 판이 「쓰고 → 미리보기로 열어 읽기」라 걸렸다(2026-10-14 · 49판 중 그 무리).
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.endswith(".localhost"):
        return ""
    return url.split("#", 1)[0]


def reads_after_last_write(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    # 성공한(`ok` 가 참) 걸음만 센다.
    last_write = -1
    for i, step in enumerate(steps):
        if step.get("ok") and step.get("tool") in WRITE_TOOLS:
            last_write = i

    if last_write == -1:
        return None

    # 그 쓰기 **앞**에 성공한 읽기로 이미 읽은 주소(# 뒤를 떼고).
    seen_before = set()
    for step in steps[:last_write]:
        if step.get("ok") and step.get("tool") in READ_TOOLS:
            address = _address(step.get("evidence") or {})
            if address:
                seen_before.add(address)

    # 마지막 쓰기 **뒤**에 성공한 읽기의 주소 — 처음 읽은 순서, 겹침 없음.
    new_reads: list[str] = []
    seen_after = set()
    for step in steps[last_write + 1 :]:
        if not (step.get("ok") and step.get("tool") in READ_TOOLS):
            continue
        address = _address(step.get("evidence") or {})
        if not address or address in seen_before or address in seen_after:
            continue
        seen_after.add(address)
        new_reads.append(address)

    if not new_reads:
        return None

    # `path` 는 `evidence["output_path"]` 가 있으면 그것, 없으면 `arguments["path"]`.
    write_step = steps[last_write]
    evidence = write_step.get("evidence") or {}
    arguments = write_step.get("arguments") or {}
    path = evidence.get("output_path") or arguments.get("path")

    return {"path": path, "write_index": last_write, "new_reads": new_reads}


def rewrite_note(found: dict[str, Any], language: str = "ko") -> str:
    """끝내려는 모델에게 한 번 건네는 말 — 쓴 파일과 그 뒤에 새로 읽은 주소를 대고, 빠졌으면 다시 쓰라고 한다.

    막지 않는다. 이미 넣었으면(예: 목록에서 본 값과 상세가 같았으면) 그대로 끝내도 된다고 같이 말한다.
    """
    path = str(found.get("path") or "")
    reads = [str(url) for url in found.get("new_reads") or []][:5]
    listed = "\n".join(f"- {url}" for url in reads)
    if language == "en":
        return (
            f"[System] You wrote {path} and then read these pages after it:\n{listed}\n"
            "If what you read there is not in the file yet, write the same file again with local_write_document "
            "so the file matches what you read. If it is already in the file, you may finish as is."
        )
    return (
        f"[시스템] {path} 를 쓴 **뒤에** 이 페이지를 새로 읽었다:\n{listed}\n"
        "거기서 읽은 내용이 파일에 아직 없으면 local_write_document 로 같은 파일을 다시 써서 읽은 것과 맞춰라. "
        "이미 들어가 있으면 그대로 끝내도 된다."
    )
