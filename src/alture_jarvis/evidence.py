"""도구가 **실제로 무엇을 했는지** 한 줄로 남기는 원장.

걸음 장부(`agent_trace.steps`)는 도구 이름과 `ok` 와 성긴 증거뿐이라, 다음 넷을
구별하지 못한다.

    연 것          vs  본문을 읽은 것
    새 출처        vs  같은 출처를 또 연 것
    읽기 전용 판   vs  거기서 생긴 쓰기
    어느 요구를 뒷받침한 증거인가

마지막 줄은 실제로 터졌다(2026-09-02). 사람인에서 상세 셋을 열어 읽고, 답의 표에는
**목록에서만 본 다른 회사 둘**을 「정규직·경력 3년↑·마감 10.01」까지 단정해 적었다.
개수 대조는 「3개 읽음」으로 통과시켰다 — 숫자는 맞고 내용은 틀렸다.

이 모듈은 **계측만 한다.** 완료 판정에 연결하지 않는다. 먼저 재고, 숫자가 나온
뒤에 붙일지 정한다.

## 왜 도구가 아니라 길목에서 만드나

산출물 처리를 만드는 도구마다 붙였다가 `sandbox_run` 으로 새어 무력화된 적이
있다. 도구는 늘어나고 사람은 등록을 잊는다. 그래서 **결과가 반드시 지나는 한
자리**(`agent._record_observation`)에서 만든다.

## 지금은 넷만

전체 도구를 한 번에 옮기지 않는다. 수직 슬라이스로 넷을 먼저 세우고, 이 원장으로
숫자가 나온 뒤에 넓힌다.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlsplit, urlunsplit

#: 증거의 종류. `page_open` 과 `body_read` 를 가르는 것이 이 원장의 존재 이유다.
TYPE_BODY_READ = "body_read"
TYPE_PAGE_OPEN = "page_open"
#: **목록을 본 것.** 연 것도 읽은 것도 아니다 — 후보 이름만 본 상태다.
#:
#: ★ 2026-09-02 사고의 정확한 자리가 여기였다. 사람인 목록에서 회사 둘을 보고
#:   상세를 안 열었는데 답에는 「정규직 · 경력 3년↑ · 마감 10.01」까지 적었다.
#:   목록 줄에 없는 값이다. 이 종류가 없으면 그 판이 「도구 잘 썼다」로 보인다.
TYPE_LISTING = "listing"
TYPE_ARTIFACT = "artifact"
TYPE_MUTATION = "mutation"
TYPE_VERIFICATION = "verification"

#: 무엇에 손을 댔나.
EFFECT_READ_LOCAL = "read_local"
EFFECT_READ_WEB = "read_web"
EFFECT_WRITE_LOCAL = "write_local"

#: 쓰기로 세는 효과. 읽기 전용 판에서 이게 생기면 정책이 깨진 것이다.
WRITE_EFFECTS = frozenset({EFFECT_WRITE_LOCAL})


@dataclass(frozen=True, slots=True)
class _Spec:
    effect: str
    type: str
    #: 출처를 담은 키들. 앞에서부터 있는 것을 쓴다.
    source_keys: tuple[str, ...]
    #: 본문을 담은 키들. 있으면 해시한다. 비면 본문 없는 증거다.
    body_keys: tuple[str, ...] = ()
    #: 출처를 어떻게 정규화하나. `path` · `url` · `query`.
    #: 검색은 주소가 없다 — **무엇을 물었는가**가 그 목록의 신원이다.
    source_kind: str = "path"
    #: **후보를 연 것인가, 그냥 이동한 것인가.**
    #:
    #: ★ 2026-09-03 실측. 「열어 놓고 본문을 안 읽은 곳 1」이 잡혔는데 열어 보니
    #:   `https://kmong.com/` — 검색하러 들어간 **사이트 첫 화면**이었다. 후보가
    #:   아니다. 이동까지 같이 세면 이 지표가 거짓말을 한다.
    candidate_open: bool = False


#: **도구 → 무슨 일을 했나.** 새 도구를 넣을 때는 이 표와 검사를 같이 고친다.
#:
#: ★ 처음에는 넷만 넣었다가 **첫 라이브 판에서 바로 구멍이 났다**(2026-09-03).
#:   모델은 `.md` 를 `local_read_document` 로 읽는데 표에 없어서, 문서를 제대로
#:   읽은 판이 「증거 0」으로 남았다. 그리고 `local_write_file` 이 빠져 있으면
#:   **「읽기 전용 위반 0건」이 거짓말이 된다** — 그 문으로 쓰면 안 세어진다.
#:   재는 자에 구멍을 두고 시작할 수는 없다.
MANIFEST: dict[str, _Spec] = {
    # ── 본문을 읽었다 ─────────────────────────────────────────────────
    "local_read_text_file": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("path",), ("content",), "path"
    ),
    "local_read_document": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("path",), ("content",), "path"
    ),
    "browser_extract": _Spec(
        EFFECT_READ_WEB, TYPE_BODY_READ, ("url",), ("text", "content"), "url"
    ),
    # ★ 2026-10-18 LH 공고 판(760b04f4): 받기가 그 자리에서 문서를 읽어 본문(`content`)을 싣는다 — 그건 읽은 것이다.
    #   이 표에 없으면 받은 PDF 로 맞게 답해도 근거 대조의 원문이 0 건이라 「읽지 않고 적었다」가 선다.
    #   본문 없이 파일만 받은 판(압축·실행 파일 · 못 읽은 문서)은 `_split_by_result` 가 「연 것」으로 내린다.
    "browser_download": _Spec(
        EFFECT_READ_WEB, TYPE_BODY_READ, ("path",), ("content",), "path"
    ),
    # ── 열었다 (본문은 아직 없다) ─────────────────────────────────────
    # ★ 여는 것은 읽는 것이 아니다. 목록에서 눌러 들어간 것뿐이다.
    # 목록에서 **후보를 눌러 들어간 것.** 이걸 읽지 않으면 그게 사고다.
    "browser_open_result": _Spec(
        EFFECT_READ_WEB, TYPE_PAGE_OPEN, ("url",), (), "url", candidate_open=True
    ),
    # 주소로 **이동한 것.** 후보가 아니다 — 사이트 첫 화면도 여기로 온다.
    "browser_open": _Spec(EFFECT_READ_WEB, TYPE_PAGE_OPEN, ("url",), (), "url"),
    # ── 목록만 봤다 ───────────────────────────────────────────────────
    # 후보 이름만 본 상태다. 목록 줄에 없는 값(고용형태·마감일)을 답에 적으면
    # 그것은 읽은 것이 아니라 지어낸 것이다 — 2026-09-02 사고의 정확한 자리.
    "browser_site_search": _Spec(
        EFFECT_READ_WEB, TYPE_LISTING, ("url",), (), "url"
    ),
    "browser_search": _Spec(EFFECT_READ_WEB, TYPE_LISTING, ("query",), (), "query"),
    "browser_snapshot": _Spec(EFFECT_READ_WEB, TYPE_LISTING, ("url",), (), "url"),
    # 레시피 실행. **한 도구가 두 일을 한다** — 검색도 하고 스크랩 같은 쓰기도 한다.
    # 결과로 갈린다(`_split_by_result` 참고): `undo_action` 이 있으면 되돌릴 것이
    # 생겼다는 뜻이니 쓰기, `result_url` 만 있으면 목록이다.
    "site_run": _Spec(EFFECT_READ_WEB, TYPE_LISTING, ("result_url",), (), "url"),
    "local_list_directory": _Spec(
        EFFECT_READ_LOCAL, TYPE_LISTING, ("path",), (), "path"
    ),
    "local_search_files": _Spec(
        EFFECT_READ_LOCAL, TYPE_LISTING, ("query",), (), "query"
    ),
    "local_glob": _Spec(EFFECT_READ_LOCAL, TYPE_LISTING, ("path", "pattern"), (), "path"),
    # ── 게임 팩: 유니티 (2026-09-27) ─────────────────────────────────────
    # ★ 처음에 이 표에 안 넣어서, 레시피를 10번 돌린 판의 원장에 유니티가 **한 줄도** 없었다.
    #   훑기는 개수·경로 목록이고, 레시피는 유니티가 에셋을 실제로 열어 읽은 결과다(결과 해시를 싣는다).
    # ★ 2026-10-01 테스터 시험: 프로젝트 정보는 **실제 파일 크기를 잰 상위 10개**(largest_assets)를 준다. 목록으로 두었더니
    #   거기서 옮긴 16MB 텍스처 넷에 「읽지 않고 적었다」 헛경고가 붙었다 — 원문 그대로의 자료라 본문 읽기로 센다.
    "unity_project_info": _Spec(EFFECT_READ_LOCAL, TYPE_BODY_READ, ("project",), (), "path"),
    "unity_run_recipe": _Spec(EFFECT_READ_LOCAL, TYPE_BODY_READ, ("project",), (), "path"),
    # 열린 에디터(2026-09-27 · 2단계) — 읽기는 계층·콘솔 목록, 바꾸기는 씬 변경(에디터 Undo 에 남는다).
    "unity_editor_status": _Spec(EFFECT_READ_LOCAL, TYPE_LISTING, ("project",), (), "path"),
    "unity_editor_look": _Spec(EFFECT_READ_LOCAL, TYPE_LISTING, ("what", "target"), (), "query"),
    "unity_editor_change": _Spec(EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("op", "target", "name"), (), "path"),
    "unity_editor_undo": _Spec(EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("project",), (), "path"),
    "google_drive_search": _Spec(
        EFFECT_READ_WEB, TYPE_LISTING, ("query",), (), "query"
    ),
    "google_gmail_search": _Spec(
        EFFECT_READ_WEB, TYPE_LISTING, ("query",), (), "query"
    ),
    # ── 썼다 ──────────────────────────────────────────────────────────
    "local_write_document": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_ARTIFACT, ("output_path", "path"), (), "path"
    ),
    "local_write_file": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_ARTIFACT, ("path",), (), "path"
    ),
    # 디자인된 장표(2026-10-25). 마지막 장에서만 PPTX 경로가 생긴다 — 그 전 장은 경로 없이 「저장함」이다.
    "local_make_slide": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_ARTIFACT, ("output_path", "path"), (), "path"
    ),
    # 한글 → PDF(2026-10-17). 결과에는 원본을 `source_path` 로만 싣는다 — `path` 로 실으면 원본이 산출물로 둔갑한다.
    "hwp_export_pdf": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_ARTIFACT, ("output_path",), (), "path"
    ),
    "local_apply_edit": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("path",), (), "path"
    ),
    "local_edit_document": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("output_path", "path"), (), "path"
    ),
    "local_edit_spreadsheet": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("output_path", "path"), (), "path"
    ),
    # ── 2026-09-04 에 메운 구멍 ───────────────────────────────────────
    # 원장에 19 개가 등록돼 있는데 실제로 쓰인 도구는 83 개였다. 빠진 것들이
    # 조용히 「안 읽었다」·「쓰기 0 건」을 만들고 있었다. 아래는 **실제 트레이스에서
    # 키를 세어 보고** 넣은 것들이다(추측으로 넣으면 출처가 안 잡혀 무동작이 된다).
    "google_drive_read": _Spec(
        EFFECT_READ_WEB, TYPE_BODY_READ, ("url", "file_id"), ("read", "content"), "url"
    ),
    "browser_read": _Spec(
        EFFECT_READ_WEB, TYPE_BODY_READ, ("url",), ("text", "content"), "url"
    ),
    "local_index_codebase": _Spec(
        EFFECT_READ_LOCAL, TYPE_LISTING, ("root", "path"), (), "path"
    ),
    "browser_links": _Spec(EFFECT_READ_WEB, TYPE_LISTING, ("url",), (), "url"),
    # 바깥에 자국이 남는 것들. 이게 빠져 있으면 「읽기 전용 위반 0 건」이 거짓이 된다.
    "local_delete_file": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("path",), (), "path"
    ),
    "google_drive_write": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("url", "file_id"), (), "url"
    ),
    "google_gmail_send": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("message_id", "thread_id"), (), "path"
    ),
    "google_calendar_create": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("event_id",), (), "path"
    ),
    "google_calendar_delete": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("event_id",), (), "path"
    ),
    "naver_blog_save_draft": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("url",), (), "url"
    ),
    "naver_blog_publish": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("url",), (), "url"
    ),
    "naver_blog_upload_image": _Spec(
        EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("url",), (), "url"
    ),
    # 결과로 갈린다 — `_split_by_result` 참고.
    "sandbox_run": _Spec(EFFECT_READ_LOCAL, TYPE_VERIFICATION, ("run_id",), (), "path"),
    "skill_read": _Spec(EFFECT_READ_LOCAL, TYPE_BODY_READ, ("name",), ("body",), "path"),
    # ── 2026-09-05: **우리 데이터를 읽는 도구들** ─────────────────────
    #
    # 앞 사람이 「다음 차례」로 지목한 자리다. 웹과 달리 이 도구들은 **자료 자체를
    # 돌려준다** — 목록을 주고 상세를 따로 열게 하는 것이 아니라, 그 안에 답이
    # 들어 있다. 그래서 `listing` 이 아니라 `body_read` 다.
    #
    # ★ 이게 실제로 고치는 것: 근거 대조(`read_bodies`)는 `body_read` 만 재료로
    #   삼는다. 등록이 없으면 자사 데이터로 답한 판은 **원문이 0 건**이 되어,
    #   맞게 답해도 「읽지 않고 적었다」 경고가 선다. 정찰기도 지울 수 없다 —
    #   지울 근거가 원장에 없으니까.
    #
    # 키는 **실제 트레이스 50 건에서 세어** 넣었다(추측 금지):
    #
    #   admission_quant_lookup            args target_labels[]  · ev targets[]
    #   admission_major_profile_lookup    args target_labels[]  · ev evidence_items[]
    #   admission_major_semantic_search   args query            · ev evidence_items[]
    #   admission_candidates_by_grade     args major_query      · ev evidence[]
    #   career_strategy_lookup            args major/job/region · ev evidence_items[]
    #
    # `source` 키처럼 매 호출 같은 식별자는 **일부러 안 쓴다.** 같은 값이라
    # 출처로 쓰면 모든 조회가 한 출처로 뭉쳐 「같은 곳을 또 읽었다」가 된다.
    "admission_quant_lookup": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("target_labels",), ("targets",), "query"
    ),
    "admission_major_profile_lookup": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("target_labels",), ("evidence_items", "targets"), "query"
    ),
    "admission_major_semantic_search": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("query",), ("evidence_items",), "query"
    ),
    "admission_candidates_by_grade": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("major_query",), ("evidence",), "query"
    ),
    "career_strategy_lookup": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("major", "job", "region"), ("evidence_items",), "query"
    ),
    # ★ **표본이 0 이라 못 셌던 도구** (2026-09-05 저녁).
    #
    #   위 다섯은 최근 2,500 판에서 키를 세어 넣었는데, 이 도구는 그 표본에
    #   **한 번도 안 나왔다**(0 회). 그래서 「실제 트레이스에서 센 것만 넣는다」는
    #   규율을 지키면 넣을 수가 없었고, 바로 그날 저녁 라이브 판에서 **세 번**
    #   불렸다. 원장은 그 세 번을 통째로 못 봤다.
    #
    #   교훈: 「최근 N 판에 없다」는 「안 쓰인다」가 아니다. 도구 카탈로그에 있는데
    #   원장에 없는 것은 언제든 이렇게 조용히 빠진다. 키는 그 라이브 판에서 셌다:
    #
    #       args  {"student_value": 2.4, "target_label": "명지대학교 컴퓨터공학과"}
    #       ev    target_label · probability · band · q50 · q70 · metric · evidence[]
    #
    #   `evidence` 가 본문이다 — 확률을 산출한 컷 기록이 거기 들어 있다.
    "admission_probability_simulate": _Spec(
        EFFECT_READ_LOCAL, TYPE_BODY_READ, ("target_label",), ("evidence", "curve"), "query"
    ),
    # 프로젝트에서 명령을 돌린 것. 최근 2,500 판에서 **390 회**로 미등록 중 1 위였다.
    #
    # `verification` 이고 본문 키는 **일부러 비운다.** `stdout` 을 본문으로 삼으면
    # pytest 출력이 근거 대조의 원문이 되어, 답에 적은 이름이 로그에 우연히 있으면
    # 경고가 지워진다. 검증은 「돌려서 통과했다」는 사실이지 읽은 자료가 아니다.
    "local_run_project_command": _Spec(
        EFFECT_READ_LOCAL, TYPE_VERIFICATION, ("command", "path"), (), "query"
    ),
}

#: 도구가 스스로 낸 해시. 본문 키가 없어도 이걸로 「같은 내용인가」를 안다.
#: `local_write_file` 은 `sha256` 을 돌려준다 — 있는 것을 안 쓰면 그것도 구멍이다.
_HASH_KEYS = ("sha256", "content_sha256", "hash")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    type: str
    effect: str
    #: 정규화한 출처. 같은 곳을 두 번 읽었는지 **이것으로** 안다.
    source_id: str
    tool: str
    ok: bool
    #: 본문 해시. 같은 출처라도 내용이 달라졌는지 이걸로 갈린다. 본문이 없으면 빈 값.
    content_hash: str = ""
    #: 목록에서 **후보를 눌러 들어간 것**인가. 이동(사이트 첫 화면)은 아니다.
    #: 「열어 놓고 안 읽었다」는 후보에만 물어야 한다.
    candidate: bool = False
    #: **누구 눈이 봤나.** 이 증거를 만든 판과 걸음.
    #:
    #: ★ 멀티 에이전트의 열쇠다. 지금 근거 대조는 **부모의 전사**를 읽는데,
    #:   하위 에이전트가 대신 읽으면 그 도구 결과는 부모 전사에 안 들어온다 —
    #:   그러면 검사가 아무 경고 없이 통과한다(`if not source: return ""`).
    #:   주인이 적혀 있어야 원문을 되짚을 수 있다.
    job_id: str = ""
    step: int = 0
    #: 어느 절을 뒷받침하나. 판이 끝난 뒤 `attach_clauses` 가 채운다.
    supports_clause_ids: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: 출처 값이 **목록으로 오는 도구**가 있다. 한 줄로 이어 붙여 신원을 만든다.
#:
#: ★ 2026-09-05. 「키를 추측하지 마라」를 지키려고 실제 트레이스에서 키를 셌더니,
#:   우리 데이터 도구 둘이 출처를 **리스트로** 준다는 것이 드러났다:
#:
#:       admission_quant_lookup      target_labels = ["경희대학교 컴퓨터공학과"]
#:       local_run_project_command   command       = ["pytest", "tests/…", "-v"]
#:
#:   `record_for` 는 `isinstance(value, str)` 만 봤다. 그래서 이 둘은 **등록해도
#:   출처가 안 잡혀 조용히 무동작**이 됐을 것이다 — 앞 사람이 경고한 바로 그 함정을
#:   키가 아니라 **값의 모양** 쪽에서 다시 만난 것이다.
_SOURCE_LIST_MAX = 8


def _as_source_text(value: Any) -> str:
    """출처로 쓸 수 있는 문자열. 문자열이거나 문자열 목록이면 준다."""
    if isinstance(value, str):
        return value if value.strip() else ""
    if isinstance(value, (list, tuple)):
        parts = [item.strip() for item in value[:_SOURCE_LIST_MAX] if isinstance(item, str) and item.strip()]
        return " ".join(parts)
    return ""


#: 도구가 **구조화된 값으로 돌려준 숫자**를 걷을 때의 상한.
#: 판마다 이만큼만 들고 있는다 — 장부가 커지면 아무도 안 읽는다.
_NUMBERS_MAX = 400
#: 이보다 깊이 들어가지 않는다. 깊은 곳의 숫자는 답에 쓰이지 않는다.
_NUMBERS_DEPTH = 4

#: 세지 않는 숫자. 순번·좌표·식별자는 답의 주장이 아니다.
_NOT_A_CLAIM = frozenset(
    {
        "step", "rank", "index", "limit", "offset", "count", "polls", "ms",
        "took_ms", "elapsed_sec", "ready_ms", "element_count", "char_count",
        "line_start", "line_end", "x", "y", "width", "height", "id", "step_number",
    }
)


def numbers_in(evidence: dict[str, Any]) -> set[str]:
    """도구가 **필드로 돌려준 숫자**만 걷는다. 본문 글자는 안 본다.

    ## 왜 이것만 걷나 (2026-09-06)

    자사 데이터 판에서 도구가 `probability=0.0 · band=위험` 을 줬는데 답의 표에는
    `75.2%` 가 적혔고, 그 창작한 값 12 개를 `sandbox_run` 에 넣어 「평균 73.69%」
    까지 냈다. **모든 검사를 통과했다** — 근거 대조는 이름만 보고, 원장은
    「읽었나」까지만 알고, 정찰기는 부를 일이 없었다.

    막으려고 표본을 만들어 봤더니 **잴 수가 없었다.** 답의 숫자는 대개
    `browser_extract` 본문에서 오는데 본문은 `agent_trace` 에 안 들어간다(관측
    보관소에 있고 그건 메모리라 재기동에 사라진다). 그래서 「도구 결과에 없는
    숫자」를 세면 56% 가 나오는데 **대부분 내가 못 본 것**이었다.

    그래서 게이트를 먼저 만들지 않고 **잴 수 있게** 만든다. 여기서 걷는 것은
    도구가 필드로 준 숫자뿐이라 의미가 분명하다 — 본문에서 온 값과 섞이지 않는다.
    이것이 판마다 쌓이면 그때 「도구는 0.0 을 줬는데 답은 75.2 를 말했다」를
    표본으로 셀 수 있다.

    순번·좌표·소요시간은 뺀다. 그건 답이 주장하는 값이 아니다.
    """

    found: set[str] = set()

    def walk(node: Any, depth: int, key: str = "") -> None:
        if len(found) >= _NUMBERS_MAX or depth > _NUMBERS_DEPTH:
            return
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            if key.lower() in _NOT_A_CLAIM:
                return
            # 정수는 정수로, 소수는 소수로. `1.0` 과 `1` 을 갈라 두면 대조가 샌다.
            found.add(str(int(node)) if float(node).is_integer() else repr(float(node)))
            return
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, depth + 1, str(name))
            return
        if isinstance(node, (list, tuple)):
            for value in node[:50]:
                walk(value, depth + 1, key)

    walk(evidence or {}, 0)
    return found


#: 날짜. 창작 검사의 대상이 아니고, **양쪽이 다르게 읽는 제일 큰 원인**이다.
#
# ★ 2026-09-09 실측. 도구가 `마감일 2026.09.13` 을 줬고 답은 `~09.13(일)` 이라
#   썼다. 같은 날짜인데 두 쪽이 이렇게 갈렸다:
#
#       도구 "2026.09.13"  ->  {"2026.09"}    (점 뒤는 건너뛴다)
#       답   "09.13"       ->  {"9.13"}
#
#   겹치는 값이 없으니 「창작」으로 찍혔다. 사실은 표기 차이였다. 창작 검사의
#   거짓 고발은 그 검사를 꺼 버리게 만든다 — 그래서 **양쪽에서 같이** 지운다.
_DATE_SHAPES = re.compile(
    r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}"
    r"|\d{1,2}\s*[.\-/]\s*\d{1,2}\s*\("
    # ★ 2026-10-03 K-Startup 5차: 엑셀은 「2026.10.06」, 답의 표 칸은 「10.06」 — 괄호가 없어 소수로 읽혀 마감일 다섯이
    #   「근거 없는 숫자」로 찍혔다. 두 자리 월.두 자리 일(앞이 통화·숫자 아님, 뒤가 숫자·%·통화 아님)도 날짜로 지운다.
    #   역검증(과거 답 997판): 바뀌는 판 3개 — 셋 다 진짜 날짜(이 판 · 「~02.06」 기간 · 「09.03~09.04」), 가격·소수 0.
    r"|(?<![\d.,$€£₩])(?:0[1-9]|1[0-2])\.(?:0[1-9]|[12]\d|3[01])(?![\d.%]|\s*(?:달러|원|USD|usd|%))"
    r"|\d{4}년\s*\d{1,2}월(?:\s*\d{1,2}일)?"
    r"|\d{1,2}월\s*\d{1,2}일"
    r"|(?<![A-Za-z0-9])D\s*-\s*\d{1,3}"
)


#: 글 속의 숫자. 천 단위 쉼표와 소수를 함께 잡는다.
# ★ 뒤돌아보기가 거르는 것은 **ASCII** 낱말 글자다, `\w` 가 아니다. 파이썬에서
#   `\w` 는 한글도 잡는다 — 그래서 `(?<![\w.])` 는 라벨에 붙은 숫자를 통째로
#   못 봤다. 추출기가 DOM 조각을 이어 붙이면 띄어쓰기가 사라진다:
#
#       "예상 기간360일"   -> 없음     "쪽수432쪽" -> 없음
#       "예상 기간: 360일" -> 360      (콜론이 끼어서 겨우 잡혔다)
#
#   2026-09-07 실측: `예상 기간360일` 이 적힌 페이지를 읽고 답에 **360** 을 썼는데
#   검사가 「근거 없음」이라 했다. 읽은 쪽이 맞고 재는 쪽이 틀렸다. 라틴 글자에
#   붙은 숫자는 계속 뺀다 — 그건 식별자와 판 번호다(`v2`, `call_12`).
_NUMBER_IN_TEXT = re.compile(r"(?<![0-9A-Za-z_.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")

#: 너무 흔해서 증거가 못 되는 값. 이걸 세면 진짜 발견이 파묻힌다.
_TRIVIAL_NUMBERS = frozenset(
    {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "100"}
)

#: 본문에서 걷는 상한. 한 걸음이 판 기록을 통째로 먹으면 안 된다.
_BODY_NUMBERS_MAX = 600
#: 한 문자열에서 볼 글자 수. `browser_extract` 본문은 3만 자까지 온다.
_BODY_TEXT_MAX = 40_000


#: 원 금액 뒤·앞 표지와 만·억 단위. 「만큼」은 단위가 아니다.
_WON_AFTER = re.compile(r"\s?원")
_WON_BEFORE = re.compile(r"(?:₩|KRW)\s?$")
_MAN_AFTER = re.compile(r"\s?만(?!큼)")
_EOK_AFTER = re.compile(r"\s?억(?:\s?(\d{1,3}(?:,\d{3})+|\d+)\s?만)?")


def _korean_unit_readings(digits: str, frac: str, text: str, start: int, end: int) -> list[str]:
    """같은 금액을 원·만원·억원으로 바꿔 쓴 값 (2026-10-02 K-Startup 판).

    원문은 「총 교육비 12,016,000원 · 자부담 400,000원」, 답은 「1,201만원 · 40만원」이었다. 단위만 바꾼 것인데
    숫자 검사가 둘 다 「근거 없음」으로 찍었다 — 거짓 고발은 그 검사를 꺼 버리게 만든다(위 날짜 주석과 같은 병).
    그래서 **읽은 쪽(seen)에만** 다른 단위로 읽은 값을 더한다. 답 쪽에 더하면 「1202」 같은 헛 주장이 경고에 끼어든다.

    - `12,016,000원` → 만원 1201(버림)·1202(반올림). 억 이상이면 억 단위도(1.5억 꼴 소수 한·두 자리 포함).
    - `1,201만` → 12010000 · `3억` → 300000000 · `1억 2,000만` → 120000000.

    원 표지(`원`·`₩`·`KRW`)가 붙은 1만 이상 금액만 줄여 읽는다. 표지 없는 큰 수(조회수·ISBN)까지 줄이면
    작은 숫자가 근거로 쏟아져 진짜 창작을 가린다.
    """
    readings: list[str] = []
    whole = int(digits)
    value = float(f"{digits}.{frac}") if frac else float(whole)
    tail = text[end:end + 16]
    eok = _EOK_AFTER.match(tail)
    if eok:
        total = value * 100_000_000 + (int(eok.group(1).replace(",", "")) * 10_000 if eok.group(1) else 0)
        if total.is_integer():
            readings.append(str(int(total)))
        return readings
    if _MAN_AFTER.match(tail):
        total = value * 10_000
        if total.is_integer():
            readings.append(str(int(total)))
        return readings
    if frac or whole < 10_000:
        return readings
    if not (_WON_AFTER.match(tail) or _WON_BEFORE.search(text[max(0, start - 5):start])):
        return readings
    readings += [str(whole // 10_000), str(round(whole / 10_000))]
    if whole >= 100_000_000:
        readings.append(str(whole // 100_000_000))
        for places in (1, 2):
            short = round(whole / 100_000_000, places)
            if not short.is_integer():
                readings.append(repr(short))
    return readings


#: 영어 줄임 단위(「66.6k」 · 「1.2M」 · 「11 million」). 뒤에 라틴 글자가 이어지면 단위가 아니다(「5km」 · 「3MB」).
_SCALE_AFTER = re.compile(r"\s?(?:([kKmMbB])(?![A-Za-z])|(thousand|million|billion)\b)", re.IGNORECASE)
_SCALES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def _scaled_unit_readings(digits: str, frac: str, text: str, end: int) -> list[str]:
    """영어 줄임 단위로 적힌 수를 풀어 쓴 값 (2026-10-24 밤 측정 판).

    깃허브는 별 수를 「66.6k」로 보여 주고, 모델은 엑셀에 66,600 이라고 적는다. 레딧 글의 「11 million」은 답에서
    「1,100만」이 됐다. 둘 다 숫자 검사가 「읽은 자료에 없는 숫자」로 막았고, 깃허브 과제 6판 중 5판이 그 막힘에서
    파일을 못 쓰고 접혔다. 한국어 단위(`_korean_unit_readings`)와 같은 병이라 같은 방식으로 고친다 —
    **읽은 쪽(seen)에만** 풀어 쓴 값을 더한다. 답 쪽에 더하면 헛 주장이 경고에 끼어든다.

    - `66.6k` → 66600 · `1.2M` → 1200000 · `11 million` → 11000000 과 만 단위 1100.
    - 반올림된 값(66.6k 의 실제 값은 66,550~66,649)을 정확한 값처럼 쓴 것은 지어낸 것이 아니라 표기라 받는다.
    """
    scale = _SCALE_AFTER.match(text[end:end + 12])
    if not scale:
        return []
    word = (scale.group(1) or scale.group(2) or "").lower()
    factor = _SCALES.get(word)
    if not factor:
        return []
    total = Decimal(f"{digits}.{frac}" if frac else digits) * factor
    if total != total.to_integral_value():
        return []
    whole = int(total)
    readings = [str(whole)]
    if whole >= 10_000:
        readings += [str(whole // 10_000), str(round(whole / 10_000))]
    return readings


def numbers_in_body(evidence: dict[str, Any]) -> set[str]:
    """도구가 **본문 글자로 돌려준 숫자.** `numbers_in` 과 짝이다.

    ## 왜 따로 있나 (2026-09-07)

    `numbers_in` 은 필드만 걷는다 — 뜻이 분명해서다. 그런데 산출물 벤치를 돌려
    보니 **답에 적힌 숫자가 거의 전부 본문에서 왔다.** 위시켓 `360일`·`5명`,
    YES24 `432쪽`·ISBN 13 자리 — 하나도 필드에 없다. 그래서 「도구가 준 적 없는
    숫자」를 세면 **6/6 · 34/34 · 10/10 으로 100% 위반**이 찍혔다. 살아 있는
    페이지를 직접 찍어 보니 그 값들은 **전부 실재했다.** 위반이 아니라 눈금의
    실명이었다 — `numbers_in` 주석이 「56% 는 대부분 내가 못 본 것」이라고
    적어 둔 바로 그 자리다.

    그래서 본문 숫자를 **섞지 않고 따로** 걷는다. 둘을 합치면 필드 대조가 뜻을
    잃고, 안 걷으면 대조 자체가 못 돈다.

        필드 숫자   — 도구가 `applicants: 5` 라고 말했다. 뜻이 분명하다.
        본문 숫자   — 도구가 준 글자 어딘가에 `5` 가 있었다. 약하지만 실재한다.

    답의 숫자가 **둘 중 어디에도 없으면** 그것이 창작이다.
    """

    found: set[str] = set()

    def take(text: str) -> None:
        # 날짜는 양쪽에서 같은 방식으로 지운다. 한쪽만 지우면 거짓 고발이 된다.
        clean = _DATE_SHAPES.sub(" ", text[:_BODY_TEXT_MAX])
        for match in _NUMBER_IN_TEXT.finditer(clean):
            if len(found) >= _BODY_NUMBERS_MAX:
                return
            whole, frac = match.group(1), match.group(2)
            digits = whole.replace(",", "")
            for scaled in _korean_unit_readings(digits, frac, clean, match.start(), match.end()):
                if scaled not in _TRIVIAL_NUMBERS:
                    found.add(scaled)
            for scaled in _scaled_unit_readings(digits, frac, clean, match.end()):
                if scaled not in _TRIVIAL_NUMBERS:
                    found.add(scaled)
            if frac:
                value = f"{digits}.{frac}".rstrip("0").rstrip(".")
                if "." in value:
                    found.add(repr(float(value)))
                    continue
                # `3.0` 은 `3` 이라는 주장이다. 적은 방법에 따라 갈리면 안 된다.
                digits = value
            if digits not in _TRIVIAL_NUMBERS:
                found.add(str(int(digits)))

    def walk(node: Any, depth: int) -> None:
        if len(found) >= _BODY_NUMBERS_MAX or depth > _NUMBERS_DEPTH:
            return
        if isinstance(node, str):
            take(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for value in node[:50]:
                walk(value, depth + 1)

    walk(evidence or {}, 0)
    return found


def code_string_values(code: str) -> list[str]:
    """코드 속 **따옴표 안 글자만** — 표에 들어간 값(「연봉 2,762만원」)은 남고, 열 너비·줄 높이·순번 같은 코드 숫자는 빠진다.

    쓴 내용의 숫자를 세는 자리 둘(바깥 AI 요약 `delegation` · 쓰기 전 숫자 문 `agent.ungrounded_write_numbers`)이 같이 쓴다.
    10-02 에 한쪽만 고쳐 다른 쪽이 10-05 까지 서식 숫자를 「읽은 자료에 없는 숫자」로 셌다 — 눈금은 한 자리에 둔다.
    """
    import ast

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return [match.group(2) for match in re.finditer(r"(['\"])(.*?)\1", code)]
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def unsupported_numbers(claimed: set[str], seen: set[str]) -> set[str]:
    """답의 숫자 중 **도구가 준 적 없는 것.** 도구 값을 반올림한 것은 준 것으로 본다 (2026-09-24).

    라이브: 계산 상자가 `15.666666666666666` 을 냈고 답은 `15.67` 이었다 — 반올림은 창작이 아닌데 「근거 없음」으로 찍혔다.
    답이 소수(자릿수 k ≥ 1)이고, 도구가 낸 **더 긴** 소수를 k 자리로 반올림하면 같을 때만 받는다. 정수로 반올림한 것은
    안 받는다 — 16 은 15.5~16.49 어디서든 나오니, 받으면 창작을 가린다.
    """
    left = set(claimed) - set(seen)
    if not left:
        return left
    decimals = [value for value in seen if "." in value]
    kept: set[str] = set()
    for value in left:
        if "." not in value:
            kept.add(value)
            continue
        places = len(value.split(".", 1)[1])
        try:
            target = float(value)
            rounded = any(
                len(tool.split(".", 1)[1]) > places and round(float(tool), places) == target for tool in decimals
            )
        except ValueError:
            rounded = False
        if not rounded:
            kept.add(value)
    return kept


#: 문서 소제목의 **절 번호**(「### 2.4 리뷰엉이 형식 해부」 · 「## 3. 결론」) — 값이 아니라 차례다.
# ★ 2026-10-24 대표 판(ab760dc8): 「지금까지 조사한 것 MD 로」가 「읽은 자료에 없는 숫자」로 두 번 막혔는데, 앞 판 숫자를
#   빼고 남은 여섯 개(2.4 · 2.6 · 3.4 · 5.2 · 5.3 · 6.3)가 전부 소제목 번호였다. 점이 든 번호이거나 끝에 점이 붙은 것만 지운다 —
#   「## 37 stars」 같은 값은 남긴다(한 자리 번호는 원래 하찮은 숫자라 안 센다).
_SECTION_NUMBER = re.compile(r"(?m)^(\s{0,3}#{1,6}[ \t]+)(?:\d+(?:\.\d+)+\.?|\d+\.)(?=[ \t])")


def numbers_claimed_in(answer: str) -> set[str]:
    """답이 **주장한 숫자.** `numbers_in_body` 와 같은 정규화를 쓴다.

    두 쪽이 같은 규칙을 써야 대조가 대칭이 된다. 한쪽만 한글 붙은 숫자를 보면
    「답은 360 이라 적었는데 도구는 안 줬다」는 거짓 고발이 나온다 — 실제로 그랬다.
    """
    found: set[str] = set()
    text = _SECTION_NUMBER.sub(r"\1", answer or "")
    for whole, frac in _NUMBER_IN_TEXT.findall(_DATE_SHAPES.sub(" ", text)):
        digits = whole.replace(",", "")
        if frac:
            value = f"{digits}.{frac}".rstrip("0").rstrip(".")
            if "." in value:
                found.add(repr(float(value)))
                continue
            digits = value
        if digits not in _TRIVIAL_NUMBERS:
            found.add(str(int(digits)))
    return found


def canonical_source(value: str, *, kind: str = "path") -> str:
    """같은 곳을 같은 이름으로 부른다.

    파일은 대소문자·상대경로가 갈리고, 주소는 조각(`#...`)과 끝 슬래시가 갈린다.
    정규화를 안 하면 **같은 곳을 두 번 읽고 「2개 읽었다」**가 된다.

    검색에는 주소가 없다. **무엇을 물었는가**가 그 목록의 신원이다.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if kind == "query":
        return "q:" + " ".join(text.split()).lower()
    if kind == "path":
        try:
            return os.path.normcase(os.path.abspath(text))
        except (OSError, ValueError):
            return text
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    if not parts.scheme:
        return text
    path = parts.path.rstrip("/") or "/"
    # 질의는 남긴다 — 검색 결과 주소는 질의가 곧 신원이다.
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


