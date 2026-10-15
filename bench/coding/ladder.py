"""코딩 난도 사다리 — 작은 모델(4B)의 천장을 재는 과제 여섯 개 (2026-09-21).

## 왜 사다리인가

AURORA 한 과제(n=1)로는 「4B 가 코딩을 하나」를 말할 수 없다. 난도를 한 칸씩 올려 **어디서 꺾이는지**를
본다. 각 과제는 자급자족한다(노트북에는 저장소가 없다) — 씨앗 파일을 만들어 주고, 끝난 작업 폴더를
**코드가 채점한다.** 모델이 「됐다」고 말한 것은 증거가 아니다.

    L1 hello_page        빈 폴더에 단일 페이지 하나(버튼이 글자를 바꾼다)
    L2 aurora            빈 폴더에 카드·확률·클릭 반응하는 페이지 (기준선 과제)
    L3 fix_bug           실패하는 테스트 1개 → 함수 한 줄 고치기
    L4 add_feature       기존 모듈에 함수 추가 + 테스트 추가 (경계값 있음)
    L5 rename_across     세 파일에 걸친 이름 바꾸기 (테스트도 같이)
    L6 two_bug_pipeline  서로 다른 파일의 버그 둘 (증상은 하나)

채점:
    - 결정론(`check_*`). 파일·코드·테스트를 실제로 돌려 본다.
    - **테스트 파일을 몰래 고쳐 통과시키는 것**을 잡는다(`_tests_untouched`) — 고칠 과제에서 테스트를 바꾸면 무효.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

PY = sys.executable

# ── 씨앗 파일 ────────────────────────────────────────────────────────────────

_CALC = '''def average(numbers):
    """숫자 목록의 평균."""
    if not numbers:
        return 0
    return sum(numbers) / len(numbers) + 1
'''

_TEST_CALC = '''from calc import average


def test_average_basic():
    assert average([2, 4, 6]) == 4


def test_average_single():
    assert average([10]) == 10


def test_average_empty():
    assert average([]) == 0
'''

_TEXTUTIL = '''import re


def slugify(text):
    """'Hello World!' -> 'hello-world'"""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-")
'''

_TEST_TEXTUTIL = '''from textutil import slugify


def test_slugify_basic():
    assert slugify("Hello World!") == "hello-world"


def test_slugify_trims():
    assert slugify("  A  b  ") == "a-b"
'''

_USERS_DB = '''USERS = {1: "kim", 2: "lee", 3: "park"}


def get_user(user_id):
    return USERS.get(user_id)
'''

_USERS_SERVICE = '''from db import get_user


def greeting(user_id):
    name = get_user(user_id)
    if name is None:
        return "hello, guest"
    return f"hello, {name}"
'''

_USERS_API = '''from db import get_user
from service import greeting


def handle(user_id):
    exists = get_user(user_id) is not None
    return {"exists": exists, "message": greeting(user_id)}
'''

_TEST_USERS = '''from api import handle
from db import get_user
from service import greeting


def test_db():
    assert get_user(1) == "kim"
    assert get_user(99) is None


def test_service():
    assert greeting(2) == "hello, lee"
    assert greeting(99) == "hello, guest"


def test_api():
    assert handle(3) == {"exists": True, "message": "hello, park"}
    assert handle(0)["exists"] is False
'''

_PAGER = '''def page_count(total_items, page_size):
    """전체 항목 수와 한 페이지 크기로 페이지 수를 구한다."""
    return total_items // page_size
'''

_SLICER = '''def page_items(items, page, page_size):
    """page 는 1부터 시작한다."""
    start = page * page_size
    return items[start:start + page_size]
'''

_TEST_PAGER = '''from pager import page_count
from slicer import page_items


def test_count_exact():
    assert page_count(10, 5) == 2


def test_count_remainder():
    assert page_count(11, 5) == 3


def test_first_page():
    assert page_items(list(range(1, 8)), 1, 3) == [1, 2, 3]


def test_last_page_partial():
    assert page_items(list(range(1, 8)), 3, 3) == [7]
'''


# ── L7 복합: 주문 CSV 리포트 (2026-09-28 헤르메스 대결 T8) ──────────────────
# 버그 넷(따옴표 안 쉼표 · 천 단위 쉼표 · 환불 음수를 버림 · 끝 빈 줄) + 명령줄 기능 추가 + 새 시험 파일 쓰기.
# 숨은 확인은 **다른 CSV**(BOM·CRLF·중간 빈 줄·합계 동점)로 명령줄 출력을 대조한다 — 보이는 시험에만 맞춘 땜질을 잡는다.
_REPORT = '''def load_orders(path):
    """orders.csv 를 읽어 [{"customer": ..., "category": ..., "amount": int}] 로 돌려준다."""
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\\n")
    for line in lines[1:]:
        parts = line.split(",")
        rows.append({"customer": parts[0], "category": parts[1], "amount": int(parts[2])})
    return rows


def total_by_category(orders):
    """카테고리별 금액 합계. 환불(음수)은 합계에서 뺀다."""
    totals = {}
    for order in orders:
        if order["amount"] > 0:
            totals[order["category"]] = totals.get(order["category"], 0) + order["amount"]
    return totals
'''

_ORDERS_CSV = '﻿customer,category,amount\n"Kim, J",book,"1,200"\nLee,toy,700\nPark,book,600\n"Kim, J",book,-300\n\n'

_TEST_REPORT = '''from pathlib import Path

from report import load_orders, total_by_category

DATA = Path(__file__).parent / "orders.csv"


def test_load_handles_quotes_and_thousands():
    rows = load_orders(DATA)
    assert rows[0] == {"customer": "Kim, J", "category": "book", "amount": 1200}
    assert len(rows) == 4


def test_refunds_reduce_totals():
    assert total_by_category(load_orders(DATA)) == {"book": 1500, "toy": 700}
'''

# 숨은 CSV — 합계: ball 3000 · bag·cup·pen 1500(동점 → 이름 순).
_HIDDEN_CSV = (
    '﻿customer,category,amount\r\n"Choi, M",pen,"2,000"\r\n\r\nJung,cup,500\r\nHan,pen,-500\r\n'
    'Oh,bag,1500\r\nYu,cup,"1,000"\r\nSeo,ball,"3,000"\r\n'
)
_HIDDEN_EXPECTED = ["ball: 3000", "bag: 1500", "cup: 1500", "pen: 1500"]


# ── L8 처음 보는 API: 가상 장면 라이브러리 (2026-10-01 베타 테스터 · 3ds Max 레이어 정리 판) ──────────
# 테스터가 3ds Max(`pymxs`) 레이어 정리 스크립트를 9B 에게 맡겼다가 코드가 망가졌다. 같은 모양의 일을 **학습 데이터에
# 없는 가상 API** 로 낸다 — 웹 검색은 소용없고, 함께 준 API.md 를 읽느냐 지어내느냐가 드러난다. 문서를 안 읽으면 걸리는
# 함정: 조명 판정은 kind 가 아니라 category · 없는 레이어는 예외가 아니라 None · 레이어 이름은 대소문자 무시(같은 이름을
# 또 만들면 SceneError) · nodes() 는 사본 · commit() 해야 저장된다. 숨은 확인은 다른 장면(이미 있는 「LIGHTS」·빈 레이어)으로.
_SCENEKIT = """\"\"\"scenekit — 작은 장면 라이브러리. 사용법은 API.md 를 볼 것. 이 파일은 고치지 않는다.\"\"\"


