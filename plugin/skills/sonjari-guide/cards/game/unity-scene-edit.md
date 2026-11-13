---
id: game/unity-scene-edit
분류: game
제목: 열린 에디터에서 오브젝트 만들기 · 바꾸기 · 지우기 · 복제 · 컴포넌트 붙이기 · 씬 저장 · 되돌리기
찾는말: [오브젝트 만들기, 게임오브젝트, 큐브, 프리팹 배치, 컴포넌트 붙이기, 위치, 크기, 회전, 지우기, 복제, 씬 저장, 되돌리기, 실행 취소, create gameobject, add component, transform, delete, duplicate, save scene, undo, prefab instance]
도구: [unity_editor_change, unity_editor_undo]
맡기기: 직접
필요: [게임 팩 켜기, 열려 있고 이어진 유니티 에디터(game/unity-editor-connect)]
확인일: 2026-11-12
---
## 되는 것
- `op`: `create`(기본 도형 `primitive_type` 또는 `prefab_path`) · `modify` · `delete` · `duplicate` · `save_scene`.
- 위치 · 회전 · 크기 · 부모 · 켜고 끄기 · 태그 · 이름 바꾸기 · 컴포넌트 붙이기 / 떼기 · 컴포넌트 값(`properties`).
- **승인 없이 바로** 하고 에디터 Undo 에 남는다(11-11 대표 결정). `unity_editor_undo` 는 손자리가 한 마지막 변경만 되돌린다 — 그 뒤 사람이 한 작업이 맨 위면 건드리지 않는다.
- 사람은 손자리 창에서 유니티 화면을 실시간으로 본다. 바꾸기 전에 무엇을 바꿀지 한 줄로 말하고 부른다.

## 안 되는 것 · 알려진 막힘
- 씬은 저절로 저장하지 않는다. `op=save_scene`(이름 없는 새 씬이면 `name` · `scene_folder` — `path` 를 쓰면 프로젝트로 읽혀 실패).
- 방금 쓴 스크립트를 컴포넌트로 붙이려면 먼저 `unity_editor_refresh` — 안 하면 「컴포넌트 없음」.
- 컴포넌트끼리 잇는 참조 칸은 → `game/unity-reference`.
- 에디터를 닫거나, 묻지 않고 다른 버전으로 열지 않는다.

## 이렇게 맡기세요
```
unity_editor_change {"op": "create", "name": "Zombie", "primitive_type": "Capsule", "position": [0, 1, 5], "components": ["Rigidbody"]}
unity_editor_change {"op": "modify", "target": "Zombie", "properties": {"Rigidbody": {"mass": 2}}}
unity_editor_change {"op": "save_scene", "name": "Wave1"}
unity_editor_undo {}
```

## 끝났는지 보는 법
- `unity_editor_look {"what": "components", "target": "Zombie"}` 로 값을 다시 읽는다. 눈으로 보려면 `screenshot`(game/unity-see-screen).

## 잰 것
- 2026-11-11 · 맥 판 165개 전수조사: 게임 만들기가 막힌 곳은 모델보다 **도구 빈틈**(다시 읽기 · 이름 없는 씬 저장 · 이름 → 번호) — 같은 날 고침. 고친 뒤 성공률은 아직 안 잼.