def _body_hash(evidence: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        body = evidence.get(key)
        if isinstance(body, str) and body.strip():
            return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:16]
    # 본문을 안 실어 보내는 도구도 해시는 낼 수 있다. 있는 것을 안 쓰면 구멍이다.
    for key in _HASH_KEYS:
        digest = evidence.get(key)
        if isinstance(digest, str) and digest.strip():
            return digest.strip()[:16]
    return ""


def _split_by_result(tool: str, spec: _Spec, evidence: dict[str, Any]) -> _Spec:
    """**한 도구가 두 일을 하는** 경우, 결과를 보고 종류를 가른다.

    ★ 2026-09-03 실측. `site_run` 은 사람인 검색도 하고 스크랩(쓰기)도 한다.
      목록으로만 등록해 두면 그 도구로 한 쓰기가 **「읽기 전용 위반 0건」에서
      빠진다** — 지표가 거짓말을 한다. 인자가 아니라 **결과**로 가른다:
      `undo_action` 이 있다는 것은 되돌릴 것이 생겼다는 뜻이고, 그게 쓰기다.
    """
    if tool == "sandbox_run":
        # 상자 안에서 돌린 코드. **파일을 남겼으면 산출물이고, 아니면 확인이다.**
        # 인자(코드)로는 못 가른다 — 만들려고 썼는데 실패한 판이 실제로 있었다
        # (pandas 없음). 결과에 남은 것으로 가른다.
        if evidence.get("saved_to") or evidence.get("outputs"):
            return _Spec(EFFECT_WRITE_LOCAL, TYPE_ARTIFACT, ("run_id",), (), "path")
        return _Spec(EFFECT_READ_LOCAL, TYPE_VERIFICATION, ("run_id",), ("stdout",), "path")
    if tool == "browser_download":
        # 본문을 실어 왔을 때만 읽은 것이다. 파일만 받았으면 연 것까지다(2026-10-18 · 위 표의 설명).
        content = evidence.get("content")
        if isinstance(content, str) and content.strip():
            return spec
        # 출처는 저장한 파일뿐이다 — 못 받은 판(경로 없음)은 증거를 만들지 않는다.
        return _Spec(EFFECT_READ_WEB, TYPE_PAGE_OPEN, ("path",), (), "path")
    if tool != "site_run":
        return spec
    if evidence.get("undo_action"):
        return _Spec(EFFECT_WRITE_LOCAL, TYPE_MUTATION, ("result_url", "site"), (), "url")
    return spec


