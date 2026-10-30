"""Site knowledge as data, not as Python.

`naver_blog.py` is 22KB of one site. Everything genuinely site-specific in it is
a handful of facts -- which URL opens the editor, which selectors are the title
and the body, what proves a save landed -- wrapped in a great deal of machinery
that is not specific to Naver at all. That machinery now lives in `browser.py`
and works anywhere, so the facts can move out into a file.

The point is not elegance. It is that adding 쿠팡, 노션, a school portal or a
government form should be a reviewed JSON file, not a new module -- and that the
site knowledge which took two days to learn ends up somewhere a person can read
and correct.

What a recipe may NOT do, by construction:
  * it cannot press a positive button on a dialog (`dismiss` only declines)
  * it cannot claim success -- a mutating step without `expect` is refused at
    load time, so "저장했습니다" always has evidence behind it
  * it cannot navigate off its own declared hosts
  * it cannot type into a password or file field (the browser layer blocks it)

Those are load-time and run-time checks rather than conventions, because a
recipe is the one part of this system meant to be edited quickly.
"""

from __future__ import annotations

import hashlib
import json
import time
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .browser import BrowserWorker
from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec


# Steps that change something the user would care about. Each one must carry
# `expect`, or the recipe is rejected when it loads -- not when it runs, and
# not silently at the point where someone is waiting for an answer.
_MUTATING = frozenset({"click", "fill", "press"})

# 읽기만 하는 걸음. **`dismiss` 는 여기 없다** — 대화상자를 거절하는 것도 화면에
# 대고 하는 선택이라("저장하시겠습니까?"에 아니오) 읽기라고 부를 수 없다.
_READ_ONLY_STEPS = frozenset({"open", "find", "verify", "wait"})


def read_only_reason(data: dict[str, Any]) -> str:
    """읽기만 하는 레시피면 빈 문자열. 아니면 **왜 아닌지**를 돌려준다.

    ★ 이 함수 하나가 자동 확정의 경계다. 그래서 "아닌 이유"를 문장으로 돌려준다 —
    참/거짓만 돌려주면 승인 화면에서 왜 걸렸는지 아무도 모른다.

    판정은 **초안 파일 자체**를 보고 한다. 모델이 인자로 "이건 읽기 전용입니다"
    라고 주장하는 것을 믿지 않는다는 뜻이다(`_approved` 가 그렇게 뚫렸다).
    """
    reasons: list[str] = []
    for action_name, action in (data.get("actions") or {}).items():
        declared = str((action or {}).get("risk") or "L1").upper()
        if declared not in {"L0", "L1"}:
            reasons.append(f"{action_name}: 스스로 {declared} 라고 적었다")
        for index, step in enumerate(action.get("steps") or []):
            do = str(step.get("do") or "")
            if do not in _READ_ONLY_STEPS:
                reasons.append(f"{action_name}[{index}]: {do or '(빈 걸음)'}")
    return "" if not reasons else ", ".join(reasons)

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_STEPS = frozenset({"open", "find", "click", "fill", "press", "dismiss", "verify", "wait"})

# 자비스가 쓴 초안이 놓이는 곳. **`recipes/` 바로 아래가 아니다.**
#
# `load_recipes` 는 `glob("*.json")` 으로 한 겹만 읽으므로 이 하위 폴더는 잡히지
# 않는다. 그게 초안과 확정의 경계다 — 파일 위치 하나로 갈리고, 옮기는 것은
# `site_promote_draft`(L2 화면 승인)뿐이다.
DRAFTS_DIRNAME = "drafts"


class RecipeError(ValueError):
    """A recipe is wrong. Raised at load time wherever possible."""


