---
name: sonjari-game
description: 게임 개발(유니티) 일을 손자리(Sonjari) 게임 팩과 같이 하는 법. 사용자가 유니티 프로젝트의 텍스처·프리팹·씬·참조·용량·성능을 묻거나, 열린 유니티 에디터에서 오브젝트를 만들고 바꾸라고 하거나, 반복되는 유니티 점검을 스크립트로 만들어 달라고 할 때 쓴다.
---

# 손자리 게임 팩 — 클로드·코덱스용 사용서

손자리는 사용자 PC 에서 도는 로컬 도우미다. 게임 팩이 켜져 있으면 유니티를 **그 PC 안에서** 다룬다.
나누는 원칙은 하나다: **설계와 코딩은 당신이, 실제 프로젝트에서 돌리고 반복하는 것은 손자리가.**

| 당신(클로드·코덱스) | 손자리 |
|---|---|
| 새 점검·작업을 C# 에디터 스크립트로 설계하고 짠다 | 그 스크립트를 실제 프로젝트에서 돌려 컴파일 오류·결과를 돌려준다 |
| 결과를 해석하고 사람과 다음 일을 정한다 | 등록된 레시피를 **토큰 없이** 매일·커밋마다 돌린다(모델도 안 쓴다) |
| — | 열린 에디터를 사람 화면에 비추고, 승인받아 바꾸고, Undo 로 되돌린다 |

## 1. 유니티 프로젝트에 대한 질문 — 먼저 레시피

1. `unity_list_recipes` 로 맞는 레시피가 있는지 본다(텍스처 점검·빠진 참조·안 쓰는 에셋·씬 무게 등).
2. 있으면 `unity_run_recipe` 로 돌리고, **`result` 의 숫자와 경로만** 사실로 쓴다. `verified: false` 면 그렇다고 말한다.
3. **에셋 파일을 직접 Read·Grep 하지 않는다.** `.unity`·`.prefab`·`.meta` YAML 을 읽어 세는 것은
   - 토큰을 크게 쓰고(씬 하나가 수 MB),
   - 회사 에셋 내용을 대화로 끌어오고,
   - 틀린다 — 텍스처 크기·압축·참조는 유니티 **가져오기 설정** 안에 있어 파일로는 안 보인다.

## 2. 레시피가 없는 새 일 — 당신이 짜고, 손자리가 돌린다

`unity_try_script` 에 C# 전체를 넣는다. 모양:

```csharp
using System; using System.Collections.Generic; using UnityEditor; using UnityEngine;
namespace Sonjari.Recipes {
  public static class FindLargeMeshes {
    [Serializable] public class Args { public string folder = "Assets"; public int min_triangles = 50000; }
    public static void Run() {
      try {
        var a = RecipeIO.ReadArgs<Args>();
        // ... 읽기만 한다 ...
        RecipeIO.Write(new Dictionary<string, object> { { "ok", true }, { "found_total", 0 }, { "items", new List<object>() } });
      } catch (Exception e) { RecipeIO.Fail(e); }
    }
  }
}
```

- `compile_errors`·`failure` 가 오면 고쳐서 **같은 `name`** 으로 다시 부른다(초안을 덮어쓴다).
- 파일·에셋·씬을 바꾸거나 인터넷·외부 프로그램을 쓰는 줄이 있으면 손자리 창의 **승인 카드**가 뜬다. 사람에게 그 창을 보라고 말한다.
- 결과가 맞으면 사람에게: 「손자리 설정 › 팩 › 게임 팩에서 이 초안을 **레시피로 등록**해 주세요.」 등록은 사람만 한다.
- 반복될 일이면 한 줄 더: 「등록한 뒤 **정기 실행**을 켜 두시면 매일 정해진 시각에 모델 없이 돌고, 나빠졌을 때만 알려 드립니다.」
  이것이 이 협업의 요점이다 — 당신이 한 번 설계한 것을 손자리가 공짜로 계속 돌린다.
- 결과에 수치 기준(`found_total`·`*_total` 같은 개수)을 넣어 두면 정기 실행이 그 숫자로 「늘었나」를 판정할 수 있다.

## 3. 열린 에디터 — 보면서 같이 만진다

사람이 에디터로 일하는 중이면 배치 모드 레시피는 못 돈다(`unity_editor_open`). 그때는:

- `unity_editor_status` — 이어진 에디터·열린 씬·선택·재생 중인지.
- `unity_editor_look` — `hierarchy`(계층) · `console`(오류·경고) · `selection` · `find` · `components`.
- `unity_editor_change` — `create`·`modify`·`delete`·`duplicate`. **승인 카드**를 거치고 에디터 Undo 에 남는다.
  씬은 저장하지 않는다. 저장은 `op=save_scene`(따로 승인) 또는 사람이 Ctrl+S.
- `unity_editor_undo` — 손자리가 한 마지막 변경만 되돌린다. 그 뒤에 사람이 한 작업이 있으면 건드리지 않는다.
- 사람은 손자리 창에서 유니티 화면을 실시간으로 보고 있다. 바꾸기 전에 무엇을 바꿀지 한 줄로 말하고 부른다.
- 에디터가 안 이어져 있다고 나오면: 「손자리 설정 › 팩 › 게임 팩에서 이 프로젝트의 『에디터 잇기』를 눌러 주세요.」

## 하지 않는 것

- 에디터를 대신 닫거나, 씬을 묻지 않고 저장하거나, 프로젝트를 다른 유니티 버전으로 열지 않는다.
- `Library/`·`Temp/` 를 읽지 않는다(유니티가 만드는 캐시다).
- 손자리 도구를 부르지 않았으면 「손자리로 확인했다」고 말하지 않는다. 손자리가 꺼져 있으면 그렇다고 말한다.
