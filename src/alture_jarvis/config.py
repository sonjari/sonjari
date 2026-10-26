from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .brand import backup_dir, documents_product_dir, downloads_dir, engine_dir, product_dir, runtime_dir, update_dir
from .msix import package_full_name

#: 프로세스 환경(os.environ)이 **아닌** 안쪽 보관소. 자식에게 안 넘어간다 (2026-10-09).
#:
#: 손자리가 프로그램을 켜는 자리는 33곳이었고 그 가운데 우리 설정(`JARVIS_*`)을 빼고 넘기는 자리는 3곳뿐이었다 — 나머지는
#: 열쇠와 데이터 위치를 그대로 물려줬다. 그날의 사고(사본에서 돌린 시험이 돌고 있는 진짜 DB 에 붙음)가 그 길이었다.
#: 켜는 자리마다 빼는 방식은 새 자리가 생길 때마다 또 잊는다. 레딧에서 네 사람 가운데 셋이 같은 말을 했다 —
#: 「빼지 말고, 애초에 거기 넣지 마라」. 그래서 `.env` 와 물려받은 값을 여기에 두고, 읽는 쪽은 전부 `_env` · `setting` 을 거친다.
#: `project_env.without_our_settings`(켜는 자리에서 빼기)는 둘째 문으로 그대로 둔다.
_PRIVATE: dict[str, str] = {}


@lru_cache(maxsize=1)
def build_id() -> str:
    """**지금 도는 코드**의 지문. 실적을 남길 때마다 같이 적는다.

    ## 왜 필요한가 (2026-08-13)

    `audit_log` 는 `tool`·`ok`·`created_at` 만 남겼다. 그래서 어제 고친 코드의 실적과
    그저께 깨져 있던 코드의 실적이 **한 표에 섞이고, 섞였다는 사실조차 안 보인다.**

    실측: 도구 실행 1,688건 중 1,398건(83%)이 범용 브라우저 작업 **이전** 코드였고,
    `measure_autonomy.py` 는 기본값이 전체 기간이라 그걸 다 합쳐 "L4 위임 89.4% 도달"
    이라고 찍었다. 같은 표가 `browser_pick_suggestion 74.6%` 를 "발목 잡는 도구"로
    지목했는데, 그 도구는 이미 전날 고쳐져 24/24 였다 — **표가 없어진 세상을 보고 있었다.**

    ## 왜 mtime 이 아니라 내용인가

    `sync_to_runtime.ps1` 이 C: 로 복사할 때마다 mtime 이 바뀐다. 내용이 같은데 판이
    달라지면 "현재 판 표본"이 매 배포마다 0 이 되어 눈금이 못 쓰게 된다.

    git sha 를 쓰지 않는 이유도 같다 — C: 런타임은 git 저장소가 아니다. 게다가 커밋
    안 한 수정으로 도는 일이 잦아서(오늘도 그랬다) sha 는 실제로 도는 코드를 못 가리킨다.
    """
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        try:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════
# 축별 지문 — 판이 바뀌어도 표본이 안 죽게
# ═══════════════════════════════════════════════════════════════════════════
#
# `build_id` 는 패키지의 **모든** `.py` 를 해시한다. 그래서 화면 코드 한 줄만
# 고쳐도 조사(L2) 표본이 통째로 리셋된다.
#
# 실측(2026-08-21): 3일치 잡 128건이 **판 29종**에 흩어져 있었다. 판 하나당 평균
# 4건. 「지금 판만」 칸이 늘 "표본 부족"이라 **좋아졌는지를 영영 못 재는** 상태였다.
#
# 그런데 L2 숫자는 `browser.py`·`agent.py` 가 안 바뀐 동안에는 유효하다. 축이
# 의존하는 파일만 해시하면 표본이 훨씬 오래 산다.
#
# ★ 목록이 낡으면 조용히 틀린다 — 새 파일이 생겼는데 어느 축에도 안 넣으면 그
#   파일을 고쳐도 축 지문이 안 바뀌어, **고치기 전과 후가 한 표에 섞인다.**
#   `test_axis_build.py` 가 분류 안 된 파일을 그 자리에서 잡는다.
_AXIS_FILES: dict[str, tuple[str, ...]] = {
    # 목록·본문을 실제로 가져오는 길
    "read": (
        "agent.py", "browser.py", "site_recipes.py", "site_atlas.py",
        # 잘 해낸 판을 레시피 초안으로 옮긴다(2026-10-20 확장 설계 P1) — 그 초안이 다음 판의 읽는 길이 된다.
        "recipe_from_run.py",
        # 사람이 손자리 크롬에서 해 보인 것을 레시피 초안으로(2026-10-20 확장 설계 T8) — 같은 출구라 같은 축.
        "demo_recorder.py",
        # 손자리가 스스로 배우고 검증한 값 칸으로 상세 본문을 줄여 읽는다(2026-10-21) — 모델이 받는 글이 달라진다.
        "value_cells.py",
        # 노는 시간에 대화 기록으로 카드를 쓴다(2026-10-21 서기) — 같은 Ollama 를 쓰므로 사람 판의 기다림이 달라질 수 있다.
        "scribe.py",
        # 이 PC 안 페이지를 열 때 화면을 재서(덮인 글자 · 가로 넘침 · 깨진 그림) 결과에 붙인다(2026-10-11) — 모델이 받는 글이 달라진다.
        "layout_probe.py",
        # 이 PC 안 페이지를 따로 찍어 모델의 눈으로 본 인상을 결과에 붙인다(2026-10-11) — 모델이 받는 글이 달라진다.
        "page_look.py",
        # 답글 말초 정리 — 링크 추출(_offered_link_to_open)이 조사 답의 내용을 바꾼다.
        "answer_hygiene.py",
        # 막힘·대안·산출물 자리 — agent.py 에서 분리(2026-10-09). 조사 판의 멈춤 판정·대안 안내·파일 저장 자리가 바뀐다.
        "stuck_hands.py",
        # 다음 수(다음 걸음) 안내 — agent.py 에서 분리(2026-10-10). 남은 요구의 종류에 맞는 다음 수·읽기/쓰기 걸음 판정이 바뀐다.
        "plan_nudges.py",
        # 전사·생각 예산·강제 호출 라우팅 — agent.py 에서 분리(2026-10-09). 전사 상한·생각 정책·강제 읽기·열기/읽기 짝짓기가 바뀐다.
        "transcript_policy.py",
        # 작은 창의 조사 판에서 지침을 손에 맞춘다(2026-10-12) — 손에 없는 도구 가족의 대목을 빼 걸음 기록에 쓸 자리가 넓어진다.
        "contract_slim.py",
        # 다른 AI 대화 사이트에 대신 묻지 않는다(2026-10-12) — 조사 판이 글을 넣는 손을 그 사이트에서 되돌려 보낸다.
        "ai_chat_sites.py",
        # 「한 일인가, 예고인가」 판정(예고 그물·표 행 수 읽기·걸음 상한·마무리 여유) — agent.py 에서 분리(2026-10-09). 조사 판의 멈춤·마무리 판정이 바뀐다.
        "promise_gate.py",
        # 요청·걸음·답의 모양을 낱말 규칙으로 판정 — agent.py 에서 분리(2026-10-09). 출처 판정·실패 그물·읽기 개수 대조가 바뀐다.
        "answer_gate.py",
        # 답 안의 클레임(성공·완료·출처·끝맺음) 판정과 자기 모순 검사 — agent.py 에서 분리(2026-10-10). 조사 답의 완성 판정이 바뀐다.
        "answer_claims.py",
        # 「없다 · 아직 없다」에 본 범위(목록 화면 · 연 글 수)를 붙인다(2026-10-19) — 조사 답에 붙는 글이 바뀐다.
        "absence_scope.py",
        # 한 번도 안 연 곳의 줄에 값이 채워졌으면 답 끝에 밝힌다(2026-10-24 bf69599d) — 조사 답에 붙는 글과 판 기록이 바뀐다.
        "unopened_places.py",
        # 답 끝 대조 덩어리를 받는 쪽(창 · 바깥 AI)에 맞게 나눈다(2026-10-24) — 조사 답에 보이는 글이 바뀐다.
        "check_notes.py",
        # 모델이 보는 도구 목록을 갈래·단계·요청으로 고르는 쪽 — agent.py 에서 분리(2026-10-09). 조사 갈래 좁히기·산출물 차례 손·플랫폼 쓰기 관문이 바뀐다.
        "tool_roster.py",
        # 상세 첫머리에서 판매가·적립을 도구가 읽어 표 칸을 채운다(2026-09-28 T1, 동결 예외 A) — 표의 값을 직접 바꾼다.
        "page_values.py",
        # 목록에서 항목으로 가는 주소의 표식(2026-10-05 arXiv·네이버 뉴스) — 순위가 무엇을 여는지를 바꾼다.
        "result_links.py",
        # 검색칸의 버릇을 확인한 사이트에서만 「첫 낱말로 다시 찾기」를 켠다(2026-10-12) — 검색 결과 목록이 바뀐다.
        "search_boxes.py",
        "plopfit.py", "serp.py", "inhouse_data.py", "google_workspace.py",
        "local_computer.py", "document_reader.py", "person_search.py",
        "hwp.py", "claude_code.py", "code_index.py", "code_scout.py",
        # 코드 모드가 어느 파이썬으로 돌고 무엇을 깔 수 있나(2026-09-26). 시험을 **어떤 환경에서** 돌리느냐가
        # 코드 판의 결과를 바꾸므로 local_computer.py 와 같은 축에 둔다.
        "project_env.py",
        # 아는 비밀 값을 도구 결과에서 가린다(2026-10-11). 모델이 받는 명령 출력·파일 글이 달라지므로 판 결과를 바꾼다 —
        # 명령을 돌리는 쪽과 같은 축에 둔다. (`secret_scrub.py` 는 가져온 지침만 걷어서 면제 목록에 있다.)
        "known_secrets.py",
        # 유니티를 배치 모드로 돌리는 쪽(2026-09-27). 게임 팩 레시피의 성적을 직접 바꾼다.
        "unity_tools.py",
        # 게임 팩 2단계(2026-09-27): 열린 에디터 다리·유니티 창 무대·레시피 정기 점검. 에디터 판의 성적(읽기·바꾸기·되돌리기)을 직접 바꾼다.
        "unity_editor.py", "unity_stage.py", "unity_schedule.py",
        # 분야 팩(2026-09-27). 켜고 끄면 모델이 보는 도구·스킬·「시킨 것」이 바뀐다 — 성적을 직접 바꾸는 층이다.
        "packs.py",
        # 이름 하나로 정의·참조·줄 범위를 찾는 쪽(2026-09-21). 색인이 「무엇이 있나」라면
        # 이쪽은 「고치면 어디가 깨지나」다 — 둘 다 읽기 축이다.
        "symbol_index.py",
        # 일하면서 하는 말(2026-09-21). 답이 아니라 **과정을 보여 주는** 쪽이라
        # 읽기 축에 둔다 — 증거로는 안 센다.
        "narration.py",
        "stray_han.py",
        # 답이 자기 두 줄 사이에서 부딪치는지 본다(2026-09-21). 답을 **검사**하는 쪽이라
        # 읽기 축이다 — 고치지 않고 원장에 적기만 한다.
        "answer_audit.py",
        # 권한 모드와 쓰기 도구 목록(2026-09-21). 무엇을 **바꿀 수 있나**를 정하므로
        # 읽기 축이 아니라 쓰기 축이다.
        "project_discovery.py",
        # 검색이 통한 주소를 배워 두고 다음엔 그리로 바로 가는 쪽. **조사 성적을
        # 직접 바꾼다** — 검색칸을 못 찾아 멈추던 판(31건·5종)이 여기서 갈린다.
        "search_atlas.py",
        # 손으로 만든 검색어의 한 글자 오타를 요청 낱말로 바꾼다(2026-10-01 「파이서」). **무엇을 검색하느냐**를 바꾸므로
        # 조사 성적을 직접 바꾼다 — search_atlas 와 같은 자리.
        "search_typo.py",
        # 요청한 날짜로 주소를 갈아 끼우는 쪽. **조사 성적을 직접 바꾼다** —
        # 어느 밤을 여느냐가 읽어 오는 값을 통째로 바꾸기 때문이다(잡 `cd3e84c0`:
        # 하루 차이로 가격 20%, 그리고 예약마감이라 실제로는 못 자는 곳이었다).
        # `clock.py` 는 면제인데 이것은 아닌 이유가 그것이다 — 저쪽은 프롬프트에
        # 적어 주는 글자고, 이쪽은 **가는 곳을 바꾼다.**
        "dates.py",
        # 사람이 PC 를 쓰는 중이면 브라우저 창을 앞으로 안 가져온다(2026-09-16). **조사 성적을 바꿀 수 있다** —
        # 뒤에 있는 창을 크롬이 느리게 돌리면 읽기·캡처가 늦어진다. 그래서 면제가 아니라 축에 넣는다.
        "user_presence.py",
        # 브라우저 무대(2026-09-24) — 사람이 넘겨받는 동안 브라우저 도구가 **기다린다**. 읽기 걸음의 시간과 결과를 바꾼다.
        "live_view.py",
        # 사이트가 박아 둔 구조화 데이터·사이트 성질 기억·페이지가 받아 온 JSON·공개 출처(2026-09-18) —
        # 전부 **읽어 오는 값과 가는 길**을 바꾼다(YES24 ISBN·MS 스토어 별점이 여기서 온다).
        "structured_data.py", "site_traits.py", "page_data.py", "site_sources.py",
        # 요약 비율이 답의 표와 맞는가 · 읽은 자료에 없는 비율(2026-10-01 밤). 조사 답에 붙는 경고를 바꾼다 — evidence 와 같은 자리.
        "number_checks.py",
        # 모델 없는 루틴(2026-10-23 · §55-39) — 레시피 주소로 브라우저 없이 목록을 받아 칸을 읽는다. 읽어 오는 값을 바꾼다.
        "routine.py",
    ),
    # 바깥을 실제로 바꾸는 길
    "write": (
        "agent.py", "browser.py", "naver_blog.py", "google_workspace.py",
        # 답글 말초 정리 — 산출물·commit 사슬(_forced_artifact·_COMMIT_CHAINS)이 쓰기의 결과를 바꾼다.
        "answer_hygiene.py",
        # 파일을 쓴 뒤에 새로 읽은 페이지를 골라낸다(2026-10-14 · 손자리가 짬) — 끝내기 전에 다시 쓰게 돌려보내는 재료.
        "write_order.py",
        # 저장한 문서를 다시 읽어 쓰려던 문장 · 칸이 빠지거나 바뀐 곳을 찾는다(2026-10-15 · 손자리에게 맡김).
        "readback.py",
        # 모델이 보는 도구 목록을 갈래·단계·요청으로 고르는 쪽 — agent.py 에서 분리(2026-10-09). 산출물 차례 손과 플랫폼 쓰기 관문이 쓰기의 결과를 바꾼다.
        "tool_roster.py",
        "windows_automation.py", "ui_vision.py", "sandbox.py", "scheduler.py",
        # 화면 밖 · 최소화된 창을 주 모니터로 데려온다(2026-10-19 ae395490 뒤) — 창 자리를 바꾸는 손이라 windows_automation 과 같은 자리.
        "window_view.py",
        "watch_service.py", "external_actions.py", "mimo_control.py",
        "hwp.py",
        # `undo_action` 이 여기 있다 — 되돌리는 것도 쓰기다(눈금도 WRITE 로 센다).
        # ★ 검사(`test_axis_build`)가 만들자마자 이 파일을 잡아냈다.
        "system_tools.py", "project_discovery.py",
        # 창에 키를 보내기 전 사람 손이 멈추길 기다리거나 미룬다(2026-09-16) — 쓰기 성공률을 바꾼다.
        "user_presence.py",
        # 브라우저 무대 — 사람이 같은 탭을 만지는 동안 쓰기 도구를 멈춘다(2026-09-24).
        "live_view.py",
        # 권한 모드와 쓰기 도구 목록(2026-09-21). 무엇을 **바꿀 수 있나**를 정한다 —
        # 읽기만 모드가 여기서 쓰기를 막고, 눈금도 이 목록으로 쓰기를 센다.
        "permissions.py",
        # 디자인된 장표(2026-10-25) — 장 HTML 을 다듬고 PPTX 로 굽는 쪽과 그 스타일 예시. 만든 파일의 모양을 바꾼다.
        "slides.py", "slides_style.py", "pptx_fonts.py", "slide_catalog.py", "slide_inbox.py", "slide_parts.py", "slide_frames.py", "doc_checks.py", "near_typos.py",
    ),
    # 사람 개입 없이 끝까지 가는 길
    "delegate": (
        "agent.py", "plan.py", "task_contract.py", "quantities.py", "evidence.py", "grounding_scout.py", "runtime.py", "tool_gateway.py", "mission.py",
        # 판 카드(2026-10-24 · 전략안 §55-41) — 확실한 요구만 밀고 완료를 가른다. 위임 판의 끝(완료 · 일부)을 바꾼다.
        "run_card.py",
        # 답글 말초 정리 — commit 사슬(_COMMIT_CHAINS)과 산출물 판정이 위임의 결과를 바꾼다.
        "answer_hygiene.py",
        # 영어 요청을 읽는 규칙(2026-09-23 밤) — plan·runtime 과 같이 계획·갈래를 정한다.
        "english.py",
        "human_gate.py", "gate_watcher.py", "proof.py", "attention.py",
        "claude_code.py", "code_runtime.py", "code_scout.py", "project_discovery.py",
        # 막힌 자리에서만 내 API 키로 클로드에게 한 번 묻는다(2026-10-26) — 조언이 루프에 끼어 판의 끝을 바꾼다. 넘기기와 같은 축.
        "api_escalation.py",
        # 앱 안의 Claude Agent(2026-10-26) — 클로드에게 끼워 주는 「앱 안」 지침이 무엇을 손자리에게 맡길지를 바꾼다. 넘기기 · 승급과 같은 축.
        "claude_agent.py",
        # 이어받기 — 채팅 갈래를 정하기 전에 가로채고, 가지에서 코드 잡을 올린다. 판의 길을 바꾼다.
        "takeover.py",
        # 손자리 자신에 대한 말(2026-10-20) — 이어받기와 같은 자리에서 채팅 갈래 전에 가로채 답하고 · 그림 읽기를 바꾸고 ·
        #   그림을 못 읽은 판의 답 끝에 질문을 붙인다. 「뭐가 바뀌었어?」 답의 글(whats_new)도 판의 답을 바꾼다.
        "self_talk.py", "whats_new.py",
        # 큰 코드 갈림길(2026-10-02) — 작은 모델에게 통째로 시킨 코드 일을 시작 전에 묻고, 클로드 코드에 맡기거나 나눠서 한다.
        "big_code.py",
        # 코드 판 관문(2026-10-09) — agent.py 에서 분리. 보기 루프·검증 되받기·손 좁히기. 위임 판의 걸음을 직접 바꾼다.
        "code_look_gate.py",
        # 모델이 보는 도구 목록을 갈래·단계·요청으로 고르는 쪽 — agent.py 에서 분리(2026-10-09). 위임 판이 부르는 손을 바꾼다.
        "tool_roster.py",
        # 바깥 AI 에게 나가는 답의 정제 · 돌려받아야 할 것 · 영수증(2026-10-15 · §55-32) — 위임 결과로 무엇이 나가는지를 바꾼다.
        "outbound.py",
        # 바깥 AI 가 받는 답에 대조 덩어리를 싣는 쪽(2026-10-24) — 위임 결과로 무엇이 나가는지를 바꾼다.
        "check_notes.py",
        # 답이 기댄 페이지 사진(대표사진)을 고르고 거르는 쪽(2026-10-18) — 판 결과와 바깥으로 나가는 것을 바꾼다.
        "showcase.py",
        # 모델 별명(2026-10-18) — `@별명` · `/모델` 로 판 하나를 어느 모델이 돌지 정한다.
        "model_aliases.py",
        # 로그인 화면 · 한 번 쓰는 값을 줄여 내보낸다(2026-10-19) — 위임 결과의 sources · 답 · 바깥 사본이 바뀐다.
        # 「사람이 같은 탭을 쓰나」 문(browser.py)의 로그인 예외도 이 판정을 쓴다.
        "url_privacy.py",
    ),
}


