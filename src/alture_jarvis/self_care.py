"""**자비스가 자기 몸을 살핀다** — 그리고 정해진 것만 고친다.

## 왜 (2026-08-20 밤 실측)

사용자 음성이 세 시간 동안 안 나왔다. 원인은 TTS 서버가 죽어 있던 것인데,
**자비스는 그 사실을 아는 채로 아무 말도 안 했다.** 장부에는 `[WinError 10061]`
이 여섯 번 찍혀 있었지만 화면 답은 멀쩡히 나갔고, `_speak_attention` 은 예외를
통째로 삼킨다(`except Exception: pass`). 사용자가 말할 때까지 아무도 몰랐다.

같은 밤에 3090 이 드라이버 사고로 시스템에서 빠졌다. 젬마가 CPU 로 내려가
**130 tok/s → 2.3 tok/s (55배)** 가 됐는데, 이때도 자비스는 "느리네요"조차 안 했다.

이 파일이 메우는 자리가 그것이다. **막힌 것을 스스로 알고 말하는 것**, 그리고
**정해진 것만 고치는 것.**

## 두 갈래로 나눈 이유

    check   읽기만 한다. 되돌릴 것이 없으니 마음껏 부른다
    heal    정해진 버튼만 누른다. **고장일 때만**, 그리고 고친 뒤 다시 잰다

자유로운 터미널을 주지 않는 이유는 이 저장소의 한 문장 때문이다 —
**자율은 더 대담해져서 얻는 게 아니라 되돌릴 수 있어서 얻는다.** `rm -rf` 한 줄은
되돌릴 것이 없다. 그래서 버튼 목록은 코드에 박혀 있고 모델은 이름만 고른다.

## 검사의 규율 (measure-first 스킬 그대로)

**① 생존 검사는 실제 왕복으로.** `/api/tags` 가 즉답해도 추론은 얼어 있을 수 있다.
   그래서 모델 검사는 **토큰을 하나 실제로 생성시킨다.**

**② 「못 봤다」와 「봤는데 정상」을 가른다.** 빈 값 하나가 두 사실을 뜻하면 조용히
   고장난다. 그래서 상태가 셋이다 — `ok` · `down` · `unknown`(검사 자체가 못 돎).

**③ 고친 뒤 다시 읽는다.** 되돌림은 성공을 확인해야 한다 — 조용히 실패한
   `Enable-ScheduledTask` 가 QB 스케줄러를 엿새 죽여 놓은 적이 있다.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable

import httpx

from .config import JarvisConfig
from .events import EventBus
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec


# 기관 하나를 고칠 수 있는 버튼. **모델은 이 이름만 고를 수 있다** — 명령을
# 지어낼 자리가 없다. 오늘 강제 커밋·강제 읽기를 만들 때 쓴 것과 같은 근거다.
#: 사람 화면에 쓰는 부품 이름.
_ORGAN_LABELS: dict[str, str] = {
    "engine": "AI 엔진(Ollama)", "model": "AI 모델", "tts": "음성", "browser": "브라우저",
    "gpu": "그래픽카드", "google": "구글 연결", "silent": "조용한 실패 감시",
}

HEALERS: dict[str, str] = {
    "restart_tts": "tts",
    "reload_model": "model",
    "restart_browser": "browser",
    # 고장난 우리 Ollama 를 끄고 새 자리로 옮겨 켠다(2026-09-18 노트북). 사람이 깐 Ollama 는 안 건드린다.
    "repair_ollama": "engine",
}

# 같은 기관을 이 횟수보다 더 고치지 않는다. 안 고쳐지는 것을 계속 누르면
# 복구가 아니라 폭주다 — 브라우저가 이미 같은 이유로 회로 차단기를 갖고 있다.
HEAL_LIMIT_PER_ORGAN = 2
HEAL_WINDOW_SEC = 15 * 60


def _same_model(left: Any, right: Any) -> bool:
    """`qwen3.6:35b-a3b` 와 `qwen3.6:35b-a3b:latest` 는 같은 모델이다."""
    def norm(value: Any) -> str:
        text = str(value or "").strip().casefold()
        return text[:-7] if text.endswith(":latest") else text
    return bool(norm(left)) and norm(left) == norm(right)


class SelfCare:
    """자기 기관을 살피고(check) 정해진 것만 고친다(heal)."""

    def __init__(
        self,
        config: JarvisConfig,
        events: EventBus,
        *,
        tts: Callable[[], Any] | None = None,
        browser: Callable[[], Any] | None = None,
        google: Callable[[], Any] | None = None,
        installer: Callable[[], Any] | None = None,
    ) -> None:
        """기관은 **부를 때 찾는다**(콜러블).

        ★ 객체를 그대로 받으면 배선 순서에 묶인다. 실제로 그랬다 — 이 도구를
        도구 카탈로그 앞에서 등록해야 하는데 음성 모듈은 그보다 **한참 뒤**에
        만들어진다. 늦게 읽으면 그 순서를 신경 쓸 필요가 없다.
        """
        self.config = config
        self.events = events
        self._tts = tts
        self._browser = browser
        self._google = google
        self._installer = installer
        #: 켤 때 한 번 돈 점검의 결과. 화면이 이것을 읽어 고장일 때만 한 줄 띄운다.
        self.last_boot: dict[str, Any] | None = None
        #: 켤 때 점검이 **지금 도는 중**인가. 화면이 묻는 길은 이것이 잡혀 있으면 겹쳐 돌지 않는다(`boot_check(wait=False)`).
        self._boot_gate = threading.Lock()
        # 기관별 (마지막 치료 시각, 그 창 안에서 몇 번)
        self._healed: dict[str, list[float]] = {}
        self._definitions = self._build_definitions()

    @staticmethod
    def _resolve(getter: Callable[[], Any] | None) -> Any:
        if getter is None:
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001 — 아직 안 만들어졌으면 「못 봤다」로 간다
            return None

    @property
    def tts(self) -> Any:
        return self._resolve(self._tts)

    @property
    def browser(self) -> Any:
        return self._resolve(self._browser)

    @property
    def google(self) -> Any:
        return self._resolve(self._google)

    @property
    def installer(self) -> Any:
        return self._resolve(self._installer)

    # ── 검사 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _organ(name: str, state: str, detail: str, evidence: dict[str, Any], healer: str = "") -> dict[str, Any]:
        return {
            "organ": name,
            # ok = 봤는데 정상 · down = 봤는데 고장 · unknown = **검사 자체가 못 돌았다**
            # 셋을 섞으면 "안 봤다"가 "정상"으로 읽힌다.
            "state": state,
            "detail": detail,
            "evidence": evidence,
            # 이 기관을 고칠 수 있는 버튼 이름. 없으면 사람이 해야 한다.
            "healer": healer if state == "down" else "",
        }

    def _usual_speed(self) -> float | None:
        """**이 PC 에서, 지금 이 모델로** 평소 나오던 속도. 모르면 `None`.

        모델을 적용할 때 `model_setup` 이 그 PC 에서 실제로 재서 적어 둔 값이다. 모델이나 컨텍스트가 그때와 다르면
        견줄 수 없는 값이라 버린다 — 다른 모델의 평소로 지금을 재면 그것이 곧 오탐이다.
        """
        from .model_setup import read_selection

        selection = read_selection(self.config.data_dir) or {}
        if str(selection.get("chat_model") or "") != self.config.ollama_model:
            return None
        if int(selection.get("num_ctx") or 0) != int(self.config.ollama_num_ctx):
            return None
        try:
            value = float((selection.get("verified") or {}).get("tokens_per_sec") or 0)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _check_model(self) -> dict[str, Any]:
        """토큰을 **실제로 만들어 본다.**

        `/api/ps` 가 "VRAM 14.41GB" 라고 답하는 동안 실제로는 CPU 에서 2.3 tok/s
        로 기어가고 있었다(2026-08-20 실측). 상태 API 는 낙관적으로 거짓말한다 —
        믿을 것은 초당 토큰 수다.

        ★ 재는 방법은 모델을 적용할 때와 **같은 함수**(`setup_profile.micro_bench`, 64토큰)다. 전에는 8토큰으로 재서
          워밍업이 섞여 한 판 안에서도 14.98 / 18.20 으로 흔들렸고(2026-09-18 노트북), 무엇보다 평소 값과 견줄 수 없었다.
        """
        from .setup_profile import micro_bench

        base = self.config.ollama_base_url
        data: dict[str, Any] = {}
        try:
            with httpx.Client(timeout=180.0) as client:
                resident = client.get(f"{base}/api/ps").json().get("models") or []

                def _post(url: str, body: dict[str, Any], _timeout: float) -> dict[str, Any]:
                    # 본문을 그대로 쥐고 있는다 — Ollama 가 적어 보낸 「왜 안 되는지」를 버리지 않으려고.
                    reply = client.post(url, json=body)
                    data.update(reply.json() if reply.content else {})
                    return data

                # ★ **떠 있는 러너를 갈아 끼우지 않는다** (2026-09-28 헤르메스 대결 재측정). 켤 때 점검이 설정값 131072 로 재서,
                #   다른 앱(헤르메스)이 쓰던 32K 러너를 백엔드 재기동 1분 뒤마다 128K 로 바꿨다(재기동 직후 첫 판만 그랬던 이유).
                #   우리 모델이 떠 있으면 **그 크기 그대로** 재고, 다른 모델만 떠 있으면(다른 앱이 쓰는 중) 올려서 재지 않는다.
                model = self.config.ollama_model
                # 이름을 모르는 항목은 예전처럼 우리 것으로 본다(모르는 것을 남의 것으로 단정하지 않는다).
                ours = [item for item in resident
                        if not (item.get("name") or item.get("model")) or _same_model(item.get("name") or item.get("model"), model)]
                if resident and not ours:
                    return self._organ(
                        # 재지 않은 것을 「정상」이라 하지 않는다 — 모른다. 화면은 고장(down)만 띄우므로 겁주지도 않는다.
                        "model", "unknown", "다른 모델이 올라가 있어 우리 모델은 재지 않았습니다(쓰는 중인 것을 내리지 않으려고).",
                        {"resident": [item.get("name") or item.get("model") for item in resident]}, "",
                    )
                ctx = int(ours[0].get("context_length") or 0) if ours else 0
                began = time.monotonic()
                micro_bench(base, model, ctx or self.config.ollama_num_ctx,
                            keep_alive=self.config.ollama_keep_alive, post=_post)
                wall = time.monotonic() - began
                # ★ 올라간 자리는 **잰 뒤에** 다시 본다 (2026-09-30 촬영 판). 아무것도 안 떠 있을 때 재면 micro_bench 가
                #   모델을 GPU 에 올리는데, 앞서 받아 둔 빈 목록으로 VRAM 을 세서 0GB → 「CPU 로 돌고 있습니다」가 떴다
                #   (/api/ps 는 그때 14.4GB 전부 VRAM). 앱을 처음 켠 사람이 제일 먼저 보는 틀린 빨간 줄이었다.
                resident = client.get(f"{base}/api/ps").json().get("models") or resident
        except Exception as exc:
            return self._organ(
                "model", "unknown", f"올라마에 닿지 못했습니다: {str(exc)[:120]}", {}, "reload_model"
            )
        if not data:
            # micro_bench 는 요청이 실패하면 예외를 삼키고 돌려준다 — 본문조차 없으면 닿지 못한 것이다.
            return self._organ("model", "unknown", "올라마에 닿지 못했습니다.", {}, "reload_model")

        count = int(data.get("eval_count") or 0)
        nanos = int(data.get("eval_duration") or 0)
        tokens_per_sec = round(count / (nanos / 1e9), 1) if count and nanos else 0.0
        vram = sum(int(item.get("size_vram") or 0) for item in resident)
        usual = self._usual_speed()
        evidence = {
            "tok_per_sec": tokens_per_sec,
            "usual_tok_per_sec": usual,
            "wall_sec": round(wall, 2),
            "vram_gb": round(vram / 1024**3, 2),
            "num_ctx": [item.get("context_length") for item in resident],
        }

        if not count:
            # ★ Ollama 는 **왜 안 되는지를 본문에 적어 보낸다**(2026-09-18 노트북: `llama-server binary not found`).
            #   그 문장을 버리면 「토큰이 안 나왔다」만 남고, 다시 올리기(reload_model)를 헛되이 누르게 된다.
            reason = str(data.get("error") or "")[:300]
            evidence["error"] = reason
            if "llama-server" in reason:
                return self._organ("model", "down", "Ollama 설치가 덜 돼 모델을 못 올립니다 — 엔진을 고쳐야 합니다.",
                                   evidence, "repair_ollama")
            detail = "토큰이 하나도 안 나왔습니다." + (f" ({reason[:160]})" if reason else "")
            return self._organ("model", "down", detail, evidence, "reload_model")
        if vram == 0:
            # ★ 오늘 밤 3090 이 빠졌을 때의 모양이다. GPU 에 한 조각도 안 올라가
            #   있으면 답은 나오지만 쓸 수 없을 만큼 느리다.
            return self._organ(
                "model", "down", "모델이 GPU 에 안 올라가 있습니다(CPU 로 돌고 있습니다).",
                evidence, "reload_model",
            )
        # ★ 속도는 **그 PC 의 평소**와 견준다(2026-09-18). 절대값 30 으로 판정했더니 15~20 이 정상인 노트북을
        #   「너무 느립니다」라고 불렀고, 다시 올려도 그대로라 빨간 줄이 영원히 안 사라졌다. 사람에게는 절대 기준
        #   숫자를 보이지 않는다 — 그 숫자는 다른 PC 의 것이다.
        if usual is not None:
            if tokens_per_sec < usual * self.config.self_check_min_speed_ratio:
                return self._organ(
                    "model", "down",
                    f"평소(적용할 때 {usual:g} tok/s)보다 크게 느립니다 — 지금 {tokens_per_sec:g} tok/s.",
                    evidence, "reload_model",
                )
        elif tokens_per_sec < self.config.self_check_min_tokens_per_sec:
            return self._organ(
                "model", "down",
                f"쓸 수 없을 만큼 느립니다 — 지금 {tokens_per_sec:g} tok/s.",
                evidence, "reload_model",
            )
        return self._organ("model", "ok", f"{tokens_per_sec:g} tok/s", evidence)

    #: 스토어판에서 밖의 프로그램이 읽는 자리 — 앱 전용 칸 안이면 그 프로그램이 못 본다.
    _OUTSIDE_FACING = ("ollama_install_dir", "browser_profile_dir", "sandbox_output_dir", "face_model_dir")

    def _check_engine(self) -> dict[str, Any]:
        """로컬 AI 엔진(Ollama) 설치가 **쓸 수 있는 상태**인가, 그리고 스토어판에서 자리가 맞는가.

        ★ 2026-09-18 노트북: 서버는 켜지고 목록도 답하는데 모델은 하나도 못 올렸다. 다른 기관 검사로는 안 보였다 —
          모델 검사는 「토큰이 안 나왔다」까지만 말했고, 설치가 반쪽이라는 것은 아무도 안 봤다. 뿌리는 **자리**였다
          (스토어판에서 앱 데이터 안에 깔면 패키지 밖 실행 파일인 Ollama 가 자기 파일을 못 본다).
        """
        import os
        from pathlib import Path

        from .msix import package_full_name

        evidence: dict[str, Any] = {}
        if package_full_name():
            local = Path(os.environ.get("LOCALAPPDATA", "") or ".").resolve()
            inside = []
            for name in self._OUTSIDE_FACING:
                value = getattr(self.config, name, None)
                if value and local in Path(value).resolve().parents:
                    inside.append(name)
            evidence["inside_app_private_store"] = inside
            if inside:
                # 사람이 고칠 수 있는 것이 아니다 — 우리 설정 버그다. 고칠 버튼 없이 알린다.
                return self._organ("engine", "down",
                                   "밖의 프로그램이 읽을 자리가 앱 전용 칸 안에 있습니다: " + ", ".join(inside), evidence)
        installer = self.installer
        if installer is None:
            return self._organ("engine", "unknown", "엔진 설치기를 못 찾았습니다.", evidence)
        status = dict(installer.status() or {})
        evidence.update({k: status.get(k) for k in ("running", "version", "install_root", "runner_missing")})
        if status.get("runner_missing"):
            return self._organ("engine", "down", "Ollama 설치가 덜 됐습니다 — 모델을 돌리는 파일을 못 찾습니다.",
                               evidence, "repair_ollama")
        if not status.get("running"):
            return self._organ("engine", "down", "Ollama 가 꺼져 있습니다.", evidence,
                               "repair_ollama" if status.get("bundled") else "")
        return self._organ("engine", "ok", f"Ollama {status.get('version') or ''}".strip(), evidence)

    def _check_tts(self) -> dict[str, Any]:
        if self.tts is None:
            return self._organ("tts", "unknown", "음성 모듈이 연결되어 있지 않습니다.", {})
        health = self.tts.health()
        if not health.get("enabled"):
            return self._organ("tts", "ok", "음성이 꺼져 있습니다(설정).", {"enabled": False})
        if health.get("ok"):
            return self._organ("tts", "ok", "음성 서버가 응답합니다.", {"voice": health.get("voice")})
        return self._organ(
            "tts", "down",
            f"음성 서버가 응답하지 않습니다: {str(health.get('error'))[:120]}",
            {"base_url": self.config.supertonic_base_url}, "restart_tts",
        )

    def _check_browser(self) -> dict[str, Any]:
        if self.browser is None:
            return self._organ("browser", "unknown", "브라우저 모듈이 없습니다.", {})
        try:
            status = self.browser.status()
        except Exception as exc:
            return self._organ("browser", "unknown", f"상태를 못 읽었습니다: {str(exc)[:100]}", {})
        evidence = {
            "started": status.get("started"),
            "stuck": status.get("stuck"),
            "recoveries": status.get("recoveries"),
        }
        if status.get("stuck"):
            return self._organ("browser", "down", "브라우저가 앞 동작에 물려 있습니다.", evidence, "restart_browser")
        if not status.get("enabled", True):
            return self._organ("browser", "ok", "브라우저가 꺼져 있습니다(설정).", evidence)
        # 안 떠 있는 것은 고장이 아니다 — 필요할 때 뜬다.
        return self._organ("browser", "ok", "떠 있습니다." if status.get("started") else "아직 안 띄웠습니다.", evidence)

    def _check_gpu(self) -> dict[str, Any]:
        """★ 오늘 밤 3090 이 빠진 것을 잡는 자리.

        고치는 버튼은 **없다.** 드라이버 재설치는 사람이 해야 하고, 그게 정직하다.
        """
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except Exception as exc:
            return self._organ("gpu", "unknown", f"nvidia-smi 를 못 돌렸습니다: {str(exc)[:100]}", {})
        if out.returncode != 0:
            return self._organ("gpu", "unknown", "nvidia-smi 가 실패했습니다.", {"stderr": out.stderr[:160]})
        cards = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        names = [line.split(",")[1].strip() for line in cards if "," in line]
        evidence = {"count": len(cards), "cards": names}
        if not cards:
            return self._organ("gpu", "down", "그래픽카드가 하나도 안 보입니다.", evidence)
        expected = int(self.config.self_check_expected_gpus)
        if expected and len(cards) < expected:
            return self._organ(
                "gpu", "down",
                f"카드가 {len(cards)}장만 보입니다(있어야 할 것 {expected}장). "
                "장치 관리자에서 오류 31 인지 보세요 — 드라이버 재설치가 필요합니다.",
                evidence,
            )
        return self._organ("gpu", "ok", " · ".join(names), evidence)

    def _check_google(self) -> dict[str, Any]:
        if self.google is None:
            return self._organ("google", "unknown", "구글 모듈이 없습니다.", {})
        try:
            # ★ **`verify=True` 여야 한다.** 안 그러면 `granted_scopes` 가 늘 비어
            #   있고, 그 빈 값은 「끊겼다」가 아니라 「안 물어봤다」는 뜻이다.
            #   실측(2026-08-21): verify 없이 granted 0·email '' / verify=True 로
            #   granted 10·email 있음. 처음 이 검사를 붙였을 때 멀쩡한 연결을
            #   「끊어졌다」고 말했다 — 빈 값 하나가 두 사실을 뜻하던 그 함정이다.
            status = self.google.status(verify=True)
        except Exception as exc:
            return self._organ("google", "unknown", f"상태를 못 읽었습니다: {str(exc)[:100]}", {})
        if not status.get("enabled"):
            return self._organ("google", "ok", "구글 연동이 꺼져 있습니다(설정).", {"enabled": False})
        granted = list(status.get("granted_scopes") or [])
        evidence = {"email": status.get("email"), "granted": len(granted)}
        if not status.get("connected") or not granted:
            # 고치는 버튼이 없다 — 재승인은 브라우저에서 사람이 눌러야 한다.
            return self._organ("google", "down", "구글 연결이 끊어졌습니다. 재승인이 필요합니다.", evidence)
        if status.get("scope_mismatch"):
            return self._organ("google", "down", "허락받은 권한이 모자랍니다. 재승인이 필요합니다.", evidence)
        return self._organ("google", "ok", f"{status.get('email')} · 권한 {len(granted)}개", evidence)

    def _check_silent(self) -> dict[str, Any]:
        """★ **성공했다는데 산출물이 빈** 자리를 찾는다 (2026-08-23 신설).

        오늘 하루에 조용한 실패를 넷 밟았는데 전부 같은 모양이었다:

            빈 메일    `gmail_send ok=True` · 본문 0자 — 이틀간 아무도 몰랐다
            축출       워치독 프로브는 성공 · 그런데 자비스 모델을 GPU 에서 밀어냄
            위성       정상 동작 · 그런데 본체를 느리게 만듦(표시 0)
            창작       답이 나옴 · 그런데 도구 0걸음

        **어느 층도 에러를 안 냈다.** 그래서 "실패를 잡는" 검사로는 안 잡힌다.
        잡는 방법은 반대쪽이다 — **성공 기록을 열어 산출물이 비었는지 본다.**

        ★ 이게 상업화의 최소 조건이다. 사용자 환경에서는 사용자가 눈치챈다.
          고객 자리에서는 **아무도 로그를 안 본다.**
        """
        import json as _json
        import sqlite3 as _sqlite3
        import time as _time

        db_path = self.config.data_dir / "jarvis.db"
        if not db_path.exists():
            return self._organ("silent", "unknown", "장부를 못 찾았습니다.", {})
        since = _time.time() - 24 * 3600
        findings: list[str] = []
        evidence: dict[str, Any] = {}
        try:
            conn = _sqlite3.connect(str(db_path))
            try:
                # ① 빈 채로 나간 커밋. 보냈다는데 내용이 없다.
                empty_sent = 0
                for (payload,) in conn.execute(
                    "select payload_json from external_actions "
                    "where status='committed' and created_at > ?",
                    (since,),
                ):
                    try:
                        body = _json.loads(payload or "{}")
                    except Exception:  # noqa: BLE001 — 못 읽는 줄은 세지 않는다
                        continue
                    if not any(
                        str(body.get(key) or "").strip()
                        for key in ("body_text", "body_html", "summary", "description", "content")
                    ):
                        empty_sent += 1
                evidence["빈_커밋"] = empty_sent
                if empty_sent:
                    findings.append(f"내용이 빈 채로 나간 것 {empty_sent}건")

                # ② 도구를 하나도 안 쓰고 길게 답한 판 = 창작 의심.
                fabricated = 0
                for (result,) in conn.execute(
                    "select result_json from jobs where status='completed' and created_at > ?",
                    (since,),
                ):
                    try:
                        data = _json.loads(result or "{}")
                    except Exception:  # noqa: BLE001
                        continue
                    steps = ((data.get("agent_trace") or {}).get("steps")) or []
                    answer = str(data.get("answer") or "")
                    # 짧은 답(인사·확인)은 도구가 없어도 정상이다. 긴 답만 센다.
                    if not steps and len(answer) > 400:
                        fabricated += 1
                evidence["도구없이_긴답"] = fabricated
                if fabricated:
                    findings.append(f"도구 없이 길게 답한 판 {fabricated}건(창작 의심)")
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            return self._organ("silent", "unknown", f"장부를 못 읽었습니다: {str(exc)[:100]}", {})

        # ③ 축출 — 자비스가 쓰려는 모델과 지금 GPU 에 올라온 것이 다른가.
        try:
            import urllib.request as _url

            with _url.urlopen(f"{self.config.ollama_base_url}/api/ps", timeout=5) as resp:
                loaded = [m.get("name", "") for m in (_json.loads(resp.read()).get("models") or [])]
            want = str(self.config.ollama_model or "")
            # ★ 우리 역할 모델은 전부 정당한 상주다. Code 잡이 도는 동안에는
            # 코더가 3090 을 차지하는 것이 **의도된 동작**이다(축출을 막으려고
            # 잡 전체를 코더로 묶는다). 채팅 모델만 정답으로 보면 코딩할 때마다
            # 이 기관이 「남의 모델이 차지했다」고 매일 아침 거짓 경보를 낸다.
            ours = {
                str(value).split(":")[0]
                for value in (self.config.model_roles or {}).values()
                if str(value or "").strip()
            }
            ours.add(want.split(":")[0])
            # ★ **정찰기도 우리 모델이다** (2026-09-09).
            #
            #   `model_roles` 만 보면 `code_scout_model` 이 빠진다. 정찰기가 3060 에
            #   올라와 있는 것은 정상인데 이 기관은 「남의 모델이 GPU 를 차지했다」고
            #   말한다. 등급별 벤치로 채팅 모델을 정찰기와 같은 것으로 바꿔 보다가
            #   드러났다 — 그 전에는 두 모델 이름이 우연히 달라 안 보였다.
            #
            #   새 모델 자리를 만들 때마다 **여기도 같이 넣어야** 한다는 뜻이고,
            #   그래서 이름을 하나하나 적지 않고 config 에서 걷는다.
            #   `vision_model` 은 Ollama 모델이 아니라 가중치 파일(`yolo26n.pt`)이라
            #   여기 넣지 않는다 — GPU 상주 목록과 같은 이름 공간이 아니다.
            scout = str(getattr(self.config, "code_scout_model", "") or "").strip()
            if scout:
                ours.add(scout.split(":")[0])
            ours.discard("")
            evidence["상주"] = loaded
            evidence["원하는_모델"] = want
            evidence["우리_모델"] = sorted(ours)
            foreign = [
                name
                for name in loaded
                if not any(stem and stem in name for stem in ours)
            ]
            if foreign:
                findings.append(
                    f"우리 것이 아닌 모델이 GPU 를 차지함({foreign[0]}) — Sonjari 역할 모델: {sorted(ours)}"
                )
        except Exception:  # noqa: BLE001 — 올라마가 조용해도 model 기관이 따로 본다
            pass

        if findings:
            return self._organ("silent", "down", " · ".join(findings), evidence)
        return self._organ("silent", "ok", "지난 24시간에 조용한 실패 없음.", evidence)

    _PROBES: dict[str, str] = {
        "engine": "_check_engine",
        "model": "_check_model",
        "tts": "_check_tts",
        "browser": "_check_browser",
        "gpu": "_check_gpu",
        "google": "_check_google",
        # ★ 다른 다섯이 "이 부품이 살아 있나"를 본다면, 이건 "살아서 헛일을 하고
        #   있지 않나"를 본다. 오늘 밟은 실패는 전부 후자였다.
        "silent": "_check_silent",
    }

    def check(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        wanted = str(arguments.get("organ") or "").strip().lower()
        names = [wanted] if wanted in self._PROBES else list(self._PROBES)
        if wanted and wanted not in self._PROBES:
            raise ValueError(f"unknown_organ:{wanted} — {', '.join(self._PROBES)} 중에서 고르세요")

        organs = []
        for name in names:
            try:
                organs.append(getattr(self, self._PROBES[name])())
            except Exception as exc:  # noqa: BLE001 — 한 기관이 죽어도 나머지는 본다
                organs.append(self._organ(name, "unknown", f"검사가 실패했습니다: {str(exc)[:120]}", {}))

        down = [item for item in organs if item["state"] == "down"]
        unknown = [item for item in organs if item["state"] == "unknown"]
        result = {
            "action": "self_check",
            "checked": len(organs),
            "organs": organs,
            # 요약을 따로 준다 — 목록만 주면 모델이 "전부 정상입니다"로 뭉갠다.
            "down": [item["organ"] for item in down],
            "unknown": [item["organ"] for item in unknown],
            "healable": sorted({item["healer"] for item in down if item["healer"]}),
            "healthy": not down,
        }
        self.events.publish("self_check", {"down": result["down"], "unknown": result["unknown"]})
        return result

    def boot_check(self, *, include_model: bool = True, wait: bool = True) -> dict[str, Any]:
        """켤 때 한 번 — **엔진과 모델만** 본다. 고장이면 화면이 한 줄 띄운다.

        ★ 2026-09-18: 이 검사들은 사람이 「너 괜찮아?」라고 물을 때만 돌았다. 노트북은 서버는 켜지고 목록은 답하는
          채로 모델을 하나도 못 올리는 상태였는데, 사람이 모델을 적용해 보기 전까지 아무도 몰랐다.
          브라우저·구글·음성은 켤 때 안 본다(느리고, 켜자마자 고장인 경우가 드물다). 모델은 첫 설정이 끝났을 때만.

        ★ 2026-10-07: **겹쳐 돌지 않는다.** 모델 검사는 멈춘 실행기 앞에서 180초까지 묶인다. 화면은 15초마다 묻고,
          결과(`last_boot`)는 검사가 끝나야 바뀐다 — 그 사이의 물음이 전부 같은 검사에 다시 들어가 요청 일꾼을 하나씩 잡았다
          (창 하나에 최대 12개 · 6GB 노트북 첫 실행에서 「시작하기」가 안 먹은 판의 후보 가운데 하나, 원인으로 확인된 것은 아니다).
          `wait=False` 면 이미 도는 검사가 있을 때 기다리지 않고 **지난 결과**(없으면 `{"pending": True}`)를 돌려준다.
          켤 때의 한 번과 「고치기」 뒤의 다시 보기는 결과가 필요하므로 기다린다(`wait=True`).
        """
        gate = self.__dict__.setdefault("_boot_gate", threading.Lock())
        if not gate.acquire(blocking=wait):
            return self.last_boot or {"pending": True}
        try:
            organs = [self._safe_probe("engine")]
            if include_model:
                organs.append(self._safe_probe("model"))
            down = [item for item in organs if item["state"] == "down"]
            result = {
                "at": time.time(),
                "organs": organs,
                "down": [item["organ"] for item in down],
                "healable": sorted({item["healer"] for item in down if item["healer"]}),
                "healthy": not down,
            }
            self.last_boot = result
            self.events.publish("self_check_boot", {"down": result["down"], "healable": result["healable"]})
            return result
        finally:
            gate.release()

    def _safe_probe(self, name: str) -> dict[str, Any]:
        try:
            return getattr(self, self._PROBES[name])()
        except Exception as exc:  # noqa: BLE001 — 한 기관이 죽어도 나머지는 본다
            return self._organ(name, "unknown", f"검사가 실패했습니다: {str(exc)[:120]}", {})

    # ── 치료 ─────────────────────────────────────────────────────────────

    def _too_often(self, organ: str) -> bool:
        now = time.time()
        recent = [at for at in self._healed.get(organ, []) if now - at < HEAL_WINDOW_SEC]
        self._healed[organ] = recent
        return len(recent) >= HEAL_LIMIT_PER_ORGAN

    def _restart_tts(self) -> dict[str, Any]:
        """음성 서버를 다시 켠다.

        ★ 켜는 길이 둘이다 (2026-09-18). 이 PC 는 작업 스케줄러가 켜지만, **포장본(스토어판)에는 그 작업이
          없다** — 아버님 노트북 진단에 `[WinError 10061]` 만 찍혀 있던 이유다. 스케줄러가 실패하면
          우리가 직접 띄운다(`tts_server.ensure`). 길이 하나뿐이면 다른 판에서는 고칠 방법이 없다.
        """
        from . import tts_server

        out = subprocess.run(
            ["schtasks", "/Run", "/TN", self.config.supertonic_task_name],
            capture_output=True, text=True, timeout=60, check=False,
        )
        result: dict[str, Any] = {"returncode": out.returncode, "stdout": out.stdout[:200].strip()}
        if out.returncode == 0:
            time.sleep(6)
            if tts_server.answering(self.config.supertonic_base_url):
                return result
        # 스케줄러가 없거나(포장본) 켰는데도 안 답하면 **우리가 띄운다.**
        result["bundled_start"] = tts_server.ensure(self.config.supertonic_base_url)
        return result

    def _reload_model(self) -> dict[str, Any]:
        """젬마를 **자비스가 쓰는 창 크기 그대로** 다시 올린다.

        ★ 다른 `num_ctx` 로 부르면 러너가 쫓겨나고, 자비스는 그 작은 창을 그대로
        받아 쓴다(8분의 1). 2026-08-20 밤에 내가 두 번 밟은 함정이라 여기서는
        설정값을 그대로 넘긴다.
        """
        with httpx.Client(timeout=300.0) as client:
            body = {
                "model": self.config.ollama_model,
                "prompt": "1",
                "stream": False,
                "think": False,
                "keep_alive": self.config.ollama_keep_alive,
                "options": {"num_predict": 1, "num_ctx": self.config.ollama_num_ctx},
            }
            began = time.monotonic()
            client.post(f"{self.config.ollama_base_url}/api/generate", json=body)
        return {"reload_sec": round(time.monotonic() - began, 1), "num_ctx": self.config.ollama_num_ctx}

    def _repair_ollama(self) -> dict[str, Any]:
        """고치기는 뒤에서 돈다(옮기기·켜기) — 끝날 때까지 기다린 뒤 돌아와야 「다시 읽기」가 뜻이 있다."""
        installer = self.installer
        if installer is None:
            raise RuntimeError("installer_missing")
        started = dict(installer.repair() or {})
        if not started.get("ok"):
            return started
        phase = ""
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            phase = str((installer.status() or {}).get("install", {}).get("phase") or "")
            if phase in {"ready", "error"}:
                break
            time.sleep(2)
        return {**started, "phase": phase}

    def _restart_browser(self) -> dict[str, Any]:
        self.browser.stop()
        time.sleep(1.5)
        return dict(self.browser.start() or {})

    def heal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        organ = HEALERS.get(action)
        if organ is None:
            raise ValueError(
                f"unknown_action:{action} — 할 수 있는 것은 {', '.join(sorted(HEALERS))} 뿐입니다"
            )

        # ★ **고장일 때만 고친다.** 멀쩡한 것을 재시작하면 그것이 곧 고장이다.
        before = getattr(self, self._PROBES[organ])()
        if before["state"] != "down":
            return {
                "action": "self_heal",
                "healer": action,
                "organ": organ,
                "ran": False,
                # ★ 2026-09-23: 사람 화면(「점검 통과」 띠)에 그대로 나간다 — 「model 은 … (ok). 손대지 않았습니다」는
                #   개발자 말이었다. 부품은 한국어 이름으로, 상태값은 빼고 말한다.
                "why": f"{_ORGAN_LABELS.get(organ, organ)}은(는) 지금 고장이 아닙니다 — 정상이라 그대로 두었습니다.",
                "before": before,
            }
        if self._too_often(organ):
            return {
                "action": "self_heal",
                "healer": action,
                "organ": organ,
                "ran": False,
                "why": f"{organ} 을 최근 {HEAL_WINDOW_SEC // 60}분 안에 "
                       f"{HEAL_LIMIT_PER_ORGAN}번 고쳤습니다. 더 눌러도 같은 결과라 멈춥니다 — 사람이 봐야 합니다.",
                "before": before,
            }

        self._healed.setdefault(organ, []).append(time.time())
        try:
            detail = getattr(self, f"_{action}")()
            error = ""
        except Exception as exc:  # noqa: BLE001
            detail, error = {}, str(exc)[:200]

        # ★ 고쳤다는 말은 증거가 아니다. **다시 읽는다.**
        after = getattr(self, self._PROBES[organ])()
        result = {
            "action": "self_heal",
            "healer": action,
            "organ": organ,
            "ran": True,
            "fixed": after["state"] == "ok",
            "before": before,
            "after": after,
            "detail": detail,
            "error": error,
        }
        self.events.publish(
            "self_heal", {"healer": action, "organ": organ, "fixed": result["fixed"]}
        )
        return result

    # ── 등록 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or []},
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "self_check",
                "손자리 자신의 상태를 실제로 찔러 확인한다 — 엔진(Ollama 설치)·모델(토큰을 하나 생성해 본다)·"
                "음성 서버·브라우저·그래픽카드·구글 연결. 느리거나 이상하다고 느껴질 때, "
                "그리고 어떤 도구가 계속 실패할 때 먼저 부른다. 아무것도 바꾸지 않는다.",
                {"organ": {"type": "string", "enum": sorted(_PROBE_NAMES), "description": "비우면 전부"}},
            ),
            self._function(
                "self_heal",
                "self_check 가 고장이라고 말한 기관을 정해진 방법으로 되살린다. "
                "고장이 아니면 아무것도 안 한다. 고친 뒤 다시 검사해서 나아졌는지 알려준다.",
                {"action": {"type": "string", "enum": sorted(HEALERS)}},
                ["action"],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {"self_check": self.check, "self_heal": self.heal}
        # check 는 읽기만 하므로 L0. heal 은 서비스를 되살리므로 L1 —
        # 밖으로 나가는 것이 없고, 고장일 때만 돌며, 되돌릴 것도 없다(이미 죽은 것을
        # 다시 띄우는 일이다). 사람 승인을 걸면 정작 새벽에 못 고친다.
        risks = {"self_check": RiskLevel.L0, "self_heal": RiskLevel.L1}
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=True,
                )
            )


_PROBE_NAMES = set(SelfCare._PROBES)