class SceneError(Exception):
    pass


class Node:
    def __init__(self, scene, name, category, kind, layer):
        self._scene, self.name, self.category, self.kind, self._layer = scene, name, category, kind, layer

    def layer(self):
        return self._layer

    def move_to(self, layer):
        if layer is None or layer._deleted:
            raise SceneError("target layer is missing or deleted")
        self._layer._nodes.remove(self)
        layer._nodes.append(self)
        self._layer = layer


class Layer:
    def __init__(self, scene, name):
        self._scene, self.name, self._nodes, self._deleted = scene, name, [], False

    def nodes(self):
        return tuple(self._nodes)


class Scene:
    def __init__(self):
        self._layers = {}
        self._saved = None
        self.new_layer("0")

    def layers(self):
        return list(self._layers.values())

    def get_layer(self, name):
        return self._layers.get(name.lower())

    def new_layer(self, name):
        if name.lower() in self._layers:
            raise SceneError("layer already exists: " + name)
        layer = Layer(self, name)
        self._layers[name.lower()] = layer
        return layer

    def delete_layer(self, layer):
        if layer.name == "0":
            raise SceneError("layer 0 cannot be deleted")
        if layer._nodes:
            raise SceneError("layer is not empty: " + layer.name)
        layer._deleted = True
        del self._layers[layer.name.lower()]

    def add(self, name, category, kind, layer_name="0"):
        layer = self.get_layer(layer_name) or self.new_layer(layer_name)
        node = Node(self, name, category, kind, layer)
        layer._nodes.append(node)
        return node

    def commit(self):
        self._saved = {layer.name: sorted(n.name for n in layer._nodes) for layer in self._layers.values()}

    def saved(self):
        return self._saved
