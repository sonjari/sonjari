"""위성 자비스 — 손은 자기 것, 두뇌만 빌린다.

## 무엇을 만드는가

나래님 노트북에 자비스 **한 벌**을 깐다. 자기 파일·자기 창·자기 크롬을 그대로
쓰되, 무거운 것만 본체(사용자님 PC)에서 빌린다:

    젬마 추론   JARVIS_OLLAMA_BASE_URL     -> 본체 (VRAM 이 거기 있다)
    음성 합성   JARVIS_SUPERTONIC_BASE_URL -> 본체 (WAV 를 받아 **여기서** 튼다)
    STT        ★ 못 **빌린다**(프로세스 안에서 도는 물건이라). 그런데 그건
               "할 수 없다"가 아니다 — 노트북에 GPU 가 있으면 자기 것으로 한다.
               large-v3-turbo / int8_float16 = 1.5~2GB, 3050 이면 넉넉하다

## ★ 왜 스위치를 역할 하나로 묶는가

위성에서 꺼야 할 것이 넷인데, 사람이 매번 기억하면 **하나씩 빠진다.** 그리고
빠진 쪽은 조용히 틀린다 — 예약 메일이 두 대에서 나가거나, 없는 GPU 로 STT 를
올리려 들거나. 이 저장소가 「설정이 두 곳에 살면 낮은 쪽만 일한다」로 여러 번
겪은 그 모양이다.

그래서 `jarvis_role="satellite"` 하나만 켜면 나머지는 코드가 정한다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.config import JarvisConfig


def _satellite(**kwargs) -> JarvisConfig:
    return JarvisConfig(jarvis_role="satellite", **kwargs)


def test_primary_is_the_default() -> None:
    """아무 말 안 하면 본체다 — 위성은 **명시해야** 된다."""
    assert JarvisConfig().jarvis_role == "primary"


@pytest.mark.parametrize(
    "field",
    [
        # Pocket 3 는 본체에 물려 있다.
        "camera_enabled",
        # WSL 이 없다(있어도 본체 것과 다른 상자다).
        "sandbox_enabled",
    ],
)
def test_satellite_turns_off_what_it_does_not_have(field: str) -> None:
    """**물건이 여기 없는 것**만 끈다. 할 수 있는 것을 끄면 안 된다."""
    assert getattr(_satellite(), field) is False, f"{field} 가 위성에서 안 꺼졌다"


@pytest.mark.parametrize("field", ["voice_enabled", "hotkey_enabled"])
def test_satellite_keeps_its_own_voice(field: str) -> None:
    """★ 처음엔 위성에서 음성을 통째로 껐다. 틀렸다.

    STT 를 본체에서 **못 빌리는** 것은 맞다(faster-whisper 는 HTTP 서비스가 아니다).
    그런데 그건 "할 수 없다"가 아니다 — 노트북에 GPU 가 있으면 자기 것으로 하면
    된다. 그리고 그 GPU 는 STT 전용이 된다(젬마는 본체에 있으니까).

    GPU 가 없으면 `_resolve_device` 가 CPU 로 내리고 **이유를 남긴다.**
    조용히 안 되는 것과, 이유를 알고 느린 것은 다르다.
    """
    assert getattr(_satellite(), field) is True, f"{field} 가 위성에서 꺼졌다"


def test_satellite_points_stt_at_the_first_gpu() -> None:
    """공개 제품과 위성 모두 첫 GPU를 중립 기본값으로 쓴다.

    폴백(`_resolve_device`)이 잡아 주긴 하지만 **처음부터 맞는 값을 주는 편이
    낫다** — 폴백은 안전망이지 설정이 아니다.
    """
    assert JarvisConfig().stt_device_index == 0
    assert _satellite().stt_device_index == 0


def test_satellite_does_not_send_scheduled_mail() -> None:
    """★ 예약이 두 대에서 돌면 메일이 두 번 간다.

    받는 사람은 그게 고장인지 정상인지 모른다 — 그러면 다음부터 안 읽는다.
    예약 메일은 본체만 보낸다.
    """
    assert _satellite(scheduled_mail_recipients=("a@b.com",)).scheduled_mail_recipients == ()


@pytest.mark.parametrize("field", ["browser_enabled", "skills_enabled"])
def test_satellite_keeps_its_own_hands(field: str) -> None:
    """★ 이게 이 설계의 요점이다.

    브라우저는 **나래님 크롬**이고 파일은 **나래님 파일**이다. 이걸 끄면 위성이
    아니라 그냥 창 하나가 된다 — 그럴 거면 본체 화면을 열면 된다.
    """
    assert getattr(_satellite(), field) is True, f"{field} 가 위성에서 꺼졌다"


def test_satellite_reads_its_own_files_not_the_primary_s() -> None:
    """파일 허용 뿌리는 **그 PC 의 사용자 홈**에서 나온다.

    본체 경로를 물려받으면 위성이 없는 폴더를 뒤진다.
    """
    roots = _satellite().local_file_allowed_roots

    assert "Desktop" in roots
    # 하드코딩된 남의 계정이 섞여 있지 않은가.
    assert roots.count("Desktop") == 1


def test_role_is_case_and_space_tolerant() -> None:
    """`.env` 에 손으로 적는 값이다 — 대소문자·공백으로 조용히 안 먹으면 안 된다."""
    assert JarvisConfig(jarvis_role="SATELLITE").camera_enabled is False
    assert JarvisConfig(jarvis_role="Satellite").camera_enabled is False


def test_unknown_role_behaves_like_primary() -> None:
    """오타가 나면 **아무것도 안 끄는 쪽**으로 떨어진다.

    반대로 만들면 오타 하나가 본체의 음성·카메라를 조용히 꺼 버린다.
    """
    config = JarvisConfig(jarvis_role="sattelite")  # 오타

    assert config.camera_enabled is False
    assert config.stt_device_index == 0  # 공개 제품 기본값 그대로
