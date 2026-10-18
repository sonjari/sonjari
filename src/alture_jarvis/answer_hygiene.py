"""답글 말초 정리 — 모델이 낸 답에서 쓸데없는 것들을 걷어 내는 순수 함수들.

agent.py 에서 분리했다(2026-10-09). 이 함수들은 전부 입력 문자열(이나 걸음 목록)을
받아서 정리된 문자열(이나 보조선언)을 돌려준다. agent.py 의 다른 상태에 기대지
않는다 — 그래서 이 모듈을 **혼자** 불러와도 된다.

함수 목록:
- _code_text_tool_call — 코더가 본문에 낸 단일 JSON 호출을 네이티브 모양으로 복구
- _clipboard_overwrote_without_a_file — 클립보드가 덮어썼는데 파일은 없었는가
- _clipboard_texts — 걸음에서 실제로 clipboard_write 에 넘어갔던 글
- _tidy_small_model_habits — 숫자 띄어쓰기·끝 인사 걷기
- _strip_stray_chinese — 한자 토막 걷기 (stray_han.mend 대용)
- _strip_schema_labels — 도구 속 필드 이름 걷기
- _strip_schema_labels_in — 문서 쓰기 인자 안의 글자에 같은 관문
- _offered_link_to_open — 「가 줘」에 링크만 준 경우 열 주소 하나
- _with_document_title — 문서 맨 앞에 H1 제목 세우기
- _artifact_still_owed — 산출물을 시켰는데 아직 없고 만들어 본 적도 없는가
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse
from .stray_han import mend as _mend_stray_han

#: 답을 파일로 옮겨 줄 때 쓰는 도구. 하나뿐이라 사슬이 필요 없다.
_ARTIFACT_FALLBACK_TOOL = "local_write_document"

#: 답에 이만큼은 있어야 옮긴다. 한 줄짜리 답을 파일로 만들면 빈 문서가 된다.
_ARTIFACT_FALLBACK_MIN_CHARS = 200

#: 파일을 **만들려고 한 적이 있는** 도구. 시도했다가 실패한 것도 센다.
#: 글을 실제로 읽어 오는 손 — 「전부」 판에서 새 글 읽기를 진척으로 셀 때 본다.
_FRESH_READ_TOOLS = frozenset({"browser_read", "browser_extract", "browser_open_result", "browser_open"})

#: 산출물 단계의 손 — 진척 판정과 산출물 차례(`_focused_tool_definitions`)가 **같이** 쓴다.
_ARTIFACT_PROGRESS_TOOLS = frozenset({
    "local_write_document", "local_edit_document", "local_write_file",
    "local_edit_spreadsheet", "artifact_from_observations", "hwp_apply_edit",
    "hwp_apply_format", "hwp_export_pdf",
})

#: 산출물 차례에 **같이 남기는** 손 — 파일을 만드는 일의 일부이거나, 막혔을 때 물을 손이다 (2026-10-04 도구 전수조사 2-E).
#:   덧붙일 기존 파일 찾기·읽기 · 사람에게 묻기 · 허용 밖 폴더 요청 · 문서 양식 스킬 읽기 · 그래프·QR 계산(인터넷 없는 상자) ·
#:   화면 찍어 저장 · 열려 있는 한글 문서 사슬 · 코드 판의 고치기. **브라우저로 더 찾으러 가는 손은 없다** —
#:   차례를 좁힌 이유(2026-10-02 밤 9d6942f2: 페이지를 세 번 더 열어 엑셀을 못 씀)는 그대로 지킨다.
_ARTIFACT_STAGE_SUPPORT = frozenset({
    "local_read_document", "local_list_directory", "local_search_files",
    "ask_user", "local_request_path_access", "skill_read",
    "sandbox_run", "browser_screenshot", "local_apply_edit",
    "hwp_list_open", "hwp_read", "hwp_preview_edit", "hwp_preview_format",
    # ★ 프로그램 창을 조작해 파일을 만드는 일(한글 → PDF 저장 · 메모장 저장)은 창 손이 곧 파일 쓰는 손이다 (2026-10-17 화면 자동화 측정).
    #   파일 만들 차례가 걸리면 이 손들이 「이 차례가 아니다」로 막혀 저장 창 앞에서 멈출 자리였다.
    "windows_list_open_windows", "windows_focus_window", "windows_open_path", "windows_uia_snapshot",
    "windows_uia_preview", "windows_execute_preview", "windows_copy_from_window",
})

_ARTIFACT_WRITE_TOOLS = frozenset({
    "local_write_document", "local_write_file", "local_edit_document",
    "local_edit_spreadsheet", "artifact_from_observations", "sandbox_run",
})


#: 클립보드에 **두 번 이상** 올렸는데 파일을 한 번도 안 만들었으면, 앞서 올린 글은
#: 이미 지워졌다고 본다 — 클립보드는 자리가 하나뿐이라 다음 clipboard_write 가 오면
#: 앞 것이 흔적도 없이 사라진다. "산출물을 시켰다"는 계획 층 판정이 없어도(면접 답변
#: 처럼 대화체로 시킨 경우가 그렇다) 이 패턴만으로 되짚어 문서로 옮긴다.
#: (2026-09-22 실측: 면접 답변을 clipboard_write 로만 여러 번 올려 앞 답이 계속 사라졌다.)
def _clipboard_overwrote_without_a_file(steps: list[dict[str, Any]]) -> bool:
    clipboard_writes = sum(
        1 for step in steps
        if step.get("ok") and str(step.get("tool") or "") == "clipboard_write"
    )
    if clipboard_writes < 2:
        return False
    return not any(
        str(step.get("tool") or "") == _ARTIFACT_FALLBACK_TOOL for step in steps
    )


#: 이 판에서 clipboard_write 로 **실제로 넘어갔던 글**, 순서대로.
#:
#: `step["arguments"]` 는 도구를 부를 때 실제로 넘긴 인자다 — evidence 의 `preview` 는
#: 200자로 잘려 있어서 못 쓴다. 답이 그 글을 안 옮겨 적었어도 여기엔 온전히 남아 있다.
def _clipboard_texts(steps: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for step in steps:
        if not step.get("ok") or str(step.get("tool") or "") != "clipboard_write":
            continue
        text = str((step.get("arguments") or {}).get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


#: 한자(중국어) 범위 — 한글(`가-힯`)·가나는 안 건드린다. CJK 통합 한자·확장 A·호환 한자.
_CJK_HAN = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")

#: 이 길이 이하로 **짧게** 끼어든 한자 토막만 지운다. 사용자가 실제로 중국어 번역·
#: 인용을 시켰으면 그 답은 이보다 훨씬 긴 덩어리로 나온다 — 그건 안 건드린다.
_STRAY_CJK_MAX_RUN = 8


#: 루프 안내(「더 찾지 말고 지금 가진 것으로 답해라」)를 **사용자에게 복창한 한 줄**. 그 줄만 지운다.
_NUDGE_ECHO = re.compile(
    r"(?m)^[ \t]*[^\n]{0,20}(?:더\s*이상|더는)\s*(?:검색|조사|찾)[^\n]{0,30}(?:않고|말고|없이)[^\n]{0,20}"
    r"(?:지금\s*가진|가진\s*것|현재\s*(?:가진|정보))[^\n]{0,30}(?:답|말씀|알려)[^\n]{0,20}$\n?"
    # 「시스템 메시지에 따라 지금 가진 것으로 답변드립니다.」(같은 날 두 번째 표현)
    r"|^[ \t]*[^\n]{0,20}(?:시스템\s*(?:메시지|지시|안내)|지침)(?:에|의)?\s*따라[^\n]{0,60}$\n?"
)


#: 숫자와 한국어 단위 사이의 띄어쓰기(「3 개」→「3개」). 「3 대 1」 같은 대결 표기를 해치지 않게 「대」는 뺀다.
_KO_NUMBER_UNIT_SPACE = re.compile(r"(?<=\d)[ \t]+(?=(?:개|건|곳|권|명|원|만\s?원|억|년|월|일|시|분|초|호|층|번|위|등|점|장|편|회|주|살|세|개월|시간|주일)(?![가-힣]*\d))")
#: 끝에 붙는 인사 한 줄 — 「이 정보가 도움이 되셨나요?」.
_HELPFUL_TAIL = re.compile(
    r"\n+[ \t]*(?:이\s*(?:정보|답변|내용)(?:가|이)\s*)?(?:조금이나마\s*)?도움이\s*되(?:셨|었)(?:나요|기를\s*바랍니다|길\s*바랍니다|으면\s*좋겠습니다)[?.!~ ]*\s*$"
)


def _tidy_small_model_habits(text: str) -> str:
    """코드 블록 밖에서만 고친다 — 코드 안의 공백은 뜻이다."""
    parts = re.split(r"(```.*?```)", text or "", flags=re.S)
    tidy = [part if part.startswith("```") else _KO_NUMBER_UNIT_SPACE.sub("", part) for part in parts]
    return _HELPFUL_TAIL.sub("", "".join(tidy)).rstrip()


def _strip_stray_chinese(text: str) -> tuple[str, list[str]]:
    """드물게 단어 하나에 섞여 나오는 간체 토막을 지운다 (2026-09-23, 사장님 실사용 보고).

    ## 왜

    Qwen 계열은 중국어·영어 위주로 훈련돼서, 낮은 확률로 한자 토큰이 한글 문장
    한가운데 섞여 나오는 게 알려진 특성이다(예: "이건 정확한 방법입니다设置인데요").
    샘플링 쪽(`ollama.py` 의 `min_p`)에서 그 확률을 낮춰도 완전히는 안 막힌다 —
    여기가 마지막 관문이다.

    ## 왜 지어내기가 아닌가

    **글자를 지우기만 한다.** 바꿔 쓰지 않는다 — 무엇을 뜻했는지 모르니 대신
    채우지 않는다. 그리고 **짧은 토막만** 지운다(`_STRAY_CJK_MAX_RUN`). 사용자가
    "이 문장을 중국어로 번역해줘"라고 시켜서 긴 중국어 문단이 온 것까지 지우면
    안 되므로, 그런 답은 길이 관문에 걸려 그대로 남는다.

    돌려주는 두 번째 값(지운 토막 목록)은 **버리지 않는다** — 호출부가 사건으로
    남겨야 "얼마나 자주 튀는지"를 나중에 실측할 수 있다(측정 먼저 원칙).
    """
    # ★ 2026-10-04: 지우기만 하면 「관測」이 「관」으로 잘린다. 한글 낱말에 붙은 글자는 한국어 소리로 바꾸고(測→측),
    #   소리를 하나로 못 정하는 글자와 영어 문장 속 글자만 지운다. 규칙과 표는 `stray_han` 한 곳에 있다 —
    #   일하면서 하는 말(`narration.clean`)도 같은 것을 쓴다.
    return _mend_stray_han(text)


#: 사이트 구조화 데이터(JSON-LD)의 필드 이름. 모델은 `structured_data` 를 `offers.price: 0` 같은 줄로 읽는다.
_SCHEMA_FIELD = (
    r"offers|price|priceCurrency|aggregateRating|ratingValue|ratingCount|reviewCount|bestRating|author|publisher|brand"
    r"|datePublished|dateModified|isbn|numberOfPages|hiringOrganization|jobLocation|baseSalary|validThrough"
    r"|operatingSystem|applicationCategory|name|description|url|sku|gtin13"
)
_SCHEMA_ITEM = re.compile(
    rf"^`?(?:{_SCHEMA_FIELD})(?:\[\d+\])?(?:\.(?:{_SCHEMA_FIELD}|[A-Za-z]+))*`?\s*[=:]\s*`?[^`]{{0,60}}`?$"
)
#: 사람이 쓰는 말이 아닌 것 — 점 경로(`offers.price`)나 낙타 표기(`ratingValue`). 이게 하나는 있어야 걷는다
#: (「(저자: 홍길동)」 같은 괄호를 해치지 않게 — 한글 괄호는 애초에 필드 이름과 안 맞는다).
_SCHEMA_TELL = re.compile(r"[A-Za-z]\.[A-Za-z]|[a-z][A-Z]")
_PARENS = re.compile(r"[ \t]*\(([^()\n]{1,200})\)")
_STRUCTURED_WORD = re.compile(r"`?structured_data`?(?:\s*\((?:book|product|softwareapplication|article)\))?", re.I)


def _strip_schema_labels(text: str) -> tuple[str, list[str]]:
    """사람에게 보이는 글에서 **도구 속 이름**을 걷는다 (2026-09-29, MS 스토어 M3).

    ## 왜

    엑셀 칸과 답에 「무료 (offers.price=0)」가 들어갔다. 값은 맞았는데 사람이 모르는 필드 이름이 셀마다 붙었다.
    과거 답 2,255판을 훑으니 13판에 이런 것이 있었다 — 대부분 「`structured_data` 기준」, 그리고
    「(`author: OpenAI`, `aggregateRating.ratingValue: 3.5`)」 같은 괄호. 근거를 밝히려는 좋은 버릇이 도구 말로 샜다.

    ## 무엇을 하나

    - 괄호 안이 **전부** 필드 이름=값 이고 그중 하나라도 점 경로·낙타 표기면 괄호째 지운다(값은 이미 본문에 있다).
    - `structured_data` 라는 낱말은 「사이트 제공 정보」로 바꾼다 — 근거를 밝힌 뜻은 남긴다.

    코드 블록(```)은 안 건드린다. 부르는 쪽이 **브라우저로 읽은 판에만** 건다 — 우리 코드를 다루는 판에서 이 낱말은 진짜 이름이다.
    """
    if not text:
        return text, []
    removed: list[str] = []

    def _parens(match: "re.Match[str]") -> str:
        items = [item.strip() for item in match.group(1).split(",")]
        if items and all(_SCHEMA_ITEM.match(item) for item in items) and _SCHEMA_TELL.search(match.group(1)):
            removed.append(match.group(0).strip())
            return ""
        return match.group(0)

    def _word(match: "re.Match[str]") -> str:
        removed.append(match.group(0))
        return "사이트 제공 정보"

    parts = re.split(r"(```.*?```)", text, flags=re.S)
    cleaned = "".join(
        part if part.startswith("```") else _STRUCTURED_WORD.sub(_word, _PARENS.sub(_parens, part)) for part in parts
    )
    return (cleaned, removed) if removed else (text, [])


