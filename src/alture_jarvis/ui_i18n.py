"""화면 언어 — 백엔드가 **화면으로 내보내는 순간** 한국어를 영어로 바꾼다 (2026-10-02 영어판 2단계).

백엔드 안의 한국어 4,343곳 가운데 사람 눈에 닿는 것은 일부다. 나머지는 모델에게 하는 말(`[시스템]`)과 요청을 읽는
낱말표다. 그것들을 고치면 동작이 깨진다. 그래서 만드는 자리는 그대로 두고 **나가는 자리**(HTTP 응답·실시간 이벤트)에서 바꾼다.

- 저장은 한국어 그대로다 — 언어를 바꾸면 지난 기록도 바로 따라 바뀌고, 되돌리면 원래대로다.
- 고정 문장은 사전에서 찾는다. 숫자가 든 문장(f-string)은 사전의 틀(``{0}개 남음``)에 맞춰 바꾼다.
- 여러 줄이 섞인 글(모델의 영어 답 + 손자리의 한국어 안내 줄)은 줄마다 본다.
- 사전에 없는 문장은 그대로 둔다 — 빠진 번역이 화면을 깨지 않는다.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

LANGS = ("ko", "en")
_HANGUL = re.compile("[가-힣]")
_HOLE = re.compile(r"\{(\d+)\}")
_DICT_PATH = Path(__file__).with_name("ui_i18n_en.json")

# 뽑기 스크립트가 못 잡는 것 — 조각을 이어 붙인 문장·빈칸이 띄어쓰기 하나로만 나뉜 틀(「{0} {1}개」는 「웹 자료 3」을
# 「웹 / 자료 3」으로 끊는다). 사전을 다시 뽑아도 사라지지 않게 여기 둔다(2026-10-02 영어 실제 판 107f2da1 에서 샌 것).
_MANUAL = {
    # 16GB 급 첫 추천(2026-10-12) — `setup_profile.recommend` 의 까닭 줄.
    "그림 읽기를 끄고 그만큼 창을 넓혔습니다 — 붙인 사진과 그림으로 된 글은 읽지 못합니다. 모델 카드의 「그림 읽기」에서 바꿀 수 있습니다(그러면 창이 줄어듭니다).":
        "Picture reading is off and the context is larger instead — attached photos and text inside images cannot be read. "
        "You can change this under “Picture reading” on the model card (the context gets smaller).",
    "웹 자료 {0}개 이상 직접 열어 읽기": "Open and read at least {0} web sources directly",
    "로컬 자료 {0}개 이상 직접 열어 읽기": "Open and read at least {0} local files directly",
    "{0}개 읽음 · 답에 {1}개": "{0} read · {1} in the answer",
    "{0}개 읽음 · 파일 표에 {1}줄": "{0} read · {1} rows in the file",
    "{0}개 이상 직접 열어 읽기": "Open and read at least {0} items directly",
    "웹 자료 {0}개 이상 목록으로 담기": "List at least {0} web items",
    "로컬 자료 {0}개 이상 목록으로 담기": "List at least {0} local items",
    "{0}개 이상 목록으로 담기": "List at least {0} items",
    # 브라우저 위 딱지(2026-10-05) — `browser._show_visual` 이 영어 화면에서 바꾼다.
    "손자리 작업 중": "Sonjari is working",
    "‘{0}’ 위에 올림": "Hovering over ‘{0}’",
    "‘{0}’ 선택": "Selecting ‘{0}’",
    "‘{0}’ 고르기": "Picking ‘{0}’",
    "입력란 선택": "Selecting the input field",
    "항목 선택": "Selecting the item",
    # 도구 이름표(2026-10-05) — `agent._tool_label` 에 더한 것.
    "페이지 본문을 읽는 중": "Reading the page",
    "검색 결과를 여는 중": "Opening a result",
    "사이트 안에서 검색하는 중": "Searching within the site",
    "페이지에서 찾는 중": "Finding it on the page",
    "페이지의 링크를 모으는 중": "Collecting the links on the page",
    "목록을 더 불러오는 중": "Loading more of the list",
    "페이지의 자료를 읽는 중": "Reading the page's data",
    "화면을 찍는 중": "Taking a screenshot",
    "화면 요소에 마우스를 올리는 중": "Hovering over an element",
    "파일을 내려받는 중": "Downloading the file",
    "파일을 붙이는 중": "Attaching the file",
    "화면에서 결과를 확인하는 중": "Checking the result on the screen",
    "탭을 닫는 중": "Closing the tab",
    "확인 창을 처리하는 중": "Handling the dialog",
    "승인된 버튼을 누르는 중": "Clicking the approved button",
    "파일 내용에서 찾는 중": "Searching inside files",
    "이름으로 파일을 찾는 중": "Finding files by name",
    "코드에서 이름을 찾는 중": "Finding the symbol in the code",
    "명령을 실행하는 중": "Running the command",
    "미리보기를 띄우는 중": "Opening the preview",
    "폴더 접근을 요청하는 중": "Asking for access to the folder",
    "격리된 상자에서 코드를 돌리는 중": "Running code in the sandbox",
    "격리된 상자로 자료를 가져오는 중": "Fetching into the sandbox",
    "쓸 수 있는 작업 방법을 확인하는 중": "Checking the available skills",
    "작업 방법을 읽는 중": "Reading the skill",
    "Google Drive 파일을 읽는 중": "Reading the Google Drive file",
    # 모델 고르개에 뜨는 「글만 읽는」 이름(2026-10-12 · `model_setup.picker`).
    "{0} · 글만 읽기": "{0} · text only",
    # 지금 모델이 그림을 못 읽을 때 도구가 붙이는 말(2026-10-12 · `runtime.unseen_pictures_note`).
    "붙여 주신 그림 {0}장은 보지 못했습니다. 지금 쓰는 모델이 그림을 읽지 못합니다. 설정의 모델에서 그림을 읽는 모델을 고르면 볼 수 있습니다.":
        "I could not look at the {0} picture(s) you attached. The current model cannot read pictures. "
        "Choose a model that reads pictures under Settings › Model to have them read.",
    "그림 없이 답할 수 있는 내용이면 글로 적어 다시 물어봐 주세요.":
        "If this can be answered without the picture, please ask again in text.",
    "지금 쓰는 모델이 그림을 읽지 못해 카메라 화면을 볼 수 없습니다. 설정의 모델에서 그림을 읽는 모델을 고르면 볼 수 있습니다.":
        "The current model cannot read pictures, so I cannot look at the camera. "
        "Choose a model that reads pictures under Settings › Model.",
}
# 이름표가 없는 도구는 「도구이름 실행 중」으로 나간다. 틀(「{0} 실행 중」)로 두면 「…가 실행 중」으로 끝나는 아무 글이나
# 먹으므로, 도구 이름 꼴(영문 소문자·숫자·밑줄)일 때만 바꾼다.
_TOOL_RUNNING = re.compile(r"^([a-z][a-z0-9_]*) 실행 중$")
# 사용자 글 칸이라도 우리가 붙인 말머리만은 바꾼다.
_PREFIXES = {"바깥 AI 가 맡긴 일 · ": "Handed off by another AI · "}

_lock = threading.Lock()
_lang = "ko"
_state_path: Path | None = None
_exact: dict[str, str] | None = None
_templates: list[tuple[re.Pattern[str], str, tuple[str, ...]]] = []


def configure(state_path: Path) -> None:
    """저장해 둔 화면 언어를 읽는다. 없으면 한국어(예전과 같다)."""
    global _state_path, _lang
    _state_path = state_path
    try:
        value = json.loads(state_path.read_text(encoding="utf-8")).get("lang")
    except (OSError, ValueError, AttributeError):
        value = None
    _lang = value if value in LANGS else "ko"


def lang() -> str:
    return _lang


def set_lang(value: str) -> str:
    global _lang
    if value not in LANGS:
        raise ValueError(f"unknown_lang:{value}")
    _lang = value
    if _state_path is not None:
        try:
            _state_path.parent.mkdir(parents=True, exist_ok=True)
            _state_path.write_text(json.dumps({"lang": value}), encoding="utf-8")
        except OSError:
            pass  # 저장 못 해도 이번 실행은 바뀐다
    return _lang


def _load() -> None:
    global _exact, _templates
    with _lock:
        if _exact is not None:
            return
        try:
            raw = json.loads(_DICT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        raw = {**raw, **_MANUAL}
        exact: dict[str, str] = {}
        templates: list[tuple[re.Pattern[str], str, tuple[str, ...]]] = []
        for ko, en in raw.items():
            if not isinstance(ko, str) or not isinstance(en, str) or not en:
                continue
            holes = [int(n) for n in _HOLE.findall(ko)]
            if not holes:
                exact[ko] = en
                continue
            pattern = "".join(
                f"(?P<h{part}>.+?)" if index % 2 else re.escape(part)
                for index, part in enumerate(_HOLE.split(ko))
            )
            # 고정 글자 조각 — 이게 다 들어 있는 줄에만 정규식을 돌린다(틀 수백 개를 줄마다 다 돌리지 않게).
            pieces = tuple(sorted((part for index, part in enumerate(_HOLE.split(ko)) if not index % 2 and part.strip()),
                                  key=len, reverse=True))
            try:
                templates.append((re.compile(f"^{pattern}$", re.S), en, pieces))
            except re.error:
                continue
        # 고정 글자가 긴 틀부터 — 짧은 틀(「{0}개」)이 긴 문장을 먼저 먹지 않게. 같으면 빈칸이 적은 틀부터.
        # ★ 2026-10-03: 전에는 정규식 길이로 쟀다 — 빈칸 자리(`(?P<h0>.+?)`)도 글자로 쳐서 빈칸 둘짜리
        #   「{0} {1}개 이상 직접 열어 읽기」가 「웹 자료 {0}개 이상 직접 열어 읽기」를 앞질러 영어 계획 이름표가
        #   「Open and read at least 자료 3 웹 directly」로 나갔다.
        templates.sort(key=lambda row: (-sum(len(piece) for piece in row[2]), row[0].groups))
        _exact, _templates = exact, templates


def reload() -> None:
    """시험·사전 갱신용 — 다음 번역 때 사전을 다시 읽는다."""
    global _exact
    with _lock:
        _exact = None


def _one(text: str) -> str | None:
    """한 덩어리(줄)를 바꾼다. 사전에 없으면 None."""
    assert _exact is not None
    hit = _exact.get(text)
    if hit is not None:
        return hit
    running = _TOOL_RUNNING.match(text)
    if running:
        return f"Running {running.group(1)}"
    for pattern, en, pieces in _templates:
        if not all(piece in text for piece in pieces):
            continue
        match = pattern.match(text)
        if match:
            out = en
            for name, value in match.groupdict().items():
                out = out.replace("{" + name[1:] + "}", translate_text(value))
            return out
    return None


def translate_text(text: str) -> str:
    """한국어가 든 글을 영어로. 통째로 → 줄마다 → 앞뒤 공백·글머리를 뗀 줄 순서로 찾는다."""
    if not text or not _HANGUL.search(text):
        return text
    _load()
    whole = _one(text)
    if whole is not None:
        return whole
    if "\n" not in text:
        stripped = text.strip()
        if stripped != text and stripped:
            inner = _one(stripped)
            if inner is not None:
                return text.replace(stripped, inner, 1)
        # 사전에 없는 대조표 글(칸 이름·본 것)은 계획 층의 영어판으로 — 바깥 AI 로 가는 길과 같은 말을 쓴다.
        from .plan import english_for_screen  # 늦게 가져온다(계획 층도 이 모듈을 늦게 가져온다)

        known = english_for_screen(stripped) if stripped else None
        if known is not None:
            return text.replace(stripped, known, 1)
        return text
    return "\n".join(translate_text(line) for line in text.split("\n"))


# 사용자가 직접 쓴 글·파일 내용은 바꾸지 않는다 — 우연히 사전 문장과 같아도 그건 사용자의 글이다.
#   설정의 값(`value`·`choices`)은 화면이 「저장」할 때 그대로 되돌아온다 — 바꾸면 영어가 실제 설정으로 들어간다.
_KEEP_KEYS = frozenset({"prompt", "display_prompt", "model_prompt", "query", "path", "url", "file", "files",
                        "source", "sources", "content_raw", "raw", "html", "code", "diff",
                        "value", "values", "choices", "default", "tag", "model", "session_id",
                        # 사람이 지은 이름 — 모델 별명 · 디스코드 봇 · 채널 (2026-10-18). 바꾸면 그대로 저장돼 돌아온다.
                        "alias", "default_model_alias", "pc_model", "bot_name", "home_channel_name"})


def translate_payload(value: Any, *, _key: str = "") -> Any:
    if _lang != "en":
        return value
    if isinstance(value, str):
        if _key in _KEEP_KEYS:
            for ko, en in _PREFIXES.items():
                if value.startswith(ko):
                    return en + value[len(ko):]
            return value
        return translate_text(value)
    if isinstance(value, list):
        return [translate_payload(item, _key=_key) for item in value]
    if isinstance(value, dict):
        return {key: translate_payload(item, _key=str(key)) for key, item in value.items()}
    return value
