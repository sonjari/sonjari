"""자비스가 지금 몇 단계인지 **세어서** 답한다.

왜 만들었나. 2026-08-10 에 같은 질문("자비스 어디까지 왔나")에 세션마다 다른 답이
나왔다. 한쪽은 "L4 거의 다 왔다"(장치를 다 만들었다는 뜻), 다른 쪽은 "L3 중반"
(실적 기준). 둘 다 틀리지 않았는데 **재는 자가 없어서** 말이 갈렸다.

만든 것과 도는 것을 구별하지 않는 것 — 그게 이 저장소가 하루 종일 잡던 병이다.
그 병이 정작 자비스 수준을 말할 때 재발하고 있었다. 그래서 눈금을 박는다.

## 눈금

    L2 조사   읽기 도구 성공률          ≥ 95%
    L3 실행   쓰기 도구 성공률          ≥ 60%
    L4 위임   사람 손 안 타고 끝난 비율  ≥ 70%

세 값 모두 `jarvis.db` 에 이미 있는 것으로 센다. 새로 기록할 것은 없다.

**L4 를 "사람 손 안 탐"으로 정하는 이유.** 자율형 에이전트의 값은 똑똑함이 아니라
**맡겨 놓고 잊어도 되는가**에서 나온다. 승인 카드를 누르거나, "3분 더" 를 고르거나,
로그인을 대신 해 줘야 했다면 그 잡은 위임이 아니다 — 사람이 옆에 붙어 있어야 했다.

## 안 세는 것

- 답이 **좋았는가**는 안 센다. 셀 수 없다. 성공률이 높아도 엉뚱한 답일 수 있다.
  이 자는 "굴러갔는가"만 잰다. 그 이상을 주장하지 않는다.
- 표본이 적으면 비율을 내지 않고 **표본 수를 그대로 보여준다.** 2 건 중 2 건 성공을
  100% 라고 적는 순간 그 표가 거짓말을 시작한다.

사용:
    python scripts/measure_autonomy.py
    python scripts/measure_autonomy.py --days 7
    python scripts/measure_autonomy.py --db "C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

DEFAULT_DB = Path("C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db")

# 비율을 말해도 되는 최소 표본. 이보다 적으면 숫자 대신 "표본 부족"이라고 적는다.
MIN_SAMPLE = 10

# 목표선. 근거를 적어 둔다 — 근거 없는 기준선은 다음 사람이 마음대로 내린다.
TARGETS = {
    "L2": 95,  # 2026-08-10 실측이 이미 98.6% 라, 이 밑으로 떨어지면 회귀다
    "L3": 60,  # 3 번 중 2 번은 사람 손 안 타야 "된다"고 말할 수 있다
    "L4": 70,  # 열 번 맡겨 일곱 번은 끝나야 맡길 마음이 든다
}

# ── 도구 분류 ────────────────────────────────────────────────────────────────
#
# 읽기 집합은 에이전트가 쓰는 것을 **그대로 가져온다**(sys.path 에 src 를 넣는다).
# 목록을 두 벌 두면 갈라지고, 갈라진 쪽은 조용히 틀린다.
#
# 쓰기 집합은 코드에서 유도할 방법이 마땅치 않아 여기 적는다. 대신 **분류 못 한
# 도구를 끝에 전부 보여준다** — 새 도구가 생겼는데 이 목록이 낡으면 그 자리에서
# 드러난다. 조용히 빠지는 것이 제일 나쁘다.
WRITE_TOOLS = frozenset(
    {
        "naver_blog_fill_editor",
        "naver_blog_save_draft",
        "naver_blog_publish",
        "google_gmail_send",
        "google_calendar_create",
        # 사용자님 드라이브에 파일이 실제로 생긴다.
        "google_drive_write",
        # 열린 유니티 에디터의 씬을 바꾼다(2026-09-27) — 승인 카드를 거치고 에디터 Undo 에 남는다. 되돌리기도 쓰기다.
        "unity_editor_change",
        "unity_editor_undo",
        "browser_fill",
        "browser_click",
        "browser_press",
        # 좌표로 누르고 치는 것(2026-09-17 섀도 DOM·캔버스 화면용) — browser_click·browser_fill 과 같은 계열이다.
        "browser_click_at",
        "browser_type_at",
        # 칸에 치고 뜨는 목록에서 고른다 — `browser_fill` 과 같은 계열이다.
        # ★ 2026-08-11 실측에서 **71건**이 어디에도 안 세어지고 있었다. 그날 만든
        # 도구인데 목록이 안 따라와서, 그 주 쓰기 실적의 큰 조각이 통째로 빠졌다.
        "browser_pick_suggestion",
        # 팝업의 부정 버튼을 실제로 누른다.
        "browser_dismiss_dialog",
        "windows_click",
        "windows_type",
        # 프로그램을 실제로 띄운다(둘 다 L2, 화면 승인 대상).
        "windows_open_path",
        "windows_execute_preview",
        # 초안을 확정해 **앞으로 실제로 쓰이게** 한다.
        "site_promote_draft",
        "local_open_path",
        "undo_action",
        # ── 2026-08-14 추가. 또 새고 있었다(이번엔 12개). ──────────────────────
        #
        # 눈금이 스스로 "분류 안 된 도구"로 띄워 줘서 잡혔다 — 그 줄을 짧게 유지한
        # 보람이 있었다(pick_suggestion 71건이 묻혔던 그 자리다).
        #
        # 비전으로 찾아 **실제로 누른다.** browser_click 과 같은 계열이다.
        "ui_click_target",
        # 짐벌을 **물리적으로 움직인다.** 관찰(camera_look·camera_status)은 NEUTRAL 에
        # 두고 **구동**만 여기 둔다 — 보는 것과 돌리는 것은 다른 일이다.
        "camera_recenter",
        "camera_gimbal_mode",
        "camera_start_live",
        # 얼굴을 등록해 **다음 판부터 쓰이게** 한다(site_promote_draft 와 같은 계열).
        "camera_register_face",
        # ── 2026-08-20 추가. 세 번째로 샜다(이번엔 14건). ────────────────────
        #
        # 또 눈금이 스스로 띄워 줘서 잡혔다. 셋 다 **화면을 실제로 바꾼다**:
        #   browser_click_confirmed  되돌릴 수 없는 누르기(L2, 승인 대상)
        #   browser_fill_form        여러 칸을 한 번에 채운다 — browser_fill 계열
        #   browser_select_option    드롭다운에서 실제로 고른다
        #
        # ★ 도구를 새로 만들면 **그날** 여기에 넣어라. 세 번 다 같은 모양이었다 —
        #   도구는 잘 돌았고, 빠진 것은 그 실적을 세는 자리였다. 조용히 빠지는 것이
        #   제일 나쁘다(성공률이 아니라 **분모**가 틀린다).
        "browser_click_confirmed",
        "browser_fill_form",
        "browser_select_option",
        # ── 2026-08-20 추가. 네 번째로 샜다(이번엔 watch 둘). ─────────────────
        #
        # 초소를 세우는 것은 **앞으로 자비스가 스스로 도는 일을 만드는 것**이다.
        # `site_promote_draft`(초안을 확정해 앞으로 실제로 쓰이게 한다)와 같은 계열이라
        # 여기 둔다. 없애는 것도 같은 크기의 변경이다.
        "watch_create",
        "watch_cancel",
        # ── 2026-08-21 추가. 다섯 번째로 샜다(schedule 둘). ────────────────────
        #
        # 예약을 만드는 것은 **앞으로 자비스가 스스로 도는 일을 만드는 것**이라
        # `watch_create` 와 같은 계열이다. 게다가 `deliver_to` 가 붙으면 되돌릴 수
        # 없는 메일까지 나간다. 취소도 같은 크기의 변경이다.
        #
        # ★ 이번엔 반창고를 붙이는 대신 **검사로 박았다** —
        #   `tests/test_tool_classification.py::test_every_registered_tool_is_classified`
        #   가 이제 분류 안 된 도구를 그 자리에서 잡는다. 안내문("그날 넣어라")을
        #   다섯 번 적고도 다섯 번 샜으면, 그건 안내문이 틀린 게 아니라 안내문으로
        #   될 일이 아니었던 것이다(사고 R).
        "schedule_create",
        "schedule_cancel",
        # ── 같은 날, 검사를 만들자마자 **12개가 더 나왔다.** ────────────────────
        #
        # 라이브 눈금에는 `schedule_*` 둘만 떴다. 그 경고가 **실제로 호출된 도구만**
        # 보여 주기 때문이다 — 만들어 놓고 아직 안 불린 도구는 분류가 비어 있어도
        # 아무 데도 안 나온다. "경고에 없다"가 "분류됐다"와 "한 번도 안 불렸다"를
        # 동시에 뜻하고 있었다. 빈 값 하나가 두 사실을 뜻하면 조용히 고장난다.
        #
        # 아래는 전부 화면이나 바깥을 **실제로 바꾼다**:
        #   browser_file_upload      이 PC 파일을 바깥으로 내보낸다(L2)
        #   browser_handle_dialog    창의 버튼을 실제로 누른다
        #   camera_stop_live         짐벌 송출을 멈춘다(start 가 이미 여기 있다)
        #   camera_register_new_person / camera_forget_face
        #                            얼굴 장부를 바꾼다(register_face 와 같은 계열)
        #   google_calendar_update / google_calendar_delete
        #                            남의 일정을 고치고 지운다. COMMIT 에도 넣는다
        "browser_file_upload",
        "browser_handle_dialog",
        "camera_stop_live",
        "camera_register_new_person",
        "camera_forget_face",
        "google_calendar_update",
        "google_calendar_delete",
        # ── 격리 상자 (2026-08-21). **만든 날 넣는다.** ───────────────────────
        #
        # 상자 안에서 코드를 실제로 돌린다. 호스트는 못 건드리지만 「무언가를
        # 실제로 했다」는 점에서 읽기가 아니다. `sandbox_fetch` 는 이 PC 에 파일을
        # 만들므로 더 분명하다.
        #
        # `sandbox_reset` 은 되돌리는 쪽인데도 여기 둔다 — `undo_action` 과 같다.
        # 되돌리는 것도 하는 일이고, 안 세면 실적이 사라진다.
        "sandbox_run",
        "artifact_from_observations",
        "sandbox_fetch",
        "sandbox_reset",
        # 로컬 파일 쓰기. 작업폴더 안에서도 실제 파일이 남으므로 L3이고, 셋 다
        # InverseSpec으로 원본 복원/신규 파일 삭제가 가능하다.
        "local_write_file",
        "local_apply_edit",
        "local_delete_file",
        # 문서 생성·엑셀 편집도 실제 파일이 남는다. 둘 다 InverseSpec 이 붙어 있다.
        "local_write_document",
        "local_edit_spreadsheet",
        "local_edit_document",
        # 클립보드는 사람 손이 닿는 곳까지 잇는 다리다 — 실제로 밖에 남는다.
        "clipboard_write",
        "hwp_apply_edit",
        # 지목 폴더의 코드를 실제로 읽고 고치는 외부 코딩 손. 결과가 git 변경으로
        # 남으므로 읽기나 중립으로 세면 L3 분모가 조용히 샌다.
        "claude_code_delegate",
    }
)

# 화면을 만지는 것이 아니라 **바깥을 실제로 바꾸는** 쓰기. 되돌릴 수 있는지를 물어야
# 하는 것은 이것들이다 — 클릭·입력은 다시 하면 되지만 이건 그렇지 않다.
#
# WRITE_TOOLS 의 부분집합이라 따로 세도 분모가 겹치지 않는다(성공률은 WRITE_TOOLS 로,
# 되돌릴 수 있는가는 이 목록으로 본다).
COMMIT_TOOLS = frozenset(
    {
        "naver_blog_save_draft",
        "naver_blog_publish",
        "google_gmail_send",
        "google_calendar_create",
        "site_promote_draft",
        "camera_register_face",
        "windows_execute_preview",
        "windows_open_path",
        "local_open_path",
        "local_write_file",
        "local_apply_edit",
        "local_delete_file",
        "local_write_document",
        "local_edit_spreadsheet",
        "artifact_from_observations",
        "hwp_apply_edit",
        # 남의 달력을 고치고 지운다. `google_calendar_create` 와 같은 무게이고,
        # 참석자가 있으면 밖으로 알림이 나간다 — 되돌려도 이미 나간 것은 남는다.
        "google_calendar_update",
        "google_calendar_delete",
        # 2026-09-01. 새 도구는 **그날** 이 표에 넣는다 — 조용히 빠지는 것이
        # 제일 나쁘다(어제는 `pick_suggestion` 71건이 같은 자리에서 빠졌다).
        "google_drive_write",
    }
)

# 준비 단계는 아직 아무것도 바꾸지 않는다. 성공률에 넣으면 쓰기가 실제보다 좋아 보인다.
PREPARE_TOOLS = frozenset(
    {
        "naver_blog_prepare_post",
        "naver_blog_prepare_save_draft",
        "google_gmail_prepare_send",
        "google_calendar_prepare_create",
        # 절차를 **초안으로만** 적어 둔다. 확정(`site_promote_draft`)이 쓰기다.
        "site_draft_recipe",
        # ★ 형제 셋 중 이것만 빠져 있었다(2026-08-14). 준비 도구가 준비 칸에 없으면
        # 쓰기 칸에도 없어서 **어디에도 안 세어진다** — 조용히 새는 전형이다.
        "naver_blog_prepare_publish",
        # 형제가 또 있었다(2026-08-21). create 만 있고 update·delete 가 없었다.
        "google_calendar_prepare_update",
        "google_calendar_prepare_delete",
        # 2026-09-01: 드라이브 쓰기의 준비 짝. 검사가 잡았다 — 등록하면서
        #   커밋만 넣고 준비를 빠뜨렸다. 형제로 세 번째 재발이다.
        "google_drive_prepare_write",
        # 캔버스처럼 UIA 로 못 잡는 화면에서 **누르기 전에** 좌표를 그려 본다.
        # 확정은 `windows_execute_preview`(WRITE·COMMIT)다.
        "windows_visual_preview",
        "hwp_preview_edit",
    }
)

# 어느 단계도 아닌 보조 도구 — 화면을 바꾸지도 않고 출처를 가져오지도 않는다.
#
# 왜 굳이 적어 두나. 이 목록이 없으면 이것들이 전부 "분류 안 된 도구" 줄에 쌓이고,
# 그 줄이 길어질수록 사람이 안 읽게 된다. 실제로 그렇게 돼서 `browser_pick_suggestion`
# 71건이 그 안에 묻혀 있었다. **경보는 짧아야 경보다** — 여기 적힌 것을 빼고 나면
# 그 줄에 남는 것은 정말로 새로 생긴, 아직 판단 안 한 도구뿐이다.
#
# L2(조사)에 넣지 않는 이유: L2 는 `agent._READ_TOOLS`(목록·본문을 실제로 가져오는
# 도구)로 잰다. 대기·스크린샷·창 목록을 거기 섞으면 거의 늘 성공하는 호출이 분모를
# 채워 조사 성공률이 실제보다 좋아 보인다.
NEUTRAL_TOOLS = frozenset(
    {
        # MCP 껍데기에만 있는 위임 문(2026-09-16, `delegation.py`). 잡 안 걸음으로는 안 나온다 —
        # 그 잡의 걸음(조사·쓰기)이 따로 세어진다. 여기서 또 세면 한 판이 두 번 들어간다.
        "sonjari_task",
        "sonjari_task_status",
        "sonjari_guide",  # 가이드 본문을 돌려주는 읽기 전용 문(2026-09-17) — 잡이 아니다
        "unity_list_recipes",  # 레시피 목록(2026-09-27) — 무엇을 할 수 있나일 뿐, 읽은 근거가 아니다
        "unity_try_script",  # 바깥 AI 전용 초안 문(2026-09-27) — 온텔릭 잡 안 걸음으로는 안 나온다
        "browser_find",
        "browser_wait",
        "browser_screenshot",
        "browser_probe_frames",
        "browser_tabs",
        "browser_switch_tab",
        "ui_find_target",
        "ui_verify",
        "site_list",
        "site_friction",
        "site_review_draft",
        "clipboard_read",
        "gpu_status",
        # 폴더를 열어 달라고 **사람에게 묻는** 문 (2026-09-20). 쓰기가 아니다 — 파일을 하나도
        # 안 건드린다. 그 뒤에 실제로 무엇을 했는지는 그 걸음이 따로 세어진다.
        "local_request_path_access",
        # 사람에게 선택지로 **묻는** 문 (2026-09-30). 읽은 근거도 쓰기 실적도 아니다.
        "ask_user",
        # 만든 페이지를 루프백에 띄워 보는 문 (2026-09-20). 파일을 안 건드린다.
        "local_preview_page",
        # 셸 (2026-09-20). 보는 명령이 대부분이고, 바꾸는 것은 승인 카드를 지난다 —
        # 실제 쓰기 실적은 그 뒤의 쓰기 도구 걸음으로 세어진다. 여기서 또 세면 두 번 들어간다.
        "local_run_shell",
        "local_find_symbol",
        # 자기 검사·치료 (2026-08-21). **만든 날 분류표에 넣는다** — 이 저장소는
        # 새 도구가 분류표에 안 들어가 성공률 분모에서 조용히 빠지는 일을 두 번
        # 겪었다(browser_pick_suggestion 71건 · 자사 데이터 4건).
        #
        # `self_heal` 도 여기다. 밖으로 나가는 것이 없고 이미 죽은 것을 다시
        # 띄우는 일이라 「쓰기 실적」으로 세면 L3 가 부풀어 보인다.
        "self_check",
        "self_heal",
        "shell_probe",
        # Code 저장소 안에서 테스트/빌드의 종료 코드를 확인한다. 외부 상태를
        # 커밋하는 도구가 아니므로 L3 쓰기 실적으로 세지 않는다.
        "local_run_project_command",
        # 밖에서 가져온 지식을 읽는다. 파일을 읽을 뿐이라 L2(조사)에 안 넣는다 —
        # 거의 늘 성공하는 호출이 조사 분모를 채우면 성공률이 실제보다 좋아 보인다.
        "skill_list",
        "skill_read",
        # 보는 자리를 옮기거나 확인만 한다. `browser_back` 과 같은 계열이다.
        # `browser_close` 는 도구 설명이 "닫는다고 잃는 것은 없다"고 적고 있다.
        "browser_close",
        "browser_verify",
        # ── plopfit 조사 도구 셋. **여기는 임시 자리다.** ─────────────────────
        #
        # 이것들은 사실 `naver_web`·`naver_news`·`github_search` 와 같은 묶음이라
        # `agent._LISTING_TOOLS`(= L2 조사 분모)에 있어야 맞다. 실제로 옮겨 봤더니
        # `test_tools_are_in_the_prompt.py` 가 잡았다 — 증거 도구가 되는 순간
        # **에이전트 프롬프트의 절차에 이름이 있어야 한다.**
        #
        # 그건 프롬프트를 고치는 일이고, 1단계의 계약은 "프롬프트를 한 글자도 안
        # 건드린다"이다(접두사 캐시·라우팅·주의 보호). 그래서 지금은 분류만 해 두고
        # L2 로 옮기는 것은 **프롬프트를 여는 2단계**에서 절차 문구와 같이 한다.
        #
        # 3일치 실측 호출 0건이라 지금 손해 보는 숫자는 없다.
        "google_trend",
        "hackernews_top",
        "reddit_hot",
        "camera_look",
        "camera_find_person",
        "camera_status",
        "camera_who_is_there",
        "windows_list_open_windows",
        "windows_focus_window",
        "windows_uia_snapshot",
        "windows_uia_preview",
        # 설명에 "화면을 바꾸지 않고 원래 클립보드도 되돌려 놓는다"고 적혀 있다.
        "windows_copy_from_window",
        # ── 2026-08-14 추가 ──────────────────────────────────────────────────
        #
        # 보는 자리를 옮길 뿐 아무것도 확정하지 않는다. 본문을 손에 쥐여 주는 것은
        # `browser_extract` 라, 이것들을 L2 에 넣으면 거의 늘 성공하는 호출이
        # 조사 분모를 채워 성공률이 실제보다 좋아 보인다.
        "browser_back",
        "browser_scroll",
        "browser_load_more",
        "browser_hover",
        "schedule_list",
        # 되돌릴 수 있는 것을 **보여주기만** 한다(도구 설명에 "공짜·읽기 전용").
        # 되돌리는 것은 undo_action 이고 그건 WRITE_TOOLS 에 있다.
        "undo_list",
        # 초소 목록은 읽기다(게이트웨이 등급도 이것만 L0 다).
        "watch_list",
        # ★ `site_run` 은 **동작마다 등급이 갈린다**(`site_recipes._run_risk` 가
        #   레시피의 `risk_of(action)` 을 그대로 쓴다). 그래서 이름만으로는 읽기인지
        #   쓰기인지 정할 수 없다.
        #
        #   지금 실적은 조사 쪽이다(사람인 검색 12건). 통째로 쓰기에 넣으면 읽기
        #   전용 레시피 실행이 L3 를 부풀린다 — 이 눈금이 제일 경계하는 일이다.
        #   그래서 일단 여기 둔다. **다만 이건 임시다** — 제대로 하려면 행마다
        #   `arguments.action` 을 보고 갈라야 한다. 쓰기 레시피가 실제로 돌기
        #   시작하면 그 순간부터 이 칸이 거짓말을 한다.
        "site_run",
    }
)


# 표의 칸 이름 -> config 의 축 이름. 둘이 갈리면 조용히 빈 값이 나온다.
_AXIS_OF_LEVEL = {"read": "read", "write": "write", "delegation": "delegate"}
_AXIS_LABELS = {"read": "조사", "write": "쓰기", "delegation": "위임"}


def _axis_builds(db_path: Path, axis: str, now_axis: str) -> set[str]:
    """그 축의 지문이 **지금과 같은** 판을 전부 모은다.

    `build` 는 패키지 전체 해시라, 화면 코드 한 줄만 고쳐도 새 판이 된다. 그래서
    「지금 판만」 칸이 늘 0~4 건이었다(2026-08-21: 3일치 128건이 판 29종에 흩어짐).

    조사 성능은 `browser.py`·`agent.py` 가 안 바뀐 동안 유효하다. 그 축의 지문이
    같은 판들을 묶으면 **표본이 훨씬 오래 산다.**

    ⚠ 판별표(`build_manifest`)는 2026-08-21 에 생겼다. 그 전 판은 축 지문이 없어
    여기 안 들어온다 — 그건 누락이 아니라 **모른다는 뜻**이고, 모르는 것을 지금
    표본에 넣지 않는 것이 이 저장소의 규칙이다.
    """
    if not now_axis:
        return set()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return set()
    try:
        rows = conn.execute("SELECT build, axes_json FROM build_manifest").fetchall()
    except sqlite3.Error:
        return set()  # 옛 DB 에는 이 표가 없다. 재는 자가 옛 DB 앞에서 죽으면 안 된다
    finally:
        conn.close()
    out: set[str] = set()
    for build, axes_json in rows:
        try:
            axes = json.loads(axes_json)
        except Exception:
            continue
        if axes.get(axis) == now_axis:
            out.add(str(build))
    return out


def _current_axis_builds() -> dict[str, str]:
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from alture_jarvis.config import axis_build_ids  # noqa: PLC0415

    return axis_build_ids()


def _current_build() -> str:
    """지금 **재는 쪽**이 보는 코드의 지문. DB 에 적힌 것과 맞춰 보려면 필요하다.

    주의: 이 스크립트가 E: 소스를 보고 있고 자비스는 C: 런타임으로 도는 경우
    지문이 다르게 나온다. 그건 오작동이 아니라 **실제로 둘이 다르다는 뜻**이다
    (C: 런타임이 조용히 낡는 사고가 이미 있었다).
    """
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from alture_jarvis.config import build_id  # noqa: PLC0415

    return build_id()


def _read_tools() -> frozenset[str]:
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from alture_jarvis.agent import _READ_TOOLS  # noqa: PLC0415

    return _READ_TOOLS


def _fabrication_suspect(payload: str, result: dict) -> bool:
    """도구를 하나도 안 쓴 답인데, **가서 본 것처럼** 말하고 있는가.

    판정은 에이전트가 쓰는 검사(`_cited_source_check`)를 **그대로 가져온다.**
    여기서 따로 규칙을 쓰면 재는 자와 고치는 자가 갈리고, 갈리면 조용히 어긋난다
    (읽기 도구 집합을 `_READ_TOOLS` 에서 그대로 가져오는 것과 같은 이유).
    """
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    try:
        prompt = str(json.loads(payload or "{}").get("prompt") or "")
    except (ValueError, TypeError):
        return False
    if not prompt:
        return False
    return bool(BrowserAgent._cited_source_check(prompt, str(result.get("answer") or ""), []))


# 이 판이 **시킨 것을 채우고** 끝났는가. 모르면 None.
#
# ★ 2026-08-20. 여기가 L4 의 분자였고, 그 분자가 이랬다:
#
#     verified = bool(steps) and any(step["ok"] for step in steps)   # agent.py
#
# **걸음 하나라도 성공했으면 참**이다. 그래서 인수인계서 3-1 이 천장으로 지목한 바로
# 그 판 — `prepare_post → fill_editor → prepare_save_draft` 까지 가 놓고 "승인을
# 기다리는 중입니다"라고 답한 판 — 이 **위임 성공으로 세어졌다.** 고쳐야 할 고장이
# 분자 안에 앉아 있었던 것이다. 실측(7일 179판): 표는 94.4%, 이 자로 다시 세면 58%.
#
# 판정은 에이전트가 이미 장부에 적어 두는 것으로 한다(새로 기록할 것이 없다):
#
#     completion_state   complete(다 채움) · answered(대조할 요구를 못 뽑음) ·
#                        partial(남았다) — 답이 스스로 미달을 말하면 여기서 내려간다
#     stop_reason        completion_state 가 없던 옛 줄을 위한 갈음
#
# 둘 다 없으면 **모른다.** 모르는 것을 성공으로도 실패로도 세지 않고 분모에서 뺀다 —
# 옛 DB 앞에서 이 자가 거짓말을 시작하지 않게.
_REACHED_STOP_REASONS = frozenset({"model_done", "wrapped_up:goal_met", "model_answered"})


def _goal_reached(verification: dict) -> bool | None:
    state = str(verification.get("completion_state") or "")
    if state:
        # ★ 2026-08-21. 「일을 시켰는데 대조할 요구를 못 뽑은」 판이다.
        #   못 잰 것이지 잘한 것이 아니다 — 위 주석의 원칙("모르는 것을 성공으로도
        #   실패로도 세지 않고 분모에서 뺀다")이 이 칸에만 안 지켜지고 있었다.
        #
        #   그동안 `answered` 한 칸에 이것과 「원래 요구가 없는 대화」가 같이
        #   들어 있었고, 둘 다 성공으로 세어졌다(위임 54판 중 17판 = 31.5%).
        if state == "unmeasured":
            return None
        return state in {"complete", "answered"}
    reason = str(verification.get("stop_reason") or "")
    if reason:
        return reason in _REACHED_STOP_REASONS
    return None


def _pct(ok: int, total: int) -> str:
    return f"{ok / total * 100:.1f}%" if total else "—"


def _level_pct(ok: int, total: int) -> str:
    """단계 표에 찍는 비율. **표본이 적으면 비율을 아예 안 낸다.**

    이 파일 맨 위의 규율 그대로다 — "2 건 중 2 건 성공을 100% 라고 적는 순간 그 표가
    거짓말을 시작한다". 판정 칸은 이미 「표본 부족」을 말하고 있었는데 옆의 비율 칸이
    `100.0%` 를 찍고 있었다. 사람은 숫자를 읽는다.

    `_pct` 는 그대로 둔다 — 「발목을 잡는 쓰기 도구」 줄은 `2/4` 처럼 **원 개수를 같이
    보여주므로** 비율이 오해를 만들지 않는다.
    """
    return _pct(ok, total) if total >= MIN_SAMPLE else "—"


def _verdict(ok: int, total: int, target: int) -> str:
    if total < MIN_SAMPLE:
        return f"표본 부족 ({total}건)"
    rate = ok / total * 100
    return f"{'도달' if rate >= target else '미달'} (기준 {target}%)"


def measure(db_path: Path, since: float, build: str | set[str] = "") -> dict:
    """`build` 를 주면 **그 판이 낸 실적만** 센다. 안 주면 전부 세되,
    표본이 어느 판 것인지를 같이 돌려준다 — 그 줄이 없으면 낡은 표를 새 표로 읽는다.

    ★ 집합을 줄 수도 있다(2026-08-21). 축별 지문이 같은 **여러 판을 묶어** 보기
    위해서다 — 화면 코드 한 줄만 고쳐도 판이 바뀌어 「지금 판만」이 늘 0~4 건이었다.
    조사 성능은 `browser.py`·`agent.py` 가 안 바뀐 동안 유효하다."""
    wanted: set[str] = {build} if isinstance(build, str) and build else (
        set(build) if not isinstance(build, str) else set()
    )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    # `build` 칸은 2026-08-13 에 생겼다. 그 전 DB 로도 이 자는 돌아야 한다 —
    # 재는 자가 옛 DB 앞에서 죽으면 아무도 안 재게 된다.
    def has_build(table: str) -> bool:
        return any(row[1] == "build" for row in conn.execute(f"PRAGMA table_info({table})"))

    audit_build = "build" if has_build("audit_log") else "''"
    jobs_build = "build" if has_build("jobs") else "''"

    read_tools = _read_tools()
    tried: Counter[str] = Counter()
    passed: Counter[str] = Counter()

    # 도구 결과는 audit_log 가 전수를 갖고 있다(잡 result_json 은 에이전트 잡만).
    builds: Counter[str] = Counter()
    for payload, created, row_build in conn.execute(
        f"SELECT payload_json, created_at, {audit_build} FROM audit_log WHERE event = 'tool_executed'"
    ):
        if created < since:
            continue
        builds[str(row_build or "")] += 1
        if wanted and str(row_build or "") not in wanted:
            continue
        try:
            row = json.loads(payload)
        except (ValueError, TypeError):
            continue
        name = str(row.get("tool") or "")
        if not name:
            continue
        tried[name] += 1
        if row.get("ok") is True:
            passed[name] += 1

    def tally(names) -> tuple[int, int]:
        return (
            sum(passed[n] for n in names if n in tried),
            sum(tried[n] for n in names if n in tried),
        )

    read_ok, read_all = tally(read_tools)
    write_ok, write_all = tally(WRITE_TOOLS)

    # ── L4: 사람 손이 닿았는가 ────────────────────────────────────────────────
    #
    # 손이 닿은 흔적 셋. 하나라도 있으면 그 잡은 위임이 아니다.
    #   1) 승인 카드를 눌러 줘야 했다        (approvals)
    #   2) "3분 더 / 계속 / 정리"를 골라 줬다 (agent_continuation_decided)
    #   3) 로그인·봇 확인 앞에서 멈췄다       (agent_checkpoints 의 human_gate)
    touched: set[str] = set()
    for (job_id,) in conn.execute("SELECT DISTINCT job_id FROM approvals WHERE job_id != ''"):
        touched.add(job_id)
    for subject, created in conn.execute(
        "SELECT subject_id, created_at FROM audit_log WHERE event = 'agent_continuation_decided'"
    ):
        if created >= since:
            touched.add(str(subject))
    gate_waits = 0
    for job_id, state in conn.execute("SELECT job_id, state_json FROM agent_checkpoints"):
        touched.add(str(job_id))
        if "human_gate" in str(state):
            gate_waits += 1

    # ★ 여기를 두 번 고쳤다. 첫 판은 97.4% 가 나왔는데 거짓이었다.
    #
    #   1) `result_json LIKE '%agent_trace%'` 로 골랐더니 **키만 있고 값이 null 인**
    #      일반 대화 108 건이 섞였다. 에이전트가 돌지도 않은 잡을 "위임 성공"으로
    #      센 것이다.
    #   2) 남은 것 중에도 0~1 스텝짜리가 37 건이었다. 검색 한 번 한 잡을 위임이라고
    #      부르면, 자비스가 아무것도 안 할수록 점수가 올라간다.
    #
    # 그래서 **위임이 걸려 있던 잡**만 센다: 3 스텝 이상이거나 쓰기 도구를 건드린 것.
    # 그리고 끝났다는 말로는 부족해서 `verified` 까지 본다 — 포기하고 답한 것과
    # 근거를 남기고 끝낸 것은 다르다.
    agent_runs = 0
    substantive = 0
    unattended_done = 0
    still_waiting = 0
    # 어떻게 끝났는지의 분포. 이 줄이 없어서 L4 94.4% 가 거짓인 것을 못 봤다.
    outcomes: Counter[str] = Counter()
    unknown_outcome = 0
    pushbacks = 0
    pushback_worked = 0
    # ★ 2026-08-13 에 뚫린 구멍. 이 자가 "전부 100%"라고 답한 바로 그날, 열 판 중
    # 일곱 판이 도구를 한 번도 안 쓰고 답을 지어내고 있었다.
    #
    # 원인은 바로 아래 `if not isinstance(trace, dict): continue` 였다. 지어낸 판은
    # 에이전트가 안 돌아 `agent_trace` 가 없고, 그래서 **분모에도 안 들어갔다.**
    # 도구를 한 번도 안 부른 판은 도구 성공률을 못 떨어뜨린다 — 아무것도 안 할수록
    # 표가 깨끗해진다. 0~1 스텝을 빼면서 배운 것과 같은 병이고, 이쪽이 더 깊다.
    #
    # 그래서 **안 한 판**을 따로 센다. 성공률에 섞지 않는다(섞으면 조언·잡담까지
    # 실패로 세어진다). 지금은 이게 '재는 값'이 아니라 '보이는 값'이다.
    toolless = 0
    toolless_sourced = 0
    for job_id, kind, status, payload, result, created, job_build in conn.execute(
        f"SELECT id, kind, status, payload_json, result_json, created_at, {jobs_build} FROM jobs"
    ):
        if created < since or not result:
            continue
        if wanted and str(job_build or "") not in wanted:
            continue
        try:
            parsed = json.loads(result)
            trace = parsed.get("agent_trace")
        except (ValueError, TypeError):
            continue
        if not isinstance(trace, dict):
            if kind == "chat":
                toolless += 1
                if _fabrication_suspect(payload, parsed):
                    toolless_sourced += 1
            continue
        agent_runs += 1
        steps = trace.get("steps") or []
        if not (len(steps) >= 3 or any(s.get("tool") in WRITE_TOOLS for s in steps)):
            continue
        substantive += 1
        verification = trace.get("verification") or {}
        # ★ `model_answered` 한 칸이 두 가지를 뜻했다 — 「원래 요구가 없는 대화」와
        #   「일을 시켰는데 못 뽑음」. 뒤쪽은 못 잰 것이라 성공률 분모에서 빠지므로,
        #   표에서도 갈라 보여야 어디가 새는지 보인다.
        reason = str(verification.get("stop_reason") or "(옛 줄 — 이유가 안 남음)")
        if reason == "model_answered" and verification.get("completion_state") == "unmeasured":
            reason = "model_answered:unmeasured"
        outcomes[reason] += 1
        # 되받기가 **듣는지** 재는 자리. 지금까지 `agent_plan_pushback` 은 이벤트로만
        # 나가고 장부에 안 남아서, 되받기를 두 번까지 하게 해 두고도 그게 효과가
        # 있었는지 아무도 못 봤다(7일치 audit_log 에 한 줄도 없다).
        pushbacks += int(verification.get("plan_pushbacks") or 0)
        if verification.get("plan_pushback_worked"):
            pushback_worked += 1
        reached = _goal_reached(verification)
        if reached is None:
            # 채웠는지 장부에 안 남은 옛 줄. 성공으로도 실패로도 세지 않는다.
            unknown_outcome += 1
        if status in {"waiting_approval", "waiting_continuation"}:
            still_waiting += 1
            continue
        verified = bool(verification.get("verified"))
        if status == "completed" and verified and reached and job_id not in touched:
            unattended_done += 1

    return {
        "window_from": since,
        "read": (read_ok, read_all),
        "write": (write_ok, write_all),
        "prepare": tally(PREPARE_TOOLS),
        # ★ 분모에서 **판정할 수 없는 옛 줄을 뺀다.** 모르는 것을 실패로 밀어 넣으면
        # 옛 DB 를 볼 때마다 없는 회귀가 보인다.
        "delegation": (unattended_done, max(0, substantive - unknown_outcome)),
        "outcomes": outcomes,
        "unknown_outcome": unknown_outcome,
        "pushbacks": (pushback_worked, pushbacks),
        "approvals": _approval_outcomes(conn, since),
        "agent_runs": agent_runs,
        "toolless": toolless,
        "toolless_sourced": toolless_sourced,
        "still_waiting": still_waiting,
        "gate_waits": gate_waits,
        "tried": tried,
        "passed": passed,
        "read_tools": read_tools,
        "builds": builds,
        "build_filter": (sorted(wanted)[0] if len(wanted) == 1 else ""),
        "build_filter_count": len(wanted),
        # 돌아갈 길을 남긴 쓰기. 표가 아직 없는 옛 DB 에서도 이 자가 돌아야 하므로
        # (재는 자가 죽으면 아무도 안 잰다) 실패를 통째로 삼킨다.
        "undo_offers": _undo_offers(conn, since),
    }


def _approval_outcomes(conn: sqlite3.Connection, since: float) -> dict[str, int]:
    """승인 카드가 **어떻게 끝났나.**

    ★ 만료가 중요하다. 만료된 승인은 "사람이 안 눌렀다"가 아니라 **자비스가 사람을
    기다리다 죽은 판**이다. L4 정의상 승인이 걸린 판은 애초에 위임이 아니므로 이
    줄은 성공률에 안 들어가지만, 만료 비율이 높으면 "승인이 걸리는 일은 아예
    끝나지 않는다"는 뜻이라 어디를 되돌릴 수 있게 만들지 정하는 근거가 된다.
    (실측 2026-08-20: 11건 중 4건 만료 = 36%.)
    """
    try:
        rows = conn.execute(
            "SELECT status FROM approvals WHERE created_at >= ?", (since,)
        ).fetchall()
    except sqlite3.Error:
        return {}
    counts = Counter(str(row[0] or "") for row in rows)
    return {"made": len(rows), **{k: v for k, v in counts.items()}}


def _undo_offers(conn: sqlite3.Connection, since: float) -> dict[str, int]:
    try:
        rows = conn.execute(
            "SELECT automatic, status FROM undo_offers WHERE created_at >= ?", (since,)
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        "made": len(rows),
        "automatic": sum(1 for row in rows if row[0]),
        "undone": sum(1 for row in rows if str(row[1]) == "undone"),
    }


# 이 프로그램의 나이 감각. 이 밑으로 떨어지면 표는 "지금"이 아니라 "그때"를 말한다.
FRESH_ENOUGH = 50


def _freshness(result: dict) -> list[str]:
    """표본이 **어느 판** 것인지. 이 줄이 없어서 사고가 났다(2026-08-13).

    `browser_pick_suggestion 74.6%` 가 "발목을 잡는 도구"로 계속 찍혔는데, 그 도구는
    이미 전날 고쳐져 24/24 였다. 74.6% 는 **없어진 코드**의 성적이었고, 표에는
    그것을 알아볼 방법이 한 줄도 없었다.
    """
    builds: Counter[str] = result.get("builds") or Counter()
    total = sum(builds.values())
    if not total:
        return []
    now = result.get("now_build") or ""
    mine = builds.get(now, 0)
    share = mine / total * 100
    unknown = builds.get("", 0)
    note = "" if share >= FRESH_ENOUGH else "   ← 이 표는 지금 코드를 말하지 않는다"
    out = [
        f"  표본의 판   지금 코드({now[:8]}) {mine}건 / 전체 {total}건 = {share:.0f}%{note}",
    ]
    if unknown:
        out.append(f"              판을 모르는 옛 줄 {unknown}건 (2026-08-13 이전에 쌓인 것)")
    if result.get("build_filter"):
        out = [f"  표본의 판   {result['build_filter'][:8]} 판만 세었다 ({mine}건)"]
    out.append("")
    return out


# 사람이 읽을 이름. 코드의 이름은 짧아서 표에 그대로 두면 아무도 안 읽는다.
_OUTCOME_LABELS = {
    "model_done": "시킨 것을 다 채우고 끝",
    "wrapped_up:goal_met": "다 채워서 정리",
    # ★ 갈래를 만든 것이 2026-08-21 이라 **그 전 줄에는 둘이 섞여 있다.** 옛 줄을
    #   지금 이름으로 읽으면 또 틀린다 — 이 저장소가 그걸로 두 번 헛짚었다.
    "model_answered": "요구가 없는 대화 (옛 줄은 '못 쟀음'이 섞여 있다)",
    # ★ 일을 시켰는데 계획 층이 대조할 요구를 못 뽑았다. **성공이 아니라 모름**이라
    #   성공률 분모에서 빠진다. 이 줄이 길어지면 눈금이 고장 나고 있다는 뜻이다.
    "model_answered:unmeasured": "❔ 일을 시켰는데 못 쟀음",
    "model_stopped_early": "★ 요구가 남았는데 멈춤",
    "wrapped_up:no_progress": "더 가도 진전이 없어 접음",
    "step_cap": "걸음을 다 씀",
}


def _outcome_lines(result: dict) -> list[str]:
    """**어떻게 끝났나.** L4 한 줄이 못 보여 주는 것.

    이 분포가 없어서 94.4% 가 거짓인 것을 아무도 못 봤다. 비율 하나는 어디가
    새는지 말해 주지 않는다 — 갈래로 세야 "커밋 앞에서 멈춘다"가 보인다.
    """
    outcomes: Counter[str] = result.get("outcomes") or Counter()
    if not outcomes:
        return []
    total = sum(outcomes.values())
    lines = ["  어떻게 끝났나 (위임이 걸린 잡 " + str(total) + "건)"]
    for reason, count in outcomes.most_common():
        label = _OUTCOME_LABELS.get(reason, reason)
        mark = "✅" if reason in _REACHED_STOP_REASONS else "❌"
        if reason.startswith("("):
            mark = "  "
        lines.append(f"    {mark} {label:<26}{count:>5}건  {count / total * 100:4.1f}%")
    unknown = int(result.get("unknown_outcome") or 0)
    if unknown:
        lines.append(f"    ※ 채웠는지 장부에 안 남은 옛 줄 {unknown}건은 분모에서 뺐다")
    worked, tried = result.get("pushbacks") or (0, 0)
    if tried:
        lines.append(f"    되받기 {tried}회 — 그중 도구를 다시 부른 판 {worked}건")
    lines.append("")
    return lines


def _approval_lines(result: dict) -> list[str]:
    """승인이 **어떻게 끝났나.** 만료는 사람이 안 누른 게 아니라 판이 죽은 것이다."""
    approvals = result.get("approvals") or {}
    made = int(approvals.get("made") or 0)
    if not made:
        return []
    expired = int(approvals.get("expired") or 0)
    consumed = int(approvals.get("consumed") or 0)
    denied = int(approvals.get("denied") or 0)
    lines = [
        "  승인 카드",
        f"    요청 {made}회 · 실행까지 간 것 {consumed}회 · 거절 {denied}회 · "
        f"만료 {expired}회({expired / made * 100:.0f}%)",
    ]
    if expired:
        lines.append(
            "    ← 만료는 사람을 기다리다 죽은 판이다. 되돌릴 수 있는 동작이면 "
            "등급을 내리는 편이 낫다."
        )
    lines.append("")
    return lines


def report(result: dict) -> str:
    read_ok, read_all = result["read"]
    write_ok, write_all = result["write"]
    done, jobs = result["delegation"]
    prep_ok, prep_all = result["prepare"]

    # ★ 2026-08-20. **이 자가 자기 규칙을 판(build)에는 안 쓰고 있었다.**
    #
    # 파일 맨 위에 적어 둔 규율은 "표본이 적으면 비율을 내지 않고 표본 수를 그대로
    # 보여준다" 인데, 그 규칙이 **날짜에만** 걸려 있었다. 그래서 30일 평균이
    # `지금` 이라는 이름의 칸에 찍혔고, 실제로 그날 두 번 오독했다:
    #
    #   "L4 52.8% · 요구가 남았는데 멈춤 105건" → 105건 중 98건이 계측 전 옛 줄
    #   "site 요구 미달 5건 = 로그인 벽"        → 전부 그날 아침에 고쳐진 것
    #
    # 머리에 경고 한 줄("이 표는 지금 코드를 말하지 않는다")은 있었지만, 큰 숫자가
    # 여전히 `지금` 칸에 있으면 사람은 큰 숫자를 읽는다. 그래서 **둘 다 찍는다.**
    # 잘못 읽을 칸을 없애는 것이 경고문보다 낫다(안내문은 안 먹는다 — 사고 R).
    current = result.get("current") or {}
    header = "전체" if current else "지금"

    def level(label: str, pad: int, ok: int, all_: int, key: str, target: int) -> list[str]:
        rows = [f"  {label:<{pad}}{_level_pct(ok, all_):>10}{all_:>10}   {_verdict(ok, all_, target)}"]
        if not current:
            return rows
        now_ok, now_all = current[key]
        # 아래 줄의 폭은 **위 줄과 무관하게 고정**이다. 상위 라벨의 pad 를 물려받으면
        # 한글 폭 보정 때문에 단계마다 한 칸씩 어긋난다.
        rows.append(
            f"  {'   └ 지금 판만':<20}{_level_pct(now_ok, now_all):>10}{now_all:>10}   "
            f"{_verdict(now_ok, now_all, target)}"
        )
        # ★ 그 축의 코드가 안 바뀐 판들을 묶은 값. 「지금 판만」이 표본 부족일 때
        #   이 줄이 대신 답한다 — 화면 한 줄 고쳤다고 조사 실적이 사라질 이유는 없다.
        axis = (result.get("by_axis") or {}).get(key)
        if axis:
            ax_ok, ax_all = axis["measure"][key]
            rows.append(
                f"  {'   └ 같은 ' + _AXIS_LABELS[key] + ' 코드':<20}"
                f"{_level_pct(ax_ok, ax_all):>10}{ax_all:>10}   "
                f"{_verdict(ax_ok, ax_all, target)}  (판 {axis['builds']}종)"
            )
        return rows

    lines = [
        "",
        "  자비스 자율성 — 지금 어디인가",
        "  " + "─" * 66,
        f"  {'단계':<22}{header:>10}{'표본':>10}   판정",
        "  " + "─" * 66,
        *level("L2 조사 (읽기)", 20, read_ok, read_all, "read", TARGETS["L2"]),
        *level("L3 실행 (쓰기)", 20, write_ok, write_all, "write", TARGETS["L3"]),
        *level("L4 위임 (무개입)", 19, done, jobs, "delegation", TARGETS["L4"]),
        "  " + "─" * 66,
        "",
        f"  에이전트가 실제로 돈 잡   {result['agent_runs']}건 중 위임이 걸린 것 {jobs}건",
        f"     (0~1스텝짜리는 안 센다. 아무것도 안 할수록 점수가 오르면 안 된다)",
        f"  준비 단계(아직 안 바꿈)  {_pct(prep_ok, prep_all):>8}  {prep_all}건 — 성공률에 넣지 않는다",
        f"  사람 문에서 기다린 잡     {result['gate_waits']}건",
        f"  아직 사람 답을 기다리는 잡 {result['still_waiting']}건",
        "",
    ]
    lines.extend(_outcome_lines(result))
    lines.extend(_approval_lines(result))
    # 위의 세 줄이 못 보는 자리. 성공률에 섞지 않고 따로 보여 준다 —
    # 조언·잡담은 도구가 필요 없는 게 맞고, 문제는 **가서 본 척한 것**뿐이다.
    toolless = result.get("toolless", 0)
    suspect = result.get("toolless_sourced", 0)
    if toolless:
        lines.extend(
            [
                f"  도구 없이 답한 대화       {toolless}건 — 위 표의 분모에 안 들어간다",
                (
                    f"     ★ 그중 안 가 보고 출처를 댄 것  {suspect}건"
                    if suspect
                    else "     그중 안 가 보고 출처를 댄 것  0건"
                ),
                "",
            ]
        )
    lines[3:3] = _freshness(result)

    tried, passed = result["tried"], result["passed"]
    # ── 되돌릴 수 있는 쓰기 ───────────────────────────────────────────────────
    #
    # ★ 왜 이 줄이 필요한가 (2026-08-15). L3 성공률 83% 는 **거의 전부 화면 조작**
    # 이었다(338회 중 298회). 되돌릴 수 없는 진짜 커밋은 8회(2.6%)뿐이고, 그중
    # 되돌릴 수 있는 것은 더 적다. 그런데 표에는 그 구별이 한 줄도 없었다.
    #
    # 이 저장소의 자율은 "되돌릴 수 있어서" 얻는 것이라고 적혀 있다. 그렇다면
    # **되돌릴 수 있는 커밋의 비율**이 L3 가 진짜로 오르고 있는지의 신호다.
    # 안 세면 화면 조작이 늘어나는 것만으로 L3 가 오른 것처럼 보인다.
    commits = sum(tried[n] for n in COMMIT_TOOLS if n in tried)
    offers = result.get("undo_offers") or {}
    if commits or offers:
        made = int(offers.get("made") or 0)
        auto = int(offers.get("automatic") or 0)
        used = int(offers.get("undone") or 0)
        lines.append("  되돌릴 수 있는 쓰기")
        lines.append(
            f"    되돌릴 수 없는 커밋 {commits}회 · 돌아갈 길을 남긴 것 {made}회"
            f"(자동 {auto}) · 실제로 되돌린 것 {used}회"
        )
        if commits and not made:
            lines.append("    ← 커밋은 있는데 돌아갈 길이 하나도 없다. InverseSpec 을 안 단 것이다.")
        lines.append("")

    worst = [
        (n, passed[n], tried[n])
        for n in tried
        if n in WRITE_TOOLS and tried[n] >= 3 and passed[n] / tried[n] < 0.8
    ]
    if worst:
        lines.append("  발목을 잡는 쓰기 도구")
        for name, ok, all_ in sorted(worst, key=lambda x: x[1] / x[2]):
            lines.append(f"    {_pct(ok, all_):>7}  {ok}/{all_}  {name}")
        lines.append("")

    known = set(result["read_tools"]) | WRITE_TOOLS | PREPARE_TOOLS | NEUTRAL_TOOLS
    unknown = sorted(n for n in tried if n not in known)
    if unknown:
        lines.append("  분류 안 된 도구 (어느 단계에도 안 세어짐)")
        lines.append("    " + ", ".join(f"{n}({tried[n]})" for n in unknown))
        lines.append("    → 쓰기면 WRITE_TOOLS, 아니면 NEUTRAL_TOOLS 에 넣을 것.")
        lines.append("      조용히 빠지는 게 제일 나쁘다 — 실제로 pick_suggestion 71건이 그랬다.")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="자비스 자율성 측정")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--days", type=int, default=0, help="최근 N일만 (0=전체)")
    parser.add_argument(
        "--build",
        nargs="?",
        const="current",
        default="",
        help="그 판이 낸 실적만 센다. 값 없이 주면 지금 도는 코드",
    )
    args = parser.parse_args()

    # 한국어 윈도우 콘솔은 기본이 cp949 라, 표에 쓰는 '—' 하나에 통째로 죽는다.
    # 이 저장소가 .ps1 한글 리터럴에서 이미 데인 자리다(사고 J).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if not args.db.exists():
        print(f"DB 를 찾을 수 없습니다: {args.db}", file=sys.stderr)
        return 1
    since = time.time() - args.days * 86400 if args.days else 0.0
    now_build = _current_build()
    wanted = now_build if args.build == "current" else args.build
    result = measure(args.db, since, wanted)
    result["now_build"] = now_build
    if not wanted:
        # 판 하나만 보라고 시키지 않았으면 **둘 다** 잰다. 스캔 한 번 더가 전부고,
        # 그 값이 없어서 30일 평균을 "지금"으로 읽는 일이 실제로 일어났다.
        result["current"] = measure(args.db, since, now_build)
        # ★ 축별로도 잰다. 「지금 판만」이 0 건이어도 **그 축의 코드가 안 바뀐
        #   여러 판**을 묶으면 말할 수 있는 표본이 생긴다.
        now_axes = _current_axis_builds()
        by_axis: dict[str, dict] = {}
        for key, axis in _AXIS_OF_LEVEL.items():
            builds = _axis_builds(args.db, axis, now_axes.get(axis, ""))
            if builds:
                by_axis[key] = {
                    "builds": len(builds),
                    "measure": measure(args.db, since, builds),
                }
        result["by_axis"] = by_axis
    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
