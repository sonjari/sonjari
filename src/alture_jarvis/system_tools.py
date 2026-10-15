from __future__ import annotations

import os
import subprocess
from typing import Any

from .config import JarvisConfig
from .human_gate import CONTENT_FRICTION_CODE, RECIPE_SUGGEST_AFTER
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec


def _gpu_status(_: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "nvidia_smi_failed")
    rows = []
    for line in result.stdout.splitlines():
        fields = [part.strip() for part in line.split(",")]
        if len(fields) == 5:
            rows.append(
                {
                    "index": int(fields[0]),
                    "name": fields[1],
                    "memory_used_mb": int(fields[2]),
                    "memory_total_mb": int(fields[3]),
                    "utilization_percent": int(fields[4]),
                }
            )
    return {"gpus": rows}


def _undo_tools(gateway: ToolGateway) -> None:
    """되돌리기를 모델도 부를 수 있게 연다.

    "방금 거 취소해줘" 는 사람이 제일 자연스럽게 하는 말인데, 지금까지 그 말을
    받아 줄 도구가 없었다. 되돌리기는 **원래 상태로 가는 방향**이라 L1 이다 —
    여기에 승인을 걸면 되돌리기가 무거워지고, 무거운 되돌리기는 안 쓰인다.
    """

    def list_undoable(arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        rows = gateway.store.list_undo_offers()
        return {
            "action": "undo_list",
            "count": len(rows),
            "items": [
                {
                    "undo_id": row["undo_id"],
                    "tool": row["tool"],
                    "label": row["label"],
                    "automatic": row["automatic"],
                    "manual_hint": row["manual_hint"],
                    # 무엇을 되돌리는지 사람이 알아볼 수 있게 — 제목 같은 것이 여기 있다.
                    "what": row["handle"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
            "instruction": (
                "되돌릴 것이 없다."
                if not rows
                else "되돌리려면 undo_action 에 undo_id 를 줘라. automatic=false 인 것은 "
                "손자리가 못 되돌리니 manual_hint 를 사용자에게 그대로 전해라."
            ),
        }

    def undo_action(arguments: dict[str, Any]) -> dict[str, Any]:
        undo_id = str(arguments.get("undo_id") or "").strip()
        if not undo_id:
            # 안 대면 가장 최근 것. "방금 거"가 사람이 쓰는 말이다.
            live = gateway.store.list_undo_offers(limit=1)
            if not live:
                return {"action": "undo_action", "ok": False, "error": "nothing_to_undo"}
            undo_id = str(live[0]["undo_id"])
        return {"action": "undo_action", **gateway.undo(undo_id)}

    gateway.register(
        ToolSpec(
            "undo_list",
            "방금 한 일 중 되돌릴 수 있는 것들을 보여준다.",
            RiskLevel.L0,
            list_undoable,
            parameters={"type": "object", "properties": {}},
        )
    )
    gateway.register(
        ToolSpec(
            "undo_action",
            "방금 한 일을 되돌린다. undo_id 를 비우면 가장 최근 것을 되돌린다.",
            RiskLevel.L1,
            undo_action,
            parameters={
                "type": "object",
                "properties": {"undo_id": {"type": "string"}},
                "required": [],
            },
        )
    )


def _friction_tools(gateway: ToolGateway) -> None:
    """어디가 제일 자주 막히는지 — 레시피를 쓸 곳을 고르는 목록.

    레시피는 자율이 저절로 늘어나는 유일한 축이다(사람이 한 번 뚫으면 다음부터
    안 막힌다). 그런데 지금 recipes/ 에는 naver_blog 하나뿐이다. 무엇을 쓸지
    모르기 때문이고, 모르는 이유는 **어디서 아픈지 아무도 안 세고 있었기** 때문이다.
    """

    # 코드는 장부에 그대로 쌓이지만, 읽는 사람에게는 **무엇을 고쳐야 하는지**가
    # 보여야 한다. 로그인 문과 안 읽히는 페이지는 손대는 곳이 완전히 다르다.
    why_ko = {
        "login_required": "로그인 문 — 사람이 한 번 열어야 함",
        "bot_check": "봇 확인 화면 — 사람이 한 번 통과시켜야 함",
        CONTENT_FRICTION_CODE: "본문이 안 읽힘 — 페이지 구조/셀렉터 문제",
    }

    def friction(arguments: dict[str, Any]) -> dict[str, Any]:
        rows = gateway.store.site_friction(limit=int(arguments.get("limit") or 15))
        ready = [row for row in rows if int(row.get("hits") or 0) >= RECIPE_SUGGEST_AFTER]
        return {
            "action": "site_friction",
            "count": len(rows),
            "items": [
                {
                    "host": row["host"],
                    "why": why_ko.get(row["code"], row["code"]),
                    "code": row["code"],
                    "hits": row["hits"],
                    "last_goal": row["last_goal"],
                    "last_url": row["last_url"],
                }
                for row in rows
            ],
            "instruction": (
                "막힌 기록이 없다."
                if not rows
                else f"레시피를 만들 때가 된 곳: {', '.join(r['host'] for r in ready)}. "
                "레시피는 화면을 같이 보며 셀렉터를 확인해서 만든다 — 짐작으로 쓰지 마라."
                if ready
                else "아직 레시피를 만들 만큼 반복된 곳은 없다."
            ),
        }

    gateway.register(
        ToolSpec(
            "site_friction",
            "어느 사이트에서 몇 번 막혔는지 보여준다. 레시피를 만들 곳을 고를 때 쓴다.",
            RiskLevel.L0,
            friction,
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
        )
    )


def register_system_tools(config: JarvisConfig, gateway: ToolGateway) -> None:
    _undo_tools(gateway)
    _friction_tools(gateway)
    gateway.register(
        ToolSpec(
            "gpu_status",
            "GPU 사용량 조회",
            RiskLevel.L0,
            _gpu_status,
            parameters={"type": "object", "properties": {}},
        )
    )

    def open_url(arguments: dict[str, Any]) -> dict[str, Any]:
        if not config.enable_system_actions:
            raise RuntimeError("system_actions_disabled")
        url = str(arguments.get("url", "")).strip()
        if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("url_not_allowed")
        if os.name != "nt":
            raise RuntimeError("windows_only")
        os.startfile(url)  # type: ignore[attr-defined]
        return {"opened": url}

    gateway.register(
        ToolSpec(
            "open_url",
            "PC 기본 브라우저에서 URL 열기",
            RiskLevel.L2,
            open_url,
            enabled=config.enable_system_actions,
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )
    )
