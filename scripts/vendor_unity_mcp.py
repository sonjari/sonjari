"""MCP for Unity(CoplayDev, MIT) 유니티 패키지를 게임 팩 안에 **고정 사본**으로 들인다 (2026-09-27, 전략안 §50).

    python scripts/vendor_unity_mcp.py <받은 저장소 폴더>

원본 v10.2.0(커밋 30d22075) 의 `MCPForUnity/` 만 가져온다. 파이썬 서버(`Server/`)는 **안 가져온다** —
온텔릭이 그 서버 자리에 서서 유니티의 로컬 소켓에 직접 붙는다. 원본 텔레메트리(`api-prod.coplay.dev`)는 그 서버에만
있으므로, 서버를 안 들이는 것만으로 그 길이 통째로 없어진다.

유니티 패키지 쪽에도 밖으로 나가는 자리가 더 있었다(업데이트 확인·스킬 동기화·NuGet 설치기·에셋 생성·원격 로그인·
웹소켓 모드·서버 띄우기·클로드/코덱스 설정 파일 자동 수정·첫 실행 설치 창). 그 자리마다 `OntelicLock` 자물쇠를 건다.
패치는 **정확한 원문을 찾아서** 넣는다 — 원문이 바뀌어 못 찾으면 멈춘다(조용히 건너뛰지 않는다).
`tests/test_unity_mcp_vendor.py` 가 결과물을 다시 훑어 자물쇠 없는 네트워크 코드가 없는지 본다.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

UPSTREAM_VERSION = "10.2.0"
UPSTREAM_COMMIT = "30d22075093d1d35dfb0091c1c7550e9ad948577"
OURS = "10.2.0-ontelic.4"
LOCK = "global::MCPForUnity.Editor.OntelicLock"
DEST = Path(__file__).resolve().parents[1] / "packs" / "game" / "vendor" / "unity-mcp"

LOCK_CS = """using System;

namespace MCPForUnity.Editor
{
    /// <summary>
    /// Ontelic build of MCP for Unity: this package never connects outside this PC.
    /// Every outbound path of the upstream package (update check, skill sync, NuGet installer, asset generation,
    /// remote login, WebSocket/HTTP transport, server launch, AI client config rewrite) checks this lock.
    /// Ontelic talks to the editor over the local socket (127.0.0.1) the stdio bridge already opens.
    /// See NOTICE.ontelic.md next to this package.
    /// </summary>
    public static class OntelicLock
    {
        public static readonly bool Offline = true;

        public const string Why =
            "Ontelic build: outbound network, server launch and AI client registration are disabled. " +
            "Connect Claude or Codex from Ontelic settings instead.";

        public static InvalidOperationException Blocked(string what)
        {
            return new InvalidOperationException("ontelic_offline: " + what + " - " + Why);
        }
    }
}
"""

LOCK_META = """fileFormatVersion: 2
guid: 6f1c0a3e9b2d4e7a8c5f0d1b2a3e4f50
MonoImporter:
  externalObjects: {}
  serializedVersion: 2
  defaultReferences: []
  executionOrder: 0
  icon: {instanceID: 0}
  userData:
  assetBundleName:
  assetBundleVariant:
