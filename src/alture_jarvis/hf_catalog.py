"""허깅페이스에서 직접 고르기 — GGUF 모델과 양자화를 사용자가 고른다 (2026-10-01 밤 대표 결정).

왜: 헤르메스는 사용자가 모델을 고르는 하네스라 결과가 나쁘면 「모델이 약하네」로 받는다. 손자리는 마법사가 골라 줘서
「손자리가 약하네」가 된다(§55-13). 추천은 그대로 두고, 그 옆에 **이 PC 에 들어가는 GGUF 를 사용자가 직접 고르는 길**을 연다.

허깅페이스가 내려받기 **전에** 알려 주는 것만 쓴다(2026-10-01 실측 — 목록 한 번 0.35초):
- 목록 API `expand[]=gguf` → 파라미터 수 · 구조 · 최대 컨텍스트 · **채팅 템플릿**(여기에 `tools` 가 있으면 도구 호출 형식을 안다)
- 파일 목록 API `tree/main` → 양자화 파일별 크기

크기에 맞는지는 **추정**이다(파일 크기 + 실행 여유). 진짜 판정은 적용할 때 실제로 올려 보고 재는 기존 장치가 한다
(`_measure_and_save` — GPU 에 다 올라가는지 · 메모리 부족이면 다음 후보 · 도구 호출 확인). 화면은 「≈」로 적는다.

회사망에서 막힐 수 있다(10-01 GitHub API 403). 그때는 `hf_unreachable` — 화면은 직접 입력으로 안내한다.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

HF_API = "https://huggingface.co/api/models"
#: 파일 크기 위에 더하는 실행 여유(GB) — 컨텍스트 KV · 런타임. 하이브리드 구조는 더 작고 큰 밀집 모델은 더 크다.
#: 추정이라 화면은 「≈」로 쓰고, 넘치는지는 적용할 때 실제로 잰다.
#: ★ 2026-10-03 (레딧 댓글 「약속한 컨텍스트에서 KV 여유를 봐라」): 여유는 **적용할 대화 길이**에 따라 다르다.
#:   설정 화면은 20GB 이상 카드면 64K 로 적용하는데 판정은 32K 여유(1.2GB)로 하고 있었다. 런타임 0.4GB + 32K 마다 KV 0.8GB.
DEFAULT_CTX = 32768


def run_margin_gb(ctx: int = DEFAULT_CTX) -> float:
    return round(0.4 + 0.8 * max(int(ctx or DEFAULT_CTX), 8192) / 32768, 1)


RUN_MARGIN_GB = run_margin_gb(DEFAULT_CTX)
#: 여유가 이만큼만 남아도 「빠듯함」으로 보여 준다(컨텍스트를 줄이면 들어갈 수 있다).
TIGHT_MARGIN_GB = 0.4
CACHE_SEC = 600.0
_TIMEOUT = 8.0

#: 파일 이름 끝의 양자화 표식. `Qwen3.8-27B-UD-IQ3_S.gguf` → `UD-IQ3_S`, `model.Q4_K_M.gguf` → `Q4_K_M`.
_QUANT = re.compile(r"(?:^|[-_.])((?:UD-)?(?:I?Q\d(?:_[A-Z0-9]+)*|BF16|F16|F32|MXFP4(?:_MOE)?))\.gguf$", re.IGNORECASE)
_SHARD = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.IGNORECASE)
#: 미리 내다보기(MTP) 머리를 **따로 넣은** 파일 — `…IQ3_S-mtp.gguf`. 같은 양자화의 일반 파일에는 그 머리가 없다.
#:
#: ★ 2026-10-08: `_QUANT` 가 양자화 이름 바로 뒤 `.gguf` 만 받아 이 파일들이 목록에서 통째로 빠졌다. 고르개로 받으면
#:   일반 파일이 와서, 같은 27B 가 이 PC 에서 66 이 아니라 40 토큰/초로 돌았다(RTX 3090 실측). 켤지 말지는 받은 뒤
#:   `model_setup.settle_mtp` 가 재서 정한다 — 여기서는 켤 수 있는 파일을 받게만 한다.
_MTP_SUFFIX = re.compile(r"-mtp\.gguf$", re.IGNORECASE)
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}")

Fetch = Callable[[str], Any]

# ── 추천 (2026-10-01 밤 대표: 「허깅페이스에서 뜨는 것도 우리가 추천해 주면 된다」) ──────────────────
# **잰 것이 아니라 규칙이다** — 화면은 기준을 같이 적는다. 규칙: 믿을 만한 양자화 제작자 · 개조판 아님 ·
# 이 카드에 3비트 이상 · 그중 많이 받은 순 최대 3개. 우리가 잰 계열이면 따로 표시한다.
#: 양자화 파일을 꾸준히 내는 곳과 모델 회사 공식 계정. 여기 없다고 나쁜 것은 아니다 — 추천 표시만 안 한다.
#: ★ 2026-10-01 밤 조사(허깅페이스 GGUF 저장소 2,103개 · 제작자 641명, 내려받기·좋아요·추천순 상위 1,000씩)로 정했다:
#:   ① 원본을 그대로 양자화해 올리는 곳 — 저장소가 많고 개조판이 주력이 아닌 곳(unsloth 179개·개조 0, bartowski 160개·개조 16%,
#:      MaziyarPanahi 60개·0, ggml-org = llama.cpp 공식, lmstudio-community, ISTA-DASLab = IST 오스트리아 양자화 연구실)
#:   ② 모델 회사 공식 계정 — 한국 회사(LG·네이버·카카오·업스테이지·SKT)도 넣는다: 좋은 것을 내면 바로 추천에 뜨게.
#:   빠진 곳: 개조판이 주력인 곳(huihui-ai 25개 중 24개) · 다시 가르친 파생판(이름이 실제와 다를 수 있다 —
#:   「Qwen3.8-35B-Distill」은 공식 3.8 이 아니라 3.6 35B 의 증류판이었다) · 특수 양자화(mudler 의 APEX — Ollama 호환 미확인).
#: ② 모델 회사 공식 계정.
OFFICIAL_AUTHORS = frozenset({
    "qwen", "google", "mistralai", "microsoft", "ibm-granite", "meta-llama", "nvidia", "deepseek-ai", "ornith-ai",
    "liquidai", "tencent", "allenai", "huggingfacetb", "openai", "zai-org", "moonshotai", "minimaxai",
    "lgai-exaone", "naver-hyperclovax", "kakaocorp", "upstage", "skt",
})
#: ③ 무엇이든 양자화하는 곳 — **원본이 ② 공식 저장소일 때만** 추천한다(카드의 `base_model` 로 본다).
#: ★ 2026-10-03: mradermacher 는 레딧 댓글 셋이 같은 이름을 댔다. 그런데 이름 거름망만 걸어 보니 통과한 10개 중 대부분이
#:   파생판이었다(「…-Claude-4.6-Opus-Reasoning-Distilled」·롤플레이용 「Euryale」·「OBLITERATED」). 이름이 아니라 원본으로 거른다.
NEEDS_OFFICIAL_BASE = frozenset({"mradermacher"})
#: ① 양자화
QUANTIZER_AUTHORS = frozenset({"unsloth", "bartowski", "ggml-org", "lmstudio-community", "maziyarpanahi", "ista-daslab"})
TRUSTED_AUTHORS = frozenset({*QUANTIZER_AUTHORS, *NEEDS_OFFICIAL_BASE, *OFFICIAL_AUTHORS})
#: 개조판 — 안전 장치를 걷어 냈거나 역할극용으로 바꾼 것. 사용자가 고를 수는 있지만 추천하지 않는다.
_MODDED = re.compile(r"uncensor|abliterat|obliterat|heretic|nsfw|roleplay|\brp\b|erotic|jailbreak|lewd|aggressive", re.IGNORECASE)
#: 이 제품에서 실제로 잰 계열(카탈로그 verified) — 저장소 이름에 이 조각이 있으면 「Sonjari 실측 계열」.
_MEASURED_FAMILIES = (("qwen3.5-9b", "Qwen 3.5 9B"), ("qwen3.6-35b-a3b", "Qwen 3.6 35B-A3B"),
                      ("gemma-4-26b-a4b", "Gemma 4 26B"))
MAX_RECOMMENDED = 3


def measured_family(repo: str) -> str:
    low = repo.lower().replace("_", "-")
    for piece, label in _MEASURED_FAMILIES:
        if piece in low:
            return label
    return ""


def model_base(name: str) -> str:
    """같은 모델을 가리키는 이름을 하나로 — `Qwen3.5-9B-GGUF` · `Qwen_Qwen3.5-9B-GGUF`(bartowski) · `Qwen3.5-9B-MTP-GGUF`."""
    base = re.sub(r"[-_.]?gguf$", "", name, flags=re.IGNORECASE).lower()
    base = re.sub(r"^[a-z-]+_(?=[a-z])", "", base)  # bartowski 식 「회사_」 머리
    return re.sub(r"[-_.]mtp$", "", base)


_VERSION_TOKEN = re.compile(r"([A-Za-z]*?)(\d+(?:\.\d+)?)")


def _version_split(name: str) -> tuple[list[str], int]:
    """이름을 `-`·`_` 로 자르고 **판 번호가 든 첫 조각**의 자리를 찾는다(크기 조각 `9B`·`A3B` 는 판이 아니다)."""
    tokens = re.split(r"[-_]", model_base(name))
    for index, token in enumerate(tokens):
        if _VERSION_TOKEN.fullmatch(token) and not token.lower().endswith("b"):
            return tokens, index
    return tokens, -1


def version_of(name: str) -> float:
    """이름의 판 번호 — `Ornith-1.5-9B` → 1.5, `Qwen3.8-27B` → 3.8, `gemma-4-12b-it` → 4. 없으면 0."""
    tokens, index = _version_split(name)
    if index < 0:
        return 0.0
    match = _VERSION_TOKEN.fullmatch(tokens[index])
    return float(match.group(2)) if match else 0.0


def family_key(name: str) -> str:
    """판 번호를 뺀 이름 — `Ornith-1.5-9B` 와 `Ornith-1.0-9B` 를 같은 가족으로."""
    tokens, index = _version_split(name)
    if index >= 0:
        match = _VERSION_TOKEN.fullmatch(tokens[index])
        tokens[index] = (match.group(1) if match else "") + "#"
    # 크기 조각(`35b`)까지만 본다 — 뒤의 `a3b`·`instruct` 유무로 같은 가족이 갈리지 않게(1.0-35B 와 1.5-35B-A3B).
    for cut, token in enumerate(tokens):
        if re.fullmatch(r"\d+(?:\.\d+)?b", token):
            return "-".join(tokens[:cut + 1])
    return "-".join(tokens)


def vision_of(row: dict[str, Any]) -> bool:
    """그림을 볼 수 있나 — **저장소에 화면 읽기 부속(mmproj) 파일이 있는가**로 본다.

    ★ 2026-10-03 (레딧 r/LocalLLM 댓글 「태그를 믿지 말고 실제 설정을 봐라」): 태그(`pipeline_tag`)는 올린 사람이
      적는 값이다. `lmstudio-community/Qwen3.5-9B-GGUF` 는 태그가 비어 「그림 못 봄」으로 나왔는데 mmproj 가 들어 있었다.
      GGUF 저장소엔 원본 config.json 이 없는 일이 많고, Ollama 가 그림을 보려면 결국 이 부속을 같이 받아야 한다 —
      그래서 파일로 본다. 파일 목록이 안 왔을 때만(옛 응답) 태그로 짐작한다.
    """
    siblings = row.get("siblings")
    if isinstance(siblings, list) and siblings:
        names = [str(item.get("rfilename") or "") for item in siblings if isinstance(item, dict)]
        return any("mmproj" in name.lower() and name.lower().endswith(".gguf") and "/" not in name for name in names)
    return str(row.get("pipeline_tag") or "") == "image-text-to-text"


def base_authors(row: dict[str, Any]) -> list[str]:
    """카드에 적힌 원본 모델(`base_model`)의 제작자들. 없으면 빈 목록."""
    card = row.get("cardData")
    base = card.get("base_model") if isinstance(card, dict) else None
    items = base if isinstance(base, list) else [base]
    return [str(item).split("/", 1)[0].lower() for item in items if isinstance(item, str) and "/" in item]


def recommendable(model: dict[str, Any]) -> bool:
    author = model["author"].lower()
    if author in NEEDS_OFFICIAL_BASE:
        bases = model.get("base_authors") or []
        if not bases or not all(base in OFFICIAL_AUTHORS for base in bases):
            return False
    return (author in TRUSTED_AUTHORS and not _MODDED.search(model["repo"])
            and model["tools"] and model["best_bits"] >= 3)


# ── 「추천」 대신 「확인한 사실」 (2026-10-03 레딧 r/LocalLLM 댓글) ─────────────────────
# 「추천」은 우리가 무엇을 확인했는지 말해 주지 않는다. 화면은 **확인한 것만** 하나씩 적는다:
#   official      — 모델 회사 공식 계정이 올린 것(저장소 주인)
#   official_base — 양자화한 곳이지만 카드의 원본(`base_model`)이 전부 공식 저장소
#   pc_measured   — 이 PC 에서 실제로 올려 보고 잰 기록이 있다(`context_ceiling.json`)
# 템플릿은 「도구 칸이 있다」까지만 읽었다 — 실제 대화로 돌려 본 것이 아니라서 「시험함」이라고 쓰지 않는다.


def checks_of(model: dict[str, Any]) -> list[str]:
    author = str(model.get("author") or "").lower()
    checks: list[str] = []
    bases = model.get("base_authors") or []
    if author in OFFICIAL_AUTHORS:
        checks.append("official")
    # ★ 원본 칸만 보면 안 된다(10-03 실측): 개조판(「…-Uncensored」·「abliterated」)도 카드에 원본을 Qwen 공식으로 적는다.
    #   「공식 원본」은 **원본을 그대로 양자화하는 곳**이 올렸고 개조판이 아닐 때만 — 다시 가르친 파생판이 아니라는 뜻이 되게.
    elif (author in QUANTIZER_AUTHORS or author in NEEDS_OFFICIAL_BASE) and not _MODDED.search(str(model.get("repo") or "")) \
            and bases and all(base in OFFICIAL_AUTHORS for base in bases):
        checks.append("official_base")
    if model.get("pc_measured"):
        checks.append("pc_measured")
    return checks


def pc_record(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """이 PC 에서 잰 기록 한 줄 → 화면용 요약. 고르기만 하고 잰 적 없는 줄(`chosen` 만)은 None."""
    if not isinstance(row, dict):
        return None
    passed = [step for step in row.get("steps") or [] if isinstance(step, dict) and step.get("passed")]
    ceiling = int(row.get("ceiling") or 0)
    if not passed and not ceiling:
        return None
    speeds = [float(step.get("tokens_per_sec") or 0) for step in passed if step.get("tokens_per_sec")]
    return {"ceiling": ceiling or max(int(step.get("num_ctx") or 0) for step in passed),
            "tokens_per_sec": round(max(speeds), 1) if speeds else None}


def tag_quant(quant: str) -> str:
    """태그 끝 양자화 조각을 화면 표기로 — Ollama 가 소문자로 적어도 `IQ4_XS` 로."""
    return quant.upper() if re.fullmatch(r"(?i)(?:ud-)?i?q\d\w*|bf16|f16|f32|mxfp4\w*", quant) else quant


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Sonjari-setup", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 — 고정된 허깅페이스 주소만
        return json.loads(response.read().decode("utf-8"))


def bits_of(quant: str) -> float:
    """양자화 이름에서 대략의 비트 — 화면이 「3비트」 묶음으로 보여 주려고. 모르면 0."""
    q = quant.upper().removeprefix("UD-")
    if q in {"BF16", "F16"}:
        return 16.0
    if q == "F32":
        return 32.0
    if q.startswith("MXFP4"):
        return 4.0
    match = re.match(r"I?Q(\d)", q)
    return float(match.group(1)) if match else 0.0


def fit_of(gb: float, usable_gb: float, margin_gb: float = RUN_MARGIN_GB) -> str:
    """`fits`(여유 있게) · `tight`(컨텍스트를 줄이면) · `over`(안 들어감)."""
    if usable_gb <= 0:
        return "over"
    if gb + margin_gb <= usable_gb:
        return "fits"
    if gb + TIGHT_MARGIN_GB <= usable_gb:
        return "tight"
    return "over"


def best_bits_for(params: int, usable_gb: float) -> int:
    """파라미터 수로 이 카드에 들어갈 **가장 높은 비트**(추정). 2비트로도 안 되면 0."""
    if not params or usable_gb <= 0:
        return 0
    for bits in (8, 6, 5, 4, 3, 2):
        # GGUF 실제 크기는 이름 비트보다 조금 크다(임베딩·출력층은 덜 깎는다) — 10% 얹는다.
        if params * (bits + 0.5) / 8 / 1e9 * 1.1 + RUN_MARGIN_GB <= usable_gb:
            return bits
    return 0


class HfCatalog:
    def __init__(self, fetch: Fetch | None = None, clock: Callable[[], float] = time.monotonic,
                 measured: Callable[[], dict[str, Any]] | None = None) -> None:
        self._fetch = fetch or _fetch_json
        self._clock = clock
        #: 이 PC 에서 잰 기록(태그 → 기록). 캐시하지 않는다 — 방금 잰 것이 바로 보여야 한다.
        self._measured = measured or (lambda: {})
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: str, make: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._cache.get(key)
            if hit and self._clock() - hit[0] < CACHE_SEC:
                return hit[1]
        value = make()
        with self._lock:
            self._cache[key] = (self._clock(), value)
        return value

    def _pc_records(self) -> dict[str, dict[str, Any]]:
        """이 PC 에서 잰 기록 — 태그는 소문자로(Ollama 가 대소문자를 바꿔 적는 일이 있다)."""
        try:
            rows = self._measured() or {}
        except Exception:  # noqa: BLE001 — 기록을 못 읽어도 목록은 보여 준다
            return {}
        out: dict[str, dict[str, Any]] = {}
        for tag, row in rows.items() if isinstance(rows, dict) else []:
            record = pc_record(row)
            if record:
                out[str(tag).lower()] = record
        return out

    def search(self, query: str, usable_gb: float, *, sort: str = "downloads", limit: int = 40) -> dict[str, Any]:
        """이 카드에 (2비트로라도) 들어가는 GGUF 저장소. 도구 호출 없는 것·안 들어가는 것은 개수만 센다.

        ★ 기본은 **많이 받은 순**이다. 인기(trending) 순 맨 위에는 개조판(Uncensored 등)이 자주 온다 — 10-01 AWS 에서
          헤르메스의 허깅페이스 검색 1위가 그랬고, 같은 날 이 목록도 그랬다. 인기순은 사람이 골라 볼 수 있다.
        """
        query = " ".join(str(query or "").split())[:80]
        order = "trendingScore" if sort == "trending" else "downloads"
        params = {"filter": "gguf", "sort": order, "limit": str(max(5, min(limit, 60)))}
        if query:
            params["search"] = query
        url = HF_API + "?" + urllib.parse.urlencode(params) + "".join(
            "&expand%5B%5D=" + part
            for part in ("gguf", "downloads", "likes", "lastModified", "pipeline_tag", "siblings", "cardData"))
        try:
            rows = self._cached("search:" + url, lambda: self._fetch(url))
        except Exception as exc:  # noqa: BLE001 — 막힌 것도 답이다(회사망·오프라인)
            return {"ok": False, "error": "hf_unreachable", "detail": str(exc)[:200], "models": []}
        models: list[dict[str, Any]] = []
        no_tools = too_big = 0
        for row in rows if isinstance(rows, list) else []:
            repo = str(row.get("id") or "")
            if not _REPO.fullmatch(repo):
                continue
            gguf = row.get("gguf") or {}
            total = int(gguf.get("total") or 0)
            template = str(gguf.get("chat_template") or "")
            tools = "tools" in template
            best = best_bits_for(total, usable_gb)
            if not tools:
                no_tools += 1
                continue
            if total and best == 0:
                too_big += 1
                continue
            models.append({
                "repo": repo,
                "author": repo.split("/", 1)[0],
                "name": repo.split("/", 1)[1],
                "params_b": round(total / 1e9, 1) if total else None,
                "architecture": str(gguf.get("architecture") or ""),
                "context_max": int(gguf.get("context_length") or 0),
                "tools": tools,
                "best_bits": best,
                "downloads": int(row.get("downloads") or 0),
                "likes": int(row.get("likes") or 0),
                "updated": str(row.get("lastModified") or "")[:10],
                "vision": vision_of(row),
                "base_authors": base_authors(row),
            })
        on_pc = self._pc_records()
        for model in models:
            model["measured_family"] = measured_family(model["repo"])
            model["modded"] = bool(_MODDED.search(model["repo"]))
            model["recommended"] = False
            prefix = f"hf.co/{model['repo']}:".lower()
            mine = [(tag.rsplit(":", 1)[-1], record) for tag, record in on_pc.items() if tag.startswith(prefix)]
            if mine:
                quant, record = max(mine, key=lambda item: item[1]["ceiling"])
                model["pc_measured"] = {"quant": tag_quant(quant), **record}
            model["checks"] = checks_of(model)
        # 같은 모델을 제작자만 달리해 두 번 추천하지 않는다(unsloth·lmstudio 의 같은 27B — 10-01 실측).
        picks: list[dict[str, Any]] = []
        seen_base: set[str] = set()
        candidates = [m for m in models if recommendable(m)]
        # 같은 이름의 **새 판이 후보에 있으면 옛 판은 추천하지 않는다** — 「Ornith」로 찾자 1.0 9B 가 1.5 9B 와 나란히 추천에 떴다(10-01 밤).
        newest = {family_key(m["name"]): max(version_of(c["name"]) for c in candidates if family_key(c["name"]) == family_key(m["name"]))
                  for m in candidates}
        for model in sorted(candidates, key=lambda m: -m["downloads"]):
            if version_of(model["name"]) < newest[family_key(model["name"])]:
                continue
            base = family_key(model["name"])  # 같은 모델의 다른 양자화판(unsloth·ISTA-DASLab 27B)도 한 번만
            if base in seen_base:
                continue
            seen_base.add(base)
            picks.append(model)
            if len(picks) >= MAX_RECOMMENDED:
                break
        for model in picks:
            model["recommended"] = True
        # 이 PC 에서 잰 것 → 기준 통과 순으로 위로 — 같은 정렬 안에서 순서는 유지한다.
        models.sort(key=lambda m: (not m.get("pc_measured"), not m["recommended"]))
        return {"ok": True, "query": query, "sort": "trending" if order == "trendingScore" else "downloads",
                "usable_gb": usable_gb, "models": models,
                "hidden": {"no_tools": no_tools, "too_big": too_big}}

    def files(self, repo: str, usable_gb: float, ctx: int = DEFAULT_CTX) -> dict[str, Any]:
        """한 저장소의 양자화 파일 — 크기 순, **적용할 대화 길이(`ctx`)에서** 이 카드에 맞는지(추정)와 Ollama 받기 이름까지."""
        repo = str(repo or "").strip()
        ctx = max(8192, min(int(ctx or DEFAULT_CTX), 262144))
        margin = run_margin_gb(ctx)
        if not _REPO.fullmatch(repo):
            return {"ok": False, "error": "bad_repo", "files": []}
        url = f"{HF_API}/{repo}/tree/main"
        try:
            rows = self._cached("tree:" + url, lambda: self._fetch(url))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "hf_unreachable", "detail": str(exc)[:200], "files": []}
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        on_pc = self._pc_records()
        # ★ 화면 읽기 부속(mmproj)도 Ollama 가 **같이 받아 같이 올린다** (2026-10-01 밤 실측: UD-Q3_K_XL 파일 13.15GB →
        #   받은 크기 14.08GB). 이걸 빼면 「들어간다」가 1GB 낙관적이다. 부속이 여럿이면 F16(Ollama 가 고르는 것), 없으면 가장 작은 것.
        projectors = [(str(r.get("path") or ""), int(r.get("size") or 0)) for r in (rows if isinstance(rows, list) else [])
                      if "mmproj" in str(r.get("path") or "").lower() and str(r.get("path") or "").lower().endswith(".gguf")
                      and "/" not in str(r.get("path") or "")]
        f16 = [size for path, size in projectors if "f16" in path.lower()]
        projector_gb = round((f16[0] if f16 else min((size for _, size in projectors), default=0)) / 1e9, 2)
        # 같은 양자화의 MTP 파일(`…-mtp.gguf`) — 있으면 그쪽을 받는다. 태그는 파일 이름 꼴이어야 Ollama 가 그 파일을 집는다
        # (`:IQ3_S` 는 일반 파일로 풀린다).
        mtp_files: dict[str, tuple[str, int]] = {}
        for row in rows if isinstance(rows, list) else []:
            path = str(row.get("path") or "")
            if "/" in path or not _MTP_SUFFIX.search(path) or "mmproj" in path.lower():
                continue
            plain = _QUANT.search(_MTP_SUFFIX.sub(".gguf", path))
            if plain:
                mtp_files.setdefault(plain.group(1).upper(), (path, int(row.get("size") or 0)))
        listed: list[tuple[str, str, int]] = []  # (양자화, 파일 이름, 크기)
        for row in rows if isinstance(rows, list) else []:
            path = str(row.get("path") or "")
            name = path.rsplit("/", 1)[-1]
            # 화면 읽기용 부속(mmproj)·나눠 올린 파일(Ollama 가 hf.co 로 못 받는다)은 고를 것이 아니다.
            if not name.lower().endswith(".gguf") or "mmproj" in name.lower() or _SHARD.search(name) or "/" in path:
                continue
            match = _QUANT.search(name)
            if match:
                listed.append((match.group(1), name, int(row.get("size") or 0)))
        # MTP 파일만 올린 저장소(일반 파일이 없는 양자화)도 목록에 나온다.
        plain_keys = {quant.upper() for quant, _name, _size in listed}
        for key, (mtp_name, mtp_size) in mtp_files.items():
            if key not in plain_keys:
                quant_only = _QUANT.search(_MTP_SUFFIX.sub(".gguf", mtp_name))
                listed.append((quant_only.group(1) if quant_only else key, _MTP_SUFFIX.sub(".gguf", mtp_name), mtp_size))
        for quant, name, size in listed:
            key = quant.upper()
            if key in seen:
                continue
            seen.add(key)
            tag = f"hf.co/{repo}:{quant}"
            mtp = mtp_files.get(key)
            if mtp:
                name, size = mtp
                tag = f"hf.co/{repo}:{name}"
            file_gb = round(size / 1e9, 2)
            gb = round(file_gb + projector_gb, 2)  # 받고 올리는 크기 = 모델 파일 + 화면 읽기 부속
            entry = {"quant": quant, "file": name, "gb": gb, "file_gb": file_gb, "projector_gb": projector_gb,
                     "bits": bits_of(quant), "fit": fit_of(gb, usable_gb, margin), "tag": tag, "mtp_file": bool(mtp)}
            record = on_pc.get(tag.lower())
            if record:
                entry["pc_measured"] = record
            files.append(entry)
        files.sort(key=lambda f: f["gb"])
        # 양자화 추천: **여유 있게 들어가는 것 중 가장 큰 것**. 1비트는 품질이 크게 떨어져 추천하지 않는다.
        fitting = [f for f in files if f["fit"] == "fits" and f["bits"] >= 2]
        for f in files:
            f["recommended"] = bool(fitting) and f is fitting[-1]
        return {"ok": True, "repo": repo, "usable_gb": usable_gb, "files": files,
                "margin_gb": margin, "ctx": ctx, "vision": bool(projectors)}


# ── 코드 일 추천 (2026-10-01 밤 대표: 「16GB 는 9B 가 메인, 코드 일을 할 때는 '이 모델을 설치하세요'」) ─────────────
# 대화·브라우저는 작은 모델로 잘 된다(9B 조사→문서 9/10). 처음 보는 코드는 9B 가 약했다(10-01 베타 실사용 1판).
# 코드 역할(`model_code`)만 큰 모델로 바꾸면 대화 모델은 그대로다 — 손자리는 역할마다 모델을 따로 둔다.
# 후보는 **규칙**이다(이 카드에 여유 있게 들어가는 가장 큰 27B 양자화). 16GB 측정(2026-10-02 새벽)이 끝나면 근거를 바꾼다.
CODE_UPGRADES: tuple[tuple[str, str, float, float], ...] = (
    # (Ollama 태그, 화면 이름, 받는 크기 GB, 파라미터 B) — 크기는 2026-10-01 허깅페이스 파일 목록 실측 + 화면 읽기 부속 0.93GB
    # (UD-Q3_K_XL 은 실제로 받아 14.08GB 확인). 16GB 측정(10-02 새벽)이 Q3_K_XL 로 돈다 — 100% 올라가면 여유 규칙을 푼다.
    ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M", "Qwen 3.8 27B · 4비트", 17.39, 27.3),
    ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL", "Qwen 3.8 27B · 3비트", 14.08, 27.3),
    ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S", "Qwen 3.8 27B · 3비트(IQ3_S)", 12.97, 27.3),
    ("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_XXS", "Qwen 3.8 27B · 3비트(작게)", 11.86, 27.3),
)
#: ★ 2026-10-02 대표 결정으로 16GB 측정을 미뤘다 — 「재는 중」이라고 적어 두면 거짓이 된다. 안 잰 것은 안 쟀다고,
#:   대가(느려짐·문맥 64K)는 그대로 적는다. 측정이 나오면 이 문장과 `measured` 를 같이 바꾼다.
CODE_UPGRADE_BASIS = ("규칙 추천 — 이 카드에 여유 있게 들어가는 가장 큰 27B 양자화입니다. "
                      "작은 모델보다 코드를 더 잘한다는 측정은 아직 없습니다. 대신 더 느리고, 한 번에 보는 양(문맥)이 64K 로 줄어듭니다.")
_PARAMS_IN_TAG = re.compile(r"(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)


def params_in_tag(tag: str) -> float:
    """태그에 적힌 크기(B). `qwen3.5:9b` → 9, `qwen3.6:35b-a3b` → 35. 모르면 0."""
    found = [float(m.group(1)) for m in _PARAMS_IN_TAG.finditer(str(tag or ""))]
    return max(found) if found else 0.0


def code_upgrade(budget_gb: float, current_code: str, installed: set[str] | frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """지금 코드 모델보다 **훨씬 큰** 모델이 이 카드에 들어가면 그 하나. 이미 크거나(20B 이상) 모르면 권하지 않는다."""
    now = params_in_tag(current_code)
    if not now or now >= 20:
        return None
    for tag, name, gb, params in CODE_UPGRADES:
        if fit_of(gb, budget_gb) == "fits" and params >= now * 2:
            return {"tag": tag, "name": name, "size_gb": gb, "params_b": params, "current": current_code,
                    "current_params_b": now, "installed": tag in installed, "basis": CODE_UPGRADE_BASIS,
                    "measured": False}
    return None



# ── 크기별로 맡길 일 (2026-10-01 밤 대표: 「9B 한테 시킬 일, 20B 이상한테 시킬 일을 나누자 — 4B·8GB 도」) ─────────
# 바깥 AI(클로드 등)가 사용법(`sonjari_guide`)을 읽을 때 **이 PC 의 모델에 맞춰** 붙인다 — 모든 PC 에 같은 문장을 박으면
# 4B 노트북에서도 「조사→문서 9/10」을 믿게 된다. 근거는 잰 것만 적고, 안 잰 칸은 안 쟀다고 적는다.
_TIERS: tuple[tuple[float, str, str, str, str], ...] = (
    # (상한 B, 이름, 맡기기 좋은 일, 당신(바깥 AI)이 직접 할 일, 근거)
    (6.0, "작은 모델(4B 급 · 그래픽카드 8GB 이하)",
     "한두 페이지 찾아 읽고 값 옮기기 · 이 PC 파일 읽고 쓰기 · 띄워 둔 앱을 브라우저로 눌러 보고 확인",
     "여러 사이트를 비교해 정리하는 조사 · 코드 짜기·고치기",
     "4B 는 노트북 8GB 에서 32K·100% GPU 만 확인 — 일 성공률은 아직 안 쟀습니다"),
    (20.0, "중간 모델(9B 급 · 12~16GB)",
     "웹에서 찾아 읽고 표·문서·엑셀로 만들기 · 로그인된 실제 브라우저 일 · 이 PC 파일·문서",
     "새 코드 설계 · 처음 보는 라이브러리·API 코드 — 짠 코드를 손자리에게 쓰게 하세요",
     "9B 조사→문서 9/10 실측 · 2026-10-01 베타 실사용에서 처음 보는 코드(3ds Max 앱 통째)를 망가뜨림(1판)"),
    (1e9, "큰 모델(20B 이상 · 16GB 에 3비트 또는 24GB 이상)",
     "위 전부 + 이미 있는 코드를 고치고 실행해서 확인하기",
     "큰 설계 · 여러 파일에 걸친 대규모 고치기",
     "35B-A3B 조사→문서 10/10 실측 · Ornith 1.5 35B 코딩 사다리 6/6(24GB, 1판씩) · 27B 3비트·16GB 카드 성적은 아직 안 잼"),
)
_CODE_TASK = re.compile(
    r"코드|코딩|버그|함수|클래스|스크립트|리팩터|컴파일|빌드|테스트(?:를|가|\s*실패)|디버그|에러\s*고|"
    r"\.(?:py|ts|tsx|js|cs|cpp|java|go|rs)\b|\b(?:code|bug|refactor|script|compile|debug)\b",
    re.IGNORECASE,
)


def tier_of(params_b: float) -> tuple[str, str, str, str]:
    for ceiling, name, give, keep, basis in _TIERS:
        if params_b < ceiling:
            return name, give, keep, basis
    return _TIERS[-1][1:]


def looks_like_code_task(text: str) -> bool:
    """맡긴 과제가 코드 일인가 — 모델 권고(`model_hint`)를 붙일지 정하는 데만 쓴다(갈래를 바꾸지 않는다)."""
    return bool(_CODE_TASK.search(str(text or "")))


def model_fit_note(chat_model: str, code_model: str, budget_gb: float, upgrade: dict[str, Any] | None) -> str:
    """바깥 AI 사용법 끝에 붙일 「이 PC 의 손자리 모델과 맡길 일」 절. 모델 크기를 모르면 표만 준다."""
    lines = ["", "## 이 PC 의 손자리 모델과 맡길 일 (지금 상태 — 판마다 다시 읽음)", ""]
    chat_b, code_b = params_in_tag(chat_model), params_in_tag(code_model or chat_model)
    if chat_model:
        lines.append(f"- 대화·조사 모델: `{chat_model}`" + (f" ({chat_b:g}B)" if chat_b else "")
                     + (f" · 코드 모델: `{code_model}`" + (f" ({code_b:g}B)" if code_b else "") if code_model and code_model != chat_model else "")
                     + (f" · 그래픽카드 쓸 수 있는 메모리 {budget_gb:.1f}GB" if budget_gb else ""))
    if chat_b:
        name, give, keep, basis = tier_of(chat_b)
        lines += [f"- 지금 크기: **{name}**", f"  - 맡기기 좋은 일: {give}", f"  - 당신이 직접 할 일: {keep}", f"  - 근거: {basis}"]
    if code_b and code_b != chat_b:
        name, give, keep, _ = tier_of(code_b)
        lines.append(f"- 코드 일은 코드 모델 기준({name}) — 당신이 직접 할 일: {keep}")
    if upgrade:
        lines.append(f"- 코드 일에는 이 PC 에 더 큰 모델이 들어갑니다: {upgrade['name']}({upgrade['size_gb']:.1f}GB). "
                     "사용자가 코드 일을 손자리에 맡기려 하면 「손자리 창 › 코드 탭 모델 이름을 눌러 받으라」고 알려 주세요. "
                     "규칙 추천이며 잰 성적이 아닙니다.")
    lines += ["", "흔한 일과 어려운 일 — 크기와 별개로 이렇게도 나눈다(공개 벤치 기준, 2026-10-01):",
              "- 흔한 일: 찾아 모으기 · 문서·표로 정리 · 이미 있는 코드의 작은 고치기 · 테스트를 돌려 확인 — 손자리에게 맡긴다. "
              "같은 체급 로컬 모델이 프런티어의 85~95% (예: Ornith 1.5 35B 자기 보고, Claude Opus 4.8 대비)",
              "- 어려운 일: 긴 코딩 · 저장소를 통째로 만들기 · 처음 보는 API · 아주 어려운 추론 — 당신이 직접 하고, "
              "손자리에게는 읽기·쓰기·실행·확인만 맡긴다. 같은 비교에서 24~66%",
              "", "크기별 기준:"]
    for _, name, give, keep, basis in _TIERS:
        lines.append(f"- {name} — 맡김: {give} / 직접: {keep} ({basis})")
    return "\n".join(lines)


def model_hint(task: str, upgrade: dict[str, Any] | None) -> str:
    """코드 일을 맡겼는데 코드 모델이 작고 더 큰 것이 들어가면 한 줄. 아니면 빈 문자열."""
    if not upgrade or not looks_like_code_task(task):
        return ""
    return (f"이 일은 코드 일인데 손자리의 코드 모델이 작습니다({upgrade['current']}). 이 PC 에는 {upgrade['name']}"
            f"({upgrade['size_gb']:.1f}GB)가 들어갑니다 — 사용자에게 손자리 창 › 코드 탭 모델 이름을 눌러 받으라고 알려 주세요"
            "(규칙 추천, 잰 성적 아님). 새 코드는 당신이 짜고 손자리에게는 쓰기·실행·확인을 맡기는 편이 낫습니다.")
