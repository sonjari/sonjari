"""파이썬이 아닌 코드도 함수 · 클래스 단위로 자른다 (tree-sitter · MIT, 2026-11-04).

★ 까닭. 코드 색인(`code_index.py`)은 파이썬만 `ast` 로 함수 · 클래스 덩어리를 만들고, 다른 언어는 **120줄씩
기계적으로** 잘랐다(`_generic_chunks`). 이름도 정규식 `SYMBOL_RE` 하나로만 뽑아서 C# · 자바 메서드
(`public void Update()`), 자바스크립트 화살표 함수(`const load = () =>`), Go 메서드는 **하나도 안 잡혔다.**
유니티(C#) 프로젝트에서 「점프 처리하는 곳 찾아 줘」가 120줄 창 하나를 돌려주던 까닭이다.

여기서는 언어별 문법(tree-sitter)으로 정의를 찾아 `ast` 판과 **같은 모양**의 덩어리를 낸다:
`{kind, symbol, start_line, end_line, signature, doc, text}`. 클래스 안 메서드는 `클래스.메서드` 이름.

부품(tree_sitter · 언어별 문법)이 없으면 `chunks()` · `facts()` 가 None 을 돌려준다 — 부르는 쪽은 예전
120줄 자르기로 그대로 간다. 문법 파일이 깨졌거나 처음 보는 노드여도 예외를 밖으로 내지 않는다.
"""
from __future__ import annotations

import functools
import importlib
import re
from typing import Any

#: 색인에 남기는 자르는 법의 판. 바뀌면 이미 만든 색인의 해당 언어 파일을 다시 자른다(`code_index.refresh`).
CHUNKER_VERSION = "ts-1"

# 언어 이름(`code_index.CODE_EXTENSIONS` 의 값) → (모듈, 문법을 돌려주는 함수 이름들 — 앞에서부터 시도)
_GRAMMARS: dict[str, tuple[str, tuple[str, ...]]] = {
    "javascript": ("tree_sitter_javascript", ("language",)),
    "typescript": ("tree_sitter_typescript", ("language_typescript", "language_tsx")),
    "csharp": ("tree_sitter_c_sharp", ("language",)),
    "java": ("tree_sitter_java", ("language",)),
    "go": ("tree_sitter_go", ("language",)),
    "rust": ("tree_sitter_rust", ("language",)),
    "cpp": ("tree_sitter_cpp", ("language",)),
    # C 는 C++ 문법으로 읽는다 — C 는 거의 그 부분집합이고, 문법 하나를 덜 싣는다.
    "c": ("tree_sitter_cpp", ("language",)),
}
#: 문법으로 자를 수 있는 언어 전부(설치 여부와 상관없이) — 판이 바뀌면 이 언어 파일을 다시 자른다.
GRAMMAR_LANGUAGES = frozenset(_GRAMMARS)

#: 이 안에서 찾은 정의는 `바깥이름.안이름` 이 된다(클래스 · 구조체 · 인터페이스 · impl).
_CONTAINERS = {
    "class_declaration", "class", "abstract_class_declaration", "interface_declaration",
    "struct_declaration", "record_declaration", "record_struct_declaration", "enum_declaration",
    "class_specifier", "struct_specifier", "impl_item", "trait_item",
}
#: 덩어리로 내는 정의(컨테이너 포함).
_DEFINITIONS = _CONTAINERS | {
    "function_declaration", "generator_function_declaration", "method_definition",
    "method_declaration", "constructor_declaration", "destructor_declaration",
    "local_function_statement", "operator_declaration",
    "function_definition", "function_item", "struct_item", "enum_item", "mod_item",
    "type_alias_declaration", "type_spec", "namespace_definition",
}
#: 정의가 아니어도 안으로 들어가 찾는 노드(이름공간 · 내보내기 · 본문).
_DESCEND = {
    "program", "source_file", "translation_unit", "compilation_unit", "export_statement",
    "namespace_declaration", "file_scoped_namespace_declaration", "declaration_list",
    "class_body", "interface_body", "enum_body", "field_declaration_list", "statement_block",
    "type_declaration", "linkage_specification", "template_declaration", "module",
    "internal_module", "ambient_declaration", "lexical_declaration", "variable_declaration",
    "variable_declarator", "expression_statement", "preproc_ifdef", "preproc_if",
}
_KIND = {
    "method_definition": "method", "method_declaration": "method", "constructor_declaration": "method",
    "destructor_declaration": "method", "operator_declaration": "method",
    "function_declaration": "function", "generator_function_declaration": "function",
    "function_definition": "function", "function_item": "function", "local_function_statement": "function",
    "arrow_function": "function", "function_expression": "function", "function": "function",
}
_IMPORT_LINE = re.compile(
    r"^\s*(?:using\s+(?:static\s+)?([A-Za-z_][\w.]*)\s*;|import\s+(?:static\s+)?([A-Za-z_][\w.]*)(?:\.\*)?\s*;|"
    r"#include\s*[<\"]([^>\"]+)[>\"])",
    re.MULTILINE,
)
_MAX_CHUNKS = 400
_MAX_DEPTH = 40


