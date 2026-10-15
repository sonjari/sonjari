"""MCP for Unity 온텔릭 사본 (2026-09-27) — 밖으로 나가는 길이 **코드에** 없는가.

원본(v10.2.0)은 텔레메트리 말고도 업데이트 확인·스킬 동기화·NuGet 설치기·에셋 생성·원격 로그인·웹소켓 전송·서버 띄우기로
밖에 나갔다. 사본은 그 자리마다 `OntelicLock` 을 건다. 이 시험은 사본을 다시 훑어 **자물쇠 없는 네트워크 코드**가 새로 생기지
않았는지 본다 — 원본을 올릴 때(`scripts/vendor_unity_mcp.py`) 새 통로가 생기면 여기서 걸린다.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "packs" / "game" / "vendor" / "unity-mcp"
PACKAGE = VENDOR / "MCPForUnity"

#: 밖으로 연결할 수 있는 C# 코드.
NETWORK = re.compile(
    r"UnityWebRequest\.(?:Get|Post|Put|Head)\(|new UnityWebRequest\(|new (?:System\.Net\.Http\.)?HttpClient\b|new WebClient\b|"
    r"new ClientWebSocket\b|\.ConnectAsync\(|DownloadString\(|SendWebRequest\("
)
#: 자물쇠 없이 둬도 되는 파일 — **이 PC 안(127.0.0.1)만** 본다. 이유를 적는다.
LOCAL_ONLY = {
    "Editor/Helpers/PortManager.cs": "포트가 비었는지 127.0.0.1 로만 두드려 본다",
}


def _vendor_script():
    spec = importlib.util.spec_from_file_location("vendor_unity_mcp", REPO / "scripts" / "vendor_unity_mcp.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_copy_is_pinned_licensed_and_explained() -> None:
    manifest = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    script = _vendor_script()
    assert manifest["version"] == script.OURS and manifest["version"].startswith(script.UPSTREAM_VERSION + "-ontelic.")
    assert "MIT License" in (VENDOR / "LICENSE").read_text(encoding="utf-8")
    notice = (VENDOR / "NOTICE.ontelic.md").read_text(encoding="utf-8")
    assert script.UPSTREAM_COMMIT in notice and "OntelicLock" in notice


def test_the_python_server_and_its_telemetry_are_not_shipped() -> None:
    assert not (VENDOR / "Server").exists()
    assert not list(VENDOR.rglob("telemetry.py"))
    hits = [p for p in VENDOR.rglob("*") if p.is_file() and p.suffix in {".cs", ".json", ".py", ".md"}
            and "api-prod.coplay.dev" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == [], "원본 텔레메트리 주소가 사본에 남아 있다"


def test_every_network_path_is_locked() -> None:
    open_paths: list[str] = []
    for path in PACKAGE.rglob("*.cs"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
        if not NETWORK.search(code):
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        if relative in LOCAL_ONLY:
            assert "IPAddress.Loopback" in code, f"{relative} 는 127.0.0.1 만 봐야 한다"
            continue
        if "OntelicLock" not in text:
            open_paths.append(relative)
    assert open_paths == [], f"자물쇠 없는 네트워크 코드: {open_paths} — scripts/vendor_unity_mcp.py 의 PATCHES 에 넣어라"


def test_every_patch_is_in_the_copy() -> None:
    script = _vendor_script()
    lock = (PACKAGE / "Editor" / "OntelicLock.cs").read_text(encoding="utf-8")
    assert "public static readonly bool Offline = true;" in lock
    for relative, old, new, why, _count in script.PATCHES:
        text = (PACKAGE / relative).read_text(encoding="utf-8")
        if old == new:  # 서명이 여러 줄인 자리 — 본문 첫 줄에 자물쇠
            assert "AI client registration" in text, why
            continue
        assert new in text, f"{relative}: {why}"


def test_the_bridge_is_local_socket_only_and_quiet_on_open() -> None:
    cache = (PACKAGE / "Editor" / "Services" / "EditorConfigurationCache.cs").read_text(encoding="utf-8")
    assert "_useHttpTransport = !global::MCPForUnity.Editor.OntelicLock.Offline &&" in cache, "HTTP 모드(uvx 로 서버 받기)로 못 간다"
    setup = (PACKAGE / "Editor" / "Setup" / "SetupWindowService.cs").read_text(encoding="utf-8")
    assert "if (global::MCPForUnity.Editor.OntelicLock.Offline) return;" in setup, "첫 실행 설치 창이 앞으로 튀어나오지 않는다"
    rewrite = (PACKAGE / "Editor" / "Services" / "StartupConfigRewrite.cs").read_text(encoding="utf-8")
    assert "OntelicLock.Offline) return;" in rewrite, "클로드·코덱스 설정 파일을 몰래 고치지 않는다"


def test_our_fixes_for_upstream_bugs_stay() -> None:
    ids = (PACKAGE / "Runtime" / "Helpers" / "UnityObjectIdCompat.cs").read_text(encoding="utf-8")
    assert "EntityId.FromULong" in ids and "OntelicResolve" in ids, "6.6 에서 번호로 찾기가 전부 실패했다"
    delete = (PACKAGE / "Editor" / "Tools" / "GameObjects" / "GameObjectDelete.cs").read_text(encoding="utf-8")
    assert "Undo.DestroyObjectImmediate(targetGo)" in delete, "지우기를 되돌릴 수 있어야 한다"
    dispatcher = (PACKAGE / "Editor" / "Services" / "Transport" / "TransportCommandDispatcher.cs").read_text(encoding="utf-8")
    assert dispatcher.count("Undo.IncrementCurrentGroup()") >= 2, "명령 하나 = Undo 한 묶음"