def record_for(
    tool: str,
    evidence: dict[str, Any],
    *,
    ok: bool,
    step: int,
    job_id: str = "",
    arguments: dict[str, Any] | None = None,
) -> EvidenceRecord | None:
    """도구 결과 하나에서 증거를 뽑는다. 표에 없는 도구는 조용히 넘긴다.

    **출처를 못 찾으면 만들지 않는다.** 출처 없는 증거는 세어도 아무 말을 못 한다 —
    지어내는 것보다 없는 편이 낫다.

    ★ 2026-09-04: `arguments` 를 폴백으로 받는다. **원장이 890 건의 읽기를 통째로
    놓치고 있었다.** `local_read_text_file` 은 증거에 `path` 를 안 싣는다
    (`char_count`·`line_start`·`content` 만 싣는다). 그래서 출처가 안 잡혀
    `None` 이 나왔고, 코드 판의 「0 개 실제로 읽음」은 **거짓말이었다.**

    무엇을 읽었는지는 결과가 아니라 **부탁한 인자**에 있는 경우가 흔하다. 결과를
    먼저 보고, 없을 때만 인자를 본다 — 결과가 진실에 가깝기 때문이다(리디렉션된
    주소, 실제로 열린 파일).
    """
    spec = MANIFEST.get(tool)
    if spec is None:
        return None
    spec = _split_by_result(tool, spec, evidence or {})
    raw = ""
    for source in ((evidence or {}), (arguments or {})):
        for key in spec.source_keys:
            raw = _as_source_text(source.get(key))
            if raw:
                break
        if raw:
            break
    source_id = canonical_source(raw, kind=spec.source_kind)
    if not source_id:
        return None
    digest = _body_hash(evidence or {}, spec.body_keys)
    return EvidenceRecord(
        evidence_id=f"e{step}-{hashlib.sha256(f'{tool}|{source_id}|{step}'.encode()).hexdigest()[:8]}",
        type=spec.type,
        effect=spec.effect,
        source_id=source_id,
        tool=tool,
        ok=bool(ok),
        content_hash=digest,
        candidate=spec.candidate_open,
        job_id=str(job_id or ""),
        step=int(step),
    )


