"""P5 Code 모드의 고정 24과제와 공개 검사.

정답 diff를 모델에게 주지 않는다. 각 과제는 독립 폴더로 물질화되고, 채점기는
답변 문구가 아니라 테스트 종료 코드·변경 경계·읽기 전용 여부를 본다.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# 채점기는 `tests/` 수정과 예상 밖 파일 잔존을 모두 탈락으로 본다. 그 계약을
# 프롬프트가 말하지 않으면, 못 한 게 아니라 못 들은 것을 감점하는 눈금이 된다.
LEAVE_NO_TRACE = "검증용 임시 파일을 만들었으면 끝나기 전에 지워라."


@dataclass(frozen=True)
class RepoCase:
    key: str
    category: str
    prompt: str
    files: dict[str, str]
    expected_changed: tuple[str, ...] = ()
    answer_tokens: tuple[str, ...] = ()
    verify_command: tuple[str, ...] = ("-m", "pytest", "-q")
    #: 파이썬이 아닌 검증. 채워져 있으면 이 명령을 그대로 실행한다
    #: (`cargo test`, `npm test` …). 비어 있으면 예전처럼 sys.executable 이다.
    verify_argv: tuple[str, ...] = ()
    #: 채점 전에 저장소에서 지울 것. Exercism 은 `.meta/` 안에 **정답**을 들고
    #: 있어서, 물질화할 때 빼지 않으면 모델이 그걸 읽고 베낀다.
    strip_paths: tuple[str, ...] = ()


def _recon(index: int, component: str, entry: str, dependency: str) -> RepoCase:
    return RepoCase(
        key=f"recon_{index}_{component}",
        category="recon",
        prompt=(
            "이 저장소는 수정하지 마. 실제 파일을 읽고 "
            f"{component} 컴포넌트의 진입점과 직접 의존 모듈을 근거 파일명과 함께 설명해줘."
        ),
        files={
            "README.md": f"# Sample {component}\n진입점은 문서가 아니라 src 코드를 확인해야 한다.\n",
            f"src/{entry}.py": f"from .{dependency} import VALUE\n\ndef run():\n    return VALUE\n",
            f"src/{dependency}.py": f"VALUE = '{component}-ready'\n",
            "src/unrelated.py": "VALUE = 'decoy'\n",
        },
        answer_tokens=(f"{entry}.py", f"{dependency}.py"),
        verify_command=(),
    )


def _single(
    index: int,
    key: str,
    prompt: str,
    source: str,
    tests: str,
) -> RepoCase:
    module = f"case_{index}_{key}"
    return RepoCase(
        key=f"single_{index}_{key}",
        category="single_patch",
        prompt=(
            prompt
            + " 기존 공개 테스트 파일은 수정하지 말고 그대로 실행해 검증해줘. "
            + LEAVE_NO_TRACE
        ),
        files={
            f"src/{module}.py": source,
            f"tests/test_{module}.py": tests.replace("MODULE", f"src.{module}"),
            "pytest.ini": "[pytest]\npythonpath = .\n",
        },
        expected_changed=(f"src/{module}.py",),
    )


def _multifile(index: int, key: str, field: str, value: str) -> RepoCase:
    package = f"feature_{index}_{key}"
    return RepoCase(
        key=f"multi_{index}_{key}",
        category="multi_file",
        prompt=(
            f"{package}에서 저장된 레코드에 {field} 필드를 추가하고 service 응답에도 "
            "같은 값을 노출해줘. 모델과 서비스 두 파일을 함께 고치고 테스트를 실행해. "
            "테스트 파일은 수정하지 마. " + LEAVE_NO_TRACE
        ),
        files={
            f"src/{package}/model.py": (
                "from dataclasses import dataclass\n\n"
                "@dataclass\nclass Record:\n    name: str\n"
            ),
            f"src/{package}/service.py": (
                "from .model import Record\n\n"
                "def describe(name: str) -> dict[str, str]:\n"
                "    record = Record(name=name)\n"
                "    return {'name': record.name}\n"
            ),
            f"src/{package}/__init__.py": "",
            f"tests/test_{package}.py": (
                f"from src.{package}.model import Record\n"
                f"from src.{package}.service import describe\n\n"
                f"def test_{field}_is_kept_across_model_and_service():\n"
                f"    row = Record(name='alpha', {field}='{value}')\n"
                f"    assert row.{field} == '{value}'\n"
                f"    assert describe('alpha')['{field}'] == '{value}'\n"
            ),
            "pytest.ini": "[pytest]\npythonpath = .\n",
        },
        expected_changed=(f"src/{package}/model.py", f"src/{package}/service.py"),
    )


def _recovery(index: int, key: str, source: str, tests: str, symptom: str) -> RepoCase:
    module = f"recovery_{index}_{key}"
    return RepoCase(
        key=f"recovery_{index}_{key}",
        category="failure_recovery",
        prompt=(
            f"현재 테스트가 {symptom} 때문에 실패한다. 먼저 실패를 재현하고 원인을 고친 뒤 "
            "같은 테스트를 다시 실행해 통과시켜줘. 테스트는 수정하지 마. " + LEAVE_NO_TRACE
        ),
        files={
            f"src/{module}.py": source,
            f"tests/test_{module}.py": tests.replace("MODULE", f"src.{module}"),
            "pytest.ini": "[pytest]\npythonpath = .\n",
        },
        expected_changed=(f"src/{module}.py",),
    )


def _visual(index: int, key: str, prompt: str, html: str, css: str, tests: str) -> RepoCase:
    folder = f"ui_{index}_{key}"
    return RepoCase(
        key=f"visual_{index}_{key}",
        category="visual",
        prompt=(
            prompt
            + " index.html과 styles.css를 고치고 UI 계약 테스트를 실행해줘. "
            + "테스트 파일은 수정하지 마. "
            + LEAVE_NO_TRACE
        ),
        files={
            f"{folder}/index.html": html,
            f"{folder}/styles.css": css,
            f"tests/test_{folder}.py": tests.replace("FOLDER", folder),
            "pytest.ini": "[pytest]\npythonpath = .\n",
        },
        expected_changed=(f"{folder}/index.html", f"{folder}/styles.css"),
    )


CASES: tuple[RepoCase, ...] = (
    _recon(1, "billing", "app", "ledger"),
    _recon(2, "search", "main", "indexer"),
    _recon(3, "notifier", "worker", "mailer"),
    _recon(4, "catalog", "api", "repository"),
    _recon(5, "scheduler", "runner", "queue"),
    _recon(6, "analytics", "cli", "metrics"),
    _single(
        1,
        "safe_divide",
        "safe_divide(a, b)가 b=0이면 None을 반환하도록 고쳐줘.",
        "def safe_divide(a: float, b: float):\n    return a / b\n",
        "from MODULE import safe_divide\n\ndef test_zero_is_none():\n    assert safe_divide(4, 0) is None\n\ndef test_value():\n    assert safe_divide(6, 3) == 2\n",
    ),
    _single(
        2,
        "slugify",
        "slugify가 공백 묶음을 한 하이픈으로 만들고 양끝 하이픈을 제거하게 고쳐줘.",
        "def slugify(value: str) -> str:\n    return value.lower().replace(' ', '-')\n",
        "from MODULE import slugify\n\ndef test_slug():\n    assert slugify('  Hello   Local AI  ') == 'hello-local-ai'\n",
    ),
    _single(
        3,
        "parse_bool",
        "parse_bool이 yes/true/1은 True, no/false/0은 False로 대소문자 무관 처리하게 고쳐줘.",
        "def parse_bool(value: str) -> bool:\n    return value == 'true'\n",
        "import pytest\nfrom MODULE import parse_bool\n\n@pytest.mark.parametrize('raw, expected', [('YES', True), ('0', False), ('False', False)])\ndef test_values(raw, expected):\n    assert parse_bool(raw) is expected\n",
    ),
    _single(
        4,
        "clamp",
        "clamp가 경계 밖 값을 최소/최대로 제한하게 고쳐줘.",
        "def clamp(value: int, low: int, high: int) -> int:\n    return value\n",
        "from MODULE import clamp\n\ndef test_bounds():\n    assert clamp(-3, 0, 9) == 0\n    assert clamp(12, 0, 9) == 9\n    assert clamp(4, 0, 9) == 4\n",
    ),
    _single(
        5,
        "unique_tags",
        "unique_tags가 입력 순서를 보존하며 중복을 제거하게 고쳐줘.",
        # set 순서는 Python hash seed에 따라 우연히 기대 순서와 같아질 수
        # 있었다. 벤치의 초기 실패는 반드시 재현되어야 하므로 틀린 순서를
        # 결정론으로 만든다.
        "def unique_tags(values: list[str]) -> list[str]:\n    return sorted(set(values))\n",
        "from MODULE import unique_tags\n\ndef test_stable():\n    assert unique_tags(['b', 'a', 'b', 'c', 'a']) == ['b', 'a', 'c']\n",
    ),
    _single(
        6,
        "duration",
        "duration_seconds가 분과 초를 합산해 정수 초를 반환하게 고쳐줘.",
        "def duration_seconds(minutes: int, seconds: int) -> int:\n    return minutes + seconds\n",
        "from MODULE import duration_seconds\n\ndef test_duration():\n    assert duration_seconds(2, 5) == 125\n",
    ),
    _multifile(1, "status", "status", "active"),
    _multifile(2, "region", "region", "seoul"),
    _multifile(3, "tier", "tier", "pro"),
    _multifile(4, "owner", "owner", "jarvis"),
    _multifile(5, "locale", "locale", "ko-KR"),
    _multifile(6, "channel", "channel", "code"),
    _recovery(
        1,
        "off_by_one",
        "def inclusive_total(start: int, end: int) -> int:\n    return sum(range(start, end))\n",
        "from MODULE import inclusive_total\n\ndef test_inclusive():\n    assert inclusive_total(1, 3) == 6\n",
        "경계값 누락",
    ),
    _recovery(
        2,
        "casefold",
        "def same_name(left: str, right: str) -> bool:\n    return left == right\n",
        "from MODULE import same_name\n\ndef test_case_insensitive():\n    assert same_name('JARVIS', 'jarvis')\n",
        "대소문자 비교",
    ),
    _recovery(
        3,
        "empty_average",
        "def average(values: list[float]) -> float:\n    return sum(values) / len(values)\n",
        "from MODULE import average\n\ndef test_empty():\n    assert average([]) == 0.0\n",
        "빈 목록 예외",
    ),
    _recovery(
        4,
        "normalize_path",
        "def normalize_path(value: str) -> str:\n    return value\n",
        "from MODULE import normalize_path\n\ndef test_duplicate_separators():\n    assert normalize_path('src\\\\agent\\\\main.py') == 'src/agent/main.py'\n",
        "Windows 경로 정규화",
    ),
    _visual(
        1,
        "split_workspace",
        "데스크톱에서 채팅과 코드 작업공간이 정확히 반반인 2열 레이아웃을 만들고, 모바일에서는 1열로 접어줘.",
        "<main class=\"workspace\"><section class=\"chat\">Chat</section><section class=\"code\">Code</section></main>\n",
        ".workspace { display: block; }\n",
        "from pathlib import Path\n\ndef test_split_contract():\n    css = Path('FOLDER/styles.css').read_text(encoding='utf-8')\n    assert 'grid-template-columns: 1fr 1fr' in css\n    assert '@media' in css and 'grid-template-columns: 1fr' in css\n",
    ),
    _visual(
        2,
        "verification_badge",
        "검증 상태를 success/error 두 종류의 접근 가능한 status 배지로 표시해줘.",
        "<main><span class=\"badge\">검증 대기</span></main>\n",
        ".badge { padding: 4px; }\n",
        "from pathlib import Path\n\ndef test_badge_contract():\n    html = Path('FOLDER/index.html').read_text(encoding='utf-8')\n    css = Path('FOLDER/styles.css').read_text(encoding='utf-8')\n    assert 'role=\"status\"' in html\n    assert 'badge--success' in html and 'badge--error' in html\n    assert '.badge--success' in css and '.badge--error' in css\n",
    ),
)


def materialize(case: RepoCase, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for relative, content in case.files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def judge(case: RepoCase, root: Path, before: dict[str, str], answer: str) -> dict[str, object]:
    after = snapshot(root)
    changed = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    expected = set(case.expected_changed)
    source_or_ui_changes = {
        path for path in changed if not path.startswith("tests/") and path != "pytest.ini"
    }
    boundary_ok = set(changed).issubset(expected) if expected else not changed
    changed_expected = expected.issubset(source_or_ui_changes)
    answer_ok = all(token.lower() in answer.lower() for token in case.answer_tokens)
    command_result: dict[str, object] = {"exit_code": None, "stdout": "", "stderr": ""}
    argv = list(case.verify_argv) if case.verify_argv else (
        [sys.executable, *case.verify_command] if case.verify_command else []
    )
    if argv:
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        command_result = {
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        tests_ok = completed.returncode == 0
    else:
        tests_ok = True
    passed = tests_ok and boundary_ok and changed_expected and answer_ok
    return {
        "passed": passed,
        "tests_ok": tests_ok,
        "boundary_ok": boundary_ok,
        "changed_expected": changed_expected,
        "answer_ok": answer_ok,
        "changed_paths": changed,
        "unexpected_paths": sorted(set(changed) - expected),
        "command": command_result,
    }


assert len(CASES) == 24
