"""가이드 스킬 `sonjari-guide` — Claude 가 온텔릭을 언제·어떻게 부르는지 (2026-09-16, 인수인계 H1-b).

MCP 안내문(`mcp_server.INSTRUCTIONS`)은 1,500자라 「무엇인가·언제」까지만 담는다. 스킬은 그 뒤 —
과제를 어떻게 적어 맡기는지, 결과를 어떻게 전하는지, 벽을 만나면 무엇을 하는지 — 를 담는다.

★ 도구 표는 **손으로 쓰지 않고 지금 도는 도구 목록에서 뽑는다.** 손으로 쓴 이름은 도구가 바뀌면 조용히
  틀린다(사고 Q·S). 그래서 설치할 때마다 새로 만든다.

설치 자리(공식 문서 기준):
- Claude Code: `~/.claude/skills/<이름>/SKILL.md` — 파일 자리가 곧 설치다.
- Claude Desktop·claude.ai: 앱이 폴더를 읽지 않는다. 사용자가 설정의 스킬 화면에서 **zip 을 올린다** —
  그래서 zip 을 만들어 두고 올리는 곳을 알려 줄 뿐, 올린 척하지 않는다.

## ★ 전역 지침 한 줄이 먼저다 (2026-09-16 실측)

연결만 해 두면 **안 부른다.** Codex(GPT-5.6)에게 「사람인에서 공고 찾아 파일로」를 시켰더니 온텔릭 도구를
**0번** 부르고 자기 브라우저·웹 검색으로 했다. 게다가 「온텔릭으로 확인했다」고 말했다(안 한 일을 했다고 말하는
고장 — 이 저장소가 여러 번 겪었다). 스킬은 **볼 수도 있고 안 볼 수도** 있지만, 전역 지침 파일은 **매번 읽는다.**

그래서 지침에는 짧게 「온텔릭 관련이면 이 파일을 먼저 읽어라」만 넣고, 절차는 스킬 파일이 들고 있는다 —
지침이 길어지지 않고, 도구가 바뀌어도 스킬 파일만 다시 만들면 된다.

| 도구 | 지침 파일 | 가리킬 곳 |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/sonjari-guide/SKILL.md` |
| Codex | `~/.codex/AGENTS.md` | `~/.codex/sonjari-guide.md`(스킬 폴더가 없어 사본을 둔다) |
| Cursor | 사용자 규칙은 앱 안에 있다 — **직접 넣지 않고** 붙여 넣을 글만 준다 |

## 분야 팩의 사용서 (2026-09-27 · 게임 팩)

팩이 `guide`(바깥 AI 용 사용서)를 가지고 있으면, 그 팩이 **켜져 있을 때** 잇기가 사용서를 가이드 옆에 두고
전역 지침에 「이 분야 일이면 이 파일을 먼저 읽어라」 한 줄을 더한다. 팩을 끄면 그 줄과 파일을 뺀다.
사람이 게임 팩을 켜는 순간 클로드·코덱스가 「게임 일은 이렇게」를 알게 된다 — 따로 가르칠 필요가 없다.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

from .brand import NAME, NAME_KO, documents_product_dir

__all__ = ["SKILL_NAME", "render_skill", "GuideSkillService"]

SKILL_NAME = "sonjari-guide"
_MARK = "<!-- sonjari-guide: generated -->"
_PACK_MARK = "<!-- sonjari-pack-guide: generated -->"
_NOTE_START = "<!-- sonjari-guide:start -->"
_NOTE_END = "<!-- sonjari-guide:end -->"
#: ★ 이름 2단계(2026-09-29): 옛 이름으로 **우리가 깔아 둔 것**은 알아보고 걷어낸다 — 한 PC 에 옛 지침·새 지침이 나란히
#:   남으면 클로드가 없는 도구 이름(sonjari_task)을 부른다. 남이 만든 같은 이름 파일은 표시가 없어 안 건드린다.
LEGACY_SKILL_NAME = "ontelic-guide"
_LEGACY_MARK = "<!-- ontelic-guide: generated -->"
_LEGACY_PACK_MARK = "<!-- ontelic-pack-guide: generated -->"
_LEGACY_NOTE = ("<!-- ontelic-guide:start -->", "<!-- ontelic-guide:end -->")
_NOTE_PAIRS = ((_NOTE_START, _NOTE_END), _LEGACY_NOTE)

_GROUPS: tuple[tuple[str, str], ...] = (
    ("sonjari_", "통째로 맡기기"),
    ("site_", "사이트 레시피"),
    ("browser_", "브라우저(낮은 단위)"),
    ("local_", "이 PC 의 파일·문서"),
    ("google_", "구글"),
    ("skill_", "스킬"),
)
#: 영어판의 묶음 이름 — 앞머리는 `_GROUPS` 와 같은 순서·같은 집합이어야 한다(시험이 본다).
_GROUPS_EN: dict[str, str] = {
    "sonjari_": "Hand off a whole task",
    "site_": "Site recipes",
    "browser_": "Browser (low-level)",
    "local_": "Files and documents on this PC",
    "google_": "Google",
    "skill_": "Skills",
}
_HANGUL = re.compile("[가-힣]")


def _first_line(text: str, limit: int = 110) -> str:
    line = " ".join(str(text or "").strip().splitlines()[:1])
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _tool_table(tools: Iterable[dict[str, Any]], lang: str) -> tuple[list[str], bool]:
    """도구 표 줄과 「위임 문이 있나」. 영어판은 묶음 이름·「기타」도 영어로 낸다."""
    english = lang == "en"
    groups = tuple((prefix, _GROUPS_EN[prefix] if english else label) for prefix, label in _GROUPS)
    other = "Other" if english else "기타"
    grouped: dict[str, list[dict[str, Any]]] = {label: [] for _, label in groups}
    grouped[other] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        if not name:
            continue
        label = next((label for prefix, label in groups if name.startswith(prefix)), other)
        grouped[label].append(tool)

    table: list[str] = []
    for label, items in grouped.items():
        if not items:
            continue
        table.append(f"\n### {label} ({len(items)})\n")
        for tool in sorted(items, key=lambda t: str(t.get("name"))):
            line = _first_line(tool.get("description", ""))
            # ★ 영어판(2026-10-19): 도구 설명은 대개 한국어다(게이트웨이가 한국어로 만든다). 영어 본문에 한국어 설명을 섞으면
            #   읽는 모델이 다시 한국어 쪽으로 끌린다 — 그 사고를 막으려고 만든 판이다. 한국어 설명은 빼고 이름만 둔다
            #   (설명 전체는 MCP 도구 목록에 그대로 있다).
            if english and (not line or _HANGUL.search(line)):
                table.append(f"- `{tool['name']}`")
            else:
                table.append(f"- `{tool['name']}` — {line}")

    has_task = any(str(t.get("name")) == "sonjari_task" for tool_list in grouped.values() for t in tool_list)
    return table, has_task


def render_skill(tools: Iterable[dict[str, Any]], lang: str = "ko") -> str:
    """SKILL.md 본문. `tools` 는 MCP 로 실제 내보내는 목록(위임 문 포함).

    `lang` 이 "en" 이면 같은 내용의 영어 본문을 낸다(2026-10-19 — 영어 사용자의 클로드 코드가 한국어 가이드를 읽고
    손자리에게 일을 한국어로 넘겼다). 그 밖의 값은 한국어(예전과 같다).
    """
    if lang == "en":
        return _render_skill_en(tools)
    table, has_task = _tool_table(tools, "ko")
    delegate = (
        "1. **과제 하나는 `sonjari_task` 로 통째로 맡긴다.** 낮은 단위 도구를 직접 여러 번 부르지 않는다 — 걸음마다\n"
        "   대화가 길어져 느리고 비싸다. 결과는 `sonjari_task_status` 로 받는다(끝날 때까지 다시 부른다).\n"
        if has_task else
        "1. 이 설치에는 위임 도구가 없다. 아래 도구를 직접 쓰되, 한 과제에 필요한 만큼만 부른다.\n"
    )
    # 저장소의 코드 일을 맡기는 칸(repo · check)은 위임 도구에 달려 있다 — 그 도구가 없는 설치에는 적지 않는다.
    repo_row = (
        "| 저장소의 **좁은** 코드 일(파일 한두 개 · 통과하면 끝인 명령이 있는 것) — 아래 「저장소의 코드 일을 맡길 때」 "
        "| 그 일을 쪼개는 설계 · 돌아온 가지의 검토와 합치기 |\n"
    ) if has_task else ""
    repo_job = f"""### 저장소의 코드 일을 맡길 때 — `repo` · `check` 칸 (2026-10-09)