"""

_SCENE_API = """# scenekit API

장면(Scene) 안에 레이어(Layer)가 있고, 레이어 안에 노드(Node)가 있다.

## Scene
- `Scene()` — 빈 장면. 레이어 `"0"` 이 항상 있다.
- `scene.layers()` — 레이어 목록(list).
- `scene.get_layer(name)` — 이름으로 레이어를 찾는다. **대소문자를 구분하지 않는다**(`"lights"` 와 `"LIGHTS"` 는 같은 레이어). **없으면 `None`** 을 돌려준다(예외가 아니다).
- `scene.new_layer(name)` — 새 레이어. 같은 이름(대소문자 무시)이 이미 있으면 `SceneError`.
- `scene.delete_layer(layer)` — 레이어를 지운다. 레이어 `"0"` 이거나 노드가 남아 있으면 `SceneError`.
- `scene.commit()` — 지금 상태를 저장한다. **commit 하지 않은 변경은 저장되지 않는다.**
- `scene.saved()` — 마지막으로 commit 한 상태 `{레이어 이름: [노드 이름, ...]}`. commit 전에는 `None`.

## Layer
- `layer.name` — 이름(만들 때 쓴 대소문자 그대로).
- `layer.nodes()` — 노드들의 **사본**(tuple). 순회하면서 옮겨도 된다.

## Node
- `node.name`
- `node.category` — 큰 분류: `"light"` · `"camera"` · `"geometry"` · `"helper"`.
- `node.kind` — 세부 종류. 조명은 `"omni"` · `"spot"` · `"sun"` 처럼 나뉜다. **조명인지는 category 로 판단한다.**
- `node.layer()` — 지금 속한 레이어.
- `node.move_to(layer)` — 다른 레이어로 옮긴다.
"""

_TIDY = """from scenekit import Scene  # noqa: F401


def organize(scene):
    \"\"\"조명은 Lights 레이어로, 카메라는 Cameras 레이어로 옮기고 비어 있는 레이어를 지운 뒤 저장한다.\"\"\"
    raise NotImplementedError
"""

_TEST_TIDY = """from scenekit import Scene
from tidy import organize


def build():
    scene = Scene()
    scene.add("omni1", "light", "omni", "FX")
    scene.add("rock", "geometry", "mesh", "FX")
    scene.add("camA", "camera", "target", "Cams")
    return scene


def test_lights_and_cameras_move_and_empty_layers_go():
    scene = build()
    organize(scene)
    assert scene.saved() == {"0": [], "FX": ["rock"], "Lights": ["omni1"], "Cameras": ["camA"]}
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


