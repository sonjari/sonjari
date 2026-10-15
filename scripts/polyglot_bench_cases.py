"""공개 골든셋(Exercism / aider polyglot)을 **우리 하네스에 묶는다.**

## 왜 남의 하네스를 안 쓰는가

남의 스캐폴드(SWE-agent·OpenHands)를 돌리면 그 스캐폴드를 재게 된다. 우리가
알고 싶은 것은 **우리 자비스**가 얼마나 하느냐다. 그래서 과제 데이터만 가져와
우리 채점기(테스트 종료 코드 · 변경 경계 · 읽기 전용 여부)로 잰다.

## 정답이 저장소 안에 있다

Exercism 은 `.meta/example.py` 에 **정답 구현**을 들고 있다. 물질화할 때 빼지
않으면 모델이 그걸 읽고 베낀다 — 그러면 100% 가 나오고 아무것도 못 잰다.
`.meta/` 와 `.docs/` 중 힌트는 통째로 제외하고, 지시문만 남긴다.

## 자체 검증 관문

`.meta` 의 정답을 넣으면 통과하고 스텁 그대로면 실패해야 한다. 이 둘 중 하나라도
어긋나면 그 과제는 눈금이 아니다 — 모델을 태우기 전에 걸러낸다.

    python scripts/polyglot_bench_cases.py --validate
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from code_repo_bench_cases import RepoCase  # noqa: E402

POLYGLOT_ROOT = ROOT / "benchmarks" / "external" / "polyglot-benchmark"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


#: 이 PC 에서 실제로 돌릴 수 있는 언어만. go·java·c++ 툴체인이 없다.
#: 없는 손으로 시키고 실패율에 넣으면 제품이 아니라 눈금을 재게 된다.
LANGUAGES: dict[str, dict[str, object]] = {
    "python": {
        "solution_glob": "*.py",
        "test_suffix": "_test.py",
        "reference": ".meta/example.py",
        "argv": [sys.executable, "-m", "pytest", "-q"],
    },
    "rust": {
        "solution_glob": "src/lib.rs",
        "test_suffix": ".rs",
        "reference": ".meta/example.rs",
        "argv": ["cargo", "test", "--quiet"],
    },
}

#: 물질화에서 통째로 뺄 것. 정답과 힌트가 여기 산다.
EXCLUDED_DIRS = (".meta", ".docs")
EXCLUDED_NAMES = {".npmrc", ".eslintrc", "LICENSE"}


def _relative_files(exercise: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(exercise.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(exercise)
        parts = relative.parts
        if parts[0] in EXCLUDED_DIRS or path.name in EXCLUDED_NAMES:
            continue
        try:
            files[relative.as_posix()] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return files


def _instructions(exercise: Path) -> str:
    parts: list[str] = []
    for name in ("instructions.md", "instructions.append.md"):
        candidate = exercise / ".docs" / name
        if candidate.is_file():
            parts.append(candidate.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(parts).strip()


def _solution_path(exercise: Path, language: str, files: dict[str, str]) -> str:
    spec = LANGUAGES[language]
    if language == "rust":
        return "src/lib.rs" if "src/lib.rs" in files else ""
    suffix = str(spec["test_suffix"])
    candidates = [
        name
        for name in files
        if name.endswith(".py") and not name.endswith(suffix) and "/" not in name
    ]
    return candidates[0] if len(candidates) == 1 else (candidates[0] if candidates else "")


def load_cases(
    languages: tuple[str, ...] = ("python",), root: Path | None = None
) -> tuple[RepoCase, ...]:
    base = root or POLYGLOT_ROOT
    cases: list[RepoCase] = []
    for language in languages:
        if language not in LANGUAGES:
            raise SystemExit(f"모르는 언어: {language}")
        practice = base / language / "exercises" / "practice"
        if not practice.is_dir():
            continue
        for exercise in sorted(practice.iterdir()):
            if not exercise.is_dir():
                continue
            files = _relative_files(exercise)
            solution = _solution_path(exercise, language, files)
            if not solution or not files:
                continue
            instructions = _instructions(exercise)
            if not instructions:
                continue
            files["INSTRUCTIONS.md"] = instructions
            cases.append(
                RepoCase(
                    key=f"polyglot_{language}_{exercise.name.replace('-', '_')}",
                    category=f"polyglot_{language}",
                    prompt=(
                        f"INSTRUCTIONS.md 를 읽고 {solution} 를 구현해줘. "
                        "테스트 파일은 수정하지 마. 테스트를 실행해 전부 통과시켜줘. "
                        "검증용 임시 파일을 만들었으면 끝나기 전에 지워라."
                    ),
                    files=files,
                    expected_changed=(solution,),
                    verify_command=(),
                    verify_argv=tuple(str(item) for item in LANGUAGES[language]["argv"]),
                )
            )
    return tuple(cases)


def validate(languages: tuple[str, ...]) -> int:
    """스텁은 실패하고 정답은 통과하는가. 아니면 그 과제는 눈금이 아니다."""
    base = POLYGLOT_ROOT
    broken: list[str] = []
    checked = 0
    for case in load_cases(languages):
        language = case.category.split("_", 1)[1]
        spec = LANGUAGES[language]
        exercise_name = case.key.split(f"polyglot_{language}_", 1)[1].replace("_", "-")
        exercise = base / language / "exercises" / "practice" / exercise_name
        reference = exercise / str(spec["reference"])
        if not reference.is_file():
            broken.append(f"{case.key}: 정답 파일 없음")
            continue
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw) / "case"
            work.mkdir()
            for relative, content in case.files.items():
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            argv = list(case.verify_argv)
            stub = subprocess.run(
                argv, cwd=work, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600, check=False,
            )
            if stub.returncode == 0:
                broken.append(f"{case.key}: 스텁인데 테스트가 통과한다")
                continue
            shutil.copyfile(reference, work / case.expected_changed[0])
            fixed = subprocess.run(
                argv, cwd=work, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600, check=False,
            )
            if fixed.returncode != 0:
                broken.append(f"{case.key}: 정답을 넣어도 실패한다")
                continue
        checked += 1
    print(f"검증한 과제 {checked}건 · 눈금이 아닌 것 {len(broken)}건")
    for line in broken[:20]:
        print("  " + line)
    return 0 if not broken else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", default="python")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    languages = tuple(item.strip() for item in args.languages.split(",") if item.strip())

    if args.validate:
        return validate(languages)
    cases = load_cases(languages)
    print(f"불러온 과제 {len(cases)}건 · 언어 {languages}")
    if args.list:
        for case in cases[:200]:
            print(f"  {case.key:42s} 고칠 파일 {case.expected_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