def _strip_schema_labels_in(value: Any, removed: list[str]) -> Any:
    """문서 쓰기 인자(칸·문단) 안의 글자에 같은 관문을 건다."""
    if isinstance(value, str):
        cleaned, found = _strip_schema_labels(value)
        removed.extend(found)
        return cleaned
    if isinstance(value, list):
        return [_strip_schema_labels_in(item, removed) for item in value]
    if isinstance(value, dict):
        return {key: _strip_schema_labels_in(item, removed) for key, item in value.items()}
    return value


#: 「X 로 가 줘 · X 들어가서 · X 열어 줘」. 이름은 로마자이거나 웹 자리를 뜻하는 말로 끝나야 한다 — 역검증에서 「아프긴한 … 열어」
#: 같은 잡담이 걸렸다(과거 77판 중 브라우저를 안 연 17판을 손으로 봤다).
_NAV_ASK = re.compile(
    r"([A-Za-z][A-Za-z0-9.\-]{1,30}|[가-힣]{0,12}(?:사이트|페이지|홈페이지|스토어|드라이브|콘솔|카페|블로그|브라우저))"
    r"\s*(?:으로|로|에|을|를|에서)?\s*(?:한번\s*|직접\s*)?"
    r"(?:가\s*줘|가\s*줄\s*수|가\s*주|가줄|가\s*봐|들어가\s*(?:줘|봐|서|줄)|열어\s*(?:줘|주|봐|줄)|이동해|접속해)"
)
_ANSWER_LINK = re.compile(r"\((https?://[^\s)]+)\)|(?<![(\w])(https?://[^\s)<>\]]+)")


