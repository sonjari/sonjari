---
id: game/unity-editor-connect
분류: game
제목: 유니티 에디터 열기 · 손자리와 잇기 · 쓴 스크립트 다시 읽히기
찾는말: [에디터 열기, 에디터 안 열림, 연결 안 됨, 잇기, 컴파일, 다시 읽기, 창 클릭, 상태, open unity editor, editor not connected, launch, refresh, recompile, play mode, editor status]
도구: [unity_editor_launch, unity_editor_status, unity_editor_refresh]
맡기기: 직접
필요: [게임 팩 켜기, 프로젝트와 같은 버전의 유니티 설치]
확인일: 2026-11-12
---
## 되는 것
- `unity_editor_status`: 이어진 에디터 · 열린 씬 · 선택 · 재생 중 / 컴파일 중인지.
- `unity_editor_launch`: `connected=false` 면 **사람에게 묻기 전에** 이것. 다리 패키지가 없으면 붙이고(manifest 사본을 남김) 에디터를 **뒤에서** 띄워 이어질 때까지 기다린다. 이미 떠 있는 에디터는 끄지 않는다.
- `unity_editor_refresh`: 손자리가 쓴 `.cs` · 에셋을 창을 누르지 않아도 다시 읽고 컴파일까지. 스크립트를 쓴 뒤 컴포넌트로 붙이기 전에 부른다. 「유니티 창을 클릭해 주세요」라고 하기 전에 이것.

## 안 되는 것 · 알려진 막힘
- 프로젝트와 다른 버전의 유니티로는 열지 않는다. 셸로 유니티를 띄우지 마라.
- 맥: 유니티가 창을 펴는 순간 스스로 맨 앞으로 나온다 → 손자리가 60초 안에 원래 앱을 앞으로 되돌린다(11-11 고침).
- 윈도우에서 앞으로 튀어나오는지는 아직 안 잼.

## 이렇게 맡기세요
```
unity_editor_status {}
unity_editor_launch {"project": "SurvivalWave"}
unity_editor_refresh {}
```

## 끝났는지 보는 법
- `unity_editor_status` 의 `connected: true` · `editor_state` 안의 `is_compiling` 이 false.
- refresh 뒤 `unity_editor_look {"what": "console"}` 에 컴파일 오류가 없다.

## 잰 것
- 2026-11-11 · 맥 판 12개 중 4개가 「에디터가 안 열린다」로 막힘 → 뿌리 셋 고침(다리 패키지를 잘못 뺌 · 잇기 목록 파일 없음 · 여는 도구가 없었음).
- 2026-11-11 · 맥 · 고친 뒤 n=1: 66초 동안 앞 앱(크롬) 그대로.