좁은 코드 일은 통째로 맡길 수 있다. `sonjari_task` 에 칸 둘을 같이 준다.

- `repo` — 저장소(또는 그 안의 폴더) 절대 경로. {NAME_KO}는 그 저장소의 **새 가지**를 따로 꺼내 거기서만 고친다.
  원래 폴더는 건드리지 않는다. 커밋 안 한 변경(추적 중인 파일)은 같이 가져간다 — 새로 만든 파일은 커밋해 둬야 보인다.
- `check` — 통과하면 끝인 명령 한 줄(예: `python -m pytest -q tests/test_x.py`). **끝의 기준은 과제 글이 아니라 이 명령이다.**
  {NAME_KO}는 글에서 요구를 짐작하지 않는다. 보고를 내려 할 때 이 명령을 직접 돌려 보고, 떨어지면 그 출력을 보고 고친다.

과제 글은 이렇게 적는다.

1. **고칠 자리를 이름으로** — 파일과 함수. 「어디에 넣을지는 알아서」보다 훨씬 잘 끝난다.
2. **끝의 기준은 `check` 에 담는다.** 가장 단단한 것은 네가 합격 시험을 먼저 써서 커밋해 두고 그 시험을 `check` 로 주는 것이다.
   시험까지 맡기려면 지킬 것을 한 줄에 하나씩 적는다(그 줄마다 시험이 하나씩 돌아온다).
3. **한 번에 파일 한두 개 크기.** 큰 기능은 네가 설계해 쪼갠 뒤 하나씩 맡긴다 — 한 번에 한 일만 돈다.

돌아오는 것은 `branch` 에 있다: `changed`(바뀐 파일) · `check`(통과했나 · 몇 번 돌렸나) · `take_home`(보는 명령 · 가져가는 명령 ·
버리는 명령). **가져가기 전에 바뀐 것을 읽는다** — {NAME_KO}는 원래 폴더에 합치지 않는다. 합치는 것은 네가 정한다.

시간 제한은 없다. 대신 제자리면 접고 `branch.stopped_because` 에 까닭을 준다(같은 실패가 되풀이됨 · 같은 파일을 돌려 보지 않고
다시 씀 · 새로 한 일이 없음). 그대로 다시 맡기면 같은 자리에서 멈춘다 — 더 작게 쪼개거나 걸린 곳을 네가 고친다.
맡긴 일이 도는 동안 사용자가 {NAME} 창에서 다른 일을 시키면, 맡긴 일이 걸음 사이에서 비켜 줬다가 이어 간다.

잰 것(그래픽카드 24GB · 27B 모델 · 2026-10-09 · 1판): 함수 하나와 그 시험 여섯 개 — 270초, 확인 명령 통과, 실패한 걸음 없음.
그 전날 칸 없이 글로만 맡긴 큰 기능(1만 줄짜리 파일 셋을 건드리는 것)은 두 번 다 끝내지 못했다. 9B 이하 모델로는 아직 안 쟀다 —
작은 모델에는 더 잘게(함수 하나) 쪼개 맡기고 결과를 꼭 읽는다.

