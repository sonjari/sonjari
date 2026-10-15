# MCP for Unity — 손자리 사본

- 원본: https://github.com/CoplayDev/unity-mcp v10.2.0 (커밋 `30d22075093d1d35dfb0091c1c7550e9ad948577`), MIT — `LICENSE` 참고
- 사본 버전: `10.2.0-ontelic.4`. `scripts/vendor_unity_mcp.py` 로 원본에서 다시 만들 수 있다.
- 가져온 것: 유니티 패키지(`MCPForUnity/`)만. 파이썬 서버(`Server/`)와 그 안의 텔레메트리는 가져오지 않았다 —
  손자리가 서버 자리에 서서 유니티가 127.0.0.1 에 여는 소켓에 직접 붙는다.

## 고친 자리 (`OntelicLock` 자물쇠 + 원본 버그 고침)

- Editor/Services/EditorConfigurationCache.cs — 전송 방식: 늘 로컬 소켓(유니티가 127.0.0.1 에서 듣고 손자리가 붙는다). HTTP 모드는 uvx 로 PyPI 에서 서버를 받아 띄운다
- Editor/Services/EditorConfigurationCache.cs — 전송 방식을 HTTP 로 바꾸려는 설정도 로컬 소켓으로 묶는다
- Editor/Services/StartupConfigRewrite.cs — 에디터를 열 때마다 설치된 AI 도구(클로드·코덱스 등)의 설정 파일을 고쳐 쓰는 자동 등록
- Editor/Setup/SetupWindowService.cs — 첫 실행 설치 창 자동 띄우기(창이 앞으로 나온다 + 파이썬·uv 설치 권유)
- Editor/Services/PackageUpdateService.cs — 업데이트 확인(raw.githubusercontent.com)
- Editor/Services/PackageUpdateService.cs — 업데이트 확인(supabase)
- Editor/Services/PackageUpdateService.cs — 업데이트 확인용 웹 클라이언트
- Editor/Setup/SkillSyncService.cs — 스킬 동기화(api.github.com)
- Editor/Setup/RoslynInstaller.cs — Roslyn 설치기(api.nuget.org 에서 받기)
- Editor/Services/AssetGen/Http/UnityWebRequestTransport.cs — 에셋 생성(Meshy·Tripo·Sketchfab·OpenRouter·fal) 요청 — 모든 에셋 생성이 이 한 통로로 나간다
- Editor/Windows/Components/Connection/McpConnectionSection.cs — 원격 서버 로그인 주소 받기
- Editor/Services/Transport/Transports/WebSocketTransportClient.cs — HTTP/웹소켓 전송(원격 서버에 붙을 수 있는 길)
- Editor/Services/ServerManagementService.cs — 파이썬 서버 띄우기(uvx 가 PyPI 에서 받아 실행 — 원본 텔레메트리가 사는 곳)
- Editor/Dependencies/UvInstaller.cs — uv 설치기(인터넷에서 받아 실행)
- Editor/Services/HttpAutoStartHandler.cs — 에디터를 열 때 HTTP 서버 자동 시작
- Editor/Clients/McpClientConfiguratorBase.cs — AI 도구 설정 파일에 원본 서버 등록(클로드·커서·코덱스 등) — 손자리 설정 › 잇기가 대신한다
- Editor/Clients/McpClientConfiguratorBase.cs — (아래 본문 첫 줄에 자물쇠 — 서명이 여러 줄이라 따로 넣는다)
- Editor/Clients/Configurators/OpenClawConfigurator.cs — AI 도구 설정 파일 등록(OpenClaw)
- Editor/Clients/Configurators/OpenCodeConfigurator.cs — AI 도구 설정 파일 등록(OpenCode)
- Runtime/Helpers/UnityObjectIdCompat.cs — 번호(instanceID)로 오브젝트 찾기 — Unity 6.6 에서 원본은 전부 예외(2026-09-27 실측). 손자리 사본이 고친 원본 버그
- Runtime/Helpers/UnityObjectIdCompat.cs — (위 고침이 쓰는 도우미 — EntityId 로 되돌리기, 안 되면 열린 씬 훑기)
- Editor/Tools/GameObjects/GameObjectDelete.cs — 지우기를 되돌릴 수 있게 — 원본은 Object.DestroyImmediate 라 AI 가 지운 것을 Ctrl+Z 로 못 살렸다(원본 주석이 스스로 적음)
- Editor/Services/Transport/TransportCommandDispatcher.cs — 명령 하나 = Undo 한 묶음 — 원본은 입력 이벤트가 없으면 여러 명령이 한 묶음으로 합쳐져 되돌리기 한 번에 둘 다 사라졌다
- Editor/Helpers/TelemetryHelper.cs — 유니티 쪽 텔레메트리(원본도 서버를 거쳐야 나가지만, 사본은 기록 자체를 안 만든다 — 손자리 쪽 「우리 방」이 대신 적는다)

## 남은 것 (알고 둔다)

- 유니티 에디터 **자체**의 통신(라이선스·Unity 서비스)은 이 패키지와 무관하다.
- 사람이 원본 창에서 링크를 누르면 브라우저가 열린다(`Application.OpenURL`) — 사람이 누른 것만.
- 로컬 소켓은 이 PC 의 다른 프로그램도 붙을 수 있다(원본 설계). 손자리는 바꾸는 명령을 승인 카드로 묶지만,
  소켓 자체에 열쇠를 거는 것은 다음 판이다.
