"""판이 바뀌어도 표본이 살아남게 — 축별 지문.

## 무엇이 문제였나

`build_id` 는 패키지의 **모든** `.py` 를 해시한다. 그래서 화면 코드 한 줄만 고쳐도
조사(L2) 표본이 통째로 리셋된다.

실측(2026-08-21): 3일치 잡 128건이 **판 29종**에 흩어져 있었다. 판 하나당 평균 4건.
「지금 판만」 칸이 늘 "표본 부족"이라 **좋아졌는지를 영영 못 재는** 상태였다.

그런데 조사 성능은 `browser.py`·`agent.py` 가 안 바뀐 동안 유효하다. 축이 의존하는
파일만 해시하면 표본이 훨씬 오래 산다.

## ★ 이 파일이 지키는 것

목록이 낡으면 **조용히 틀린다.** 새 파일이 생겼는데 어느 축에도 안 넣으면, 그
파일을 고쳐도 축 지문이 안 바뀌어 **고치기 전과 후가 한 표에 섞인다.**
그게 이 눈금이 처음부터 없애려던 바로 그 병이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import axis_build_ids, axis_files, build_id

_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"

# 어느 축에도 안 들어가는 것이 **정상인** 파일. 도구나 판단을 담지 않는다.
# 여기 넣을 때는 왜 안 넣는지 한 줄 적는다 — 그래야 다음 사람이 판단할 수 있다.
_NOT_AN_AXIS = {
    "__init__.py",
    "__main__.py",
    "config.py",          # 지문을 만드는 쪽. 자기를 세면 순환이다
    # 화면 언어(2026-10-02) — 백엔드 글을 **나가는 순간** 영어로 바꾼다. 판이 하는 일·모델이 받는 말은 그대로다.
    # 영어 화면에서 프롬프트의 「생각 언어」 한 줄을 바꾸는 것은 agent.py(`_voice_and_manner`)에 있어 그쪽 지문이 잡는다.
    "ui_i18n.py",
    # 위성을 새 판으로 갈아치우는 쪽. 조사/쓰기/위임 **어느 것도 아니다** —
    # 자비스가 바깥에 대고 하는 일이 아니라 자기 설치본을 관리하는 일이다.
    # (자기 성적에 영향을 줄 수는 있다. 새 판을 깔면 다음 표본이 그 판 것이 되니까.
    #  그건 `build_id` 가 이미 담는다.)
    "updater.py",
    # 첫 실행 — PC 재기·모델 목록·받기/적용(전략안 §43). `updater.py` 와 같은 설치 쪽이다.
    # 판이 하는 일(조사·쓰기·위임)의 길이 아니라 **어떤 모델로 돌지**를 정한다. 그 결정의
    # 효과는 모델이 바뀐 뒤의 벤치가 잰다 — 이 파일들의 코드가 판 결과를 바꾸지는 않는다.
    "model_catalog.py",
    "setup_profile.py",
    "model_setup.py",
    # 허깅페이스에서 모델·양자화 고르기와 코드 일 추천(2026-10-01 밤) — 어떤 모델로 돌지 고르는 쪽, model_setup 과 같은 자리.
    "hf_catalog.py",
    # 첫 실행 P4 — 다른 도구의 지침 가져오기와 그 비밀 걷어 내기. 설치 쪽이다: 넣고·보이고·
    # 지우기까지만 하고 **아직 어떤 프롬프트에도 안 실린다**(전용 표, 회상·learned_block 밖).
    # 가져온 지침을 대답에 쓰기 시작하는 날 이 판단을 다시 한다 — 그때는 판 결과를 바꾼다.
    "instruction_import.py",
    "secret_scrub.py",
    # 목소리 서버를 켜는 쪽(2026-09-18). 조사·쓰기·위임 어느 것도 아니다 — 말을 만드는 것은 그 서버고,
    # 이 파일은 그 서버가 떠 있게만 한다. 판의 답을 바꾸지 않는다(음성이 없어도 화면 답은 그대로 나간다).
    "tts_server.py",
    # P5 — 다른 도구의 MCP 설정에 자비스를 잇는 설치 쪽. 판이 하는 일을 바꾸지 않는다.
    "mcp_connect.py",
    # H1 (2026-09-16) — 바깥 Claude 가 잡을 넣고 결과를 요약해 받는 문, 그리고 그 사용법 스킬 파일을 만드는 쪽.
    # 잡 안의 걸음(조사·쓰기)은 지금과 같은 에이전트가 돈다 — 이 파일들은 판 결과를 바꾸지 않고 **읽어서 요약**만 한다.
    "delegation.py",
    "guide_skill.py",
    # 그림자 기록(2026-10-09) — 판이 끝난 뒤 사람 요청의 일곱 칸을 낱말 규칙과 모델로 나란히 **읽어서** 적는 것.
    # 판 결과를 바꾸지 않는다(기록만 붙인다) — delegation.py 와 같은 면제 목록에 이유를 함께 적어 둔다.
    "intent_shadow.py",
    # 맡긴 코드 일이 일할 **자리**(git 가지·작업 폴더)를 판 앞에 만들고 판 뒤에 커밋하는 쪽(2026-10-09).
    # 판 안의 걸음과 끝의 판정(확인 명령)은 agent.py · code_runtime.py 에 있다 — 이 파일은 그것을 바꾸지 않는다.
    "delegated_branch.py",
    # DB 를 누가 열 수 있는가 — 판의 결과가 아니라 여는 문이다.
    "store_owner.py",
    # W1·W2 (2026-09-15) — 스토어 패키지·깔리는 제품 쪽. 판이 하는 일(조사·쓰기·위임)을 바꾸지 않는다:
    # 패키지 경로 풀기, 기억 복제 폴더, 첫 실행 표시, Ollama 받기·켜기.
    "msix.py",
    # 만든 파일을 띄우는 자리 하나(2026-10-05). 판이 끝난 **뒤** 무엇으로 열지만 정한다 — 조사·쓰기·위임의 걸음을 안 바꾼다.
    "file_open.py",
    "backup.py",
    "setup_state.py",
    "ollama_install.py",
    # HTTPS 검사를 윈도우에 맡기는 기동 한 줄(2026-09-24). 판단·걸음을 안 바꾸고, 초기화한 PC 에서
    # 인증서로 죽던 받기(Ollama 등)를 살린다 — ollama_install 과 같은 설치 쪽.
    "os_trust.py",
    # 가장 새 C++ 런타임을 먼저 올리는 기동 한 줄(2026-09-24). winrt 의 옛 msvcp140 때문에 음성에서 백엔드가 죽었다.
    "msvc_runtime.py",
    # 기동 때 이 프로세스가 볼 GPU 를 정하는 한 줄(2026-09-28). 판단·걸음을 안 바꾸고, 기동 경로에 따라 음성·비전이
    # 모델 전용 카드로 새던 것을 막는다 — os_trust·msvc_runtime 과 같은 기동 쪽.
    "gpu_policy.py",
    # 스토어 설치에 새 버전이 있다고 **알리기만** 하는 쪽(2026-09-18). 갱신은 윈도우가 한다.
    "store_update.py",
    # 「문제 보내기」(2026-09-29) — 보여 주고 동의받은 진단을 서버로 보내는 쪽. 판이 하는 일(조사·쓰기·위임)을 안 바꾼다.
    "problem_report.py",
    # 상표 정리(2026-09-15) — 제품 이름 상수뿐. 이름을 알아듣는 규칙은 그것을 쓰는 runtime·task_contract 쪽 지문에 잡힌다.
    "brand.py",
    # 누가 API 에 닿을 수 있나. 조사/쓰기/위임이 아니라 **문지기**다.
    "peer_guard.py",
    # 대화에서 사실을 뽑는 쪽. 조사/쓰기/위임이 아니라 **기억**이다.
    "fact_extract.py",
    # 컨텍스트 감시(2026-09-23) — 모델 카드에 붙은 프로그램 목록을 **보기만** 한다(nvidia-smi). 모델을 건드리지 않고
    # 판이 하는 일(조사·쓰기·위임)을 바꾸지 않는다. 상한 재기(`model_setup.py`)와 같은 설치 쪽이다.
    "context_watch.py",
    # 모델 올리기 막대(2026-10-01) — 카드 메모리를 **보기만** 해서 화면에 진행률을 준다. 모델을 올리지도 내리지도 않고
    # 판이 하는 일을 안 바꾼다(context_watch.py 와 같은 자리).
    "load_progress.py",
    "jobs.py",            # 저장소. 실적을 담을 뿐 만들지 않는다
    "sqlite_schema.py",   # DB 에 칸을 더하는 문. 판의 성패를 만들지 않는다
    "events.py",          # 이벤트 버스
    "live_progress.py",   # 진행 이벤트의 최신 값만 들고 있다가 호스트 채팅에 「지금 하는 일」을 보여 준다. 판이 하는 일을 안 바꾼다(events.py 와 같은 자리)
    "api.py",             # HTTP 껍데기
    "models.py",
    "memory.py",          # 대화 기억
    "state_machine.py",
    "transcript.py",
    "presentation.py",    # 표현 방식(음성/화면)
    # 사고 원문을 화면용으로 한국어로 옮기는 쪽. 조사/쓰기/위임이 **아니다** —
    # 모델의 일을 바꾸지 않고 보여 주는 말만 바꾼다. 실패해도 원문이 그대로 남고
    # 판의 결과는 한 글자도 달라지지 않는다. `presentation.py` 와 같은 자리다.
    "thinking_ko.py",
    # 문서를 만드는 손이지 축이 아니다 — local_computer 가 부르는 순수 함수 모음.
    "documents.py",
    "tts.py",
    "voice.py",
    "notifications.py",
    "clock.py",
    "profile.py",
    "media.py",
    "screen_capture.py",
    "vision.py",
    "face_identity.py",
    "osmo_ble.py",
    "android_bridge.py",
    "mcp_server.py",      # 바깥으로 내보내는 문. 도구 자체는 각 모듈에 있다
    # 이 PC 에서 재 보기(2026-10-13) — 손자리에게 과제를 **시키고 채점하는** 쪽이다. 판이 하는 일을 바꾸지 않는다.
    "measure_kit.py",
    "self_care.py",       # 자기 점검. 세 축 중 어디에도 안 속한다
    "shell_probe.py",     # 읽기 전용 셸. 조사 성공률의 분모가 아니다
    "ask_user.py",        # 사람에게 선택지로 묻는 문(2026-09-30). 조사·쓰기·위임 어느 실적도 아니다
    "skills.py",          # 답변 품질 쪽이지 조사·쓰기·위임의 길이 아니다
    "skill_domains.py",   # W4 — 스킬 후보를 분야로 좁힌다. skills.py 와 같은 자리
    "skill_hygiene.py",   # W4 — 스킬 본문의 승인 건너뛰기 문장을 걷는다. skills.py 와 같은 자리
    "settings.py",        # W3 — 설정 화면 값의 저장 층. config.py 와 같은 설치·설정 쪽
    "diagnostics.py",     # W3 — 진단 파일 만들기. 판이 하는 일을 바꾸지 않는다
    "process_census.py",  # 2026-10-14 — 프로세스가 쥔 것을 센다(읽기만). 판이 하는 일을 바꾸지 않는다
    "observations.py",
    "watch.py",
    "ollama.py",
}


def test_every_axis_file_exists() -> None:
    """목록에 적힌 파일이 사라지면 그 축은 조용히 다른 것을 재기 시작한다."""
    missing: list[str] = []
    for axis, names in axis_files().items():
        for name in names:
            if not (_PACKAGE / name).is_file():
                missing.append(f"{axis}/{name}")
    assert not missing, f"축 목록에 있는데 파일이 없다: {missing}"


def test_no_module_is_silently_unclassified() -> None:
    """★ 이 파일에서 가장 중요한 검사.

    새 모듈이 생겼는데 어느 축에도 안 넣고 면제 목록에도 안 적으면 여기서 걸린다.
    **판단을 안 한 채로 지나가는 것**을 막는 자리다.
    """
    in_axes = {name for names in axis_files().values() for name in names}
    on_disk = {p.name for p in _PACKAGE.glob("*.py")}

    unjudged = sorted(on_disk - in_axes - _NOT_AN_AXIS)

    assert not unjudged, (
        "어느 축에도 없고 면제 목록에도 없는 모듈이다 — 이대로면 그 파일을 고쳐도\n"
        "축 지문이 안 바뀌어 고치기 전과 후가 한 표에 섞인다:\n"
        + "\n".join(f"  {name}" for name in unjudged)
        + "\n\n조사/쓰기/위임 중 하나에 넣거나, 왜 아닌지를 _NOT_AN_AXIS 에 적을 것."
    )


def test_axis_digests_are_distinct_from_each_other() -> None:
    """축이 셋인데 지문이 같으면 쪼갠 의미가 없다."""
    axes = axis_build_ids()

    assert set(axes) == {"read", "write", "delegate"}
    assert len(set(axes.values())) == 3, f"축 지문이 겹친다: {axes}"


def test_axis_digest_is_narrower_than_the_whole_build() -> None:
    """전체 지문과 달라야 한다 — 같으면 전체를 해시한 것과 다를 바 없다."""
    whole = build_id()

    assert all(digest != whole for digest in axis_build_ids().values())


@pytest.mark.parametrize(
    ("axis", "must_have"),
    [
        ("read", "browser.py"),
        ("write", "browser.py"),
        ("delegate", "agent.py"),
        ("delegate", "plan.py"),
    ],
)
def test_the_obvious_files_are_in_the_right_axis(axis: str, must_have: str) -> None:
    """축의 핵심 파일이 빠지면 그 축은 안 바뀐 척한다."""
    assert must_have in axis_files()[axis]
