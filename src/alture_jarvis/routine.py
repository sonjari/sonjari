"""모델 없는 루틴 — 레시피 주소로 **브라우저 없이** 받아 목록 칸을 읽는다 (2026-10-23 · 전략안 §55-39 · §55-40 첫 칸).

    python -m alture_jarvis.routine run --recipe saramin --query "연구비 관리" --region 부산 --out jobs.json

스토어 판은 앱 안 파이썬을 밖에서 못 띄운다 → 실행 별칭 `sonjari.exe -m alture_jarvis.routine run ...`
(`claude_hooks` · `mcp_connect.server_entry` 와 같은 길 · `command_line()` 이 그 줄을 만든다).

## 왜 (10-22~23 채용 봇 판 · 전략안 §55-39)

손자리는 매칭 · 리포트 · 시험은 잘 만들었고, 무너진 곳은 전부 **사이트 길을 스스로 지어낸 자리**였다 — 통합검색 주소
(`/zf_user/search?...&loc_mcd=3`, 공고 0개), 짐작한 지역 번호. 같은 날 레시피 주소(`/zf_user/search/recruit?...&loc_mcd=106000`)를
브라우저 없이 받으니 공고 10개 · 근무지 부산이 나왔다. 길은 레시피가 알고, 루틴은 그 길을 매번 똑같이 돈다.

## 지키는 것

- **주소 · 번호는 레시피에서만.** 지역 이름 → 번호는 레시피 `param_values.region` 표(`SiteRecipeTools._named_values` — 브라우저 길과
  같은 함수)가 바꾼다. 표에 없는 이름은 실행하지 않는다. 주소를 직접 받는 문은 없다 — 루틴 설명서에 `url` 칸이 있으면 거절한다.
- **깨진 것을 조용히 넘기지 않는다.** 0건(사이트가 「결과 없음」이라고 말한 것)과 깨짐(칸을 못 읽음 · 모양이 평소와 다름)을 가른다.
  깨짐이면 `--out` 파일을 덮지 않는다 — 지난번 좋은 결과가 남고, 틀린 값이 「새 결과」로 나가지 않는다.
- **근거를 붙인다.** 줄마다 출처 주소 · 받은 시각 · 원문 한 줄.
- **표준 라이브러리만.** HTML 은 `html.parser` 로 읽는다(새 의존 없음).

## 사람인 목록에서 실측한 함정 (2026-10-23 · `tests/fixtures/routine_lists/saramin_*.html`)

- 결과가 0건이면 사람인은 「검색결과가 없습니다」 아래에 **인기 공고 20개**를 같은 `item_recruit` 모양으로 붙인다.
  공고 칸만 세면 0건을 20건으로 읽는다 → `#recruit_info_list` 안만 읽는다.
- 「검색결과가 없습니다」 글자는 **모든 검색 화면**의 자동완성 상자에도 있다 → 글자가 아니라 `.info_no_result` 칸으로 0건을 가른다.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

#: 끝 코드 — 예약 · 사람 모두 이것만 보고 가를 수 있게.
EXIT = {"ok": 0, "empty": 0, "refused": 2, "broken": 3, "failed": 4}

#: 루틴 설명서(JSON)가 받는 칸. **`url` 은 없다** — 주소는 레시피에서만 나온다.
SPEC_KEYS = frozenset({"recipe", "query", "region"})

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/125.0.0.0 Safari/537.36")
_MAX_BYTES = 8 * 1024 * 1024
_TIMEOUT_SEC = 20
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

Fetch = Callable[[str], "tuple[str, str]"]  # 주소 → (본문, 마지막 주소)


class RoutineRefused(ValueError):
    """돌리기 전에 멈춘다 — 레시피에 없는 사이트 · 지역 · 주소."""


# ── 레시피 ───────────────────────────────────────────────────────────────────

def builtin_recipe_dir() -> Path:
    """손자리에 든 레시피 자리 — `config.site_recipe_dir` 기본값과 같은 계산(환경 변수도 같이 본다)."""
    from .config import setting  # 우리 설정은 환경에서 직접 읽지 않는다(환경 → 보관소 순서 · 2026-10-09 규칙)

    value = setting("JARVIS_SITE_RECIPE_DIR")
    return Path(value) if value else Path(__file__).resolve().parents[2] / "recipes"


def load_recipe(name: str, recipe_dir: Path | None = None) -> Any:
    from .site_recipes import RecipeError, SiteRecipe

    name = str(name or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise RoutineRefused(f"레시피 이름이 이상하다: 「{name}」")
    path = Path(recipe_dir or builtin_recipe_dir()) / f"{name}.json"
    if not path.exists():
        raise RoutineRefused(f"레시피 「{name}」가 없다({path.parent}). 루틴은 레시피가 있는 사이트에서만 돈다.")
    try:
        return SiteRecipe(path, json.loads(path.read_text(encoding="utf-8")))
    except (RecipeError, ValueError) as exc:
        raise RoutineRefused(f"레시피 「{name}」를 못 읽었다 — {exc}") from exc


def normalize_spec(spec: Any) -> dict[str, str]:
    """루틴 설명서 검사. 모르는 칸(특히 `url`)은 거절한다 — 조용히 버리면 지어낸 주소가 통과한 것처럼 보인다."""
    if not isinstance(spec, dict):
        raise RoutineRefused("루틴 설명서는 JSON 객체여야 한다")
    extra = sorted(set(spec) - SPEC_KEYS)
    if extra:
        hint = " 주소는 레시피에서만 나온다 — 직접 넣지 않는다." if any("url" in str(key).lower() for key in extra) else ""
        raise RoutineRefused(f"루틴 설명서가 모르는 칸: {', '.join(map(str, extra))}.{hint}")
    out = {key: str(spec.get(key) or "").strip() for key in SPEC_KEYS}
    if not out["recipe"]:
        raise RoutineRefused("recipe 가 비었다")
    if not out["query"]:
        raise RoutineRefused("query(검색어)가 비었다")
    if out["recipe"] not in PARSERS:
        raise RoutineRefused(f"「{out['recipe']}」는 아직 루틴으로 읽을 줄 모른다(지금은 {', '.join(sorted(PARSERS))}).")
    return out


def build_url(recipe: Any, spec: dict[str, str]) -> tuple[str, dict[str, str]]:
    """레시피 주소 틀에 값을 넣는다. 지역 이름 → 번호는 레시피 표가 바꾼다(브라우저 길과 같은 함수)."""
    from .site_recipes import RecipeError, SiteRecipeTools

    url_key = "search_region" if spec.get("region") else "search"
    template = recipe.urls.get(url_key)
    if not template:
        raise RoutineRefused(f"레시피 「{recipe.name}」에 `{url_key}` 주소가 없다")
    params: dict[str, Any] = {"query": spec["query"]}
    if spec.get("region"):
        params["region"] = spec["region"]
        try:
            params = SiteRecipeTools._named_values(recipe, recipe.name, url_key, params)
        except RecipeError as exc:
            raise RoutineRefused(str(exc)) from exc
    # 검색어는 주소용으로 감싼다. 지역 값은 표의 번호(+ 레시피가 정한 이음표)라 그대로 넣는다.
    filled = {"query": urllib.parse.quote(str(params["query"]), safe=""), "region": str(params.get("region") or "")}
    missing = sorted(name for name in set(_PLACEHOLDER.findall(template)) if not filled.get(name))
    if missing:
        raise RoutineRefused(f"주소 틀의 빈칸을 못 채웠다: {', '.join(missing)}")
    url = _PLACEHOLDER.sub(lambda m: filled[m.group(1)], template)
    if not recipe.allows(url):
        raise RoutineRefused(f"레시피 주소가 레시피의 hosts 밖이다: {url}")
    return url, {"url_key": url_key, "region_code": filled["region"]}


# ── 받기 ─────────────────────────────────────────────────────────────────────

def http_fetch(url: str) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.6",
    })
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC) as response:  # noqa: S310 — 레시피 hosts 를 지난 주소만 온다
        raw = response.read(_MAX_BYTES + 1)
        final = response.geturl()
        charset = response.headers.get_content_charset() or "utf-8"
    if len(raw) > _MAX_BYTES:
        raise ValueError(f"응답이 {_MAX_BYTES // (1024 * 1024)}MB 를 넘는다 — 목록 화면이 아니다")
    return raw.decode(charset, errors="replace"), final


# ── HTML 을 작은 나무로 ──────────────────────────────────────────────────────

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None") -> None:
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[Any] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def walk(self):  # noqa: ANN201
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find_all(self, tag: str = "", cls: str = "", id_: str = "") -> list["Node"]:
        return [node for node in self.walk()
                if (not tag or node.tag == tag) and (not cls or cls in node.classes)
                and (not id_ or node.attrs.get("id") == id_)]

    def find(self, tag: str = "", cls: str = "", id_: str = "") -> "Node | None":
        for node in self.walk():
            if (not tag or node.tag == tag) and (not cls or cls in node.classes) and (not id_ or node.attrs.get("id") == id_):
                return node
        return None

    def text(self) -> str:
        parts = [child.text() if isinstance(child, Node) else child for child in self.children]
        return " ".join(" ".join(parts).split())


class _TreeBuilder(HTMLParser):
    """`<script>` · `<style>` 속 글은 버린다 — 그 안의 「태그」를 칸으로 읽지 않는다(표본에 그 함정을 넣었다)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack[-1].tag not in {"script", "style"}:
            self.stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


