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
                 installed: Callable[[], set[str]], fast_tag: Callable[[], str], is_fast: Callable[[str], bool],
                 booster: Any = None, tag_of: Callable[[str], str] | None = None,
                 gpu_mode: Callable[[], str] | None = None) -> None:
        self.service = service
        #: 램 부스트 손(`ram_boost.Booster` · 2026-11-11). 없으면(맥 · 시험) 예전과 같다.
        self.booster = booster
        self.config = config
        self.data_dir = Path(data_dir)
        self._installed = installed
        self._fast_tag = fast_tag
        self._is_fast = is_fast
        #: 마법사 키 → Ollama 태그(비트 사다리가 「깔려 있나」를 본다 · 11-11). 없으면 2비트만 안다.
        self._tag_of = tag_of
        #: 사람이 고른 그래픽카드 쓰는 법(`gpu_mode` · 11-11). 없으면 자동.
        self._gpu_mode = gpu_mode or (lambda: "auto")
        self._seen_jobs: set[str] = set()
        self._kept_free: set[str] = set()

    def _boost_key(self, facts: dict[str, Any] | None = None, min_fit_mib: int = 0) -> str:
        """램 부스트로 올릴 3.6 — 깔려 있고 남은 램에 맞고, **그래픽카드에 절반 이상 올라가는** 것 중 좋은 것(4비트)부터.

        11-11 대표: 램 기준 비트 사다리. ★ 11-12 출시 문 시험: 램만 보고 4비트를 고르니 12GB 카드 + 짐에서 20% 만 카드에 올라가
        긴 판의 첫 글자가 5분씩 안 나왔다(가격 과제 시간 제한). 카드 몫(`ram_boost.card_share`)을 같이 본다. 카드를 모르면 2비트.
        사다리 맨 아래(2비트)는 카드 몫과 상관없이 고를 수 있다 — 예전(0.4.44) 동작.
        """
        from .ram_boost import BOOST_LADDER, CARD_SHARE_MIN, card_share

        facts = facts or {}
        card = None
        if facts.get("card_total_gb"):
            card = {"used_gb": facts.get("card_used_gb") or 0, "total_gb": facts.get("card_total_gb")}
        try:
            ours = float(facts.get("model_gb") or 0)
        except (TypeError, ValueError):
            ours = 0.0
        installed = self._installed()
        last = len(BOOST_LADDER) - 1
        for index, key in enumerate(BOOST_LADDER):
            tag = self._tag_of(key) if self._tag_of is not None else (self._fast_tag() if key == FAST_KEY else "")
            if not (tag and tag in installed and self.booster is not None and self.booster.fits(key)):
                continue
            if index < last:
                share = card_share(key, card, ours, min_fit_mib)
                if share is None or share < CARD_SHARE_MIN:
                    continue
            return key
        return FAST_KEY

    def keep_free(self, job_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        """「그래픽카드 비워 두기」를 고른 사람의 판 시작 — 넘치기 **전에** 램 부스트를 건다 (2026-11-11 대표).
        이미 켜져 있으면 다시 안 건다. 램이 모자라면 아무것도 안 한다(그때는 자동과 같다)."""
        from .gpu_mode import KEEP_FREE_GB

        if self._gpu_mode() != "keep_free" or self.booster is None or self.booster.active or job_id in self._kept_free:
            return {"action": "none", "why": "not_keep_free"}
        self._kept_free.add(job_id)
        key = self._boost_key(facts, int(KEEP_FREE_GB * 1024))
        if not self.booster.fits(key):
            return {"action": "none", "why": "ram_short"}
        current = str(self.config.model_for("chat") or "")
        before = {"tag": current, "num_ctx": int(self.config.num_ctx_for("chat") or 0)}
        outcome = self.booster.engage(key, FAST_CTX, facts, job_id=job_id, reason="keep_free",
                                      min_fit_mib=int(KEEP_FREE_GB * 1024))
        if outcome.get("action") == "boosted" and not self._is_fast(current):
            write_state(self.data_dir, {"from": before, "to": str(outcome.get("to") or ""), "job_id": job_id,
                                        "at": time.time(), "facts": facts, "ram_boost": True, "keep_free": True})
        return {**outcome, "from": current}

    def on_spill(self, job_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        """넘친 판의 시작에서 한 번 부른다. {"action": "switched"|"missing"|"none", …}."""
        if job_id in self._seen_jobs:
            return {"action": "none", "why": "already_checked_this_job"}
        # 「속도 우선」을 고른 사람은 넘쳐도 바꾸지 않는다 — 알리기만(경고는 부르는 쪽이 낸다 · 11-11 대표).
        if self._gpu_mode() == "speed":
            return {"action": "none", "why": "speed_mode"}
        self._seen_jobs.add(job_id)
        if len(self._seen_jobs) > 200:
            self._seen_jobs = {job_id}
        current = str(self.config.model_for("chat") or "")
        if self._is_fast(current):
            # ★ 이미 빠른 모델인데도 넘쳤다 = 다른 프로그램이 카드를 쥐었다 → 램 부스트 (2026-11-11 16GB 카드 사용자 PC · 대표 결정).
            #   예전엔 여기서 끝나 「CPU 로 돌고 있습니다」가 뜬 채 사람이 손자리를 껐다 켜야 했다. 이미 켜져 있으면 다시 안 켠다.
            if self.booster is not None and not self.booster.active and self._busy_card(facts):
                outcome = self.booster.engage(self._boost_key(facts), FAST_CTX, facts, job_id=job_id, reason="spill_on_fast")
                if outcome.get("action") == "boosted":
                    return {**outcome, "from": current}
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
        # 카드를 남이 쥐고 있으면 빠른 모델도 통째로는 안 들어간다 — 처음부터 램 부스트로 올린다(램이 모자라면 예전대로).
        if self.booster is not None and self._busy_card(facts):
            boosted = self.booster.engage(self._boost_key(facts), FAST_CTX, facts, job_id=job_id, reason="spill_switch")
            if boosted.get("action") == "boosted":
                write_state(self.data_dir, {"from": before, "to": str(boosted.get("to") or self._fast_tag()),
                                            "job_id": job_id, "at": time.time(), "facts": facts, "ram_boost": True})
                return {**boosted, "from": before.get("tag")}
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

    @staticmethod
    def _busy_card(facts: dict[str, Any]) -> bool:
        """카드를 다른 프로그램이 쥐었나 — 가득 찼거나 · 무거운 프로그램이 켜져 있거나 · 우리 모델이 덜 올라갔거나."""
        share = facts.get("gpu_share")
        return bool(facts.get("card_full") or facts.get("heavy_running")
                    or (isinstance(share, (int, float)) and share < 0.95))

    def restore(self) -> dict[str, Any]:
        """「원래 모델로」 — 적어 둔 모델로 되돌린다. 램 부스트도 끈다(2026-11-11)."""
        released = False
        if self.booster is not None:
            try:
                released = bool(self.booster.release().get("released"))
            except Exception:  # noqa: BLE001 — 부스트를 못 꺼도 모델은 되돌린다
                pass
        state = read_state(self.data_dir)
        before = state.get("from") if isinstance(state.get("from"), dict) else None
        if not before or not before.get("tag"):
            # 이미 빠른 모델에서 부스트만 켰던 판(16GB 카드 사용자 PC 의 경우) — 부스트를 끈 것이 「원래대로」다.
            return {"ok": True, "boost_released": True} if released else {"ok": False, "error": "nothing_to_restore"}
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
