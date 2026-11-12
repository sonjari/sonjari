---
id: game/unity-see-screen
분류: game
제목: 열린 에디터 읽기 — 씬 계층 · 콘솔 오류 · 선택 · 이름으로 찾기 · 컴포넌트 값 · 화면 찍어 보기
찾는말: [계층, 하이어라키, 콘솔, 오류, 경고, 선택한 것, 찾기, 컴포넌트 값, 화면 보기, 스크린샷, 게임 화면, 씬 화면, 잘 보이나, hierarchy, console, errors, warnings, selection, find object, components, screenshot, game view, scene view]
도구: [unity_editor_look]
맡기기: 직접
필요: [게임 팩 켜기, 열려 있고 이어진 유니티 에디터(game/unity-editor-connect)]
확인일: 2026-11-12
---
## 되는 것
- 바꾸지 않고 읽기만 한다. `what`:
  - `hierarchy` 씬 계층 · `console` 오류 · 경고 · `selection` 사람이 고른 것 · `find` 이름으로 찾기 · `components` 한 오브젝트의 컴포넌트와 값
  - `screenshot` 게임 화면(기본) 또는 씬 화면(`source: "scene_view"`)을 찍어 **손자리가 직접 보고 `question` 에 답한다** — 만든 것이 잘 보이는지 눈으로 확인할 때.
- Game 탭이 닫혀 있어 게임 화면 파일이 안 생기면 씬 화면으로 대신 찍는다(11-12 고침).

## 안 되는 것 · 알려진 막힘
- 화면 사진은 손자리 창에 비추고 모델이 읽을 뿐, 기록 · 바깥으로 보내지 않는다.
- `Library/` · `Temp/` 는 읽지 않는다(유니티 캐시).

## 이렇게 맡기세요
```
unity_editor_look {"what": "console"}
unity_editor_look {"what": "components", "target": "Player"}
unity_editor_look {"what": "screenshot", "question": "좀비 다섯 마리가 화면에 다 보이나?"}
```

## 끝났는지 보는 법
- console 에 빨간 오류가 0 이면 컴파일은 통과. screenshot 답은 모델의 눈이라 틀릴 수 있다 — 중요한 판정은 `components` 값으로 다시 본다.

## 잰 것
- 2026-11-08 기록: 화면 찍기 성공 68 · 실패 2(6초 기다리기를 넣은 뒤 실패 0).
