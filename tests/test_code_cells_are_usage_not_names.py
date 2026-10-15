"""표의 코드 칸(`` `--n-cpu-moe N` ``)은 이름이 아니라 **쓰는 법**이다.

★ 2026-09-28 MCP 위임 판 62caf7a9. llama.cpp MoE 옵션 표를 제대로 읽고 만들었는데 「읽지 않고 적은 것이 있습니다: `--override-tensor`,
`--cpu-moe`, `--n-cpu-moeN`, `-ot"exps=CPU"`」가 붙었다. 이름을 뽑을 때 백틱을 이름에 붙이고 자리표시자 N 까지 붙여 어떤 원문에도
없는 이름을 만들었다. 과거 경고 130건 중 7건이 코드 칸에서 나온 것이었다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

ANSWER = """| 옵션 | 뜻 | 예시 |
|---|---|---|
| `--override-tensor (-ot)` | 텐서 수동 할당 | `-ot "exps=CPU"` |
| `--cpu-moe` | 전부 CPU | `--cpu-moe` |
| `--n-cpu-moe N` | 상위 N개 | `--n-cpu-moe 31` |
| `-ot "exps=CPU"` | 전부 CPU | `-ot "exps=CPU"` |"""

READ = 'use --override-tensor or -ot "exps=CPU"; newer builds add --cpu-moe and --n-cpu-moe 31'


def test_options_that_were_read_get_no_warning() -> None:
    assert BrowserAgent._listed_entity_grounding_check(ANSWER, [{"role": "tool", "content": READ}]) == ""


def test_an_option_that_was_not_read_is_still_caught() -> None:
    answer = ANSWER + "\n| `--made-up-flag` | 지어냄 | x |"

    warning = BrowserAgent._listed_entity_grounding_check(answer, [{"role": "tool", "content": READ}])

    assert "--made-up-flag" in warning
    assert "--override-tensor" not in warning