TASKS: dict[str, dict[str, Any]] = {
    "L1_hello_page": {
        "level": 1,
        "seed": {},
        "prompt": (
            "index.html 하나를 만들어줘. 제목은 '별 관측', 버튼 하나(글자는 '관측 시작')와 그 아래 "
            "빈 문단이 있고, 버튼을 누르면 문단 글자가 '관측 중입니다'로 바뀌어야 해. "
            "만든 뒤 local_preview_page로 열어서 browser_open으로 화면을 확인해."
        ),
    },
    "L2_aurora": {
        "level": 2,
        "seed": {},
        "prompt": (
            "AURORA라는 한밤의 오로라 항해 관측소를 index.html 단일 파일로 만들어줘. "
            "깊은 밤 색감과 빛나는 오로라를 사용하고, 서로 다른 3개 관측 목적지 카드와 "
            "각 목적지의 관측 확률을 보여줘. 카드와 버튼은 클릭해 반응해야 해. "
            "완성 뒤 local_preview_page로 열고 browser_open, browser_snapshot, browser_click으로 "
            "화면과 상호작용을 직접 확인해. local_run_project_command로 검증하고 "
            "검증용 임시 파일은 삭제해."
        ),
    },
    "L3_fix_bug": {
        "level": 3,
        "seed": {"calc.py": _CALC, "test_calc.py": _TEST_CALC},
        "protect": ["test_calc.py"],
        "prompt": (
            "test_calc.py 가 실패한다. 원인을 찾아 calc.py 를 고치고, "
            "local_run_project_command 로 python -m pytest -q 를 돌려 통과를 확인해. "
            "테스트 파일은 고치지 마."
        ),
    },
    "L4_add_feature": {
        "level": 4,
        "seed": {"textutil.py": _TEXTUTIL, "test_textutil.py": _TEST_TEXTUTIL},
        "prompt": (
            "textutil.py 에 word_count(text) 함수를 추가해. 공백(스페이스·탭·줄바꿈)이 몇 개 이어져도 "
            "한 칸으로 보고 단어 수를 세고, 빈 문자열이나 공백뿐인 문자열은 0 이야. "
            "test_textutil.py 에도 word_count 테스트를 2개 이상 추가하고, "
            "local_run_project_command 로 python -m pytest -q 를 돌려 전부 통과하는지 확인해."
        ),
    },
    "L5_rename_across": {
        "level": 5,
        "seed": {"db.py": _USERS_DB, "service.py": _USERS_SERVICE, "api.py": _USERS_API,
                 "test_users.py": _TEST_USERS},
        "prompt": (
            "함수 get_user 의 이름을 fetch_user 로 바꿔. db.py, service.py, api.py, test_users.py "
            "네 파일 모두에서 정의와 사용을 빠짐없이 바꾸고, 예전 이름 get_user 는 어디에도 남기지 마. "
            "local_run_project_command 로 python -m pytest -q 를 돌려 전부 통과하는지 확인해."
        ),
    },
    "L6_two_bug_pipeline": {
        "level": 6,
        "seed": {"pager.py": _PAGER, "slicer.py": _SLICER, "test_pager.py": _TEST_PAGER},
        "protect": ["test_pager.py"],
        "prompt": (
            "test_pager.py 의 테스트가 여러 개 실패한다. 원인을 찾아 pager.py 와 slicer.py 를 고쳐서 "
            "전부 통과시켜. 테스트 파일은 고치지 마. "
            "local_run_project_command 로 python -m pytest -q 를 돌려 통과를 확인해."
        ),
    },
    "L7_compound_report": {
        "level": 7,
        "seed": {"report.py": _REPORT, "orders.csv": _ORDERS_CSV, "test_report.py": _TEST_REPORT},
        "protect": ["test_report.py", "orders.csv"],
        # 대결용 중립 문장 — 우리 도구 이름을 넣지 않는다. `{folder}` 는 판마다 채운다.
        "prompt": (
            "{folder} 에서 test_report.py 가 실패한다. report.py 를 고쳐서 통과시켜 — 따옴표로 감싼 칸·천 단위 쉼표·"
            "환불(음수)·빈 줄·BOM 이 섞인 CSV 도 제대로 읽어야 한다. 그리고 명령줄에서 `python report.py <csv 경로>` 로 "
            "실행하면 카테고리별 합계를 합계가 큰 순서로(같으면 카테고리 이름 순) 한 줄에 하나씩 `카테고리: 합계` 형식으로 "
            "출력하게 해. 이 명령줄 기능의 테스트를 새 파일 test_cli.py 에 2개 이상 써. test_report.py 와 orders.csv 는 "
            "고치지 마. pytest 로 전부 통과하는지 확인해."
        ),
    },
    "L8_unfamiliar_api": {
        "level": 8,
        "seed": {"scenekit.py": _SCENEKIT, "API.md": _SCENE_API, "tidy.py": _TIDY, "test_tidy.py": _TEST_TIDY},
        "protect": ["test_tidy.py", "scenekit.py", "API.md"],
        "prompt": (
            "tidy.py 의 organize(scene) 를 완성해. scenekit 라이브러리를 쓰는데 처음 보는 라이브러리라 사용법은 같은 폴더의 "
            "API.md 에 있다. 조명은 'Lights' 레이어로, 카메라는 'Cameras' 레이어로 옮기고(없으면 만들고, 이름만 대소문자가 다른 "
            "레이어가 이미 있으면 그걸 쓴다), 그 뒤 비어 있는 레이어는 지운다('0' 레이어는 남긴다). 마지막에 저장까지 해야 한다. "
            "scenekit.py · API.md · test_tidy.py 는 고치지 마. local_run_project_command 로 python -m pytest -q 를 돌려 통과를 확인해."
        ),
    },
}