@functools.lru_cache(maxsize=16)
def _parsers(language: str) -> tuple[Any, ...]:
    spec = _GRAMMARS.get(language)
    if spec is None:
        return ()
    try:
        from tree_sitter import Language, Parser

        module = importlib.import_module(spec[0])
        return tuple(Parser(Language(getattr(module, name)())) for name in spec[1] if hasattr(module, name))
    except Exception:  # noqa: BLE001 — 부품이 없거나 판이 안 맞으면 예전 길로
        return ()


def available(language: str) -> bool:
    return bool(_parsers(language))


def supported_languages() -> tuple[str, ...]:
    return tuple(sorted(name for name in _GRAMMARS if available(name)))


def _parse(text: str, language: str) -> Any | None:
    raw = text.encode("utf-8", errors="replace")
    best = None
    for parser in _parsers(language):
        try:
            tree = parser.parse(raw)
        except Exception:  # noqa: BLE001
            continue
        if not tree.root_node.has_error:
            return tree
        best = best or tree  # 오류가 있어도 tree-sitter 는 읽을 수 있는 데까지 읽는다
    return best


def _text(node: Any) -> str:
    try:
        return node.text.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _name_of(node: Any) -> str:
    named = node.child_by_field_name("name")
    if named is not None:
        return _text(named)
    if node.type == "impl_item":  # impl Trait for Type → Type
        target = node.child_by_field_name("type")
        return _text(target) if target is not None else ""
    if node.type == "function_definition":  # C/C++: 선언자 사슬 끝의 이름
        current = node.child_by_field_name("declarator")
        for _ in range(8):
            if current is None:
                break
            if current.type in {"identifier", "field_identifier", "qualified_identifier",
                                "destructor_name", "operator_name"}:
                return _text(current)
            current = current.child_by_field_name("declarator") or (
                current.named_children[0] if current.named_children else None
            )
    return ""


def _descendants(node: Any, limit: int = 200) -> list[Any]:
    out, stack = [], [node]
    while stack and len(out) < limit:
        current = stack.pop(0)
        out.append(current)
        stack.extend(current.named_children)
    return out


def _doc_before(node: Any, lines: list[str]) -> str:
    """정의 바로 위 주석 줄(///, //, /** */, #[doc])을 설명으로 붙인다 — 한글 증상 검색이 여기에 걸린다."""
    row = node.start_point[0] - 1
    picked: list[str] = []
    while row >= 0 and len(picked) < 30:
        line = lines[row].strip()
        if line.startswith(("//", "/*", "*", "#[")) or line.endswith("*/"):
            picked.append(line)
            row -= 1
            continue
        if line.startswith("[") and line.endswith("]"):  # C# 특성([SerializeField]) 은 건너뛴다
            row -= 1
            continue
        break
    return "\n".join(reversed(picked))[:2000]


