"""모델이 그래픽카드 밖으로 새면 빠른 모델(Qwen 3.6 2비트)로 바로 넘긴다 (2026-10-30 대표 결정).

## 왜
16GB 카드에 3ds Max · 유니티 · 게임이 그래픽 메모리를 쥐면 Swift 27B 가 카드 밖(CPU)으로 넘쳐 아주 느려진다.
이 PC 에서 그 모양을 흉내 냈더니(모델 자리 12GB) Swift 27B 작은 판이 카드에 71% · 초당 6.1~6.6토큰이었다(다 올라가면 95).
같은 조건의 Qwen 3.6 2비트는 88% · 초당 116토큰 · 코드 과제 10/12(10-23 밤 · 과제마다 한 판) — 일부가 CPU 로 가도 빠르다(MoE).
대표: 「너무 느리면 못 쓴다 · 새면 바로 대안 모델로 넘기고, 안 깔려 있으면 깔라고 하자」.

## 규칙
- 판 시작, 첫 모델 호출 직전에 **한 번만** 본다(판 도중엔 안 바꾼다 — 다시 올리는 30초 + 쌓인 앞부분을 다시 읽어 더 느려진다).
- 깔려 있으면 **묻지 않고** 바꾼다(10-20 「설정은 대화로 묻는다」의 예외 · 대표 결정). 바꾸기 전 모델은 `data/model_fallback.json` 에 적는다.
- 안 깔려 있으면 지금 모델로 계속하고 「빠른 모델 받기」라고 말하면 받는다고 알린다(12GB 받기는 사람이 말해야 한다).
- **되돌리기는 사람 말로만**(「원래 모델로」). 자동으로 되돌리지 않는다 — 넘침을 알아채는 눈이 진짜 16GB 카드에서 재 본 값이 아니라
  (`gpu_pressure` 머리말) 판마다 왔다 갔다 할 수 있다.
설계: `generated_reports/fix_candidates_1030/설계_넘치면_빠른모델로_1030.md`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from .heavy_apps import SMALL_CARD_GB

#: 넘쳤을 때 넘길 모델(`setup_profile.FAST_PICK_KEY` 와 같은 값 — 마법사의 「무거운 프로그램과 함께」 카드).
FAST_KEY = "qwen3.6-35b-iq2m"
#: 빠른 모델을 올릴 창 — 10-23 밤에 잰 칸(64K · 글만 읽기).
FAST_CTX = 65536
STATE_FILE = "model_fallback.json"

_RESTORE = re.compile(r"^(?:원래\s*(?:모델|대로)(?:로)?(?:\s*(?:돌려|바꿔|돌아가)\S*)?|go\s+back\s+to\s+the\s+(?:usual|original)\s+model)$", re.I)
_PULL = re.compile(r"^(?:빠른\s*모델\s*(?:받기|받아\s*줘|받아줘|깔아\s*줘|깔아줘|설치(?:해\s*줘)?)|download\s+the\s+fast(?:er)?\s+model)$", re.I)


def _plain(text: str) -> str:
    return " ".join(str(text or "").strip().strip(".!?。").split())


def restore_command(text: str) -> bool:
    """「원래 모델로」 — 짧은 명령만. 긴 일 부탁 속 낱말은 가로채지 않는다."""
    value = _plain(text)
    return len(value) <= 30 and bool(_RESTORE.match(value))


def pull_command(text: str) -> bool:
    """「빠른 모델 받기」 — 짧은 명령만."""
    value = _plain(text)
    return len(value) <= 30 and bool(_PULL.match(value))


def spilled(facts: dict[str, Any], warn_below: float) -> bool:
    """넘쳤나 — 카드에 덜 올라갔거나(`gpu_share`) 카드 전체가 가득(`card_full`)."""
    share = facts.get("gpu_share")
    return (isinstance(share, (int, float)) and share < warn_below) or bool(facts.get("card_full"))


def read_state(data_dir: Path | str) -> dict[str, Any]:
    try:
        value = json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 — 없거나 깨졌으면 넘긴 적 없는 것으로 본다
        return {}


def write_state(data_dir: Path | str, state: dict[str, Any] | None) -> None:
    path = Path(data_dir) / STATE_FILE
    if not state:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


class Fallback:
    """런타임이 쥐는 손. `service` 는 `model_setup.SetupService`(바꾸기 · 받기) · `config` 는 지금 모델을 읽는다."""

    def __init__(self, *, service: Any, config: Any, data_dir: Path | str,
                 installed: Callable[[], set[str]], fast_tag: Callable[[], str], is_fast: Callable[[str], bool]) -> None:
        self.service = service
        self.config = config
        self.data_dir = Path(data_dir)
        self._installed = installed
        self._fast_tag = fast_tag
        self._is_fast = is_fast
        self._seen_jobs: set[str] = set()

    def on_spill(self, job_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        """넘친 판의 시작에서 한 번 부른다. {"action": "switched"|"missing"|"none", …}."""
        if job_id in self._seen_jobs:
            return {"action": "none", "why": "already_checked_this_job"}
        self._seen_jobs.add(job_id)
        if len(self._seen_jobs) > 200:
            self._seen_jobs = {job_id}
        current = str(self.config.model_for("chat") or "")
        if self._is_fast(current):
            return {"action": "none", "why": "already_fast"}
        # ★ 큰 카드(16GB 넘음)에서는 넘기지 않는다 — 알리기만 한다 (2026-11-02 대표 승인).
        #   이 장치는 16GB 카드에서 3ds Max · 유니티가 메모리를 쥘 때를 위한 것이다. 24GB 3090 에서 다른 일(시험 크롬 여러 개)이
        #   잠깐 23.62/24GB 를 채우자 저장된 선택을 27B → 3.6 2비트로 **영구히** 바꿨다(판 28168caf · 05:00). 큰 카드에선 27B 가
        #   카드에 넉넉히 들어가니, 잠깐 찬 것으로 사람의 선택을 덮지 않는다. 카드 크기를 모르면 예전대로 넘긴다.
        try:
            total = float(facts.get("card_total_gb") or 0)
        except (TypeError, ValueError):
            total = 0.0
        if total > SMALL_CARD_GB:
            return {"action": "none", "why": "big_card"}
        if self._fast_tag() not in self._installed():
            return {"action": "missing"}
        before = {"tag": current, "num_ctx": int(self.config.num_ctx_for("chat") or 0)}
        try:
            eyes = self.service.current_eyes()
            if isinstance(eyes, dict) and eyes.get("reads_pictures") is not None:
                before["eyes"] = bool(eyes.get("reads_pictures"))
        except Exception:  # noqa: BLE001
            pass
        result = self.service.apply(FAST_KEY, FAST_CTX, eyes=False, accept_spill=True)
        if not result.get("ok"):
            return {"action": "failed", "error": str(result.get("error") or "apply_failed")}
        # 여기까지 왔으면 지금 모델은 빠른 모델이 **아니었다** — 남아 있는 기록은 지난번 것이라 덮어쓴다(2026-11-02).
        #   예전엔 「기록이 없을 때만」 썼다. 10-31 16GB 흉내 시험의 기록(작은 27B iq3xxs)이 남아, 11-02 에 3090 의 진짜 27B 에서
        #   넘겼을 때 「원래 모델로」가 시험용 모델로 돌아갈 뻔했다.
        write_state(self.data_dir, {"from": before, "to": str(result.get("chat_model") or self._fast_tag()),
                                    "job_id": job_id, "at": time.time(), "facts": facts})
        return {"action": "switched", "from": before.get("tag"), "to": result.get("chat_model"),
                "tokens_per_sec": (result.get("verified") or {}).get("tokens_per_sec")}

    def restore(self) -> dict[str, Any]:
        """「원래 모델로」 — 적어 둔 모델로 되돌린다."""
        state = read_state(self.data_dir)
        before = state.get("from") if isinstance(state.get("from"), dict) else None
        if not before or not before.get("tag"):
            return {"ok": False, "error": "nothing_to_restore"}
        result = self.service.apply_tag(str(before["tag"]), int(before.get("num_ctx") or 32768), eyes=before.get("eyes"))
        if result.get("ok"):
            write_state(self.data_dir, None)
        return {**result, "restored_to": before["tag"]}

    def pull_fast(self) -> dict[str, Any]:
        """「빠른 모델 받기」 — 받고 나면 바로 쓰지는 않는다(다음에 넘칠 때 넘긴다). 받는 동안은 지금 모델 그대로."""
        return self.service.start_pull(FAST_KEY)


def switched_line(english: bool) -> str:
    if english:
        return ("Graphics card memory is short, so I switched to the faster model (Qwen 3.6 2-bit) for this job - "
                "say \"go back to the usual model\" to switch back")
    return "그래픽카드가 모자라 빠른 모델(Qwen 3.6 2비트)로 바꿔 진행합니다 — 「원래 모델로」라고 하시면 돌아갑니다"


def missing_line(english: bool) -> str:
    if english:
        return ("Graphics card memory is short, so this model runs slowly. The faster model (Qwen 3.6 2-bit, 12GB) handles this much better - "
                "say \"download the fast model\" to get it. I do not close other programs")
    return ("그래픽카드가 모자라 지금 모델이 느립니다. 빠른 모델(Qwen 3.6 2비트 · 12GB)이 이런 때 훨씬 빠릅니다 — "
            "「빠른 모델 받기」라고 하시면 받습니다. 손자리는 다른 프로그램을 끄지 않습니다")
