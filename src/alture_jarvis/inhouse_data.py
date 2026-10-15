"""우리가 직접 쌓은 데이터를 자비스가 볼 수 있게 하는 창구.

2026-08-13 실측에서 드러난 구멍이다. NAS 에는 입시·진로 조회 도구가 20 여 개
있는데(도메인 앱 서버) **자비스 도구 목록에는 0 건**이었다.
그래서 "이 성적으로 어디 갈 수 있냐" 같은 질문을 받으면 자비스가 고를 수 있는
길이 둘뿐이었다 — 기억에서 답하거나(창작), 웹을 뒤지거나(느리고 부정확).

우리 원천(cutoffs 76k · 대학알리미 성과지표 · majors_career 25k)을 두고 남의
블로그를 읽고 있었다는 뜻이다.

★ **도구 정의를 여기에 베껴 적지 않는다.** NAS 가 스키마째 내려주고
(`GET /v1/inhouse/tools`) 자비스는 그걸로 자기 도구를 만든다. 이 저장소가 여러 번
배운 규칙이다 — 목록을 두 벌 두면 갈리고, 갈린 쪽은 조용히 틀린다(`gemma_bundle`,
`plan.SITE_ALIASES`, 상한 두 군데 … 전부 같은 병이었다).

NAS 가 안 뜨는 판을 위해 **마지막으로 성공한 목록을 디스크에 적어 둔다.** 이건
두 번째 목록이 아니라 캐시다 — 사람이 고치라고 두는 파일이 아니고, 성공할 때마다
통째로 덮인다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

logger = logging.getLogger(__name__)

# 도구 결과 하나가 모델 컨텍스트에서 차지할 수 있는 최대치.
#
# 조회 결과에는 근거 행이 통째로 들어 있어(합격컷 3 개년 × 여러 전형) 그대로 넣으면
# 한 번에 수만 자가 된다. 컨텍스트는 이 모델에서 거의 공짜지만(SWA) **읽히는 양은
# 공짜가 아니다** — 길면 모델이 뒤쪽을 안 본다.
_RESULT_MAX_CHARS = 12_000

# 화면에 그려 보라고 만든 값들. 자비스는 그릴 곳이 없고, 이것 하나가 수 KB 다.
_DROP_KEY_SUFFIXES = ("_html", "_base64", "_svg")


def _cap_lists(value: Any, limit: int, dropped: list[int], depth: int = 0) -> Any:
    """긴 목록의 **뒤를 잘라내되 구조는 온전히** 남긴다.

    ★ 직렬화한 글자를 자르면 안 된다. 처음엔 그렇게 했는데, 모델이 받는 것이
    반쪽짜리 JSON **문자열**이 된다 — 근거를 반만 보고 답하는 것이 못 보고
    모른다고 하는 것보다 나쁘다는 걸 이 저장소는 이미 여러 번 배웠다.

    행은 뒤에서 자른다. 합격컷 조회는 최신 연도가 앞에 오므로 뒤가 옛날이다.
    """
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {k: _cap_lists(v, limit, dropped, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > limit:
            dropped.append(len(value) - limit)
            value = value[:limit]
        return [_cap_lists(v, limit, dropped, depth + 1) for v in value]
    return value


def _shrink(value: Any, depth: int = 0) -> Any:
    """모델에 넣기 전에 **렌더용 덩어리만** 걷어낸다.

    값을 자르지는 않는다. 자르면 근거가 반쯤 남아서 더 나쁘다 — 숫자를 반만 보고
    답하는 것이 못 보고 모른다고 하는 것보다 나쁘다는 걸 이미 여러 번 봤다.
    """
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: _shrink(v, depth + 1)
            for k, v in value.items()
            if not any(str(k).endswith(suffix) for suffix in _DROP_KEY_SUFFIXES)
        }
    if isinstance(value, list):
        return [_shrink(v, depth + 1) for v in value]
    return value


class InhouseDataTools:
    """NAS 의 자사 데이터 조회 도구를 자비스 도구로 옮겨 붙인다."""

    def __init__(self, config: JarvisConfig) -> None:
        self.config = config
        self._cache_path: Path = config.data_dir / "inhouse_tools.json"
        self._schemas: list[dict[str, Any]] = []
        self._source: str = "none"
        self._error: str = ""
        if not config.inhouse_data_enabled:
            self._error = "disabled"
        elif not config.inhouse_api_key.strip():
            # 키가 없으면 어차피 401 이다. 캐시로 도구만 띄우면 **부르는 족족
            # 실패하는 도구**가 목록에 서고, 그건 도구를 안 주느니만 못하다.
            self._error = "api_key_missing"
        else:
            self._schemas, self._source, self._error = self._load_schemas()

    # ── 스키마 확보 ────────────────────────────────────────────────────

    def _load_schemas(self) -> tuple[list[dict[str, Any]], str, str]:
        try:
            fetched = self._fetch_schemas()
        except Exception as exc:  # noqa: BLE001
            cached = self._read_cache()
            if cached:
                logger.warning("[inhouse] NAS 목록 실패 — 캐시 사용: %s", exc)
                return cached, "cache", str(exc)[:200]
            logger.warning("[inhouse] NAS 목록 실패, 캐시도 없음: %s", exc)
            return [], "none", str(exc)[:200]
        self._write_cache(fetched)
        return fetched, "nas", ""

    def _fetch_schemas(self) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{self.config.inhouse_api_base.rstrip('/')}/v1/inhouse/tools",
            headers=self._headers(),
            timeout=self.config.inhouse_startup_timeout_sec,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "inhouse_tools_not_ok"))
        tools = [t for t in (payload.get("tools") or []) if isinstance(t, dict) and t.get("name")]
        if not tools:
            raise RuntimeError("inhouse_tools_empty")
        return tools

    def _read_cache(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        tools = raw.get("tools") if isinstance(raw, dict) else raw
        if not isinstance(tools, list):
            return []
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    def _write_cache(self, tools: list[dict[str, Any]]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps({"tools": tools}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[inhouse] 캐시 기록 실패(무시): %s", exc)

    def _headers(self) -> dict[str, str]:
        return {
            self.config.inhouse_api_header: self.config.inhouse_api_key,
            "Content-Type": "application/json",
        }

    # ── 에이전트가 보는 얼굴 ────────────────────────────────────────────

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": str(schema["name"]),
                    "description": str(schema.get("description") or ""),
                    "parameters": dict(schema.get("input_schema") or {"type": "object", "properties": {}}),
                },
            }
            for schema in self._schemas
        ]

    @property
    def names(self) -> set[str]:
        return {str(schema["name"]) for schema in self._schemas}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.inhouse_data_enabled,
            "api_base": self.config.inhouse_api_base,
            "tools": sorted(self.names),
            "schema_source": self._source,
            "error": self._error,
        }

    # ── 실행 ──────────────────────────────────────────────────────────

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"{self.config.inhouse_api_base.rstrip('/')}/v1/inhouse/call/{name}",
            headers=self._headers(),
            json={
                "tool_input": arguments or {},
                "tenant_id": self.config.inhouse_tenant_id,
            },
            timeout=self.config.inhouse_call_timeout_sec,
        )
        if response.status_code >= 400:
            # 무엇이 막았는지 그대로 올린다. 여기서 뭉개면 "사이트가 막았나"로
            # 오해받는다 — `browser_extract` 때 실제로 그랬다.
            raise RuntimeError(f"inhouse_http_{response.status_code}: {response.text[:200]}")
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or "inhouse_call_failed"))
        result = _shrink(payload.get("result"))
        if not isinstance(result, dict):
            result = {"result": result}
        if len(json.dumps(result, ensure_ascii=False)) <= _RESULT_MAX_CHARS:
            return result

        # 아직 크다 — 목록을 점점 짧게 잡아 가며 예산 안에 넣는다. 요약·근거 필드는
        # 그대로 남으므로 답의 뼈대는 안 없어진다.
        for limit in (12, 6, 3, 1):
            dropped: list[int] = []
            capped = _cap_lists(result, limit, dropped)
            text = json.dumps(capped, ensure_ascii=False)
            if len(text) <= _RESULT_MAX_CHARS or limit == 1:
                # 잘랐다는 사실을 **결과 안에** 남긴다. 조용히 자르면 모델은 그것이
                # 전부인 줄 알고 "그게 다입니다"라고 답한다.
                capped["_truncated"] = (
                    f"목록이 길어 각 목록을 {limit}개까지만 담았다"
                    f"(생략 {sum(dropped)}건). 더 좁혀서 다시 물으면 전부 볼 수 있다."
                )
                return capped
        return result

    def register(self, gateway: ToolGateway) -> None:
        for definition in self.ollama_tools:
            function = definition["function"]
            name = str(function["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(function.get("description") or ""),
                    parameters=dict(function.get("parameters") or {}),
                    # 읽기 전용 조회다. NAS 쪽 화이트리스트가 쓰기 도구를 애초에
                    # 안 내려준다 — 등급은 여기서도 한 번 더 못 박는다.
                    risk_level=RiskLevel.L1,
                    handler=lambda args, n=name: self.call(n, args),
                )
            )
