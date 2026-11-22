"""`sonjari_pack_request` — 꺼진 팩을 사람에게 「켜 달라고 청하는」 도구 (2026-11-16 · 설계_팩켜기UX §4-2 · §4-3).

## 왜

꺼진 팩의 도구는 목록에 없고, 불리면 「설정 › 팩에서 켜라」 글로 끝났다 — 클로드가 그 자리에서 켤 길이 없었다.
이제 클로드(또는 손자리 모델)는 이 도구로 **청하고**, 사람은 손자리 승인 카드에서 권한을 보고 누른다.

## 지킬 것

- **켜는 것은 늘 사람.** 등급 L2 · `ALWAYS_ASK` · `NEVER_BYPASS`(권한 무시 모드에서도 카드) — 켜기는 권한 동의라서다.
- 카드에는 `pack.json` 의 summary · permissions 넷 · 이 기계용으로 받을 모델 크기 · why 를 그대로 싣는다.
- 거절 · 만료면 그대로 돌려주고 **같은 일 안에서 다시 조르지 않는다**(카드를 새로 안 만든다). 떠 있는 카드를 둘로 만들지 않는다.
- 받을 파일이 남은 팩(2026-11-16 저녁 대표 「켜기를 누르면 필요한 파일이 다운된다고 같이 얘기해 주면서」): 카드에 크기 · 받는 자리 ·
  남은 자리를 보이고 단추는 「켜고 받기」 — **누른 것이 받기 동의**라 켜면서 받기를 시작한다. 자리가 모자라면 켜지 않는다.
- **받기는 맡기지 않는다**(ADR-PACK-1 결정 3): 맡김이 켜져 있어도 받을 파일이 남은 팩은 카드를 띄운다. 받을 것이 없는 팩만 맡김으로 바로.
- 「받을 것이 남았나」는 `ModelFetcher.status` 의 `needs_fetch` 한 자리(설정한 자리에 이미 있으면 남은 것이 아니다 · `pack_places`).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .pack_models import platform_fits
from .packs import PackError, localize_permissions, tools_here
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

TOOL_NAME = "sonjari_pack_request"
#: 일 번호가 없는 부름(바깥 클로드 MCP)은 「같은 일」을 모른다 — 이 시간 안의 거절 · 만료를 같은 일로 본다.
OUTSIDE_SAME_WORK_SEC = 2 * 3600

PACK_REQUEST_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "꺼져 있는 손자리 분야 팩(아래 「지금 꺼진 팩」 목록)을 켜 달라고 사용자에게 청한다. 사용자가 손자리 창의 카드에서 "
            "권한(읽기 · 쓰기 · 실행 · 인터넷)을 보고 직접 누른다 — 대신 켜지 않는다. 시킨 일에 그 팩이 꼭 필요할 때만 한 번 부른다. "
            "거절되면 같은 일에서 다시 청하지 말고 사람에게 그대로 전한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pack": {"type": "string", "description": "켜 달라고 할 팩 id(예: animator)"},
                "why": {"type": "string", "description": "무슨 일 때문에 필요한가 — 사용자에게 보일 한 문장"},
            },
            "required": ["pack", "why"],
            "additionalProperties": False,
        },
    },
}

WHY_MAX_CHARS = 200


def model_bytes(pack: Any, here: tuple[str, str] | None = None) -> int:
    """이 기계용으로 받을 모델 · 실행기 크기 합(바이트). 다른 기계용(`platform` 이 안 맞음)은 세지 않는다."""
    return sum(int(model.get("size") or 0) for model in getattr(pack, "models", ()) or ()
               if platform_fits(str(model.get("platform") or ""), here))


def _gb(size: int) -> str:
    return f"약 {size / 1e9:.1f}GB" if size >= 1e8 else f"약 {max(1, round(size / 1e6))}MB"


class PackRequestTools:
    """도구 한 개 — 청하기. 켜는 일은 사람이 카드에서 누른 뒤에만(게이트가 막는다)."""

    def __init__(self, registry: Any, store: Any, *, models_status: Callable[[str], dict[str, Any]] | None = None,
                 clock: Callable[[], float] = time.time, hints: Callable[[], dict[str, Any]] | None = None,
                 on_delegated: Callable[[dict[str, Any]], None] | None = None,
                 models_fetch: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.registry = registry
        self.store = store
        self.models_status = models_status
        #: 「켜고 받기」 — 사람이 카드에서 누른 뒤에만 부른다(`ModelFetcher.fetch`). 없으면 예전처럼 크기만 알린다.
        self.models_fetch = models_fetch
        self.clock = clock
        #: 이 PC 에 맞는 팩 판정(`PackHints.hints`) — 설명에 「맞는 까닭」을 싣는다. 없으면 까닭 없이 목록만.
        self.hints = hints
        #: 맡김으로 카드 없이 켰을 때(ADR-PACK-1) — 화면 알림 「○○ 켜짐 · 되돌리기」를 띄울 자리.
        self.on_delegated = on_delegated
        self._delegated_at: dict[str, float] = {}

    # ── 목록 ────────────────────────────────────────────────────────────
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return [PACK_REQUEST_TOOL]

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        """손자리 모델에게는 **켜지 않은 우리 팩이 있을 때만** 보인다 — 다 켜져 있으면 고를 것만 늘린다."""
        packs = getattr(self.registry, "packs", {}) or {}
        off = [p for p in packs.values() if getattr(p, "origin", "builtin") != "user" and not self.registry.is_enabled(p.id)]
        return [PACK_REQUEST_TOOL] if off else []

    def register(self, gateway: ToolGateway) -> None:
        spec = PACK_REQUEST_TOOL["function"]
        gateway.register(ToolSpec(
            name=spec["name"], description=str(spec["description"]), parameters=dict(spec["parameters"]),
            # ★ L2 — 늘 승인을 거친다. `ALWAYS_ASK` · `NEVER_BYPASS` 에 이름이 있어 어느 모드에서도 사람이 누른다.
            risk_level=RiskLevel.L2, handler=self.request,
        ))
        gateway.approval_describers[TOOL_NAME] = self.describe
        gateway.pre_approval_job_checks[TOOL_NAME] = self.check
        gateway.delegated_approvals[TOOL_NAME] = self.delegated
        gateway.description_providers[TOOL_NAME] = self.tool_description

    # ── 사람이 맡겼나(ADR-PACK-1) ─────────────────────────────────────────
    def delegated(self, arguments: dict[str, Any], job_id: str = "") -> bool:
        """카드 없이 켜도 되나: 사람이 「클로드에게 맡기기」를 켰고 · **바깥 클로드**(일 번호 없음)가 부른 것만.

        손자리 안 모델의 청(일 번호 있음)은 맡기지 않는다 — 웹 · 문서를 읽던 로컬 모델이 글에 끌릴 수 있다.
        """
        if job_id:
            return False
        may = getattr(self.registry, "claude_may_enable", None)
        if not callable(may) or not may():
            return False
        pack_id = str(arguments.get("pack") or "").strip().lower()
        pack = (getattr(self.registry, "packs", {}) or {}).get(pack_id)
        # 받을 파일이 남은 팩은 맡기지 않는다 — 받기(크기 · 라이선스 · 인터넷)는 사람이 카드에서 「켜고 받기」를 누른다(ADR-PACK-1 결정 3).
        # 판정을 못 읽으면 남은 것으로 본다(카드 쪽).
        if pack is not None and self.fetch_plan(pack)["needs"]:
            return False
        self._delegated_at[pack_id] = self.clock()
        return True

    # ── 받을 것이 남았나(「켜고 받기」 · 맡김이 같은 판정을 쓴다) ──────────────────────
    def fetch_plan(self, pack: Any) -> dict[str, Any]:
        """`{needs, bytes, disk_needed, disk_free, disk_ok, root, known}`.

        - `needs`: 이 기계용 · 꼭 있어야 하는 파일 가운데 아직 없는 것이 있나(설정한 자리에 있으면 있는 것).
        - 상태를 못 읽으면 `known=False` 로 팩에 적힌 크기를 쓰고, 받을 것이 있으면 남은 것으로 본다(맡김 · 「있음」 쪽으로 새지 않게).
        """
        size = model_bytes(pack)
        if not (getattr(pack, "models", ()) or ()):
            return {"needs": False, "bytes": 0, "disk_needed": 0, "disk_free": None, "disk_ok": True, "root": "", "known": True}
        status: dict[str, Any] | None = None
        if self.models_status is not None:
            try:
                status = self.models_status(pack.id)
            except Exception:  # noqa: BLE001
                status = None
        if not isinstance(status, dict):
            return {"needs": size > 0, "bytes": size, "disk_needed": size, "disk_free": None, "disk_ok": None, "root": "",
                    "known": False}
        needs = bool(status.get("needs_fetch", not status.get("all_ready", False)))
        return {
            "needs": needs,
            "bytes": int(status.get("to_download_bytes") or 0) if needs else 0,
            "disk_needed": int(status.get("disk_needed_bytes") or 0) if needs else 0,
            "disk_free": status.get("disk_free_bytes"),
            "disk_ok": bool(status.get("disk_ok", True)) if needs else True,
            "root": str(status.get("root") or ""),
            "known": True,
        }

    # ── 설명(목록을 줄 때마다) ────────────────────────────────────────────
    def tool_description(self) -> str:
        """「지금 꺼진 팩 · 하는 일 · 이 PC 에 맞는 까닭」을 싣는다 — 꺼진 팩은 도구가 목록에 없어 클로드가 있는 줄도 몰랐다(11-16 맥 실측)."""
        base = str(PACK_REQUEST_TOOL["function"]["description"])
        packs = getattr(self.registry, "packs", {}) or {}
        off = [p for p in packs.values() if getattr(p, "origin", "builtin") != "user" and not self.registry.is_enabled(p.id)]
        may = getattr(self.registry, "claude_may_enable", None)
        delegated = bool(callable(may) and may())
        lines = [base,
                 "부르기 전에 대화에서 사용자에게 「○○ 팩을 켤까요 — 무엇을 하는 팩이고 왜 필요한지」를 먼저 묻고, 응을 받은 뒤에만 부른다.",
                 ("사용자가 팩 켜기를 클로드에게 맡겨 두었다 — 부르면 카드 없이 바로 켜진다. 그래서 더더욱 대화에서 먼저 물어라."
                  if delegated else
                  "부르면 손자리 창에 켜기 카드가 뜨고 사용자가 누른다(사용자가 손자리에서 맡겨 두면 그다음부터는 바로 켜진다).")]
        if off:
            fits: dict[str, list[str]] = {}
            if self.hints is not None:
                try:
                    for row in (self.hints() or {}).get("hints") or ():
                        if row.get("fits"):
                            fits[str(row.get("pack"))] = [str(reason).split("(")[0].strip() for reason in row.get("reasons") or ()]
                except Exception:  # noqa: BLE001 — 판정을 못 읽어도 목록은 낸다
                    fits = {}
            lines.append("지금 이 PC 에서 꺼진 팩:")
            for pack in off:
                first = str(pack.summary or "").split(". ")[0].strip().rstrip(".")
                why = f" · 이 PC 에 맞음: {', '.join(fits[pack.id])}" if fits.get(pack.id) else ""
                lines.append(f"- {pack.id}({pack.name}): {first}{why}")
        else:
            lines.append("지금은 이 PC 의 팩이 모두 켜져 있다 — 부를 일이 없다.")
        lines.append("켠 팩은 사용자가 설정 › 팩에서 다시 끌 수 있다. 모델 · 실행기를 받아야 하는 팩은 맡김이어도 카드가 뜨고, "
                     "사용자가 「켜고 받기」를 누르면 켜면서 받는다 — 클로드는 대신 받지 않는다.")
        return "\n".join(lines)

    # ── 카드 전 ─────────────────────────────────────────────────────────
    def _pack(self, arguments: dict[str, Any]) -> Any:
        pack_id = str(arguments.get("pack") or "").strip().lower()
        packs = getattr(self.registry, "packs", {}) or {}
        if pack_id not in packs:
            known = ", ".join(sorted(packs)) or "(없음)"
            raise ValueError(f"unknown_pack: 「{pack_id}」 이라는 팩이 없다 — 있는 팩: {known}")
        return packs[pack_id]

    def check(self, arguments: dict[str, Any], job_id: str = "") -> None:
        """카드를 만들기 전에. 못 쓰면 예외 — 그 글이 그대로 부른 쪽에 간다(카드 없음)."""
        pack = self._pack(arguments)
        why = " ".join(str(arguments.get("why") or "").split())
        if not why:
            raise ValueError("why 가 비었다 — 무슨 일 때문에 이 팩이 필요한지 한 문장으로 적어라(사용자 카드에 그대로 보인다).")
        if len(why) > WHY_MAX_CHARS:
            raise ValueError(f"why 는 {WHY_MAX_CHARS}자 안의 한 문장이어야 한다.")
        if self.registry.is_enabled(pack.id):
            raise ValueError(f"already_enabled: {pack.name}은 이미 켜져 있다 — 다시 청하지 말고 그 팩의 도구 "
                             f"{len(tools_here(pack))}개를 그대로 부르면 된다.")
        last = self._last_card(pack.id, job_id)
        if last is None:
            return
        status = last["status"]
        if status == "pending":
            raise ValueError(f"pack_request_pending: {pack.name} 켜기 카드가 이미 손자리 창에 떠 있다 — 새로 청하지 말고 "
                             "사용자가 누를 때까지 기다려라.")
        if status in ("denied", "expired"):
            said = "거절했다" if status == "denied" else "누르지 않아 카드가 만료됐다"
            raise ValueError(f"pack_request_declined: 사용자가 {pack.name} 켜기를 {said} — 이 일에서는 다시 청하지 마라. "
                             "그 팩 없이 할 수 있는 것을 하거나, 사람에게 그대로 전해라(나중에 설정 › 팩에서 직접 켤 수 있다).")

    def _last_card(self, pack_id: str, job_id: str) -> dict[str, Any] | None:
        """같은 일에서 이 팩을 청한 가장 최근 카드의 상태(`pending` · `denied` · `expired`) — 없거나 이미 쓴 것이면 None."""
        try:
            rows = self.store.list_approvals(200)
        except Exception:  # noqa: BLE001 — 장부를 못 읽으면 막지 않는다(카드는 어차피 사람이 본다)
            return None
        now = self.clock()
        for row in rows:  # 최근 것부터
            if str(row.get("tool_name") or "") != TOOL_NAME or str(row.get("job_id") or "") != (job_id or ""):
                continue
            if str((row.get("arguments") or {}).get("pack") or "").strip().lower() != pack_id:
                continue
            if not job_id and now - float(row.get("created_at") or 0) > OUTSIDE_SAME_WORK_SEC:
                return None
            status = str(row.get("status") or "")
            if status == "pending" and float(row.get("expires_at") or 0) < now:
                status = "expired"
            if status in ("pending", "denied", "expired"):
                return {"status": status}
            return None  # 승인 · 소진 — 그 뒤에 끈 것이면 다시 청할 수 있다
        return None

    def describe(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """승인 카드에 덧붙일 칸 — pack.json 그대로(요약 · 권한 넷) + 받을 크기 + 까닭."""
        try:
            pack = self._pack(arguments)
        except ValueError:
            return {}
        plan = self.fetch_plan(pack)
        return {
            "kind": "pack_enable",
            "pack": pack.id, "name": pack.name, "summary": pack.summary,
            # 이 기계 꼴로 푼다 — 맥에 윈도우 경로가 보이지 않게(`{docs}` 자리 표시 · ADR-PACK-1).
            "permissions": {key: value for key, value in localize_permissions(
                {key: pack.permissions.get(key) for key in ("reads", "writes", "runs", "network")}).items()},
            "tools": len(tools_here(pack)),
            # 「켜고 받기」(11-16 저녁) — 단추 이름 · 막힘은 화면이 이 칸으로 정한다.
            "fetch_on_enable": plan["needs"],
            "has_models": any(platform_fits(str(m.get("platform") or "")) for m in getattr(pack, "models", ()) or ()),
            "download_bytes": plan["bytes"],
            "disk_needed_bytes": plan["disk_needed"],
            "disk_free_bytes": plan["disk_free"],
            "disk_ok": plan["disk_ok"],
            "place": plan["root"],
            "download": _download_line(pack, plan),
            "why": " ".join(str(arguments.get("why") or "").split())[:WHY_MAX_CHARS],
        }

    # ── 사람이 누른 뒤 ───────────────────────────────────────────────────
    def request(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pack = self._pack(arguments)
        plan = self.fetch_plan(pack)
        if plan["needs"] and plan["disk_ok"] is False:
            # 자리가 모자라면 켜지 않는다 — 켜 놓고 못 받으면 「켜짐」인데 못 쓰는 팩이 된다(화면은 단추를 막지만 경합 · 다른 문 대비).
            raise ValueError(f"not_enough_disk: {pack.name}에 필요한 파일 {_gb(plan['disk_needed'])}를 받을 자리가 모자라다"
                             f"(남은 {_gb(int(plan['disk_free'] or 0))} · 받는 자리 {plan['root'] or '데이터 폴더'}) — 켜지 않았다. "
                             "사용자에게 「설정 › 일반 › 팩 파일 자리」에서 큰 드라이브를 고르라고 전해라.")
        try:
            self.registry.set_enabled(pack.id, True)
        except PackError as exc:
            raise ValueError(str(exc)) from exc
        here = tools_here(pack)
        # 맡김으로 카드 없이 켠 것인가 — 바로 앞의 맡김 판정이 이 팩에 대해 True 였나(몇 초 안).
        delegated = self.clock() - self._delegated_at.pop(pack.id, -1e9) < 30
        result: dict[str, Any] = {
            "ok": True, "enabled": True, "pack": pack.id, "name": pack.name,
            "tools": here, "tool_count": len(here),
            "by": "delegated" if delegated else "person",
            "message": (f"맡김 설정대로 {pack.name}을 켰습니다 · 도구 {len(here)}개 — 사용자에게 켰다고 한 줄 알려라"
                        if delegated else f"사용자가 {pack.name}을 켰습니다 · 도구 {len(here)}개"),
        }
        if plan["needs"]:
            result["models"] = self._start_fetch(pack, plan)
            if result["models"].get("fetching"):
                result["message"] += f" · 필요한 파일({_gb(plan['bytes'])}) 받기를 시작했습니다"
        following = self.registry.next_for(pack.id)
        if following:
            result["next"] = following
        result["instruction"] = ("이제 그 팩의 도구를 부를 수 있다(바깥 클로드는 목록에 아직 없으면 sonjari_tool 고정 문으로). "
                                 + ("다음 팩(next)은 사람이 원할 때만 권하고, 대신 청하지 마라." if following else ""))
        if delegated and self.on_delegated is not None:
            try:
                self.on_delegated({"pack": pack.id, "name": pack.name, "tool_count": len(here),
                                   "why": " ".join(str(arguments.get("why") or "").split())[:WHY_MAX_CHARS]})
            except Exception:  # noqa: BLE001 — 알림을 못 띄워도 켠 사실은 그대로
                pass
        return result

    def _start_fetch(self, pack: Any, plan: dict[str, Any]) -> dict[str, Any]:
        """사람이 「켜고 받기」를 누른 뒤에만 — 받기를 시작하고 무엇을 시작했는지 돌려준다. 실패해도 켠 사실은 그대로."""
        models: dict[str, Any] = {"download_bytes": plan["bytes"], "fetching": False}
        if self.models_fetch is None:
            models["note"] = f"모델 · 실행기({_gb(plan['bytes'])})는 아직 안 받았다 — 사용자가 설정 › 팩에서 「받기」를 눌러야 쓸 수 있다."
            return models
        try:
            out = self.models_fetch(pack.id)
        except Exception as exc:  # noqa: BLE001 — 받기를 못 시작해도 켠 사실은 그대로
            models["error"] = f"{exc.__class__.__name__}: {exc}"[:300]
            models["note"] = "받기를 시작하지 못했다 — 사용자에게 설정 › 팩에서 「받기」를 다시 눌러 달라고 전해라."
            return models
        models["status"] = out
        if isinstance(out, dict) and out.get("ok") and (out.get("started") or out.get("state") == "running"):
            models["fetching"] = True
            models["note"] = ("받는 중이다(손자리 창 · 설정 › 팩에 진행이 보인다). 다 받기 전에는 그 팩 도구가 not_ready 를 돌려줄 수 있다 — "
                              "사용자에게 받는 중이라고 알리고, 그 팩의 확인 도구(…_check)로 준비됐는지 본 뒤 이어 가라.")
        else:
            models["error"] = str((out or {}).get("error") or "not_started") if isinstance(out, dict) else "not_started"
            models["note"] = "받기를 시작하지 못했다 — 사용자에게 설정 › 팩에서 「받기」를 다시 눌러 달라고 전해라."
        return models


def _download_line(pack: Any, plan: dict[str, Any]) -> str:
    """카드의 받기 한 줄 — 사람이 누르기 전에 「얼마나 · 어디에 · 자리가 되나」."""
    if not (getattr(pack, "models", ()) or ()):
        return "받을 파일 없음"
    if not plan["needs"]:
        return "필요한 파일은 이 PC 에 이미 있습니다 — 켜면 바로 씁니다"
    place = f" · 받는 자리 {plan['root']}" if plan["root"] else ""
    free = plan["disk_free"]
    left = f" · 남은 자리 {_gb(int(free))}" if isinstance(free, (int, float)) and not isinstance(free, bool) else ""
    if plan["disk_ok"] is False:
        return (f"자리가 모자랍니다 — 필요 {_gb(plan['disk_needed'])}{left}{place}. "
                "설정 › 일반 › 팩 파일 자리에서 큰 드라이브를 고르세요")
    what = f"필요한 파일 {_gb(plan['bytes'])}를 받습니다" if plan["bytes"] else "필요한 파일을 들입니다(거울 · 손으로 넣은 자리)"
    return f"켜면 {what}{place}{left}"


def next_line(registry: Any, pack_id: str) -> str:
    """그 팩 도구 영수증 끝 한 줄 — 이어 쓸 팩(켰거나 무시한 팩은 빠짐). 없으면 빈 글."""
    rows = registry.next_for(pack_id) if registry is not None else []
    if not rows:
        return ""
    parts = [f"{row['name']}({row['pack']}) — {row['when']}" for row in rows]
    return ("다음에 이어 쓸 팩(꺼져 있음 · 사람이 원하면 sonjari_pack_request 로 청할 수 있음): " + " · ".join(parts))


def attach_next_line(registry: Any) -> Callable[[str, Any], Any]:
    """게이트의 결과 손질 — 팩 도구의 **끝난 결과**(receipt 나 files 가 있는 dict)에만 `next_pack` 한 줄을 붙인다."""

    def note(tool: str, result: Any) -> Any:
        if not isinstance(result, dict) or result.get("ok") is False or "next_pack" in result:
            return result
        if not (result.get("receipt") or result.get("files")):
            return result
        owner = registry.tool_owner(tool) if registry is not None else ""
        if not owner or tool == TOOL_NAME:
            return result
        line = next_line(registry, owner)
        return {**result, "next_pack": line} if line else result

    return note


__all__ = ["PACK_REQUEST_TOOL", "PackRequestTools", "TOOL_NAME", "attach_next_line", "model_bytes", "next_line"]