""" if has_task else ""
    return f"""---
name: {SKILL_NAME}
description: {NAME}({NAME_KO}) MCP 를 쓰는 법. 사용자가 웹에서 찾아 읽고 표·문서·엑셀로 만들어 달라고 하거나, 로그인된 실제 브라우저·이 PC 의 파일이 필요한 일을 맡길 때 쓴다. 「{NAME_KO}에게 시켜」·「{NAME}로 해 줘」 같은 말에도 쓴다.
---

{_MARK}
# {NAME} 가이드

{NAME}({NAME_KO})는 사용자 PC 에서 도는 로컬 AI 작업 도우미다. 사용자의 **실제 크롬**(로그인된 사이트)·파일·
워드/엑셀/한글 문서를 직접 다룬다. 이 스킬은 {NAME} MCP 서버가 연결돼 있을 때만 쓴다.

## 맡길 일 / 맡기지 않을 일

{NAME_KO}가 가진 것은 셋이다. 네 도구에는 없는 것들이다.

- **사용자의 실제 크롬** — 사용자가 로그인해 둔 사이트가 그대로 열린다. 네 웹 검색·자동화 브라우저(Playwright 등)는
  빈 브라우저라 로그인이 없고, 네이버·쿠팡·사람인 같은 국내 사이트의 봇 검사에 자주 막힌다.
- **본문을 이 PC 에서 읽는 조사** — 여러 페이지를 읽어도 본문은 이 대화의 창에 안 쌓이고 결과(요약·근거 주소)만 온다.
  2026-10-02 실측(n=1): 같은 채용 공고 조사가 너 혼자 $1.25 · {NAME_KO}에게 맡겨 $0.19.
- **이 PC 의 파일·문서** — 워드·엑셀·한글(.hwp) 읽기와 새 문서 만들기.

| {NAME_KO}에게 맞는 일 | 너에게 맞는 일 |
|---|---|
| 사이트에서 찾아 읽고 → 파일로 정리(채용 공고·상품·가격·경쟁사) | 대화에 이미 있는 글의 요약·번역 · 일반 지식 질문 |
| 로그인이 필요한 사이트·봇 검사가 있는 국내 사이트에서 보기 | 큰 설계 · 여러 파일에 걸친 고치기 · 처음 보는 API 의 코드 — 아래 「이 PC 의 코드를 고칠 때」 |
{repo_row}| **코딩 중** 여러 페이지를 읽는 조사 — 라이브러리 문서·에러 메시지·버전 차이 비교 | 설계·어려운 디버깅 판단 |
| **코딩 중** 사용자 로그인이 있어야 보이는 화면 확인(관리자 페이지·배포된 서비스) | **네가 방금 띄워 둔 앱**(`http://localhost:…`)의 동작 확인 — 네 테스트 도구가 더 빠르고 결과를 직접 본다 |
| 이 PC 의 코드 파일 읽어 오기 · 네가 짠 수정을 그 파일에 쓰기 · 사용자 PC 의 문서 | {NAME_KO}가 돌려준 결과의 검토 |

### 맡긴 결과는 네가 확인할 수 있다

결과에는 말만 오지 않는다 — `sources`(읽은 주소와 그 자리의 원문), `files`(만든 파일 경로), 「없었다」고 할 때
**실제로 본 범위**(검색어·건수)가 온다. `unsupported_numbers` 는 도구가 본 적 없는 숫자다. 그 근거로 확인하고,
모자란 칸만 네가 채운다.

### 코딩 중에 맡기는 이유와 순서 (2026-09-29)

코딩 중 조사를 직접 하면 페이지 본문이 **이 대화의 창**에 쌓인다. {NAME_KO}에게 맡기면 본문은 사용자 PC 에서 읽고
결과(요약·근거 주소)만 돌아온다. 대신 로컬 모델이라 **느리다**(수십 초~몇 분) — 기다리는 동안 다른 일을 해도 되는
조사에 맡긴다. 순서는 **싼 것부터 → 근거 확인 → 모자라면 직접**: 맡기고, 돌아온 `sources` 로 확인하고,
`resume` 이 있거나 답이 모자라면 남은 칸만 직접 한다.

### 이 PC 의 코드를 고칠 때 (2026-10-01 베타 테스터)

「3ds Max 스크립트 고쳐 줘」를 통째로 맡기면, {NAME_KO}(로컬 모델)는 처음 보는 API 를 **웹에서 찾아 공부하느라** 오래 걸린다
(실사용: 「손자리가 인터넷 서칭을 많이 하네」). 너는 그 API 를 이미 안다. 나눠서 한다:

1. {NAME_KO}에게 **파일을 읽어 오게** 한다 — 「`D:\\...\\script.py` 내용을 그대로 돌려줘(고치지 말고)」.
2. 고칠 코드는 **네가** 짠다.
3. {NAME_KO}에게 **그대로 쓰게** 한다 — 경로와 바꿀 내용을 과제 문장에 그대로 넣는다. 허락 안 된 폴더면 {NAME} 창에 승인 카드가 뜬다 — 사용자에게 그 창을 보라고 알린다.

{repo_job}### 손자리 모델 크기에 따라 맡길 일이 다르다 (2026-10-01 밤)

PC 마다 손자리 모델이 다르다(4B·9B·27B·35B). `sonjari_guide` 를 부르면 끝에 **이 PC 의 모델과 「맡기기 좋은 일 / 네가 직접 할 일」**이
붙어 온다 — 그 표대로 나눈다. 결과에 `model_hint` 가 오면 손자리 모델이 그 일에 작다는 뜻이니 사용자에게 그대로 전한다.

## 순서

