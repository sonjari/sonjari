"""콘티(JSON) 검사 — 굽기 전에 틀린 것을 거절하고, 걸리는 것은 표시만 한다 (2026-11-16 · 설계 §10-5 ② · §10-12).

콘티 꼴:

    {"title": "손자리 홍보", "aspect": "16:9",
     "cuts": [{"id": "c1", "kind": "gen", "prompt": "…", "seconds": 3, "candidates": 2, "seed": 11,
               "first_image": "D:/…/icon_first.png", "last_image": "D:/…/product_photo.png"},
              {"id": "c2", "kind": "code", "note": "앱 화면 · 글자 — HyperFrames 로"}]}

- `kind`: `gen`(생성 모델이 굽는다) · `code`(글자 · 로고 · 앱 화면 — HyperFrames/리모션) · `3d`(3D 팩 렌더). **굽는 것은 gen 뿐.**
- 길이는 2~5초(5B 실측은 3초 · 한 컷 한 동작). 프레임 수는 24fps 로 셈해 **8k+1**(LTX 는 8k+1 · Wan 은 4k+1 — 8k+1 은 둘 다 만족).
- 글자 · 로고 낌새가 보이면 막지 않고 `notes` 에 적는다(길은 클로드가 정한다 — 3D 팩 `gen_3d_check` 와 같은 결).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

FPS = 24
SECONDS_RANGE = (2.0, 5.0)
MAX_CANDIDATES = 4
#: 한 묶음에 굽는 후보 수 상한 — FastWan 컷당 약 40~60초(§10-8 · §10-9) × 16 ≈ 15분.
MAX_BATCH_RUNS = 16
MAX_PROMPT_CHARS = 1500
KINDS = ("gen", "code", "3d")
#: 화면비 → (가로, 세로). 32 의 배수. 16:9 는 실측한 832×480 그대로.
ASPECTS: dict[str, tuple[int, int]] = {"16:9": (832, 480), "9:16": (480, 832), "1:1": (640, 640)}
_ID = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
#: 프롬프트 안 글자 · 로고 낌새(영어 · 한국어). 막지 않고 표시만.
_TEXTY = re.compile(
    r"(\btext\b|\bwords?\b|\bletters?\b|\blogo\b|\bsubtitles?\b|\bcaption\b|\btypography\b|\bsign that (?:says|reads)\b|"
    r"\bsaying\b|\bwritten\b|[\"“”「」『』]|글자|글씨|로고|자막|문구|쓰여)", re.IGNORECASE)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class StoryboardError(ValueError):
    pass


def frames_for(seconds: float, fps: int = FPS) -> int:
    """초 → 프레임 수(8k+1). 3초 → 73(실측 판과 같음)."""
    k = max(1, round(float(seconds) * fps / 8))
    return 8 * k + 1



def _image_arg(item: dict[str, Any], key: str, cut_id: str, resolve: Any) -> Path | None:
    """컷의 그림 칸(first_image · last_image) — 파일 도구와 같은 검사 · 그림 확장자 · 있는 파일만."""
    raw = str(item.get(key) or "").strip()
    if not raw:
        return None
    path = resolve(raw) if resolve is not None else Path(raw)
    if path.suffix.lower() not in IMAGE_EXT:
        raise StoryboardError(f"{cut_id}: {key} 가 그림 파일이 아니다({', '.join(sorted(IMAGE_EXT))})")
    if not path.is_file():
        raise StoryboardError(f"{cut_id}: {key} 가 없다 — {path.name}")
    return path

def parse(raw: Any, *, resolve: Any = None) -> dict[str, Any]:
    """콘티를 검사해 정리한 꼴로 돌려준다. 틀리면 `StoryboardError`(무엇이 틀렸는지 한국어로).

    `resolve` 는 첫 그림 경로 검사(파일 도구와 같은 허락 범위) — 시험은 비워 둔다.
    """
    if not isinstance(raw, dict):
        raise StoryboardError("콘티는 JSON 객체여야 한다({title, aspect, cuts:[…]})")
    aspect = str(raw.get("aspect") or "16:9").strip()
    if aspect not in ASPECTS:
        raise StoryboardError(f"aspect 는 {list(ASPECTS)} 가운데 하나 — 받은 것: {aspect}")
    width, height = ASPECTS[aspect]
    cuts_in = raw.get("cuts")
    if not isinstance(cuts_in, list) or not cuts_in:
        raise StoryboardError("cuts 가 비었다 — 컷을 하나 이상 적는다")
    seen: set[str] = set()
    cuts: list[dict[str, Any]] = []
    notes: list[str] = []
    runs = 0
    for index, item in enumerate(cuts_in, start=1):
        if not isinstance(item, dict):
            raise StoryboardError(f"{index}번째 컷이 객체가 아니다")
        cut_id = str(item.get("id") or f"c{index}").strip()
        if not _ID.fullmatch(cut_id):
            raise StoryboardError(f"컷 id 「{cut_id}」 — 영문 · 숫자 · _ - 로 24자 안")
        if cut_id in seen:
            raise StoryboardError(f"컷 id 「{cut_id}」가 두 번 나온다")
        seen.add(cut_id)
        kind = str(item.get("kind") or "gen").strip().lower()
        if kind not in KINDS:
            raise StoryboardError(f"{cut_id}: kind 는 {list(KINDS)} 가운데 하나")
        try:
            seconds = float(item.get("seconds") or 3)
        except (TypeError, ValueError) as exc:
            raise StoryboardError(f"{cut_id}: seconds 가 숫자가 아니다") from exc
        if not SECONDS_RANGE[0] <= seconds <= SECONDS_RANGE[1]:
            raise StoryboardError(f"{cut_id}: 생성 컷 길이는 {SECONDS_RANGE[0]:g}~{SECONDS_RANGE[1]:g}초 — 길면 컷을 나눈다(한 컷 한 동작)"
                                  if kind == "gen" else f"{cut_id}: seconds 는 {SECONDS_RANGE[0]:g}~{SECONDS_RANGE[1]:g}")
        cut: dict[str, Any] = {"id": cut_id, "kind": kind, "seconds": seconds, "note": str(item.get("note") or "")[:400]}
        if kind == "gen":
            prompt = str(item.get("prompt") or "").strip()
            if not prompt:
                raise StoryboardError(f"{cut_id}: 생성 컷(gen)인데 prompt 가 비었다")
            if len(prompt) > MAX_PROMPT_CHARS:
                raise StoryboardError(f"{cut_id}: prompt 가 {MAX_PROMPT_CHARS}자를 넘는다")
            try:
                candidates = int(item.get("candidates") or 2)
            except (TypeError, ValueError) as exc:
                raise StoryboardError(f"{cut_id}: candidates 가 숫자가 아니다") from exc
            if not 1 <= candidates <= MAX_CANDIDATES:
                raise StoryboardError(f"{cut_id}: candidates 는 1~{MAX_CANDIDATES}")
            seed = item.get("seed")
            if seed not in (None, ""):
                try:
                    seed = int(seed)
                except (TypeError, ValueError) as exc:
                    raise StoryboardError(f"{cut_id}: seed 가 정수가 아니다") from exc
                if not 0 <= seed < 2**31:
                    raise StoryboardError(f"{cut_id}: seed 는 0 이상 2^31 미만")
            else:
                seed = None
            first_path = _image_arg(item, "first_image", cut_id, resolve)
            last_path = _image_arg(item, "last_image", cut_id, resolve)
            if last_path is not None:
                notes.append(f"{cut_id}: 끝 그림(last_image)은 LTX 로 구울 때만 쓴다 — FastWan 시안 · Wan 본판은 첫 그림까지만 받는다(gen_video_finish engine ltx)")
            if _TEXTY.search(prompt):
                notes.append(f"{cut_id}: 프롬프트에 글자 · 로고 낌새가 있다 — 생성 모델은 글씨를 뭉갠다(§10-5 ②). 글자는 code 컷으로 얹는 쪽이 낫다")
            runs += candidates
            cut.update({"prompt": prompt, "candidates": candidates, "seed": seed,
                        "first_image": str(first_path) if first_path else None,
                        "last_image": str(last_path) if last_path else None, "frames": frames_for(seconds)})
        cuts.append(cut)
    if runs == 0:
        raise StoryboardError("생성 컷(gen)이 하나도 없다 — 굽을 것이 없다(code · 3d 컷은 손자리가 굽지 않는다)")
    if runs > MAX_BATCH_RUNS:
        raise StoryboardError(f"한 묶음 후보 합이 {runs} — {MAX_BATCH_RUNS} 이하로(묶음을 나눈다)")
    return {"title": str(raw.get("title") or "")[:120], "aspect": aspect, "width": width, "height": height,
            "cuts": cuts, "runs": runs, "notes": notes}
