"""유니티 배치 모드 라이선스 실패를 「결과 파일 없음」 대신 까닭으로 (2026-11-18 · 이 PC 실측 · 맥 성공 로그로 역검증).

11-18 밤 PC: unity_try_script 가 exit 198 · 「no_result_file」 만 돌려줬다 — 로그에는 headless 권한 없음 · 권한 0개.
맥에서 성공한 6판 모두 「Access token is unavailable」 경고를 찍었다 → 그 줄로는 가르지 않는다(헛걸림).
"""
from __future__ import annotations

from alture_jarvis.unity_tools import LICENSE_FIX, license_failure

SUCCESS_MAC = """[Licensing::Module] Error: Access token is unavailable; failed to update
[Licensing::Client] Successfully resolved entitlement details
[Licensing::Client] Successfully updated license, isAsync: True, time: 0.00
"""
FAIL_PC = """[Licensing::Module] LicensingClient has failed validation; ignoring
[Licensing::Module] Error: Access token is unavailable; failed to update
[Licensing::Client] Error: Code 404 while processing request (status: Found 0 entitlement groups and 0 free entitlements matching requested entitlement ids)
[Licensing::Module] Error: 'com.unity.editor.headless' was not found.
Application will exit with return code 198
"""


def test_a_successful_run_warning_is_not_a_license_failure() -> None:
    assert license_failure(SUCCESS_MAC) == []


def test_the_pc_failure_is_named_and_the_fix_is_for_a_person() -> None:
    lines = license_failure(FAIL_PC)
    assert len(lines) == 2 and any("headless" in x for x in lines)
    assert "허브" in LICENSE_FIX and "로그인" in LICENSE_FIX