{delegate}2. **과제 문장에 셋을 담는다**: 무엇을 · 어디서(사이트 이름) · 어떤 파일로(`.xlsx`·`.docx`·`.md`).
   예: 「사람인에서 서울 마케팅 공고 3개를 찾아 회사·마감일·자격을 엑셀로 정리해 줘」.
   **과제는 사용자가 너와 쓰는 언어로 적는다.** {NAME_KO} 모델은 한국어·영어를 다 읽는다.
   **저장 폴더는 적지 않는다** — 그러면 {NAME_KO} 결과물 폴더(내 문서 아래)에 저장되고 `files` 로 경로가 온다.
   네 작업 폴더 같은 다른 자리를 적으면 {NAME} 창의 승인 카드에서 멈춘다(사람이 자리에 없으면 그대로 기다린다).
   파일이 거기 있어야 하면 받은 뒤 네가 옮긴다.
3. 결과를 전할 때:
   - `files` 의 경로를 그대로 알려 준다. 파일 내용을 지어서 설명하지 않는다.
   - `unsupported_numbers` 가 있으면(`status: needs_review`) 그 숫자를 사실로 말하지 않는다 —
     「출처에서 확인되지 않은 숫자가 있어 확인이 필요하다」고 먼저 말한다.
   - `sources` 는 근거로 같이 준다.
4. **한 번에 한 일.** {NAME_KO}는 과제를 하나씩 돈다. 여러 개면 앞 과제가 끝난 뒤 다음을 맡긴다.

## 벽을 만나면

- 로그인·보안 문자(캡차)·결제·본인 확인: 사람에게 넘긴다. 대신 풀거나 우회 도구를 찾지 않는다.
  예외 하나 — **이 PC 개발 주소**(`localhost`·`127.0.0.1`·`*.test`)의 시험 앱은 과제 문장에 시험 계정
  (예: 아이디 "demo_user", 비밀번호 "demo1234")을 **그대로** 적으면 {NAME_KO}가 그 값으로 넣는다.
  문장에 없는 값은 넣지 않는다.
- `needs_approval`: 되돌릴 수 없는 동작이 {NAME} 창의 승인 카드를 기다린다. 사용자에게 그 창을 보라고 알린다.
- 메일 발송·발행·삭제·결제는 이 연결로 할 수 없다. 사용자에게 {NAME} 창에서 직접 하도록 안내한다.
- 「연결하지 못했습니다」: {NAME} 이 꺼져 있다. 켜 달라고 알린다 — 결과를 지어내지 않는다.

## 지금 쓸 수 있는 도구 (설치할 때 도구 목록에서 뽑음)
{chr(10).join(table)}
"""


def _render_skill_en(tools: Iterable[dict[str, Any]]) -> str:
    """영어판 SKILL.md — 한국어판과 **같은 내용**(잰 숫자·조건·필드 이름을 더하거나 빼지 않는다).

    한국어판을 고치면 여기도 같이 고친다. 한국 사이트 예시는 영어 사용자가 아는 예로 바꿨다(뜻은 같다) —
    다만 「국내 사이트의 봇 검사」는 사실 주장이라 사이트 이름(Naver·Coupang·Saramin)을 그대로 둔다.
    한글은 한 글자도 넣지 않는다(시험이 본다) — 영어 본문에 섞인 한국어가 바로 이 판이 막으려는 사고다.
    """
    table, has_task = _tool_table(tools, "en")
    delegate = (
        "1. **Hand off one task whole with `sonjari_task`.** Do not call the low-level tools directly many times — each step\n"
        "   makes the conversation longer, which is slow and expensive. Get the result with `sonjari_task_status` (call it again until it is done).\n"
        if has_task else
        "1. This install has no delegation tool. Use the tools below directly, but call only as many as one task needs.\n"
    )
    repo_row = (
        "| **Narrow** code work in a repository (one or two files · a command that means done when it passes) — see "
        "\"Handing off code work in a repository\" below "
        "| Designing how to split that work · reviewing and merging the branch that comes back |\n"
    ) if has_task else ""
    repo_job = f"""### Handing off code work in a repository — the `repo` and `check` fields (2026-10-09)

Narrow code work can be handed off whole. Give `sonjari_task` two more fields.

- `repo` — absolute path of the repository (or a folder inside it). {NAME} takes a **new branch** of that repository separately and edits only there.
  It does not touch the original folder. Uncommitted changes (to tracked files) come along — newly created files must be committed to be seen.
- `check` — a one-line command that means done when it passes (e.g. `python -m pytest -q tests/test_x.py`). **What counts as done is this command, not the task text.**
  {NAME} does not guess requirements from the text. When it is about to report, it runs this command itself, and if it fails, it reads the output and fixes.

Write the task text like this.

1. **Name the place to fix** — the file and the function. This finishes far more often than "put it wherever it fits".
2. **Put what counts as done in `check`.** The most solid way is to write the acceptance test yourself first, commit it, and give that test as `check`.
   If you hand off the tests too, write each thing to keep on its own line (one test comes back per line).
3. **One or two files at a time.** Design and split a big feature yourself, then hand the pieces off one by one — only one job runs at a time.

What comes back is in `branch`: `changed` (changed files) · `check` (did it pass · how many runs) · `take_home` (command to view · command to take it ·
command to discard). **Read what changed before taking it** — {NAME} does not merge into the original folder. Merging is your call.

There is no time limit. Instead, if it is going nowhere it stops and gives the reason in `branch.stopped_because` (the same failure repeats · rewrote the same
file without running it · nothing new was done). Handing it off again unchanged stops at the same place — split it smaller or fix the stuck spot yourself.
If the user gives another task in the {NAME} window while a handed-off job is running, the handed-off job steps aside between steps and then continues.

Measured (24GB graphics card · 27B model · 2026-10-09 · 1 run): one function and its six tests — 270 seconds, check command passed, no failed steps.
The day before, a big feature handed off as text only, without these fields (touching three 10,000-line files), did not finish either of two times. Not yet
measured with 9B or smaller models — for a small model, split it finer (one function) and always read the result.

