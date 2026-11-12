---
id: game/unity-project-overview
분류: game
제목: 유니티 프로젝트 훑어보기(에디터 안 띄우고)
찾는말: [유니티 프로젝트, 프로젝트 정보, 버전, 렌더 파이프라인, 에셋 개수, 패키지, unity project, project info, unity version, URP, HDRP, asset count]
도구: [unity_project_info]
맡기기: 직접
필요: [게임 팩 켜기, 사용자가 허락한 유니티 프로젝트 폴더]
확인일: 2026-11-12
---
## 되는 것
- 에디터를 띄우지 않고 프로젝트를 훑는다: 유니티 버전 · 그 버전이 설치됐나 · 에디터가 지금 열려 있나 · 씬 / 프리팹 / 텍스처 개수 · 렌더 파이프라인 · 큰 에셋 · 패키지.
- 유니티 일을 시작할 때 맨 먼저 부른다. 여기서 「에디터 열림」이면 에디터 도구로, 아니면 레시피로 간다.

## 안 되는 것
- 텍스처 압축 · 참조 같은 **가져오기 설정 안의 값**은 여기서 안 본다 → 점검 레시피(`game/unity-checks`).
- 허락 안 한 폴더는 읽지 않는다.

## 이렇게 맡기세요
```
unity_project_info {}            # 허락한 프로젝트가 하나면 인자 없이
unity_project_info {"project": "SurvivalWave"}
```

## 끝났는지 보는 법
- 결과의 프로젝트 줄마다 `version` · `editor_installed` · `editor_open` · `allowed` 가 있다. `editor_installed: false` 면 사람에게 유니티 허브에서 그 버전을 깔아 달라고 말한다(대신 깔지 않는다).

## 잰 것
- 이 도구만 따로 잰 기록은 아직 없다. 09-27 레시피 시험(FPS Microgame · 파일 24,791개)의 첫 걸음으로 쓰였다.