def _offered_link_to_open(prompt: str, answer: str, steps: list[dict[str, Any]]) -> str:
    """「가 줘」라고 했는데 **링크만 주고 안 열었으면** 도구가 열 주소 하나. 없으면 빈 문자열.

    ★ 2026-09-29 대표 실사용(잡 9fe5fbd7): 「…로 가줄수는있나 … 로그인은 내가할게」에 도구를 한 번도 안 부르고
      「AWS 콘솔로 바로 **이동해 드리겠습니다**」와 링크를 답했다 — 그 링크는 데스크톱 앱에서 눌러도 안 열렸다. 말과 행동이 달랐다.
      계획 층은 AWS 를 모르는 사이트라 요구를 0개 뽑아 되받을 근거도 없었다. 사고 R — 안내 대신 도구가 한다.
    """
    match = _NAV_ASK.search(str(prompt or ""))
    if not match:
        return ""
    if any(str(step.get("tool") or "").startswith(("browser_", "google_")) and step.get("ok") for step in steps):
        return ""
    links = [first or second for first, second in _ANSWER_LINK.findall(str(answer or ""))]
    links = [link.rstrip(".,*`'\"") for link in links if link]
    if not links:
        return ""
    name = match.group(1).lower()
    if re.fullmatch(r"[a-z][a-z0-9.\-]+", name):
        token = re.sub(r"[^a-z0-9]", "", name.split(".")[0])
        for link in links:
            host = (urlparse(link).hostname or "").lower()
            if token and token in re.sub(r"[^a-z0-9.]", "", host):
                return link
        return ""
    return links[0]