""" if has_task else ""
    return f"""---
name: {SKILL_NAME}
description: How to use the {NAME} MCP. Use it when the user asks you to find and read things on the web and turn them into a table, document or spreadsheet, or hands you work that needs the real logged-in browser or files on this PC. Also use it for requests like "have {NAME} do it" or "do it with {NAME}".
---

{_MARK}
# {NAME} guide

{NAME} is a local AI work assistant that runs on the user's PC. It works directly with the user's **real Chrome** (sites they are logged in to), files,
and Word/Excel/Hangul documents. Use this skill only while the {NAME} MCP server is connected.

## What to hand off / what not to

{NAME} has three things. Your tools do not have them.

- **The user's real Chrome** — sites the user is logged in to open as they are. Your web search and automation browsers (Playwright etc.)
  are empty browsers with no login, and they are often blocked by the bot checks of Korean sites such as Naver, Coupang and Saramin.
- **Research read on this PC** — even when it reads many pages, the page text does not pile up in this conversation's context; only the result (summary, source URLs) comes back.
  Measured 2026-10-02 (n=1): the same job-post research cost $1.25 done by you alone · $0.19 handed to {NAME}.
- **Files and documents on this PC** — reading Word, Excel and Hangul (.hwp) files, and making new documents.

| Good for {NAME} | Good for you |
|---|---|
| Find and read on sites → organize into a file (job posts · products · prices · competitors) | Summarizing or translating text already in the conversation · general knowledge questions |
| Viewing sites that need a login · Korean sites with bot checks | Big design · fixes across many files · code for an API you have not seen before — see "When editing code on this PC" below |
{repo_row}| Research **while coding** that reads many pages — library docs · error messages · version differences | Design · hard debugging calls |
| Checking screens **while coding** that only show with the user's login (admin pages · deployed services) | Checking **an app you just started** (`http://localhost:…`) — your test tools are faster and you see the result directly |
| Reading code files on this PC · writing the fix you made into that file · documents on the user's PC | Reviewing what {NAME} returns |

### You can check the results you handed off

Results are not just words — you get `sources` (the URLs read and the original text at that spot), `files` (paths of the files made), and, when it says
"there was none", **the range it actually looked at** (search terms · counts). `unsupported_numbers` are numbers the tools never saw. Check with that
evidence, and fill only the missing cells yourself.

### Why hand off while coding, and in what order (2026-09-29)

If you do research yourself while coding, the page text piles up in **this conversation's context**. Hand it to {NAME} and the pages are read on the
user's PC; only the result (summary · source URLs) comes back. In exchange it is **slow**, because it is a local model (tens of seconds to a few minutes) —
hand off research you can keep working through while you wait. The order is **cheapest first → check the evidence → do it yourself if it falls short**:
hand it off, check with the `sources` that come back, and if there is a `resume` or the answer falls short, do only the remaining cells yourself.

### When editing code on this PC (2026-10-01 beta tester)

If you hand off "fix my 3ds Max script" whole, {NAME} (a local model) takes a long time **studying an API it has never seen, on the web**
(real use: "Sonjari is searching the internet a lot"). You already know that API. Split it:

1. Have {NAME} **read the file back** — "Return the contents of `D:\\...\\script.py` as they are (do not change them)".
2. **You** write the code changes.
3. Have {NAME} **write them as they are** — put the path and the new content directly in the task text. If the folder is not allowed, an approval card appears in the {NAME} window — tell the user to look at that window.

{repo_job}### What to hand off depends on the {NAME} model size (2026-10-01 night)

The {NAME} model differs from PC to PC (4B · 9B · 27B · 35B). When you call `sonjari_guide`, **this PC's model and "good to hand off / do it yourself"**
are attached at the end — split the work by that table. If a result comes with `model_hint`, the {NAME} model is small for that job — pass it on to the user as is.

## Order

{delegate}2. **Put three things in the task text**: what · where (site name) · which file (`.xlsx`·`.docx`·`.md`).
   E.g. "Find 3 marketing job posts in London on Indeed and put each one's company, deadline and requirements into an Excel file".
   **Write the task in the language the user is using with you.** The {NAME} model reads both Korean and English.
   **Do not write a save folder** — then it is saved in the {NAME} output folder (under Documents) and the path comes back in `files`.
   If you write some other place, such as your working folder, it stops at the approval card in the {NAME} window (if nobody is at the PC, it just waits).
   If the file has to be there, move it yourself after you receive it.
3. When you pass on the result:
   - Give the paths in `files` as they are. Do not make up the file contents in your description.
   - If there are `unsupported_numbers` (`status: needs_review`), do not state those numbers as facts —
     first say "there are numbers that could not be confirmed in the sources, so they need checking".
   - Give `sources` along with it as evidence.
4. **One task at a time.** {NAME} runs tasks one by one. If there are several, hand off the next one after the previous one finishes.

## When you hit a wall

- Login · CAPTCHA · payment · identity check: hand it to a person. Do not solve it for them or look for a tool to get around it.
  One exception — for a test app at **a development address on this PC** (`localhost`·`127.0.0.1`·`*.test`), if you write the test account
  (e.g. username "demo_user", password "demo1234") **as is** in the task text, {NAME} enters those values.
  It does not enter values that are not in the text.
- `needs_approval`: an irreversible action is waiting at the approval card in the {NAME} window. Tell the user to look at that window.
- Sending mail · publishing · deleting · paying cannot be done through this connection. Tell the user to do it directly in the {NAME} window.
- "Could not connect": {NAME} is off. Ask the user to turn it on — do not make up results.

