"""작은 창의 지침은 손에 맞춘다 — 손에 없는 도구 가족의 대목을 뺀다 (2026-10-12).

창 32,768 의 조사 판은 도구를 29개만 받는다(`tool_roster._SMALL_WINDOW_RESEARCH_BUNDLE` — 그날 아침에 81 → 29개로 줄였다).
그런데 공통 지침(`agent.AGENT_SYSTEM_PROMPT` · 13,856자 · 8천 토큰쯤)은 그대로 실었다: 구글 드라이브 · 메일 · 일정,
네이버 블로그 글쓰기, 한글 문서, 윈도우 앱 조작, 되돌리기, 코드 저장소 — **그 판의 손에 없는 도구의 사용법**이다.
그날 잰 고정 앞부분이 13,725토큰이고 답을 쓸 자리 8,192 를 떼면 걸음 기록에 쓸 자리는 6~8천 토큰이었다. 화면 하나를
읽으면 앞서 읽은 것이 밀려났다(같은 9B 가 창 32K 에서 온전한 줄 1~3/9, 64K 에서 7~8/9).

밀려난 것을 버리지 않게 하는 것(`transcript.read_ledger` · `prior_turn_block`)과 따로, **방 자체를 넓힌다.**

- 대목은 사람이 골라 표시한다(첫 줄의 앞머리 → 그 대목 다음에 남는 줄의 앞머리 → 이 가족이 손에 있으면 남긴다).
  도구 이름이 보인다고 기계적으로 빼지 않는다 — 처음에 그렇게 계산했더니 「봇 확인 화면은 통과하려 하지 마라」가
  다른 도구 이름을 말했다는 까닭으로 같이 빠졌다.
- 지키는 규칙(봇 확인 · 승인 · 믿을 수 없는 페이지 글 · 실패 뒤 되풀이 금지 · 막힌 것을 뚫지 않는다)에는 표시가 없다.
- 표시한 앞머리가 지침에 없으면 오류다. 지침을 고치면서 이 표가 조용히 헛도는 일이 없게(시험이 지금 지침으로 돌린다).
- 손이 그 가족을 다 가졌으면 받은 글 그대로다 — 큰 창의 판은 글자 하나 안 바뀐다.

그 판의 손 29개로 좁히면 13,856 → 8,044자(41%)다. 줄 수가 실제로 오르는지는 넣은 뒤에 잰다.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

#: (대목 첫 줄의 앞머리, 그 다음에 남는 줄의 앞머리 — 비면 한 줄짜리, 이 가족 가운데 하나라도 손에 있으면 남긴다)
SPANS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # 브라우저로 가라는 앞 줄(「- GitHub 은 브라우저로 간다」)은 표시하지 않는다 — github_search 가 손에 없어도 필요한 말이다(2026-10-21).
    ("- GitHub 저장소 탐색에 github_search", "", ("github_",)),
    ("- ★ **구글 것을 브라우저로 열지 마라.**", "- 내 PC의 파일은 순서가 이것이다:", ("google_",)),
    ("- 내 PC의 파일은 순서가 이것이다:", "- 파일을 만들거나 고칠 때는",
     ("local_search_files", "local_glob", "local_grep", "local_list_directory", "local_index_codebase")),
    ("- 파일을 만들거나 고칠 때는", "- 표나 문서로 남길 것은", ("local_write_file", "local_apply_edit")),
    ("- 이미 있는 문서를 손보라면", "- **각주는 한글(hwpx)에서만 된다.**", ("local_edit_document", "local_edit_spreadsheet")),
    ("- 사용자 구글 드라이브에 올릴 것은", "  한글 문서를 달라고 하면", ("google_",)),
    ("- Code 작업에서 선택한 저장소를 고친 뒤에는", "- 앞선 조사·조회 결과를 표나 문서로 만들 때는", ("local_run_project_command",)),
    ("- 이미 열려 있는 한글 문서는", "- **파일명·제목만 보고 답하지 마라.**", ("hwp_",)),
    ("네이버 블로그:", "브라우저로 화면을 조작할 때", ("naver_blog_",)),
    ("- **같은 사이트에서 손으로 뚫어냈으면 site_draft_recipe", "- **사용자가 사이트를 지목하면 그 사이트부터 연다.**", ("site_draft_recipe",)),
    ("  ★ **카테고리는 누르는 것이 아니라 올려놓는 것이다.**", "  ★ **`browser_fill` 로 글자만 넣고 끝내면", ("browser_hover",)),
    ("  ★ **`browser_fill` 로 글자만 넣고 끝내면", "  ★ **정렬을 바꾸라거나", ("browser_pick_suggestion",)),
    ("  ★ **정렬을 바꾸라거나", "  ★ `browser_pick_suggestion` 이 `suggestion_not_found` 로 답하면", ("browser_select_option",)),
    ("  ★ `browser_pick_suggestion` 이 `suggestion_not_found` 로 답하면", "  ★ 위 표가 안 맞는 화면도 있다.", ("browser_pick_suggestion",)),
    ("- **요소를 못 찾으면 셀렉터를 지어내지 마라.**", "- 클릭이 가로막히면", ("browser_probe_frames", "ui_find_target")),
    ('- ★ **"되돌려/취소해/무르자/방금 거 지워"는', "- **봇 확인(캡차) 화면이 뜨면", ("undo_",)),
    ("- Google Drive의 **기존 파일은 고치지 마라.**", "- Gmail 발송, Calendar 일정", ("google_",)),
    ("- Gmail 발송, Calendar 일정", "- 로컬 파일은 허용된 경로만 읽는다.", ("google_gmail_", "google_calendar_", "naver_blog_")),
    ("- `claude_code_delegate`는", "- 프로그램 실행과 파일 열기처럼", ("claude_code_delegate",)),
    ("- Windows 앱은 먼저 UIA snapshot/ref를 사용하라.", "- snapshot의 ref만 클릭에 사용하고", ("windows_",)),
)
#: 「화면 상황에 따라 도구를 골라라」 표의 줄이 권하는 도구.
_ROW_TOOL = re.compile(r"`((?:browser|ui)_[a-z_]+)`")


def slim_contract(text: str, hands: Iterable[str]) -> str:
    """손에 있는 도구로 좁힌 지침. 손이 지침이 말하는 가족을 다 가졌으면 받은 글 그대로다."""
    held = tuple(str(name) for name in hands)

    def has(families: tuple[str, ...]) -> bool:
        return any(name.startswith(family) for name in held for family in families)

    lines = text.split("\n")
    for start, stop, families in SPANS:
        begin = next((index for index, line in enumerate(lines) if line.startswith(start)), None)
        if begin is None:
            raise ValueError(f"지침에 이 대목이 없다: {start}")
        if stop:
            end = next((index for index in range(begin + 1, len(lines)) if lines[index].startswith(stop)), None)
            if end is None:
                raise ValueError(f"대목의 끝을 못 찾았다: {start} → {stop}")
        else:
            end = begin + 1
        if not has(families):
            del lines[begin:end]
    kept = []
    for line in lines:
        tools = _ROW_TOOL.findall(line) if line.startswith("  | ") else []
        if tools and not any(tool in held for tool in tools):
            continue
        kept.append(line)
    return "\n".join(kept)
