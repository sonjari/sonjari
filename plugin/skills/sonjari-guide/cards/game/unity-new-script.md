---
id: game/unity-new-script
분류: game
제목: 클로드가 짠 C# 에디터 스크립트를 실제 프로젝트에서 돌려 보기 → 레시피로 쌓기
찾는말: [새 점검, 스크립트 돌려보기, 에디터 스크립트, C#, 컴파일 오류, 레시피 만들기, 자동화, editor script, try script, compile error, new recipe, batch mode]
도구: [unity_try_script]
맡기기: 직접
필요: [게임 팩 켜기, 프로젝트와 같은 버전의 유니티 설치, 그 프로젝트의 에디터가 닫혀 있을 것(배치 모드)]
확인일: 2026-11-12
---
## 되는 것
- **설계와 코딩은 당신이, 돌리기는 손자리가.** 당신이 짠 C# 를 사용자 PC 의 실제 프로젝트에서 배치 모드로 한 번 돌려 컴파일 오류 · 결과를 돌려준다. 에셋은 PC 밖으로 안 나간다.
- 오류가 오면 고쳐서 **같은 `name`** 으로 다시 부른다(초안을 덮어쓴다).
- 결과가 맞으면 사람이 손자리 설정 › 팩 › 게임 팩에서 **레시피로 등록**한다(등록은 사람만). 등록하면 `game/unity-checks` 처럼 토큰 없이 매일 돈다.

## 안 되는 것 · 알려진 막힘
- 파일 · 에셋 · 씬을 바꾸거나 인터넷 · 외부 프로그램을 쓰는 줄이 있으면 손자리 창에 **승인 카드**가 뜬다 — 사람에게 그 창을 보라고 말한다.
- 열린 에디터 안에서 바로 바꾸는 일은 이것이 아니라 `game/unity-scene-edit`.
- 처음 보는 큰 API(네트워크 라이브러리 등)를 통째로 시키지 말고 단계로 쪼개라(11-09: 통째 47분 실패 → 쪼개고 이름을 적어 주니 8분).

## 이렇게 맡기세요
```csharp
using System; using System.Collections.Generic; using UnityEditor; using UnityEngine;
namespace Sonjari.Recipes {
  public static class FindLargeMeshes {
    [Serializable] public class Args { public string folder = "Assets"; public int min_triangles = 50000; }
    public static void Run() {
      try { var a = RecipeIO.ReadArgs<Args>();
        RecipeIO.Write(new Dictionary<string, object> { { "ok", true }, { "found_total", 0 } });
      } catch (Exception e) { RecipeIO.Fail(e); } } } }
```
`unity_try_script {"name": "find_large_meshes", "title": "큰 메시 찾기", "csharp": "<위 C#>", "params": {"min_triangles": 50000}, "project": "<허락된 프로젝트 폴더>"}`
(`name` · `csharp` · `project` 는 꼭. `params_schema` 를 주면 등록 뒤 사람이 값을 바꿀 수 있다.)
결과에 `*_total` 같은 개수를 넣어 두면 정기 실행이 「늘었나」로 판정한다.

## 끝났는지 보는 법
- `compile_errors` · `failure` 가 비어 있고 결과 JSON 의 `ok` 가 true.
- **끝 판정은 손자리 결과 밖에서** — 결과 숫자를 사람이 아는 정답 하나와 견줘 본다(11-09: 손자리 코드가 찍은 「PASS」만 믿었다가 절반을 안 한 판이 통과).

## 잰 것
- 이 도구만 따로 잰 성공률은 아직 없다.