def _artifact_still_owed(
    plan_results: list[tuple[Any, bool, str]], steps: list[dict[str, Any]]
) -> bool:
    """산출물을 시켰는데 **아직 없고, 만들어 본 적도 없는가.**

    만들어 봤다가 실패한 판은 여기서 안 민다 — 그건 모델이 안 부른 것이 아니라
    도구가 안 된 것이다(`_forced_artifact_decision` 의 `already_attempted` 와 같은 규율).
    """
    owed = any(
        not ok and str(getattr(req, "kind", "")) == "artifact"
        for req, ok, _saw in plan_results
    )
    tried = any(str(step.get("tool") or "") in _ARTIFACT_WRITE_TOOLS for step in steps)
    return owed and not tried


#: 답이 **문서를 만들겠다고 예고**하는가 — 그런 답은 옮겨 적을 문서가 아니다.
_PLANS_THE_DOCUMENT = re.compile(
    r"(?:작성|생성|만들|정리|반영|저장|작업|제작)(?:해|하|어|들어)?\s*(?:드리|보|하)?겠습니다"
)


_LEADING_NUMBER = re.compile(r"^\s*(?:\d+|[IVX]+)\s*[.)]\s*")

#: 답 **끝에 우리가 붙인** 것들. 사람이 채팅에서 볼 말이고 산출물에 들어갈 것이 아니다.
#: (2026-09-16: 강제 산출물이 만든 엑셀에 `❌ 3개 이상 직접 열어 읽기` 가 들어갔다.)
# 영어 판의 대조표 머리(「**Checklist**」)도 우리가 붙인 것이다(2026-10-01) — 안 보면 영어 판에서 대조표가 파일에 섞인다.
_OUR_APPENDED_NOTES = re.compile(r"\n\s*(?:\*\*(?:시킨 것 대조|Checklist)\*\*|⚠\s*\*\*시킨 조건과 다른)")