"""

# (파일, 찾을 원문, 바꿀 글, 이 자리가 무엇인가). 원문은 정확히 한 번(또는 count 번) 있어야 한다.
PATCHES: list[tuple[str, str, str, str, int]] = [
    (
        "Editor/Services/EditorConfigurationCache.cs",
        "_useHttpTransport = EditorPrefs.GetBool(EditorPrefKeys.UseHttpTransport, true);",
        f"_useHttpTransport = !{LOCK}.Offline && EditorPrefs.GetBool(EditorPrefKeys.UseHttpTransport, true);",
        "전송 방식: 늘 로컬 소켓(유니티가 127.0.0.1 에서 듣고 온텔릭이 붙는다). HTTP 모드는 uvx 로 PyPI 에서 서버를 받아 띄운다",
        2,
    ),
    (
        "Editor/Services/EditorConfigurationCache.cs",
        "        public void SetUseHttpTransport(bool value)\n        {\n",
        f"        public void SetUseHttpTransport(bool value)\n        {{\n            if ({LOCK}.Offline) value = false;\n",
        "전송 방식을 HTTP 로 바꾸려는 설정도 로컬 소켓으로 묶는다",
        1,
    ),
    (
        "Editor/Services/StartupConfigRewrite.cs",
        "        private static void RunOnce()\n        {\n",
        f"        private static void RunOnce()\n        {{\n            if ({LOCK}.Offline) return;\n",
        "에디터를 열 때마다 설치된 AI 도구(클로드·코덱스 등)의 설정 파일을 고쳐 쓰는 자동 등록",
        1,
    ),
    (
        "Editor/Setup/SetupWindowService.cs",
        "        private static void CheckSetupNeeded()\n        {\n",
        f"        private static void CheckSetupNeeded()\n        {{\n            if ({LOCK}.Offline) return;\n",
        "첫 실행 설치 창 자동 띄우기(창이 앞으로 나온다 + 파이썬·uv 설치 권유)",
        1,
    ),
    (
        "Editor/Services/PackageUpdateService.cs",
        "        protected virtual string FetchLatestVersionFromGitHub(string branch)\n        {\n",
        f"        protected virtual string FetchLatestVersionFromGitHub(string branch)\n        {{\n            if ({LOCK}.Offline) return null;\n",
        "업데이트 확인(raw.githubusercontent.com)",
        1,
    ),
    (
        "Editor/Services/PackageUpdateService.cs",
        "        protected virtual string FetchLatestVersionFromAssetStoreJson()\n        {\n",
        f"        protected virtual string FetchLatestVersionFromAssetStoreJson()\n        {{\n            if ({LOCK}.Offline) return null;\n",
        "업데이트 확인(supabase)",
        1,
    ),
    (
        "Editor/Services/PackageUpdateService.cs",
        "        protected virtual WebClient CreateWebClient()\n        {\n",
        f"        protected virtual WebClient CreateWebClient()\n        {{\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"update check\");\n",
        "업데이트 확인용 웹 클라이언트",
        1,
    ),
    (
        "Editor/Setup/SkillSyncService.cs",
        "        internal static HttpClient CreateGitHubClient()\n        {\n",
        f"        internal static HttpClient CreateGitHubClient()\n        {{\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"skill sync\");\n",
        "스킬 동기화(api.github.com)",
        1,
    ),
    (
        "Editor/Setup/RoslynInstaller.cs",
        "                    using (var request = UnityWebRequest.Get(url))\n",
        f"                    if ({LOCK}.Offline) throw {LOCK}.Blocked(\"NuGet download\");\n                    using (var request = UnityWebRequest.Get(url))\n",
        "Roslyn 설치기(api.nuget.org 에서 받기)",
        1,
    ),
    (
        "Editor/Services/AssetGen/Http/UnityWebRequestTransport.cs",
        "            if (spec == null) throw new ArgumentNullException(nameof(spec));\n",
        f"            if (spec == null) throw new ArgumentNullException(nameof(spec));\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"asset generation request\");\n",
        "에셋 생성(Meshy·Tripo·Sketchfab·OpenRouter·fal) 요청 — 모든 에셋 생성이 이 한 통로로 나간다",
        1,
    ),
    (
        "Editor/Windows/Components/Connection/McpConnectionSection.cs",
        "        private async Task<string> GetLoginUrlAsync()\n        {\n",
        f"        private async Task<string> GetLoginUrlAsync()\n        {{\n            if ({LOCK}.Offline) return null;\n",
        "원격 서버 로그인 주소 받기",
        1,
    ),
    (
        "Editor/Services/Transport/Transports/WebSocketTransportClient.cs",
        "                    await _socket.ConnectAsync(candidate, connectionToken).ConfigureAwait(false);\n",
        f"                    if ({LOCK}.Offline) throw {LOCK}.Blocked(\"WebSocket transport\");\n                    await _socket.ConnectAsync(candidate, connectionToken).ConfigureAwait(false);\n",
        "HTTP/웹소켓 전송(원격 서버에 붙을 수 있는 길)",
        1,
    ),
    (
        "Editor/Services/ServerManagementService.cs",
        "        public bool StartLocalHttpServer(bool quiet = false)\n        {\n",
        f"        public bool StartLocalHttpServer(bool quiet = false)\n        {{\n            if ({LOCK}.Offline) return false;\n",
        "파이썬 서버 띄우기(uvx 가 PyPI 에서 받아 실행 — 원본 텔레메트리가 사는 곳)",
        1,
    ),
    (
        "Editor/Dependencies/UvInstaller.cs",
        "        public static UvInstallResult Run(int timeoutMs = 180000)\n        {\n",
        f"        public static UvInstallResult Run(int timeoutMs = 180000)\n        {{\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"uv installer\");\n",
        "uv 설치기(인터넷에서 받아 실행)",
        1,
    ),
    (
        "Editor/Services/HttpAutoStartHandler.cs",
        "        static HttpAutoStartHandler()\n        {\n",
        f"        static HttpAutoStartHandler()\n        {{\n            if ({LOCK}.Offline) return;\n",
        "에디터를 열 때 HTTP 서버 자동 시작",
        1,
    ),
    (
        "Editor/Clients/McpClientConfiguratorBase.cs",
        "        public override void Configure()\n        {\n",
        f"        public override void Configure()\n        {{\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"AI client registration\");\n",
        "AI 도구 설정 파일에 원본 서버 등록(클로드·커서·코덱스 등) — 온텔릭 설정 › 잇기가 대신한다",
        3,
    ),
    (
        "Editor/Clients/McpClientConfiguratorBase.cs",
        "        public void ConfigureWithCapturedValues(\n",
        "        public void ConfigureWithCapturedValues(\n",
        "(아래 본문 첫 줄에 자물쇠 — 서명이 여러 줄이라 따로 넣는다)",
        1,
    ),
    (
        "Editor/Clients/Configurators/OpenClawConfigurator.cs",
        "        public override void Configure()\n        {\n",
        f"        public override void Configure()\n        {{\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"AI client registration\");\n",
        "AI 도구 설정 파일 등록(OpenClaw)",
        1,
    ),
    (
        "Editor/Clients/Configurators/OpenCodeConfigurator.cs",
        "        public override void Configure()\n        {\n",
        f"        public override void Configure()\n        {{\n            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"AI client registration\");\n",
        "AI 도구 설정 파일 등록(OpenCode)",
        1,
    ),
    (
        "Runtime/Helpers/UnityObjectIdCompat.cs",
        "            return _instanceIdToObject?.Invoke(null, new object[] { instanceId }) as Object;\n",
        "            // Ontelic build: on 6000.6 the reflected InstanceIDToObject(int) throws at runtime, so every lookup by\n"
        "            // instanceID failed (find by_id, get_gameobject, components). Forward mapping is (int)EntityId.ToULong,\n"
        "            // so map back with EntityId.FromULong, then scan open scenes, then try the old path last.\n"
        "            var resolved = OntelicResolve(instanceId);\n"
        "            if (resolved != null) return resolved;\n"
        "            try { return _instanceIdToObject?.Invoke(null, new object[] { instanceId }) as Object; }\n"
        "            catch (System.Exception) { return null; }\n",
        "번호(instanceID)로 오브젝트 찾기 — Unity 6.6 에서 원본은 전부 예외(2026-09-27 실측). 온텔릭 사본이 고친 원본 버그",
        1,
    ),
    (
        "Runtime/Helpers/UnityObjectIdCompat.cs",
        "        public static Object InstanceIDToObjectCompat(int instanceId)\n",
        "#if UNITY_6000_6_OR_NEWER\n"
        "        private static Object OntelicResolve(int instanceId)\n"
        "        {\n"
        "            try\n"
        "            {\n"
        "                var byEntity = EditorUtility.EntityIdToObject(EntityId.FromULong((ulong)(uint)instanceId));\n"
        "                if (byEntity != null) return byEntity;\n"
        "            }\n"
        "            catch (System.Exception) { }\n"
        "            for (int s = 0; s < UnityEngine.SceneManagement.SceneManager.sceneCount; s++)\n"
        "            {\n"
        "                var scene = UnityEngine.SceneManagement.SceneManager.GetSceneAt(s);\n"
        "                if (!scene.isLoaded) continue;\n"
        "                foreach (var root in scene.GetRootGameObjects())\n"
        "                {\n"
        "                    foreach (var t in root.GetComponentsInChildren<Transform>(true))\n"
        "                    {\n"
        "                        if (GetInstanceIDCompat(t.gameObject) == instanceId) return t.gameObject;\n"
        "                        foreach (var c in t.GetComponents<Component>())\n"
        "                        {\n"
        "                            if (c != null && GetInstanceIDCompat(c) == instanceId) return c;\n"
        "                        }\n"
        "                    }\n"
        "                }\n"
        "            }\n"
        "            return null;\n"
        "        }\n"
        "#endif\n\n"
        "        public static Object InstanceIDToObjectCompat(int instanceId)\n",
        "(위 고침이 쓰는 도우미 — EntityId 로 되돌리기, 안 되면 열린 씬 훑기)",
        1,
    ),
    (
        "Editor/Tools/GameObjects/GameObjectDelete.cs",
        "                    Object.DestroyImmediate(targetGo);\n",
        "                    // Ontelic build: deletes must be undoable in the editor a person is using.\n"
        "                    if (global::MCPForUnity.Editor.OntelicLock.Offline) Undo.DestroyObjectImmediate(targetGo);\n"
        "                    else Object.DestroyImmediate(targetGo);\n",
        "지우기를 되돌릴 수 있게 — 원본은 Object.DestroyImmediate 라 AI 가 지운 것을 Ctrl+Z 로 못 살렸다(원본 주석이 스스로 적음)",
        1,
    ),
    (
        "Editor/Services/Transport/TransportCommandDispatcher.cs",
        "                var result = CommandRegistry.ExecuteCommand(command.type, parameters, pending.CompletionSource);\n",
        "                // Ontelic build: give every bridged command its own undo group. Without input events Unity keeps\n"
        "                // one group open, so \"create\" then \"modify\" merged and one Ctrl+Z removed both (2026-09-27).\n"
        "                if (global::MCPForUnity.Editor.OntelicLock.Offline) Undo.IncrementCurrentGroup();\n"
        "                var result = CommandRegistry.ExecuteCommand(command.type, parameters, pending.CompletionSource);\n"
        "                if (global::MCPForUnity.Editor.OntelicLock.Offline) Undo.IncrementCurrentGroup();\n",
        "명령 하나 = Undo 한 묶음 — 원본은 입력 이벤트가 없으면 여러 명령이 한 묶음으로 합쳐져 되돌리기 한 번에 둘 다 사라졌다",
        1,
    ),
    (
        "Editor/Helpers/TelemetryHelper.cs",
        "        public static bool IsEnabled\n        {\n            get\n            {\n",
        f"        public static bool IsEnabled\n        {{\n            get\n            {{\n                if ({LOCK}.Offline) return false;\n",
        "유니티 쪽 텔레메트리(원본도 서버를 거쳐야 나가지만, 사본은 기록 자체를 안 만든다 — 온텔릭 쪽 「우리 방」이 대신 적는다)",
        1,
    ),
]


def _patch_captured_values(text: str) -> str:
    """`ConfigureWithCapturedValues(` 는 서명이 여러 줄이다 — 서명 뒤 첫 `{` 다음 줄에 자물쇠를 넣는다."""
    head = "        public void ConfigureWithCapturedValues(\n"
    start = text.index(head)
    brace = text.index("\n        {\n", start) + len("\n        {\n")
    guard = f"            if ({LOCK}.Offline) throw {LOCK}.Blocked(\"AI client registration\");\n"
    return text[:brace] + guard + text[brace:]


def vendor(source_repo: Path) -> dict[str, object]:
    package = source_repo / "MCPForUnity"
    if not (package / "package.json").is_file():
        raise SystemExit(f"{package} 에 package.json 이 없다 — v{UPSTREAM_VERSION} 저장소를 줘라")
    upstream = json.loads((package / "package.json").read_text(encoding="utf-8"))
    if upstream.get("version") != UPSTREAM_VERSION:
        raise SystemExit(f"버전이 다르다: {upstream.get('version')} (고정 {UPSTREAM_VERSION}) — 패치 원문을 다시 확인하고 올려라")

    target = DEST / "MCPForUnity"
    if target.exists():
        shutil.rmtree(target)
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package, target)
    shutil.copyfile(source_repo / "LICENSE", DEST / "LICENSE")

    applied: list[str] = []
    for relative, old, new, why, count in PATCHES:
        path = target / relative
        text = path.read_text(encoding="utf-8")
        found = text.count(old)
        if found != count:
            raise SystemExit(f"패치 원문을 {count}번 찾아야 하는데 {found}번 — {relative}: {why}")
        if relative.endswith("McpClientConfiguratorBase.cs") and old.startswith("        public void ConfigureWithCapturedValues"):
            text = _patch_captured_values(text)
        else:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        applied.append(f"{relative} — {why}")

    (target / "Editor" / "OntelicLock.cs").write_text(LOCK_CS, encoding="utf-8")
    (target / "Editor" / "OntelicLock.cs.meta").write_text(LOCK_META, encoding="utf-8")

    manifest = dict(upstream)
    manifest["version"] = OURS
    manifest["displayName"] = "MCP for Unity (Sonjari build)"
    manifest["description"] = (
        "MCP for Unity 10.2.0 (CoplayDev, MIT) pinned by Sonjari. Outbound network, telemetry, server launch and "
        "AI client registration are disabled; Sonjari connects over the local socket. See NOTICE.ontelic.md."
    )
    (target / "package.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    notice = [
        "# MCP for Unity — 온텔릭 사본",
        "",
        f"- 원본: https://github.com/CoplayDev/unity-mcp v{UPSTREAM_VERSION} (커밋 `{UPSTREAM_COMMIT}`), MIT — `LICENSE` 참고",
        f"- 사본 버전: `{OURS}`. `scripts/vendor_unity_mcp.py` 로 원본에서 다시 만들 수 있다.",
        "- 가져온 것: 유니티 패키지(`MCPForUnity/`)만. 파이썬 서버(`Server/`)와 그 안의 텔레메트리는 가져오지 않았다 —",
        "  온텔릭이 서버 자리에 서서 유니티가 127.0.0.1 에 여는 소켓에 직접 붙는다.",
        "",
        "## 고친 자리 (`OntelicLock` 자물쇠 + 원본 버그 고침)",
        "",
        *[f"- {line}" for line in applied],
        "",
        "## 남은 것 (알고 둔다)",
        "",
        "- 유니티 에디터 **자체**의 통신(라이선스·Unity 서비스)은 이 패키지와 무관하다.",
        "- 사람이 원본 창에서 링크를 누르면 브라우저가 열린다(`Application.OpenURL`) — 사람이 누른 것만.",
        "- 로컬 소켓은 이 PC 의 다른 프로그램도 붙을 수 있다(원본 설계). 온텔릭은 바꾸는 명령을 승인 카드로 묶지만,",
        "  소켓 자체에 열쇠를 거는 것은 다음 판이다.",
        "",
    ]
    (DEST / "NOTICE.ontelic.md").write_text("\n".join(notice), encoding="utf-8")
    return {"dest": str(target), "patched": len(applied), "files": sum(1 for _ in target.rglob("*") if _.is_file())}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(vendor(Path(sys.argv[1])), ensure_ascii=False, indent=1))
