"""첫 실행 2단계 — 모델을 **받고, 적용하고, 실제로 도는지 확인한다.**

## 왜 (2026-09-13, 전략안 §43 · P2)

지금은 사용자가나 Claude 가 `.env` 에 모델 태그를 손으로 적는다. 공개 제품이면
사용자가 갤러리에서 누르거나 추천을 받아들이는 것으로 끝나야 한다.

## 이 저장소가 이미 겪은 것 — 전부 여기서 막는다

1. **태그가 갈리면 서로 GPU 에서 쫓아낸다.** 같은 26B 를 사설 별칭과 공식 태그로
   라는 이름으로 부른다. 추천 이름(`gemma4:26b-a4b-it-qat`)으로 바꾸면 같은 파일이
   두 이름으로 올라가 서로를 내린다(자비스가 몇 분씩 멈춘 사고). → **digest 가 같으면
   이미 쓰는 이름을 유지한다.**
2. **Ollama 는 스스로 모델을 안 바꾼다.** 새 모델을 부르면 옛 모델을 내리지 않고
   멈춘다(8/31 재발). → **옛 모델을 `keep_alive: 0` 으로 먼저 내린다.**
3. **200 은 증거가 아니다.** 받기가 「success」로 끝나도 못 올릴 수 있다. → 적용 전에
   **토큰을 실제로 생성**해 본다(`setup_profile.micro_bench`). 안 되면 저장하지 않는다.

## 어디에 저장하나

`.env` 는 건드리지 않는다 — API 키·토큰이 섞인 파일이다. 사용자가 고른 것만
`data/model_selection.json` 에 두고, 설정을 읽을 때 그 위에 얹는다
(`apply_selection_to_config`). /health 가 어느 쪽에서 왔는지 말한다.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

import re

from .model_catalog import (
    CATALOG, TEXT_ONLY_PREFIX, agent_grade, by_key, by_tag, is_text_only_name, text_only_key, text_only_name,
    text_only_name_for_tag,
)
from .setup_profile import (
    _get_json,
    _post_json,
    catalog_view,
    detect,
    micro_bench,
    pictures_too_tight,
    recommend,
    usable_budget_gb,
)

SELECTION_NAME = "model_selection.json"
CEILING_NAME = "context_ceiling.json"
#: 재는 칸. **이 다섯 칸만** 재고, 새면 그 전 칸이 상한이다(2026-09-29 밤 대표 결정).
#:
#: ★ 09-23 엔 「칸 사이를 좁혀 진짜 상한을 잡자」로 이분 탐색까지 했다. 09-29 AWS 에서 9B 가 248K 까지 밀리며
#:   적재가 여러 번 더 돌아 「너무 느리다」 — 칸 하나마다 모델을 새로 올린다. 둥근 칸이면 설명도 쉽다.
CONTEXT_LADDER: tuple[int, ...] = (16384, 32768, 65536, 131072, 262144)
#: 칸 사이를 좁혀 재나. 꺼 둔다(위 결정). 켜면 09-23 방식(`CONTEXT_STEP` 단위 이분 탐색)으로 돌아간다.
CONTEXT_REFINE = False
#: 한 칸 올렸을 때 이 PC 의 첫 칸 속도 대비 이만큼은 나와야 합격. 컨텍스트가 커지면 조금 느려지는 건 정상이고,
#: CPU 로 새면 몇 배 떨어진다 — 그 사이를 가른다.
CONTEXT_MIN_SPEED_SHARE = 0.7
#: 두 배 칸 사이를 좁힐 때의 눈금. 이보다 잘게 재 봐야 차이가 없고 적재만 늘어난다.
CONTEXT_STEP = 4096
#: 「더 쥐어짜기」(설정 화면에서 사람이 누를 때만 · 2026-10-25 대표). 처음 재기는 둥근 칸 다섯 개 그대로 두고,
#: 잰 기록의 **합격 칸과 첫 불합격 칸 사이만** 반으로 두 번 더 올려 본다. 09-23 의 4K 이분 탐색은 128K → 256K 사이에서
#: 다섯 번 더 올려 느렸다(09-29 되돌림). 두 번이면 이 PC(모델 한 번 올리기 7~20초)에서 30~40초 더.
#: 득이 큰 곳은 16GB 카드처럼 「32K 합격 · 64K 불합격」인 PC — 48K · 56K 를 건진다.
SQUEEZE_PROBES = 2
SQUEEZE_STEP = 8192
#: 올려 보고 그래픽카드에 다 안 들어간 것 — 이것만 「그 칸은 안 들어간다」의 증거다. 올리다 시간이 다 된 것 · 서버 무응답은 아니다.
FIT_REASONS = frozenset({"not_fully_on_gpu", "context_clamped", "too_slow", "model_out_of_memory"})


def squeeze_gap(record: dict[str, Any]) -> tuple[int, int] | None:
    """잰 기록에서 (합격 상한, 그 위 첫 불합격 칸). 좁힐 사이가 없으면 None."""
    ceiling = int(record.get("ceiling") or 0)
    if not ceiling:
        return None
    above = [int(step.get("num_ctx") or 0) for step in record.get("steps") or []
             if not step.get("passed") and int(step.get("num_ctx") or 0) > ceiling and step.get("why") in FIT_REASONS]
    if not above:
        return None
    high = min(above)
    if _squeeze_mid(ceiling, high) == 0:
        return None
    return ceiling, high


def _squeeze_mid(low: int, high: int) -> int:
    middle = (low + high) // 2 // SQUEEZE_STEP * SQUEEZE_STEP
    return middle if low < middle < high else 0
#: Ollama 모델 이름 모양 — `이름[:태그]`, 이름에 `네임스페이스/` 한 번. 셸·경로 문자는 받지 않는다.
# ★ 2026-10-01 헤르메스 비교 중 발견: Ollama 는 `hf.co/작성자/저장소:양자화` 로 허깅페이스 GGUF 를 바로 받는데,
#   이 검사가 슬래시 둘·대문자 때문에 거절해 「직접 입력」으로 그 길이 막혀 있었다. 허깅페이스 주소만 대소문자를 받는다.
OLLAMA_TAG = re.compile(
    r"(?:(?:hf\.co|huggingface\.co)/[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}"
    r"|[a-z0-9][a-z0-9._-]{0,80}(?:/[a-z0-9][a-z0-9._-]{0,80})?)"
    r"(?::[A-Za-z0-9][A-Za-z0-9._-]{0,80})?"
)


# ── 이름 고르기 ───────────────────────────────────────────────────────────────
def pull_failure_reason(exc: BaseException) -> str:
    """모델 받기 실패의 **원인 갈래** — 화면이 사람에게 다음 할 일을 원인마다 다르게 말하려고 (2026-10-01).

    ★ 베타 첫 사용자(회사 PC): Ollama 가 안 떠 있어 「[WinError 10061] 연결 거부」였는데, 화면은 「인터넷 연결과 디스크
      여유를 확인하라」고 했다 — 엉뚱한 곳을 보라는 안내다. 받기는 **이 PC 안의 Ollama**(127.0.0.1)에 부탁하는 일이라,
      연결 거부는 인터넷이 아니라 Ollama 가 꺼져 있다는 뜻이다.
    """
    text = f"{type(exc).__name__}: {exc}"
    reason = getattr(exc, "reason", None)
    if isinstance(exc, ConnectionRefusedError) or isinstance(reason, ConnectionRefusedError) \
            or "10061" in text or "Connection refused" in text:
        return "ollama_not_running"
    if "No space left" in text or "WinError 112" in text or "disk is full" in text.lower():
        return "disk_full"
    return ""


def why_apply_failed(bench: dict[str, Any]) -> str:
    """토큰 생성이 실패한 **진짜 이유**. 화면이 엉뚱한 곳(드라이버)을 가리키지 않게 가른다.

    ★ 2026-09-18 노트북 실측: 온텔릭이 깐 Ollama 에 `llama-server.exe` 가 없어
      (`error starting llama-server: llama-server binary not found`) 모델이 하나도 안 올라갔는데,
      화면은 「글자가 나오지 않았습니다 — 그래픽카드 드라이버를 확인해 주세요」였다. 원인 셋(설치 반쪽·
      시간 초과·정말 빈 답)이 한 문구로 뭉쳐 있었다. 지난 노트북 설치의 「드라이버 재설치」 오탐과 같은 병이다.
    """
    error = str(bench.get("error") or "").lower()
    # ★ 메모리 부족이 먼저다 (2026-10-01 밤 베타 테스터 노트북 RTX 3050 6GB). 오류가
    #   「llama-server startup failed … cudaMalloc failed: out of memory」였는데 「llama-server」 낱말만 보고
    #   「설치가 덜 됐다」로 갈라 다시 설치를 시켰다 — 다시 깔아도 메모리는 그대로라 안 풀린다.
    if "out of memory" in error or "cudamalloc" in error or "outofmemory" in error or "insufficient memory" in error:
        return "model_out_of_memory"
    if ("llama-server" in error or "llama_server" in error) and (
            "not found" in error or "no such file" in error or "cannot find" in error):
        return "ollama_runner_missing"
    if "llama-server" in error or "llama_server" in error:
        return "model_load_failed"
    if "timeout" in error or "timed out" in error:
        return "model_load_timeout"
    if "urlerror" in error or "connection" in error or "refused" in error:
        return "ollama_not_answering"
    if error == "empty_generation":
        return "model_did_not_generate"
    return "model_did_not_generate"


def gpu_users(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """메모리가 모자랐을 때 **지금 그래픽카드를 누가 쓰나** — 사람이 닫을 것을 고르게 (2026-10-01 밤).

    우리 모델은 방금 내렸으니 남은 것은 남의 몫이다. 이름이 `ollama`·`llama-server` 여도 보인다 — 예전에 깐
    다른 Ollama(위성 등)가 모델을 쥐고 있는 것이 그 노트북에서 가장 흔한 범인이라 숨기면 안 된다.
    윈도우는 프로그램별 메모리가 `[N/A]` 라 카드 전체 사용량만 준다. 못 읽으면 빈 값.
    """
    from .context_watch import gpu_snapshot

    shot = snapshot if snapshot is not None else gpu_snapshot()
    gpus = [gpu for gpu in shot.get("gpus") or [] if gpu.get("total_gb")]
    if not gpus:
        return {}
    gpu = max(gpus, key=lambda g: g.get("total_gb") or 0)
    names: list[str] = []
    for name in gpu.get("apps") or []:
        if "insufficient" not in name.lower() and name not in names:
            names.append(name)
    return {"used_gb": gpu.get("used_gb"), "total_gb": gpu.get("total_gb"), "apps": names[:8]}


#: 그래픽카드를 늘 조금씩 쓰는 윈도우의 기본 프로그램 — 닫으라고 권하지 않는다(닫을 수 없거나 닫아도 다시 뜬다).
#: 「이걸 닫으세요」에 탐색기가 나오면 사람은 그 안내 전체를 안 믿는다.
_ALWAYS_THERE = frozenset({
    "dwm", "explorer", "csrss", "searchhost", "shellexperiencehost", "startmenuexperiencehost", "textinputhost",
    "systemsettings", "lockapp", "widgets", "applicationframehost", "ctfmon", "sihost", "taskmgr",
})

def way_out(failed_key: str, *, installed: set[str] | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """고른 모델을 그래픽카드에 다 못 올렸을 때 **사람이 고를 수 있는 두 길** (2026-10-10 대표).

    전에는 빨간 글 한 줄이었다(「다른 GPU 앱을 종료한 뒤 다시 시도해 주세요」) — 무엇을 닫아야 하는지도, 닫아도 되는지도,
    안 닫고 가는 길도 없었다. 여기서 재료를 준다:

      close    지금 그 카드를 쓰는 프로그램(윈도우 기본은 뺌)과, **다 닫으면 들어가는가**. 닫는 것은 사람이 한다 —
               우리가 남의 프로그램을 끄다가 저장 안 한 일을 날리면 그게 더 큰 사고다.
      smaller  지금 빈 메모리에 들어가는 한 단계 작은 모델(`setup_profile.smaller_that_fits`).

    모르는 것은 모른다고 준다(None). 「들어갑니다」는 잰 값이 있을 때만 말한다. 못 읽으면 빈 dict — 화면은 예전 글을 쓴다.
    """
    from .setup_profile import BASE_RESERVE_GB, smaller_choice

    model = by_key(failed_key)
    if model is None or not model.vram_gb:
        return {}
    users = gpu_users(snapshot)
    total, used = users.get("total_gb"), users.get("used_gb")
    free = round(float(total) - float(used), 1) if total is not None and used is not None else None
    needs = min(model.vram_gb.values())  # 가장 작은 창으로도 이만큼 — 큰 창은 적용할 때 이미 줄여 봤다
    closable = [name for name in users.get("apps") or [] if name.lower() not in _ALWAYS_THERE]
    out: dict[str, Any] = {
        "model_key": failed_key, "model_name": model.name, "needs_gb": needs,
        "card": {"total_gb": total, "used_gb": used, "free_gb": free},
        "close": {
            "apps": closable[:6],
            # 다 닫아도 안 들어가는 카드면 「닫으세요」가 헛걸음이다 — 그 말을 하지 않게 화면에 알린다.
            #   카드가 스스로 쓰는 몫은 추천이 쓰는 값 그대로(`setup_profile.BASE_RESERVE_GB`) — 같은 것을 두 자리에 적지 않는다.
            "would_fit": (needs + BASE_RESERVE_GB <= float(total)) if total is not None else None,
        },
        "smaller": None,
    }
    # 글만 읽기 칸도 본다(2026-10-26 · 16GB 에서 Swift 가 안 들어가면 Qwen3.6 2비트 · 글만 읽기) — 화면은 `text_only` 면 그림을 끄고 적용한다.
    pick = smaller_choice(free, failed_key)
    if pick is not None:
        smaller, ctx, need, text_only = pick
        tags = {_bare_tag(tag) for tag in installed or ()}
        out["smaller"] = {
            "model_key": smaller.key, "name": smaller.name, "num_ctx": ctx, "needs_gb": need, "text_only": text_only,
            "download_gb": smaller.download_gb, "installed": _bare_tag(smaller.ollama_tag) in tags,
            "weak_at": smaller.weak_at, "good_at": smaller.good_at,
        }
    return out


def _bare_tag(tag: str) -> str:
    """`:latest` 를 뗀 이름. Ollama 는 같은 모델을 `q:latest` 와 `q` 두 이름으로 말한다 —
    그대로 비교하면 「지금 쓰는 것」에 ✓ 가 안 붙고, 목록에 같은 모델이 두 줄로 나온다."""
    return str(tag or "").strip().lower().removesuffix(":latest")


def resolve_tag(catalog_tag: str, installed: list[dict[str, Any]], configured: list[str]) -> str:
    """추천 이름과 **같은 파일**을 이미 다른 이름으로 쓰고 있으면 그 이름을 쓴다."""
    by_name = {str(m.get("name") or ""): str(m.get("digest") or "") for m in installed}
    wanted_digest = by_name.get(catalog_tag) or by_name.get(f"{catalog_tag}:latest") or ""
    if not wanted_digest:
        return catalog_tag
    for name in configured:
        for candidate in (name, f"{name}:latest"):
            if candidate in by_name and by_name[candidate] == wanted_digest:
                return name
    return catalog_tag


# ── 저장된 선택 ───────────────────────────────────────────────────────────────
def read_selection(data_dir: Path) -> dict[str, Any] | None:
    path = Path(data_dir) / SELECTION_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not value.get("chat_model"):
        return None
    return value


def write_selection(data_dir: Path, selection: dict[str, Any]) -> None:
    """반쯤 쓴 파일이 남지 않게 **옆에 쓰고 바꿔 끼운다.**"""
    path = Path(data_dir) / SELECTION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(selection, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


#: 목록 밖 모델에서 만든 「글만 읽는」 이름 → 원래 이름 (2026-10-13). 목록 모델은 이름에 목록 키가 실려 있어 이 표가
#: 필요 없다(`text_only_key`). 목록 밖 모델은 이름만으로는 원래 이름을 되살릴 수 없어서, 「그림도 읽기」로 돌아갈 때
#: 어디로 갈지를 여기 적어 둔다.
TEXT_ONLY_SOURCES_NAME = "text_only_sources.json"


def read_text_only_sources(data_dir: Path) -> dict[str, str]:
    try:
        value = json.loads((Path(data_dir) / TEXT_ONLY_SOURCES_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(name): str(source) for name, source in value.items() if name and source} if isinstance(value, dict) else {}


def remember_text_only_source(data_dir: Path, name: str, source: str) -> None:
    """「글만 읽는」 이름이 어느 모델에서 나왔는지 적는다. 못 적어도 적용을 꺾지 않는다(되돌아갈 길만 없어진다)."""
    try:
        known = read_text_only_sources(data_dir)
        known[_bare_tag(name)] = str(source)
        path = Path(data_dir) / TEXT_ONLY_SOURCES_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(path)
    except OSError:
        pass


def read_ceilings(data_dir: Path) -> dict[str, dict[str, Any]]:
    """모델별로 마지막에 잰 컨텍스트 상한. 화면이 「09-23 잼 · 128K」를 보여 주는 재료."""
    try:
        value = json.loads((Path(data_dir) / CEILING_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _remember_ceiling(data_dir: Path, result: dict[str, Any]) -> None:
    rows = read_ceilings(data_dir)
    old = rows.get(str(result["model"])) or {}
    row = dict(result)
    # 다시 재도 사람이 고른 칸은 남긴다 — 잰 결과는 사실이고, 고른 것은 뜻이다(둘은 따로 바뀐다).
    for key in ("chosen", "chosen_at"):
        if key in old and key not in row:
            row[key] = old[key]
    rows[str(result["model"])] = row
    _write_ceilings(data_dir, rows)


def remember_context_choice(data_dir: Path, tag: str, num_ctx: int) -> None:
    """이 모델을 **어떤 컨텍스트로 쓰기로 했나** — 다음에 이 모델로 바꿀 때 재지 않고 바로 이 크기로 올린다.

    ★ 2026-09-30 대표: 3.8 → 3.6 교체가 10분 가까이 걸렸다. 교체가 128K(샘) → 64K(샌다고 이미 잰 값) → 32K 로 모델을
      세 번 새로 올렸고(한 번 42~80초), 대표는 그 뒤 쓰려던 64K 로 다시 골랐다(네 번째). 이 PC 가 이미 아는 것을 매번 다시 쟀다.
    """
    rows = read_ceilings(data_dir)
    row = dict(rows.get(tag) or {"model": tag})
    row["chosen"] = int(num_ctx)
    row["chosen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows[tag] = row
    _write_ceilings(data_dir, rows)


def _write_ceilings(data_dir: Path, rows: dict[str, dict[str, Any]]) -> None:
    path = Path(data_dir) / CEILING_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def apply_selection_to_config(config: Any) -> str:
    """저장된 선택을 설정에 얹는다. 돌려주는 값은 **어디서 왔는지** — `setup` / `env`."""
    selection = read_selection(Path(config.data_dir))
    if not selection:
        return "env"
    roles = dict(config.model_roles or {})
    roles["chat"] = str(selection["chat_model"])
    if selection.get("vision_model"):
        roles["vision"] = str(selection["vision_model"])
    config.model_roles = roles
    if selection.get("num_ctx"):
        config.ollama_num_ctx = int(selection["num_ctx"])
    return "setup"


def follow_chat_with_code(config: Any) -> bool:
    """선택이 「코드는 대화 모델을 따라간다」고 적어 두었으면 코드 역할을 대화 모델로 맞춘다. 맞췄으면 True.

    ★ 2026-10-10: 예전에는 「따라간다」를 **대화 모델 이름의 사본**(`settings.json` 의 `model_code`)으로 적었다.
      대화 모델은 `model_selection.json` 에, 그 사본은 다른 파일에 — 두 파일이 어긋나면(한쪽만 되돌림 · 쓰는 도중 꺼짐 ·
      화면에서 대화 모델만 바꿈) 코드 역할이 옛 모델에 남는다. 아무 말 없이, 자리가 하나뿐인 카드에서 대화 걸음과
      코드 걸음이 서로를 밀어낸다. 이 PC 에서 하루 종일 그랬다(작은 양자화로 재 본 뒤 대화 쪽만 되돌렸다).
      이제 사본을 두지 않는다 — 선택 파일의 한 줄(`code_follows_chat`)이 사실이고, 코드 역할은 켤 때마다 여기서 맞춘다.

    따로 고른 코드 모델(화면 설정의 `model_code`)이 있으면 그 선택이 이긴다. 선택 파일이 그 줄을 안 적었으면(옛 파일 ·
    관리 설치의 환경변수로 코드 모델을 정한 PC) 손대지 않는다.
    """
    selection = read_selection(Path(config.data_dir))
    if not selection or not selection.get("code_follows_chat"):
        return False
    if "model_code" in tuple(getattr(config, "settings_applied", ()) or ()):
        return False
    roles = dict(config.model_roles or {})
    chat = str(roles.get("chat") or "").strip()
    if not chat or str(roles.get("code") or "").strip() == chat:
        return False
    roles["code"] = chat
    config.model_roles = roles
    return True


# ── 받기·적용 ─────────────────────────────────────────────────────────────────
#: 미리 내다보기(MTP)를 켰을 때 이만큼은 빨라야 켠다 — 재는 흔들림보다 커야 한다.
MTP_MIN_GAIN = 1.10
#: 켤 때 쓰는 값. 27B 셋에서 4 가 2 보다 빨랐다(2026-10-08 · RTX 3090). 느려지는 모델은 재서 안 켠다.
MTP_DRAFT_TOKENS = 4
#: 끔·켬을 견줄 때 쓰는 글 — 길게 쓰게 해야 속도가 고르다(「1부터 30까지」는 60토큰에 끝난다).
MTP_BENCH_PROMPT = "퀵소트가 어떻게 동작하는지 설명하고, 주석을 단 파이썬 구현을 쓰고, [5, 2, 9, 1, 7] 을 정렬하는 과정을 한 걸음씩 적어라."


def parse_model_parameters(text: str) -> dict[str, Any]:
    """`/api/show` 의 parameters 글(줄마다 「이름 값」)을 다시 만들 때 넘길 모양으로. 같은 이름이 여러 줄이면 목록."""
    out: dict[str, Any] = {}
    for line in str(text or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        key, raw = parts[0], parts[1].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            value: Any = raw[1:-1]
        else:
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
        if key in out:
            out[key] = (out[key] if isinstance(out[key], list) else [out[key]]) + [value]
        else:
            out[key] = value
    return out


class SetupService:
    """첫 실행 화면이 부르는 곳. 한 번에 한 모델만 받는다."""

    def __init__(
        self,
        config: Any,
        *,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
        post: Callable[[str, dict[str, Any], float], dict[str, Any]] | None = None,
        get: Callable[[str], dict[str, Any] | None] | None = None,
        stream: Callable[[str, dict[str, Any]], Any] | None = None,
        patch_settings: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._publish = publish or (lambda _event, _payload: None)
        # 설정 저장은 **런타임이 쥔 서비스**로 간다. 여기서 새로 만들면 라이브 반영 고리
        # (`on_live_change`)가 안 달려서, 저장은 됐는데 이 프로세스는 옛 모델을 계속 쓴다.
        self._patch_settings = patch_settings
        self._post = post or _post_json
        self._get = get or (lambda url: _get_json(url))
        self._stream = stream or _stream_lines
        self._lock = threading.Lock()
        self._apply_lock = threading.RLock()
        self._pulls: dict[str, dict[str, Any]] = {}
        self._profile: dict[str, Any] | None = None
        self._profile_at = 0.0
        self.last_bench: dict[str, Any] | None = None
        #: 모델마다 「그림 부속이 따로 붙었나」를 물어본 답(`eyes_of`) — (물어본 때, 답). 화면이 자주 불러 잠깐 들고 있는다.
        self._eyes_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        #: 모델 파일의 크기를 읽는 손 — 시험은 가짜로 바꿔 끼운다(몇 GB 짜리 파일을 진짜로 만들지 않으려고).
        self._blob_size: Callable[[Path], int] = lambda path: path.stat().st_size
        #: 재는 중인 상한 — 화면이 칸마다 받아 그린다. 다 재면 `None`.
        self.context_live: dict[str, Any] | None = None
        #: 상한 재기에서 그래픽카드 비율을 못 읽었을 때 다시 읽기 전 기다림. 시험은 0 으로 둔다.
        self._reread_sec = 1.0
        # 카드 사정 보기(nvidia-smi). 시험은 가짜로 바꿔 끼운다.
        from .context_watch import gpu_snapshot

        self.gpu_snapshot: Callable[[], dict[str, Any]] = gpu_snapshot

    @property
    def base_url(self) -> str:
        return str(self.config.ollama_base_url).rstrip("/")

    @property
    def is_satellite(self) -> bool:
        return str(getattr(self.config, "jarvis_role", "")).lower() == "satellite"

    # 진단은 비싸지 않지만 화면이 단계마다 부른다 — 30초는 같은 PC 다.
    def profile(self, *, fresh: bool = False) -> dict[str, Any]:
        if fresh or self._profile is None or time.monotonic() - self._profile_at > 30:
            self._profile = detect(self.base_url)
            self._profile_at = time.monotonic()
        return self._profile

    def recommendation(self) -> dict[str, Any]:
        if self.is_satellite:
            return {"mode": "satellite", "model_key": None, "reasons": [
                "이 PC 는 위성입니다 — 모델은 본체 PC 에서 빌려 씁니다."], "warnings": []}
        return recommend(self.profile(), self.last_bench)

    def pulls(self) -> dict[str, Any]:
        """모델 받기 상태만(목록·PC 점검 없이) — 제보의 첫 실행 자취가 가볍게 읽는다."""
        return dict(self._pulls)

    def models(self) -> dict[str, Any]:
        return {
            "models": self._with_eyes(catalog_view(self.profile())),
            "selection": read_selection(Path(self.config.data_dir)),
            "current_chat_model": self.config.model_for("chat"),
            # 지금 쓰는 모델의 그림 읽기 — 목록 밖 모델(허깅페이스에서 고른 것)도 화면이 켜고 끌 수 있게(2026-10-13).
            "eyes": {} if self.is_satellite else self.current_eyes(),
            "pulls": dict(self._pulls),
            "satellite": self.is_satellite,
        }

    def eyes_of(self, tag: str) -> dict[str, Any]:
        """받아 둔 이 모델이 그림을 읽는가 · 그 부속이 **따로 붙은 파일**인가(뗄 수 있나) · 부속의 크기(GB).

        Ollama 에 직접 묻는다(`/api/show`) — 파일 줄(`FROM`)이 둘이면 모델 파일과 그림 부속이 따로다. **이름으로 가르지
        않는다:** 같은 집안의 공식 태그도 갈린다(2026-10-13 6GB 노트북: `qwen3.5:2b` 는 두 파일, `qwen3.5:4b` 는 그림이
        모델 파일 안에 든 한 파일). 허깅페이스에서 받은 것은 부속이 따로 온다. 안 받았거나 못 물어봤으면 전부 아니오다.
        크기는 이 PC 의 파일에서 읽는다 — Ollama 가 다른 PC 에 있으면 0 이다(모른다).
        """
        key = _bare_tag(tag)
        held = self._eyes_cache.get(key)
        if held and time.monotonic() - held[0] < 30:
            return dict(held[1])
        answer: dict[str, Any] = {"vision": False, "separable": False, "eyes_gb": 0.0}
        if not key:
            return answer
        try:
            shown = self._post(f"{self.base_url}/api/show", {"model": tag}, 20.0) or {}
        except Exception:  # noqa: BLE001 — 못 물어본 것은 기억하지 않는다(받고 나면 답이 달라진다)
            return answer
        paths = list(dict.fromkeys(re.findall(r"^FROM\s+(.*sha256[-:][0-9a-f]{64})\s*$", str(shown.get("modelfile") or ""), re.M)))
        answer["vision"] = "vision" in [str(c) for c in shown.get("capabilities") or []]
        if answer["vision"] and len(paths) >= 2:
            answer["separable"] = True
            sizes: list[int] = []
            for path in paths:
                try:
                    sizes.append(int(self._blob_size(Path(path.strip().replace("sha256:", "sha256-")))))
                except OSError:
                    sizes = []
                    break
            if len(sizes) >= 2:
                answer["eyes_gb"] = round(min(sizes) / 1e9, 2)
        self._eyes_cache[key] = (time.monotonic(), dict(answer))
        return answer

    def current_eyes(self) -> dict[str, Any]:
        """지금 쓰는 대화 모델의 그림 읽기 — 켜져 있나 · 바꿀 수 있나 · 바꿀 때 어느 이름을 부르나. 목록 밖 모델도 같다.

        `source_tag` 는 **그림을 읽는 쪽 이름**이다. 화면은 이 이름에 `eyes: true/false` 를 실어 적용을 부른다
        (`apply_tag`). 「글만 읽는」 이름을 쓰는 중이면 그 이름이 나온 원래 이름을 찾아 준다 — 못 찾으면 못 바꾼다.
        """
        current = str(self.config.model_for("chat") or "").strip()
        if not current:
            return {}
        if is_text_only_name(current):
            key = text_only_key(current)
            if key:
                source = self._tag_for(by_key(key).ollama_tag)
            else:
                source = read_text_only_sources(Path(self.config.data_dir)).get(_bare_tag(current), "")
            info = self.eyes_of(source) if source else {}
            return {"tag": current, "reads_pictures": False, "can_switch": bool(source) and bool(info.get("vision")),
                    "source_tag": source, "saves_gb": float(info.get("eyes_gb") or 0.0), "listed": bool(key)}
        info = self.eyes_of(current)
        return {"tag": current, "reads_pictures": bool(info["vision"]), "can_switch": bool(info["separable"]),
                "source_tag": current, "saves_gb": float(info["eyes_gb"]), "listed": by_tag(current) is not None}

    def _with_eyes(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """목록의 카드에 「이 PC 에 받아 둔 이 모델은 그림 부속을 뗄 수 있다」를 붙인다.

        목록이 미리 아는 것은 우리가 부속을 따로 받아 붙이는 모델뿐이다(`projector_tag`). 나머지는 받아 봐야 안다 —
        받아 둔 것만 물어보고(`eyes_of`), 뗄 수 있으면 같은 칸으로 알린다. 덜 쓰는 메모리는 그 PC 의 부속 파일 크기다.
        """
        if self.is_satellite:
            return rows
        for row in rows:
            if row.get("pictures_optional") or not row.get("installed") or not row.get("vision"):
                continue
            info = self.eyes_of(str(row.get("ollama_tag") or ""))
            if info["separable"]:
                row.update(pictures_optional=True, text_only_tag=text_only_name(str(row.get("key") or "")),
                           text_only_saves_gb=float(info["eyes_gb"]))
        return rows

    def benchmark(self, model_key: str | None = None, num_ctx: int | None = None) -> dict[str, Any]:
        model = by_key(model_key) if model_key else None
        tag = self._tag_for(model.ollama_tag) if model else self.config.model_for("chat")
        ctx = int(num_ctx or self.config.ollama_num_ctx)
        result = micro_bench(self.base_url, tag, ctx, post=self._post)
        self.last_bench = result
        return result

    def start_pull(self, model_key: str, apply_ctx: int = 0, eyes: bool | None = None) -> dict[str, Any]:
        """받기 시작. `apply_ctx` 를 주면 **다 받은 뒤 백엔드가 바로 적용한다.**

        ★ 2026-09-16 노트북 첫 설치: 적용을 **마법사 화면이** 받기 끝나기를 지켜보다 했다. 「받는 동안 다음으로」 →
          연결까지 마치고 마법사를 닫으니 지켜볼 화면이 없어 적용이 안 됐고, 받아 둔 Qwen 대신 기본값(Gemma 26B)이
          남아 제품 첫 화면이 「대화 모델이 이 PC 에 없습니다」였다. 화면이 닫혀도 끝나는 일은 서버가 끝낸다.
        """
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        model = by_key(model_key)
        if model is None:
            return {"ok": False, "error": "unknown_model"}
        with self._lock:
            state = self._pulls.get(model_key)
            if state and state.get("status") == "pulling":
                return {"ok": True, **state}
            state = {"model_key": model_key, "status": "pulling", "completed": 0, "total": 0,
                     "detail": "시작합니다", "started_at": time.time()}
            self._pulls[model_key] = state
        # `eyes=False` 면 받은 뒤 그림 부속을 뗀 채(글만 읽기)로 적용한다 — 「안 들어가면 작은 모델」의 글만 읽기 칸(2026-10-26).
        after = (lambda: self.apply(model_key, int(apply_ctx), eyes=eyes)) if apply_ctx else None
        threading.Thread(target=self._pull, args=(model_key, model.ollama_tag, after), daemon=True).start()
        return {"ok": True, **state}

    def _pull(self, model_key: str, tag: str, after: Callable[[], dict[str, Any]] | None = None) -> None:
        state = self._pulls[model_key]
        try:
            # ★ 2026-09-29 밤 AWS 첫 실행: Ollama 는 **층마다** total 을 보낸다(본체 6GB + 틀·설정 몇 KB). 마지막 층의
            #   total 만 적었더니 본체를 다 받은 뒤 마법사가 「받는 중 0% · 0.0/0.0GB」로 1~2분 멈춘 듯 보였다
            #   (그 뒤엔 크기 없는 해시 확인). 층을 **합쳐서** 세고, 무슨 단계인지 `phase` 로 따로 알린다.
            layers: dict[str, tuple[int, int]] = {}
            for event in self._stream(f"{self.base_url}/api/pull", {"model": tag, "stream": True}):
                if event.get("error"):
                    raise RuntimeError(str(event["error"]))
                status = str(event.get("status") or "")
                state["detail"] = status
                digest = str(event.get("digest") or "")
                if event.get("total") and digest:
                    layers[digest] = (int(event.get("completed") or 0), int(event["total"]))
                    state["total"] = sum(total for _, total in layers.values())
                    state["completed"] = sum(done for done, _ in layers.values())
                elif event.get("total"):
                    state["total"] = int(event["total"])
                    state["completed"] = int(event.get("completed") or 0)
                lowered = status.lower()
                if lowered.startswith("verifying"):
                    state["phase"] = "verifying"
                elif lowered.startswith(("writing manifest", "removing", "success")):
                    state["phase"] = "finishing"
                elif lowered.startswith("pulling") and digest:
                    state["phase"] = "downloading"
                self._publish("setup_model_pull", dict(state))
            # ★ 「success」가 왔다고 끝이 아니다 — 목록에 실제로 있는지 다시 본다.
            tags = self._get(f"{self.base_url}/api/tags") or {}
            names = {str(m.get("name") or "") for m in tags.get("models") or []}
            if tag not in names and f"{tag}:latest" not in names:
                raise RuntimeError("pull_reported_success_but_model_missing")
            self._profile = None
            if after is not None:
                # 「받았다」를 알리기 **전에** 적용한다 — 화면이 done 을 보고 또 적용하면 두 번 돌린다.
                state.update(detail="받았습니다 — 실제로 한 번 돌려 보고 적용하는 중")
                self._publish("setup_model_pull", dict(state))
                state["applied"] = after()
            state.update(status="done", detail="받았습니다")
        except Exception as exc:  # noqa: BLE001 — 실패도 화면에 보여야 한다
            state.update(status="failed", detail=f"{type(exc).__name__}: {str(exc)[:160]}", reason=pull_failure_reason(exc))
        self._publish("setup_model_pull", dict(state))

    def apply(self, model_key: str, num_ctx: int, *, remembered_first: bool = False,
              eyes: bool | None = None) -> dict[str, Any]:
        """고른 모델로 **실제로 한 번 돌려 보고**, 되면 그때 저장한다.

        `num_ctx` 는 사람이 모델 카드에서 **고른 칸**이다 — 그대로 올린다. 모델만 바꾸는 길(고르개)은 `remembered_first` 로
        「이 모델을 쓰던 크기」를 먼저 쓴다(`_measure_and_save`).

        `eyes=False` 는 「글만 읽기」다(2026-10-12) — 그림 부속을 따로 붙이는 모델에서 그 부속을 뺀 이름으로 올린다
        (`text_only_tag`). 안 주면(None) 예전 그대로 그림을 읽게 올린다. 부속을 뗄 수 없는 모델에서는 이 값을 무시한다.
        ★ 2026-10-13: 우리가 부속을 붙인 모델(`projector_tag`)뿐 아니라, **받아 보니 부속이 따로 붙어 온 모델**도 뗀다
          (`eyes_of`). 6GB 카드에서 눈을 단 채로는 다 못 올라가던 4B 가 눈을 빼니 창 48K 까지 올라갔다.
        """
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        model = by_key(model_key)
        if model is None:
            return {"ok": False, "error": "unknown_model"}
        ctx = int(num_ctx)
        # 표에 없는 창이라도 **표의 가장 큰 창보다 작으면** 받는다 — 창이 작을수록 메모리가 덜 들고, 들어가는지는
        # 아래에서 실제로 올려 본다(`_measure_and_save`). 표보다 큰 창만 거절한다(들어가는지 우리가 모른다).
        # ★ 2026-09-29 밤: 3.6 표엔 128K 하나뿐이라 64K 를 골라도 거절되거나 128K 로 바뀌어 CPU 로 샜다.
        if ctx not in model.vram_gb and not (ctx >= 4096 and ctx < max(model.vram_gb)):
            return {"ok": False, "error": "context_not_measured",
                    "measured": sorted(model.vram_gb)}
        tag = self._tag_for(model.ollama_tag)
        vision = model.vision
        # ★ 2026-10-15: 말하지 않았는데(None) 그림을 켠 채로는 빠듯하면 글만 읽기로 — 목록이 「글만 읽기」로 보인 칸과 같게.
        #   설정 화면이 그림을 단 채 올려 6GB 노트북에서 카드에 70.7% 만 올라갔다(`setup_profile.pictures_too_tight`).
        if eyes is None and model.vision:
            try:
                if pictures_too_tight(model, ctx, self.profile()):
                    eyes = False
            except Exception:  # noqa: BLE001 — 카드를 못 읽으면 예전 그대로
                pass
        if eyes is False and (model.projector_tag or (model.vision and self.eyes_of(tag)["separable"])):
            made = self.text_only_tag(tag, text_only_name(model.key))
            if not made.get("ok"):
                return {"ok": False, "error": str(made.get("error") or "text_only_failed"), "kept": self.config.model_for("chat")}
            tag, vision = str(made["tag"]), False
        previous = self.config.model_for("chat")
        return self._try_and_save(tag, ctx, previous, catalog_key=model.key, vision=vision,
                                  status=model.status, remembered_first=remembered_first)

    def _try_and_save(self, tag: str, ctx: int, previous: str, *, catalog_key: str, vision: bool,
                      status: str, remembered_first: bool = False) -> dict[str, Any]:
        with self._apply_lock:
            result = self._measure_and_save(tag, ctx, previous, catalog_key=catalog_key, vision=vision, status=status,
                                            remembered_first=remembered_first)
        if not result.get("ok") and previous and _bare_tag(previous) != _bare_tag(tag):
            # ★ 2026-09-29 밤: 교체가 실패하면 **옛 모델을 도로 올려 둔다.** 재기 전에 옛 모델을 내리고(`_unload(previous)`)
            #   새 모델도 내리니 GPU 가 빈 채로 끝났고, 대표의 다음 질문이 3.8 을 처음부터 올리느라 70~90초 가만히 있었다
            #   (21:35·21:38·21:51·21:54 네 번 같은 모양). 빈 prompt 는 모델만 올린다 — 대화와 같은 창·keep_alive 로.
            threading.Thread(target=self._rewarm, args=(previous,), name="setup-rewarm-previous", daemon=True).start()
        return result

    def _rewarm(self, tag: str) -> None:
        try:
            self._post(f"{self.base_url}/api/generate", {
                "model": tag, "prompt": "", "keep_alive": self.config.ollama_keep_alive,
                "options": {"num_ctx": int(self.config.num_ctx_for("chat"))},
            }, 300.0)
        except Exception:  # noqa: BLE001 — 못 올려도 다음 질문이 올린다(느릴 뿐)
            pass

    def _way_out(self, catalog_key: str) -> dict[str, Any]:
        """못 올렸을 때의 두 길(`way_out`). 안내를 만들다 틀어져도 적용의 결과를 꺾지 않는다 — 빈 값을 준다."""
        try:
            tags = self._get(f"{self.base_url}/api/tags") or {}
            installed = {str(row.get("name") or "") for row in tags.get("models") or []}
            return way_out(catalog_key, installed=installed)
        except Exception:  # noqa: BLE001 — 안내는 덤이다
            return {}

    def _unload(self, tag: str) -> None:
        if not tag:
            return
        try:
            self._post(f"{self.base_url}/api/generate", {"model": tag, "keep_alive": 0, "prompt": ""}, 60.0)
        except Exception:  # noqa: BLE001 — 안 떠 있었으면 내릴 것도 없다
            pass

    def _unload_others(self, tag: str) -> list[str]:
        """같은 Ollama 에 올라와 있는 **다른** 모델을 내린다. 내린 이름들 — 못 읽으면 빈 목록(재기는 그대로 간다)."""
        try:
            rows = (self._get(f"{self.base_url}/api/ps") or {}).get("models") or []
        except Exception:  # noqa: BLE001
            return []
        unloaded: list[str] = []
        for row in rows:
            name = str(row.get("name") or row.get("model") or "")
            if not name or _bare_tag(name) == _bare_tag(tag) or self._same_model_file(row, tag):
                continue
            self._unload(name)
            unloaded.append(name)
        return unloaded

    def _measure_and_save(self, tag: str, ctx: int, previous: str, *, catalog_key: str, vision: bool,
                          status: str, remembered_first: bool = False) -> dict[str, Any]:
        # 코드 역할이 **대화를 따라가고 있었나** — 저장·설정 반영 전에 잡아 둔다(바꾼 뒤엔 옛 대화 모델을 모른다).
        code_follows_chat = bool(previous) and _bare_tag(str(self.config.model_for("code") or "")) == _bare_tag(previous)
        # ★ 2026-09-30: **이 PC 가 이미 아는 것부터** (대표: 「직전에 쓰던 컨텍스트를 넣어 주면 된다」).
        #   ① 이 모델에 사람이 고른 칸이 있으면 그 크기로 바로 — 샌다는 걸 알고 고른 칸이면 줄이지 않는다(뜻이다).
        #   ② 없으면 잰 상한에서 시작 — 들어간다고 이미 잰 크기라 한 번에 올라간다.
        #   ③ 실패로 잰 칸은 다시 시도하지 않는다. 기록이 없을 때만 예전처럼 큰 칸부터 줄여 간다.
        known = read_ceilings(Path(self.config.data_dir)).get(tag) or {}
        failed = {int(step.get("num_ctx") or 0) for step in known.get("steps") or [] if not step.get("passed")}
        chosen = int(known.get("chosen") or 0)
        measured_ceiling = int(known.get("ceiling") or 0)
        accept_spill = False
        # ★ 2026-10-05: 기억은 **모델만 바꿀 때** 쓴다. 전에는 늘 기억이 이겨서, 모델 카드에서 64K·128K 를 골라 적용해도
        #   「성공」이라면서 예전에 쓰던 32K 로 올라왔다(가짜 홈 실측: 64K → 32K, 128K → 32K). 사람이 지금 고른 칸이 기억보다 먼저다.
        if chosen and (remembered_first or ctx == chosen):
            ctx, accept_spill = chosen, True
        elif measured_ceiling:
            ctx = min(ctx, measured_ceiling)
        candidates = [(tag, ctx, catalog_key, vision, status)]
        # ★ 32K 보다 큰 창이 새면 **같은 모델을 한 칸씩 줄여** 잰다(128K → 64K → 32K). 대표 09-29: 「새면 그 전 단계로」.
        #   3.6·128K 가 7.5% 새자 작은 모델 목록이 없어 곧장 거절했다 — 64K 면 다 들어가는데 재 보지도 않았다.
        #   32K 이하에서 새면 예전 그대로 작은 모델로 간다(8GB 노트북: 창을 더 깎는 것보다 작은 모델이 낫다).
        candidates += [(tag, step, catalog_key, vision, status) for step in (131072, 65536, 32768)
                       if step < ctx and step not in failed]
        # 대화 길이를 깎기 전에 작은 모델을 32K에서 잰다. 목록 밖 태그는 자동 교체하지 않는다.
        smaller = {
            "gemma4-26b-qat": ("qwen3.5-9b", "qwen3.5-4b", "qwen3.5-2b"),
            "qwen3.5-9b": ("qwen3.5-4b", "qwen3.5-2b"),
            "qwen3.5-4b": ("qwen3.5-2b",),
        }
        for key in smaller.get(catalog_key, ()):
            model = by_key(key)
            if model is not None:
                candidates.append((self._tag_for(model.ollama_tag), 32768, key, model.vision, model.status))
        if previous != tag:
            self._unload(previous)
        warnings: list[str] = []
        attempts: list[dict[str, Any]] = []
        #: 모델마다 한 번만 — 미리 내다보기를 재 보고 빠르면 기본값에 심는다(`settle_mtp`). 창을 줄여 다시 잴 때는 안 한다.
        mtp_by_tag: dict[str, dict[str, Any]] = {}
        projector_by_tag: dict[str, dict[str, Any]] = {}
        for index, (tag, ctx, catalog_key, vision, status) in enumerate(candidates):
            if index:
                tags = self._get(f"{self.base_url}/api/tags") or {}
                names = {m.get("name") for m in tags.get("models") or []}
                if tag not in names and f"{tag}:latest" not in names:
                    self._pulls[catalog_key] = {"model_key": catalog_key, "status": "pulling", "completed": 0, "total": 0}
                    self._pull(catalog_key, tag)
                    if self._pulls[catalog_key]["status"] != "done":
                        attempts.append({"model": tag, "error": "fallback_download_failed"})
                        continue
            if tag not in mtp_by_tag:
                # 목록이 그림 부속을 따로 붙이라고 한 모델이면 먼저 붙인다(붙인 뒤의 크기로 재야 한다). 못 붙였으면 그림 없이 간다.
                spec = by_key(catalog_key)
                if spec is not None and spec.projector_tag and spec.ollama_tag == tag:
                    projector_by_tag[tag] = self.ensure_projector(tag, spec.projector_tag)
                    if not projector_by_tag[tag].get("vision"):
                        vision = False
                mtp_by_tag[tag] = self.settle_mtp(tag, ctx)
            elif tag in projector_by_tag and not projector_by_tag[tag].get("vision"):
                vision = False
            self._publish("setup_model_measuring", {"model": tag, "num_ctx": ctx, "attempt": index + 1})
            bench = micro_bench(self.base_url, tag, ctx, post=self._post)
            self.last_bench = bench
            if not bench.get("ok"):
                self._unload(tag)
                reason = why_apply_failed(bench)
                following = candidates[index + 1] if index + 1 < len(candidates) else None
                # ★ 메모리가 모자라 못 올렸으면 **다음 후보(작은 창·작은 모델)로** 간다 — GPU 에 다 안 올라간 경우와 같은 길.
                #   2026-10-01 밤 RTX 3050 6GB: 4B·32K 가 OOM 으로 실패하자 2B 를 재 보지도 않고 곧장 그만뒀다.
                if reason == "model_out_of_memory" and following is not None:
                    attempts.append({"model": tag, "num_ctx": ctx, "bench": bench, "error": reason})
                    warnings.append(f"{tag} · {ctx // 1024}K는 그래픽카드 메모리가 모자라 올리지 못했습니다 — "
                                    f"{following[0]} {following[1] // 1024}K로 다시 잽니다.")
                    continue
                failed_result: dict[str, Any] = {"ok": False, "error": reason, "bench": bench, "kept": previous,
                                                 "attempts": attempts, "warnings": warnings}
                if reason == "model_out_of_memory":
                    failed_result["gpu_users"] = gpu_users()
                    failed_result["way_out"] = self._way_out(catalog_key)
                return failed_result
            offload = self.gpu_offload(tag)
            # ★ 2026-09-30: 상한 재기(09-29)와 같은 병 — 3.8 이 **생성까지 했는데** 바로 뒤 `/api/ps` 에서 못 읽어
            #   `gpu_measurement_unavailable` 로 세 번 연속 거절됐다(01:27·01:32·01:40, 직접 올려 보면 ps 에 바로 보임).
            #   한 번 못 읽은 것은 안 올라간 증거가 아니다. 상한 재기처럼 몇 번 다시 읽는다.
            for _ in range(3):
                if offload.get("gpu_share") is not None:
                    break
                time.sleep(self._reread_sec)
                offload = self.gpu_offload(tag)
            share = offload.get("gpu_share")
            attempts.append({"model": tag, "num_ctx": ctx, "bench": bench, "offload": offload})
            if share is None:
                self._unload(tag)
                return {"ok": False, "error": "gpu_measurement_unavailable", "kept": previous,
                        "bench": bench, "offload": offload, "attempts": attempts, "warnings": warnings}
            if share >= 1.0 or (index == 0 and accept_spill):
                if share < 1.0:
                    warnings.append(f"{tag} · 지난번에 고른 {ctx // 1024}K 로 올렸습니다 — GPU {share:.1%}, 나머지는 CPU 입니다.")
                break
            following = candidates[index + 1] if index + 1 < len(candidates) else None
            if following and following[0] == tag:
                warnings.append(f"{tag} · {ctx // 1024}K는 GPU에 {share:.1%}만 올라가 한 칸 줄여 {following[1] // 1024}K로 다시 잽니다.")
            else:
                warnings.append(f"{tag} · {ctx // 1024}K는 GPU에 {share:.1%}만 올라가 적용하지 않았습니다. 작은 모델을 재측정합니다.")
            self._unload(tag)
        else:
            return {"ok": False, "error": "model_not_fully_on_gpu", "kept": previous,
                    "attempts": attempts, "warnings": warnings, "way_out": self._way_out(catalog_key)}
        selection = {
            "catalog_key": catalog_key,
            "chat_model": tag,
            "vision_model": tag if vision else "",
            # 이 모델이 그림을 읽는가 — 화면의 「그림도 읽기 / 글만 읽기」가 이 값을 본다(2026-10-12).
            "reads_pictures": bool(vision),
            # 코드 역할이 대화 모델을 따라가는가 — 사본을 따로 적지 않고 이 한 줄로 적는다(`follow_chat_with_code`).
            "code_follows_chat": bool(code_follows_chat),
            "num_ctx": ctx,
            "status": status,
            "chosen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verified": {"tokens_per_sec": bench.get("tokens_per_sec"), "load_sec": bench.get("load_sec"),
                         "gpu_share": offload.get("gpu_share")},
            # 미리 내다보기를 이 PC 에서 잰 기록 — 켰는지, 끔·켬이 각각 몇 토큰/초였는지.
            "mtp": mtp_by_tag.get(tag) or {"supported": False},
            **({"projector": projector_by_tag[tag]} if tag in projector_by_tag else {}),
        }
        write_selection(Path(self.config.data_dir), selection)
        remember_context_choice(Path(self.config.data_dir), tag, ctx)
        apply_selection_to_config(self.config)
        from .settings import adopt_model_selection

        adopt_model_selection(self.config, vision=vision, code_follows_chat=code_follows_chat)
        self.config.model_source = 'setup'
        self._publish("setup_model_applied", selection)
        return {"ok": True, "selection": selection, "bench": bench, "offload": offload,
                "warnings": warnings, "attempts": attempts}

    def ensure_projector(self, tag: str, projector_tag: str) -> dict[str, Any]:
        """그림 읽는 부속(mmproj)이 없는 모델에 **따로 받아 붙인다.** 이미 그림을 읽으면 아무것도 안 한다.

        ★ 2026-10-08: 첫 추천이 된 Swift 27B 압축판의 저장소에는 부속이 없다. 그대로 권하면 사용자의 모델은 화면·사진을
          못 읽는다(지금 추천보다 못해진다). Ollama 는 부속 파일만 `hf.co/저장소:파일.gguf` 로 따로 받을 수 있고(0.93GB),
          두 파일을 `files` 로 넘겨 **같은 이름으로** 다시 만들면 그림 읽기가 생긴다 — 이 PC 에서 붙여 그림 셋을 맞게 읽었다.
        ★ 어느 부속이 맞는지는 모델마다 다르다. 규칙으로 고르지 않고 목록(`CatalogModel.projector_tag`)이 정해 준 것만 붙인다.
        ★ 못 받거나 못 붙이면 그림 없이 간다 — 모델 적용을 막지 않는다. 결과는 돌려준다.
        """
        def blobs_and_caps(name: str) -> tuple[list[str], list[str], str]:
            shown = self._post(f"{self.base_url}/api/show", {"model": name}, 30.0) or {}
            digests = re.findall(r"^FROM\s+.*sha256[-:]([0-9a-f]{64})", str(shown.get("modelfile") or ""), re.M)
            return list(dict.fromkeys(digests)), [str(c) for c in shown.get("capabilities") or []], str(shown.get("parameters") or "")

        try:
            model_blobs, capabilities, parameters = blobs_and_caps(tag)
            if "vision" in capabilities:
                return {"attached": False, "already": True, "vision": True}
            if not model_blobs:
                return {"attached": False, "vision": False, "error": "model_blob_not_found"}
            self._publish("setup_model_measuring", {"model": tag, "attempt": 0, "what": "projector"})
            pulled = self._post(f"{self.base_url}/api/pull", {"model": projector_tag, "stream": False}, 3600.0) or {}
            if str(pulled.get("status") or "") != "success":
                return {"attached": False, "vision": False, "error": "projector_download_failed"}
            projector_blobs, _caps, _params = blobs_and_caps(projector_tag)
            if not projector_blobs:
                return {"attached": False, "vision": False, "error": "projector_blob_not_found"}
            made = self._post(f"{self.base_url}/api/create", {
                "model": tag, "stream": False,
                "files": {"model.gguf": "sha256:" + model_blobs[0], "mmproj.gguf": "sha256:" + projector_blobs[0]},
                "parameters": parse_model_parameters(parameters),
            }, 300.0) or {}
            if str(made.get("status") or "") != "success":
                return {"attached": False, "vision": False, "error": "attach_failed"}
            _blobs, capabilities, _params = blobs_and_caps(tag)
            return {"attached": "vision" in capabilities, "vision": "vision" in capabilities}
        except Exception as exc:  # noqa: BLE001 — 그림 부속 때문에 모델 적용을 죽이지 않는다
            return {"attached": False, "vision": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def text_only_tag(self, source_tag: str, name: str) -> dict[str, Any]:
        """같은 모델 파일로 **그림 부속만 뺀 이름**을 이 PC 의 Ollama 에 만든다. 이미 있으면 그대로 쓴다.

        ★ 2026-10-12 대표: 「16GB 는 굳이 그림을 봐야 하나 — 켜고 끌 수 있게」. 그림 부속은 우리가 따로 받아 붙인 것이라
          (`ensure_projector`) 떼는 것도 같은 길의 거꾸로다: 모델 파일 하나만으로 다른 이름을 만든다. **새로 받는 것은 없고
          지우는 것도 없다** — 원래 이름(그림 읽는 것)은 그대로 남아, 다시 켜면 그쪽으로 돌아간다.
        ★ 그날 3090 에서 잰 것: 부속을 떼면 1.1GB 쯤 비고, 창을 48K → 64K 로 넓혀도 원래보다 덜 쓴다. 16GB 조건의 가격 조사
          세 과제에서 그림 없는 64K 가 세 판 모두 세 줄(그림 있는 48K 는 두 판).
        ★ 모델 파일이 어느 것인지는 크기로 가른다(큰 쪽이 모델). 크기를 못 읽으면(Ollama 가 다른 PC 에 있다) 첫 줄이 모델이다 —
          `ensure_projector` 가 만들 때 그 순서로 넣는다.
        """
        def show(model: str) -> dict[str, Any]:
            return self._post(f"{self.base_url}/api/show", {"model": model}, 30.0) or {}

        try:
            source = show(source_tag)
        except Exception:  # noqa: BLE001 — 못 물어본 것도 결과다
            return {"ok": False, "error": "model_not_installed"}
        blobs = re.findall(r"^FROM\s+(.*sha256[-:]([0-9a-f]{64}))\s*$", str(source.get("modelfile") or ""), re.M)
        if not blobs:
            return {"ok": False, "error": "model_blob_not_found"}
        sized: list[tuple[int, str]] = []
        for path, digest in blobs:
            try:
                sized.append((Path(path.strip().replace("sha256:", "sha256-")).stat().st_size, digest))
            except OSError:
                sized = []
                break
        model_blob = max(sized)[1] if sized else blobs[0][1]
        try:
            existing = show(name)
        except Exception:  # noqa: BLE001 — 아직 안 만든 이름
            existing = {}
        capabilities = [str(c) for c in existing.get("capabilities") or []]
        if capabilities and "vision" not in capabilities and model_blob in str(existing.get("modelfile") or ""):
            return {"ok": True, "tag": name, "created": False}
        # 공식 태그는 말하는 틀을 모델 파일이 아니라 태그에 적어 둔다(`renderer` · `parser`). 파일만으로 다시 만들면 그 틀이
        # 떨어져 도구 쓰기가 사라질 수 있다 — 원래 이름이 그 칸을 갖고 있으면 그대로 싣는다. 허깅페이스에서 받은 것은
        # 그 칸이 비어 있어 예전과 같은 요청이 나간다.
        carried = {field: str(source.get(field)) for field in ("renderer", "parser") if source.get(field)}
        try:
            made = self._post(f"{self.base_url}/api/create", {
                "model": name, "stream": False, "files": {"model.gguf": "sha256:" + model_blob},
                "parameters": parse_model_parameters(str(source.get("parameters") or "")),
                **carried,
            }, 300.0) or {}
            if str(made.get("status") or "") != "success":
                return {"ok": False, "error": "text_only_create_failed"}
            capabilities = [str(c) for c in show(name).get("capabilities") or []]
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "text_only_create_failed", "detail": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if "vision" in capabilities or "tools" not in capabilities:
            # 부속이 안 떨어졌거나(그림이 모델 파일 안에 든 모델) 도구 쓰기가 사라졌다 — 그 이름으로는 일을 못 시킨다.
            return {"ok": False, "error": "text_only_not_usable", "capabilities": capabilities}
        return {"ok": True, "tag": name, "created": True}

    def settle_mtp(self, tag: str, ctx: int) -> dict[str, Any]:
        """미리 내다보기(MTP)를 **이 PC 에서 재 보고** 빠를 때만 그 모델의 기본값에 심는다.

        ★ 2026-10-08 실측(RTX 3090): 같은 27B 가 끔 40 → 켬 66 토큰/초. 그런데 허깅페이스에서 받은 파일에는 이 설정이
          안 붙어 와서, 고르개로 받은 사용자는 우리가 잰 것보다 느린 모델을 썼다.
        ★ **아무 모델에나 켜면 안 된다.** 파일에 표시(`…nextn_predict_layers`)가 없는 모델도 Ollama 는 거절하지 않고
          그냥 느려진다(9B 99 → 68). 표시가 있어도 느려지는 모델이 있다(35B A3B 141 → 101). 그래서 표시가 있을 때만
          끔·켬을 재고, 뚜렷이 빠를 때만 켠다.
        ★ 요청마다 옵션으로 붙이지 않고 **모델의 기본값**에 심는다(같은 이름으로 다시 만든다 — 파일은 그대로, 설정
          한 줄만 는다). 요청이 Ollama 로 나가는 자리가 여럿이라 한 곳만 빠뜨려도 모델이 계속 다시 올라간다.
        ★ 이미 값이 적혀 있으면(만든 사람이나 사용자가 정한 것) 건드리지 않는다.
        """
        try:
            shown = self._post(f"{self.base_url}/api/show", {"model": tag}, 30.0) or {}
        except Exception as exc:  # noqa: BLE001 — 못 물어봤으면 안 켠다
            return {"supported": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        layers = 0
        for key, value in (shown.get("model_info") or {}).items():
            if str(key).endswith("nextn_predict_layers"):
                try:
                    layers = max(layers, int(value or 0))
                except (TypeError, ValueError):
                    continue
        if layers < 1:
            return {"supported": False}
        parameters = parse_model_parameters(str(shown.get("parameters") or ""))
        if "draft_num_predict" in parameters:
            return {"supported": True, "already": True, "draft_num_predict": parameters.get("draft_num_predict")}
        self._publish("setup_model_measuring", {"model": tag, "num_ctx": ctx, "attempt": 0, "what": "mtp"})
        speeds: dict[str, float] = {}
        for label, value in (("off", 0), ("on", MTP_DRAFT_TOKENS)):
            bench = micro_bench(self.base_url, tag, ctx, post=self._post, extra_options={"draft_num_predict": value},
                                num_predict=200, prompt=MTP_BENCH_PROMPT)
            if not bench.get("ok"):
                # 켠 채로 못 올라가면(메모리 등) 안 켠다. 끈 채로도 못 올라가면 아래 본 측정이 그 이유를 말한다.
                return {"supported": True, "enabled": False, "error": why_apply_failed(bench), "speeds": speeds}
            speeds[label] = float(bench.get("tokens_per_sec") or 0.0)
        record: dict[str, Any] = {"supported": True, "enabled": False, "off_tps": speeds["off"], "on_tps": speeds["on"]}
        if speeds["off"] > 0 and speeds["on"] >= speeds["off"] * MTP_MIN_GAIN:
            try:
                made = self._post(f"{self.base_url}/api/create", {
                    "model": tag, "from": tag, "stream": False,
                    "parameters": {**parameters, "draft_num_predict": MTP_DRAFT_TOKENS},
                }, 180.0) or {}
            except Exception as exc:  # noqa: BLE001 — 못 심었으면 끈 채로 간다
                record["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                return record
            record["enabled"] = str(made.get("status") or "") == "success"
            record["draft_num_predict"] = MTP_DRAFT_TOKENS
        return record

    def gpu_offload(self, tag: str) -> dict[str, Any]:
        """Ollama `/api/ps` 로 **실제로** 그래픽카드에 올라간 비율. 모르면 `gpu_share: None`."""
        ps = self._get(f"{self.base_url}/api/ps") or {}
        rows = list(ps.get("models") or [])

        def share_of(row: dict[str, Any], **extra: Any) -> dict[str, Any]:
            size = int(row.get("size") or 0)
            vram = int(row.get("size_vram") or 0)
            return {"gpu_share": min(1.0, vram / size) if size else None, "size": size, "size_vram": vram,
                    "context_length": int(row.get("context_length") or 0), **extra}

        for row in rows:
            if str(row.get("name") or row.get("model") or "") in {tag, f"{tag}:latest"}:
                return share_of(row)
        # ★ 2026-10-01 실측: 같은 모델 파일을 다른 이름으로 가진 PC(이 PC 의 `plopfit-gemma4-qat` 별칭)에서는
        #   별칭이 먼저 떠 있으면 `gemma4:26b-a4b-it-qat` 이 **그 러너로 0.7초 만에 답하고** `/api/ps` 엔 별칭 이름만 보인다.
        #   이름으로만 찾아 「못 잼」 → 마법사 적용 실패(E2E autopilot_applied, 09-30 새벽 3.8 세 번도 같은 모양).
        #   이 함수는 **방금 돌려 보기에 성공한 직후**에만 불린다 — 그때 떠 있는 모델이 하나뿐이고 **같은 모델 파일**
        #   (계열·크기·양자화가 같음)이면 그게 답한 러너다. 다른 모델 하나만 남았으면(우리 것이 밀려남) 여전히 모른다.
        if len(rows) == 1 and self._same_model_file(rows[0], tag):
            only = rows[0]
            return share_of(only, matched="same_file_alias", resident_name=str(only.get("name") or only.get("model") or ""))
        return {"gpu_share": None, "seen": [str(row.get("name") or row.get("model") or "") for row in rows]}

    def _same_model_file(self, row: dict[str, Any], tag: str) -> bool:
        """`/api/ps` 한 줄이 `tag` 와 같은 모델 파일인가 — `/api/tags` 의 details(계열·크기·양자화)가 셋 다 같을 때만."""
        def key(details: Any) -> tuple[str, str, str] | None:
            if not isinstance(details, dict):
                return None
            got = (str(details.get("family") or ""), str(details.get("parameter_size") or ""),
                   str(details.get("quantization_level") or ""))
            return got if all(got) else None

        mine = None
        for model in (self._get(f"{self.base_url}/api/tags") or {}).get("models") or []:
            if str(model.get("name") or "") in {tag, f"{tag}:latest"}:
                mine = key(model.get("details"))
                break
        theirs = key(row.get("details"))
        return mine is not None and mine == theirs

    # ── 컨텍스트 상한 — 이 PC 에서 **실제로 올려 보고** 잰다 (2026-09-23 제품 요청) ─────────────
    def model_max_context(self, tag: str) -> int:
        """모델 파일이 말하는 최대 컨텍스트(`/api/show` 의 `*.context_length`). 모르면 0."""
        try:
            shown = self._post(f"{self.base_url}/api/show", {"model": tag}, 20.0) or {}
        except Exception:  # noqa: BLE001 — 못 물어보면 사다리 끝까지 재 본다
            return 0
        info = shown.get("model_info") or {}
        values = [int(v) for k, v in info.items() if str(k).endswith(".context_length") and str(v).isdigit()]
        return max(values) if values else 0

    def measure_context_ceiling(
        self,
        tag: str | None = None,
        *,
        ladder: tuple[int, ...] = CONTEXT_LADDER,
        busy: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """이 PC 에서 이 모델을 **몇 K 까지 그래픽카드에 온전히** 올릴 수 있나 — 추정이 아니라 실측.

        ## 왜 (2026-09-23)

        재시작하면 모델이 32K 로 올라왔다. 원인은 Ollama 기본값이다 — VRAM 24~48GB 면 32K, 24GB 미만이면
        4K(docs.ollama.com/context-length). `num_ctx` 를 안 보내는 프로그램(클로드 코드의 Anthropic 호환
        요청에는 그 칸이 없다)이 먼저 올리면 그 값이 되고, 온텔릭은 올라와 있는 컨텍스트를 따라간다.
        그리고 우리가 고르던 컨텍스트는 **우리 PC 에서 잰 표**(`model.vram_gb`)였다 — 남의 PC 에선 추정이다.

        ## 어떻게

        사다리 아래부터 한 칸씩: 내리고 → 그 컨텍스트로 **토큰을 실제로 생성**(`micro_bench`) → `/api/ps` 로
        그래픽카드 비율과 실제 잡힌 컨텍스트를 본다. 합격은 셋 다:

            · 그래픽카드에 100% (조금이라도 CPU 로 새면 몇 배 느려진다)
            · Ollama 가 요청한 컨텍스트를 그대로 잡았다 (깎아서 올리면 그 칸은 모르는 것이다)
            · 속도가 **이 PC 의 첫 칸 대비** `CONTEXT_MIN_SPEED_SHARE` 이상 — 절대 기준은 느린 정상 노트북을
              고장이라 불렀다(09-18). 기준은 그 PC 자신이다.

        처음 떨어진 칸에서 멈춘다. 마지막 합격 칸이 상한이다. 끝나면 **상한으로 다시 올려 둔다** — 떨어진 칸이
        CPU 에 반쯤 걸친 채로 남으면 다음 대화가 그걸 따라간다.

        ★ 모델을 내렸다 올렸다 하므로 **다른 일이 돌 때는 재지 않는다**(`busy`).
        ★ 여기서는 저장하지 않는다. 적용은 `apply_context_ceiling` — 사람이 결과를 보고 누른다.
        """
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        tag = str(tag or self.config.model_for("chat") or "").strip()
        if not OLLAMA_TAG.fullmatch(tag):
            return {"ok": False, "error": "bad_tag"}
        if busy is not None and busy():
            return {"ok": False, "error": "busy"}
        if not self._apply_lock.acquire(blocking=False):
            return {"ok": False, "error": "already_measuring"}
        try:
            return self._climb(tag, ladder)
        finally:
            self._apply_lock.release()

    def squeeze_context_ceiling(self, tag: str | None = None, *,
                                busy: Callable[[], bool] | None = None) -> dict[str, Any]:
        """잰 기록의 합격 칸과 첫 불합격 칸 사이를 **두 번만** 더 올려 본다(`SQUEEZE_PROBES` · 사람이 누를 때만).

        처음부터 다시 재지 않는다 — 이미 잰 칸은 사실이다. 끝나면 **지금 적용된 크기**로 다시 올려 둔다(재기와 적용은 따로).
        """
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        tag = str(tag or self.config.model_for("chat") or "").strip()
        if not OLLAMA_TAG.fullmatch(tag):
            return {"ok": False, "error": "bad_tag"}
        record = read_ceilings(Path(self.config.data_dir)).get(tag) or {}
        if not record.get("measured_at"):
            return {"ok": False, "error": "not_measured"}
        gap = squeeze_gap(record)
        if gap is None:
            return {"ok": False, "error": "nothing_to_squeeze"}
        if busy is not None and busy():
            return {"ok": False, "error": "busy"}
        if not self._apply_lock.acquire(blocking=False):
            return {"ok": False, "error": "already_measuring"}
        try:
            steps = [dict(step) for step in record.get("steps") or []]
            baseline = float(record.get("baseline_tokens_per_sec") or 0.0)
            self.context_live = {"model": tag, "model_max": record.get("model_max"), "steps": steps, "loading": 0}
            started = time.monotonic()
            low, high = gap
            stopped = "squeezed"
            for _ in range(SQUEEZE_PROBES):
                middle = _squeeze_mid(low, high)
                if not middle:
                    break
                step = self._probe(tag, middle, steps, baseline)
                if step["passed"]:
                    low = middle
                elif step.get("why") in FIT_REASONS:
                    high = middle
                else:
                    # 올리지도 못했다 — 그 칸이 안 들어간다는 증거가 아니다. 거기서 멈추고 아는 것만 남긴다.
                    stopped = str(step.get("why") or "load_failed")
                    break
            self.context_live["loading"] = -1
            self._unload(tag)
            applied = int(getattr(self.config, "ollama_num_ctx", 0) or 0)
            passed = {int(step.get("num_ctx") or 0) for step in steps if step.get("passed")}
            micro_bench(self.base_url, tag, applied if applied in passed else low, post=self._post,
                        keep_alive=str(getattr(self.config, "ollama_keep_alive", "") or "30m"))
            result = {**record, "ok": True, "ceiling": low, "steps": steps,
                      "squeezed": {"from": gap[0], "to": low, "below": high, "stopped": stopped,
                                   "took_sec": round(time.monotonic() - started, 1),
                                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}}
            _remember_ceiling(Path(self.config.data_dir), result)
            self._publish("setup_context_measured", {k: v for k, v in result.items() if k != "steps"})
            return result
        finally:
            self.context_live = None
            self._apply_lock.release()

    def _probe(self, tag: str, ctx: int, steps: list[dict[str, Any]], baseline: float) -> dict[str, Any]:
        """한 칸: 내리고 → 그 컨텍스트로 실제 생성 → `/api/ps` 로 그래픽카드 비율·잡힌 컨텍스트를 본다."""
        self._publish("setup_context_probe", {"model": tag, "num_ctx": ctx, "phase": "loading"})
        if self.context_live is not None:
            self.context_live["loading"] = ctx
        # 같은 모델이라도 컨텍스트가 다르면 Ollama 는 러너를 새로 띄워야 한다. 스스로 교체를 시작조차 안 한
        # 전례가 있어(8/31) 먼저 내린다 — 이 파일 머리말 2번.
        self._unload(tag)
        # ★ 같은 Ollama 에 **다른 앱이 올려 둔 모델**도 내리고 잰다 (2026-10-25 대표 · 실사용자 PC). 같은 PC 의 다른 앱이 생각 글 번역에
        #   `translategemma:4b`(3.3GB)를 같은 Ollama 에 올린다. 그대로 두고 재면 27B 가 그만큼 모자라 「다 못 올림」 → 9B 로 내려갔을 수 있다.
        #   대화 부르기는 이미 그렇게 한다(`ollama._make_room_for` — Ollama 는 스스로 내리지 않는다 · 08-31 실측). 다른 앱은 다음에 부를 때 다시 올린다.
        made_room = self._unload_others(tag)
        if made_room:
            self._publish("setup_context_probe", {"model": tag, "phase": "made_room", "unloaded": made_room})
        bench = micro_bench(self.base_url, tag, ctx, post=self._post, keep_alive="10m")
        if not bench.get("ok"):
            step = {"num_ctx": ctx, "passed": False, "why": why_apply_failed(bench),
                    "error": str(bench.get("error") or "")[:200]}
        else:
            # ★ 2026-09-29 이 PC 실측: 40K 칸이 112.8 tok/s(가장 빠름)로 **생성까지 했는데** 비율을 못 읽어
            #   「떨어짐」이 됐고, 상한이 36K 에서 멈췄다. 한 번 못 읽은 것은 떨어진 증거가 아니다 — 몇 번 다시 읽고,
            #   그래도 모르면 그때 `/api/ps` 가 보여 준 이름들을 남겨 다음에 원인을 볼 수 있게 한다.
            offload = self.gpu_offload(tag)
            for _ in range(3):
                if offload.get("gpu_share") is not None:
                    break
                time.sleep(self._reread_sec)
                offload = self.gpu_offload(tag)
            share = offload.get("gpu_share")
            speed = float(bench.get("tokens_per_sec") or 0.0)
            loaded = int(offload.get("context_length") or 0)
            why = ""
            if share is None:
                why = "gpu_measurement_unavailable"
            elif share < 0.999:
                why = "not_fully_on_gpu"
            elif loaded and loaded < ctx:
                why = "context_clamped"
            elif baseline and speed < baseline * CONTEXT_MIN_SPEED_SHARE:
                why = "too_slow"
            step = {"num_ctx": ctx, "passed": not why, "why": why, "gpu_share": share,
                    "tokens_per_sec": speed, "load_sec": bench.get("load_sec"), "loaded_ctx": loaded,
                    "vram_gb": round(int(offload.get("size_vram") or 0) / 2**30, 2),
                    "size_gb": round(int(offload.get("size") or 0) / 2**30, 3)}
            if share is None:
                step["ps_seen"] = offload.get("seen") or []
        steps.append(step)
        self._publish("setup_context_probe", {"model": tag, "phase": "measured", **step})
        return step

    def _climb(self, tag: str, ladder: tuple[int, ...]) -> dict[str, Any]:
        """두 배씩 올라가다 처음 떨어지면, **그 사이를 반씩 좁혀** 진짜 상한을 찾는다.

        ★ 2026-09-23 제품 요청: 「칸을 우리가 나눌 필요 없다 — 실측 상한 자체를 잡자」. 두 배 칸만 재면 3090 의
          qwen3.6 은 「32K 합격 · 64K 96.6%」에서 끝나 그 사이(진짜 상한)를 버린다. 합격 칸과 첫 불합격 칸 사이를
          `CONTEXT_STEP` 단위로 이분 탐색한다 — 몇 번(보통 3~4번) 더 올려 볼 뿐이다.
        """
        model_max = self.model_max_context(tag)
        steps: list[dict[str, Any]] = []
        self.context_live = {"model": tag, "model_max": model_max, "steps": steps, "loading": 0}
        baseline = 0.0
        ceiling = 0
        failed_at = 0
        stopped = "ladder_end"
        started = time.monotonic()
        for ctx in ladder:
            if model_max and ctx > model_max:
                stopped = "model_limit"
                break
            step = self._probe(tag, ctx, steps, baseline)
            if not step["passed"]:
                stopped = step["why"]
                failed_at = ctx
                break
            baseline = baseline or float(step.get("tokens_per_sec") or 0.0)
            ceiling = ctx
        # 합격 칸과 첫 불합격 칸 사이를 좁힌다. 첫 칸부터 떨어졌으면 좁힐 사이가 없다(더 작은 모델의 몫이다).
        # ★ 09-29 부터 꺼져 있다(`CONTEXT_REFINE`) — 새면 그 전 칸이 상한이다.
        if CONTEXT_REFINE and ceiling and failed_at:
            low, high = ceiling, failed_at
            while high - low > CONTEXT_STEP:
                middle = (low + high) // 2 // CONTEXT_STEP * CONTEXT_STEP
                if middle <= low:
                    break
                step = self._probe(tag, middle, steps, baseline)
                if step["passed"]:
                    low = middle
                else:
                    high = middle
            ceiling = low
        # 상한으로 다시 올려 둔다. 첫 칸조차 떨어졌으면 내려 둔다 — 반쯤 걸친 러너를 남기지 않는다.
        self.context_live["loading"] = -1  # 「상한으로 다시 올리는 중」
        self._unload(tag)
        if ceiling:
            micro_bench(self.base_url, tag, ceiling, post=self._post,
                        keep_alive=str(getattr(self.config, "ollama_keep_alive", "") or "30m"))
        result = {
            "ok": bool(ceiling), "model": tag, "ceiling": ceiling, "model_max": model_max, "stopped": stopped,
            "steps": steps, "baseline_tokens_per_sec": baseline, "min_speed_share": CONTEXT_MIN_SPEED_SHARE,
            "took_sec": round(time.monotonic() - started, 1),
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if not ceiling:
            # ★ 2026-10-25: 첫 칸이 **올라가지도 못한 것**(시간 초과 · 서버 무응답 · 로드 실패)을 「가장 작은 칸도 안 들어감 —
            #   더 작은 모델을 권함」으로 말했다. 그 말은 올려 보고 그래픽카드에 다 안 들어갔을 때만 맞다. 나머지는 까닭을 그대로 준다.
            result["error"] = "no_context_fits" if stopped in FIT_REASONS else "first_rung_failed"
        else:
            result.update(self._card_record(tag, steps))
        _remember_ceiling(Path(self.config.data_dir), result)
        self.context_live = None
        self._publish("setup_context_measured", {k: v for k, v in result.items() if k != "steps"})
        return result

    def _card_record(self, tag: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """잴 때의 카드 사정 — 30분마다 보는 감시(`context_watch`)가 「그때와 붙은 프로그램이 달라졌나」를 볼 기준점."""
        from .context_watch import model_gpu, others, slope_gb_per_k

        try:
            snapshot = self.gpu_snapshot()
        except Exception:  # noqa: BLE001 — 기준점이 없으면 감시가 「모름」이라 할 뿐이다
            return {}
        gpu = model_gpu(snapshot)
        if gpu is None:
            return {}
        # 「남의 몫 GB」는 남기지 않는다 — 카드 사용량 − size_vram 의 대부분이 Ollama 자신의 버퍼였다(context_watch 머리말).
        return {"gpu_uuid": gpu["uuid"], "gpu_index": gpu["index"],
                "others_apps": others(gpu), "gb_per_k": round(slope_gb_per_k(steps), 5)}

    def apply_context_ceiling(self, tag: str | None = None, num_ctx: int | None = None) -> dict[str, Any]:
        """잰 상한(또는 **잰 칸 하나**)을 이 모델의 컨텍스트로 쓴다. 안 잰 값은 받지 않는다 — 들어가는지 모른다.

        저장 자리는 설정 화면 값 하나다(`ollama_num_ctx`). 설정 층이 맨 마지막에 얹혀 재시작에도 이기고,
        모델을 바꾸면 `adopt_model_selection` 이 이 값을 지운다 — 옛 모델의 상한이 새 모델에 남지 않는다.

        ★ 2026-09-29 대표 요청 「모델 고를 때 컨텍스트를 칸별로」: 상한 하나만 적용하면 「64K 로 빠르게 · 128K 로
          길게」를 못 고른다. 그래서 `num_ctx` 로 **잰 칸 중 하나**를 받는다 — CPU 로 샌 칸도 속도를 보고 고를 수
          있다(느려지는 걸 알고 긴 창을 원하는 사람). 안 잰 크기와 올리지도 못한 칸은 여전히 거절한다.
          자유 입력 칸이 131070 같은 어중간한 값을 만든 적이 있다(09-29 이 PC 설정).
        """
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        tag = str(tag or self.config.model_for("chat") or "").strip()
        measured = read_ceilings(Path(self.config.data_dir)).get(tag) or {}
        ceiling = int(measured.get("ceiling") or 0)
        if not ceiling:
            return {"ok": False, "error": "not_measured"}
        if num_ctx:
            rung = next((step for step in measured.get("steps") or [] if int(step.get("num_ctx") or 0) == int(num_ctx)), None)
            if rung is None:
                return {"ok": False, "error": "not_measured"}
            if not float(rung.get("tokens_per_sec") or 0):
                return {"ok": False, "error": "rung_did_not_load"}
            ceiling = int(num_ctx)
        if _bare_tag(tag) != _bare_tag(self.config.model_for("chat")):
            return {"ok": False, "error": "not_the_chat_model", "chat_model": self.config.model_for("chat")}
        if self._patch_settings is None:
            return {"ok": False, "error": "settings_not_wired"}
        saved = self._patch_settings({"ollama_num_ctx": ceiling})
        if not saved.get("ok"):
            return {"ok": False, "error": str(saved.get("error") or "settings_rejected")}
        # 설정 층은 컨텍스트를 「다시 켜야 반영」으로 둔다. 모델은 방금 상한으로 올려 뒀으니 이 프로세스도 바로 쓴다.
        self.config.ollama_num_ctx = ceiling
        # 다음에 이 모델로 바꾸면 재지 않고 이 크기로 바로 올린다(`_measure_and_save`).
        remember_context_choice(Path(self.config.data_dir), tag, ceiling)
        self._publish("setup_model_applied", {"role": "chat", "chat_model": tag, "num_ctx": ceiling})
        return {"ok": True, "model": tag, "num_ctx": ceiling}

    # ── 목록 밖 모델 (M3) — 이미 받은 모델 · 직접 입력 ───────────────────────────
    def installed_models(self) -> dict[str, Any]:
        """이 PC Ollama 에 있는 모델 전부. **도구 호출이 되는지 Ollama 에 직접 묻는다**(`/api/show`).

        ★ 2026-09-15 실측: 웹 요약은 Gemma 4 의 `tools` 표시를 빠뜨렸는데 `/api/show` 는 있다고 했다.
          받기 전 안내(우리 표)는 안내일 뿐 — 판정은 받은 모델의 `capabilities` 로 한다.
        """
        tags = self._get(f"{self.base_url}/api/tags") or {}
        rows = []
        for model in tags.get("models") or []:
            name = str(model.get("name") or "")
            if not name:
                continue
            capabilities: list[str] = []
            try:
                shown = self._post(f"{self.base_url}/api/show", {"model": name}, 20.0) or {}
                capabilities = [str(c) for c in shown.get("capabilities") or []]
            except Exception:  # noqa: BLE001 — 못 물어본 것도 결과다
                capabilities = []
            catalog = by_tag(name) or by_tag(name.removesuffix(":latest"))
            rows.append({
                "name": name, "size_gb": round(int(model.get("size") or 0) / 2**30, 2),
                "capabilities": capabilities, "tools": "tools" in capabilities,
                "embedding_only": "embedding" in capabilities and "completion" not in capabilities,
                "catalog_key": catalog.key if catalog else "",
                "status": catalog.status if catalog else "unlisted",
            })
        return {"models": rows}

    def picker(self, role: str = "chat") -> dict[str, Any]:
        """머리에 적힌 모델 이름을 눌렀을 때 뜨는 목록 (2026-09-21 제품 요청).

        ## 왜 한 번의 호출인가

        이 목록을 만들려면 세 곳을 봐야 한다 — 우리 카탈로그, 이 PC 의 Ollama, 그리고
        지금 이 역할이 쓰는 모델. 화면이 셋을 따로 부르면 **셋이 서로 다른 순간을
        보게 된다**(받는 중에 특히). 한 번에 만들어 한 번에 준다.

        ## 사람이 직접 받은 모델도 같이 보인다

        사용자는 이미 `ollama pull` 로 자기 모델을 받아 뒀을 수 있다. 그게 목록에
        없으면 「온텔릭에서는 못 쓴다」로 읽힌다 — 쓸 수 있다. 다만 **우리가 능력을
        잰 적이 없다**는 것은 분명히 적는다(`listed: false`, `grade.measured: false`).
        「검증됨」이 VRAM 에 들어간다는 뜻이지 일을 잘한다는 뜻이 아닌 것과 같은 구별이다.

        ## 못 고르는 것은 **왜인지 적어서** 보낸다

        도구를 못 부르는 모델, 임베딩 전용 모델은 고를 수 없다. 그냥 빼 버리면 사용자는
        자기가 받은 모델이 왜 안 보이는지 모른 채 같은 벽에 계속 부딪친다 —
        `blocked` 에 이유를 담아 **보이되 못 누르게** 한다.
        """
        role = role if role in {"chat", "code", "vision"} else "chat"
        current = self.config.model_for(role)
        profile = self.profile()
        budget = usable_budget_gb(profile)
        rows: list[dict[str, Any]] = []
        known: set[str] = set()
        # 같은 파일을 두 이름으로 보여 주면 **사용자가 태그 갈림을 직접 만든다** — 두 이름이
        # 각자 러너를 띄워 서로를 GPU 에서 쫓아낸다(이 파일 머리말 1번, 자비스가 몇 분씩 멈춘 사고).
        # digest 가 같으면 우리 목록의 이름만 남긴다.
        digests = {str(m.get("name") or ""): str(m.get("digest") or "")
                   for m in (self._get(f"{self.base_url}/api/tags") or {}).get("models") or []}
        listed_digests = set()

        for model in catalog_view(profile):
            tag = str(model.get("ollama_tag") or "")
            known.add(_bare_tag(tag))
            if model.get("installed"):
                found = digests.get(tag) or digests.get(f"{tag}:latest")
                if found:
                    listed_digests.add(found)
            rows.append({
                "tag": tag,
                "name": str(model.get("name") or tag),
                "vendor": str(model.get("vendor") or ""),
                "listed": True,
                "installed": bool(model.get("installed")),
                "fits": bool(model.get("fits")),
                "size_gb": float(model.get("download_gb") or 0.0),
                "num_ctx": model.get("largest_fitting_ctx"),
                "vision": bool(model.get("vision")),
                "roles": list(model.get("roles") or []),
                "grade": agent_grade(tag),
                "current": _bare_tag(tag) == _bare_tag(current),
                "blocked": "" if model.get("fits") else "이 PC 그래픽카드 메모리에 안 들어갑니다",
            })

        for row in self.installed_models().get("models", []):
            name = str(row.get("name") or "")
            if not name or _bare_tag(name) in known:
                continue
            if digests.get(name) and digests[name] in listed_digests:
                continue  # 우리 목록의 모델과 같은 파일 — 이름만 다르다
            known.add(_bare_tag(name))
            size = float(row.get("size_gb") or 0.0)
            blocked = ""
            if row.get("embedding_only"):
                blocked = "글을 쓰는 모델이 아닙니다 (임베딩 전용)"
            elif not row.get("tools"):
                blocked = "도구를 부를 수 없어 손자리가 일을 못 합니다"
            elif budget and size > budget:
                blocked = f"이 PC 에 쓸 수 있는 {budget:.1f}GB 를 넘습니다"
            # 손자리가 만든 「글만 읽는」 이름이면 날것의 이름 대신 그 모델의 이름으로 보인다(2026-10-12).
            plain_of = by_key(text_only_key(name)) if text_only_key(name) else None
            # 목록 밖 모델에서 만든 것도 머리(`sonjari-text-`)를 떼고 「글만 읽기」를 붙여 보인다(2026-10-13).
            unlisted_plain = _bare_tag(name)[len(TEXT_ONLY_PREFIX):] if is_text_only_name(name) and not plain_of else ""
            rows.append({
                "tag": name,
                "name": f"{plain_of.name} · 글만 읽기" if plain_of else f"{unlisted_plain} · 글만 읽기" if unlisted_plain else name,
                "vendor": plain_of.vendor if plain_of else "",
                "listed": False,
                "installed": True,
                "fits": not blocked,
                "size_gb": size,
                "num_ctx": None,
                "vision": "vision" in (row.get("capabilities") or []),
                "roles": [],
                "grade": agent_grade(name),
                "current": _bare_tag(name) == _bare_tag(current),
                "blocked": blocked,
            })

        view: dict[str, Any] = {
            "role": role,
            "current": current,
            "budget_gb": budget,
            "satellite": self.is_satellite,
            "models": rows,
            "pulls": dict(self._pulls),
        }
        if role == "code" and not self.is_satellite:
            from .hf_catalog import code_upgrade

            view["suggestion"] = code_upgrade(budget, current, set(digests))
        return view

    def select(self, tag: str, role: str = "chat", num_ctx: int = 0) -> dict[str, Any]:
        """고르개에서 고른 것을 **그 역할에만** 적용한다.

        `chat` 은 기존 적용 경로 그대로다 — 받아 두고, 실제로 토큰을 뽑아 보고, GPU 에
        다 올라갔을 때만 저장한다. `code` 는 설정 한 줄(`model_code`)이라 거기에 쓴다.

        ★ 코드 모델도 **실제로 도는지 먼저 본다.** 저장만 하고 못 도는 모델을 박아 두면
          Code 탭이 통째로 죽는다. 200 은 증거가 아니다 — 이 파일 머리말의 3번.
        """
        tag = str(tag or "").strip()
        role = role if role in {"chat", "code"} else "chat"
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        if not OLLAMA_TAG.fullmatch(tag):
            return {"ok": False, "error": "bad_tag"}
        if role == "chat":
            # 고르개는 **모델을** 고르는 자리다 — 이 모델을 쓰던 크기가 있으면 그것으로(09-30), 없으면 넘어온 크기로.
            return self.apply_tag(tag, int(num_ctx) or 32768, remembered_first=True)

        catalog = by_tag(tag)
        ctx = int(num_ctx) or (max(catalog.vram_gb) if catalog else self.config.num_ctx_for("code"))
        ctx = max(4096, min(int(ctx), 262144))
        try:
            shown = self._post(f"{self.base_url}/api/show", {"model": tag}, 20.0) or {}
        except Exception:  # noqa: BLE001 — 못 물어본 것도 결과다
            return {"ok": False, "error": "model_not_installed"}
        if "tools" not in [str(c) for c in shown.get("capabilities") or []]:
            return {"ok": False, "error": "no_tool_calling"}
        previous = self.config.model_for("code")
        if previous and _bare_tag(previous) != _bare_tag(tag):
            self._unload(previous)
        mtp = self.settle_mtp(tag, ctx)
        bench = micro_bench(self.base_url, tag, ctx, post=self._post)
        self.last_bench = bench
        if not bench.get("ok"):
            self._unload(tag)
            return {"ok": False, "error": why_apply_failed(bench), "bench": bench, "kept": previous}
        if self._patch_settings is None:
            return {"ok": False, "error": "settings_not_wired", "bench": bench}
        saved = self._patch_settings({"model_code": tag})
        if not saved.get("ok"):
            return {"ok": False, "error": str(saved.get("error") or "settings_rejected"), "bench": bench}
        self._publish("setup_model_applied", {"role": "code", "chat_model": tag, "num_ctx": ctx})
        return {"ok": True, "role": "code", "model": tag, "num_ctx": ctx, "bench": bench, "mtp": mtp}

    def start_pull_tag(self, tag: str, apply_ctx: int = 0, role: str = "chat", eyes: bool | None = None) -> dict[str, Any]:
        """직접 입력한 태그 받기. 이름 모양만 검사하고, 크기는 받기 시작하면 Ollama 가 알려 준다.

        `role="code"` 면 다 받은 뒤 **코드 역할에만** 적용한다(대화 모델은 그대로 — 2026-10-01 밤 코드 일 추천).
        `eyes=False` 면 다 받은 뒤 「글만 읽기」로 적용한다(`apply_tag`) — 받는 파일은 같다(그림 부속도 같이 온다).
        """
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        tag = str(tag or "").strip()
        if not OLLAMA_TAG.fullmatch(tag):
            return {"ok": False, "error": "bad_tag"}
        with self._lock:
            state = self._pulls.get(tag)
            if state and state.get("status") == "pulling":
                return {"ok": True, **state}
            state = {"model_key": tag, "status": "pulling", "completed": 0, "total": 0,
                     "detail": "시작합니다", "started_at": time.time()}
            self._pulls[tag] = state
        if role == "code":
            after = lambda: self.select(tag, "code", int(apply_ctx))  # noqa: E731
        else:
            after = (lambda: self.apply_tag(tag, int(apply_ctx), eyes=eyes)) if apply_ctx else None
        threading.Thread(target=self._pull, args=(tag, tag, after), daemon=True).start()
        return {"ok": True, **state}

    def apply_tag(self, tag: str, num_ctx: int = 32768, *, remembered_first: bool = False,
                  eyes: bool | None = None) -> dict[str, Any]:
        """목록 밖 모델 적용. 도구 호출이 안 되는 모델은 **받지 않는다** — 온텔릭이 일을 못 한다."""
        if self.is_satellite:
            return {"ok": False, "error": "satellite_uses_brain_models"}
        tag = str(tag or "").strip()
        if not OLLAMA_TAG.fullmatch(tag):
            return {"ok": False, "error": "bad_tag"}
        catalog = by_tag(tag)
        if catalog is not None:
            requested = int(num_ctx or 0)
            # 표보다 작은 창은 그대로 쓴다 — 예전엔 표에 없으면 **가장 큰 창**으로 바꿔 3.6 이 늘 128K 로 올라 샜다.
            ctx = requested if 4096 <= requested <= max(catalog.vram_gb) else max(catalog.vram_gb)
            # 「글만 읽는」 이름을 집어 왔으면 그 뜻 그대로 — 목록 모델로 풀면서 그림을 다시 붙이지 않는다.
            if eyes is None and text_only_key(tag):
                eyes = False
            return self.apply(catalog.key, ctx, remembered_first=remembered_first, eyes=eyes)
        data_dir = Path(self.config.data_dir)
        if eyes is True and is_text_only_name(tag):
            # 「글만 읽는」 이름을 쓰다가 「그림도 읽기」로 돌아간다 — 그 이름이 나온 원래 이름으로 간다.
            source = read_text_only_sources(data_dir).get(_bare_tag(tag), "")
            if not source:
                return {"ok": False, "error": "text_only_source_unknown", "kept": self.config.model_for("chat")}
            tag = source
        try:
            shown = self._post(f"{self.base_url}/api/show", {"model": tag}, 20.0) or {}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "model_not_installed"}
        capabilities = [str(c) for c in shown.get("capabilities") or []]
        if "tools" not in capabilities:
            return {"ok": False, "error": "no_tool_calling", "capabilities": capabilities}
        vision = "vision" in capabilities
        if eyes is False and vision:
            # ★ 2026-10-13: 목록 밖 모델도 「글만 읽기」로 올린다 — 허깅페이스에서 받은 것은 그림 부속이 따로 온다.
            #   그림이 모델 파일 안에 든 모델은 뗄 수 없다. 말없이 그림을 단 채 올리지 않고 **못 한다고 돌려준다** —
            #   사람은 자리를 아끼려고 끈 것이라, 조용히 켠 채 올리면 다 못 올라간 까닭을 알 수 없다.
            if not self.eyes_of(tag)["separable"]:
                return {"ok": False, "error": "pictures_inside_model_file", "kept": self.config.model_for("chat")}
            source = tag
            made = self.text_only_tag(source, text_only_name_for_tag(source))
            if not made.get("ok"):
                return {"ok": False, "error": str(made.get("error") or "text_only_failed"), "kept": self.config.model_for("chat")}
            tag, vision = str(made["tag"]), False
            remember_text_only_source(data_dir, tag, source)
        ctx = max(4096, min(int(num_ctx or 32768), 262144))
        previous = self.config.model_for("chat")
        return self._try_and_save(tag, ctx, previous, catalog_key="", vision=vision,
                                  status="unlisted", remembered_first=remembered_first)

    def _tag_for(self, catalog_tag: str) -> str:
        tags = self._get(f"{self.base_url}/api/tags") or {}
        configured = [self.config.model_for(role) for role in ("chat", "vision", "code")]
        return resolve_tag(catalog_tag, list(tags.get("models") or []), [c for c in configured if c])


def _stream_lines(url: str, body: dict[str, Any]):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=3600) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if line:
                yield json.loads(line)


__all__ = [
    "CATALOG", "SetupService", "apply_selection_to_config", "read_selection",
    "resolve_tag", "write_selection",
]
