---
id: game/unity-checks
분류: game
제목: 유니티 점검 레시피 — 큰 텍스처 · 빠진 참조 · 안 쓰는 에셋 · 씬 무게(정기 실행 가능)
찾는말: [점검, 검사, 큰 텍스처, 빠진 참조, Missing, 안 쓰는 에셋, 용량, 씬 무게, 최적화, 매일 점검, 레시피, texture audit, missing reference, missing script, unused assets, scene stats, recipe, scheduled check]
도구: [unity_list_recipes, unity_run_recipe]
맡기기: 직접
필요: [게임 팩 켜기, 프로젝트와 같은 버전의 유니티 설치, 그 프로젝트의 에디터가 닫혀 있을 것(배치 모드)]
확인일: 2026-11-12
---
## 되는 것
- 검증된 레시피를 유니티 배치 모드(창 없이)로 돌려 숫자 · 경로를 돌려준다. **모델을 쓰지 않는다** — 토큰 0.
- 지금 레시피 넷: `texture_audit`(최대 크기 · 압축 · Read/Write) · `missing_references`(Missing Script · 빈 참조 칸) · `unused_assets`(씬에서 안 닿는 에셋과 크기) · `scene_stats`(오브젝트 · 삼각형 · 실시간 빛 · 그림자 · 카메라 · 파티클).
- 사람이 손자리 설정에서 **정기 실행**을 켜면 정해 둔 시각에 모델 없이 돌고, 숫자가 나빠졌을 때만 알린다.

## 안 되는 것 · 알려진 막힘
- 그 프로젝트의 에디터가 열려 있으면 배치 모드가 못 돈다(`unity_editor_open`) → 사람에게 닫아 달라 하거나 에디터 도구(`game/unity-see-screen`)로.
- 레시피는 읽기만 한다. 고치는 일은 하지 않는다.
- `.unity` · `.prefab` · `.meta` 를 직접 Read · Grep 하지 마라 — 씬 하나가 수 MB 이고, 가져오기 설정은 파일로 안 보여 틀린다.

## 이렇게 맡기세요
```
unity_list_recipes {}
unity_run_recipe {"recipe": "texture_audit", "params": {"max_size": 2048, "folder": "Assets"}}
unity_run_recipe {"recipe": "missing_references", "params": {"include_scenes": true}}
```
레시피에 없는 점검이면 → `game/unity-new-script`.

## 끝났는지 보는 법
- 결과 `verified: true` 일 때만 숫자를 사실로 쓴다. `false` 면 그렇다고 말한다.
- 답에는 `result` 의 숫자와 경로만 쓴다.

## 잰 것
- 2026-09-27 · FPS Microgame(유니티 6000.6.3f1 · 파일 24,791개) · 「큰 텍스처 찾기」 「빠진 참조 찾기」 두 과제 × 3판:
  고친 뒤 35B 6/6(76~96초) · 9B 6/6(59~113초) · 4B 6/6(60~97초). 정답은 원본 YAML 로 대조. `bench/game_pack/RESULTS_2026-09-27.ko.md`
