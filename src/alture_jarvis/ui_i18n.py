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
    # 바깥 AI(MCP) 연결이 영어로 내보낼 때 사전에 없던 것 (2026-10-19 · 운영 맡기기 판 1,481개를 영어로 요약해 본 나머지).
    #   `mcp_server._english` 가 「 · 」 조각 · 이어 붙은 문장 단위로 찾는다.
    "바깥 AI": "the outside AI",
    "{0}개 읽음": "{0} read",
    "답에 {0}개": "{0} in the answer",
    "파일 표에 {0}줄": "{0} rows in the file",
    "{0} 에게 보냄": "Sent to {0}",
    "필요한 것 {0}/{1}": "needs {0}/{1}",
    # 확인 못 한 항목이 있을 때의 영수증 조각 (2026-10-19 · `outbound.receipt`) — 분수 대신 셋을 따로 센다.
    "필요한 것 {0}개": "{0} needs",
    "채움 {0}": "filled {0}",
    "비어 있음 {0}": "empty {0}",
    "확인 못 함 {0}": "not checked {0}",
    "이름이 붙은 칸 · 제목을 찾지 못해 확인하지 못한 항목: {0} — 비어 있다는 뜻이 아닙니다. 답 본문에서 직접 확인하세요.":
        "Items that could not be checked because no column or heading with that name was found: {0} — this does not "
        "mean they are empty. Read the answer itself to check them.",
    "정제 {0}": "masked {0}",
    "답 항목 중 읽은 원문에 없는 이름 있음": "some names in the answer are not in the pages read",
    "{0} (목록 화면 {1}곳은 세지 않음)": "{0} ({1} list pages not counted)",
    "정렬·필터 안 씀 — 검색어 결과만 봄": "Did not use sort or filters — only looked at the search results",
    "가지의 변경은 아직 원래 폴더에 없습니다 — branch.take_home 의 명령으로 본 뒤 가져가세요.":
        "The branch's changes are not in the original folder yet — review them with the commands in branch.take_home, then take them.",
    "가지에 바뀐 파일이 없습니다.": "No files changed on the branch.",
    "확인 명령이 통과하지 않은 채 끝났습니다 — 가지의 변경은 미완성입니다. 가져가기 전에 직접 돌려 보세요.":
        "It ended without the check command passing — the branch's changes are unfinished. Run it yourself before taking them.",
    "돌려받아야 할 것 중 비어 있는 항목: {0} — 이 항목 없이 끝낼 수 있는지, 다시 맡길지 정하세요.":
        "Items you asked for that are still empty: {0} — decide whether you can finish without them or hand the task off again.",
    "답에서 가린 것이 있습니다({0}). 연락처가 꼭 필요하면 needs 에 밝혀 다시 맡기세요 — 주민번호 · 카드 번호 · 비밀 키는 내보내지 않습니다.":
        "Some things in the answer were masked ({0}). If you really need contact details, name them in needs and hand it "
        "off again — national ID numbers, card numbers and secret keys are never returned.",
    "전화번호": "phone number",
    "메일 주소": "email address",
    "같은 확인 실패가 되풀이돼 멈췄습니다 — 그대로 다시 맡기면 같은 자리에서 멈춥니다. 마지막 실패 출력을 보고 과제를 더 작게 쪼개거나, 걸린 곳을 직접 고친 뒤 나머지를 맡기세요.":
        "Stopped because the same check failure kept repeating — handing it off again unchanged stops at the same place. "
        "Look at the last failure output and split the task smaller, or fix the stuck part yourself and hand off the rest.",
    "같은 파일을 돌려 보지 않고 거듭 다시 쓰다 멈췄습니다 — 이 일은 지금 모델에 큽니다. 파일 하나·함수 하나 크기로 쪼개 맡기세요.":
        "Stopped after rewriting the same file again and again without running it — this job is too big for the current "
        "model. Hand it off in one-file or one-function pieces.",
    "한동안 새로 본 것도 고친 것도 돌려 본 것도 없어 멈췄습니다 — 과제에 고칠 자리(파일·함수 이름)를 적어 다시 맡기세요.":
        "Stopped because for a while nothing new was looked at, changed or run — hand it off again with the place to fix "
        "(file and function names) in the task.",
    "걸음 수 안전망에 닿아 멈췄습니다 — 한 번에 맡기기엔 큰 일입니다. 나눠서 맡기세요.":
        "Stopped at the step safety limit — this is too big to hand off in one go. Split it up.",
    "손자리가 센 것으로는 시킨 개수만큼 본문을 열어 읽지 않았습니다(답 끝의 경고에 몇 개인지 있습니다).":
        "By Sonjari's own count, it did not open and read as many pages as asked (the warning at the end of the answer says how many).",
    "이 판에서는 파일을 고치지 않았고 실행 확인도 하지 않았습니다 — 답은 설명입니다.":
        "This run did not change any files and did not run anything to check — the answer is an explanation.",
    "코드는 고쳤지만 검증(테스트·실행 확인)을 돌리지 못한 채 끝났습니다 — files 는 검증되지 않은 결과입니다. 열어서 확인하거나 검증만 다시 맡기세요.":
        "The code was changed but it ended without running the checks (tests or a run) — files are unverified results. "
        "Open them to check, or hand off just the checking.",
    "파일은 만들었지만 **검증(테스트·실행 확인)을 끝내지 못해** 멈췄습니다. files 는 검증되지 않은 결과입니다 — 열어서 확인하거나, 검증만 다시 맡기세요.":
        "Files were made but it stopped **without finishing the checks (tests or a run)**. files are unverified results — "
        "open them to check, or hand off just the checking.",
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
        # 「 · 」로 이어 붙인 한 줄(「Claude Code 에게 보냄 · 정제 0」 · 「3개 읽음 · 답에 2개 · …」)은 조각마다 (2026-10-19).
        #   틀의 빈칸 안에서도 이 길을 탄다 — 「… (지금: {0})」의 {0} 가 이어 붙인 조각이다.
        if " · " in stripped:
            parts = stripped.split(" · ")
            moved = [translate_text(part) for part in parts]
            # 조각이 **다** 바뀌었을 때만 — 반만 바뀐 한국어 · 영어 섞인 줄은 원문보다 나쁘다(모델의 한국어 답 줄 등).
            if moved != parts and not any(_HANGUL.search(part) for part in moved):
                return text.replace(stripped, " · ".join(moved), 1)
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
                        "alias", "default_model_alias", "pc_model", "bot_name", "home_channel_name",
                        # 「나에 대한 지침」(2026-10-18) — 파일 원문 · 카드가 만든 줄 · 카드 답. 사용자의 글이라 그대로 오가야 한다.
                        "content_raw", "card_lines", "user_label", "work_text", "avoid_text", "sites"})


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
