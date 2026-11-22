"""답에 적힌 산출물 경로가 실제로 있나 — 없는 경로를 「만들었다」고 말하지 않게 (2026-11-17 맥 새 계정 시험).

## 무슨 일이 있었나

「방금 정리한 걸 한글(hwp) 파일로도 만들어 줘」 — 길은 맞게 갔다(router=artifact). 4B 가 도구를 0걸음 쓰고 글로 답했고,
되밀기 한 번에도 또 글로 답했다. 계획은 「실제 산출물 파일 만들기 · 못 함 · 열 수 있는 산출물 없음」을 **알았는데**
답 뒤 검사 묶음이 `"" if not steps` 로 통째로 건너뛰어져, 「한글(hwp) 파일로 정리했습니다 · 저장 경로
`/Users/sonjari/Documents/Sonjari/경제_기사_3개.hwp`」가 그대로 나갔다. 그 계정 이름은 `sonjaritest` — 있을 수 없는 경로였다.

## 규칙(결정론 · 말투를 보지 않는다)

답에서 **확장자 있는 절대 경로**(맥 `/Users/…` 등 · `~/…` · 윈도우 `C:\\…`)를 뽑아, 이 판에서 쓴 파일이거나 디스크에 실제로
있으면 통과. 아니면 「없는 경로」다. 없는 경로가 있는 줄은 지우고 맨 위에 한 줄을 붙인다 — 쓰기가 한 번도 성공하지 않았으면
「파일을 만들지 못했습니다」, 아니면 「없는 경로를 지웠습니다」. 웹 주소 · 상대 경로 · 확장자 없는 폴더는 건드리지 않는다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

# 산출물로 나올 만한 확장자만 본다 — `.com` · `.kr` 같은 주소 끝, `.app` 같은 앱 묶음은 대상이 아니다.
_OUTPUT_EXTS = {
    "docx", "doc", "hwp", "hwpx", "xlsx", "xls", "csv", "pptx", "ppt", "pdf", "md", "txt", "html", "json",
    "png", "jpg", "jpeg", "gif", "webp", "svg", "mp4", "mov", "mp3", "wav", "zip",
    "py", "js", "ts", "tsx", "rs", "java", "c", "cpp", "go", "sh", "ps1",
    "glb", "stl", "3mf", "obj", "fbx", "blend",
}

_POSIX_ROOTS = r"(?:~|/(?:Users|Volumes|home|tmp|private|var|opt|mnt|srv))"
_PATH_CHARS = r"[^\s`'\"<>|*?()\[\]{}，。、]"
# 확장자는 영문 · 숫자만 — 「…/a.hwp에 저장」처럼 한글 조사가 바로 붙어도 `a.hwp` 까지만 잡는다. 욕심껏 길게(폴더 이름의 점은 건너뜀).
_POSIX = re.compile(rf"(?<![\w:/.]){_POSIX_ROOTS}/{_PATH_CHARS}+\.([A-Za-z0-9]{{1,5}})(?![A-Za-z0-9.])")
_WINDOWS = re.compile(rf"(?<![\w])[A-Za-z]:\\{_PATH_CHARS}+\.([A-Za-z0-9]{{1,5}})(?![A-Za-z0-9.])")
_TICKED = re.compile(r"`([^`\n]+)`")
_WHOLE_TICKED = re.compile(rf"(?:{_POSIX_ROOTS}/|[A-Za-z]:\\)[^`\n<>|*?\"]+\.[A-Za-z0-9]{{1,5}}")

# 파일을 실제로 쓰는 도구(성공한 것만 센다). 셸은 무엇을 썼는지 모르므로 디스크 확인에 맡긴다.
_WRITE_TOOLS = {
    "local_write_file", "local_write_document", "local_apply_edit", "local_write_sheet", "local_write_slides",
    "local_save_image", "local_copy_file", "local_move_file", "sandbox_write_file", "gen_3d", "genvideo_render",
}


def _claims(answer: str) -> list[str]:
    """답에서 산출물 경로처럼 보이는 것들(나온 순서 · 겹침 없이)."""
    found: list[str] = []
    candidates: list[str] = []
    for match in _TICKED.finditer(answer):
        inner = match.group(1).strip()
        # `…/Application Support/…/a.docx` 처럼 띄어쓰기가 든 경로는 따옴표 안 통째로가 경로다.
        if _WHOLE_TICKED.fullmatch(inner) and inner.rsplit(".", 1)[-1].lower() in _OUTPUT_EXTS and inner not in found:
            found.append(inner)
            continue
        candidates.append(inner)
    candidates.append(answer)
    for text in candidates:
        for pattern in (_POSIX, _WINDOWS):
            for match in pattern.finditer(text):
                path = match.group(0).rstrip(".,;:)」』")
                ext = path.rsplit(".", 1)[-1].lower()
                # `C:\Users\...\report.txt` 같은 예시 경로(줄임표)는 주장이 아니다.
                if "..." in path or "…" in path:
                    continue
                if ext in _OUTPUT_EXTS and path not in found:
                    found.append(path)
    return found


def _written_paths(steps: Iterable[dict[str, Any]]) -> set[str]:
    written: set[str] = set()
    for step in steps or ():
        if not step.get("ok") or str(step.get("tool") or "") not in _WRITE_TOOLS:
            continue
        evidence = step.get("evidence") or {}
        arguments = step.get("arguments") or {}
        for value in (evidence.get("output_path"), evidence.get("path"), arguments.get("path"), arguments.get("output_path")):
            if value:
                written.add(_norm(str(value)))
    return written


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expanduser(path.strip())))


def wrote_any(steps: Iterable[dict[str, Any]]) -> bool:
    return any(step.get("ok") and str(step.get("tool") or "") in _WRITE_TOOLS for step in steps or ())


def false_paths(answer: str, steps: Iterable[dict[str, Any]], exists: Callable[[str], bool] | None = None) -> list[str]:
    """답에 적힌 산출물 경로 중 이 판에서 쓰지도 않았고 디스크에도 없는 것."""
    exists = exists or (lambda path: Path(os.path.expanduser(path)).exists())
    written = _written_paths(steps)
    missing: list[str] = []
    for path in _claims(answer or ""):
        if _norm(path) in written or exists(path):
            continue
        missing.append(path)
    return missing


def drop_false_paths(
    answer: str,
    steps: Iterable[dict[str, Any]],
    say: Callable[[str, str], str],
    exists: Callable[[str], bool] | None = None,
) -> tuple[str, list[str]]:
    """없는 경로가 있는 줄을 지우고 맨 위에 한 줄을 붙인다. (바뀐 답, 없는 경로들). 없으면 답 그대로."""
    steps = list(steps or ())
    missing = false_paths(answer, steps, exists)
    if not missing:
        return answer, []
    kept = [line for line in answer.splitlines() if not any(path in line for path in missing)]
    body = "\n".join(kept).strip()
    if not wrote_any(steps):
        head = say(
            f"⚠ 요청하신 파일을 만들지 못했습니다 — 파일을 쓰는 도구를 쓰지 않았고, 답에 적혀 있던 경로({len(missing)}곳)에는 파일이 없습니다. "
            "아래 내용은 파일이 아니라 글로만 드리는 것입니다. 「다시 해 줘」라고 하시면 실제로 만들어 봅니다.",
            f"⚠ The file you asked for was not created — no file-writing tool ran, and the path{'s' if len(missing) > 1 else ''} in the answer "
            f"({len(missing)}) do not exist. What follows is text only. Say \"try again\" and I'll actually make it.",
        )
    else:
        head = say(
            f"⚠ 답에 적혀 있던 경로 중 실제로 없는 {len(missing)}곳을 지웠습니다 — 만든 파일은 아래 「만든 것」에서 확인해 주세요.",
            f"⚠ Removed {len(missing)} path(s) from the answer that do not exist — check the files actually made below.",
        )
    return f"{head}\n\n{body}" if body else head, missing