## Tools available now (taken from the tool list at install time)
{chr(10).join(table)}
"""


def render_note(guide_path: Path, packs: Iterable[tuple[str, Path]] = (), lang: str = "ko") -> str:
    """전역 지침에 넣을 **짧은** 블록. 절차는 안 적는다 — 스킬 파일을 가리키기만 한다.

    `lang` 이 "en" 이면 같은 내용의 영어 블록(2026-10-19). 시작·끝 표시는 두 언어가 같다 — 언어를 바꿔도 옛 블록을
    알아보고 갈아 끼운다. 팩 이름은 팩이 가진 이름 그대로 둔다(번역하지 않는다).
    """
    if lang == "en":
        pack_lines_en = "".join(
            f"- For **{name}** work, first read `{path}` and split the work the way it says (design and coding are yours; "
            f"running and repeating it in the real project is {NAME}'s).\n"
            for name, path in packs
        )
        return f"""{_NOTE_START}
## {NAME} is on this PC

- For {NAME}-related requests (finding things on the web and making documents or spreadsheets, the real logged-in browser, files on this PC),
  **read `{guide_path}` first** and follow its steps.
- {NAME} works in the user's real Chrome (sites they are logged in to) and on this PC. Your web search and automation browsers are empty browsers
  with no user login, and they are often blocked by the bot checks of Korean sites — hand that kind of work, and research across many pages, to the {NAME} MCP.
  Work your own tools can handle, such as checking a localhost app you just started, you do yourself.
- If you did not call {NAME} tools, **do not say "I did it with {NAME}".**
- If {NAME} is off or its tools are not visible, tell the user so (do not make it up).
{pack_lines_en}{_NOTE_END}"""
    pack_lines = "".join(
        f"- **{name}** 일이면 먼저 `{path}` 를 읽고 그 나눔대로 한다(설계·코딩은 너, 실제 프로젝트에서 돌리고 반복하는 것은 {NAME_KO}).\n"
        for name, path in packs
    )
    return f"""{_NOTE_START}
## {NAME}({NAME_KO}) 가 이 PC 에 있다

- {NAME_KO} 관련 요청(웹에서 찾아 문서·엑셀로 만들기, 로그인된 실제 브라우저, 이 PC 의 파일)이면
  **먼저 `{guide_path}` 를 읽고** 그 절차대로 한다.
- {NAME_KO}는 사용자의 실제 크롬(로그인된 사이트)과 이 PC 에서 일한다. 네 웹 검색·자동화 브라우저는 빈 브라우저라
  사용자 로그인이 없고 국내 사이트의 봇 검사에 자주 막힌다 — 그런 일과 여러 페이지 조사는 {NAME} MCP 로 맡긴다.
  네가 방금 띄운 localhost 앱의 확인처럼 네 도구로 충분한 일은 네가 한다.
- {NAME} 도구를 부르지 않았으면 **「{NAME_KO}로 했다」고 말하지 않는다.**
- {NAME} 이 꺼져 있거나 도구가 안 보이면 그 사실을 사용자에게 말한다(지어내지 않는다).
{pack_lines}{_NOTE_END}"""


def _with_pack_mark(text: str) -> str:
    """앞머리(---) 뒤에 표시를 끼운다 — 스킬 파일은 앞머리가 맨 위여야 읽힌다."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            cut = end + len("\n---")
            return text[:cut] + "\n\n" + _PACK_MARK + text[cut:]
    return _PACK_MARK + "\n" + text


