---
id: game/unity-reference
분류: game
제목: 컴포넌트끼리 잇기 — 인스펙터의 참조 칸 채우기(드래그해서 넣던 칸)
찾는말: [참조, 참조 칸, 잇기, 연결, 드래그해서 넣는 칸, 인스펙터 칸, 카메라가 플레이어 따라가기, 타겟 지정, 머티리얼 넣기, reference, assign, link component, inspector field, SerializeField, drag and drop field, object field]
도구: [unity_editor_change]
맡기기: 직접
필요: [게임 팩 켜기, 열려 있고 이어진 유니티 에디터(game/unity-editor-connect)]
확인일: 2026-11-12
---
## 되는 것
- 「카메라 스크립트의 target 칸에 Player 를 넣어」처럼, 사람이 인스펙터에서 끌어다 넣던 칸을 채운다.
- 장면의 오브젝트는 `{"ref": "오브젝트 이름"}`, 에셋은 `{"ref": "Assets/…"}`. 손자리가 이름을 번호(instanceID)로 바꿔 넘기고, 그 칸이 원하는 컴포넌트 · Transform 을 다리가 꺼낸다.
- 맨 이름 글자만 넣었다가 「property operations failed」가 나면, 장면에 **정확히 그 이름**이 있는 칸만 번호로 바꿔 한 번 더 넣는다(11-12 고침).

## 안 되는 것 · 알려진 막힘
- 이름이 겹치는 오브젝트가 여럿이면 어느 것이 들어갈지 보장하지 않는다 — 이름을 고유하게 하거나 경로를 쓴다.
- 방금 쓴 스크립트의 칸이면 먼저 `unity_editor_refresh`.

## 이렇게 맡기세요
```
unity_editor_change {"op": "modify", "target": "Main Camera",
  "properties": {"CameraFollow": {"target": {"ref": "Player"}}}}
unity_editor_change {"op": "modify", "target": "Zombie",
  "properties": {"MeshRenderer": {"sharedMaterial": {"ref": "Assets/Materials/Zombie.mat"}}}}
```

## 끝났는지 보는 법
- `unity_editor_look {"what": "components", "target": "Main Camera"}` 에서 그 칸이 비어 있지 않고 원하는 이름을 가리킨다.
- 재생해서 보려면 사람에게 Play 를 눌러 달라고 하고 `screenshot`.

## 잰 것
- 2026-11-12 고침(판 b2e846a3) · 맥 · PC 운영 반영. 실기기에서 고친 뒤 성공률은 **아직 안 잼**.