# ── 사람인 목록 ─────────────────────────────────────────────────────────────

#: 조건 칸 가르기. 사람인 목록은 「근무지 · 경력 · 학력 · 고용형태 (· 연봉)」 순서였다(10-23 부산 10건 실측 · 10건 모두).
#  순서만 믿지 않고 낱말로 가른다 — 칸 하나가 빠지면 순서로는 학력이 경력 자리에 들어간다.
_CONDITION_WORDS = (
    ("career", re.compile(r"신입|경력")),
    ("education", re.compile(r"학력|졸|박사|석사|고교|중학")),
    ("employment_type", re.compile(r"정규직|계약직|인턴|파견|아르바이트|프리랜서|기간제|위촉|병역|교육생|전임|해외취업")),
    ("salary", re.compile(r"만원|연봉|월급|시급|일급|회사내규|면접 후")),
)
_REQUIRED = ("rec_idx", "title", "company", "location")
#: 이 칸이 **모든** 줄에서 비면 모양이 바뀐 것이다(사람인이 칸 이름을 바꿨을 때 조용히 빈칸으로 나가지 않게).
_USUALLY_FILLED = ("career", "education", "employment_type", "deadline")
JOB_FIELDS = ("rec_idx", "title", "company", "location", "career", "education", "employment_type", "salary",
              "deadline", "posted", "other")


