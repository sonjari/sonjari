"""원문에 닻을 내린 코워크 작업 계약의 그림자 컴파일러.

첫 단계에서는 실행을 바꾸지 않는다. 기존 :mod:`plan` 은 그대로 일하고, 이 모듈은
같은 요청을 **절 단위**로 보존해 잡 장부에 남긴다. 다음 단계에서 도구 효과와 증거
원장을 붙일 때도 원문을 다시 추측하지 않게 만드는 호환층이다.

계약의 불변식은 둘이다.

* 모든 clause 는 원문 ``quote`` 와 정확한 ``span`` 을 가진다.
* 모델이 자유롭게 계획을 창작하지 않는다. 지금은 구조 경계와 확인 가능한 표지만
  결정론으로 읽는다. 모르는 절은 버리지 않고 ``unclassified`` 로 남긴다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .brand import SELF_NAME_PATTERN
from .plan import write_prohibition_scope as _write_prohibition_scope
from .quantities import (
    ROLE_ACTION,
    ROLE_CONSTRAINT,
    ROLE_INPUT,
    ROLE_OUTPUT,
    ROLE_RANGE,
    ROLE_UNKNOWN,
    counted_object as _counted_object,
    quantity_role as _quantity_role,
    unit_is_part_of_a_name as _unit_is_part_of_a_name,
)


CONTRACT_VERSION = "task-contract-shadow-v1"


_ENUMERATION = re.compile(r"(?<!\d)(?:\d{1,2}\s*[.)]|[-*•])\s+")
#: 한국어 요청은 마침표 없이 줄로 나열되는 일이 많다. 줄바꿈을 경계로 안 보면
#: 여러 항목이 한 절로 뭉쳐, 수량과 대상의 소유 관계가 처음부터 사라진다.
_SENTENCE_END = re.compile(r"[.!?。]\s+|\n+")

#: 「읽어라」만 조회가 아니다. 실제로 제일 많이 오는 모양은 「상위 5개를 알려줘」다.
#: 이 낱말들이 없어서 과거 187판 중 35판(벤치 프롬프트 두 개)에서 계약이 통째로
#: 침묵했다 — **재는 자가 재는 대상 앞에서 아무것도 못 읽었다.**
_READ = re.compile(
    r"읽|열어\s*읽|본문|원문|살펴|훑|조사|검색|찾아"
    r"|알려\s*(?:줘|주라|주세요|다오)|알아\s*봐|여쭤|물어봐"
    r"|스크랩|긁어|수집|모아\s*줘|뽑아\s*줘|보여\s*줘"
    r"|상위\s*\d|순위\s*\d|목록|리스트"
)
_COMPARE = re.compile(r"비교|대조|차이|축(?:으로|별로)?")
_ANALYZE = re.compile(r"분석|평가|진단|판단|검토")
_CREATE = re.compile(r"만들|작성|생성|옮기|수정|편집|저장|발행|보내|등록|업로드")
_VERIFY = re.compile(r"검증|확인|테스트|재현")
_STRUCTURE = re.compile(r"표|구분|분리|목록|정리|강점|병목|우선순위|P0|P1|P2")
#: ★ 「너」는 음절이라 낱말 안에 숨는다. `너무`·`건너편`·`너머`의 「너」가 걸려
#: 「이 사이트 너무 느려 점검해줘」가 **자기 진단**으로 잡혔다. 이 저장소가
#: 낱말표로 여러 번 겪은 자리라, 뒤에 오는 글자를 보고 사람을 가리키는 「너」만 센다.
_SELF_REFERENCE = re.compile(
    # 새 이름과 옛 이름 모두 — 사용자는 한동안 습관대로 옛 이름으로 부른다(brand.py).
    SELF_NAME_PATTERN
    + r"|너(?![가-힣])|너(?:의|가|를|한테|에게|랑|와|는)(?![가-힣])"
    r"|네\s*(?:몸|상태|시스템)",
    re.I,
)
_HEALTH = re.compile(r"상태\s*(?:점검|진단)|점검|오류|문제|이상|느려|고장|병목")

_LOCAL_SOURCE = re.compile(r"로컬|내\s*(?:컴퓨터|PC|파일)|문서|폴더|드라이브|[A-Za-z]:[\\/]")
_WEB_SOURCE = re.compile(r"공개\s*웹|웹|인터넷|사이트|홈페이지|URL|https?://", re.I)
#: 주소를 그대로 댄 것(`lit.dev`·`porsche.com/korea`). 이것도 웹이다.
#
# ★ 2026-09-18 밤. 「lit.dev 문서에서 … 데코레이터 3개」가 **로컬 자료**로 읽혔다 — 「문서」는 로컬 낱말표에
#   있고 `lit.dev` 는 웹 낱말표에 없었다. 모델은 정답 페이지를 이미 읽어 놓고도 「읽을 로컬 파일을
#   지정해 달라」고 답했다. 주소가 있으면 그 문장의 「문서」는 그 사이트의 문서다.
WEB_DOMAIN = re.compile(
    r"(?<![A-Za-z0-9@])[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*"
    r"\.(?:com|net|org|dev|io|ai|app|kr|jp|me|so|gg|co\.kr|or\.kr|go\.kr)(?![A-Za-z0-9])",
    re.I,
)

_QUANTITY = re.compile(
    r"(?<![A-Za-z0-9])"  # ★ 「P1/P2 개선」이 「2개」가 됐다 — 앞에 글자·숫자가 붙으면 수량이 아니다
    r"(?P<value>\d{1,2}|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?P<unit>개|곳|건|군데|권|명|축|단계|순위|회|번|차례"
    r"|년|개월|주|일|시간|분|초|원|만원|퍼센트|%)"
)
_KOREAN_NUMBER = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}


@dataclass(frozen=True, slots=True)
class ContractQuantity:
    value: int
    unit: str
    quote: str
    span_start: int
    span_end: int
    #: 이 숫자가 무엇을 세는가. 프롬프트 전체의 대표 숫자를 만들지 않는다.
    role: str = ROLE_UNKNOWN
    #: 세는 대상의 **원문**. span 이 없으면 소유권을 인정하지 않는다.
    object_quote: str = ""
    object_span_start: int = -1
    object_span_end: int = -1


@dataclass(frozen=True, slots=True)
class ContractClause:
    id: str
    quote: str
    span_start: int
    span_end: int
    operations: tuple[str, ...] = ()
    source_scope: str = ""
    quantities: tuple[ContractQuantity, ...] = ()
    required_evidence: tuple[str, ...] = ()
    measurable: bool = False


@dataclass(frozen=True, slots=True)
class DeliverableSection:
    clause_id: str
    label: str
    min_items: int = 0


@dataclass(frozen=True, slots=True)
class LegacyBinding:
    requirement_index: int
    requirement_kind: str
    requirement_label: str
    clause_id: str = ""
    #: 후보로 살아남은 절들. 하나로 못 좁혔다고 **아무것도 모르는 것은 아니다** —
    #: 「실행해 통과를 확인해줘」처럼 요구가 정말 두 절에 걸쳐 있을 수 있다.
    #: 하나면 `clause_id` 와 같고, 여럿이면 여기에만 남는다.
    clause_ids: tuple[str, ...] = ()
    #: 왜 못 묶었는지. 빈 값 하나가 「후보가 없다」와 「후보가 여럿이라 포기했다」를
    #: 같이 뜻하면, 이 분모는 다음 사람에게 방향을 못 알려 준다. 둘은 고치는 법이
    #: 정반대다 — 앞은 절을 더 잘게, 뒤는 소유권 규칙을 더 촘촘히.
    #:
    #:     ""                        묶였다
    #:     "no_clause"               절 자체가 없다
    #:     "ambiguous:3 rules=수량"   후보 3개까지 좁혔고 그때 걸린 규칙
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TaskContract:
    version: str
    source_sha256: str
    side_effect_policy: str
    clauses: tuple[ContractClause, ...]
    deliverable_sections: tuple[DeliverableSection, ...] = ()
    dependencies: tuple[tuple[str, str], ...] = ()
    legacy_bindings: tuple[LegacyBinding, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def classified_clause_count(self) -> int:
        return sum(bool(clause.operations) for clause in self.clauses)

    @property
    def measurable_clause_count(self) -> int:
        return sum(clause.measurable for clause in self.clauses)

    def summary(self) -> dict[str, Any]:
        total = len(self.clauses)
        bound = sum(bool(item.clause_id) for item in self.legacy_bindings)
        return {
            "version": self.version,
            "side_effect_policy": self.side_effect_policy,
            "clauses": total,
            "classified_clauses": self.classified_clause_count,
            "measurable_clauses": self.measurable_clause_count,
            "deliverable_sections": len(self.deliverable_sections),
            "legacy_requirements": len(self.legacy_bindings),
            "legacy_requirements_bound": bound,
            # 하나로 못 좁혔지만 **몇 개까지는 좁힌** 것. 아주 모르는 것과 구별한다.
            "legacy_requirements_narrowed": sum(
                1 for item in self.legacy_bindings
                if not item.clause_id and item.clause_ids
            ),
            "legacy_unbound_reasons": sorted(
                {
                    item.reason.split(":")[0].split(" ")[0]
                    for item in self.legacy_bindings
                    if item.reason
                }
            ),
            "classified_ratio": round(self.classified_clause_count / total, 3) if total else 0.0,
            "warnings": list(self.warnings),
        }


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def clause_spans(prompt: str) -> list[tuple[int, int]]:
    """번호 목록과 문장 경계로 원문을 자르되 정확한 offset을 보존한다."""

    text = str(prompt or "")
    if not text.strip():
        return []
    starts = {0}
    # 번호 목록은 긴 복합 요청에서 가장 강한 구조 표지다. 표지 자체를 clause에
    # 포함해 사람이 장부만 보고도 어느 항목인지 알아볼 수 있게 한다.
    for match in _ENUMERATION.finditer(text):
        before = text[match.start() - 1] if match.start() else ""
        if match.start() == 0 or before.isspace() or before in ".!?;:":
            starts.add(match.start())
    # 번호가 없는 자연어 요청도 문장별로 보존한다. 쉼표는 의존 절을 지나치게
    # 잘게 쪼개므로 경계로 쓰지 않는다.
    for match in _SENTENCE_END.finditer(text):
        starts.add(match.end())
    ordered = sorted(starts)
    spans: list[tuple[int, int]] = []
    for index, start in enumerate(ordered):
        end = ordered[index + 1] if index + 1 < len(ordered) else len(text)
        trimmed = _trimmed_span(text, start, end)
        if trimmed:
            spans.append(trimmed)
    return spans


def _quantities(text: str, absolute_start: int) -> tuple[ContractQuantity, ...]:
    found: list[ContractQuantity] = []
    for match in _QUANTITY.finditer(text):
        token = match.group("value")
        value = int(token) if token.isdigit() else _KOREAN_NUMBER.get(token, 0)
        if value <= 0:
            continue
        unit = match.group("unit")
        # ★ 「한번 조사해주라」의 「한번」은 **말버릇**이다(2026-09-29 실사용 — `action_cardinality 1` 로 잡혀 「뉴스 1개」가 됐다).
        #   세는 「한 번」은 뒤에 표지가 붙거나(「한 번 더」·「한 번만」·「한 번씩」·「한 번째」) 앞에서 못 박는다(「정확히 한 번 실행해」).
        #   역검증(09-29, 과거 고유 요청 1,217개 속 263곳): 뺀 것 가운데 진짜 개수는 「정확히 한 번 실행해」 하나였다 — 그래서 앞도 본다.
        if (
            token == "한"
            and unit == "번"
            and not re.match(r"\s*(?:더|만|씩|째)", text[match.end():])
            and not re.search(r"(?:정확히|딱|단|오직)\s*$", text[:match.start()])
        ):
            continue
        # ★ 「11번가」 · 「3번지」의 숫자는 이름의 일부다(2026-10-13 촬영 판 — 가게 이름이 「열한 번」으로 읽혔다).
        if _unit_is_part_of_a_name(unit, text[match.end():]):
            continue
        obj, obj_start, obj_end = _counted_object(text, match.start(), match.end())
        role = _quantity_role(unit, obj, text[match.end() : match.end() + 6])
        found.append(
            ContractQuantity(
                value=value,
                unit=unit,
                quote=match.group(0),
                span_start=absolute_start + match.start(),
                span_end=absolute_start + match.end(),
                role=role,
                object_quote=obj,
                object_span_start=absolute_start + obj_start if obj else -1,
                object_span_end=absolute_start + obj_end if obj else -1,
            )
        )
    return tuple(found)


#: 동사 줄기 **바로 뒤**가 이것이면 이미 한 일이다(「만들었지만」「검토했어」「작성해 줬잖아」).
_PAST_AFTER_STEM = re.compile(r"^(?:었|였|았|했|됐|됬|되었|하였|해\s*줬|어\s*줬|해\s*놨|어\s*놨|해\s*뒀|어\s*뒀)")
#: 줄기 바로 뒤가 띄어쓰기 + 「때·수·적·줄」이면 **꾸미는 말**이다(「컴포넌트를 만들 때 쓰는」「만들 수 있는」).
_MODIFIER_AFTER_STEM = re.compile(r"^\s+(?:때|수|적|줄|데)(?![가-힣])")
#: 같은 어절 안에 이것이 있으면 **남의 말을 옮기거나 부정하는 말**이다
#: (「클로드가 검토해달라고 하게」「문서를 만들어달라는 게 아니라」).
_REPORTED_IN_WORD = re.compile(r"달라고|달라는|달란|하라고|하라는|해\s*달라고")


def _requested(pattern: re.Pattern[str], text: str) -> bool:
    """이 동사가 **온텔릭에게 지금 시키는 말**로 한 번이라도 쓰였는가.

    ★ 2026-09-18 저녁(팀원 계정 · 이어받기 대화). 낱말만 보고 일로 바꿔서 셋이 터졌다.

        「고맙다 … 온텔릭 역시 내가 만들었지만 대박인기능이다」 → 만들기 요청으로 읽고 같은 문서를 또 만듦
        「그 문서로 만들어줘 클로드가 나중에 보고 검토해달라고하게」 → 「검토」를 온텔릭 일로 읽고 웹 검색 2건
        「나는 문서를 만들어달라는게아니라 이 질문에 답변을 해달라는거였어」 → 다시 만들기로 읽힘

    그래서 낱말을 더 늘리지 않고 **그 낱말이 놓인 모양**을 본다 — 이미 한 일(과거)과 남의 말(인용·부정)은
    시킨 일이 아니다. 하나라도 지금 시키는 모양으로 쓰였으면 시킨 것이다.
    """
    for match in pattern.finditer(text):
        tail = text[match.end() : match.end() + 12]
        word_rest = re.split(r"\s", tail, maxsplit=1)[0]
        if _PAST_AFTER_STEM.match(tail) or _MODIFIER_AFTER_STEM.match(tail):
            continue
        if _REPORTED_IN_WORD.search(word_rest):
            continue
        return True
    return False


def _operations(text: str) -> tuple[str, ...]:
    operations: list[str] = []
    if _READ.search(text):
        operations.append("read_body")
    if _COMPARE.search(text):
        operations.append("compare")
    if _requested(_ANALYZE, text):
        operations.append("analyze")
    # 금지절의 동사를 실행 요구로 만들지 않는다. 판 전역 금지든 대상 하나에 대한
    # 금지든 **그 절 안에서는** 「수정」이 할 일이 아니다.
    if _requested(_CREATE, text) and not _write_prohibition_scope(text):
        operations.append("mutate_or_create")
    if _requested(_VERIFY, text):
        operations.append("verify")
    if _STRUCTURE.search(text):
        operations.append("structure_output")
    # 전역 AND가 아니라 **같은 clause 안**에서만 자기 진단 의도를 만든다.
    if _SELF_REFERENCE.search(text) and _HEALTH.search(text):
        operations.append("self_diagnose")
    return tuple(dict.fromkeys(operations))


def _source_scope(text: str) -> str:
    web = bool(_WEB_SOURCE.search(text) or WEB_DOMAIN.search(text))
    local_hits = {match.group(0) for match in _LOCAL_SOURCE.finditer(text)}
    if web and local_hits <= {"문서"}:
        # 주소를 대고 「문서」라고 했으면 그 사이트의 문서다(`WEB_DOMAIN` 주석).
        local_hits = set()
    local = bool(local_hits)
    if local and not web:
        return "local"
    if web and not local:
        return "web"
    if local and web:
        return "mixed"
    return ""


def _required_evidence(
    operations: Iterable[str], source_scope: str
) -> tuple[str, ...]:
    ops = set(operations)
    evidence: list[str] = []
    if "read_body" in ops:
        evidence.append("body_read")
    if "mutate_or_create" in ops:
        evidence.append("artifact_or_mutation")
    if "verify" in ops:
        evidence.append("verification")
    if source_scope == "local" and "body_read" in evidence:
        evidence.append("canonical_path")
    elif source_scope == "web" and "body_read" in evidence:
        evidence.append("canonical_url")
    return tuple(evidence)


def _deliverable_section(clause: ContractClause) -> DeliverableSection | None:
    if not ({"compare", "structure_output", "analyze"} & set(clause.operations)):
        return None
    # 「경력 3년」·「1순위부터」가 섹션의 최소 항목 수가 되면 안 된다. 내놓을
    # 개수만 센다 — 역할이 생기기 전에는 이 자리가 아무 숫자나 집어 갔다.
    minimum = max(
        (
            quantity.value
            for quantity in clause.quantities
            if quantity.role == ROLE_OUTPUT
        ),
        default=0,
    )
    label = re.sub(r"^\s*(?:\d{1,2}\s*[.)]|[-*•])\s*", "", clause.quote).strip()
    return DeliverableSection(clause.id, label[:240], minimum)


def _legacy_bindings(
    clauses: tuple[ContractClause, ...], requirements: Iterable[Any]
) -> tuple[LegacyBinding, ...]:
    """기존 평면 Requirement가 어느 원문 절에서 왔는지 그림자로 연결한다.

    완벽히 맞추는 척하지 않는다. 수량·source_scope처럼 결정론으로 소유권을 알 수
    있을 때만 묶고, 모르면 빈 clause_id로 남긴다. 빈 값이 다음 계측의 분모다.
    """

    bindings: list[LegacyBinding] = []
    for index, requirement in enumerate(requirements):
        kind = str(getattr(requirement, "kind", ""))
        label = str(getattr(requirement, "label", ""))
        target = getattr(requirement, "target", None)
        source_scope = str(getattr(requirement, "source_scope", ""))
        candidates = list(clauses)
        # 어떤 규칙이 실제로 후보를 좁혔는지 남긴다. 안 남기면 「못 묶음 41%」만
        # 보이고 무엇을 고쳐야 하는지는 안 보인다.
        applied: list[str] = []
        if source_scope:
            scoped = [clause for clause in candidates if clause.source_scope == source_scope]
            if scoped:
                candidates = scoped
                applied.append("출처")
        if kind in {"count", "count_action", "footnote"}:
            try:
                wanted = int(target)
            except (TypeError, ValueError):
                wanted = 0
            # 같은 숫자라도 역할이 다르면 그 요구의 주인이 아니다. 「경력 3년」이
            # 「자료 3개 읽기」의 근거로 잡히면 소유권이 아니라 우연이다.
            wanted_roles = {
                "count": {ROLE_INPUT},
                "count_action": {ROLE_ACTION, ROLE_OUTPUT},
                "footnote": {ROLE_OUTPUT},
            }[kind]
            numbered = [
                clause
                for clause in candidates
                if any(
                    quantity.value == wanted and quantity.role in wanted_roles
                    for quantity in clause.quantities
                )
            ]
            if numbered:
                candidates = numbered
                applied.append("수량·역할")
            else:
                loose = [
                    clause
                    for clause in candidates
                    if any(quantity.value == wanted for quantity in clause.quantities)
                ]
                if loose:
                    candidates = loose
                    applied.append("수량")
        # `site` 는 지금까지 **아무 규칙도 안 걸렸다**(실측 9건 전부 rules=없음).
        # 라벨이 「사람인에서 하기」이므로 그 이름이 실제로 적힌 절이 주인이다.
        if kind == "site":
            named = label.split("에서")[0].strip()
            if named:
                on_site = [c for c in candidates if named in c.quote]
                if on_site:
                    candidates = on_site
                    applied.append("사이트이름")
        operation_for_kind = {
            "count": "read_body",
            "observe": "read_body",
            "verify": "verify",
            "artifact": "mutate_or_create",
            "footnote": "mutate_or_create",
        }.get(kind, "")
        if operation_for_kind:
            matching = [
                clause for clause in candidates if operation_for_kind in clause.operations
            ]
            if matching:
                candidates = matching
                applied.append("동작")
        surviving = tuple(clause.id for clause in candidates)
        if len(candidates) == 1:
            chosen, reason = candidates[0].id, ""
        elif not candidates:
            chosen, reason, surviving = "", "no_clause", ()
        else:
            chosen = ""
            reason = "ambiguous:%d rules=%s" % (
                len(candidates),
                ",".join(applied) or "없음",
            )
            # 후보가 너무 많으면 아는 게 없는 것과 같다. 넷 이상은 안 남긴다 —
            # 남기면 「23개 절이 주인일 수 있다」 같은 무의미한 줄이 장부에 쌓인다.
            if len(surviving) > 3:
                surviving = ()
        bindings.append(
            LegacyBinding(
                requirement_index=index,
                requirement_kind=kind,
                requirement_label=label,
                clause_id=chosen,
                clause_ids=surviving,
                reason=reason,
            )
        )
    return tuple(bindings)


def compile_task_contract(
    prompt: str, *, legacy_requirements: Iterable[Any] = ()
) -> TaskContract:
    """실행에 영향 없는 span-grounded 계약을 만든다."""

    text = str(prompt or "")
    clauses: list[ContractClause] = []
    warnings: list[str] = []
    for index, (start, end) in enumerate(clause_spans(text), 1):
        quote = text[start:end]
        operations = _operations(quote)
        source_scope = _source_scope(quote)
        quantities = _quantities(quote, start)
        required_evidence = _required_evidence(operations, source_scope)
        measurable = bool(required_evidence or quantities)
        clauses.append(
            ContractClause(
                id=f"c{index}",
                quote=quote,
                span_start=start,
                span_end=end,
                operations=operations,
                source_scope=source_scope,
                quantities=quantities,
                required_evidence=required_evidence,
                measurable=measurable,
            )
        )
        if not operations:
            warnings.append(f"c{index}:unclassified")

    clause_tuple = tuple(clauses)
    sections = tuple(
        section
        for clause in clause_tuple
        if (section := _deliverable_section(clause)) is not None
    )
    read_ids = [
        clause.id for clause in clause_tuple if "read_body" in clause.operations
    ]
    analysis_ids = [
        clause.id
        for clause in clause_tuple
        if {"compare", "analyze", "structure_output"} & set(clause.operations)
        and clause.id not in read_ids
    ]
    dependencies = tuple((source, target) for source in read_ids for target in analysis_ids)
    bindings = _legacy_bindings(clause_tuple, legacy_requirements)
    for binding in bindings:
        if binding.reason:
            # 이름표에는 개수를 빼고 종류만 남긴다 — 개수를 넣으면 경고가
            # 판마다 달라져 아무도 안 읽는 줄이 된다.
            warnings.append(
                "legacy_unbound:" + binding.reason.split(":")[0].split(" ")[0]
            )
    return TaskContract(
        version=CONTRACT_VERSION,
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        # 정책은 셋이다. `scoped` 는 「테스트 파일은 수정하지 마」처럼 대상 하나만
        # 묶인 판 — 판 전체를 읽기 전용으로 읽으면 손이 통째로 사라진다.
        side_effect_policy={"job": "read_only", "clause": "scoped"}.get(
            _write_prohibition_scope(text), "unspecified"
        ),
        clauses=clause_tuple,
        deliverable_sections=sections,
        dependencies=dependencies,
        legacy_bindings=bindings,
        warnings=tuple(dict.fromkeys(warnings)),
    )