def _digest_files(names: tuple[str, ...]) -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in sorted(names):
        path = package / name
        try:
            digest.update(name.encode())
            digest.update(path.read_bytes())
        except OSError:
            # 파일이 없어도 **이름은 넣는다** — 사라진 것도 변화다.
            continue
    return digest.hexdigest()[:12]


@lru_cache(maxsize=1)
def axis_build_ids() -> dict[str, str]:
    """축별 지문. `build_id` 와 같이 남겨 두면 나중에 축별로 표본을 묶을 수 있다."""
    return {axis: _digest_files(files) for axis, files in _AXIS_FILES.items()}


def axis_files() -> dict[str, tuple[str, ...]]:
    """검사가 목록을 볼 수 있게 내준다."""
    return dict(_AXIS_FILES)


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """`.env` 의 값을 **안쪽 보관소(`_PRIVATE`)** 에 싣는다. **이미 있는 값은 덮지 않는다.**

    ## 왜 뒤늦게 생겼나

    `.env` 와 `.env.example` 은 오래 전부터 있었는데 **읽는 코드가 없었다.** 설정은
    전부 `os.getenv` 로만 들어왔고, 실제 값은 `scripts/task_entry.py` 가 손으로
    `setdefault` 하는 것들뿐이었다. 그래서 `.env` 에 무언가를 적어 두면 적용된 것처럼
    보이지만 아무 일도 일어나지 않는다 — 2026-08-06 MCP 토큰을 넣고 재시작했는데
    계속 401 이 나서 발견했다.

    ## 덮지 않는 이유

    `task_entry.py` 가 켜 두는 스위치들(브라우저 쓰기, 카메라 등)이 이미 환경이나
    보관소에 올라와 있다. 여기서 덮으면 오래된 `.env` 한 줄이 그 결정을 조용히
    뒤집는다. 환경변수가 언제나 이긴다 — 그래야 한 번 실행에서만 값을 바꿔 보는
    것도 가능하다.

    ## 왜 보관소에 두나

    프로세스 환경(os.environ)에 두면 자식 프로세스가 물려받아 열쇠와 데이터 위치가
    새는다. 보관소는 이 프로세스 안에서만 보인다.
    """
    target = path or Path(_env("JARVIS_RUNTIME_ROOT") or _default_runtime_root()) / ".env"
    loaded: dict[str, str] = {}
    if not target.exists():
        return loaded
    # utf-8-sig: BOM 이 붙은 파일이 흔하다. 안 벗기면 첫 키 이름에 BOM 이 들러붙어
    # 그 줄만 조용히 무시된다(사고 J 와 같은 부류의 고장).
    for raw in target.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ or key in _PRIVATE:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        _PRIVATE[key] = value
        loaded[key] = value
    return loaded


#: 모델별 생각 예산 기본표 — dataclass 기본값과 로더가 **이 한 곳**을 본다(사고 Q: 상한이 두 곳이면 낮은 쪽이 일한다).
#: ★ 2026-09-30: qwen3.8 은 기본 8,000자에 잘린 뒤 2단째(think=False)에서 생각을 본문으로 이어 쓰다 8,027 토큰 상한에
#:   걸려 도구를 하나도 못 냈다(QR 과제, 2분 11초). 잘린 생각은 8,214자로 결론 직전이었다 — 스스로 끝나게 둔다.
#:   qwen3.6 은 3,000자에서 끊어도 2단째가 1~2초 만에 제대로 된 걸음을 낸다(09-20 실측).
#: ★ 2026-10-07: Ornith(10-02 부터 운영 모델)는 표에 없어 Gemma 기준 기본값 8,000자로 돌고 있었다. 어려운 코딩 과제
#:   (사다리 L7·L8, 3판씩)에서 판마다 한두 턴이 8,000자까지 생각하고 끊겨 17~26초씩 버렸다. 3,000자로 낮춰 다시 쟀다:
#:   통과 5/6 → 5/6(떨어진 판은 양쪽 다 모델이 덧붙인 시험이 채점 폴더에서 깨진 것) · 총 시간 가운데 78 → 63초.
#:   끊긴 뒤의 2단째는 8,000자 때와 같이 0.5~4초 만에 제대로 된 걸음을 냈다. 과제 둘 · 3판씩이다 — 더 깊은 계획이
#:   필요한 일에서 모자라는지는 아직 못 봤다.
DEFAULT_THINKING_BUDGETS: dict[str, int] = {"qwen3.6": 3000, "qwen3.8": 16000, "ornith": 3000}


def _thinking_budgets(raw: str) -> dict[str, int]:
    """`qwen3.6=3000;gemma4=8000` → {이름 앞부분: 글자 수}. 비어 있으면 기본표."""
    pairs: dict[str, int] = {}
    for chunk in str(raw or "").replace(",", ";").split(";"):
        name, _, value = chunk.partition("=")
        name, value = name.strip().lower(), value.strip()
        if name and value.isdigit():
            pairs[name] = int(value)
    return pairs or dict(DEFAULT_THINKING_BUDGETS)