def _with_document_title(blocks: list[dict[str, Any]], body: str) -> list[dict[str, Any]]:
    """문서 맨 앞에 **제목(H1)** 이 서게 한다.

    ★ 2026-09-13 양식 검사기가 잡았다. 이 안전망이 만든 파일 넷이 전부 제목 없이
    나왔고, 이름도 `정리.docx` · `1_채용_공고_요약.docx` 였다. 답이 「### 1. 채용 공고
    요약」 같은 **소제목으로 시작**하니, 그 소제목이 파일 이름이 되고 문서엔 제목이
    없었다. 사람이 받은 워드 첫 줄이 「1. 채용 공고 요약」이다.

    - 맨 앞 세 블록 안에 H1 이 있으면 그것을 **맨 앞으로** 옮긴다. 답은 흔히
      「조사한 결과입니다.」 한 줄 뒤에 `# 제목` 을 쓴다 — 문서에선 제목이 먼저다.
    - 첫 블록이 소제목이면 번호를 떼고 H1 로 올린다.
    - 제목이 하나도 없으면 답의 첫 문장을 제목으로 세운다(짧게).
    """
    if not blocks:
        return blocks
    for index, block in enumerate(blocks[:3]):
        if block.get("type") == "heading" and int(block.get("level") or 1) == 1:
            return [block] + blocks[:index] + blocks[index + 1:]
    first = blocks[0]
    if first.get("type") == "heading":
        title = _LEADING_NUMBER.sub("", str(first.get("text") or "")).strip()
        return [{**first, "level": 1, "text": title}] + blocks[1:]
    line = next((ln.strip() for ln in str(body or "").splitlines() if ln.strip()), "")
    line = re.sub(r"^[#>*\-\s]+", "", line)
    title = re.split(r"(?<=[.!?。])\s|입니다\.|했습니다\.", line, maxsplit=1)[0].strip(" .")[:40] or "정리"
    return [{"type": "heading", "level": 1, "text": title}] + blocks