class SiteRecipe:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.name = str(data.get("name") or path.stem)
        self.description = str(data.get("description") or "")
        self.hosts = [str(h).lower() for h in (data.get("hosts") or [])]
        self.urls = {str(k): str(v) for k, v in (data.get("urls") or {}).items()}
        self.targets = {
            str(k): [str(s) for s in v] for k, v in (data.get("targets") or {}).items()
        }
        self.actions = dict(data.get("actions") or {})
        # ★ 사람이 부르는 **이름** → 사이트가 쓰는 **값** (2026-10-04). 사람인의 지역은 `loc_mcd=105000` 같은 번호인데, 모델은 그 번호를
        #   모른다 — 짐작해 넣으면(41·42·44) 사이트는 오류 대신 엉뚱한 목록을 주고, 그 목록이 「0건」의 근거가 된다. 번호는 사람이 화면에서
        #   읽어 확인한 표가 댄다. 표에 없는 이름은 실행하지 않고 쓸 수 있는 이름을 알려 준다(틀린 안내는 벽보다 나쁘다 — 사고 R).
        self.param_values = {
            str(param): {str(name): str(value) for name, value in (table or {}).items()}
            for param, table in (data.get("param_values") or {}).items()
            if isinstance(table, dict)
        }
        self.param_joins = {str(k): str(v) for k, v in (data.get("param_joins") or {}).items()}
        # ★ 사람이 보여 준 레시피의 **검증 상태**와 쓴 횟수 (2026-10-28). 상태는 저장하기 전 「한 번 해 보기」가 남긴다 —
        #   `verified`(걸음마다 확인이 맞았다) · `unverified`(안 해 봤거나 틀렸다). 쓴 횟수는 `site_run` 이 돌 때마다 센다.
        #   손자리에 든(사람이 검토한) 레시피에는 이 칸이 없고, 없으면 믿을 만한 쪽으로 친다(순서는 `rank`).
        self.verification = dict(data.get("verification") or {})
        self.usage = dict(data.get("usage") or {})
        # ★ **이 사이트 상세 화면에서 읽을 자리** — 경로 앞머리 → 선택자들 (2026-10-04 실전 판 e055235f).
        #   사람인 공고 편집기 템플릿이 본문을 `<main>` 으로 감싸, 본문 고르기가 그 안만 읽고 「핵심 정보」(근무형태·급여)를 버렸다.
        #   어디가 사이트가 채운 칸이고 어디가 올린 사람의 글인지는 사이트를 본 사람이 안다 — 레시피에 적는다.
        self.read_selectors = {
            str(prefix): [str(selector) for selector in selectors if str(selector).strip()]
            for prefix, selectors in (data.get("read_selectors") or {}).items()
            if isinstance(selectors, list)
        }
        self._validate()

    def _validate(self) -> None:
        if not self.hosts:
            raise RecipeError(f"{self.name}: hosts를 비워둘 수 없다 — 어디로 갈 수 있는지가 곧 안전선이다")
        if not self.actions:
            raise RecipeError(f"{self.name}: actions가 없다")
        for action_name, action in self.actions.items():
            steps = action.get("steps") or []
            if not steps:
                raise RecipeError(f"{self.name}.{action_name}: steps가 비었다")
            risk = str(action.get("risk") or "L1")
            if risk not in {"L0", "L1", "L2"}:
                raise RecipeError(f"{self.name}.{action_name}: risk는 L0·L1·L2 중 하나여야 한다")
            for index, step in enumerate(steps):
                self._validate_step(action_name, index, step)
        self._validate_undos()

    def _validate_undos(self) -> None:
        """`undo` 는 **이 레시피 안의 다른 동작 이름**이다.

        ## 왜 레시피가 역동작을 갖나 (2026-08-15)

        "신청서를 냈다"를 범용으로 되돌리는 방법은 없다 — 취소 경로가 사이트마다
        다르기 때문이다. 그런데 그 사이트별 지식이 살 집은 이미 있다. 레시피다.
        그리고 자비스는 레시피를 스스로 초안 쓴다. 그러니 조사(L2)가 범용인 것과
        같은 방식으로 쓰기도 범용이 된다 — 사이트가 느는 것이 곧 레시피가 느는 것이다.

        ## 여기서 안 하는 것

        **등급을 안 내린다.** 레시피가 "나 되돌릴 수 있으니 승인 빼줘"라고 스스로
        적을 수 있으면 자비스가 자기 승인 등급을 쓰는 것이고, 그건 `_approved`
        인자로 뚫려 있던 구멍과 같은 모양이다. 강등은 **역동작이 실제로 성공한
        기록**(레시피 파일이 아닌 곳)이 있을 때만 한다 — 그건 다음 단계다.
        """
        for action_name, action in self.actions.items():
            undo = action.get("undo")
            if undo is None:
                continue
            undo_name = str(undo)
            where = f"{self.name}.{action_name}.undo"
            if undo_name not in self.actions:
                raise RecipeError(f"{where}: '{undo_name}' 절차가 없다 — 있는 것: {sorted(self.actions)}")
            if undo_name == action_name:
                raise RecipeError(f"{where}: 자기 자신을 되돌릴 수는 없다")
            if self.actions[undo_name].get("undo"):
                # 되돌리기의 되돌리기는 되돌리기가 아니라 다시 하기다. 사슬을 허용하면
                # 되돌리다가 원래 자리로 돌아오는 고리가 생긴다.
                raise RecipeError(f"{where}: 되돌리기('{undo_name}')가 또 되돌리기를 갖는다")

    @property
    def rank(self) -> int:
        """레시피를 고를 때의 순서 — **검증된 것이 먼저**(0), 미검증이 뒤(1). 칸이 없는 레시피(손자리에 든 것)는 0."""
        return 1 if str(self.verification.get("state") or "") == "unverified" else 0

    def undo_action_of(self, action_name: str) -> str:
        return str((self.actions.get(action_name) or {}).get("undo") or "")

    def fingerprint_of(self, action_name: str) -> str:
        """그 절차의 지문. **바뀌면 옛 실적이 안 통한다.**

        절차만이 아니라 그것이 쓰는 셀렉터(`targets`)와 주소(`urls`)까지 같이 해싱한다.
        단계는 그대로 두고 셀렉터만 바꾸면 **같은 이름으로 다른 것을 누를 수 있고**,
        그게 승인을 물려받는 제일 쉬운 길이다. 넓게 잡아서 틀리는 쪽이 안전하다 —
        상관없는 변경으로 실적이 날아가면 한 번 더 되돌려 보면 그만이다.
        """
        payload = json.dumps(
            {
                "action": self.actions.get(action_name) or {},
                "targets": self.targets,
                "urls": self.urls,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _validate_step(self, action_name: str, index: int, step: dict[str, Any]) -> None:
        where = f"{self.name}.{action_name}[{index}]"
        do = str(step.get("do") or "")
        if do not in _STEPS:
            raise RecipeError(f"{where}: 모르는 단계 '{do}' — {sorted(_STEPS)} 중 하나여야 한다")
        if do == "open" and not (step.get("url") or step.get("url_key")):
            raise RecipeError(f"{where}: open에는 url 또는 url_key가 필요하다")
        if do == "open" and step.get("url_key") and step["url_key"] not in self.urls:
            raise RecipeError(f"{where}: urls에 '{step['url_key']}'가 없다")
        if do in {"find", "click", "fill", "press"} and not (
            step.get("target") or step.get("ref")
        ):
            raise RecipeError(f"{where}: {do}에는 target(또는 ref)이 필요하다")
        target = step.get("target")
        if target and target not in self.targets:
            raise RecipeError(f"{where}: targets에 '{target}'가 없다")
        if do in _MUTATING and do != "fill" and not step.get("expect"):
            # fill is exempt: typing into a field is undone by typing again, and
            # its evidence is the save that follows. A click or a key press can
            # commit, so those must prove themselves.
            raise RecipeError(
                f"{where}: {do}에는 expect가 필요하다 — 증거 없이 성공이라고 말하지 않는다"
            )

    def allows(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in self.hosts)

    def risk_of(self, action_name: str) -> RiskLevel:
        risk = str((self.actions.get(action_name) or {}).get("risk") or "L1")
        return {"L0": RiskLevel.L0, "L1": RiskLevel.L1, "L2": RiskLevel.L2}[risk]


def load_recipes(directory: Path) -> dict[str, SiteRecipe]:
    """Every *.json in the recipe directory. A broken one is named, not skipped."""
    recipes: dict[str, SiteRecipe] = {}
    if not directory.exists():
        return recipes
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RecipeError(f"{path.name}: JSON을 읽을 수 없다 — {exc}") from exc
        recipe = SiteRecipe(path, data)
        recipes[recipe.name] = recipe
    return recipes


class SiteRecipeTools:
    """Run a named action from a recipe, step by step, through the browser."""

    def __init__(self, config: JarvisConfig, worker: BrowserWorker) -> None:
        self.config = config
        self.worker = worker
        self.recipes = self._load_all()
        # 되돌리기 **실적** 장부. `register` 에서 게이트웨이 것을 받는다.
        # 없으면(시험 등) 실적이 없는 것으로 친다 — 모르면 안 내려간다.
        self.store: Any = None

    def _load_all(self) -> dict[str, SiteRecipe]:
        """손자리에 든 레시피 + 사람이 승인한 배운 레시피(`config.user_recipes_dir`). 이름이 겹치면 든 것이 이긴다."""
        found = load_recipes(self.config.site_recipe_dir)
        user_dir = getattr(self.config, "user_recipes_dir", None)
        if user_dir is not None:
            try:
                learned = load_recipes(Path(user_dir))
            except Exception:  # noqa: BLE001 — 사람 폴더의 깨진 파일이 손자리를 못 뜨게 하면 안 된다
                learned = {}
            for name, recipe in learned.items():
                found.setdefault(name, recipe)
        return found

    def save_learned(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """사람이 「응」 한 배운 레시피를 저장한다 — 확정본과 **같은 규칙**을 먼저 통과시킨다."""
        user_dir = Path(self.config.user_recipes_dir)
        name = str(recipe.get("name") or "").strip()
        if not name or not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            raise RecipeError(f"배운 레시피 이름이 이상하다: {name!r}")
        path = user_dir / f"{name}.json"
        SiteRecipe(path, recipe)
        user_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
        self.recipes = self._load_all()
        self._tell_browser_about_search_recipes()
        return {"saved": True, "name": name, "path": str(path)}

    def replay_unsaved(
        self,
        recipe_data: dict[str, Any],
        action_name: str = "from_demo",
        progress: Callable[[dict[str, Any]], None] | None = None,
        lang: str = "ko",
    ) -> dict[str, Any]:
        """저장하기 **전의** 레시피를 그대로 한 번 돌려 본다 — 걸음마다 확인(`expect`)이 맞았는지 돌려준다(2026-10-28 대표).

        `{"ok", "total", "failed_at", "reason", "rows"}`. `ok` 는 **모든 걸음이 끝까지 돌고, 누르기 · 키 누르기의 확인이 전부 맞았을 때만**
        참이다 — 확인 결과를 못 읽은 것도 맞다고 치지 않는다(`verified is True` 만). 첫 틀린 걸음에서 멈춘다(뒤를 돌려 봐야 다른 화면 위다).

        사람이 [한 번 해 볼게요]를 눌러 시킨 일이라 게이트웨이의 승인 카드를 거치지 않는다 — 그 단추가 승인이다. 열 수 있는 주소는 저장했을
        때와 같게 레시피의 `hosts` 안으로 막힌다. 입력 값은 **보여 주신 그 말**(`_slots`)로 채운다.
        """
        from .recipe_from_run import step_lines

        recipe = SiteRecipe(Path("demo-unsaved.json"), recipe_data)  # 저장 때와 같은 규칙을 먼저 통과시킨다
        action = recipe.actions.get(action_name)
        if action is None:
            raise RecipeError(f"{recipe.name}에 '{action_name}' 절차가 없다")
        params = {str(k): str(v) for k, v in (recipe_data.get("_slots") or {}).items()}
        shown = step_lines(recipe_data, action_name, lang)
        steps = list(action["steps"])
        total = sum(1 for step in steps if step.get("do") != "dismiss")
        refs: dict[str, str] = {}
        rows: list[dict[str, Any]] = []
        number = 0

        def say(row: dict[str, Any]) -> None:
            if progress is not None:
                try:
                    progress(row)
                except Exception:  # noqa: BLE001 — 화면 알림이 틀어져도 돌려 보기는 간다
                    pass

        def fail(reason: str) -> dict[str, Any]:
            return {"ok": False, "total": total, "failed_at": number, "reason": reason[:200], "rows": rows}

        for step in steps:
            if step.get("do") == "dismiss":
                try:
                    self._run_step(recipe, step, params, refs)
                except Exception:  # noqa: BLE001 — 가로막는 창이 없어서 못 닫은 것은 틀린 것이 아니다
                    pass
                continue
            number += 1
            what, check = shown[number - 1] if number - 1 < len(shown) else (str(step.get("do")), "")
            text = (what + check).strip()
            say({"n": number, "total": total, "text": text, "ok": None, "note": ""})
            try:
                outcome = self._run_step(recipe, step, params, refs)
            except Exception as exc:  # noqa: BLE001 — 어디서 왜 틀렸는지를 사람에게 말해야 한다
                note = f"{type(exc).__name__}: {exc}"[:160]
                rows.append({"n": number, "text": text, "ok": False, "note": note})
                say(rows[-1])
                return fail(note)
            if step.get("do") in {"click", "press"} and outcome.get("verified") is not True:
                evidence = str(outcome.get("evidence") or "").strip()
                if outcome.get("verified") is False:
                    note = (f"the expected change did not show up{f' ({evidence})' if evidence else ''}" if lang == "en"
                            else f"기대한 변화가 화면에 나타나지 않았습니다{f' ({evidence})' if evidence else ''}")
                else:
                    note = "could not read the check result" if lang == "en" else "확인 결과를 읽지 못했습니다"
                rows.append({"n": number, "text": text, "ok": False, "note": note})
                say(rows[-1])
                return fail(note)
            if step.get("do") == "verify" and outcome.get("verified") is not True:
                note = "the check did not pass" if lang == "en" else "확인이 맞지 않았습니다"
                rows.append({"n": number, "text": text, "ok": False, "note": note})
                say(rows[-1])
                return fail(note)
            rows.append({"n": number, "text": text, "ok": True, "note": ""})
            say(rows[-1])
        return {"ok": True, "total": total, "failed_at": None, "reason": "", "rows": rows}

    def forget_learned(self, name: str) -> dict[str, Any]:
        """배운 레시피를 지운다(「되돌려」). 손자리에 든 레시피는 여기서 못 지운다 — 사람 폴더 안의 것만."""
        path = Path(self.config.user_recipes_dir) / f"{name}.json"
        existed = path.exists()
        if existed:
            path.unlink()
        self.recipes = self._load_all()
        self._tell_browser_about_search_recipes()
        return {"removed": existed, "name": name}

    def has_search_for(self, url: str) -> bool:
        """이 주소의 사이트에 검색 절차가 이미 있는가 — 있으면 배우기를 권하지 않는다."""
        return any(
            recipe.allows(url) and any(any(word in key.lower() for word in self._SEARCH_ACTION) for key in recipe.actions)
            for recipe in self.recipes.values()
        )

    # ---- tools ----------------------------------------------------------
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        listing = ", ".join(
            f"{name}({'/'.join(recipe.actions)}){' [미검증]' if recipe.rank else ''}"
            for name, recipe in sorted(self.recipes.items(), key=lambda item: (item[1].rank, item[0]))
        ) or "(등록된 사이트 없음)"
        return [
            {
                "type": "function",
                "function": {
                    "name": "site_run",
                    "description": (
                        "등록된 사이트 절차를 실행한다. 사이트마다 손으로 브라우저를 몰지 말고 "
                        f"이걸 먼저 확인하라. 사용 가능: {listing}"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site": {"type": "string"},
                            "action": {"type": "string"},
                            "params": {"type": "object"},
                        },
                        "required": ["site", "action"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "site_list",
                    "description": "등록된 사이트 절차 목록과 각 절차가 필요한 값을 확인한다.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "site_draft_recipe",
                    "description": (
                        "같은 사이트에서 반복해서 막힐 때, 지금 화면에서 확인한 절차를 "
                        "레시피 **초안**으로 적어 둔다. 다음부터 안 막히게 하는 유일한 방법이다. "
                        "★ 셀렉터를 지어내지 마라 — browser_snapshot·browser_probe_frames 로 "
                        "실제로 확인한 것만 넘겨라. 지금 화면에 안 걸리는 셀렉터가 하나라도 있으면 "
                        "초안을 쓰지 않고 거부한다. 초안은 바로 실행되지 않고 사용자 승인을 거친다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site": {"type": "string", "description": "사이트 키 (예: kmong)"},
                            "hosts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "이 절차가 갈 수 있는 호스트. 여기가 안전선이다",
                            },
                            "action": {"type": "string", "description": "절차 이름 (예: read_posting)"},
                            "action_description": {"type": "string"},
                            "description": {"type": "string"},
                            "risk": {"type": "string", "enum": ["L0", "L1", "L2"]},
                            "urls": {"type": "object", "description": "이름 -> 시작 주소"},
                            "targets": {
                                "type": "object",
                                "description": "이름 -> 셀렉터 목록. 실제로 확인한 것만",
                            },
                            "steps": {
                                "type": "array",
                                "items": {"type": "object"},
                                "description": (
                                    "do: open|find|click|fill|press|dismiss|verify|wait. "
                                    "바꾸는 클릭에는 expect 를 반드시 붙여라(없으면 거부된다)"
                                ),
                            },
                        },
                        "required": ["site", "hosts", "action", "targets", "steps"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "site_review_draft",
                    "description": (
                        "써 둔 초안을 사람이 읽을 수 있게 보여준다. site 를 비우면 초안 목록. "
                        "확정을 요청하기 전에 이걸로 먼저 보여 드려라."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"site": {"type": "string"}},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "site_promote_draft",
                    "description": (
                        "초안을 확정해 앞으로 실제로 쓰이게 한다. "
                        "★ 읽기만 하는 절차(open/find/verify/wait 뿐)는 바로 확정된다 — "
                        "바꾸는 것이 없어 되돌릴 것도 없기 때문이다. "
                        "한 번이라도 누르거나(click) 채우거나(fill) 키를 치면(press) 화면 승인이 필요하니 "
                        "사용자가 쓰겠다고 하신 뒤에 부른다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"site": {"type": "string"}},
                        "required": ["site"],
                    },
                },
            },
        ]

    @property
    def names(self) -> set[str]:
        return {"site_run", "site_list", "site_draft_recipe", "site_review_draft", "site_promote_draft"}

    # 이름에 이것이 들어간 절차는 "그 사이트의 검색"으로 본다. 레시피를 쓰는 사람이
    # 특별한 이름을 외울 필요가 없도록 흔한 말로 잡는다.
    _SEARCH_ACTION = ("search", "검색", "찾기")

    def register(self, gateway: ToolGateway) -> None:
        # 실적 장부는 게이트웨이의 것을 쓴다. **레시피 파일이 아닌 곳**이라는 것이
        # 요점이다 — 자비스가 쓰는 파일에 강등 근거를 두면 자기 등급을 자기가 쓴다.
        self.store = gateway.store
        self._tell_browser_about_search_recipes()
        # 등급이 셋으로 갈린다. 초안 쓰기가 L1 인 것이 이 설계의 핵심이다 —
        # 파일 하나 쓰는 일이고, 그 파일은 아직 아무것도 실행하지 않는다.
        # 실제로 쓰이게 만드는 것(promote)만 사람 앞에 세운다. **단, 되돌릴 것이
        # 있을 때만** — 아래 dynamic_risk 참고.
        risks = {
            "site_list": RiskLevel.L0,
            "site_review_draft": RiskLevel.L0,
            "site_draft_recipe": RiskLevel.L1,
            # 바닥은 L1 이고, 누르거나 채우는 초안이면 `_promote_risk` 가 L2 로
            # 올린다. 게이트웨이는 올리는 것만 허용하므로 이 바닥이 곧 최소 보장이다.
            "site_promote_draft": RiskLevel.L1,
        }
        dynamic = {
            "site_promote_draft": self._promote_risk,
            "site_run": self._run_risk,
        }
        for name, handler in (
            ("site_run", self.run),
            ("site_list", self.list_actions),
            ("site_draft_recipe", self.draft),
            ("site_review_draft", self.review_draft),
            ("site_promote_draft", self.promote_draft),
        ):
            definition = next(
                item["function"] for item in self.ollama_tools if item["function"]["name"] == name
            )
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["description"]),
                    parameters=dict(definition.get("parameters") or {}),
                    # ★ 여기 주석은 원래 "site_run 의 실제 등급은 절차마다 다르고
                    # `run` 안에서 지켜진다"고 적혀 있었는데 **사실이 아니었다.**
                    # `SiteRecipe.risk_of` 는 정의만 돼 있고 부르는 곳이 한 군데도
                    # 없어서, 레시피에 `"risk": "L2"` 라고 적어 둔 절차가 승인 없이
                    # 그냥 돌았다(naver_blog.save_draft 가 실제로 그 상태였다).
                    # 이제 `_run_risk` 로 게이트웨이가 직접 본다.
                    risk_level=risks.get(name, RiskLevel.L1),
                    dynamic_risk=dynamic.get(name),
                    inverse=self._inverses().get(name),
                    handler=handler,
                    enabled=self.config.browser_enabled,
                )
            )

    def _tell_browser_about_search_recipes(self) -> None:
        """**레시피가 브라우저에게 알려 준다** — 반대로 하면 순환한다.

        `browser_site_search` 가 실패했을 때, 그 사이트에 사람이 검토해 둔 검색
        절차가 있으면 그 자리에서 이름을 대 준다. 실측(2026-08-16)에서 사람인이
        정확히 그 모양이었다 — 일반 검색이 실패하자 손으로 더듬다 엉뚱한 칸을
        채웠고, 정작 `site_run saramin search_jobs` 는 그대로 있었다.

        호스트로 걸어 둔다. 자비스가 서 있는 화면이 어느 사이트인지가 판정 기준이고,
        레시피 이름과 호스트가 다를 수 있기 때문이다(`recipes/*.json` 의 `hosts`).
        """
        worker = getattr(self, "worker", None)
        if worker is None:
            return
        read_places: dict[str, list[tuple[str, list[str]]]] = {}
        for recipe in self.recipes.values():
            places = [(prefix, selectors) for prefix, selectors in (getattr(recipe, "read_selectors", None) or {}).items() if selectors]
            for host in recipe.hosts if places else []:
                read_places[host.casefold().removeprefix("www.")] = places
        try:
            worker._recipe_read_selectors = read_places
        except Exception:
            pass
        table: dict[str, str] = {}
        result_markers: dict[str, list[str]] = {}
        for name, recipe in self.recipes.items():
            action = next(
                (
                    key
                    for key in recipe.actions
                    if any(word in key.lower() for word in self._SEARCH_ACTION)
                ),
                "",
            )
            if not action:
                continue
            raw_markers = (recipe.actions.get(action) or {}).get("result_url_contains", [])
            markers = raw_markers if isinstance(raw_markers, list) else [raw_markers]
            clean_markers = [str(marker) for marker in markers if str(marker).strip()]
            for host in recipe.hosts:
                table[host.casefold()] = f'site_run(site="{name}", action="{action}")'
                if clean_markers:
                    result_markers[host.casefold()] = clean_markers
        try:
            worker._recipe_search = table
            worker._recipe_result_markers = result_markers
            worker._site_search_delegate = self._auto_search_recipe
        except Exception:
            pass

    def _auto_search_recipe(
        self, current_url: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | None:
        """현재 호스트의 **L0 검색**만 범용 검색 대신 실행한다.

        이 문은 게이트웨이를 우회하므로 L0보다 높은 절차는 여기서 실행하면 안 된다.
        필요한 값도 query 하나뿐인 절차로 좁힌다. 어느 하나라도 애매하면 ``None``을
        돌려 범용 `browser_site_search`가 원래 하던 판단을 그대로 하게 둔다.
        """
        query = str(arguments.get("query") or "").strip()
        if not current_url or not query:
            return None
        for site, recipe in sorted(self.recipes.items()):
            if not recipe.allows(current_url):
                continue
            for action_name in recipe.actions:
                if not any(word in action_name.lower() for word in self._SEARCH_ACTION):
                    continue
                if recipe.risk_of(action_name) != RiskLevel.L0:
                    continue
                if self._params_of(recipe, action_name) - {"query"}:
                    continue
                result = self.run(
                    {"site": site, "action": action_name, "params": {"query": query}}
                )
                raw_markers = (recipe.actions.get(action_name) or {}).get(
                    "result_url_contains", []
                )
                markers = raw_markers if isinstance(raw_markers, list) else [raw_markers]
                return {
                    **result,
                    "delegated_from": "browser_site_search",
                    "strategy": "reviewed_site_recipe",
                    "result_url_contains": [
                        str(marker) for marker in markers if str(marker).strip()
                    ],
                }
        return None

    def _inverses(self) -> dict[str, InverseSpec]:
        """무엇을 어떻게 되돌리는가.

        ★ 2026-08-15 에 달았다. 그 전까지 **자동으로 되돌아가는 도구는 캘린더 하나뿐**
        이었다(쓰기 도구 22개 중 명세가 달린 것이 2개). `InverseSpec` 의 문서가
        "역동작을 아무도 안 짜놨을 뿐이다"라고 적어 둔 그대로였고, 그래서
        `undo_action` 은 실적 0회였다 — 되돌릴 것이 없으니 되돌릴 일도 없었다.

        확정(promote)은 되돌리기 재료가 이미 다 있었다. `promote_draft` 가 덮어쓸 때
        예전 것을 `drafts/{site}.replaced-{시각}.json` 으로 남겨 두기 때문이다.

        `site_run` 은 **절차가 스스로 선언한다**(action 의 `undo`). 하나로 못 되돌리는
        것은 맞지만, 무엇으로 되돌리는지는 그 사이트를 아는 레시피가 안다.

        `site_draft_recipe` 는 안 단다 — 초안은 아직 아무것도 실행하지 않는다.
        """
        return {
            "site_promote_draft": InverseSpec(
                label="방금 확정한 절차를 초안으로 되돌리기",
                handle_from=self._promote_handle,
                undo=self._undo_promote,
            ),
            "site_run": InverseSpec(
                label="방금 실행한 절차를 되돌리기",
                handle_from=self._run_handle,
                undo=self._undo_run,
            ),
        }

    @staticmethod
    def _run_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        """되돌릴 절차를 선언한 실행만 손잡이를 남긴다.

        `status != "done"` 이면 안 남긴다 — 증거를 못 읽어 멈춘 실행은 **어디까지
        갔는지 모른다.** 모르는 것을 되돌리겠다고 나서면 그게 새로운 사고다.
        """
        if result.get("status") != "done" or not result.get("undo_action"):
            return None
        return {
            "site": str(result.get("site") or ""),
            "action": str(result["undo_action"]),
            "params": dict(result.get("undo_params") or {}),
            # 실적은 **원래 절차**에 대해 쌓인다(되돌린 절차가 아니라). 이 값이
            # 없으면 "scrap 을 되돌려 봤다"가 아니라 "unscrap 을 해 봤다"가 되어
            # 엉뚱한 쪽의 승인이 빠진다.
            "for_action": str(result.get("action") or ""),
        }

    def _undo_run(self, handle: dict[str, Any]) -> dict[str, Any]:
        """역동작을 **레시피 그대로** 실행한다.

        게이트웨이를 다시 거치지 않는다(승인을 또 묻지 않는다는 규칙은
        `ToolGateway.undo` 에 적혀 있다). 대신 `run` 이 하던 검증 — 허용된 호스트,
        단계마다의 expect — 은 그대로 걸린다. 되돌리기라고 증거를 안 보면
        "되돌렸습니다"가 거짓말이 될 수 있다.
        """
        site = str(handle.get("site") or "")
        for_action = str(handle.get("for_action") or "")
        try:
            outcome = self.run(
                {
                    "site": site,
                    "action": handle.get("action"),
                    "params": dict(handle.get("params") or {}),
                }
            )
        except Exception:
            self._revoke_proof(site, for_action)
            raise
        if outcome.get("status") != "done":
            # 되돌아갈 줄 알았는데 안 됐다. **그 믿음 위에서 승인을 빼고 있었으므로**
            # 실적을 회수한다 — 다음부터 이 절차는 다시 사람 앞에 선다.
            self._revoke_proof(site, for_action)
            raise RecipeError(
                f"{site}.{handle.get('action')}: 되돌리기가 증거를 못 읽었다 — "
                f"{outcome.get('reason') or outcome.get('status')}"
            )
        self._record_proof(site, for_action)
        # ★ `{**outcome}` 으로 펼치면 안 된다 — outcome 에도 `action` 이 있어서
        # 이 이름이 조용히 덮인다(시험이 잡았다). 실행 결과와 되돌리기 결과가
        # 같은 칸 이름을 쓰므로 여기서는 손으로 짠다.
        return {
            "action": "undo_site_run",
            "site": outcome.get("site"),
            "ran": outcome.get("action"),
            "status": outcome.get("status"),
            "steps": outcome.get("steps"),
        }

    @staticmethod
    def _promote_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        site = str(result.get("site") or "")
        path = str(result.get("path") or "")
        if not site or not path:
            # 무엇을 되돌려야 할지 모른다. 눌렀는데 아무 일도 안 일어나는 버튼이
            # 제일 나쁘므로 아예 안 내준다(캘린더가 같은 규율을 쓴다).
            return None
        return {"site": site, "path": path, "replaced_backup": str(result.get("replaced_backup") or "")}

    def _undo_promote(self, handle: dict[str, Any]) -> dict[str, Any]:
        """확정을 물린다. **확정본을 지우는 게 아니라 초안으로 되돌린다.**

        되돌리기가 일을 없애 버리면 그것이 새로운 사고가 된다 — 자비스가 만든
        절차는 남기고, "앞으로 실제로 쓰인다"는 것만 취소한다. 초안 폴더는
        `load_recipes` 의 glob 에 안 잡히므로 그 자리가 곧 '안 쓰임'이다.
        """
        site = str(handle.get("site") or "")
        target = Path(str(handle.get("path") or ""))
        backup = str(handle.get("replaced_backup") or "")
        if not site or not target.exists():
            raise RecipeError(f"{site}: 확정본이 이미 없다 — 되돌릴 것이 없다")

        drafts = self._drafts_dir()
        drafts.mkdir(parents=True, exist_ok=True)
        draft_path = drafts / f"{site}.json"
        draft_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")

        if backup and Path(backup).exists():
            # 덮어쓰기였다. 예전 확정본을 그 자리에 되돌려 놓는다.
            target.write_text(Path(backup).read_text(encoding="utf-8"), encoding="utf-8")
            Path(backup).unlink()
            restored = "previous"
        else:
            # 새로 생긴 것이었다. 확정본 자리에서 빼면 원래대로다.
            target.unlink()
            restored = "removed"

        self.recipes = self._load_all()
        return {
            "action": "undo_site_promote_draft",
            "site": site,
            "restored": restored,
            "draft_path": str(draft_path),
            "active": site in self.recipes,
        }

    # ---- 등급을 인자에서 정한다 ------------------------------------------
    # ---- 되돌릴 수 있다는 **실적** ------------------------------------------

    def _record_proof(self, site: str, action: str) -> None:
        recipe = self.recipes.get(site)
        if self.store is None or recipe is None or action not in recipe.actions:
            return
        self.store.record_inverse_proof(site, action, recipe.fingerprint_of(action))

    def _revoke_proof(self, site: str, action: str) -> None:
        if self.store is None or not site or not action:
            return
        self.store.revoke_inverse_proof(site, action)

    def _proven_reversible(self, recipe: SiteRecipe, action: str) -> bool:
        """이 절차의 역동작이 **실제로 성공한 적이 있는가.**

        지문까지 같아야 한다 — 레시피가 바뀌었으면 같은 이름이어도 다른 일이다.
        장부가 없으면(시험 등) 실적도 없는 것으로 친다: 모르면 안 내려간다.
        """
        if self.store is None or not recipe.undo_action_of(action):
            return False
        return bool(
            self.store.has_inverse_proof(recipe.name, action, recipe.fingerprint_of(action))
        )

    def _run_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """실행할 절차가 스스로 적어 둔 등급. 모르는 사이트는 사람 앞에 세운다.

        ## 되돌려 본 적이 있으면 안 올린다 (2026-08-15)

        **강등이 아니라 "안 올리는 것"이다.** 등록 등급(L1)이 바닥이고
        `effective_risk` 가 `max(등록, 동적)` 이라, 여기서 L1 을 돌려주면 L1 이 된다 —
        L0 로는 내려갈 수 없다. 승인 우회로가 안 되는 이유가 이 구조다.

        근거는 **레시피가 적은 주장이 아니라 실적**이다(`recipe_inverse_proofs`).
        레시피는 자비스가 스스로 초안 쓰므로, 거기 적힌 말로 등급을 내리면 자비스가
        자기 승인을 자기가 쓰는 것이 된다 — `_approved` 인자로 뚫려 있던 그 구멍이다.

        되돌리기가 한 번이라도 실패하면 실적이 회수되어 다시 L2 로 돌아간다.
        """
        recipe = self.recipes.get(str(arguments.get("site") or ""))
        if recipe is None:
            return RiskLevel.L1  # 어차피 `run` 이 "모르는 사이트"로 거절한다
        action = str(arguments.get("action") or "")
        if action not in recipe.actions:
            return RiskLevel.L1
        declared = recipe.risk_of(action)
        if declared >= RiskLevel.L2 and self._proven_reversible(recipe, action):
            return RiskLevel.L1
        return declared

    def _promote_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """**읽기만 하는 레시피는 사람을 안 부른다.**

        확정을 사람에게 맡긴 이유는 레시피가 실행될 때 감시를 덜 받기 때문인데,
        `open`·`find`·`verify` 뿐인 절차는 아무것도 바꾸지 않는다 — 되돌릴 것이
        없으면 물어볼 것도 없다. 이 저장소의 규칙 그대로다: **자율은 대담해져서가
        아니라 되돌릴 수 있어서 얻는다.**

        조사 레시피는 자비스가 혼자 쌓고, 사람 승인은 **누르고 채우는 것**에만 남는다.

        읽을 수 없는 초안이면 L2 다. 판단이 안 서면 사람이 본다.
        """
        path = self._drafts_dir() / f"{str(arguments.get('site') or '').strip()}.json"
        if not path.exists():
            return RiskLevel.L2
        data = json.loads(path.read_text(encoding="utf-8"))
        return RiskLevel.L1 if not read_only_reason(data) else RiskLevel.L2

    def list_actions(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        del arguments
        return {
            "sites": [
                {
                    "site": name,
                    "description": recipe.description,
                    "hosts": recipe.hosts,
                    # 검증된 것이 먼저 나온다(위 정렬) — 미검증은 모델이 그렇게 알 수 있게 칸을 둔다.
                    **({"verification": str(recipe.verification.get("state") or ""),
                        "usage": {"runs": int(recipe.usage.get("runs") or 0), "succeeded": int(recipe.usage.get("succeeded") or 0)}}
                       if recipe.verification else {}),
                    "actions": [
                        {
                            "action": action_name,
                            "risk": str((action or {}).get("risk") or "L1"),
                            "params": sorted(self._params_of(recipe, action_name)),
                            # 이름으로 받는 인자는 쓸 수 있는 이름을 같이 보여 준다 — 모델이 번호를 짐작하지 않게(2026-10-04).
                            **(
                                {"param_names": {
                                    param: sorted(name for name in table if len(name) <= 2)
                                    for param, table in recipe.param_values.items()
                                    if param in self._params_of(recipe, action_name)
                                }}
                                if any(param in self._params_of(recipe, action_name) for param in recipe.param_values)
                                else {}
                            ),
                            "description": str((action or {}).get("description") or ""),
                        }
                        for action_name, action in recipe.actions.items()
                    ],
                }
                for name, recipe in sorted(self.recipes.items(), key=lambda item: (item[1].rank, item[0]))
            ]
        }

    # ---- the run --------------------------------------------------------
    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        site = str(arguments.get("site") or "")
        action_name = str(arguments.get("action") or "")
        params = dict(arguments.get("params") or {})
        recipe = self.recipes.get(site)
        if recipe is None:
            raise RecipeError(f"모르는 사이트: {site or '(없음)'} — 등록된 것: {sorted(self.recipes)}")
        ok = False
        try:
            result = self._run_recipe(recipe, site, action_name, arguments, params)
            ok = result.get("status") == "done"
            return result
        finally:
            self._record_use(recipe, ok)

    def _record_use(self, recipe: SiteRecipe, ok: bool) -> None:
        """쓴 횟수 · 성공 수를 **사람 폴더의 레시피 파일**에 센다(2026-10-28). 손자리에 든 레시피는 건드리지 않는다. 못 써도 일은 간다."""
        try:
            user_dir = getattr(self.config, "user_recipes_dir", None)
            path = Path(recipe.path)
            if user_dir is None or path.parent != Path(user_dir) or not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            usage = dict(data.get("usage") or {})
            usage["runs"] = int(usage.get("runs") or 0) + 1
            usage["succeeded"] = int(usage.get("succeeded") or 0) + (1 if ok else 0)
            usage["last_at"] = time.time()
            data["usage"] = usage
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            recipe.usage = usage
        except Exception:  # noqa: BLE001 — 세기가 틀어져도 레시피는 돈다
            pass

    def _run_recipe(self, recipe: SiteRecipe, site: str, action_name: str, arguments: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        action = recipe.actions.get(action_name)
        if action is None:
            raise RecipeError(f"{site}에 '{action_name}' 절차가 없다 — 있는 것: {sorted(recipe.actions)}")
        params = self._named_values(recipe, site, action_name, params)
        missing = sorted(self._params_of(recipe, action_name) - set(params))
        if missing:
            # Guessing a missing value is how a post gets published with a
            # placeholder title in it.
            raise RecipeError(f"{site}.{action_name}: 값이 없다 — {missing}")

        refs: dict[str, str] = {}
        steps_done: list[dict[str, Any]] = []
        for index, step in enumerate(action["steps"]):
            outcome = self._run_step(recipe, step, params, refs)
            steps_done.append({"step": index, "do": step["do"], **outcome})
            if outcome.get("verified") is False:
                # Stop here and say so. Carrying on would run the rest of the
                # recipe against a page that is not in the state it assumes.
                return {
                    "site": site, "action": action_name, "status": "unverified",
                    "steps": steps_done,
                    "reason": "화면에서 증거를 못 읽었습니다. 클릭이 먹었을 수 있으니 다시 실행하지 마시고 화면을 확인해 주세요.",
                }
        done = {"site": site, "action": action_name, "status": "done", "steps": steps_done}
        if (
            recipe.risk_of(action_name) == RiskLevel.L0
            and any(word in action_name.lower() for word in self._SEARCH_ACTION)
        ):
            # 목록 화면까지만 열고 끝내면 작은 모델은 snapshot의 j번호를 결과 rank로
            # 착각한다(라이브: j57 → browser_open_result(rank=57)). 검색 레시피가
            # 아는 상세 URL 표식으로 바로 순위를 만들어 같은 결과에 싣는다.
            collector = getattr(self.worker, "collect_reviewed_search_results", None)
            if callable(collector):
                raw_markers = (recipe.actions.get(action_name) or {}).get(
                    "result_url_contains", []
                )
                markers = raw_markers if isinstance(raw_markers, list) else [raw_markers]
                listing = collector(
                    [str(marker) for marker in markers if str(marker).strip()], limit=15
                )
                done["results"] = list(listing.get("results") or [])
                done["result_count"] = int(listing.get("result_count") or 0)
                done["result_url"] = str(listing.get("url") or "")
                done["instruction"] = (
                    f"검색 결과 {done['result_count']}건을 함께 돌려준다. snapshot의 j번호가 "
                    "아니라 이 results의 rank를 browser_open_result에 줘라."
                )
        undo_name = recipe.undo_action_of(action_name)
        if undo_name:
            # ★ 되돌리기에 **필요한 값만** 싣는다. 원래 params 를 통째로 실으면
            # 로그인 절차의 아이디·비밀번호까지 장부에 남는다. 되돌리기가 쓰는 것은
            # 그 역동작의 자리표시자뿐이라, 거기 없는 값은 애초에 남길 이유가 없다.
            needed = self._params_of(recipe, undo_name)
            done["undo_action"] = undo_name
            done["undo_params"] = {k: v for k, v in params.items() if k in needed}
        return done

    def _run_step(
        self,
        recipe: SiteRecipe,
        step: dict[str, Any],
        params: dict[str, Any],
        refs: dict[str, str],
    ) -> dict[str, Any]:
        do = str(step["do"])
        if do == "open":
            url = str(step.get("url") or recipe.urls[str(step["url_key"])])
            url = self._fill_in(url, params)
            if not recipe.allows(url):
                raise RecipeError(f"{recipe.name}: 허용되지 않은 주소 {url} — hosts={recipe.hosts}")
            # ★ **검토된 문**으로 연다 (2026-08-13).
            #
            # 그냥 `browser_open` 을 쓰면, 모델이 지어낸 검색 주소를 가로채는 장치에
            # 이 주소까지 같이 걸린다 — 레시피의 `?searchword={query}` 가 딱 그 모양이다.
            # 실제로 그날 사람인 레시피가 통째로 우회당했다(150초 성공 → 204초 미달).
            #
            # 레시피 주소는 지어낸 것이 아니라 **사람이 보고 확정한 것**이다. 그 차이를
            # 인자가 아니라 **문**으로 표시한다(`_approved` 구멍에서 배운 규칙).
            # ★ **검토된 절차로서** 연다 (2026-08-13).
            #
            # 그냥 부르면, 모델이 지어낸 검색 주소를 가로채는 장치에 이 주소까지
            # 같이 걸린다 — 레시피의 `?searchword={query}` 가 딱 그 모양이라 실제로
            # 사람인 레시피가 통째로 우회당했다(150초 성공 → 204초 미달).
            #
            # 레시피 주소는 지어낸 것이 아니라 **사람이 보고 확정한 것**이다.
            result = self.worker.execute_trusted("browser_open", {"url": url})
            return {"url": result.get("url", "")}
        if do == "wait":
            self.worker.execute("browser_wait", {"milliseconds": int(step.get("ms") or 800)})
            return {}
        if do == "dismiss":
            result = self.worker.execute(
                "browser_dismiss_dialog", {"rounds": int(step.get("rounds") or 2)}
            )
            return {"dialogs": result.get("dialog_count", 0)}
        if do == "verify":
            result = self.worker.execute_trusted(
                "browser_verify",
                {
                    "expect": self._expect_of(step, params),
                    "timeout_ms": int(step.get("timeout_ms") or 6000),
                },
            )
            verification = result.get("verification", {})
            return {
                "verified": verification.get("status") == "verified",
                "evidence": verification.get("evidence", ""),
            }

        ref = self._resolve_ref(recipe, step, refs)
        if do == "find":
            return {"ref": ref, "as": step.get("as", "")}
        if do == "fill":
            self.worker.execute(
                "browser_fill", {"ref": ref, "value": self._fill_in(str(step.get("value") or ""), params)}
            )
            return {"ref": ref}
        payload: dict[str, Any] = {"ref": ref, "expect": self._expect_of(step, params)}
        if step.get("verify_timeout_ms"):
            payload["verify_timeout_ms"] = int(step["verify_timeout_ms"])
        if do == "press":
            payload["key"] = str(step.get("key") or "Enter")
            result = self.worker.execute_trusted("browser_press", payload)
        else:
            result = self.worker.execute_trusted("browser_click", payload)
        return {
            "ref": ref,
            "verified": result.get("verified"),
            "evidence": result.get("verification", {}).get("evidence", ""),
        }

    def _resolve_ref(
        self, recipe: SiteRecipe, step: dict[str, Any], refs: dict[str, str]
    ) -> str:
        named = str(step.get("ref") or "")
        if named.startswith("$"):
            key = named[1:]
            if key not in refs:
                raise RecipeError(f"{recipe.name}: 앞 단계에서 '{key}'를 찾은 적이 없다")
            return refs[key]
        target = str(step["target"])
        found = self.worker.execute(
            "browser_find_selector", {"selectors": recipe.targets[target]}
        )
        ref = str(found["ref"])
        refs[step.get("as") or target] = ref
        return ref

    # ---- 초안 쓰기 -------------------------------------------------------
    #
    # 여기까지 레시피는 사람만 쓸 수 있었다. 그런데 자비스는 막힌 그 순간에 **이미
    # 진짜 화면을 보고 있다** — `browser_probe_frames` 로 프레임을 세고
    # `browser_snapshot` 으로 ref 를 받는다. 셀렉터를 지어낼 필요가 없는 자리에서,
    # 관찰한 것을 JSON 으로 옮겨 적는 마지막 한 걸음만 없었다.
    #
    # ★ 그래서 자동 생성을 여는 대신 **초안 쓰기**를 연다. 둘은 다르다:
    #
    #     쓴다   자비스가.  단, 지금 화면에 **실제로 있는** 셀렉터만.
    #     쓴다고 말한다   아무 때나. 이건 못 하게 막는다.
    #     확정한다   사람이. L2 화면 승인으로 `recipes/` 에 올라간다.
    #
    # 왜 확정을 사람이 하는가. 레시피는 실행될 때 감시를 덜 받는다 — `site_run`
    # 한 번에 절차가 통째로 돈다. 그럴듯한데 엉뚱한 것을 누르는 레시피는 레시피가
    # 없는 것보다 나쁘다. 다만 그 위험은 이미 좁다: 로드 때 expect 를 강제하고,
    # hosts 밖으로 못 가고, 증거를 못 읽으면 멈춘다. 최악이 "확인 못 하고 멈춤"이라
    # 초안까지 막을 이유는 없었다.
    def _drafts_dir(self) -> Path:
        return self.config.site_recipe_dir / DRAFTS_DIRNAME

    def _confirm_selectors_live(
        self, targets: dict[str, list[str]], used: set[str]
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        """지금 화면에서 **실제로 걸리는** 셀렉터만 남긴다.

        ★ 이 검사가 이 기능의 전부다. 이게 없으면 "자비스가 레시피를 쓴다"는 것은
        곧 "자비스가 셀렉터를 지어낸다"가 된다 — 추측한 셀렉터가 이틀을 태웠고,
        그래서 모델에게는 지어내지 말라고 프롬프트에 못을 박아 두었다. 그 못을
        도구로 뽑아 주면 안 된다.

        확인된 셀렉터를 **앞으로 보낸다.** 지금 걸리는 것이 제일 정확하고, 나머지는
        구조가 바뀌었을 때의 대비책으로 뒤에 남는다(프로덕션 레시피와 같은 규칙).

        하나라도 못 찾으면 초안을 쓰지 않는다. 못 찾은 것을 그냥 적어 두면, 그
        레시피는 **다음에 실행될 때** 처음으로 틀린 것이 드러난다 — 사람이 화면을
        떠난 뒤다.
        """
        confirmed: dict[str, str] = {}
        missing: list[str] = []
        ordered: dict[str, list[str]] = {}
        for name in sorted(used):
            selectors = [s for s in targets.get(name, []) if str(s).strip()]
            if not selectors:
                missing.append(f"{name}: 셀렉터가 비었다")
                continue
            hit = ""
            why: list[str] = []
            for selector in selectors:
                try:
                    self.worker.execute("browser_find_selector", {"selectors": [selector]})
                except Exception as exc:  # noqa: BLE001 - 못 찾은 것도 결과다
                    # ★ 왜 안 걸렸는지를 버리지 않는다.
                    #
                    # 브라우저는 `=0`(그런 요소가 없다)과 `=hidden`(있는데 안 보인다)을
                    # 구분해서 알려주는데, 처음엔 그걸 통째로 삼키고 "걸리는 것이
                    # 없다"고만 했다. 둘은 다음 수가 완전히 다르다 —
                    #   =0      셀렉터가 틀렸다. 다른 것을 찾아라
                    #   =hidden 요소는 맞다. 첫 번째가 숨은 중복이거나 스크롤 밖이다
                    #           (2026-08-10 크몽에서 실제로 겪었다: probe 는 3개라는데
                    #            초안은 없다고 했고, 이유를 안 알려줘서 헤맸다)
                    why.append(f"{selector} → {str(exc)[:120]}")
                    continue
                hit = selector
                break
            if not hit:
                missing.append(f"{name}:\n      " + "\n      ".join(why))
                continue
            confirmed[name] = hit
            ordered[name] = [hit] + [s for s in selectors if s != hit]
        if missing:
            raise RecipeError(
                "지금 화면에서 확인되지 않는 target 이 있어 초안을 쓰지 않았다:\n  "
                + "\n  ".join(missing)
                + "\n\n확인된 것만 적는 게 이 기능의 전부다. 짐작으로 채우지 마라.\n"
                "  `=0` 이면 그런 요소가 없다 → browser_probe_frames 로 실제 셀렉터를 찾아라.\n"
                "  `=hidden` 이면 요소는 맞는데 첫 번째가 안 보인다 → 더 좁은 셀렉터를 쓰거나\n"
                "  스크롤·펼치기로 화면에 띄운 뒤 다시 불러라.\n"
                "  절차가 도는 그 화면이 아니라면 browser_open 으로 먼저 그 화면을 열어라."
            )
        # 쓰이지 않은 target 도 그대로 보존한다 — 사람이 손으로 적어 둔 것일 수 있다.
        for name, selectors in targets.items():
            ordered.setdefault(name, [str(s) for s in selectors])
        return ordered, confirmed

    def draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        site = str(arguments.get("site") or "").strip()
        action_name = str(arguments.get("action") or "").strip()
        if not site or not action_name:
            raise RecipeError("site 와 action 이 필요하다")
        steps = list(arguments.get("steps") or [])
        if not steps:
            raise RecipeError("steps 가 비었다 — 무엇을 하는 절차인지가 없다")

        targets = {
            str(k): [str(s) for s in (v if isinstance(v, list) else [v])]
            for k, v in (arguments.get("targets") or {}).items()
        }
        used = {str(s["target"]) for s in steps if s.get("target")}
        unknown = sorted(used - set(targets))
        if unknown:
            raise RecipeError(f"steps 가 쓰는 target 이 targets 에 없다: {unknown}")

        ordered, confirmed = self._confirm_selectors_live(targets, used)
        # 등급을 안 적어 주면 **걸음을 보고 정한다.** 예전 기본값은 무조건 L2 였는데,
        # 그러면 읽기만 하는 절차도 스스로 L2 라고 적어 버려 자동 확정이 영영 안
        # 걸린다(시험에서 실제로 그렇게 걸렸다). 바꾸는 걸음이 하나라도 있으면 L2 다.
        declared = str(arguments.get("risk") or "").strip().upper()
        if declared not in {"L0", "L1", "L2"}:
            mutating = [
                s for s in steps if str(s.get("do") or "") not in _READ_ONLY_STEPS
            ]
            declared = "L2" if mutating else "L1"
        data = {
            "name": site,
            "description": str(arguments.get("description") or ""),
            "hosts": [str(h).lower() for h in (arguments.get("hosts") or [])],
            "urls": {str(k): str(v) for k, v in (arguments.get("urls") or {}).items()},
            "targets": ordered,
            "actions": {
                action_name: {
                    "description": str(arguments.get("action_description") or ""),
                    "risk": declared,
                    "steps": steps,
                }
            },
            # `_` 로 시작하는 키는 엔진이 무시한다 — 왜 그렇게 됐는지 적는 자리다.
            "_drafted_by": "jarvis",
            "_confirmed_live": confirmed,
        }

        drafts = self._drafts_dir()
        drafts.mkdir(parents=True, exist_ok=True)
        path = drafts / f"{site}.json"
        # 확정본과 **똑같은 규칙**으로 먼저 통과시킨다. expect 없는 클릭, hosts 누락,
        # 모르는 단계가 여기서 걸린다 — 승인 화면까지 가져가서 걸리면 늦다.
        SiteRecipe(path, data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # 확정 때 사람을 부를지 여기서 미리 알려 준다 — 모델이 "승인 받아야 하나"를
        # 짐작하지 않도록. 실제 판정은 확정 시점에 파일을 다시 읽어서 한다.
        blocking = read_only_reason(data)
        return {
            "action": "site_draft_recipe",
            "site": site,
            "draft_path": str(path),
            "confirmed_live": confirmed,
            "status": "draft",
            "read_only": not blocking,
            "needs_approval_because": blocking,
            "instruction": (
                (
                    f"★ 초안만 썼다. 아직 실행되지 않는다({DRAFTS_DIRNAME}/ 안에 있어서 site_run 이 "
                    "집지 않는다). 읽기만 하는 절차라 확정에 승인이 필요 없다 — "
                    "site_promote_draft 를 바로 불러서 쓸 수 있게 만들어라."
                )
                if not blocking
                else (
                    f"★ 초안만 썼다. 아직 실행되지 않는다({DRAFTS_DIRNAME}/ 안에 있어서 site_run 이 "
                    f"집지 않는다). 바꾸는 걸음이 있어서({blocking}) 확정에 화면 승인이 필요하다. "
                    "사용자에게 site_review_draft 로 내용을 보여 드리고, 쓰겠다고 하시면 "
                    "site_promote_draft 를 불러라. 스스로 확정하지 마라."
                )
            ),
        }

    def review_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        site = str(arguments.get("site") or "").strip()
        drafts = self._drafts_dir()
        if not site:
            return {
                "action": "site_review_draft",
                "drafts": sorted(p.stem for p in drafts.glob("*.json")) if drafts.exists() else [],
            }
        path = drafts / f"{site}.json"
        if not path.exists():
            raise RecipeError(f"{site} 초안이 없다 — 있는 것: {sorted(p.stem for p in drafts.glob('*.json'))}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "action": "site_review_draft",
            "site": site,
            "draft_path": str(path),
            "hosts": data.get("hosts"),
            "confirmed_live": data.get("_confirmed_live"),
            "recipe": data,
            "replaces_existing": site in self.recipes,
            "read_only": not read_only_reason(data),
            "needs_approval_because": read_only_reason(data),
        }

    def promote_draft(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """초안을 확정본으로 올린다.

        **등급은 초안이 정한다**(`_promote_risk`): 읽기만 하는 절차면 L1 이라 그냥
        올라가고, 누르거나 채우는 절차면 L2 라 화면 승인을 거친다. 조사 레시피가
        사람 손을 안 거치고 쌓이게 하려는 것 — 확정을 사람이 하던 이유는 레시피가
        실행될 때 감시를 덜 받아서인데, 바꾸는 것이 없으면 그 이유가 성립하지 않는다.

        덮어쓰는 경우 예전 것을 초안 폴더에 남긴다. 되돌릴 수 없는 일을 만들지
        않는다는 이 저장소의 규칙 그대로다.
        """
        site = str(arguments.get("site") or "").strip()
        path = self._drafts_dir() / f"{site}.json"
        if not path.exists():
            raise RecipeError(f"{site} 초안이 없다")
        data = json.loads(path.read_text(encoding="utf-8"))
        target = self.config.site_recipe_dir / f"{site}.json"
        SiteRecipe(target, data)  # 올리기 직전에 한 번 더 — 파일이 손으로 고쳐졌을 수 있다

        backup = ""
        if target.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            kept = self._drafts_dir() / f"{site}.replaced-{stamp}.json"
            kept.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            backup = str(kept)

        self.config.site_recipe_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        path.unlink()
        self.recipes = self._load_all()
        return {
            "action": "site_promote_draft",
            "site": site,
            "path": str(target),
            "replaced_backup": backup,
            "actions": sorted((self.recipes.get(site).actions if site in self.recipes else {})),
            "instruction": (
                "확정됐다. 이제 site_run 으로 실행할 수 있다. 도구 설명의 목록은 "
                "재기동 전까지 낡아 있으니 site_list 로 확인해라."
            ),
        }

    @staticmethod
    def _expect_of(step: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        expect = dict(step.get("expect") or {})
        if expect.get("value"):
            expect["value"] = SiteRecipeTools._fill_in(str(expect["value"]), params)
        return expect

    @staticmethod
    def _fill_in(template: str, params: dict[str, Any]) -> str:
        return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), template)

    @staticmethod
    def _named_values(recipe: SiteRecipe, site: str, action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """이름으로 받은 값을 레시피의 표로 사이트 값으로 바꾼다. 여러 개는 쉼표·빗금·가운뎃점·빈칸으로 나눠 준다.

        표에 있는 값(번호)을 그대로 준 것은 받는다. 표에 없는 것은 **실행하지 않고** 쓸 수 있는 이름을 댄다 — 짐작한 번호로
        검색한 결과는 오류가 아니라 그럴듯한 엉뚱한 목록이라, 받아 주면 틀린 결론의 근거가 된다.
        """
        tables = getattr(recipe, "param_values", None) or {}
        if not tables:
            return params
        out = dict(params)
        for param, table in tables.items():
            if param not in out:
                continue
            names = [part for part in re.split(r"[,/·\s]+|(?<=[가-힣])(?:와|과|및)\s", str(out[param]).strip()) if part]
            values: list[str] = []
            unknown: list[str] = []
            for name in names:
                value = table.get(name) or (name if name in table.values() else "")
                if not value:
                    unknown.append(name)
                elif value not in values:
                    values.append(value)
            if unknown or not values:
                short = sorted({name for name in table if len(name) <= 2})
                raise RecipeError(
                    f"{site}.{action_name}: 「{', '.join(unknown) or out[param]}」은(는) 이 사이트에서 쓸 수 있는 {param} 이름이 아니다 — "
                    f"쓸 수 있는 이름: {', '.join(short or sorted(table))}. 번호를 짐작해 넣지 말고 이 이름 가운데서 골라라."
                )
            out[param] = (getattr(recipe, "param_joins", None) or {}).get(param, ",").join(values)
        return out

    @staticmethod
    def _params_of(recipe: SiteRecipe, action_name: str) -> set[str]:
        """Every {placeholder} the action's steps refer to."""
        found: set[str] = set()
        for step in (recipe.actions.get(action_name) or {}).get("steps", []):
            for key in ("value", "url"):
                found.update(_PLACEHOLDER.findall(str(step.get(key) or "")))
            if step.get("url_key"):
                found.update(_PLACEHOLDER.findall(recipe.urls.get(str(step["url_key"]), "")))
            found.update(_PLACEHOLDER.findall(str((step.get("expect") or {}).get("value") or "")))
        return found