def read_bodies(
    records: Iterable[dict[str, Any]],
    resolve: "Callable[[str, int], str]",
) -> str:
    """이 판이 **본문까지 읽은 것**의 원문을 모은다.

    근거 대조가 여기서 재료를 받는다. 전사가 아니라 원장에서 받는 이유는 둘이다.

    ① **전사는 잘린다.** `_bounded_transcript` 가 창을 지키느라 오래된 도구 결과를
       접는다. 그러면 답의 이름이 「안 읽은 것」으로 잘못 찍힌다.
    ② **전사는 경계를 못 넘는다.** 하위 에이전트가 대신 읽으면 부모 전사에는
       그 결과가 없다 — 검사가 조용히 통과한다. 원장은 주인을 들고 있어서
       원문을 되짚을 수 있다.

    `resolve(job_id, step)` 가 원문을 못 주면 그 증거는 조용히 건너뛴다. 원문을
    프로세스 밖으로 실어 나르지 않는다 — **대조는 본문이 있는 자리에서 한다.**
    """
    chunks: list[str] = []
    for record in records:
        if str(record.get("type") or "") != TYPE_BODY_READ or not record.get("ok"):
            continue
        try:
            body = resolve(str(record.get("job_id") or ""), int(record.get("step") or 0))
        except Exception:  # noqa: BLE001 — 대조 재료가 없다고 판을 죽이지 않는다
            body = ""
        if body:
            chunks.append(body)
    return "\n".join(chunks)