def seed(task: str, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in TASKS[task]["seed"].items():
        (root / name).write_text(content, encoding="utf-8")


# ── 채점 ─────────────────────────────────────────────────────────────────────

def _run_pytest(root: Path) -> tuple[bool, str]:
    done = subprocess.run(
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,  # 한글 출력 — cp949 로 읽다 깨졌다(09-28)
    )
    tail = (done.stdout + done.stderr).strip().splitlines()[-3:]
    return done.returncode == 0, " | ".join(tail)


def _find_page(root: Path) -> Path | None:
    """이중 중첩(`<작업폴더>/<작업폴더>/index.html`)도 찾는다 — 4B 가 실제로 그렇게 썼다."""
    direct = root / "index.html"
    if direct.is_file():
        return direct
    found = sorted(root.rglob("index.html"), key=lambda p: len(p.parts))
    return found[0] if found else None


def check_page(task: str, root: Path) -> dict[str, Any]:
    page = _find_page(root)
    if page is None:
        return {"passed": False, "why": "index.html 없음"}
    text = page.read_text(encoding="utf-8", errors="replace")
    nested = page.parent != root
    detail: dict[str, Any] = {"bytes": len(text.encode("utf-8")), "nested_path": nested}
    if task == "L1_hello_page":
        ok = (
            "별 관측" in text and "관측 시작" in text and "관측 중입니다" in text
            and re.search(r"<button", text, re.I) is not None
            and re.search(r"<script|onclick", text, re.I) is not None
        )
        return {"passed": ok, "why": "" if ok else "제목·버튼·문구·스크립트 중 빠진 것이 있다", **detail}
    # L2: 카드 3개 이상 + 확률(%) 표시 + 상호작용 코드
    cards = len(re.findall(r"class=[\"'][^\"']*card", text, re.I))
    percents = len(re.findall(r"\d{1,3}\s*%", text))
    interactive = re.search(r"addEventListener|onclick", text, re.I) is not None
    detail.update({"cards_static": cards, "percents_static": percents})
    # ★ 글자로만 세면 **자바스크립트로 그린 카드**를 못 본다 (2026-10-04 Ornith 1.5 35B 두 판 — 화면에는 카드 셋·확률 셋이
    #   떴는데 원본 글자에는 카드 틀이 하나라 「카드=1」로 떨어졌다). 글자로 모자라면 **실제로 그려서** 센다.
    #   글자로 이미 채운 판은 예전 그대로다 — 앞선 기록과 견줄 수 있게 그리지 않는다.
    if "AURORA" in text and interactive and (cards < 3 or percents < 3):
        rendered = _rendered_counts(page)
        if rendered is not None:
            detail["cards_rendered"], detail["percents_rendered"] = rendered
            cards, percents = max(cards, rendered[0]), max(percents, rendered[1])
    ok = "AURORA" in text and cards >= 3 and percents >= 3 and interactive
    return {"passed": ok, "why": "" if ok else f"AURORA={('AURORA' in text)} 카드={cards} 확률={percents} 상호작용={interactive}",
            "cards": cards, "percents": percents, **detail}


def _rendered_counts(page: Path) -> tuple[int, int] | None:
    """페이지를 머리 없는 크로미움으로 열어 **그려진** 카드 수와 확률(%) 표시 수를 센다. 못 열면 None.

    카드는 **가장 안쪽** 것을 센다 — 카드들을 감싼 상자(`cards`)를 세면 셋이 하나가 된다.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 — 크로미움이 없으면 글자 채점만 한다
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                view = browser.new_page(viewport={"width": 1280, "height": 900})
                view.goto(page.resolve().as_uri(), wait_until="load", timeout=15000)
                view.wait_for_timeout(800)
                cards = int(view.evaluate(
                    "() => Array.from(document.querySelectorAll('[class*=card i]')).filter(el => {"
                    " const r = el.getBoundingClientRect(); return r.width > 20 && r.height > 20;"
                    " }).filter(el => !el.querySelector('[class*=card i]')).length"
                ))
                body = str(view.evaluate("() => document.body ? document.body.innerText : ''"))
                return cards, len(re.findall(r"\d{1,3}\s*%", body))
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        return None


def _tests_untouched(task: str, root: Path) -> str:
    """고칠 과제에서 테스트 파일을 바꿨으면 그 이유를 돌려준다. 멀쩡하면 빈 문자열."""
    for name in TASKS[task].get("protect", []):
        path = root / name
        if not path.is_file():
            return f"{name} 이 사라졌다"
        if _sha(path.read_text(encoding="utf-8")) != _sha(TASKS[task]["seed"][name]):
            return f"{name} 을 고쳤다(테스트를 바꿔 통과시키면 무효)"
    return ""


def check_python(task: str, root: Path) -> dict[str, Any]:
    tampered = _tests_untouched(task, root)
    if tampered:
        return {"passed": False, "why": tampered}
    ok, tail = _run_pytest(root)
    if not ok:
        return {"passed": False, "why": "pytest 실패: " + tail}
    extra = _extra_checks(task, root)
    if extra:
        return {"passed": False, "why": extra}
    return {"passed": True, "why": "", "pytest": tail}


def _extra_checks(task: str, root: Path) -> str:
    """pytest 통과만으로는 모자란 과제의 추가 확인."""
    if task == "L4_add_feature":
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from textutil import word_count, slugify\n"
            "assert word_count('a b\\tc\\nd') == 4\n"
            "assert word_count('  ') == 0 and word_count('') == 0\n"
            "assert word_count('one   two') == 2\n"
            "assert slugify('Hello World!') == 'hello-world'\n"
        ) % str(root)
        done = subprocess.run([PY, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if done.returncode != 0:
            return "word_count 숨은 확인 실패: " + (done.stderr.strip().splitlines() or ["?"])[-1]
        test_text = (root / "test_textutil.py").read_text(encoding="utf-8")
        added = len(re.findall(r"def test_\w*word", test_text)) + len(
            re.findall(r"def test_\w+\(", test_text)) - 2
        if added < 2 and len(re.findall(r"word_count", test_text)) < 3:
            return "word_count 테스트를 2개 이상 추가하지 않았다"
    if task == "L7_compound_report":
        cli = root / "test_cli.py"
        if not cli.is_file():
            return "test_cli.py 가 없다"
        if len(re.findall(r"^\s*def test_\w+\(", cli.read_text(encoding="utf-8"), re.M)) < 2:
            return "test_cli.py 에 시험이 2개 미만"
        hidden = root / "_hidden_orders.csv"
        hidden.write_bytes(_HIDDEN_CSV.encode("utf-8"))
        try:
            done = subprocess.run([PY, "report.py", str(hidden)], cwd=root, capture_output=True,
                                  text=True, encoding="utf-8", timeout=30)
            got = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
            if done.returncode != 0 or got != _HIDDEN_EXPECTED:
                return f"숨은 CSV 명령줄 출력이 다르다: {got[:6]} (기대 {_HIDDEN_EXPECTED})"
            code = (
                "import sys; sys.path.insert(0, %r)\n"
                "from report import load_orders, total_by_category\n"
                "rows = load_orders(%r)\n"
                "assert len(rows) == 6, len(rows)\n"
                "assert total_by_category(rows) == {'pen': 1500, 'cup': 1500, 'bag': 1500, 'ball': 3000}\n"
            ) % (str(root), str(hidden))
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            if done.returncode != 0:
                return "숨은 CSV 읽기 실패: " + ((done.stderr or "").strip().splitlines() or ["?"])[-1]
        finally:
            hidden.unlink(missing_ok=True)
    if task == "L8_unfamiliar_api":
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from scenekit import Scene\n"
            "from tidy import organize\n"
            "s = Scene()\n"
            "s.add('cam1', 'camera', 'free')\n"
            "s.add('box', 'geometry', 'mesh')\n"
            "s.add('sun1', 'light', 'sun', 'LIGHTS')\n"
            "s.add('spot1', 'light', 'spot', 'Rig')\n"
            "s.add('dummy', 'helper', 'point', 'Rig')\n"
            "s.new_layer('Old')\n"
            "s.add('chair', 'geometry', 'mesh', 'Props')\n"
            "organize(s)\n"
            "want = {'0': ['box'], 'LIGHTS': ['spot1', 'sun1'], 'Rig': ['dummy'], 'Props': ['chair'], 'Cameras': ['cam1']}\n"
            "assert s.saved() == want, s.saved()\n"
        ) % str(root)
        done = subprocess.run([PY, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if done.returncode != 0:
            return "숨은 장면 확인 실패: " + ((done.stderr or "").strip().splitlines() or ["?"])[-1][:200]
    if task == "L5_rename_across":
        left = [p.name for p in root.glob("*.py") if "get_user" in p.read_text(encoding="utf-8")]
        if left:
            return f"get_user 가 남았다: {left}"
        if not any("def fetch_user" in p.read_text(encoding="utf-8") for p in root.glob("*.py")):
            return "fetch_user 정의가 없다"
    return ""


def check(task: str, root: Path) -> dict[str, Any]:
    checker: Callable[[str, Path], dict[str, Any]] = (
        check_page if task in {"L1_hello_page", "L2_aurora"} else check_python
    )
    try:
        return checker(task, root)
    except Exception as exc:  # noqa: BLE001 — 채점기가 죽어도 판의 결과를 잃지 않는다
        return {"passed": False, "why": f"채점기 오류 {type(exc).__name__}: {exc}"}


if __name__ == "__main__":  # 채점기 자체 검증: 씨앗은 통과하면 안 되고, 정답은 통과해야 한다
    import shutil
    import tempfile

    fixes = {
        "L3_fix_bug": {"calc.py": _CALC.replace(" + 1", "")},
        "L4_add_feature": {
            "textutil.py": _TEXTUTIL + '\n\ndef word_count(text):\n    return len(text.split())\n',
            "test_textutil.py": _TEST_TEXTUTIL + '\n\ndef test_wc1():\n    from textutil import word_count\n    assert word_count("a  b") == 2\n\n\ndef test_wc2():\n    from textutil import word_count\n    assert word_count("  ") == 0\n',
        },
        "L5_rename_across": {
            name: text.replace("get_user", "fetch_user")
            for name, text in {"db.py": _USERS_DB, "service.py": _USERS_SERVICE,
                               "api.py": _USERS_API, "test_users.py": _TEST_USERS}.items()
        },
        "L6_two_bug_pipeline": {
            "pager.py": _PAGER.replace("return total_items // page_size",
                                       "return -(-total_items // page_size)"),
            "slicer.py": _SLICER.replace("start = page * page_size", "start = (page - 1) * page_size"),
        },
    }
    fixes["L7_compound_report"] = {
        "report.py": '''import csv
import sys


def load_orders(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            if not (rec.get("customer") or "").strip():
                continue
            rows.append({"customer": rec["customer"], "category": rec["category"],
                         "amount": int(rec["amount"].replace(",", ""))})
    return rows


def total_by_category(orders):
    totals = {}
    for order in orders:
        totals[order["category"]] = totals.get(order["category"], 0) + order["amount"]
    return totals


def main(argv):
    totals = total_by_category(load_orders(argv[0]))
    for category, total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{category}: {total}")


if __name__ == "__main__":
    main(sys.argv[1:])
''',
        "test_cli.py": '''import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(csv_text, tmp_path):
    path = tmp_path / "o.csv"
    path.write_text(csv_text, encoding="utf-8")
    return subprocess.run([sys.executable, str(HERE / "report.py"), str(path)],
                          capture_output=True, text=True).stdout.split()


def test_orders_by_total(tmp_path):
    out = run("customer,category,amount\\na,x,5\\nb,y,9\\n", tmp_path)
    assert out == ["y:", "9", "x:", "5"]


def test_ties_by_name(tmp_path):
    out = run("customer,category,amount\\na,b,5\\nb,a,5\\n", tmp_path)
    assert out == ["a:", "5", "b:", "5"]
''',
    }
    fixes["L8_unfamiliar_api"] = {
        "tidy.py": '''def organize(scene):
    dest = {"light": "Lights", "camera": "Cameras"}
    for layer in list(scene.layers()):
        for node in layer.nodes():
            name = dest.get(node.category)
            if name:
                node.move_to(scene.get_layer(name) or scene.new_layer(name))
    for layer in list(scene.layers()):
        if layer.name != "0" and not layer.nodes():
            scene.delete_layer(layer)
    scene.commit()
''',
    }
    bad = 0
    for task in ("L3_fix_bug", "L4_add_feature", "L5_rename_across", "L6_two_bug_pipeline", "L7_compound_report", "L8_unfamiliar_api"):
        seeded = Path(tempfile.mkdtemp())
        seed(task, seeded)
        before = check(task, seeded)["passed"]
        fixed = Path(tempfile.mkdtemp())
        seed(task, fixed)
        for name, content in fixes[task].items():
            (fixed / name).write_text(content, encoding="utf-8")
        after = check(task, fixed)
        # 테스트 파일을 바꿔 통과시키는 꼼수도 잡는지
        cheat = Path(tempfile.mkdtemp())
        seed(task, cheat)
        for name in TASKS[task].get("protect", []):
            (cheat / name).write_text("def test_x():\n    assert True\n", encoding="utf-8")
        cheated = check(task, cheat)["passed"] if TASKS[task].get("protect") else False
        ok = (not before) and after["passed"] and (not cheated)
        bad += 0 if ok else 1
        print(f"{task}: 씨앗통과={before} 정답통과={after['passed']} 꼼수통과={cheated} -> {'OK' if ok else 'FAIL ' + str(after)}")
        for d in (seeded, fixed, cheat):
            shutil.rmtree(d, ignore_errors=True)
    # 페이지 과제: 빈 폴더는 실패
    empty = Path(tempfile.mkdtemp())
    print("L1 빈폴더 통과=", check("L1_hello_page", empty)["passed"], "(False 여야 함)")
    good = Path(tempfile.mkdtemp())
    (good / "index.html").write_text('<h1>별 관측</h1><button onclick="document.getElementById(\'p\').textContent=\'관측 중입니다\'">관측 시작</button><p id="p"></p>', encoding="utf-8")
    print("L1 정답 통과=", check("L1_hello_page", good)["passed"], "(True 여야 함)")
    sys.exit(1 if bad else 0)