def _total_of(root: Node) -> int | None:
    node = root.find(cls="cnt_result")
    if node is None:
        return None
    match = re.search(r"([\d,]+)\s*건", node.text())
    return int(match.group(1).replace(",", "")) if match else None


def _item_of(item: Node) -> dict[str, str]:
    row: dict[str, str] = {key: "" for key in JOB_FIELDS}
    rec_idx = item.attrs.get("value", "").strip()
    title_node = item.find("h2", "job_tit")
    link = title_node.find("a") if title_node else None
    if link is not None:
        row["title"] = (link.attrs.get("title") or link.text()).strip()
        href_idx = re.search(r"rec_idx=(\d+)", link.attrs.get("href", ""))
        if href_idx and rec_idx and href_idx.group(1) != rec_idx:
            rec_idx = ""  # 칸과 링크가 다른 공고를 가리키면 어느 쪽도 믿지 않는다 → 아래에서 깨짐
        elif href_idx and not rec_idx:
            rec_idx = href_idx.group(1)
    row["rec_idx"] = rec_idx if rec_idx.isdigit() else ""
    corp = item.find("strong", "corp_name")
    row["company"] = corp.text() if corp else ""
    condition = item.find("div", "job_condition")
    spans = [child for child in condition.children if isinstance(child, Node) and child.tag == "span"] if condition else []
    others: list[str] = []
    for index, span in enumerate(spans):
        text = span.text()
        if index == 0 and span.find("a") is not None:
            row["location"] = re.sub(r"\s+,", ",", text)  # 근무지는 지역 링크가 든 첫 칸
            continue
        for key, pattern in _CONDITION_WORDS:
            if not row[key] and pattern.search(text):
                row[key] = text
                break
        else:
            others.append(text)
    row["other"] = " · ".join(others)
    date = item.find("span", "date")
    row["deadline"] = date.text() if date else ""
    day = item.find("span", "job_day")
    row["posted"] = day.text() if day else ""
    return row


