# 손자리 HUD (Tauri 데스크톱 창)

로컬에서 도는 손자리용 Tauri 2 데스크톱 HUD다. 평상시에는 우측 하단 원형 오브로 머물고, 긴 답변이나 승인 요청이 생기면 같은 오브가 Aurora Glass 패널로 확장된다.

## 상태 표현

| 백엔드 상태/이벤트 | HUD 표현 |
|---|---|
| `idle` | 천천히 호흡하는 보라색 오브 |
| `listening` | 인디고 수신 링 |
| `transcribing`, `routing`, `working` | 보라·핑크 회전 오로라 |
| `speaking` | 음성 파형 오브 |
| `presentation_ready: voice` | 오브 유지 |
| `presentation_ready: hybrid/screen` | 480×660 답변 패널 |
| `approval_requested` | 주황색 물리 승인 카드 |
| `error` | 붉은 상태 배지 |

## 보안

제어 토큰은 번들 또는 브라우저 저장소에 넣지 않는다. 데스크톱 프로세스가 백엔드 데이터 폴더의 `data\control.token`(소스에서 돌릴 때: `<설치 폴더>\data\control.token`)을 읽어 WebView에 런타임으로만 전달한다. 경로를 바꾸려면 `JARVIS_TOKEN_PATH` 환경 변수를 사용한다.

## 실행

```powershell
npm.cmd install
npm.cmd run test
npm.cmd run build
npm.cmd run tauri:dev
```

백엔드는 기본적으로 `http://127.0.0.1:8091`을 사용한다. 다른 주소는 `JARVIS_URL` 환경 변수로 지정한다.

브라우저 프리뷰에서는 보안상 제어 토큰을 자동으로 읽지 않는다. 화면만 확인할 때는 `npm.cmd run dev`를 사용하고, 실제 PTT·채팅은 Tauri 앱으로 검증한다.

## 런타임 배포와 자동 시작

릴리스 빌드가 끝난 뒤 다음 스크립트를 순서대로 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync_ui_to_runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_ui_autostart.ps1
```

소스에서 돌릴 때 실행 파일은 `<설치 폴더>\ui\alture-jarvis-hud.exe` 다. 같은 앱을 다시 실행하면 새 창을 만들지 않고 기존 오브를 앞으로 가져온다.