def _code_text_tool_call(
    message: dict[str, Any], allowed_names: set[str] | frozenset[str]
) -> dict[str, Any] | None:
    """코더가 본문에 낸 단일 JSON 호출만 네이티브 모양으로 복구한다.

    일부 Ollama 코더는 긴 에이전트 시스템 문장에서 ``tool_calls`` 대신
    ``{"name": ..., "arguments": ...}``를 content로 낸다. 아무 산문이나
    실행하지 않고, JSON 객체 하나이며 실제로 노출한 코드 도구 이름일 때만
    복구한다. 실행은 여전히 게이트웨이를 탄다.
    """
    content = str(message.get("content") or "").strip()
    if not content or len(content) > 20_000:
        return None
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else ""
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
    name = str(function.get("name") or "")
    arguments = function.get("arguments")
    if name not in allowed_names or not isinstance(arguments, dict):
        return None
    return {"function": {"name": name, "arguments": arguments}}


# ── 준비까지 해 놓고 커밋을 안 부르는 판 ────────────────────────────────────────
#
# ★ 2026-08-20. **L3→L4 의 천장이 여기였다.** 7일 실측에서 위임이 걸린 179 판 중
# 60 판(33.5%)이 `model_stopped_early` 로 끝났고, 그중 행위 요구가 미달인 12 판의
# 걸음 꼬리가 전부 같은 모양이었다:
#
#     naver_blog_prepare_post → fill_editor → prepare_save_draft        (끝)
#     google_gmail_prepare_send                                          (끝)
#     google_calendar_upcoming → google_calendar_prepare_create          (끝)
#
# 답은 "승인을 기다리는 대기 상태입니다"였다. **승인 요청이 뜬 적이 없다** — 커밋
# 도구를 불러야 카드가 생기는데 부르지 않았으니, 사용자가 누를 것 자체가 없었다.
#
# 프롬프트에는 이미 못을 박아 뒀다("commit 도구를 실제로 호출해야만 화면에 승인
# 요청이 생성된다"). 되받기도 두 번까지 걸어 뒀다. 둘 다 못 뚫었다.
# **안내문은 안 먹는다 — 결정론으로 박을 수 있으면 코드로 옮긴다**(사고 R).
#
# 그래서 사슬의 남은 칸을 에이전트가 대신 부른다. 안전한 이유는 하나다:
#
#     ★ **뿌리(chain[0]) 다음의 도구들은 전부 인자가 `{"action_id"}` 하나뿐이다.**
#       지어낼 것이 없다. 제목·본문·수신자를 받는 것은 뿌리뿐이고, 뿌리는 **절대
#       대신 부르지 않는다** — 셀렉터를 지어내지 않는 것과 같은 규칙이다.
#
# 뿌리가 이 판에서 실제로 성공했다는 것은 "사용자가 시킨 그 내용을 자비스가 이미
# 만들어 놨다"는 뜻이다. 남은 것은 그것을 밖으로 내보내는 일뿐이고, 등급이 L2 면
# 게이트웨이가 그 자리에서 **진짜 승인 카드**를 만든다(지어낸 대기가 아니라).
#
# ⚠ 여기 목록은 `_ACTION_ID_CONSUMER_TO_PRODUCER` 와 어긋나면 안 된다. 뿌리 뒤의
#   모든 이름이 그 표에 있는지 검사가 지킨다(test_forced_commit.py).
_COMMIT_CHAINS: dict[str, tuple[str, ...]] = {
    # 본문을 채우지 않고 저장하면 **빈 글이 저장된다.** fill_editor 를 사슬에 넣는
    # 이유가 그것이다 — 이것은 prepare_save_draft 의 형제라 사슬을 자동으로
    # 역추적하면 빠진다.
    "naver_blog_save_draft": (
        "naver_blog_prepare_post",
        "naver_blog_fill_editor",
        "naver_blog_prepare_save_draft",
        "naver_blog_save_draft",
    ),
    "naver_blog_publish": (
        "naver_blog_prepare_post",
        "naver_blog_fill_editor",
        "naver_blog_prepare_publish",
        "naver_blog_publish",
    ),
    "google_gmail_send": ("google_gmail_prepare_send", "google_gmail_send"),
    "google_drive_write": ("google_drive_prepare_write", "google_drive_write"),
    "google_calendar_create": ("google_calendar_prepare_create", "google_calendar_create"),
    "google_calendar_update": ("google_calendar_prepare_update", "google_calendar_update"),
    "google_calendar_delete": ("google_calendar_prepare_delete", "google_calendar_delete"),
}

# 한 판에서 대신 불러 주는 최대 횟수. 블로그 사슬이 최대 셋(채우기·저장준비·저장)이라
# 그보다 하나 크게 둔다. 무한이면 못 하는 일을 계속 밀어 넣게 된다 — `nudges`·
# `_PLAN_PUSHBACK_LIMIT` 과 같은 규율이다.
_FORCED_COMMIT_LIMIT = 4

_FORCED_COMMIT_NOTE = (
    "★ **네가 부르지 않아서 시스템이 대신 불렀다.** 사용자가 시킨 그 동작인데 "
    "준비만 해 놓고 답을 내려 했다. 커밋 도구를 부르는 것 자체는 안전하다 — "
    "승인이 필요하면 그 순간 화면에 카드가 뜨고, 카드는 **도구를 불러야만** 생긴다. "
    "'승인을 기다린다'고 글로 쓰는 것은 기다리는 것이 아니라 아무 일도 안 일어나는 "
    "것이다. 남은 칸이 더 있으면 지금 이어서 불러라."
)