def parse_saramin_list(html: str, *, region_names: list[str] | None = None) -> dict[str, Any]:
    """사람인 검색 목록 → {status, total_on_site, items, problems, notes}. status: ok · empty · broken."""
    root = parse_html(html)
    problems: list[str] = []
    notes: list[str] = []
    total = _total_of(root)
    container = root.find(id_="recruit_info_list")
    said_empty = root.find(cls="info_no_result") is not None

    if container is None:
        if said_empty:
            # 0건 화면 밑의 「인기 공고」는 우리 검색 결과가 아니다 — 세지 않는다.
            return {"status": "empty", "total_on_site": 0, "items": [], "problems": [],
                    "notes": ["사이트가 「검색결과가 없습니다」라고 했다(밑에 붙은 인기 공고는 세지 않았다)"]}
        return {"status": "broken", "total_on_site": total, "items": [], "notes": [],
                "problems": ["목록 자리(#recruit_info_list)도, 「결과 없음」 칸(.info_no_result)도 없다 — 화면 모양이 바뀌었거나 다른 화면이다"]}

    items = [_item_of(node) for node in container.find_all(cls="item_recruit")]
    if total is None:
        problems.append("「총 N건」 머리말(.cnt_result)을 못 읽었다")
    elif total == 0 and items:
        problems.append(f"머리말은 0건인데 목록에 {len(items)}줄이 있다")
    elif total > 0 and not items:
        problems.append(f"머리말은 {total}건인데 목록 칸(.item_recruit)을 하나도 못 읽었다")
    elif len(items) > total:
        problems.append(f"머리말 {total}건보다 읽은 줄({len(items)})이 많다")
    elif len(items) < total:
        notes.append(f"첫 쪽만 읽었다 — 사이트 총 {total}건 중 {len(items)}건")

    for index, row in enumerate(items, 1):
        empty = [key for key in _REQUIRED if not row[key]]
        if empty:
            problems.append(f"{index}번째 줄에서 {', '.join(empty)} 칸을 못 읽었다")
    if len(items) >= 3:
        for key in _USUALLY_FILLED:
            if not any(row[key] for row in items):
                problems.append(f"{key} 칸을 {len(items)}줄 모두에서 못 읽었다 — 칸 모양이 바뀐 것 같다")

    if region_names and items:
        for row in items:
            row["region_match"] = "yes" if any(name in row["location"] for name in region_names) else "no"
        off = sum(1 for row in items if row["region_match"] == "no")
        where = "·".join(region_names)
        # 10-04 사고 모양: 틀린 지역 번호는 오류 대신 엉뚱한 지역 공고(서초구 20개)를 돌려줬다.
        if off * 2 > len(items):
            problems.append(f"{len(items)}건 중 {off}건이 {where} 공고가 아니다 — 지역이 안 걸린 것 같다")
        elif off:
            notes.append(f"{off}건은 근무지에 {where}이(가) 안 보인다(여러 지역 공고일 수 있다)")

    status = "broken" if problems else ("ok" if items else "empty")
    return {"status": status, "total_on_site": total, "items": items, "problems": problems, "notes": notes}


#: 레시피 이름 → 목록 읽는 법. 다음 걸음(§55-40 ②)에서 이것을 레시피 JSON 의 칸 표로 옮긴다.
PARSERS: dict[str, Callable[..., dict[str, Any]]] = {"saramin": parse_saramin_list}


def _region_short_names(recipe: Any, region_code: str) -> list[str]:
    """번호들 → 그 번호를 가리키는 짧은 이름(「부산」). 근무지 칸 대조에 쓴다."""
    table = (getattr(recipe, "param_values", None) or {}).get("region") or {}
    joiner = urllib.parse.unquote((getattr(recipe, "param_joins", None) or {}).get("region", ","))
    codes = [code for code in urllib.parse.unquote(region_code).split(joiner) if code]
    return sorted({name for name, code in table.items() if code in codes and len(name) <= 2})


# ── 돌리기 ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def run_routine(
    spec: Any,
    out: Path | str | None = None,
    *,
    fetch: Fetch | None = None,
    recipe_dir: Path | None = None,
) -> dict[str, Any]:
    """루틴 한 회차. 늘 결과 dict 를 돌려준다(예외로 새지 않는다). `out` 은 ok · empty 일 때만 쓴다."""
    started = time.time()
    result: dict[str, Any] = {"routine": "", "status": "", "count": 0, "total_on_site": None,
                              "source_url": "", "fetched_at": "", "params": {}, "jobs": [],
                              "problems": [], "notes": [], "out": "", "seconds": 0.0, "model_used": False}
    try:
        clean = normalize_spec(spec)
        recipe = load_recipe(clean["recipe"], recipe_dir)
        url, info = build_url(recipe, clean)
    except RoutineRefused as exc:
        result.update(status="refused", problems=[str(exc)], params=dict(spec) if isinstance(spec, dict) else {})
        return result
    result["routine"] = f"{recipe.name}.{info['url_key']}"
    result["params"] = {**clean, "region_code": info["region_code"]}
    result["source_url"] = url
    try:
        html, final = (fetch or http_fetch)(url)
    except Exception as exc:  # noqa: BLE001 — 받기 실패는 「깨짐」이 아니라 「못 받음」이다(사이트 모양은 모른다)
        result.update(status="failed", problems=[f"받기 실패: {type(exc).__name__}: {str(exc)[:200]}"],
                      fetched_at=_now_iso(), seconds=round(time.time() - started, 2))
        return result
    fetched_at = _now_iso()
    result["fetched_at"] = fetched_at
    if final and final != url:
        result["notes"].append(f"사이트가 다른 주소로 보냈다: {final}")
        if not recipe.allows(final) or urllib.parse.urlparse(final).path != urllib.parse.urlparse(url).path:
            result.update(status="broken", seconds=round(time.time() - started, 2),
                          problems=[f"레시피 주소가 아닌 화면으로 넘어갔다({final}) — 목록을 읽지 않았다"])
            return result

    parsed = PARSERS[recipe.name](html, region_names=_region_short_names(recipe, info["region_code"]) or None)
    job_template = recipe.urls.get("job", "")
    jobs = []
    for row in parsed["items"]:
        job = dict(row)
        job["url"] = job_template.replace("{job_id}", row["rec_idx"]) if job_template and row["rec_idx"] else ""
        job["source_url"] = url
        job["fetched_at"] = fetched_at
        job["evidence"] = " | ".join(part for part in (row["title"], row["company"], row["location"], row["career"],
                                                       row["education"], row["employment_type"], row["deadline"]) if part)[:300]
        jobs.append(job)
    result.update(status=parsed["status"], count=len(jobs), total_on_site=parsed["total_on_site"], jobs=jobs,
                  problems=parsed["problems"], notes=result["notes"] + parsed["notes"],
                  seconds=round(time.time() - started, 2))
    if out and result["status"] in {"ok", "empty"}:
        path = Path(out)
        result["out"] = str(path)
        _write_json(path, result)
    elif out:
        result["notes"].append(f"깨짐이라 {out} 를 덮지 않았다(지난번 결과가 남아 있다)")
    return result