def _env(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw:
        return raw.strip()
    stored = _PRIVATE.get(name)
    if stored:
        return stored.strip()
    return default.strip()


def setting(name: str, default: str = "") -> str:
    """`_env` 와 같은 일을 하는 공개 이름 — 다른 모듈이 쓴다."""
    return _env(name, default)


def keep_private(name: str, value: str, *, override: bool = False) -> None:
    """값 하나를 보관소에 둔다. override 가 아니면 환경·보관소에 이미 있는 이름은 건드리지 않는다."""
    if not override and (name in os.environ or name in _PRIVATE):
        return
    _PRIVATE[name] = value


def absorb_environment() -> list[str]:
    """환경에 있는 `JARVIS_*` 를 보관소로 옮기고 환경에서 지운다.

    이름을 대소문자 가리지 않고 본다(윈도우는 환경변수 이름의 대소문자를 가리지 않는다).
    보관소의 같은 이름을 덮는다(환경이 우선). 옮긴 이름 목록을 돌려준다.
    """
    moved: list[str] = []
    for key in list(os.environ):
        if key.upper().startswith("JARVIS_"):
            _PRIVATE[key] = os.environ[key]
            del os.environ[key]
            moved.append(key)
    return moved


def environment_for_our_own_child() -> dict[str, str]:
    """우리가 **우리 자신의 부속**(음성 서버 등)을 켤 때만 쓰는 환경.

    os.environ 사본 + 보관소. 사본이라 바꿔도 우리 환경·보관소에는 안 된다.
    """
    handed = dict(os.environ)
    handed.update(_PRIVATE)
    return handed


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _default_runtime_root() -> Path:
    configured = _env("JARVIS_RUNTIME_ROOT")
    if configured:
        return Path(configured)
    if os.name == "nt":
        local_app_data = _env("LOCALAPPDATA")
        if local_app_data:
            return runtime_dir(Path(local_app_data))
        return runtime_dir(Path.home() / "AppData" / "Local")
    return Path.cwd()


def _default_backup_root() -> Path:
    """기억 복제 폴더. 사용자 폴더 아래라 MSIX 가상화 밖이고, 앱을 지워도 남는다(W1-3)."""
    configured = _env("JARVIS_BACKUP_DIR")
    return Path(configured) if configured else backup_dir(Path.home())


def _outside_app_data(*, legacy: Path, fresh: Path) -> Path:
    """**앱 전용 칸 밖**의 자리. 옛 자리를 이미 쓰고 있으면 그대로 이어 쓴다.

    ★ 2026-09-18 노트북 실측(뿌리). 스토어판(MSIX)에서 `%LOCALAPPDATA%` 아래에 **새로 만든 파일**은
      앱 전용 칸으로 간다. 우리 프로세스만 쓰는 파일이면 괜찮지만, **밖에서 도는 프로그램**이 읽는
      자리면 그 프로그램은 못 본다 — Ollama 가 자기 러너를 못 찾아(`llama-server binary not found`)
      모델을 하나도 못 올렸다. 파일은 43개가 멀쩡히 있었고, 서버는 켜지고 목록도 답해서 더 안 보였다.
      크롬(`chrome.exe`)도 같은 처지다: 우리가 쓴 설정과 크롬이 보는 설정이 갈린다.
      그래서 **밖의 프로그램이 읽는 것·다시 받기 비싼 것**은 사용자 폴더에 둔다(`backup_dir` 와 같은 이유).
      옛 자리는 그대로 인정한다 — 이미 쓰던 PC 가 갑자기 빈 프로필·빈 설치로 시작하면 안 된다.

    ★ 다만 **패키지 안에서는 옛 자리를 인정하지 않는다.** 우리 프로세스에게는 앱 전용 칸이 그 경로로 보여
      `exists()` 가 참이 된다 — 고장난 자리를 「이미 쓰던 자리」로 읽고 계속 쓰게 된다. 그게 노트북에서
      벌어진 일이다(우리 눈에는 있고 Ollama 눈에는 없는 폴더).
    """
    if legacy.exists() and not package_full_name():
        return legacy
    return fresh


def _default_local_roots() -> str:
    home = Path.home()
    candidates = [home / "Desktop", home / "Documents", home / "Downloads"]
    # 자비스가 만든 것을 다음 턴에 다시 읽어야 폐루프가 닫힌다. 예전에는 sandbox
    # 산출물이 허용 루트와 교집합이 없어, 만들고도 "거기 3행 고쳐"를 못 했다.
    candidates.append(_default_runtime_root() / "outputs" / "workspace")
    # ★ 브라우저가 받은 문서도 읽을 수 있어야 한다 (2026-09-01).
    #
    #   `browser_download` 로 PDF 를 받아 놓고 `local_read_document` 가 "허용된 경로가
    #   아니다"로 거절하면, 받은 것이 아무 데도 안 닿는다. 위 sandbox 산출물과 같은
    #   폐루프 문제다 — 만들고도(받고도) 못 읽는 자리.
    candidates.append(_default_runtime_root() / "outputs" / "downloads")  # 옛 기본 자리에 받아 둔 파일
    # 새 기본 자리(다운로드\Ontelic)는 위 Downloads 에 이미 들어 있다.
    return ";".join(str(path) for path in candidates)


@dataclass(slots=True)
class JarvisConfig:
    _settings_defaults: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    host: str = "127.0.0.1"
    port: int = 8091
    runtime_root: Path = field(default_factory=_default_runtime_root)
    data_dir: Path = field(default_factory=lambda: _default_runtime_root() / "data")
    output_dir: Path = field(default_factory=lambda: _default_runtime_root() / "outputs")
    #: 사람에게 줄 **결과물**이 가는 자리. 중간 산출물(`output_dir`)과 다르다.
    #
    # 잡별 UUID 폴더는 판이 끝나면 치울 것들에 맞다. 사람이 달라고 한 문서는
    # 탐색기에서 바로 보여야 한다. 설정으로 빼 둔 이유는 검사가 진짜 「내 문서」를
    # 더럽히지 않게 하기 위해서다 — 검사가 사람 폴더에 쓰면 그건 검사가 아니다.
    # 새 PC 는 `내 문서\\Ontelic`, 이미 `내 문서\\JARVIS` 가 있는 PC 는 그 자리를 계속 쓴다(brand.py).
    documents_dir: Path = field(default_factory=lambda: documents_product_dir(Path.home() / "Documents"))
    control_token: str = ""
    profile_path: Path = field(
        default_factory=lambda: _default_runtime_root() / "data" / "JARVIS_PROFILE.md"
    )
    profile_max_chars: int = 6000

    ollama_base_url: str = "http://127.0.0.1:11434"
    # 우리가 깔아 주는 Ollama 가 사는 자리. **앱 전용 칸 밖**이어야 한다 — Ollama 는 패키지 밖 실행 파일이라
    # 그 칸이 안 보인다(2026-09-18 노트북: 파일 43개가 있는데 `llama-server binary not found`).
    ollama_install_dir: Path = field(
        default_factory=lambda: _outside_app_data(
            legacy=_default_runtime_root() / "data" / "ollama",
            fresh=engine_dir(Path.home()) / "ollama",
        )
    )
    # 스토어판 「지금 업데이트」 도우미가 상태를 적는 자리. **앱 전용 칸 밖** — 도우미는 패키지 밖에서 돈다.
    store_update_dir: Path = field(default_factory=lambda: update_dir(Path.home()))
    # 위성이 갱신을 받아 올 본체. **비워 두는 것이 기본이다** —
    # `brain_control_url` 이 `ollama_base_url` 의 호스트에서 끌어온다.
    #
    # ★ 새 비밀을 안 만든 이유: 이미 깔린 위성(다른 사용자 노트북)이 재설치 없이
    #   동작해야 한다. 설정을 하나 더 요구하면 그 한 대는 영원히 못 받는다.
    brain_host: str = ""
    # 제어 API 에 닿을 수 있는 **추가** 대역. 루프백과 테일넷은 항상 열려 있다.
    # 쉼표로 여럿. 오타가 있으면 뜰 때 예외로 알려 준다 — 조용히 버리면
    # 「열어 뒀다고 생각했는데 안 열린」 상태가 된다.
    api_extra_allowed_cidrs: str = ""
    # 역할별 태그는 이 기본값과 `from_env` 두 자리에서만 산다. 호출부에 태그를
    # 박으면 벤치에서 고른 코더를 바꿔도 한 갈래만 옛 모델을 쓰는 사고가 재발한다.
    model_roles: dict[str, str] = field(
        default_factory=lambda: {
            "chat": "gemma4:26b-a4b-it-qat",
            # 2026-08-25 재선정. 7B 장난감 벤치 승자는 저장소 규모의 코드
            # 에이전트 기본값이 될 수 없다. 3090에서 실측한 최신 주력 모델을 쓴다.
            # ★ 2026-09-15 PC 의존성 정리: 비어 있으면 대화 모델을 쓴다(`model_for`). 27B 코더를 기본으로 박으면
            #   8GB 카드 사용자의 Code 탭이 없는 모델을 부른다. 운영 PC 는 환경변수로 따로 준다.
            "code": "",
            "vision": "gemma4:26b-a4b-it-qat",
        }
    )
    model_num_ctx: dict[str, int] = field(
        # Qwen3.8-27B의 네이티브 창은 256K다. 3090 실측에서 q8_0 KV의 128K는
        # 9% CPU 오프로딩, 100K는 100% GPU였다. 코딩 지연과 품질을 위해 100K를 쓴다.
        # 코드 모델을 따로 줄 때만 쓴다. 비우면 대화 모델과 같은 컨텍스트 — 다르면 러너를 새로 띄워 축출한다.
        default_factory=dict
    )
    # Qwen3.8 Code 추론 프로필. balanced는 공식 thinking 샘플링 권장값을 쓰고,
    # fast는 짧은 질의/기계적 수정용 non-thinking이다.
    #
    # ★ 2026-08-29 정책 변경. 예전에는 "UI에 추론 원문을 노출하지 않고 계획·도구·
    # 검증 근거만 보여 준다"였다. 그 결과 화면에는 「판단하고 있습니다」한 줄이
    # 몇 분씩 떠 있었고, 무슨 근거로 그 손을 골랐는지 볼 방법이 없었다.
    # 이제 사고 원문을 `agent_thinking_text` 로 흘려보내고 코드 작업공간에서
    # **펼친 채로** 보여 준다. 답이 아니라 과정이라는 것은 자리와 생김새로
    # 말한다(등폭·낮은 대비·접을 수 있음).
    code_inference_profile: str = "balanced"
    # 되돌려 보낼 최근 사고 흔적 개수. 0이 기본이다 — 미끄러지는 창은 프리픽스
    # 캐시를 매 걸음 무효로 만들고, Qwen3 공식 지침도 이전 사고는 빼라고 한다.
    # 되살리고 싶으면 JARVIS_CODE_PRESERVE_RECENT_THINKING 로 올린다.
    code_preserve_recent_thinking: int = 0
    # Code 4차: 3060은 주 코더의 가중치를 나눠 갖지 않고 별도 읽기 전용 정찰기로
    # 쓴다. endpoint가 없거나 모델이 응답하지 않으면 주 Qwen3.8 단독 경로로 즉시
    # 폴백한다. 운영 PC에서 실측하기 전에는 opt-in으로 둔다.
    code_scout_enabled: bool = False
    code_scout_base_url: str = "http://127.0.0.1:11435"
    code_scout_model: str = "qwen3.5:9b"
    code_scout_num_ctx: int = 65536
    code_scout_timeout_sec: int = 60
    code_scout_max_predict: int = 1200
    code_scout_keep_alive: str = "30m"
    #: 정찰기를 올릴 카드. 비우면 메모리 여유 검사를 건너뛴다(정찰기는 기본 꺼짐). 이 PC 3060 의 ID 가 기본값으로
    #: 박혀 있었다 — 운영 PC 는 .env 로 준다.
    code_scout_gpu_uuid: str = ""
    code_scout_min_free_vram_mb: int = 8000
    ollama_timeout_sec: int = 180
    # ★ 코드 판은 한 호출이 훨씬 길다. 실측(2026-08-28): 생성 5,520 토큰이
    #   145초, 3,248 토큰이 89초. 여기에 프리필이 붙으면 180초를 넘긴다 —
    #   실제로 그 때문에 저장소 SWE 판 하나가 `timed out` 으로 통째로 죽었고,
    #   모델은 이미 고쳐 놓은 뒤였다(목표 테스트 19개가 통과 상태였다).
    #   대화 타임아웃은 그대로 두고 코드 역할만 넉넉히 준다.
    ollama_code_timeout_sec: int = 900
    # 모델 호출 **한 번**이 뽑을 수 있는 최대 토큰. 2026-08-20 이전에는 상한이 없었고,
    # 스트리밍이라 위 180초 타임아웃도 안 걸린다(토큰이 계속 나오면 read 가 리셋된다).
    # 실측: 캘린더 판 하나가 **1,853초(31분)** 동안 GPU 87% 로 생성만 했다.
    #
    # 8192 인 이유: 우리 답 중 가장 긴 것이 4,000자 안쪽(≈2,000토큰)이고, 생각까지
    # 합쳐도 그 네 배면 충분하다. 그러면 최악이 1~2분으로 묶인다.
    # ⚠ 생각(think=True)이 이 예산을 먼저 먹으면 답이 빈다 — 그래서 빈 답이면
    #   생각을 끄고 한 번 더 부르는 장치(agent.py 정리 단계)와 **짝이다.**
    ollama_max_predict: int = 8192
    # 한 턴에서 **사고**에 쓸 수 있는 글자. 넘으면 흐름을 끊고, 지금까지의 생각을 들려주며
    # 「바로 답하라」로 한 번 더 부른다(2단 호출 — Qwen 공식 우회법과 같은 모양).
    #
    # ★ 왜 필요한가 (2026-09-18 실측). 로컬 엔진에는 사고 예산이 없다. 그래서 어떤 턴은
    #   `num_predict` 8,192 를 **전부 사고에 쓰고** 답에 600토큰만 남겼다 — 그 턴 하나가 85초다.
    #   한 판(316초)에서 그런 턴 둘이 168초(57%)를 먹었다. 모집단에서도 그런 턴은 1.5% 인데
    #   생성 시간의 19% 를 가져간다.
    # ★ 값의 근거: 사고 있는 턴 1,306개 분포에서 95% 가 5,711자 안, 98% 가 20,828자. 그 사이가 비어 있다.
    #   8,000자는 보통 사고를 안 건드리고(95% 통과) 폭주만 잡는다(3.6%). 0 이면 끄는 것.
    ollama_thinking_char_budget: int = 8000
    #: 모델별 생각 예산 — 이름 앞부분 → 글자 수. 8천은 Gemma 4 기준이고, Qwen 3.6 은 턴마다 예산 끝까지 쓴다
    #: (2026-09-20 코워크 한 판: 5턴 중 4턴이 8천 자·턴당 32초에서 끊겼고, 끊은 뒤 1~2초 만에 제대로 된 걸음을 냈다).
    ollama_thinking_budget_by_model: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_THINKING_BUDGETS)
    )
    #: 일하면서 **말한다** — 도구를 부르기 전에 무엇을 왜 하는지 한 줄 (2026-09-21).
    #:
    #: 실측(Qwen 3.6): 안내 없으면 말 0/3, 시키면 3/3 이고 **도구 호출은 둘 다 3/3**.
    #: 비용 +0.1초/호출. 사람이 보면서 엉뚱한 길을 바로 막을 수 있는 것이 값이다.
    #: 끄면 **아무것도 안 바꾼다** — 읽고 계획만 말한다(클로드의 plan 과 같은 자리).
    #: 권한 모드 `read_only` 가 이 값을 끈다. 쓰기 도구는 관문에서 거절되고, 거절문은
    #: 「지금은 읽기만 모드」라고 **이유를 댄다** — 막기만 하면 같은 벽에 계속 부딪친다.
    local_write_enabled: bool = True
    agent_narration_enabled: bool = True
    #: ★ **모델별로 끌 수 있어야 한다.** 도구 설명에 「먼저 알리고」를 넣었다가 젬마의
    #: 도구 호출이 통째로 막힌 적이 있다. 새 모델은 **재 보고** 켠다 — 이름 앞부분으로 맞춘다.
    agent_narration_blocked_models: tuple[str, ...] = ("plopfit-gemma4", "gemma4")
    ollama_max_tool_steps: int = 12
    #: ★ Code 모드만 따로 (2026-09-20). 어려운 코딩 한 바퀴의 최소 걸음을 세어 보면
    #: 색인 1 · grep 1~2 · 읽기 2~3 · 고치기 1~2 · 돌리기 1 · 실패 읽고 다시 2~3 = **8~12**.
    #: 기본 12 는 한 바퀴를 겨우 돌고 끝나서, 시험이 빨간불인 채로 「승인하시겠습니까?」로
    #: 끝나는 판이 나왔다. 일반 대화는 12 그대로 둔다 — 넓은 예산은 헛도는 판을 길게 만든다.
    code_max_tool_steps: int = 24
    code_autonomous_max_steps: int = 80
    ollama_keep_alive: str = "24h"

    # ★ 굳은 요청을 끊는 자 (2026-08-31).
    #
    # `timeout_for()` 는 **한 판에 줄 시간**이라 code 는 900초다. 그런데 그 값이
    # httpx 의 `read` 로도 쓰이고 있었다 — 즉 **첫 바이트를 900초 기다렸다.**
    #
    # 실측(08-31 00:26): Ollama 가 요청을 받고 생성을 시작조차 안 한 채 굳었다.
    # 3090 0% · 슬롯 idle · 모델 상주. 자비스는 `_receive_response_headers` 에서
    # 3분 넘게 같은 스택으로 멈춰 있었고, 그대로 두면 15분을 기다렸을 것이다.
    # 벤치 예산이 1,200초인데 **멈춤 한 번이 판을 통째로 먹는다** — 어젯밤
    # `d9e13593`(11도구/1121초) `939b3c31`(15도구/1089초) 가 그것이었다.
    #
    # Ollama 는 스트리밍이라 **생성이 시작되면 토큰이 연속으로 온다.** 그래서
    # 조각 사이가 벌어지는 것 자체가 고장이고, 첫 바이트든 중간이든 같은 자로
    # 잰다. 300초 근거는 실측이다 — 그날 성공한 호출의 **총** 소요 최대가
    # 3분 53초(233초)였다. 생성 전체보다 긴 값이라 멀쩡한 판은 안 걸린다.
    #
    # ⚠ 프롬프트가 더 길어지면(프리필이 늘면) 이 값도 같이 봐야 한다. 늘리기
    # 전에 `agent_model_first_byte` 로 찍히는 첫 바이트 지연 분포를 볼 것.
    ollama_stall_timeout_sec: int = 300
    # 실측(2026-08-10, RTX 3090)으로 정한 값이다. 컨텍스트는 이 모델에서 거의 공짜다 —
    # Gemma 4 가 슬라이딩 윈도우 어텐션이라 KV 캐시가 창 크기만큼 자라지 않는다:
    #
    #     num_ctx    모델 VRAM    3090 여유
    #      24,576     14.03 GB     7,372 MiB
    #      65,536     14.27 GB     6,742 MiB
    #     131,072     14.41 GB     5,920 MiB      <- 24K -> 128K 가 0.38GB
    #
    # 속도도 같았다(같은 입력 4,029토큰: prefill 1.08s / 1.08s / 1.21s). 창을 크게
    # 잡는 것 자체는 값이 없고, **실제로 채웠을 때만** 비용이 붙는다.
    #
    # 2026-08-20: 64K → 128K.
    #
    # 쿠팡 판에서 도구 결과가 176,021자(약 88,000토큰) 나왔다. 64K 창에서는 담을
    # 방법이 없어 앞쪽이 잘렸고, 잘린 앞쪽에 **시킨 일**이 있었다(그래서 모델이
    # 시스템 프롬프트를 요약해 뱉었다). 창을 키우는 것은 위 표대로 0.38GB 다.
    #
    # 창만 키우면 안 된다 — 전사 예산(agent._bounded_transcript, 180,000자)과
    # **쌍이다.** 한쪽만 올리면 낮은 쪽이 계속 일한다. 긴 컨텍스트일수록 정확도가
    # 떨어지는 것도 여전하므로, 창을 채우지 않는 쪽(전사 접기)이 본 처방이다.
    # 모델 자체 한계는 262,144 라 아직 남아 있다.
    ollama_num_ctx: int = 131072
    # 이보다 큰 러너가 이미 떠 있으면 그걸 그대로 쓴다(_options). 재적재 14GB 를
    # 피하려는 장치다.
    # ★ 2026-09-26: 16K → 32K. 작은 모델(8GB 노트북)은 짧은 창에서 일을 못 한다 —
    #   외부 실측 8K 6/12 · 16K 9/12, 우리 4B 사다리도 32K 에서 쟀다. 남이 16K 로 올려 둔
    #   러너를 주워 쓰면 카탈로그가 32K 로 고른 것이 조용히 16K 가 된다. 재적재가 낫다.
    ollama_min_num_ctx: int = 32768
    ollama_adopt_resident_context: bool = True
    agent_routing_enabled: bool = True
    agent_thinking_enabled: bool = True
    #: 걸음마다 생각할 것인가. `always`(기본) · `adaptive` · `off`.
    #: 기본을 안 바꾸는 이유는 `agent._should_think` 주석에 있다 — 사고가 비싸다는
    #: 것만 쟀지, 값을 못 한다는 것은 아직 안 쟀다.
    agent_thinking_policy: str = "always"
    #: 열었으면 **같은 걸음에서** 읽는다.
    #:
    #: ★ 재고 켰다(2026-09-03). 같은 빌드에서 켬/끔만 바꿔 같은 프롬프트 4개:
    #:     시간 371초 → 285초 (**-23%**) · 품질 동일(대조 전부 충족·읽음 10·열고안읽음 0)
    #:   브라우저 판 셋 개별로도 -22% · -25% · -25% 로 일관됐다.
    #:
    #: 줄어드는 것은 걸음이 아니라 **모델 호출**이다. 추출은 그대로 걸음으로 남고,
    #: 그 사이의 모델 턴이 사라진다 — 그 턴은 아무것도 정하지 않았다.
    agent_fuse_open_and_read: bool = True
    agent_stream_enabled: bool = True
    agent_time_warning_sec: int = 30
    #: 「문제 보내기」 받는 곳(2026-09-29 결정: 손자리 개발팀 서버). 보여 주고 동의받은 내용만 간다 — problem_report.py.
    problem_report_url: str = "https://api.robometafit.com/sonjari/reports"
    agent_continue_short_sec: int = 180
    agent_continue_long_sec: int = 900
    agent_checkpoint_ttl_sec: int = 1800
    # 승인 카드가 살아 있는 시간. **위 체크포인트와 같은 값이어야 한다** (2026-08-14).
    #
    # 원래 `tool_gateway.ToolGateway` 의 클래스 기본값 300초(5분)로 박혀 있었고,
    # `runtime.py` 가 인자 없이 만들어서 **조절할 방법이 아예 없었다.**
    #
    # 그래서 승인이 잡보다 25분 먼저 죽었다. 되살릴 수 있는 잡을 승인이 없어서
    # 못 되살리는 것이다. 실측(승인 20건): 만료 3 · 미응답 4 — 그중 셋은 열흘째
    # `waiting_approval` 로 남아 있었다.
    #
    # 이건 그냥 불편이 아니라 **위임의 천장**이었다. L4 의 정의가 "맡겨 놓고 잊어도
    # 되는가"인데, 되돌릴 수 없는 일에 승인이 걸리고 그 승인이 5분 만에 죽으면
    # 자리를 비우는 순간 반드시 실패한다.
    #
    # 늘리는 대신 지키는 것: 승인은 **그 호출 하나에만** 묶인다(nonce + 도구명 +
    # 인자 대조, `JobStore.find_approved`). 그러니 창이 길어져도 "아까 누른 승인이
    # 딴 일에 쓰이는" 일은 없다. 위험은 "같은 일을 한참 뒤에 한다"뿐이고, 그건
    # 체크포인트가 이미 30분으로 정해 둔 범위다.
    approval_ttl_sec: int = 1800
    # 승인 방식 — 기본은 수동. 켜면 **되돌릴 수 있는 것만**(대상 때문에 등급이 오른 동작) 자동으로 지나간다.
    # 메일 발송·발행·결제·삭제처럼 등록 자체가 L2 인 것은 이 값으로도 안 열린다(`ToolGateway._auto_approvable`).
    approval_auto_reversible: bool = False
    #: 권한 모드 「권한 무시」(2026-09-23). 켜면 결제·메일 보내기·발행만 묻는다(`permissions.NEVER_BYPASS`).
    approval_bypass_enabled: bool = False
    # 승인 창이 닫히기 전에 한 번 더 데스크톱으로 알린다. 즉시 알림과 만료 직전
    # 알림 두 번이면 자리를 비운 판도 조용히 취소되지 않는다.
    approval_reminder_lead_sec: int = 300
    # 혼자 계속 갈 수 있는 상한.
    #
    # 예전에는 12스텝·180초에서 무조건 멈추고 사람을 불렀다. 그게 안전 장치처럼
    # 보였지만 사실은 아니다 — **되돌릴 수 없는 일은 어차피 L2 승인에서 따로
    # 멈춘다.** 여기 있던 12/180 은 안전이 아니라 자원 한도였고, 그 값이 자비스를
    # L3 에 묶어 두고 있었다(관측 스텝 중앙값 2, 긴 조사는 18에서 끊김).
    #
    # 그래서 규칙을 바꾼다: 되돌릴 수 없는 일을 아직 안 했고 진전이 있으면 혼자
    # 더 간다. 아래 둘은 그 '혼자'의 끝이다 — 무한히 도는 것을 막는 값이지
    # 사람을 부르는 값이 아니다.
    # ★ 30 → 48 (2026-09-01). 상한이 **성공 분포 한가운데** 박혀 있었다.
    #
    #   통과한 판의 걸음 수 실측: 19 · 24 · 26 · 32 · 34 · 44
    #   상한 30 은 그 사이다. 44걸음짜리가 통과했는데 30에서 끊고 있었다.
    #
    #   30 은 브라우저 조사용으로 정해진 값이다(예산 주석: "하나를 제대로 읽는 데
    #   두 걸음"). 저장소 작업은 읽고·고치고·돌려보고가 한 묶음이라 걸음이 더 든다.
    #   48 은 관측 최대(44)에서 한 뼘 여유다.
    agent_autonomous_max_steps: int = 48
    # ★ 900 → 1500 (2026-09-01). **전체 회귀 한 번이 277초**로 리스의 31% 다.
    #
    #   코드 작업은 "고치고 → 돌려보고 → 또 고치고"인데, 그 사이클이 두 번이면
    #   테스트만으로 리스가 끝난다. 통과한 판의 실측 소요는 337~1,202초였다.
    agent_autonomous_lease_sec: int = 1500
    # 자동으로 이어가는 **코드 작업**이 이 시간 안에 검증을 통과하지 못하면 그때까지 한 일을 담아 끝낸다(0 이면 끔).
    # 리스(위)는 진전이 있으면 계속 늘어나서, 검증을 못 하는 4B 가 29분까지 갔다(2026-09-22).
    # 값은 실측에서 골랐다: 이번 사다리 완료 36판의 최대가 592초, 이 저장소가 예전에 적어 둔 통과 최대가 1,202초 —
    # 어느 쪽도 안 자르는 1,200초. 하드웨어가 느리면 `JARVIS_CODE_JOB_STALL_SEC` 로 올린다. **검증에 성공한 판은 안 자른다.**
    code_job_stall_sec: int = 1200
    # 이 값 **이하**의 컨텍스트로 도는 판에서는 도구 정의를 줄인다(이야기가 안 나온 도구 가족을 빼고 긴 설명문을 자른다). 0 이면 끔.
    # 일반 Cowork 의 도구 128개는 18.4K 토큰이라 32K 컨텍스트의 56% 다(2026-09-22 실측). 주력(35B, 131,072)은 이 값보다 커서 영향이 없다.
    tool_surface_compact_max_ctx: int = 40_000
    # 위의 작은 창에서, **조사 판**에는 「찾아서 읽고 파일로」 묶음만 싣는다(`tool_roster._SMALL_WINDOW_RESEARCH_BUNDLE`).
    # 2026-10-12 — 재 보고 켠다. 기본은 꺼 둔다(창 32K 의 9B · 4B 로 같은 가격 조사 세 과제를 돌려 본 뒤 정한다).
    # ★ 2026-10-13 기본을 **켠다.** 묶음만으로는 줄 수가 안 올랐다(9B 1 → 0 · 4B 2 → 2 · 각 1판). 그런데 그 뒤 이틀 밤의
    #   작은 창 고침(지침을 손에 맞춤 · 읽은 것 늘 보이기 · 창의 빈 자리 쓰기 …)과 측정은 **전부 이 PC 의 켠 상태**에서 했다 —
    #   가격 조사 9B 평균 2.2 → 4.6 · 4B 3.2 → 4.0 줄, 네 번 이어 묻기 여덟 줄기 통과가 다 그 조합이다. 지침 줄이기는 이 스위치가
    #   켜져 있어야 돈다. 꺼 둔 채 내보내면 작은 카드를 쓰는 사람은 **한 번도 재 보지 않은 조합**으로 돌게 된다.
    #   큰 창(40K 초과) · 조사 아닌 판은 그대로다. 끄려면 `JARVIS_SMALL_WINDOW_RESEARCH_BUNDLE=0`.
    small_window_research_bundle: bool = True
    startup_warmup_enabled: bool = True
    # 한가할 때 고정 앞부분(도구 목록 + 고정 지침)을 데워 둔다 — 새 일의 첫 걸음이 그것을 처음부터 다시 읽지 않게(`ollama.prime_front`).
    front_prime_enabled: bool = True
    # 계획 요구로 판 도중에 모델을 미는가(되받기 · 힌트 · 단계 거절 · 대신 열기). 끄면 끝 검사만(2026-10-21 「밀기 켬/끔」 측정 — 요청의 `plan_push` 가 판마다 이긴다).
    plan_push_enabled: bool = True
    # 서기(2026-10-21 · `scribe`): 손자리가 놀 때 클로드 코드 대화 기록을 읽어 「이야기 카드」 초안을 쌓는다. **기본 꺼짐** —
    # 남의 대화 기록을 읽는 일이라 사람이 켜고, 읽을 폴더(`~/.claude/projects/<프로젝트>`)도 사람이 고른다(`;` 로 여럿).
    scribe_enabled: bool = False
    scribe_folders: str = ""
    # 읽을 새 말이 없을 때 다시 보기까지(초). 새 말이 남아 있으면 조용해진 뒤 바로 다음 덩어리를 읽는다.
    scribe_interval_sec: int = 900
    #: 압축 직후 서기 카드와 같이 다시 넣을 「일하는 방식」 파일(선택 · 비우면 안 넣음 · 2026-10-22 서기 훅 제품화).
    scribe_style_file: str = ""
    # 손자리가 켜는 Ollama 에 넘기는 서버 보관함 한도(MiB). -1 = 이 PC 메모리에 맞춰 · 0 = 손대지 않음(`ollama_install.ollama_launch_env`).
    ollama_prompt_cache_mib: int = -1
    startup_warmup_retry_sec: int = 120

    conversation_session_id: str = "office-main"
    # 워크스페이스가 살아 있다고 보는 시간. 화면은 그보다 자주 알려 온다(약 20초).
    # 짧게 잡으면 잠깐 끊긴 사이 음성 답변이 팝업으로 새고, 길게 잡으면 창을 닫은
    # 뒤에도 한동안 아무 데도 안 뜬다.
    workspace_presence_ttl_sec: int = 75
    # 사람이 아니면 못 푸는 브라우저 실패를 화면·알림·음성으로 올릴지.
    attention_notices_enabled: bool = True
    # ★ **스스로 일감을 만드는 두 가지**를 끌 수 있게 한다 (2026-09-05).
    #
    #   예약(scheduler)과 관찰 초소(watches)는 사람이 안 시켜도 잡을 큐에 넣는다.
    #   그게 이 둘의 존재 이유인데, 대신 **아무도 안 볼 때도 3090·3060 이 돈다.**
    #   실측(2026-09-05 새벽): 관찰 셋(크몽 2·위시켓 1, 6시간 주기)이 도는 동안
    #   3060 이 84°C·94%·170W 상한에 붙어 있었고, 두 카드 합쳐 350W 를 뿜었다.
    #   끄고 60초 뒤 43W 로 내려갔다.
    #
    #   목록을 비우는 것(`watch_cancel`)으로는 부족하다 — 그러면 다음에 누가
    #   하나 세우는 순간 조용히 다시 돌기 시작한다. **스위치가 있어야 꺼진 것이
    #   꺼진 채로 남는다.**
    #
    #   기본값은 켜짐이다. 끄는 것은 이 PC 의 선택이지 이 코드의 기본이 아니다.
    scheduler_enabled: bool = True
    watches_enabled: bool = True
    memory_recent_messages: int = 12
    memory_max_chars: int = 12000
    memory_compact_batch: int = 6
    memory_retrieval_enabled: bool = True
    # 대화에서 사실을 뽑아 서랍에 넣는가 (P2). 끄면 서랍은 손으로 넣은 것만 남는다.
    # 켜 두는 편이 맞지만, 끄는 스위치가 있어야 「추출 때문인가」를 가릴 수 있다.
    fact_learning_enabled: bool = True
    memory_retrieval_limit: int = 4
    memory_retrieval_max_chars: int = 4200
    visual_memory_max_age_sec: float = 3600.0

    # 예약 작업이 **사람 없이** 결과를 보내도 되는 주소. 여기 없는 주소로 보내
    # 달라는 예약은 `schedule_create` 가 그 자리에서 거절한다.
    #
    # ★ 왜 「보낼 때」가 아니라 「예약을 만들 때」 막나 (2026-08-21).
    #   `google_gmail_send` 는 L2 이고 되돌리기가 없다 — 보낸 메일은 못 지운다.
    #   그런데 아침 7시에 예약이 돌 때는 승인해 줄 사람이 없다. 그러니 승인은
    #   **사람이 있는 시점**, 곧 예약을 만드는 순간에 받아야 한다. 그때 수신자와
    #   내용이 이미 정해지고, 그 둘이 곧 승인의 내용이다.
    #
    #   오늘 캘린더에 단 가드와 같은 논리다: 밖으로 나가면 사람 앞에, 나한테
    #   오는 것이면 아니다. 여기 적힌 주소는 「나한테 오는 것」의 목록이다.
    #
    #   쉼표로 나눈다. 비워 두면 예약 메일 배달이 **통째로 꺼진다** — 기본이
    #   안전한 쪽이다.
    # 자기 검사(self_check)의 속도 판정. **1순위는 그 PC 의 평소 속도다** — 모델을 적용할 때 그 PC 에서 잰 값
    # (`model_setup` 선택 파일의 verified.tokens_per_sec) × 아래 비율보다 느리면 고장.
    # 2026-08-20 실측: 3090 정상 117~136 tok/s, 3090 이 빠져 CPU 로 내려갔을 때 2.3 (평소의 2%).
    # 2026-09-18 노트북(RTX 5050 Laptop): 정상이 15~20 tok/s. 절대값 30 을 기준으로 뒀더니 **정상 노트북을 고장이라
    # 불렀다** — 하드웨어 속도를 고장으로 읽은 것. 그래서 절대값은 평소 값이 없을 때만 쓰는 바닥(「쓸 수 없을 만큼」)이다.
    self_check_min_speed_ratio: float = 0.4
    self_check_min_tokens_per_sec: float = 5.0
    # 켤 때 엔진·모델을 한 번 스스로 점검한다(2026-09-18). 그 전에는 사람이 「너 괜찮아?」라고 물을 때만 돌아서
    # 노트북이 모델을 하나도 못 올리는 채로 조용히 있었다. 켜자마자 부르면 우리 Ollama 가 아직 안 떴을 수 있어 조금 기다린다.
    self_check_on_boot: bool = True
    self_check_boot_delay_sec: float = 45.0
    # 있어야 할 그래픽카드 수. 0 이면 안 센다. 같은 날 3090 이 드라이버 사고로
    # 통째로 사라졌는데 자비스는 한마디도 안 했다 — 그 자리를 메운다.
    self_check_expected_gpus: int = 0
    # 본체 안에서 디스코드 다리를 돌린다(2026-10-18, `messaging/service.py`). 저장된 봇 토큰이 없으면 어차피 안 뜬다.
    # 끄면 따로 띄우는 다리(`python -m alture_jarvis.messaging`)만 쓴다.
    discord_bridge_enabled: bool = True
    scheduled_mail_recipients: str = ""
    supertonic_base_url: str = "http://127.0.0.1:7788"
    supertonic_voice: str = "F1"
    supertonic_language: str = "ko"
    supertonic_task_name: str = "Alture-Jarvis-Supertonic"
    tts_enabled: bool = True
    tts_steps: int = 4
    tts_speed: float = 1.08
    tts_voice_max_chars: int = 70
    tts_summary_max_chars: int = 72
    tts_warmup_enabled: bool = True

    camera_enabled: bool = False
    camera_name: str = ""
    camera_index: int = 0
    # Set this to read from a network stream instead of a local USB device --
    # rtsp://... for an IP camera, rtmp://127.0.0.1:1935/live/pocket3 for a
    # local relay. When it is set, camera_index/camera_backend are ignored and
    # the frame size the sender chose is used as-is.
    camera_stream_url: str = ""
    camera_stream_reconnect_sec: float = 3.0
    camera_stream_read_timeout_sec: float = 12.0
    # Optional screen-capture input for device integrations. It wins over
    # camera_stream_url when both are set.
    camera_screen_capture_enabled: bool = False
    # Recognising who is in frame, and sweeping the room to look for them.
    # Face data never leaves this PC: both paths below are local files.
    face_recognition_enabled: bool = False
    # 받아 온 모델(수백 MB)이라 앱을 지워도 남게 둔다 — 앱 전용 칸이면 재설치마다 다시 받는다.
    face_model_dir: Path = field(
        default_factory=lambda: _outside_app_data(
            legacy=_default_runtime_root() / "data" / "faces" / "models",
            fresh=engine_dir(Path.home()) / "faces",
        )
    )
    face_registry_path: Path = field(
        default_factory=lambda: _default_runtime_root() / "data" / "faces" / "registry.json"
    )
    # Default sweep geometry for an explicitly configured device integration.
    sweep_left_steps: int = 1
    sweep_right_steps: int = 4
    sweep_step_seconds: float = 2.5
    # Empty means "pick by URL scheme" (see VisionService._stream_ffmpeg_options).
    # Set it to override; the format is OpenCV's own "key;value|key;value".
    camera_stream_ffmpeg_options: str = ""
    # Gimbal control by driving DJI Mimo on the tablet over ADB. Off by default:
    # these tools move a physical camera, so it should be a deliberate opt-in.
    camera_control_enabled: bool = False
    camera_control_adb_serial: str = ""
    camera_control_package: str = "mimo.sz"
    # Restart the Mimo livestream when vision has had no frames for this long.
    # Generous on purpose: a restart walks the whole wizard, so reacting to a
    # brief Wi-Fi wobble costs more than waiting it out.
    camera_autorecover_enabled: bool = True
    camera_autorecover_after_sec: float = 90.0
    camera_autorecover_cooldown_sec: float = 300.0
    camera_width: int = 1920
    camera_height: int = 1080
    camera_fps: int = 30
    camera_backend: str = "msmf"

    vision_enabled: bool = True
    vision_model: str = "yolo26n.pt"
    vision_device: str = "cuda:0"
    vision_fps: float = 1.0
    vision_imgsz: int = 416
    person_enter_hits: int = 2
    person_enter_window: int = 3
    person_exit_after_sec: float = 2.0

    voice_enabled: bool = True
    microphone_name: str = ""
    sample_rate: int = 16000
    stt_model: str = "large-v3-turbo"
    stt_device: str = "cuda"
    stt_device_index: int = 0
    stt_compute_type: str = "int8_float16"
    # CPU 로 받아쓸 때 모델(그래픽 카드용 라이브러리가 없는 포장본 등). large-v3-turbo 는 CPU 에서 5초 음성에 6초 걸렸다.
    stt_cpu_model: str = "small"
    # 받아쓰기 언어. "auto" 면 모델이 알아서 고른다(영어판 P0 에서 화면 언어와 잇는다).
    stt_language: str = "ko"
    hotkey_enabled: bool = True
    hotkey: str = "f9"
    hotkey_suppress: bool = True
    hotkey_trigger_on_release: bool = True
    media_pause_enabled: bool = True
    media_excluded_apps: str = "teams,ms-teams,zoom,webex,discord"
    media_resume_delay_sec: float = 0.3

    # Optional compatibility adapter for the separately installed Plopfit app.
    # Public builds do not assume that another private checkout exists.
    plopfit_enabled: bool = False
    # Open WebUI(패키지 밖 프로그램)가 읽어 가는 자리라 앱 전용 칸이면 안 보인다.
    plopfit_functions_dir: Path = field(
        default_factory=lambda: _outside_app_data(
            legacy=_default_runtime_root() / "integrations" / "plopfit" / "functions",
            fresh=product_dir(Path.home()) / "plopfit" / "functions",
        )
    )
    plopfit_lib_dir: Path = field(
        default_factory=lambda: _outside_app_data(
            legacy=_default_runtime_root() / "integrations" / "plopfit" / "lib",
            fresh=product_dir(Path.home()) / "plopfit" / "lib",
        )
    )
    pc_mcp_base_url: str = "http://127.0.0.1:8088"
    pc_mcp_token: str = ""
    enable_system_actions: bool = False

    # 우리 데이터(입시·진로 조회)를 자비스가 보는 창구. NAS 가 스키마째 내려준다.
    # ⚠ 아래 `load()` 에도 같은 항목이 있고 **거기가 이긴다.** 한쪽만 고치면 아무
    # 일도 안 일어난다(browser_max_elements 로 이미 한 번 헛돌았다).
    inhouse_data_enabled: bool = False
    inhouse_api_base: str = ""
    inhouse_api_key: str = ""
    inhouse_api_header: str = "X-API-Key"
    inhouse_tenant_id: str = ""
    # 기동 때 목록을 받아 오는 시간. 짧게 잡는다 — NAS 가 느리다고 자비스가
    # 안 뜨면 안 된다. 실패하면 마지막 캐시로 뜬다.
    inhouse_startup_timeout_sec: float = 6.0
    inhouse_call_timeout_sec: float = 45.0

    browser_enabled: bool = True
    browser_headless: bool = False
    # ★ 사람이 PC 를 쓰는 중이면 화면을 뺏지 않는다 (2026-09-16, 인수인계 H2-A · `user_presence.py`).
    #   최근 이 초 안에 키보드·마우스 입력이 있으면 브라우저 창을 앞으로 안 가져오고, 창에 키를 보내는 조작은 손이
    #   멈출 때까지 기다린다. `assume_user_active` 는 실측용(늘 쓰는 중인 것처럼).
    #   ★ dataclass 기본은 끔, 로더(실제 제품)는 켬 — 켜 두면 시험이 **돌리는 사람의 실제 키보드 입력 시간**을 읽어
    #   결과가 그때그때 달라진다(2026-09-16 전체 시험에서 되돌리기 시험이 그렇게 흔들렸다). 사고 Q 의 두 자리 규칙.
    yield_to_user_enabled: bool = False
    yield_to_user_active_sec: float = 10.0
    assume_user_active: bool = False
    # 자비스 크롬이 처음 떴을 때 보여 줄 곳.
    #
    # about:blank 였다. 자비스가 자기 일을 할 때는 주소로 바로 가니 상관없지만,
    # **사람이 그 창을 쓸 때**가 문제였다 — 로그인을 하려고 봐도 빈 화면이라
    # 주소를 손으로 쳐야 했다(2026-08-10 사용자 지적). 네이버를 띄워 두면 거기서
    # 검색해서 들어갈 수 있고, 네이버 로그인 자체도 바로 된다.
    #
    # 빈 문자열로 두면 예전처럼 about:blank 다.
    browser_home_url: str = "https://www.google.com"
    browser_read_only: bool = True
    browser_sandbox: bool = True
    browser_visual_overlay: bool = True
    # 크롬을 **Playwright 가 띄우지 않고**, 평범하게 띄운 크롬에 DevTools 로 붙는다.
    #
    # 2026-08-11 실측(같은 PC·같은 UA·같은 headed):
    #
    #   Playwright 가 띄운 크롬   navigator.webdriver=true   쿠팡 상품검색 Access Denied
    #   chrome.exe + CDP attach  navigator.webdriver=false  열림 · 상품 309개
    #
    # 원인은 위장 여부가 아니다. Playwright 는 `--remote-debugging-pipe` 로 크롬을
    # 모는데 그게 크롬을 자동화 모드로 넣고(webdriver=true), 덤으로 사람 브라우저엔
    # 없는 플래그 40여 개(--disable-extensions·--disable-sync·--use-mock-keychain…)가
    # 붙는다. `--remote-debugging-port` 는 자동화 모드가 아니다 — 개발자가 DevTools
    # 를 여는 것과 같은 길이라 **숨기는 것이 없다.** 우리가 금지한 것은 위장
    # (웹드라이버 플래그 감추기·UA 위조·캡차 풀기)이지 진짜 브라우저를 쓰는 것이
    # 아니다.
    #
    # "auto": 붙어 보고 안 되면 예전 방식으로 내려간다(왜 내려갔는지 `status()` 에
    # 남긴다 — 조용히 갈아타지 않는다). "off": 예전 방식만.
    browser_attach_mode: str = "auto"
    browser_cdp_port: int = 9222
    # 빈 값이면 찾아 쓴다(`_find_chrome`).
    browser_chrome_path: str = ""
    # 만든 화면(이 PC 안 페이지)을 열 때 화면 없는 크롬으로 따로 찍어 모델의 눈으로 본다(`page_look`). 열 때마다 몇 초가 든다
    # (찍기 약 2초 · 보기 1~4초). 그림을 못 보는 모델에서는 아무 말도 안 나올 뿐이다. 끄려면 JARVIS_PAGE_EYE_ENABLED=0.
    page_eye_enabled: bool = True
    # 붙을 크롬이 뜨기를 기다리는 시간. 프로필이 잠겨 있으면(같은 프로필로 크롬이
    # 이미 떠 있으면) chrome.exe 는 기존 프로세스에 일을 넘기고 그냥 죽는다 —
    # 포트가 끝내 안 열리는 것으로 드러난다.
    browser_attach_launch_timeout_sec: int = 25
    # 한 목록이 스냅샷 예산을 몇 개까지 먹을 수 있는가. 0이면 상한 없음.
    #
    # 드롭다운이 열리면 그 카탈로그가 목록을 통째로 먹어 **다른 칸이 밀려난다**
    # (위시켓 기술 카탈로그). 스냅샷은 DOM 순서로 자르므로, 앞에 놓인 목록 하나가
    # 예산 120개를 다 쓰면 그 뒤의 저장 버튼·다음 입력칸은 화면에 뻔히 보이는데도
    # 자비스 눈에는 없다 — [[jarvis-browser-sees-only-tags]] 와 같은 병이다.
    #
    # 잘라도 **잘랐다고 말한다**(항목의 `group_more`). 조용히 자르면 "그 화면엔
    # 그런 것이 없다"는 잘못된 결론이 나온다.
    browser_snapshot_group_cap: int = 15
    # 크롬이 직접 읽고 쓰는 프로필이라 **앱 전용 칸 밖**에 둔다(2026-09-18, `_outside_app_data`).
    browser_profile_dir: Path = field(
        default_factory=lambda: _outside_app_data(
            legacy=_default_runtime_root() / "data" / "browser-profile",
            fresh=product_dir(Path.home()) / "browser-profile",
        )
    )
    browser_download_dir: Path = field(
        default_factory=lambda: downloads_dir(Path.home())
    )
    # Screenshots and frame dumps kept whenever a browser step fails, so the
    # next session inherits the evidence instead of re-deriving it. The
    # 2026-08-03 임시저장 chase cost two days for exactly this reason.
    browser_evidence_dir: Path = field(
        default_factory=lambda: _default_runtime_root() / "outputs" / "browser-evidence"
    )
    # Site procedures live here as reviewed JSON rather than as Python. See
    # site_recipes.py for why.
    # Package-relative, not runtime-root-relative: recipes are versioned source
    # that ships with the code, not per-machine state like the browser profile.
    site_recipe_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "recipes"
    )
    # 유니티 에디터가 설치된 자리(세미콜론으로 여럿). 허브 기본 자리를 먼저 보고, 허브의 추가 설치 자리는 코드가 스스로 찾는다.
    # 레시피 실행 시간 상한 — 배치 모드는 프로젝트를 여는 데만 1분 남짓 든다(FPS Microgame 실측 71초).
    unity_editor_roots: str = r"C:\Program Files\Unity\Hub\Editor"
    unity_run_timeout_sec: int = 900
    # 밖에서 가져온 지식(스킬). 레시피와 같은 이유로 패키지 기준이다 — 코드와 함께
    # 버전이 매겨지는 자료지 PC 마다 다른 상태가 아니다.
    #
    # ★ 이 값은 **여기와 `load()` 두 곳에 산다.** 한쪽만 고치면 조용히 헛돈다 —
    #   이 저장소가 하루에 네 번 밟은 그 지뢰다(dataclass 기본값 · 환경변수 로더 ·
    #   함수 안 하드 상수).
    skills_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "skills"
    )
    # 분야 팩(2026-09-27, 전략안 §50). 레시피·스킬과 같은 이유로 패키지 기준 — 우리 팩은 코드와 함께 버전이 매겨진다.
    packs_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "packs"
    )
    # 사람이 스킬팩을 넣는 폴더(2026-10-11). 비워 두면 문서 폴더 안의 `skillpacks` 다(`skillpacks_dir`) — 문서 폴더를
    # 옮기면 같이 따라가야 해서 여기에 경로를 박지 않는다. ↓ `load()` 의 `JARVIS_USER_PACKS_DIR` 와 짝.
    user_packs_dir: Path | None = None
    # ── 역할: 이 자비스가 「본체」인가 「위성」인가 (2026-08-21) ──────────────
    #
    # 위성은 **자기 PC 의 손과 눈**(파일·창·브라우저)을 그대로 갖되, 무거운 것만
    # 본체에서 빌려 쓴다:
    #
    #     젬마 추론   JARVIS_OLLAMA_BASE_URL     -> 본체 (VRAM 이 거기 있다)
    #     음성 합성   JARVIS_SUPERTONIC_BASE_URL -> 본체 (소리는 여기서 난다.
    #                                               WAV 를 받아 winsound 로 튼다)
    #     STT        ★ 못 빌린다 — faster-whisper 는 HTTP 서비스가 아니라
    #                프로세스 안에서 GPU 로 돈다. 위성은 음성 입력이 없다
    #
    # ★ 스위치를 따로따로 두지 않고 **역할 하나**로 묶는 이유: 위성에서 꺼야 할
    #   것이 넷인데, 사람이 매번 기억하면 하나씩 빠진다. 그리고 빠진 쪽은 조용히
    #   틀린다 — 예약 메일이 두 대에서 나가거나, 없는 GPU 로 STT 를 올리려 든다.
    jarvis_role: str = "primary"
    # 대화 모델이 **어디서 정해졌나** — `env`(설정 파일·환경변수) / `setup`(첫 실행 화면에서
    # 사용자가 고르고 실제로 돌려 본 것, data/model_selection.json). 두 곳이 다르면 누가
    # 이겼는지 모르고 헤맨다 — 이 저장소가 「값이 사는 자리」로 여러 번 데였다.
    model_source: str = "env"
    #: 화면이 **쓰는 사람을 뭐라고 부를 것인가.** 「사용자」·「선생님」·이름 등.
    #
    # ★ 2026-09-11. 이 이름이 UI 소스 다섯 곳에 **박혀 있었다.** 그래서 다른 사람에게
    #   줄 판을 만들 때 본체 소스를 고쳐야 했고, 실제로 그렇게 고친 것이 사용자 화면에
    #   그대로 나왔다 — 「자비스 나는 누구게」에 상대 이름이 뜬 것이다.
    #
    #   이름은 **판마다 다른 값**이지 코드가 아니다. 설정으로 내린다. 한 소스로 두
    #   판을 만들 수 있어야 다음에 또 안 샌다.
    user_label: str = ""
    skills_enabled: bool = True
    # 이어받기(전략안 §44) — 한도로 멈춘 클로드·코덱스 대화를 찾아 제안한다. 반자동이라 켜진 채로
    # 태어난다: 최근 멈춘 대화가 없으면 모델을 한 번도 안 부르고, 있어도 묻기만 한다.
    takeover_enabled: bool = True
    # 가지(worktree)에서 코드를 이어 작업하는 H2 는 코드 베타 관문을 못 넘었다(실제 1회 0편집).
    # Cowork 선공개에서는 채팅으로 「응」이라고 해도 인계문만 만든다. 켜는 문은 이 한 줄이다.
    # ★ 2026-09-20 기본값을 켠다 (사장님 지시: "코드모드에서 이어받기가 핵심인데 안 되더라고").
    #
    #   목표는 하나다 — **클로드 한도가 끝나면 온텔릭이 상당 부분을 이어받는 것.**
    #   꺼 둔 근거는 "H2 실제 시험이 기본 추천 조건을 못 넘었다"(9월 중순)였다. 그 사이 모델과
    #   배선이 바뀌었고, 무엇보다 **되돌리기가 「가지 하나 삭제」로 끝난다** — 이 저장소가 쓰기를
    #   여는 기준으로 삼아 온 그 선 안이다. 원래 폴더는 건드리지 않고 worktree 에서만 일한다.
    takeover_branch_enabled: bool = True
    # 기억 복제 폴더(W1-3). 스토어 MSIX 는 앱을 지우면 AppData 전용 칸을 같이 지운다 — 사용자 폴더
    # 아래에 대화·배운 사실 복제본을 둔다. ★ dataclass 기본값은 **꺼짐(None)** 이고 로더가 켠다:
    # 시험·임시 런타임이 실제 사용자 홈에 복제본을 흘리지 않게. 끄는 문은 JARVIS_MEMORY_BACKUP_ENABLED=0.
    memory_backup_dir: Path | None = None
    # 스킬 온보딩(W4)에서 고른 분야. 비면 전부 후보. 분야는 트리거를 대신하지 않고 **후보만 좁힌다**.
    skills_domains: tuple[str, ...] = ()
    # 화면(data/settings.json)에서 얹힌 키. 어디서 왔는지 보이게(`model_source` 와 같은 뜻).
    settings_applied: tuple[str, ...] = ()
    # ★ 갈래는 **꺼진 채로 태어난다.** 도구(skill_list·skill_read)는 켜져 있어도
    #   아무것도 강제하지 않지만, 이건 답변 경로의 시스템 프롬프트를 바꾼다.
    #
    #   켜기 전에 사람이 한 번 봐야 하는 이유: 매칭이 도는 것은 검사로 증명했지만
    #   (`test_skill_routing.py`, 부정 14건 포함), **영어 플레이북 7,000자를 받은
    #   젬마가 한국어로 좋은 답을 내는지**는 라이브에서만 알 수 있다. 답이 영어로
    #   샐 수도 있고, 전보다 나쁠 수도 있다. 그건 쓰는 사람만 판단할 수 있다.
    skills_route_enabled: bool = False
    #: 부르는 쪽이 스킬을 안 지목했을 때 **젬마에게 한 번 물어볼 것인가.**
    #
    # 실측 2026-09-09: 10판에서 진짜 오답 0, 응답 0.7초. 스킬이 필요 없는 판에서는
    # 정확히 `none` 을 냈다. 도구 133개 중에서는 헤매던 모델이 스킬 분류는 해낸다 —
    # 「지금 무엇을 해야 하나」와 「이 요청이 무슨 종류인가」는 다른 일이다.
    #
    # 판마다 모델 호출이 한 번 더 붙는다(웜 0.7초). 그 값이 아까우면 끈다 —
    # 끄면 낱말표가 하던 대로 한다.
    skills_guess_enabled: bool = True

    # ★ 사고 도구 목록만 상시로 띄운다 (2026-08-31).
    #
    # 스킬은 두 종류가 섞여 있었다. `kmong-listing`·`nas-deploy` 는 **사람이 말로
    # 부르는 것**이라 낱말표(`SKILL_TRIGGERS_KO`)가 맞다. 그런데 `thinking-*` 은
    # **사람이 그 이름을 말하지 않는다** — "지금 병목이 어디지"라고 묻지
    # "theory-of-constraints 써줘"라고 하지 않는다. 상황을 알아보는 건 모델의 일이다.
    #
    # 그래서 28종 중 **20종이 갈래가 없어 도달 불가**였고, `skill_list` 는 장부
    # 10,548건 중 **2건**(0.04%)만 불렸다. 어느 길로도 안 쓰이고 있었다.
    #
    # 예전에 「61종 이름을 상시로」가 한 번 기각됐는데(`_skill_instruction` 주석),
    # 이유는 토큰이 아니라 **희석**이었다 — "지금 몇 시야"에 마케팅 목록이 딸려간다.
    # 그 걱정의 실체는 marketing 28종(20,616자)이다. 여기서는 그걸 안 싣는다:
    #
    #     thinking 28종 한 줄(60자)   2,359자   ← 이것만
    #     marketing 28종 전체        20,616자   ← 안 실음
    #
    # 되돌리기는 이 한 줄이다. 효과는 `skill_read` 호출 수로 잰다(지금 0건).
    skills_thinking_card_enabled: bool = True

    #: 한 줄 설명을 몇 글자까지 보여줄까. 늘리기 전에 실제 크기를 다시 재라.
    skills_thinking_card_chars: int = 60
    # 가장 긴 SKILL.md 가 30KB(humanizer)다. 그대로 내주면 도구 결과 하나가
    # 전사 예산(`agent._TRANSCRIPT_BUDGET_CHARS`)의 6분의 1을 먹는다. 자를 때는
    # 글자가 아니라 `##` 절 단위로 접고, 몇 절을 접었는지 같이 돌려준다.
    skills_body_max_chars: int = 12000
    # ── 격리 상자 (5차 C) ────────────────────────────────────────────────
    #
    # ★ 이것도 **꺼진 채로 태어난다.** 상자 안에서 임의 코드가 돈다는 뜻이라,
    #   `/etc/wsl.conf` 의 격리(automount·interop off)가 살아 있는지 사람이 한 번
    #   보고 켜는 게 맞다. `SandboxBox.status()` 가 `isolated` 로 매번 다시 읽는다.
    sandbox_enabled: bool = False
    sandbox_distro: str = "Ubuntu"
    sandbox_timeout_sec: int = 60
    sandbox_output_max_chars: int = 8000
    sandbox_fetch_max_bytes: int = 8_000_000
    # 상자가 만든 파일이 나오는 자리. **하나로 고정한다** — 상자가 경로를 정하게
    # 하면 격리가 의미를 잃는다.
    sandbox_output_dir: Path = field(
        # 설치 폴더 옆이면 스토어판에서 읽기 전용(WindowsApps)이다. 앱 데이터 안도 안 된다 —
        # 상자(WSL)는 **패키지 밖**이라 앱 전용 칸이 안 보인다. 상자가 쓴 파일과 우리가 읽는 파일이 갈린다.
        default_factory=lambda: _outside_app_data(
            legacy=_default_runtime_root() / "outputs" / "sandbox",
            fresh=product_dir(Path.home()) / "sandbox",
        )
    )
    # Claude Code는 로컬 상자가 같은 파일에서 두 번 막히거나, 처음부터 다중 파일·git
    # 저장소 작업일 때만 결정론으로 열린다. 임대시간을 넘으면 session_id를 보존해
    # 다음 판에서 --resume으로 잇는다 — 단일 JobRunner를 계속 붙들지 않기 위해서다.
    # ★ 2026-10-19: 사용자 설정 「막히면 내 클로드에게 넘기기」(설정 › 연결)의 **기본값**이다. 기본 꺼짐 —
    #   2026-08-27 측정에서 24판 중 6판이 다중 파일 조건으로 클로드에게 빠져 로컬 실력이 부풀어 보였다(운영 .env 도 그래서 0).
    #   이 값(환경변수 포함)은 기본값일 뿐이고 화면에서 켠 값이 이긴다(`settings.apply_user_settings`).
    #   측정 판은 이 값과 무관하게 언제나 꺼진다(`claude_code.measurement_reason`).
    claude_code_enabled: bool = False
    # 관리자 잠금(`JARVIS_CLAUDE_CODE_LOCKED`). 참이면 화면에서 켤 수 없고(「관리자가 꺼 둠」) 켜 둔 값도 일하지 않는다.
    claude_code_locked: bool = False
    # ★ 2026-10-26 「막히면 내 API 키로 클로드에게 한 번 묻기」(`api_escalation.py` · `docs/설계_혼합_로컬API승급_2026-10-26.ko.md`).
    #   넘기기(위 claude_code_*)와 다른 길이다 — 구독 로그인이 아니라 사용자가 손자리에 넣은 API 키. 기본 꺼짐 · 측정 판은 늘 꺼짐.
    #   키는 여기 두지 않는다(DPAPI · `data/secrets/`). 달 상한은 달러 정수.
    api_escalation_enabled: bool = False
    api_escalation_model: str = "claude-opus-5-5"
    api_escalation_monthly_usd: int = 3
    claude_code_command: str = "claude"
    claude_code_lease_sec: int = 90
    claude_code_result_max_chars: int = 16_000
    # 업로드는 이 PC 파일을 바깥으로 내보내는 동작이라 승인(L2)만으로 부족하다.
    # 승인 화면의 경로만 보고 그게 무엇인지 사람이 판단하기 어려우므로, 애초에
    # 나갈 수 있는 뿌리를 정해 둔다. 기본은 사용자가 스스로 고른 파일이 모이는 곳.
    browser_upload_allowed_roots: tuple[str, ...] = field(
        default_factory=lambda: (
            str(Path.home() / "Desktop"),
            str(Path.home() / "Documents"),
            str(Path.home() / "Downloads"),
        )
    )
    browser_upload_max_bytes: int = 32 * 1024 * 1024
    #: 요소 하나를 누르거나 채울 때 **눌릴 수 있게 될 때까지** 기다리는 상한(초).
    #
    # ★ 20 -> 8 (2026-09-09 실측). 위시켓 판에서 클릭 하나가 **43.9초** 걸렸고
    #   그 판 도구 시간의 대부분이었다. 8 초로 내려 9 판을 돌린 결과:
    #
    #       총 시간 중앙  122초 -> 67초      최악 456초 -> 109초
    #       편차(최대/최소) 8.3배 -> 2.4배
    #       실패 안 늘었고(9/9 completed) **걸음은 오히려 줄었다**(8 -> 7)
    #
    #   「빨리 포기하면 더 헤맬 것」이라는 걱정은 틀렸다. 20 초를 기다리는 동안
    #   화면이 바뀌어 오히려 헷갈렸던 것으로 보인다.
    #
    #   근거: 성공한 도구 호출 62건 중 8 초를 넘은 것은 **1건(1.6%)**이고 그것도
    #   클릭이 아니라 페이지 열기였다. 정상 동작의 90%가 2.4초 안에 끝난다 —
    #   8 초는 이미 정상의 3배 여유다.
    #
    #   ⚠ 표본은 한국 사이트 3곳 66건이다. 더 느린 곳(관공서·무거운 SPA)에서는
    #   멀쩡한 조작이 죽을 수 있다. `JARVIS_BROWSER_ACTION_TIMEOUT_SEC` 로 되돌린다.
    #   호스트별 동적 상한은 `took_ms` 분포가 쌓인 뒤에 만든다 — 모르는 것 위에
    #   규칙을 세우지 않는다.
    browser_action_timeout_sec: int = 8
    browser_navigation_timeout_sec: int = 30
    #: 열어 둘 탭의 최대 수. 넘으면 **우리가 연 것 중 오래된 것부터** 닫는다.
    #: 2026-09-16 사용자 지적: 조사 몇 판 뒤 탭이 18장이었다. 사람이 로그인해 둔 탭은
    #: 우리가 만지지 않은 것이므로 안 닫는다.
    browser_max_tabs: int = 6
    #: 우리가 크롬 창을 **앞으로 가져와도 되는가**. 기본은 안 된다 (2026-09-16, 두 번째 지적).
    #: 예전에는 「최근 10초 안에 사람이 키를 눌렀나」로 정했는데, 맡겨 놓고 지켜보는 사람은
    #: 키를 안 눌러 10초 뒤 양보가 풀렸다. 조건을 없앴다 — 뒤에서 일해도 결과는 같다.
    browser_allow_foreground: bool = False
    #: 창이 나타나는 순간 Win32 로 내려 앞을 안 뺏기게 하는 감시. 2026-09-16 에 이 감시가
    #: **사용자의 카카오톡 창과 보조 모니터 작업표시줄을 최소화**했다(이름 검사가 빠져 있었다).
    #: 이제 이름·창 클래스 두 겹으로 막았지만, 남의 창에 닿을 수 있는 종류의 코드라 끌 수
    #: 있게 둔다. 끄면 CDP 로만 내린다 — 크롬 말고는 절대 못 건드리지만 기동 순간은 못 막는다.
    browser_sink_windows: bool = True
    # 뜨는 동안 막 태어난 크롬 창을 보이기 전에 투명하게 만든다(콜드스타트 번쩍임). 끄면 예전처럼 20ms 감시만.
    browser_birth_guard: bool = True
    # 조용히 띄울 때 크롬 창이 **어느 모니터에도 안 겹치는 자리에서** 태어나게 한다(콜드스타트 번쩍임의 뿌리 처방).
    browser_birth_offscreen: bool = True
    #: ★ 2026-09-26: 주차 모드에선 크롬을 **창 없이** 띄우고 첫 창을 CDP 로 뒤쪽·화면 밖에 만든다. 첫 창이 앞창을 가져가는 것이
    #:   콜드스타트 앞창 줄다리기의 뿌리였다(이 PC 실측 3회: 보통 1,400ms 쥠 · 창 없이 0ms).
    browser_no_startup_window: bool = True
    # 일하는 동안 크롬을 화면 밖에 펴 두고, 사람이 할 일이 있을 때만 화면 안으로(2026-09-24 제품 결정)
    browser_park_offscreen: bool = True
    browser_task_timeout_sec: int = 180
    # Playwright CDP는 page.goto 응답 핸들을 연결 수명 동안 쌓는다. Chrome 자체는
    # 그대로 두고 이 횟수마다 attach 연결만 갈아 핸들을 회수한다. 0이면 끈다.
    browser_reconnect_after_navigations: int = 50
    # ★ 쌓이는 것은 탐색 횟수가 아니라 **페이지가 주고받은 요청 · 응답 기록**이다 (2026-10-14 실측).
    #   Playwright 는 그 기록을 종류마다 1만 개가 찰 때까지 연결 장부에 쥐고 있고, 윈도우에서는 기록 하나가 잠금
    #   (세마포어) 두세 개를 쥔다. 가격 조사 과제 세 개(탐색 5번)에 손잡이가 2,505 → 7,217개가 됐다 — 횟수 50번을
    #   기다리는 동안 수만 개가 쌓인다. 밤새 돌린 PC 셋에서 손잡이 7만~12만 개 · 메모리 18GB 까지 갔다.
    #   장부에 이 수만큼 쌓이면 다음 동작 앞에서 연결만 갈아 끼운다(크롬과 탭은 그대로). 0이면 끈다.
    browser_reconnect_after_objects: int = 4000
    # 물린 브라우저를 **스스로 되살리기까지** 기다리는 시간.
    #
    # 2026-08-16 실측: 한 번 물리면 3분이 지나도 안 풀렸다 — 느린 것이 아니라
    # 영영 안 끝나는 것이었고, 그날 사람이 세 번 손으로 껐다 켰다. 기다리는 것은
    # 답이 아니다. 다만 **진짜로 오래 걸리는 동작**(무거운 페이지 로딩)을 회복으로
    # 오해하면 멀쩡한 일을 죽이므로, 한 동작의 상한(180초)보다 짧게 두되
    # 사람이 답답해하기 전에는 움직이도록 60초로 잡는다.
    browser_stuck_recover_after_sec: int = 60
    # 2026-08-13: 120 → 200. 조작 가능 요소 선별을 넓히고 나니(`_INTERACTIVE` 에
    # onclick·tabindex 추가) 쿠팡 검색결과가 상한에 딱 걸렸다 — 200 개를 채우고
    # 잘렸다는 뜻이라, 그 뒤에 있는 것(정렬·필터·다음 페이지)이 안 보인다.
    # 컨텍스트는 이 모델에서 거의 공짜다(위 num_ctx 표: 24K→128K 가 0.38GB).
    browser_max_elements: int = 200
    # 문서만 내려온 뒤 화면이 그려질 때까지. 이걸 안 기다리면 스크립트가 그리는
    # 사이트(대학어디가·학교알리미·평가원 실측)가 "조작 가능한 요소 0개"로 읽힌다.
    browser_ready_timeout_ms: int = 6000
    # 봇 검사에 걸린 검색엔진을 얼마 동안 건너뛸 것인가.
    #
    # 차단은 한 번 걸리면 한동안 이어진다(2026-08-08 실측: 빙·구글이 새 임시
    # 프로필에서도 계속 막혔다). 그런데 매번 다시 시도하면 goto + 대기 + 수집으로
    # 검색 1회당 ~10초를 버리고, 이미 찍힌 엔진을 계속 두드리는 것 자체가 차단을
    # 유지시킨다. 그렇다고 영구 제외는 틀렸다 — 차단은 풀린다.
    browser_search_block_cooldown_sec: int = 600

    google_enabled: bool = True
    # Public desktop OAuth credentials belong to the app build. Environment
    # values support packaged/managed deployments; the legacy JSON path remains
    # a compatibility fallback for existing installations.
    google_project_id: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_bundle_path: Path = field(
        default_factory=lambda: _default_runtime_root() / "resources" / "google_oauth_client.json"
    )
    google_client_secret_path: Path = field(
        default_factory=lambda: _default_runtime_root() / "data" / "google" / "client_secret.json"
    )
    google_token_path: Path = field(
        default_factory=lambda: _default_runtime_root() / "data" / "google" / "token.dpapi"
    )
    google_oauth_timeout_sec: int = 900
    google_write_enabled: bool = False
    # ★ 제한(restricted) 권한 — 드라이브 전체 읽기·지메일 읽기 (2026-09-16, 인수인계 H4).
    #   공개 앱이 이 권한을 쓰면 Google 검증 + CASA 보안 평가를 12개월마다 받아야 한다. 그래서 공개판 기본은 끔:
    #   드라이브는 사용자가 고른 파일만(`drive.file` + Picker), 지메일 읽기는 브라우저 경로로. 사내 설치만 켠다.
    google_restricted_scopes_enabled: bool = False
    gmail_attachment_max_bytes: int = 20 * 1024 * 1024
    #: 드라이브에 한 번에 올릴 수 있는 크기. 멀티파트 업로드라 통째로 메모리에 올린다.
    drive_upload_max_bytes: int = 25 * 1024 * 1024
    gmail_attachment_max_count: int = 10
    calendar_default_timezone: str = "Asia/Seoul"
    # Slack the calendar guard allows before calling a start time "past".
    # "지금부터 회의" is legitimate, and the model composes the timestamp a
    # beat before the tool runs.
    calendar_past_grace_minutes: int = 5

    external_action_ttl_sec: int = 600
    # How long after a commit an identical payload counts as the same
    # instruction rather than a new one. Covers a double-pressed approval
    # card and the polling race that caused the 2026-08-20 double booking,
    # without blocking a genuine repeat forever. 0 disables the check.
    external_action_dedupe_window_sec: int = 600

    # Korean-only integration. Users opt in explicitly; it is not a global
    # product assumption.
    naver_blog_enabled: bool = False
    private_update_enabled: bool = False
    naver_blog_allowed_hosts: str = "blog.naver.com;admin.blog.naver.com;nid.naver.com"
    naver_blog_image_max_bytes: int = 10 * 1024 * 1024
    naver_blog_image_max_count: int = 20
    # A drafted post is written once and then discussed: the user reads it, asks
    # for an edit, decides, and only then approves. The commit tier keeps the
    # short TTL (it is minted immediately before the approval card), but letting
    # the *plan* expire in 10 minutes throws away the only copy of the draft
    # mid-conversation and forces the whole thing to be rewritten.
    naver_blog_plan_ttl_sec: int = 3600
    naver_blog_save_verify_timeout_sec: int = 8
    # 임시저장·발행이 **확인된 뒤** 브라우저를 닫을 것인가.
    #
    # 확인됐을 때만 닫는다. 확인이 안 된 채로 닫으면 오늘(2026-08-09) 같은 일이
    # 벌어졌을 때 증거가 사라진다 — 도구는 실패라고 했는데 편집기에는 글이 다
    # 들어가 있었고, 그 창이 없었으면 아무도 그걸 몰랐다.
    naver_blog_close_after_save: bool = True
    # 스마트에디터가 프레임 안에서 다 그려질 때까지. 바깥 페이지의 로딩 완료와는
    # 상관이 없어서, 이걸 안 기다리면 캐시가 식은 날에만 "제목 영역 없음"이 뜬다.
    naver_blog_editor_ready_timeout_ms: int = 15000

    #: 셸의 **바꾸는 명령**을 승인 없이 돌릴 것인가 (2026-09-20, 커서의 Run Mode 와 같은 자리).
    #:
    #: 기본은 꺼짐 — 만들기·지우기·설치·네트워크는 승인 카드가 뜬다. 사장님이 「자동으로 하길
    #: 원하면 버튼 하나」라고 하셔서 설정에 두었다. 켜도 **보안 설정·시스템 폴더는 안 열린다.**
    shell_autorun_enabled: bool = False
    #: 그림자 기록 — 판이 끝난 뒤 사람 요청의 일곱 칸을 낱말 규칙과 모델로 나란히 읽는 것(2026-10-09).
    #: 기본은 꺼짐. 켜도 판의 동작은 바뀌지 않는다 — 기록만 붙인다.
    intent_shadow_enabled: bool = False
    #: 계단식 접기 때 모델에게 **정리 한 장**을 쓰게 해서 요청 메시지 앞에 둔다(`transcript.set_fold_sheet` · 2026-10-10).
    #: 재기 전이라 기본은 끔 — 접을 때마다 모델을 한 번 더 부른다. 볼 것: 접은 뒤 이미 읽은 파일을 다시 읽는 걸음이 줄었나.
    fold_summary_enabled: bool = False
    local_computer_enabled: bool = True
    local_file_allowed_roots: str = field(default_factory=_default_local_roots)
    #: **읽기만** 넓게 여는 자리. 쓰기는 위의 `local_file_allowed_roots` 그대로다 (2026-09-20).
    #:
    #: 코워크는 이 PC 를 보고 답하는 자리라 읽을 수 있어야 보고가 된다 — 오늘 코워크 판들이
    #: 저장소·메모 폴더에서 전부 `path_outside_allowed_roots` 로 막혔다. 비면 **사용자 폴더 전체**를
    #: 읽기 범위로 본다. 비밀(`.env`·키·토큰·다른 AI 도구 기록)은 읽기도 따로 막는다.
    local_read_roots: str = ""
    local_file_max_bytes: int = 32 * 1024 * 1024
    # ★ 2026-10-05: 20,000 → 400,000 · **시간 예산**을 따로 둔다. E: 에서 「JARVIS_전략안」 파일이 넓이 우선 22,566번째였다 —
    #   개수 상한 바로 뒤라 다섯 번 찾아 다섯 번 0건이었다. 개수는 PC 마다 뜻이 다르다(이 디스크는 초당 3천 개, SSD 는 수만 개).
    #   사람이 기다릴 수 있는 것은 시간이다 — 상한은 시간으로 걸고, 개수는 메모리를 지키는 안전판으로만 둔다.
    local_file_scan_limit: int = 400000
    local_file_scan_seconds: float = 20.0
    windows_control_enabled: bool = True
    # 한글 오토메이션은 로컬 Windows + 설치된 한글에서만 돈다. COM 호출은
    # 별도 제한시간 프로세스에서 실행해 JobRunner 하나를 영원히 붙들지 않는다.
    hwp_enabled: bool = True
    hwp_security_module_name: str = "FilePathCheckerModuleExample"
    hwp_com_timeout_sec: int = 30
    hwp_preview_ttl_sec: int = 300

    def model_for(self, role: str = "chat") -> str:
        """역할 이름이 잘못돼도 주 대화 모델로 안전하게 돌아간다."""
        roles = self.model_roles or {}
        return str(roles.get(role) or roles.get("chat") or "").strip()

    def timeout_for(self, role: str = "chat") -> float:
        """이 역할의 한 호출에 줄 시간. 코드 판은 훨씬 길다."""
        if role == "code":
            return float(max(self.ollama_timeout_sec, self.ollama_code_timeout_sec))
        return float(self.ollama_timeout_sec)

    def num_ctx_for(self, role: str = "chat") -> int:
        """이 역할이 쓸 컨텍스트. **같은 모델이면 대화와 같은 값**을 쓴다.

        ★ 2026-09-21 실측. 사장님 PC 에서 이렇게 갈려 있었다:

            model_roles  = {"chat": qwen3.6, "code": qwen3.6}
            by_role ctx  = {"chat": 131072,  "code": 102400}

        원인은 OS **사용자 환경변수**에 남은 옛값(`JARVIS_OLLAMA_CODE_NUM_CTX=102400`).
        Qwen 3.8 을 쓰던 시절 3090 실측으로 정한 값인데, 모델을 3.6 으로 바꾼 뒤에도
        남아 있었다. 모델 이름은 설정이 덮었지만 컨텍스트는 아무도 안 덮었다.

        이 저장소가 아는 사고다 — **num_ctx 가 다르면 Ollama 는 러너를 새로 띄우고,
        `OLLAMA_MAX_LOADED_MODELS=1` 이라 옛 러너를 쫓아낸다.** 즉 Cowork 탭과 Code 탭을
        오가는 것만으로 23GB 재적재가 걸렸다. 모델은 같은데.

        바로 위 `model_num_ctx` 주석이 이미 그렇게 적고 있었다 — 「비우면 대화 모델과
        같은 컨텍스트, 다르면 러너를 새로 띄워 축출한다」. **비우지 못한 경우**를
        아무도 안 막고 있었을 뿐이다. 값이 사는 자리는 셋이 아니라 넷이다:
        dataclass 기본값 · 환경변수 로더 · 함수 안 하드 상수 · **OS 환경변수**.
        """
        contexts = self.model_num_ctx or {}
        wanted = int(contexts.get(role) or 0)
        if wanted and role != "chat":
            mine = str((self.model_roles or {}).get(role) or "").strip().lower()
            chat = str((self.model_roles or {}).get("chat") or "").strip().lower()
            bare = lambda tag: tag.removesuffix(":latest")  # noqa: E731
            # 같은 파일을 두 컨텍스트로 부르면 러너가 둘이 된다 — 그 순간 하나가 쫓겨난다.
            if not mine or bare(mine) == bare(chat):
                wanted = 0
        return max(4096, wanted or self.ollama_num_ctx)

    def inference_profile_for(self, role: str = "chat") -> str:
        if role != "code":
            return "default"
        profile = str(self.code_inference_profile or "balanced").strip().lower()
        return profile if profile in {"fast", "balanced", "medium", "deep"} else "balanced"

    @property
    def ollama_model(self) -> str:
        """기존 상태 점검 코드가 읽는 주 대화 모델 호환 별칭."""
        return self.model_for("chat")

    @classmethod
    def from_env(cls) -> "JarvisConfig":
        root = _default_runtime_root()
        data_dir = Path(_env("JARVIS_DATA_DIR", str(root / "data")))
        output_dir = Path(_env("JARVIS_OUTPUT_DIR", str(root / "outputs")))
        legacy_model = _env("JARVIS_OLLAMA_MODEL", "gemma4:26b-a4b-it-qat")
        return cls(
            host=_env("JARVIS_HOST", "127.0.0.1"),
            port=_int("JARVIS_PORT", 8091),
            runtime_root=root,
            data_dir=data_dir,
            output_dir=output_dir,
            documents_dir=Path(
                _env("JARVIS_DOCUMENTS_DIR", str(documents_product_dir(Path.home() / "Documents")))
            ),
            control_token=_env("JARVIS_CONTROL_TOKEN"),
            profile_path=Path(
                _env(
                    "JARVIS_PROFILE_PATH",
                    str(data_dir / "JARVIS_PROFILE.md"),
                )
            ),
            profile_max_chars=_int("JARVIS_PROFILE_MAX_CHARS", 6000),
            ollama_base_url=_env("JARVIS_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_install_dir=Path(_env("JARVIS_OLLAMA_INSTALL_DIR", str(_outside_app_data(
                legacy=data_dir / "ollama", fresh=engine_dir(Path.home()) / "ollama")))),
            store_update_dir=Path(_env("JARVIS_STORE_UPDATE_DIR", str(update_dir(Path.home())))),
            brain_host=_env("JARVIS_BRAIN_HOST", "").strip(),
            api_extra_allowed_cidrs=_env("JARVIS_API_ALLOWED_CIDRS", "").strip(),
            model_roles={
                "chat": _env("JARVIS_OLLAMA_CHAT_MODEL", legacy_model),
                "code": _env(
                    "JARVIS_OLLAMA_CODE_MODEL", ""
                ),
                "vision": _env("JARVIS_OLLAMA_VISION_MODEL", legacy_model),
            },
            model_num_ctx={
                "code": _int("JARVIS_OLLAMA_CODE_NUM_CTX", 0),
            },
            code_preserve_recent_thinking=_int(
                "JARVIS_CODE_PRESERVE_RECENT_THINKING", 0
            ),
            code_inference_profile=_env(
                "JARVIS_CODE_INFERENCE_PROFILE", "balanced"
            ).lower(),
            code_scout_enabled=_bool("JARVIS_CODE_SCOUT_ENABLED", False),
            code_scout_base_url=_env(
                "JARVIS_CODE_SCOUT_BASE_URL", "http://127.0.0.1:11435"
            ).rstrip("/"),
            code_scout_model=_env("JARVIS_CODE_SCOUT_MODEL", "qwen3.5:9b"),
            code_scout_num_ctx=_int("JARVIS_CODE_SCOUT_NUM_CTX", 65536),
            code_scout_timeout_sec=_int("JARVIS_CODE_SCOUT_TIMEOUT_SEC", 60),
            code_scout_max_predict=_int("JARVIS_CODE_SCOUT_MAX_PREDICT", 1200),
            code_scout_keep_alive=_env("JARVIS_CODE_SCOUT_KEEP_ALIVE", "30m"),
            code_scout_gpu_uuid=_env(
                "JARVIS_CODE_SCOUT_GPU_UUID",
                "",
            ),
            code_scout_min_free_vram_mb=_int("JARVIS_CODE_SCOUT_MIN_FREE_VRAM_MB", 8000),
            ollama_timeout_sec=_int("JARVIS_OLLAMA_TIMEOUT_SEC", 180),
            ollama_code_timeout_sec=_int(
                "JARVIS_OLLAMA_CODE_TIMEOUT_SEC", 900
            ),
            ollama_max_predict=_int("JARVIS_OLLAMA_MAX_PREDICT", 8192),
            ollama_thinking_char_budget=_int("JARVIS_OLLAMA_THINKING_CHAR_BUDGET", 8000),
            # `qwen3.6=3000;gemma4=8000` 모양. 비우면 기본표(Qwen 3.6 만 3000).
            ollama_thinking_budget_by_model=_thinking_budgets(
                _env("JARVIS_OLLAMA_THINKING_BUDGET_BY_MODEL", "")
            ),
            ollama_max_tool_steps=_int("JARVIS_OLLAMA_MAX_TOOL_STEPS", 12),
            code_max_tool_steps=_int("JARVIS_CODE_MAX_TOOL_STEPS", 24),
            code_autonomous_max_steps=_int("JARVIS_CODE_AUTONOMOUS_MAX_STEPS", 80),
            ollama_keep_alive=_env("JARVIS_OLLAMA_KEEP_ALIVE", "24h"),
            ollama_stall_timeout_sec=_int("JARVIS_OLLAMA_STALL_TIMEOUT_SEC", 300),
            # ★ 이 기본값이 **실제로 쓰이는 값**이다. 위 dataclass 기본값(131072)은
            #   `load()` 를 안 거치는 경로에서만 쓰인다 — 둘이 갈리면 여기가 이긴다.
            #   2026-08-20 에 위만 고쳤다가 `/health` 가 계속 65536 을 말해서 잡았다.
            #   상한이 사는 자리는 셋이다: dataclass · 이 로더 · 함수 안 하드 상수.
            ollama_num_ctx=_int("JARVIS_OLLAMA_NUM_CTX", 131072),
            ollama_min_num_ctx=_int("JARVIS_OLLAMA_MIN_NUM_CTX", 32768),
            ollama_adopt_resident_context=_bool(
                "JARVIS_OLLAMA_ADOPT_RESIDENT_CONTEXT", True
            ),
            agent_routing_enabled=_bool("JARVIS_AGENT_ROUTING_ENABLED", True),
            agent_thinking_enabled=_bool("JARVIS_AGENT_THINKING_ENABLED", True),
            agent_thinking_policy=_env("JARVIS_AGENT_THINKING_POLICY", "always"),
            agent_fuse_open_and_read=_bool("JARVIS_AGENT_FUSE_OPEN_READ", True),
            agent_stream_enabled=_bool("JARVIS_AGENT_STREAM_ENABLED", True),
            agent_time_warning_sec=_int("JARVIS_AGENT_TIME_WARNING_SEC", 30),
            problem_report_url=_env("JARVIS_PROBLEM_REPORT_URL", "https://api.robometafit.com/sonjari/reports"),
            agent_continue_short_sec=_int("JARVIS_AGENT_CONTINUE_SHORT_SEC", 180),
            agent_continue_long_sec=_int("JARVIS_AGENT_CONTINUE_LONG_SEC", 900),
            agent_checkpoint_ttl_sec=_int("JARVIS_AGENT_CHECKPOINT_TTL_SEC", 1800),
            approval_ttl_sec=_int("JARVIS_APPROVAL_TTL_SEC", 1800),
            approval_auto_reversible=_bool("JARVIS_APPROVAL_AUTO_REVERSIBLE", False),
            approval_bypass_enabled=_bool("JARVIS_APPROVAL_BYPASS_ENABLED", False),
            approval_reminder_lead_sec=_int("JARVIS_APPROVAL_REMINDER_LEAD_SEC", 300),
            # ⚠ dataclass 기본값과 **여기 둘 다** 고쳐야 한다. 한쪽만 고치면 로더가
            #    이겨서 아무 일도 안 일어난다 — 2026-09-01 에 그 자리를 또 밟았다.
            agent_autonomous_max_steps=_int("JARVIS_AGENT_AUTONOMOUS_MAX_STEPS", 48),
            agent_autonomous_lease_sec=_int("JARVIS_AGENT_AUTONOMOUS_LEASE_SEC", 1500),
            code_job_stall_sec=_int("JARVIS_CODE_JOB_STALL_SEC", 1200),
            tool_surface_compact_max_ctx=_int("JARVIS_TOOL_SURFACE_COMPACT_MAX_CTX", 40_000),
            small_window_research_bundle=_bool("JARVIS_SMALL_WINDOW_RESEARCH_BUNDLE", True),
            startup_warmup_enabled=_bool("JARVIS_STARTUP_WARMUP_ENABLED", True),
            front_prime_enabled=_bool("JARVIS_FRONT_PRIME_ENABLED", True),
            plan_push_enabled=_bool("JARVIS_PLAN_PUSH", True),
            scribe_enabled=_bool("JARVIS_SCRIBE_ENABLED", False),
            scribe_folders=_env("JARVIS_SCRIBE_FOLDERS", ""),
            scribe_interval_sec=_int("JARVIS_SCRIBE_INTERVAL_SEC", 900),
            scribe_style_file=_env("JARVIS_SCRIBE_STYLE_FILE", ""),
            ollama_prompt_cache_mib=_int("JARVIS_OLLAMA_PROMPT_CACHE_MIB", -1),
            startup_warmup_retry_sec=_int("JARVIS_STARTUP_WARMUP_RETRY_SEC", 120),
            conversation_session_id=_env("JARVIS_CONVERSATION_SESSION_ID", "office-main"),
            workspace_presence_ttl_sec=_int("JARVIS_WORKSPACE_PRESENCE_TTL_SEC", 75),
            attention_notices_enabled=_bool("JARVIS_ATTENTION_NOTICES_ENABLED", True),
            # ★ dataclass 기본값만 고치면 헛돈다 — 값이 사는 자리가 셋이고
            #   로더가 그중 하나다(사고 Q). 여기 안 적으면 .env 가 안 먹는다.
            scheduler_enabled=_bool("JARVIS_SCHEDULER_ENABLED", True),
            watches_enabled=_bool("JARVIS_WATCHES_ENABLED", True),
            memory_recent_messages=_int("JARVIS_MEMORY_RECENT_MESSAGES", 12),
            memory_max_chars=_int("JARVIS_MEMORY_MAX_CHARS", 12000),
            memory_compact_batch=_int("JARVIS_MEMORY_COMPACT_BATCH", 6),
            memory_retrieval_enabled=_bool("JARVIS_MEMORY_RETRIEVAL_ENABLED", True),
            fact_learning_enabled=_bool("JARVIS_FACT_LEARNING_ENABLED", True),
            memory_retrieval_limit=_int("JARVIS_MEMORY_RETRIEVAL_LIMIT", 4),
            memory_retrieval_max_chars=_int("JARVIS_MEMORY_RETRIEVAL_MAX_CHARS", 4200),
            visual_memory_max_age_sec=_float("JARVIS_VISUAL_MEMORY_MAX_AGE_SEC", 3600.0),
            self_check_min_speed_ratio=_float("JARVIS_SELF_CHECK_MIN_SPEED_RATIO", 0.4),
            self_check_min_tokens_per_sec=_float("JARVIS_SELF_CHECK_MIN_TPS", 5.0),
            self_check_on_boot=_bool("JARVIS_SELF_CHECK_ON_BOOT", True),
            self_check_boot_delay_sec=_float("JARVIS_SELF_CHECK_BOOT_DELAY_SEC", 45.0),
            self_check_expected_gpus=_int("JARVIS_SELF_CHECK_EXPECTED_GPUS", 0),
            discord_bridge_enabled=_bool("JARVIS_DISCORD_BRIDGE_ENABLED", True),
            scheduled_mail_recipients=_env("JARVIS_SCHEDULED_MAIL_RECIPIENTS", ""),
            supertonic_base_url=_env("JARVIS_SUPERTONIC_BASE_URL", "http://127.0.0.1:7788"),
            supertonic_voice=_env("JARVIS_SUPERTONIC_VOICE", "F1"),
            supertonic_language=_env("JARVIS_SUPERTONIC_LANGUAGE", "ko"),
            supertonic_task_name=_env(
                "JARVIS_SUPERTONIC_TASK_NAME", "Alture-Jarvis-Supertonic"
            ),
            tts_enabled=_bool("JARVIS_TTS_ENABLED", True),
            tts_steps=_int("JARVIS_TTS_STEPS", 4),
            tts_speed=_float("JARVIS_TTS_SPEED", 1.08),
            tts_voice_max_chars=_int("JARVIS_TTS_VOICE_MAX_CHARS", 70),
            tts_summary_max_chars=_int("JARVIS_TTS_SUMMARY_MAX_CHARS", 72),
            tts_warmup_enabled=_bool("JARVIS_TTS_WARMUP_ENABLED", True),
            camera_enabled=_bool("JARVIS_CAMERA_ENABLED", False),
            camera_name=_env("JARVIS_CAMERA_NAME", ""),
            camera_index=_int("JARVIS_CAMERA_INDEX", 0),
            camera_stream_url=_env("JARVIS_CAMERA_STREAM_URL", ""),
            camera_screen_capture_enabled=_bool("JARVIS_CAMERA_SCREEN_CAPTURE", False),
            face_recognition_enabled=_bool("JARVIS_FACE_RECOGNITION_ENABLED", False),
            face_model_dir=Path(_env("JARVIS_FACE_MODEL_DIR", str(_outside_app_data(
                legacy=data_dir / "faces" / "models", fresh=engine_dir(Path.home()) / "faces")))),
            face_registry_path=Path(
                _env("JARVIS_FACE_REGISTRY_PATH", str(data_dir / "faces" / "registry.json"))
            ),
            sweep_left_steps=_int("JARVIS_SWEEP_LEFT_STEPS", 1),
            sweep_right_steps=_int("JARVIS_SWEEP_RIGHT_STEPS", 4),
            sweep_step_seconds=_float("JARVIS_SWEEP_STEP_SECONDS", 2.5),
            camera_stream_reconnect_sec=_float("JARVIS_CAMERA_STREAM_RECONNECT_SEC", 3.0),
            camera_stream_read_timeout_sec=_float("JARVIS_CAMERA_STREAM_READ_TIMEOUT_SEC", 12.0),
            camera_stream_ffmpeg_options=_env("JARVIS_CAMERA_STREAM_FFMPEG_OPTIONS", ""),
            camera_control_enabled=_bool("JARVIS_CAMERA_CONTROL_ENABLED", False),
            camera_control_adb_serial=_env("JARVIS_CAMERA_CONTROL_ADB_SERIAL", ""),
            camera_control_package=_env("JARVIS_CAMERA_CONTROL_PACKAGE", "mimo.sz"),
            camera_autorecover_enabled=_bool("JARVIS_CAMERA_AUTORECOVER_ENABLED", True),
            camera_autorecover_after_sec=_float("JARVIS_CAMERA_AUTORECOVER_AFTER_SEC", 90.0),
            camera_autorecover_cooldown_sec=_float("JARVIS_CAMERA_AUTORECOVER_COOLDOWN_SEC", 300.0),
            camera_width=_int("JARVIS_CAMERA_WIDTH", 1920),
            camera_height=_int("JARVIS_CAMERA_HEIGHT", 1080),
            camera_fps=_int("JARVIS_CAMERA_FPS", 30),
            camera_backend=_env("JARVIS_CAMERA_BACKEND", "msmf"),
            vision_enabled=_bool("JARVIS_VISION_ENABLED", True),
            vision_model=_env("JARVIS_VISION_MODEL", "yolo26n.pt"),
            vision_device=_env("JARVIS_VISION_DEVICE", "cuda:0"),
            vision_fps=_float("JARVIS_VISION_FPS", 1.0),
            vision_imgsz=_int("JARVIS_VISION_IMGSZ", 416),
            person_enter_hits=_int("JARVIS_PERSON_ENTER_HITS", 2),
            person_enter_window=_int("JARVIS_PERSON_ENTER_WINDOW", 3),
            person_exit_after_sec=_float("JARVIS_PERSON_EXIT_AFTER_SEC", 2.0),
            voice_enabled=_bool("JARVIS_VOICE_ENABLED", True),
            microphone_name=_env("JARVIS_MICROPHONE_NAME", ""),
            sample_rate=_int("JARVIS_SAMPLE_RATE", 16000),
            stt_model=_env("JARVIS_STT_MODEL", "large-v3-turbo"),
            stt_device=_env("JARVIS_STT_DEVICE", "cuda"),
            stt_device_index=_int("JARVIS_STT_DEVICE_INDEX", 0),
            stt_compute_type=_env("JARVIS_STT_COMPUTE_TYPE", "int8_float16"),
            stt_cpu_model=_env("JARVIS_STT_CPU_MODEL", "small"),
            stt_language=_env("JARVIS_STT_LANGUAGE", "ko"),
            hotkey_enabled=_bool("JARVIS_HOTKEY_ENABLED", True),
            hotkey=_env("JARVIS_HOTKEY", "f9"),
            hotkey_suppress=_bool("JARVIS_HOTKEY_SUPPRESS", True),
            hotkey_trigger_on_release=_bool("JARVIS_HOTKEY_TRIGGER_ON_RELEASE", True),
            media_pause_enabled=_bool("JARVIS_MEDIA_PAUSE_ENABLED", True),
            media_excluded_apps=_env(
                "JARVIS_MEDIA_EXCLUDED_APPS", "teams,ms-teams,zoom,webex,discord"
            ),
            media_resume_delay_sec=_float("JARVIS_MEDIA_RESUME_DELAY_SEC", 0.3),
            plopfit_enabled=_bool("JARVIS_PLOPFIT_ENABLED", False),
            plopfit_functions_dir=Path(
                _env(
                    "JARVIS_PLOPFIT_FUNCTIONS_DIR",
                    str(_outside_app_data(legacy=root / "integrations" / "plopfit" / "functions",
                                          fresh=product_dir(Path.home()) / "plopfit" / "functions")),
                )
            ),
            plopfit_lib_dir=Path(
                _env(
                    "JARVIS_PLOPFIT_LIB_DIR",
                    str(_outside_app_data(legacy=root / "integrations" / "plopfit" / "lib",
                                          fresh=product_dir(Path.home()) / "plopfit" / "lib")),
                )
            ),
            pc_mcp_base_url=_env("JARVIS_PC_MCP_BASE_URL", "http://127.0.0.1:8088"),
            pc_mcp_token=_env("JARVIS_PC_MCP_TOKEN"),
            enable_system_actions=_bool("JARVIS_ENABLE_SYSTEM_ACTIONS", False),
            inhouse_data_enabled=_bool("JARVIS_INHOUSE_DATA_ENABLED", False),
            inhouse_api_base=_env("JARVIS_INHOUSE_API_BASE", ""),
            inhouse_api_key=_env("JARVIS_INHOUSE_API_KEY"),
            inhouse_api_header=_env("JARVIS_INHOUSE_API_HEADER", "X-API-Key"),
            inhouse_tenant_id=_env("JARVIS_INHOUSE_TENANT_ID", ""),
            inhouse_startup_timeout_sec=_float("JARVIS_INHOUSE_STARTUP_TIMEOUT_SEC", 6.0),
            inhouse_call_timeout_sec=_float("JARVIS_INHOUSE_CALL_TIMEOUT_SEC", 45.0),
            browser_enabled=_bool("JARVIS_BROWSER_ENABLED", True),
            browser_headless=_bool("JARVIS_BROWSER_HEADLESS", False),
            yield_to_user_enabled=_bool("JARVIS_YIELD_TO_USER", True),
            yield_to_user_active_sec=float(_env("JARVIS_YIELD_TO_USER_ACTIVE_SEC", "10") or 10),
            assume_user_active=_bool("JARVIS_ASSUME_USER_ACTIVE", False),
            browser_home_url=_env("JARVIS_BROWSER_HOME_URL", "https://www.google.com"),
            browser_read_only=_bool("JARVIS_BROWSER_READ_ONLY", True),
            browser_sandbox=_bool("JARVIS_BROWSER_SANDBOX", True),
            browser_visual_overlay=_bool("JARVIS_BROWSER_VISUAL_OVERLAY", True),
            browser_attach_mode=_env("JARVIS_BROWSER_ATTACH", "auto").strip().lower() or "auto",
            browser_cdp_port=_int("JARVIS_BROWSER_CDP_PORT", 9222),
            browser_chrome_path=_env("JARVIS_BROWSER_CHROME_PATH"),
            page_eye_enabled=_bool("JARVIS_PAGE_EYE_ENABLED", True),
            browser_attach_launch_timeout_sec=_int(
                "JARVIS_BROWSER_ATTACH_LAUNCH_TIMEOUT_SEC", 25
            ),
            browser_snapshot_group_cap=_int("JARVIS_BROWSER_SNAPSHOT_GROUP_CAP", 15),
            browser_profile_dir=Path(
                _env("JARVIS_BROWSER_PROFILE_DIR", str(_outside_app_data(
                    legacy=root / "data" / "browser-profile",
                    fresh=product_dir(Path.home()) / "browser-profile",
                )))
            ),
            browser_download_dir=Path(
                _env("JARVIS_BROWSER_DOWNLOAD_DIR", str(downloads_dir(Path.home())))
            ),
            browser_evidence_dir=Path(
                _env("JARVIS_BROWSER_EVIDENCE_DIR", str(root / "outputs" / "browser-evidence"))
            ),
            site_recipe_dir=Path(
                _env("JARVIS_SITE_RECIPE_DIR", str(Path(__file__).resolve().parents[2] / "recipes"))
            ),
            # ↑ dataclass 기본값과 **짝이다.** 위를 고치면 여기도 고친다.
            unity_editor_roots=_env("JARVIS_UNITY_EDITOR_ROOTS", r"C:\Program Files\Unity\Hub\Editor"),
            unity_run_timeout_sec=_int("JARVIS_UNITY_RUN_TIMEOUT_SEC", 900),
            skills_dir=Path(
                _env("JARVIS_SKILLS_DIR", str(Path(__file__).resolve().parents[2] / "skills"))
            ),
            # ↑ 와 짝 — dataclass 기본값과 같은 자리.
            packs_dir=Path(
                _env("JARVIS_PACKS_DIR", str(Path(__file__).resolve().parents[2] / "packs"))
            ),
            # ↑ dataclass 의 `user_packs_dir` 와 짝. 비어 있으면 문서 폴더를 따라간다.
            user_packs_dir=(Path(_env("JARVIS_USER_PACKS_DIR")) if _env("JARVIS_USER_PACKS_DIR") else None),
            jarvis_role=(_env("JARVIS_ROLE", "primary").strip().lower() or "primary"),
            user_label=_env("JARVIS_USER_LABEL", "").strip(),
            skills_enabled=_bool("JARVIS_SKILLS_ENABLED", True),
            takeover_enabled=_bool("JARVIS_TAKEOVER_ENABLED", True),
            takeover_branch_enabled=_bool("JARVIS_TAKEOVER_BRANCH_ENABLED", True),
            memory_backup_dir=(
                _default_backup_root() if _bool("JARVIS_MEMORY_BACKUP_ENABLED", True) else None
            ),
            skills_route_enabled=_bool("JARVIS_SKILLS_ROUTE_ENABLED", False),
            skills_domains=tuple(
                part.strip() for part in _env("JARVIS_SKILLS_DOMAINS").split(",") if part.strip()
            ),
            skills_guess_enabled=_bool("JARVIS_SKILLS_GUESS_ENABLED", True),
            skills_thinking_card_enabled=_bool("JARVIS_SKILLS_THINKING_CARD", True),
            skills_thinking_card_chars=_int("JARVIS_SKILLS_THINKING_CARD_CHARS", 60),
            skills_body_max_chars=_int("JARVIS_SKILLS_BODY_MAX_CHARS", 12000),
            # ↑↓ dataclass 기본값과 **짝이다.** 한쪽만 고치면 조용히 헛돈다.
            sandbox_enabled=_bool("JARVIS_SANDBOX_ENABLED", False),
            sandbox_distro=_env("JARVIS_SANDBOX_DISTRO", "Ubuntu"),
            sandbox_timeout_sec=_int("JARVIS_SANDBOX_TIMEOUT_SEC", 60),
            sandbox_output_max_chars=_int("JARVIS_SANDBOX_OUTPUT_MAX_CHARS", 8000),
            sandbox_fetch_max_bytes=_int("JARVIS_SANDBOX_FETCH_MAX_BYTES", 8_000_000),
            sandbox_output_dir=Path(
                _env("JARVIS_SANDBOX_OUTPUT_DIR", str(_outside_app_data(
                    legacy=root / "outputs" / "sandbox",
                    fresh=product_dir(Path.home()) / "sandbox",
                )))
            ),
            claude_code_enabled=_bool("JARVIS_CLAUDE_CODE_ENABLED", False),
            claude_code_locked=_bool("JARVIS_CLAUDE_CODE_LOCKED", False),
            api_escalation_enabled=_bool("JARVIS_API_ESCALATION_ENABLED", False),
            api_escalation_model=os.getenv("JARVIS_API_ESCALATION_MODEL", "claude-opus-5-5").strip() or "claude-opus-5-5",
            api_escalation_monthly_usd=_int("JARVIS_API_ESCALATION_MONTHLY_USD", 3),
            claude_code_command=_env("JARVIS_CLAUDE_CODE_COMMAND", "claude"),
            claude_code_lease_sec=_int("JARVIS_CLAUDE_CODE_LEASE_SEC", 90),
            claude_code_result_max_chars=_int(
                "JARVIS_CLAUDE_CODE_RESULT_MAX_CHARS", 16_000
            ),
            browser_upload_allowed_roots=tuple(
                part.strip()
                for part in _env(
                    "JARVIS_BROWSER_UPLOAD_ROOTS",
                    ";".join(
                        str(Path.home() / name) for name in ("Desktop", "Documents", "Downloads")
                    ),
                ).split(";")
                if part.strip()
            ),
            browser_upload_max_bytes=_int("JARVIS_BROWSER_UPLOAD_MAX_BYTES", 32 * 1024 * 1024),
            browser_action_timeout_sec=_int("JARVIS_BROWSER_ACTION_TIMEOUT_SEC", 8),
            browser_navigation_timeout_sec=_int("JARVIS_BROWSER_NAVIGATION_TIMEOUT_SEC", 30),
            browser_max_tabs=_int("JARVIS_BROWSER_MAX_TABS", 6),  # ↑ dataclass 기본값과 짝
            browser_allow_foreground=_bool("JARVIS_BROWSER_ALLOW_FOREGROUND", False),  # ↑ 짝
            browser_sink_windows=_bool("JARVIS_BROWSER_SINK_WINDOWS", True),  # ↑ 짝
            browser_birth_guard=_bool("JARVIS_BROWSER_BIRTH_GUARD", True),
            browser_birth_offscreen=_bool("JARVIS_BROWSER_BIRTH_OFFSCREEN", True),
            browser_no_startup_window=_bool("JARVIS_BROWSER_NO_STARTUP_WINDOW", True),
            browser_park_offscreen=_bool("JARVIS_BROWSER_PARK_OFFSCREEN", True),
            browser_task_timeout_sec=_int("JARVIS_BROWSER_TASK_TIMEOUT_SEC", 180),
            browser_reconnect_after_navigations=_int(
                "JARVIS_BROWSER_RECONNECT_AFTER_NAVIGATIONS", 50
            ),
            browser_reconnect_after_objects=_int("JARVIS_BROWSER_RECONNECT_AFTER_OBJECTS", 4000),
            browser_stuck_recover_after_sec=_int("JARVIS_BROWSER_STUCK_RECOVER_AFTER_SEC", 60),
            # ⚠ 위 dataclass 기본값(200)과 **여기 둘 다** 고쳐야 한다. `load()` 는
            # 언제나 이 값을 넣으므로 dataclass 쪽만 고치면 아무 일도 안 일어난다
            # (2026-08-13 에 그렇게 한 번 헛돌았다). 상한이 여러 군데면 낮은 쪽만 일한다.
            browser_max_elements=_int("JARVIS_BROWSER_MAX_ELEMENTS", 200),
            browser_ready_timeout_ms=_int("JARVIS_BROWSER_READY_TIMEOUT_MS", 6000),
            browser_search_block_cooldown_sec=_int(
                "JARVIS_BROWSER_SEARCH_BLOCK_COOLDOWN_SEC", 600
            ),
            google_enabled=_bool("JARVIS_GOOGLE_ENABLED", True),
            google_project_id=_env("JARVIS_GOOGLE_PROJECT_ID", ""),
            google_oauth_client_id=_env("JARVIS_GOOGLE_OAUTH_CLIENT_ID", ""),
            google_oauth_client_secret=_env("JARVIS_GOOGLE_OAUTH_CLIENT_SECRET", ""),
            google_oauth_bundle_path=Path(
                _env(
                    "JARVIS_GOOGLE_OAUTH_BUNDLE_PATH",
                    str(root / "resources" / "google_oauth_client.json"),
                )
            ),
            google_client_secret_path=Path(
                _env(
                    "JARVIS_GOOGLE_CLIENT_SECRET_PATH",
                    str(root / "data" / "google" / "client_secret.json"),
                )
            ),
            google_token_path=Path(
                _env(
                    "JARVIS_GOOGLE_TOKEN_PATH",
                    str(root / "data" / "google" / "token.dpapi"),
                )
            ),
            google_oauth_timeout_sec=_int("JARVIS_GOOGLE_OAUTH_TIMEOUT_SEC", 900),
            google_write_enabled=_bool("JARVIS_GOOGLE_WRITE_ENABLED", False),
            google_restricted_scopes_enabled=_bool("JARVIS_GOOGLE_RESTRICTED_SCOPES", False),
            gmail_attachment_max_bytes=_int("JARVIS_GMAIL_ATTACHMENT_MAX_BYTES", 20 * 1024 * 1024),
            drive_upload_max_bytes=_int("JARVIS_DRIVE_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
            gmail_attachment_max_count=_int("JARVIS_GMAIL_ATTACHMENT_MAX_COUNT", 10),
            calendar_default_timezone=_env("JARVIS_CALENDAR_DEFAULT_TIMEZONE", "Asia/Seoul"),
            calendar_past_grace_minutes=_int("JARVIS_CALENDAR_PAST_GRACE_MINUTES", 5),
            external_action_ttl_sec=_int("JARVIS_EXTERNAL_ACTION_TTL_SEC", 600),
            external_action_dedupe_window_sec=_int("JARVIS_EXTERNAL_ACTION_DEDUPE_WINDOW_SEC", 600),
            naver_blog_enabled=_bool("JARVIS_NAVER_BLOG_ENABLED", False),
            private_update_enabled=_bool("JARVIS_PRIVATE_UPDATE_ENABLED", False),
            naver_blog_allowed_hosts=_env(
                "JARVIS_NAVER_BLOG_ALLOWED_HOSTS",
                "blog.naver.com;admin.blog.naver.com;nid.naver.com",
            ),
            naver_blog_image_max_bytes=_int("JARVIS_NAVER_BLOG_IMAGE_MAX_BYTES", 10 * 1024 * 1024),
            naver_blog_image_max_count=_int("JARVIS_NAVER_BLOG_IMAGE_MAX_COUNT", 20),
            naver_blog_plan_ttl_sec=_int("JARVIS_NAVER_BLOG_PLAN_TTL_SEC", 3600),
            naver_blog_save_verify_timeout_sec=_int("JARVIS_NAVER_BLOG_SAVE_VERIFY_TIMEOUT_SEC", 8),
            naver_blog_close_after_save=_bool("JARVIS_NAVER_BLOG_CLOSE_AFTER_SAVE", True),
            naver_blog_editor_ready_timeout_ms=_int("JARVIS_NAVER_BLOG_EDITOR_READY_TIMEOUT_MS", 15000),
            shell_autorun_enabled=_bool("JARVIS_SHELL_AUTORUN_ENABLED", False),
            intent_shadow_enabled=_bool("JARVIS_INTENT_SHADOW_ENABLED", False),
            fold_summary_enabled=_bool("JARVIS_FOLD_SUMMARY_ENABLED", False),
            local_computer_enabled=_bool("JARVIS_LOCAL_COMPUTER_ENABLED", True),
            local_file_allowed_roots=_env(
                "JARVIS_LOCAL_FILE_ALLOWED_ROOTS", _default_local_roots()
            ),
            local_read_roots=_env("JARVIS_LOCAL_READ_ROOTS", ""),
            local_file_max_bytes=_int("JARVIS_LOCAL_FILE_MAX_BYTES", 32 * 1024 * 1024),
            local_file_scan_limit=_int("JARVIS_LOCAL_FILE_SCAN_LIMIT", 400000),
            local_file_scan_seconds=_float("JARVIS_LOCAL_FILE_SCAN_SECONDS", 20.0),
            windows_control_enabled=_bool("JARVIS_WINDOWS_CONTROL_ENABLED", True),
            hwp_enabled=_bool("JARVIS_HWP_ENABLED", True),
            hwp_security_module_name=_env(
                "JARVIS_HWP_SECURITY_MODULE_NAME", "FilePathCheckerModuleExample"
            ),
            hwp_com_timeout_sec=_int("JARVIS_HWP_COM_TIMEOUT_SEC", 30),
            hwp_preview_ttl_sec=_int("JARVIS_HWP_PREVIEW_TTL_SEC", 300),
        )

    def __post_init__(self) -> None:
        """역할이 「위성」이면 **여기서 못 하는 것들을 끈다.**

        위성은 본체에서 젬마와 음성 합성만 빌려 온다. 나머지 손과 눈(파일·창·
        브라우저)은 자기 PC 것을 쓴다 — 그래서 다른 사용자 자비스는 다른 사용자 파일을 본다.

        ★ 스위치를 사람이 하나씩 끄게 두면 하나씩 빠진다. 그리고 빠진 쪽은 조용히
          틀린다:
            · STT   — faster-whisper 는 GPU 가 필요하고 **HTTP 로 못 빌린다.**
                      노트북에 GPU 가 없으면 올리려다 실패한다
            · 예약   — 두 대에서 같은 예약이 돌면 메일이 두 번 간다
            · 상자   — WSL 이 없다(있어도 본체 것과 다른 상자다)
            · 카메라 — Pocket 3 는 본체에 물려 있다
        """
        # 첫 실행 화면에서 고른 모델을 얹는다. 위성은 본체 모델을 빌리므로 얹지 않는다.
        if str(self.jarvis_role).lower() != "satellite":
            try:
                from .model_setup import apply_selection_to_config

                self.model_source = apply_selection_to_config(self)
            except Exception:  # noqa: BLE001 — 선택 파일이 깨졌다고 자비스가 안 뜨면 안 된다
                self.model_source = "env"
        # ★ 화면에서 바꾼 값은 **맨 마지막**에 얹는다(W3). 환경변수·.env·task_entry setdefault·첫 실행 선택
        #   무엇보다 뒤라서 다음 기동에도 이긴다 — 「.env 가 항상 졌다」의 반대편 사고를 막는 자리다.
        try:
            from .settings import apply_user_settings

            self.settings_applied = tuple(apply_user_settings(self))
        except Exception:  # noqa: BLE001 — 설정 파일이 깨졌다고 자비스가 안 뜨면 안 된다
            self.settings_applied = ()
        if str(self.jarvis_role).lower() != "satellite":
            # ★ 2026-10-10: 코드 역할이 대화 모델을 따라가는 PC 면 **켤 때마다 여기서 맞춘다.** 사본을 따로 적어 두면
            #   원본과 어긋난다 — 환경변수에 남은 옛 코드 모델도 여기서 진다(`model_setup.follow_chat_with_code`).
            try:
                from .model_setup import follow_chat_with_code

                follow_chat_with_code(self)
            except Exception:  # noqa: BLE001 — 선택 파일이 깨졌다고 자비스가 안 뜨면 안 된다
                pass
            return
        # ★ 카메라와 상자는 **물건이 여기 없다.**
        self.camera_enabled = False      # A satellite has no camera unless configured.
        self.sandbox_enabled = False     # WSL 이 없다(있어도 본체 것과 다른 상자다)
        # 예약이 두 대에서 돌면 메일이 두 번 간다. 받는 사람은 그게 고장인지
        # 정상인지 모르고, 그러면 다음부터 안 읽는다.
        self.scheduled_mail_recipients = ()
        # ── 음성 ──────────────────────────────────────────────────────────
        #
        # ★ 처음엔 위성에서 음성을 통째로 껐다. **틀렸다.**
        #
        #   STT 는 본체에서 못 빌리는 게 맞다(faster-whisper 는 HTTP 서비스가
        #   아니라 프로세스 안에서 돈다). 그런데 그건 "빌릴 수 없다"이지
        #   "할 수 없다"가 아니다 — 노트북에 GPU 가 있으면 **자기 것으로 하면 된다.**
        #
        #   `large-v3-turbo` 를 `int8_float16` 으로 올리면 1.5~2GB 다. 3050 이면
        #   들어가고, 게다가 그 GPU 는 STT 전용이 된다(젬마는 본체에 있으니까).
        #
        #   그래서 음성 입력은 **끄지 않는다.** GPU 가 없으면 `_resolve_device` 가
        #   알아서 CPU 로 내리고 **이유를 `/health` 에 남긴다** — 조용히 안 되는
        #   것과 이유를 알고 느린 것은 다르다.
        #
        # 다만 장치 번호는 맞춰 준다. 본체 기본값은 1번(3090)인데 노트북은 대개
        # GPU 가 한 장이라 0번이다. 폴백이 잡아 주긴 하지만 **처음부터 맞는 값을
        # 주는 편이 낫다** — 폴백은 안전망이지 설정이 아니다.
        if self.stt_device_index != 0:
            self.stt_device_index = 0

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.browser_download_dir.mkdir(parents=True, exist_ok=True)
        self.browser_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.google_client_secret_path.parent.mkdir(parents=True, exist_ok=True)
        self.google_token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path = self.data_dir / "control.token"
        if not self.control_token:
            if token_path.exists():
                self.control_token = token_path.read_text(encoding="utf-8-sig").strip()
            else:
                self.control_token = secrets.token_urlsafe(32)
        # 파일은 지금 이 프로세스가 실제로 받아 주는 토큰이어야 한다. Tauri 껍데기는
        # `.env` 를 읽지 않고 이 파일만 읽는데(ui/src-tauri/src/lib.rs), 그동안 `.env`
        # 에 토큰이 있으면 여기서 파일을 아예 건드리지 않았다. setup_mcp.py 가 `.env`
        # 에만 새 토큰을 써 넣은 뒤로 둘이 갈라져서, 워크스페이스의 모든 쓰기가
        # 401 invalid_control_token 으로 조용히 막혔다(2026-08-08, 첨부 업로드로 발견).
        # BOM 없는 utf-8 로 다시 쓰는 것은 예전 PowerShell 이 만든 파일 정규화도 겸한다.
        token_path.write_text(self.control_token, encoding="utf-8")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    @property
    def skillpacks_dir(self) -> Path:
        """사람이 스킬팩 폴더를 넣는 자리 — 문서 폴더 안이다.

        앱 자료 폴더에 두면 안 된다: 스토어 판에서 그 자리는 「앱 전용 칸」으로 가서, 탐색기로 넣은 것을 우리가 못 본다
        (2026-09-18 노트북 실측). 프로그램 폴더는 잠겨 있고 판마다 새것으로 바뀐다.
        """
        return Path(self.user_packs_dir) if self.user_packs_dir else self.documents_dir / "skillpacks"

    @property
    def user_recipes_dir(self) -> Path:
        """사람이 승인한 **배운 레시피** 자리 — 문서 폴더 안이다(스킬팩 폴더와 같은 까닭 · 확장 설계 §3-5).

        손자리에 들어 있는 레시피(`site_recipe_dir` — 프로그램 폴더라 스토어 판에서 잠긴다)와 섞지 않는다.
        """
        return self.documents_dir / "recipes"

    def public_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw.pop("control_token", None)
        raw.pop("pc_mcp_token", None)
        raw.pop("google_oauth_client_secret", None)
        raw.pop("google_client_secret_path", None)
        raw.pop("google_oauth_bundle_path", None)
        raw.pop("google_token_path", None)
        # ★ **밖으로 나가는 것은 쓰이는 값이다** (2026-09-21 사장님 지적).
        #
        #   `num_ctx_for()` 를 고쳐 실효값은 131072 가 됐는데 머리에는 계속 100K 가 떴다.
        #   `asdict` 가 **덮어쓰기 원본**(`{"code": 102400}`)을 그대로 내보냈고 화면이
        #   그걸 읽었기 때문이다. 값이 사는 자리가 또 갈렸다 — 이번엔 계산한 값과 원본.
        #
        #   역할을 **전부** 채워서 내보낸다. 빠진 역할이 있으면 화면이 제 나름의
        #   기본값을 쓰고, 그게 또 하나의 「함수 안 하드 상수」가 된다.
        raw["model_num_ctx"] = {
            role: self.num_ctx_for(role) for role in (self.model_roles or {"chat": ""})
        }
        return {key: str(value) if isinstance(value, Path) else value for key, value in raw.items()}