#: 증거 종류 → 이 종류가 뒷받침할 수 있는 요구의 종류.
_SUPPORTS = {
    TYPE_BODY_READ: {"count", "observe"},
    TYPE_PAGE_OPEN: set(),  # 연 것만으로는 아무 요구도 못 채운다 — 그게 요점이다
    TYPE_LISTING: set(),  # 목록을 본 것도 마찬가지다. 이름만 봤다.
    TYPE_ARTIFACT: {"artifact", "footnote"},
    TYPE_MUTATION: {"artifact"},
    TYPE_VERIFICATION: {"verify"},
}


def attach_clauses(
    records: list[dict[str, Any]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    """증거가 어느 절을 뒷받침하는지 계약의 바인딩에서 되짚는다.

    정확한 짝짓기가 아니다 — 요구 하나가 여러 절에 걸쳐 있을 수 있고, 지금은
    그 후보(`clause_ids`)까지만 안다. 비어 있는 비율이 다음 계측의 분모다.
    """
    by_kind: dict[str, list[str]] = {}
    for binding in (contract or {}).get("legacy_bindings") or []:
        kind = str(binding.get("requirement_kind") or "")
        ids = list(binding.get("clause_ids") or [])
        if not ids and binding.get("clause_id"):
            ids = [str(binding["clause_id"])]
        if ids:
            by_kind.setdefault(kind, []).extend(str(item) for item in ids)
    out: list[dict[str, Any]] = []
    for record in records:
        kinds = _SUPPORTS.get(str(record.get("type") or ""), set())
        found: list[str] = []
        for kind in sorted(kinds):
            for clause_id in by_kind.get(kind, []):
                if clause_id not in found:
                    found.append(clause_id)
        out.append({**record, "supports_clause_ids": tuple(found)})
    return out


def _was_read(opened: str, read: set[str]) -> bool:
    """연 곳을 **읽었는가.** 사이트가 들어간 뒤 주소에 매개변수를 덧붙여도 같은 곳이다.

    ★ 2026-10-08 숙소 조사 판: 상세 여섯을 열어 여섯 다 읽었는데 「열어 놓고 안 읽은 곳 6」으로 찍혔다. 연 주소는
      `…/3009957?adultCount=2&checkInDate=…` 이고 읽을 때의 주소는 거기에 `&verticalCategory=…` 가 붙어 있었다.
      같은 경로이고 연 주소의 매개변수를 **전부 그대로 가진** 주소를 읽었으면 읽은 것이다. 질의가 신원인 검색 주소는
      이 규칙에서도 갈린다(질의 값이 다르면 그대로 가진 것이 아니다).
    """
    if opened in read:
        return True
    try:
        mine = urlsplit(opened)
    except ValueError:
        return False
    if not mine.scheme:
        return False
    wanted = set(parse_qsl(mine.query, keep_blank_values=True))
    for source in read:
        try:
            other = urlsplit(source)
        except ValueError:
            continue
        if (other.scheme, other.netloc, other.path) != (mine.scheme, mine.netloc, mine.path):
            continue
        if wanted <= set(parse_qsl(other.query, keep_blank_values=True)):
            return True
    return False


def summarize(records: Iterable[dict[str, Any]], *, read_only: bool) -> dict[str, Any]:
    """이 판이 실제로 무엇을 했나 — 네 숫자.

    ``opened_never_read`` 가 이 원장을 만든 이유다. 목록에서 눌러 들어가고 본문을
    안 읽은 출처가 몇 개인지, 지금까지는 셀 방법 자체가 없었다.
    """
    opened: set[str] = set()
    read: set[str] = set()
    listed: set[str] = set()
    reads_by_source: dict[str, int] = {}
    writes = 0
    unbound = 0
    total = 0
    for record in records:
        total += 1
        source = str(record.get("source_id") or "")
        kind = str(record.get("type") or "")
        if not record.get("ok"):
            continue
        if kind == TYPE_PAGE_OPEN:
            # 이동은 세지 않는다. 「열어 놓고 안 읽었다」는 **후보**에만 묻는다 —
            # 실측에서 사이트 첫 화면이 「안 읽은 곳 1」로 찍혔다.
            if record.get("candidate"):
                opened.add(source)
        elif kind == TYPE_LISTING:
            listed.add(source)
        elif kind == TYPE_BODY_READ:
            read.add(source)
            reads_by_source[source] = reads_by_source.get(source, 0) + 1
        if str(record.get("effect") or "") in WRITE_EFFECTS:
            writes += 1
        if not record.get("supports_clause_ids"):
            unbound += 1
    return {
        "records": total,
        "sources_opened": len(opened),
        "sources_read": len(read),
        "sources_listed": len(listed),
        # ★ **이 판이 목록만 보고 답했나.** 목록은 봤는데 본문을 하나도 안 읽었다.
        #   2026-09-02 사고가 정확히 이 모양이었다 — 목록 줄에 없는 값(고용형태·
        #   마감일)을 답에 적었는데, 개수 대조는 통과시켰다.
        #   목록이 곧 답인 요청(「제목만 알려줘」)도 있으니 **고장이 아니라 신호**다.
        "answered_from_listing_only": bool(listed) and not read,
        # 열어 놓고 본문을 안 읽은 곳. 「3개 읽었다」의 거짓이 여기 산다.
        "opened_never_read": sorted(source for source in opened if not _was_read(source, read)),
        # 같은 곳을 두 번 이상 읽은 것. 하나를 두 번 열고 「2개」가 되던 자리다.
        "reread_sources": sorted(s for s, n in reads_by_source.items() if n > 1),
        "write_effects": writes,
        # 읽기 전용이라고 해 놓고 쓰기가 생겼나. 0 이어야 한다.
        "read_only_violations": writes if read_only else 0,
        "unsupported_records": unbound,
    }