def summary(result: dict[str, Any]) -> dict[str, Any]:
    """예약 목록 · 화면에 남길 작은 줄 — 공고 본문은 빼고 건수 · 상태 · 근거만."""
    return {
        "status": result.get("status", ""),
        "count": int(result.get("count") or 0),
        "total_on_site": result.get("total_on_site"),
        "problems": list(result.get("problems") or [])[:5],
        "notes": list(result.get("notes") or [])[:5],
        "out": result.get("out", ""),
        "source_url": result.get("source_url", ""),
        "fetched_at": result.get("fetched_at", ""),
        "seconds": result.get("seconds", 0.0),
        "model_used": False,
    }


def command_line(spec: dict[str, Any], out: str | Path) -> str:
    """사람이 그대로 붙여 돌릴 수 있는 한 줄. 스토어 판은 실행 별칭(`claude_hooks` 와 같은 길), 개발 판은 지금 파이썬."""
    from . import msix

    if msix.is_packaged():
        from .mcp_connect import msix_alias_path

        prefix = f'"{Path(str(msix_alias_path())).as_posix()}"'
    else:
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
            exe = exe.with_name("python.exe")
        prefix = f'"{exe.as_posix()}"'
    parts = [prefix, "-m alture_jarvis.routine run", f"--recipe {spec['recipe']}", f'--query "{spec["query"]}"']
    if spec.get("region"):
        parts.append(f'--region "{spec["region"]}"')
    parts.append(f'--out "{Path(str(out)).as_posix()}"')
    return " ".join(parts)


# ── 명령 ─────────────────────────────────────────────────────────────────────

USAGE = ("쓰는 법: python -m alture_jarvis.routine run --recipe saramin --query \"연구비 관리\" "
         "[--region 부산] [--out jobs.json] [--recipe-dir 폴더]")
_CLI_OPTIONS = frozenset({"recipe", "query", "region", "out", "recipe-dir"})


def _args(argv: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    key = ""
    for item in argv:
        if item.startswith("--"):
            key = item[2:]
            out[key] = ""
        elif key:
            out[key] = item
            key = ""
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    if not argv or argv[0] != "run":
        print(USAGE)
        return EXIT["refused"]
    opts = _args(argv[1:])
    unknown = sorted(set(opts) - _CLI_OPTIONS)
    if unknown:
        print(json.dumps({"status": "refused", "problems": [
            f"모르는 인자: {', '.join('--' + key for key in unknown)} — 주소는 레시피에서만 나온다. {USAGE}"]}, ensure_ascii=False))
        return EXIT["refused"]
    spec = {key: opts[key] for key in ("recipe", "query", "region") if key in opts}
    result = run_routine(spec, opts.get("out") or None,
                         recipe_dir=Path(opts["recipe-dir"]) if opts.get("recipe-dir") else None)
    # 화면에는 짧게 — 공고 전체는 --out 파일에 있다.
    print(json.dumps({**summary(result), "routine": result.get("routine", ""), "params": result.get("params", {})},
                     ensure_ascii=False, indent=2))
    return EXIT.get(str(result.get("status")), EXIT["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
