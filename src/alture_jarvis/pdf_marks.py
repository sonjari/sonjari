"""PDF 한 쪽을 글자로 읽을 때 **글자가 아닌 것**을 글자로 내보내지 않는다 (2026-11-23 NIPA 수행계획서 판 f38ebeb4).

두 가지 병이 한 판에 같이 나왔다.

1. **기호 글꼴을 글자로 읽음.** 한글 양식의 체크 상자는 윈도우 Marlett 글꼴 글자 여러 개(g f e d c b)를 한자리에 겹쳐
   그린 것이다. pypdf 는 이것을 「gfedcb산 gfedc학 gfedc연」으로 뽑았고, 모델은 「인코딩 오류 · 오타」라고 단정한 뒤
   「일반·학술·연구로 고쳐라」를 지어냈다. 화면은 ☑산 □학 □연 이다(쪽을 그려서 확인).
   같은 병이 이 PC 의 PDF 200개 중 4개에 있었다: Wingdings3 「X」(화면 ▶) · Wingdings 「v」(화면 ❖) ·
   Wingdings 「/circle4」(화면 •). 기호 글꼴의 글자는 **글자가 아니다** — 아는 것은 그 모양으로, 모르는 것은 「⟦기호⟧」로 바꾼다.
   모르는 것을 짐작해 바꾸지 않는다(틀린 ☑ 은 빈 상자보다 나쁘다). 표는 화면으로 확인한 것만 싣는다.

2. **그림을 못 보고 「없다」고 함.** 직인 · 서명 도장은 그림(Image XObject)으로 「(직인)」 · 「(인/서명)」 글자 위에 찍혀
   있었다. 글자 읽기에는 아무 흔적이 없으니 모델은 「서명/인감 미기재 · 날인 필요」라고 썼다. 못 본 것과 없는 것은
   다른 말이다 — 쪽마다 그림이 어디(어느 글자 위 · 근처)에 몇 개 있는지 적어 「⟦그림 …⟧」 줄로 붙인다.
   그 줄은 답 검사(`picture_claims`)가 다시 읽어, 그 자리를 「없다」고 한 답에 경고를 붙인다.

여기는 pypdf 만 쓴다(새 부품 없음). 그림 **속**은 여기서 읽지 않는다 — 읽지 않았다는 사실만 적는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 그림 표시 줄의 머리. 답 검사가 이 머리로 줄을 찾는다(`picture_claims.picture_anchors`).
PICTURE_HEAD = "⟦그림"
#: 바꿀 표를 모르는 기호 글자 자리.
UNKNOWN_SYMBOL = "⟦기호⟧"

#: 글자가 아니라 기호를 그리는 글꼴(이름을 소문자로 견준다). Symbol 글꼴은 그리스 글자라 넣지 않는다.
_SYMBOL_FONT_WORDS = ("marlett", "wingding", "webding", "dingbat")

#: Marlett 체크 상자를 이루는 글자 — g(바탕) · c d e f(테두리 네 겹) · b(체크 표시) · a(메뉴 체크 표시).
#: 화면 확인: NIPA 수행계획서 1쪽 「gfedcb」 = ☑ · 「gfedc」 = □ (pypdfium2 로 쪽을 그려 봄, 2026-11-23).
_MARLETT_BOX = frozenset("abcdefg")
_MARLETT_CHECK = frozenset("ab")

#: 다른 기호 글꼴에서 **화면으로 확인한** 글자만. (글꼴 이름 줄기, 뽑힌 글자) → 화면 모양.
#: 확인한 파일(이 PC 2026-11-23): ILO WP96 보고서 Wingdings3 「X」 · 청년창업 입교자 계획서 Wingdings 「v」 ·
#: 행정학회 보고서 Wingdings 「/circle4」.
_KNOWN_SYMBOLS: dict[tuple[str, str], str] = {
    ("wingdings3", "X"): "▶",
    ("wingdings", "v"): "❖",
    ("wingdings", "/circle4"): "•",
}

#: 이보다 작은 그림(가로나 세로, pt)은 선 · 점이라 세지 않는다.
_PICTURE_MIN_PT = 6.0
#: 그림 하나에 이름표로 붙일 글자 조각 수 · 한 쪽에 적을 그림 수.
_ANCHORS_PER_PICTURE = 2
_PICTURES_PER_PAGE = 8


def _font_stem(font: Any) -> str:
    """글꼴 사전 → 「marlett」 · 「wingdings3」 처럼 줄인 이름. 부분 글꼴 앞머리(ABCDEF+)와 -Regular 를 뗀다."""
    try:
        name = str(font.get("/BaseFont", "")) if font is not None else ""
    except Exception:  # noqa: BLE001 — 글꼴 사전이 깨졌어도 읽기를 멈추지 않는다
        name = ""
    name = name.lstrip("/").split("+", 1)[-1].lower()
    name = re.sub(r"[-,]?(regular|normal)$", "", name)
    return re.sub(r"[\s_-]+", "", name)


def _is_symbol_font(stem: str) -> bool:
    return any(word in stem for word in _SYMBOL_FONT_WORDS)


def _already_symbol(text: str) -> bool:
    """글꼴이 제대로 된 유니코드를 줬으면(✔ ■ ▶ 같은 기호 영역 글자) 건드리지 않는다."""
    stripped = text.strip()
    return bool(stripped) and all(ord(char) >= 0x2000 for char in stripped)


def _mul(a: list[float], b: list[float]) -> list[float]:
    return [
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5],
    ]


@dataclass(slots=True)
class _Cluster:
    """한자리에 겹쳐 그린 기호 글자 묶음(체크 상자 하나 · 글머리 하나)."""

    stem: str
    raw: str
    x: float
    y: float
    anchor: str  # 이 묶음 바로 앞까지 나온 글자의 끝 몇 자(공백 뺌) — 결과 글에서 자리를 찾을 때 쓴다

    def shape(self) -> str:
        letters = self.raw.strip()
        if self.stem.startswith("marlett"):
            chars = set(letters)
            if chars and chars <= _MARLETT_BOX and len(chars) >= 3:
                return "☑" if chars & _MARLETT_CHECK else "□"
            return UNKNOWN_SYMBOL
        return _KNOWN_SYMBOLS.get((self.stem, letters), UNKNOWN_SYMBOL)


@dataclass(slots=True)
class PageMarks:
    text: str
    symbols_replaced: int = 0
    symbols_unplaced: int = 0
    pictures: list[str] = field(default_factory=list)
    picture_note: str = ""


def _tail(text: str, size: int = 4) -> str:
    return re.sub(r"\s+", "", text)[-size:]


def _place_clusters(text: str, clusters: list[_Cluster]) -> tuple[str, int, int]:
    """결과 글에서 기호 묶음을 **순서대로** 찾아 바꾼다. (새 글, 바꾼 수, 못 찾은 수).

    pypdf 의 결과 글은 글자 조각을 이은 것과 늘 같지는 않다(이 PC PDF 534쪽 중 63쪽이 달랐다 — 조각 일부를 결과에서 뺌).
    그래서 조각을 다시 잇지 않고, 앞에서부터 커서를 옮기며 찾는다. 같은 글자(「v」)가 보통 글에도 있을 수 있으니
    **바로 앞 글자가 맞는 자리**를 먼저 고른다.
    """
    pieces: list[str] = []
    cursor = 0
    replaced = unplaced = 0
    for cluster in clusters:
        key = cluster.raw.strip() or cluster.raw
        if not key:
            continue
        chosen = -1
        first = text.find(key, cursor)
        probe = first
        while probe >= 0 and cluster.anchor:
            if _tail(text[:probe]).endswith(cluster.anchor):
                chosen = probe
                break
            probe = text.find(key, probe + 1)
        if chosen < 0:
            chosen = first
        if chosen < 0:
            unplaced += 1
            continue
        pieces.append(text[cursor:chosen])
        pieces.append(cluster.shape())
        cursor = chosen + len(key)
        replaced += 1
    pieces.append(text[cursor:])
    return "".join(pieces), replaced, unplaced


def _words(text: str, x: float, em: float) -> list[tuple[float, float, str]]:
    """글자 조각 하나 → 낱말마다 (왼쪽 x, 오른쪽 x, 낱말). 글자 폭은 어림한다(한중일 1em · 그 밖 0.55em).

    한 줄이 조각 **하나**로 오는 PDF 가 흔하다(「Company: … (Seal)   Head: … (Sign)」). 조각의 시작점만 보면 그 줄 가운데
    찍힌 도장을 못 맞춘다 — 낱말 자리를 어림해 그림 밑의 낱말을 찾는다. 어림이라 이름표는 「어느 낱말 근처」 정도의 뜻이다."""
    words: list[tuple[float, float, str]] = []
    cursor = x
    start = None
    current = ""
    for char in text:
        width = em * (1.0 if ord(char) >= 0x2E80 else 0.55)
        if char.isspace():
            if current:
                words.append((start if start is not None else cursor, cursor, current))
            current, start = "", None
        else:
            if not current:
                start = cursor
            current += char
        cursor += width
    if current:
        words.append((start if start is not None else cursor, cursor, current))
    return words


def _picture_label(picture: tuple[float, float, float, float, int],
                   chunks: list[tuple[float, float, float, str, int]], page_area: float) -> str:
    """그림 하나의 자리 이름. 겹친 글자가 그림보다 **먼저** 그려졌으면 그림이 그 글자 위에 찍힌 것(도장 · 서명)이고,
    나중에 그려졌으면 그림은 바탕이다(글상자 배경 · 로고 판) — 이 PC PDF 1,216쪽 역검증에서 바탕 그림이 「글자 위」로 불렸다."""
    x0, y0, x1, y1, order = picture
    if page_area and (x1 - x0) * (y1 - y0) >= 0.8 * page_area:
        return "쪽 전체를 덮는 그림(스캔 · 배경일 수 있음)"
    over: list[str] = []
    under: list[str] = []
    for left, right, y, text, seq in sorted(chunks):
        if left <= x1 + 2 and right >= x0 - 2 and y0 - 3 <= y <= y1 + 3:
            bucket = over if seq < order else under
            if text not in bucket:
                bucket.append(text)
    if over:
        return " · ".join(f"「{name}」" for name in over[:_ANCHORS_PER_PICTURE]) + " 글자 위"
    if under:
        return "글자 밑 바탕"
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    near = sorted(((min(abs(left - cx), abs(right - cx)) if not left <= cx <= right else 0.0) ** 2 + (y - cy) ** 2, text)
                  for left, right, y, text, _ in chunks)
    if near and near[0][0] <= 60.0 ** 2:
        return f"「{near[0][1]}」 근처"
    return "글자와 떨어진 자리"


def read_page(page: Any) -> PageMarks:
    """pypdf 쪽 하나 → 기호를 바꾼 글 + 그림 표시 줄."""
    resources = page.get("/Resources") or {}
    try:
        xobjects = resources.get("/XObject") or {}
    except Exception:  # noqa: BLE001
        xobjects = {}

    clusters: list[_Cluster] = []
    chunks: list[tuple[float, float, float, str, int]] = []  # (왼쪽 x, 오른쪽 x, y, 낱말, 그린 순서) — 그림 이름표 재료
    boxes: list[tuple[float, float, float, float, int]] = []  # (x0, y0, x1, y1, 그린 순서)
    order = [0]
    seen: list[str] = []  # 지금까지 나온 글자 조각(앞 글자 맞추기용)
    current: list[_Cluster | None] = [None]

    def close() -> None:
        if current[0] is not None:
            clusters.append(current[0])
            current[0] = None

    def on_text(text: str, cm: Any, tm: Any, font: Any, size: Any) -> None:
        if not text:
            return
        order[0] += 1
        try:
            matrix = _mul([float(v) for v in tm], [float(v) for v in cm])
            x, y = matrix[4], matrix[5]
            em = abs(float(size or 0)) * (matrix[0] ** 2 + matrix[1] ** 2) ** 0.5
        except Exception:  # noqa: BLE001
            x = y = em = 0.0
        stem = _font_stem(font)
        if _is_symbol_font(stem) and text.strip() and not _already_symbol(text):
            open_one = current[0]
            # 한 상자의 겹 글자는 같은 자리(±1pt)에 그려진다. 자리가 바뀌면 새 상자다.
            if open_one is not None and open_one.stem == stem and abs(open_one.x - x) <= 1.0 and abs(open_one.y - y) <= 1.0:
                open_one.raw += text
            else:
                close()
                current[0] = _Cluster(stem=stem, raw=text, x=x, y=y, anchor=_tail("".join(seen[-40:])))
            seen.append(text)
            return
        if text.strip():
            close()
            for left, right, word in _words(text, x, em or 10.0):
                if re.search(r"\w", word):
                    chunks.append((left, right, y, word[:16], order[0]))
        seen.append(text)

    def on_operator(operator: bytes, arguments: Any, cm: Any, tm: Any) -> None:
        del tm
        is_image = False
        if operator == b"Do" and arguments:
            try:
                target = xobjects.get(arguments[0])
                target = target.get_object() if target is not None else None
                is_image = target is not None and target.get("/Subtype") == "/Image"
            except Exception:  # noqa: BLE001
                is_image = False
        elif operator == b"INLINE IMAGE":
            is_image = True
        if not is_image:
            return
        order[0] += 1
        try:
            a, b, c, d, e, f = (float(v) for v in cm)
        except Exception:  # noqa: BLE001
            return
        xs = (e, e + a, e + c, e + a + c)
        ys = (f, f + b, f + d, f + b + d)
        box = (min(xs), min(ys), max(xs), max(ys), order[0])
        if box[2] - box[0] < _PICTURE_MIN_PT or box[3] - box[1] < _PICTURE_MIN_PT:
            return
        boxes.append(box)

    text = page.extract_text(visitor_text=on_text, visitor_operand_before=on_operator) or ""
    close()
    text, replaced, unplaced = _place_clusters(text, clusters)
    marks = PageMarks(text=text, symbols_replaced=replaced, symbols_unplaced=unplaced)

    try:
        media = page.mediabox
        page_area = float(media.width) * float(media.height)
    except Exception:  # noqa: BLE001
        page_area = 0.0
    labels = [_picture_label(box, chunks, page_area) for box in boxes[:_PICTURES_PER_PAGE]]
    marks.pictures = labels
    if labels:
        more = f" 외 {len(boxes) - len(labels)}개" if len(boxes) > len(labels) else ""
        marks.picture_note = (
            f"{PICTURE_HEAD} {len(boxes)}개 · 그림 속은 안 읽음⟧ "
            + " · ".join(f"{index}) {label}" for index, label in enumerate(labels, 1))
            + more
        )
    return marks
