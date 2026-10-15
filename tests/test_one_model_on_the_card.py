"""★ 3090 에 모델 둘이 같이 사는 일은 **절대** 없어야 한다 (2026-09-20 사장님 지시).

> "무조건 무슨일이있어도 그래픽카드에는(3090에는) 2개의 모델이 공존하게하는거는 절대로하지말자"

## 그날 실제로 있었던 일 (실측)

워치독이 5분마다 **상주 모델만** 찔렀다 — 축출을 막으려고 만든 규칙이다. 그런데 그 프로브가
`keep_alive=24h` 라, 한 번 올라간 젬마의 24시간 임대가 **5분마다 영원히 갱신**됐다.

    [12:37:15] probe: 상주 모델만 찌른다 [plopfit-gemma4-qat] (축출 방지)
    [12:42:14] probe: 상주 모델만 찌른다 [plopfit-gemma4-qat] (축출 방지)
    [12:47:15] probe: 상주 모델만 찌른다 [plopfit-gemma4-qat] (축출 방지)

그래서 설정은 `qwen3.6:35b-a3b` 인데 그 모델은 **한 번도 상주하지 못했다**(`resident: False`).
대화마다 젬마를 밀어내고 71초를 기다렸다. 젬마를 내리고 재 보니:

    3.6 적재 21.7초 · 상주 24.66GB 전부 VRAM(3090 18.7GB + 3060 10.2GB) · 웜 대화 1.5초 · 75.1 tok/s

**고장은 모델이 아니라 자리 다툼이었다.**

## 이 파일이 지키는 것

모델을 올리는 **모든 경로**가 먼저 자리를 비운다. 하나만 빠져도 그 경로에서 그대로 재발한다 —
이 저장소가 「새 도구를 만들었는데 등록 자리 하나를 빠뜨려」 겪은 일과 같은 모양이다.
그래서 손으로 적은 목록이 아니라 **소스를 훑어서** 검사한다(목록은 언젠가 반드시 낡는다).
"""

from __future__ import annotations

from _harvest import WATCHDOG, needs_monorepo_watchdog
import ast
import inspect
from pathlib import Path

import alture_jarvis.ollama as ollama_module
from alture_jarvis.ollama import OllamaClient


def _methods_that_load_a_model() -> dict[str, ast.FunctionDef]:
    """`/api/chat` 이나 `/api/generate` 를 **직접** 부르면서 모델을 올리는 메서드.

    `keep_alive: 0` 만 보내는 것(내리는 호출)은 모델을 올리지 않으므로 뺀다.
    """
    source = Path(inspect.getfile(ollama_module)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    klass = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.ClassDef) and n.name == "OllamaClient")
    out: dict[str, ast.FunctionDef] = {}
    for node in klass.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        body = ast.dump(node)
        if "/api/chat" not in body and "/api/generate" not in body:
            continue
        # 모델을 **올리지 않는** 것은 뺀다:
        #   `_make_room_for`      내리기만 한다(`keep_alive: 0`)
        #   `_wait_out_transient_404`  `/api/ps` 로 보기만 하고 기다린다
        #   `prime_front`         **이미 올라가 있는 우리 모델에만** 보낸다(2026-10-10). 자리를 비우면 안 되는 길이다 —
        #                         남의 모델을 밀어내지 않는 것이 약속이라, 올라가 있지 않으면 아무것도 안 보낸다(아래 시험이 붙든다).
        if node.name in {"_make_room_for", "_wait_out_transient_404", "prime_front"}:
            continue
        out[node.name] = node
    return out


def test_every_path_that_loads_a_model_frees_the_card_first() -> None:
    # `_post_chat` 은 `/api/chat` 의 단일 통로다 — 거기서 비우면 그 아래는 다 덮인다.
    funnel = "_post_chat"
    missing = []
    for name, node in _methods_that_load_a_model().items():
        dumped = ast.dump(node)
        if "_make_room_for" in dumped or (name != funnel and funnel in dumped):
            continue
        missing.append(name)
    assert not missing, (
        "이 메서드들이 모델을 올리면서 자리를 안 비운다 — 3090 에 둘이 같이 올라간다: "
        f"{sorted(missing)}\n"
        "각 메서드 맨 앞에서 `self._make_room_for(<올릴 모델>)` 을 부를 것."
    )


def test_priming_checks_the_model_is_already_there_before_it_sends() -> None:
    """데워 두기는 자리를 비우지 않는 유일한 길이다 — 그 대신 「지금 올라가 있나 · 그 창 그대로인가」를 보고 나서만 보낸다."""
    source = Path(inspect.getfile(ollama_module)).read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "prime_front")
    text = ast.get_source_segment(source, node) or ""
    assert "_front_resident_ctx" in text and "/api/chat" in text
    assert text.index("_front_resident_ctx") < text.index("/api/chat")
    assert "not_resident" in text and "window_differs" in text
    assert "_make_room_for" not in text, "남의 모델을 밀어내면 안 된다"


def test_freeing_the_card_actually_unloads_the_other_model() -> None:
    """내리라고 **말해야** 내려간다. Ollama 는 스스로 축출을 시작조차 안 한다(2026-08-31 실측)."""
    # ★ 검사 하네스가 `_make_room_for` 를 가짜로 덮어 둔다(진짜 GPU 를 내리면 안 되니까).
    #   그러니 **파일에서** 원본을 읽는다 — 속성에서 읽으면 가짜의 소스를 보게 된다.
    room = ast.get_source_segment(
        Path(inspect.getfile(ollama_module)).read_text(encoding="utf-8"),
        next(n for n in ast.walk(ast.parse(
            Path(inspect.getfile(ollama_module)).read_text(encoding="utf-8")))
            if isinstance(n, ast.FunctionDef) and n.name == "_make_room_for"),
    ) or ""
    assert '"keep_alive": 0' in room
    assert "_same_model" in room, "올리려는 그 모델을 내리면 안 된다"


@needs_monorepo_watchdog
def test_the_watchdog_does_not_pin_one_model_forever() -> None:
    """★ 진짜 원인이 있던 자리. 워치독이 젬마를 하드코딩하고 24시간으로 갱신했다.

    고친 뒤에도 누가 「기본값은 젬마」로 되돌리지 못하게 여기서 붙든다.
    """
    script = WATCHDOG
    if not script.is_file():  # 저장소 밖으로 떼어 낸 설치본에는 없다
        import pytest

        pytest.skip(f"워치독 스크립트가 없다: {script}")
    text = script.read_text(encoding="utf-8-sig")
    # ★ **주석은 세지 않는다.** 왜 그랬는지 적어 둔 기록은 지우지 않는 것이 이 저장소의 규칙이고
    #   (§12), 그 기록에도 모델 이름이 나온다. 붙들 것은 **실행되는 줄**이다.
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "plopfit-gemma4-qat" not in code, (
        "워치독이 실행하는 줄에 젬마를 박아 두지 말 것 — 그것이 「강제 의존」이다. "
        "온텔릭 `/health` 가 알려 주는 모델을 쓰고, 못 물어봤으면 아무 모델도 안 찌른다."
    )
    assert "/health" in code, "모델 이름을 어디선가는 **물어봐야** 한다"