class GuideSkillService:
    """스킬 파일을 만들고 Claude Code 자리에 넣거나 zip 으로 둔다."""

    def __init__(self, *, home: Path | None = None, documents: Path | None = None,
                 clock=time.time, pack_guides=None,  # noqa: ANN001
                 lang: Callable[[], str] | None = None) -> None:
        self.home = home or Path.home()
        self.documents = documents or documents_product_dir(self.home / "Documents")
        self.clock = clock
        #: 켜진 팩의 사용서 — [{"id", "name", "text"}]. 부를 때마다 읽는다(켜고 끄는 것이 곧바로 반영되게).
        self.pack_guides = pack_guides or (lambda: [])
        #: 가이드 본문의 언어("ko"·"en"). **렌더할 때마다** 부른다 — 화면 언어를 바꾸면 다음 갱신(`refresh_installed`)에서
        #:   설치된 가이드가 그 언어로 다시 써진다(2026-10-19 · 영어 사용자의 클로드가 한국어 가이드를 읽고 한국어로 맡겼다).
        self.lang = lang or (lambda: "ko")

    def _lang(self) -> str:
        try:
            return str(self.lang() or "ko")
        except Exception:  # noqa: BLE001 — 언어를 못 읽으면 예전처럼 한국어
            return "ko"

    def _render(self, tools: Iterable[dict[str, Any]]) -> str:
        return render_skill(tools, self._lang())

    # ── 팩 사용서 ────────────────────────────────────────────────────────
    def pack_guide_path(self, client: str, pack_id: str) -> Path:
        name = f"{SKILL_NAME.split('-')[0]}-{pack_id}"
        if client == "codex":
            return self.home / ".codex" / f"{name}.md"
        return self.home / ".claude" / "skills" / name / "SKILL.md"

    def _pack_files(self, client: str) -> list[Path]:
        """이 클라이언트 자리에 **우리가 둔** 팩 사용서(표시가 있는 것만)."""
        if client == "codex":
            candidates = list((self.home / ".codex").glob(f"{SKILL_NAME.split('-')[0]}-*.md"))
        else:
            candidates = list((self.home / ".claude" / "skills").glob(f"{SKILL_NAME.split('-')[0]}-*/SKILL.md"))
        out = []
        for path in candidates:
            if path.parent.name == SKILL_NAME or path.stem == SKILL_NAME:
                continue
            try:
                if _PACK_MARK in path.read_text(encoding="utf-8-sig", errors="ignore"):
                    out.append(path)
            except OSError:
                continue
        return out

    def _write_pack_guides(self, client: str) -> list[tuple[str, Path]]:
        written: list[tuple[str, Path]] = []
        keep: set[Path] = set()
        for pack in self.pack_guides():
            path = self.pack_guide_path(client, str(pack["id"]))
            if path.exists() and _PACK_MARK not in path.read_text(encoding="utf-8-sig", errors="ignore"):
                continue  # 같은 이름의 남의 파일은 덮지 않는다
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_with_pack_mark(str(pack["text"])), encoding="utf-8-sig")  # BOM — `_write_note` 주석
            written.append((str(pack["name"]), path))
            keep.add(path)
        for stale in self._pack_files(client):
            if stale not in keep:
                self._remove_pack_file(stale)
        return written

    def _remove_pack_file(self, path: Path) -> None:
        try:
            path.unlink()
            if path.name == "SKILL.md" and not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError:
            pass

    def refresh_packs(self, tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """팩을 켜고 끌 때. **이미 잇기를 한** 클라이언트만 다시 쓴다 — 잇지 않은 곳에 지침을 새로 만들지 않는다."""
        done: dict[str, Any] = {}
        tools = list(tools)
        for client, row in self.note_status().items():
            if row["installed"]:
                done[client] = self.install_note(client, tools)
        return done

    def refresh_installed(self, tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """앱이 켜질 때 — **우리가 깔아 둔** 가이드를 이 판의 문구로 맞춘다.

        ★ 2026-10-02: 스킬 파일·전역 지침은 「잇기」를 누를 때 한 번만 써졌다. 가이드 문구를 고쳐 업데이트를 내도
          테스터 PC 의 클로드는 옛 문구(「네 브라우저로 대신하지 않는다」)를 계속 읽었다 — 연결 안내문(MCP)만 새것이었다.
          표시가 있는 우리 파일만 고치고, 잇지 않은 곳에는 아무것도 새로 만들지 않는다(`refresh_packs` 와 같은 규칙).
        """
        tools = list(tools)
        done: dict[str, Any] = {}
        path = self.claude_code_path()
        try:
            if path.is_file():
                old = path.read_text(encoding="utf-8-sig", errors="ignore")
                new = self._render(tools)  # 언어가 바뀌었으면 old != new — 그 언어로 다시 쓴다
                if _MARK in old and old != new:
                    path.write_text(new, encoding="utf-8-sig")  # BOM — `_write_note` 주석
                    done["claude_code_skill"] = str(path)
        except OSError as exc:
            done["claude_code_skill_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        done["notes"] = self.refresh_packs(tools)
        return done

    def claude_code_path(self) -> Path:
        return self.home / ".claude" / "skills" / SKILL_NAME / "SKILL.md"

    #: 전역 지침 파일과, 그 지침이 가리킬 스킬 파일.
    def note_targets(self) -> dict[str, dict[str, Path]]:
        return {
            "claude_code": {"note": self.home / ".claude" / "CLAUDE.md", "guide": self.claude_code_path()},
            "codex": {"note": self.home / ".codex" / "AGENTS.md", "guide": self.home / ".codex" / f"{SKILL_NAME}.md"},
        }

    def note_status(self) -> dict[str, Any]:
        rows: dict[str, Any] = {}
        for client, paths in self.note_targets().items():
            note = paths["note"]
            text = note.read_text(encoding="utf-8-sig", errors="ignore") if note.exists() else ""
            rows[client] = {"path": str(note), "exists": note.exists(), "installed": self._has_note(text),
                            "guide_path": str(paths["guide"]), "guide_exists": paths["guide"].exists()}
        return rows

    def _write_note(self, note: Path, text: str) -> str:
        backup = ""
        if note.exists():
            old = note.read_text(encoding="utf-8-sig", errors="ignore")
            backup_path = note.with_name(f"{note.name}.bak-sonjari-{int(self.clock())}")
            backup_path.write_text(old, encoding="utf-8")
            backup = str(backup_path)
        note.parent.mkdir(parents=True, exist_ok=True)
        # ★ BOM 을 붙인다 (2026-09-16 실측). Codex 는 이 파일을 **PowerShell 로** 읽는다:
        #     powershell -NoProfile -Command Get-Content -Raw -LiteralPath ...\sonjari-guide.md
        #   5.1 은 BOM 없는 UTF-8 을 시스템 코드페이지(cp949)로 읽어 한글을 통째로 깨뜨린다.
        #   실측에서 Codex 가 지침대로 가이드를 열었는데 **받은 것이 「Ontelic(?⑦뀛由? MCP 瑜?..」** 였다 —
        #   지침은 들었는데 읽은 내용이 쓰레기였다. 사고 J 와 같은 가족이고, 이번엔 **사용자 PC 에
        #   우리가 설치하는 파일**이라 우리가 붙여야 한다.
        note.write_text(text, encoding="utf-8-sig")
        return backup

    @staticmethod
    def _without_note(text: str) -> str:
        """우리 블록을 뺀다 — 새 이름 블록과 옛 이름(ontelic-guide) 블록 모두."""
        for start, end in _NOTE_PAIRS:
            while start in text and end in text:
                head, rest = text.split(start, 1)
                _, tail = rest.split(end, 1)
                text = head.rstrip("\n") + ("\n\n" if head.strip() and tail.strip() else "") + tail.lstrip("\n")
        return text

    @staticmethod
    def _has_note(text: str) -> bool:
        return any(start in text for start, _ in _NOTE_PAIRS)

    def _remove_legacy_guides(self, client: str) -> list[str]:
        """옛 이름으로 **우리가 깔아 둔** 가이드 사본을 지운다 — **지금 잇는 클라이언트 것만**, 표시가 있는 것만.

        ★ 2026-09-29 코덱스 교차 검사: 클로드만 이어도 코덱스의 옛 가이드까지 지웠다. 코덱스 지침은 아직 그 옛 파일을
          가리키고 있어서 안내가 끊겼다. 그 클라이언트를 다시 이을 때 그쪽 옛 파일을 걷는다.
        """
        removed: list[str] = []
        prefix = LEGACY_SKILL_NAME.split("-")[0]
        if client == "codex":
            candidates = [(self.home / ".codex" / f"{LEGACY_SKILL_NAME}.md", _LEGACY_MARK)]
            candidates += [(path, _LEGACY_PACK_MARK) for path in (self.home / ".codex").glob(f"{prefix}-*.md")]
        else:
            candidates = [(self.home / ".claude" / "skills" / LEGACY_SKILL_NAME / "SKILL.md", _LEGACY_MARK)]
            candidates += [(path, _LEGACY_PACK_MARK)
                           for path in (self.home / ".claude" / "skills").glob(f"{prefix}-*/SKILL.md")]
        for path, mark in candidates:
            try:
                if path.is_file() and mark in path.read_text(encoding="utf-8-sig", errors="ignore"):
                    self._remove_pack_file(path)
                    removed.append(str(path))
            except OSError:
                continue
        return removed

    def install_note(self, client: str, tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """지침 파일에 우리 블록을 넣는다(있으면 갈아 끼운다). **사람이 쓴 나머지는 건드리지 않는다.**"""
        paths = self.note_targets().get(client)
        if paths is None:
            return {"ok": False, "error": "unknown_client"}
        # Codex 는 스킬 폴더가 없다 — 지침이 가리킬 사본을 옆에 둔다.
        if client == "codex":
            guide = paths["guide"]
            # 같은 이름의 **남의 파일**이면 덮지 않는다(2026-09-29 코덱스 교차 검사) — 클로드 스킬 쪽과 같은 규칙.
            if guide.exists() and _MARK not in guide.read_text(encoding="utf-8-sig", errors="ignore"):
                return {"ok": False, "error": "foreign_guide_exists", "path": str(guide)}
            guide.parent.mkdir(parents=True, exist_ok=True)
            guide.write_text(self._render(tools), encoding="utf-8-sig")  # BOM — `_write_note` 주석
        packs = self._write_pack_guides(client)
        self._remove_legacy_guides(client)
        note = paths["note"]
        old = note.read_text(encoding="utf-8-sig", errors="ignore") if note.exists() else ""
        body = self._without_note(old).rstrip("\n")
        # 언어가 바뀌면 블록이 달라져 text != old — 갱신(`refresh_installed` → `refresh_packs`) 때 그 언어로 갈아 끼운다.
        text = (body + "\n\n" if body else "") + render_note(paths["guide"], packs, self._lang()) + "\n"
        if text == old:
            return {"ok": True, "path": str(note), "backup": "", "guide_path": str(paths["guide"]),
                    "pack_guides": [str(path) for _, path in packs], "unchanged": True}
        backup = self._write_note(note, text)
        return {"ok": True, "path": str(note), "backup": backup, "guide_path": str(paths["guide"]),
                "pack_guides": [str(path) for _, path in packs]}

    def remove_note(self, client: str) -> dict[str, Any]:
        paths = self.note_targets().get(client)
        if paths is None:
            return {"ok": False, "error": "unknown_client"}
        for stale in self._pack_files(client):
            self._remove_pack_file(stale)
        note = paths["note"]
        if not note.exists():
            return {"ok": True, "removed": False}
        old = note.read_text(encoding="utf-8-sig", errors="ignore")
        if not self._has_note(old):
            return {"ok": True, "removed": False}
        backup = self._write_note(note, self._without_note(old))
        return {"ok": True, "removed": True, "path": str(note), "backup": backup}

    def manual_note(self) -> str:
        """Cursor 처럼 우리가 못 쓰는 곳에 사람이 직접 붙여 넣을 글."""
        return render_note(self.claude_code_path(), lang=self._lang())

    def zip_path(self) -> Path:
        return self.documents / f"{SKILL_NAME}.zip"

    def status(self) -> dict[str, Any]:
        path = self.claude_code_path()
        ours = path.exists() and _MARK in path.read_text(encoding="utf-8-sig", errors="ignore")
        return {
            "name": SKILL_NAME,
            "claude_code": {"installed": ours, "path": str(path),
                            "available": (self.home / ".claude").exists(),
                            "foreign": path.exists() and not ours},
            "zip": {"exists": self.zip_path().exists(), "path": str(self.zip_path())},
            "notes": self.note_status(),
        }

    def install_claude_code(self, tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
        path = self.claude_code_path()
        backup = ""
        if path.exists():
            old = path.read_text(encoding="utf-8-sig", errors="ignore")
            if _MARK not in old:
                # 같은 이름의 **남의 스킬**이면 덮지 않는다 — 사용자가 직접 만든 것일 수 있다.
                return {"ok": False, "error": "foreign_skill_exists", "path": str(path)}
            backup_path = path.with_name(f"SKILL.md.bak-{int(self.clock())}")
            backup_path.write_text(old, encoding="utf-8")
            backup = str(backup_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render(tools), encoding="utf-8-sig")  # BOM — `_write_note` 주석
        self._remove_legacy_guides("claude_code")
        return {"ok": True, "path": str(path), "backup": backup}

    def remove_claude_code(self) -> dict[str, Any]:
        path = self.claude_code_path()
        if not path.exists():
            return {"ok": True, "removed": False}
        if _MARK not in path.read_text(encoding="utf-8-sig", errors="ignore"):
            return {"ok": False, "error": "foreign_skill_exists", "path": str(path)}
        path.unlink()
        return {"ok": True, "removed": True}

    def build_zip(self, tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
        target = self.zip_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            # zip 안에는 스킬 이름 폴더 하나 — 올리는 화면이 폴더째 기대한다.
            archive.writestr(f"{SKILL_NAME}/SKILL.md", self._render(tools))
        target.write_bytes(buffer.getvalue())
        return {"ok": True, "path": str(target)}
