"""스토어가 거절한 매니페스트 모양을 다시 만들지 않는다 (2026-10-01 첫 업로드).

1. 「숨은 앱」(AppListEntry="none") — 파트너 센터: "specifies a headless app. You don't have permission" (HeadlessAppBypass 필요).
2. 콘솔 실행 이름은 그 Application 에 SupportsMultipleInstances="true" 가 있어야 한다 — makeappx 0x80080204.
3. 그 makeappx 실패에도 빌드 스크립트가 옛 msix 크기를 찍고 exit 0 으로 끝났다 — 실패는 멈춰야 한다.
4. 영어 화면이 들어간 뒤에도 패키지는 한국어만 신고했다(2026-10-05 전 세계 제출 직전에 봄) — 스토어 「지원 언어」가 한국어뿐으로 뜬다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / "packaging" / "msix" / "AppxManifest.template.xml").read_text(encoding="utf-8")
BUILD = (ROOT / "packaging" / "msix" / "build_app_package.ps1").read_text(encoding="utf-8")


def _without_comments(xml: str) -> str:
    return re.sub(r"<!--.*?-->", "", xml, flags=re.S)


def test_no_headless_application():
    assert 'AppListEntry="none"' not in _without_comments(MANIFEST)


def test_console_alias_lives_on_a_multi_instance_application():
    body = _without_comments(MANIFEST)
    for app in re.findall(r"<Application\b.*?</Application>", body, flags=re.S):
        if 'Subsystem="console"' in app:
            head = app.split(">", 1)[0]
            assert 'SupportsMultipleInstances="true"' in head


def test_the_mcp_alias_is_still_declared():
    body = _without_comments(MANIFEST)
    assert "{{ALIAS}}" in body and 'Executable="backend\\python\\python.exe"' in body


def test_build_stops_when_makeappx_fails_and_never_reports_an_old_package():
    pack = BUILD[BUILD.index("$msix = Join-Path $Stage"):]
    assert "Remove-Item $msix" in pack.split("makeappx pack")[0]
    assert re.search(r"if \(\$packExit -ne 0[^\n]*throw", pack)


def test_the_package_declares_every_language_the_app_ships():
    """앱이 가진 화면 언어(`ui_i18n.LANGS`)를 패키지도 신고한다. 첫 줄(기본 언어)은 한국어 그대로."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from alture_jarvis import ui_i18n

    declared = re.findall(r'<Resource Language="([a-z]{2})-[a-z]{2}" />', _without_comments(MANIFEST))
    assert declared[0] == "ko"
    assert set(declared) == set(ui_i18n.LANGS)