def chunks(text: str, language: str) -> list[dict[str, Any]] | None:
    """정의 단위 덩어리. 부품이 없으면 None(부르는 쪽이 예전 길로), 정의가 하나도 없으면 []."""
    if not available(language):
        return None
    tree = _parse(text, language)
    if tree is None:
        return None
    lines = text.splitlines()
    out: list[dict[str, Any]] = []

    def emit(node: Any, name: str, kind: str) -> None:
        start = node.start_point[0] + 1
        end = max(start, node.end_point[0] + 1)
        out.append(
            {
                "kind": kind,
                "symbol": name,
                "start_line": start,
                "end_line": end,
                "signature": (lines[start - 1].strip() if start <= len(lines) else "")[:300],
                "doc": _doc_before(node, lines),
                "text": "\n".join(lines[start - 1 : end])[:8000],
            }
        )

    def walk(node: Any, prefix: str, depth: int) -> None:
        if depth > _MAX_DEPTH or len(out) >= _MAX_CHUNKS:
            return
        for child in node.named_children:
            if len(out) >= _MAX_CHUNKS:
                return
            kind = child.type
            if kind == "variable_declarator":
                # const load = () => {…} · const load = function () {…}
                value = child.child_by_field_name("value")
                if value is not None and value.type in {"arrow_function", "function_expression", "function"}:
                    name = _text(child.child_by_field_name("name") or value)
                    if name:
                        emit(child.parent if child.parent is not None else child, f"{prefix}{name}", "function")
                    continue
            if kind == "field_definition" or kind == "public_field_definition":
                value = child.child_by_field_name("value")
                if value is not None and value.type in {"arrow_function", "function_expression"}:
                    name = _text(child.child_by_field_name("property") or child.child_by_field_name("name"))
                    if name:
                        emit(child, f"{prefix}{name}", "method")
                continue
            if kind in _DEFINITIONS:
                name = _name_of(child)
                receiver = child.child_by_field_name("receiver") if kind == "method_declaration" else None
                if name and receiver is not None:  # Go: func (s *Server) Start() → Server.Start
                    owner = next(
                        (_text(n) for n in _descendants(receiver) if n.type == "type_identifier"), ""
                    )
                    name = f"{owner}.{name}" if owner else name
                if kind == "namespace_definition":
                    walk(child, f"{prefix}{name}." if name else prefix, depth + 1)
                    continue
                if name:
                    label = _KIND.get(kind, "class" if kind in _CONTAINERS else kind.split("_")[0])
                    emit(child, f"{prefix}{name}", label)
                if kind in _CONTAINERS:
                    walk(child, f"{prefix}{name}." if name else prefix, depth + 1)
                continue
            if kind in _DESCEND or child.named_child_count and depth < 2 and kind.endswith("_body"):
                walk(child, prefix, depth + 1)

    walk(tree.root_node, "", 0)
    out.sort(key=lambda row: (row["start_line"], -row["end_line"]))
    if not out:
        return []
    # 정의 밖 줄(가져오기 · 맨 위 코드 · 설정 객체)이 많으면 앞머리 한 덩어리를 더 둔다 — 그 줄도 검색에 걸려야 한다.
    first = min(row["start_line"] for row in out)
    if first > 1:
        head = "\n".join(lines[: min(first - 1, 120)])
        if head.strip():
            out.insert(
                0,
                {"kind": "module", "symbol": "", "start_line": 1, "end_line": min(first - 1, 120),
                 "signature": next((line.strip() for line in lines if line.strip()), "")[:300],
                 "doc": "", "text": head[:8000]},
            )
    return out[:_MAX_CHUNKS]


def facts(text: str, language: str) -> tuple[list[dict[str, Any]], list[str]] | None:
    """(심볼 목록, 가져오기 목록) — `code_index._python_facts` 와 같은 모양. 부품이 없으면 None."""
    found = chunks(text, language)
    if found is None:
        return None
    symbols = [
        {"name": row["symbol"].rsplit(".", 1)[-1], "qualified": row["symbol"], "kind": row["kind"], "line": row["start_line"]}
        for row in found
        if row["symbol"]
    ][:500]
    found = {value for match in _IMPORT_LINE.finditer(text) for value in match.groups() if value}
    if language == "go":  # import "fmt" · import ( "a" \n "b" )
        for block in re.findall(r'^\s*import\s*(?:\(([^)]*)\)|("[^"]+"))', text, re.MULTILINE):
            found |= set(re.findall(r'"([^"]+)"', block[0] or block[1]))
    return symbols, sorted(found)[:500]
