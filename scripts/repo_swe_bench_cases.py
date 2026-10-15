"""우리 저장소의 git 역사로 **SWE-bench 방식** 과제를 만든다.

## 왜 이걸 만드나

24과제는 고칠 파일이 사실상 지목된 판만 잰다. 실제 일감의 대부분은 **자리를
먼저 찾는 것**이고, 그 능력은 한 번도 안 쟀다. 그리고 목적이 「쿼터가 끊기면
자비스가 우리 것을 이어받는다」라면, 재야 할 것은 남의 저장소가 아니라
**우리 저장소**다.

## SWE-bench 와 같은 구성

    부모 커밋의 코드          (버그가 있는 상태)
  + 고친 커밋의 테스트        (실패하는 테스트)
  -> "이 테스트가 실패한다. 원인을 찾아 고쳐라"   <- 소스 파일은 안 알려준다

채점도 같다:

    FAIL_TO_PASS   그 테스트가 통과하는가
    PASS_TO_PASS   나머지가 안 깨졌는가          <- 인수인계를 안전하게 만드는 조건
    변경 경계      예상한 소스 파일만 고쳤는가

Docker 가 필요 없다 — 우리 환경이 이미 그 저장소다.

## 자체 검증 관문

부모 코드 + 새 테스트에서 **반드시 실패**해야 하고, 정답 소스를 넣으면
**반드시 통과**해야 한다. 둘 중 하나라도 어긋나면 그 커밋은 눈금이 아니다.
모델을 태우기 전에 걸러낸다.

    python scripts/repo_swe_bench_cases.py --discover 60
    python scripts/repo_swe_bench_cases.py --validate --limit 8
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

JARVIS = Path(__file__).resolve().parents[1]
#: 모노레포 뿌리 — 과제는 모노레포 커밋에서 뽑는다. 공개판은 드라이브 바로 아래라 parents[1] 이 없다(09-29 IndexError):
#: import 는 살리고(시험이 snapshot·judge 를 쓴다), 커밋을 뽑을 때 git 이 없다고 알린다.
REPO = JARVIS.parents[1] if len(JARVIS.parents) > 1 else JARVIS
PREFIX = "tools/alture-jarvis/"
SPEC_PATH = JARVIS / "benchmarks" / "repo_swe_cases.json"
VENV_PYTHON = Path("C:/RoboMetaFit/tools/alture-jarvis/.venv/Scripts/python.exe")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class RepoSweSpec:
    commit: str
    parent: str
    subject: str
    source_files: tuple[str, ...]
    test_files: tuple[str, ...]
    failure_head: str = ""
    validated: bool = False
    notes: str = field(default="")


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        joined = " ".join(args)
        raise RuntimeError("git " + joined + " 실패: " + result.stderr[:200])
    return result.stdout


def discover(limit: int = 60, scan: int = 400) -> list[RepoSweSpec]:
    """소스 1~3개 + 테스트를 함께 고친 커밋. 「버그를 고치고 증명한」 모양이다."""
    log = _git("log", "--format=%H", "-" + str(scan), "--", PREFIX).split()
    specs: list[RepoSweSpec] = []
    for commit in log:
        shown = _git("show", "--name-only", "--format=", commit, "--", PREFIX)
        files = [line.strip() for line in shown.splitlines() if line.strip()]
        sources = tuple(
            f
            for f in files
            if f.startswith(PREFIX + "src/alture_jarvis/") and f.endswith(".py")
        )
        tests = tuple(
            f for f in files if f.startswith(PREFIX + "tests/") and f.endswith(".py")
        )
        if not (1 <= len(sources) <= 3) or not tests or len(tests) > 2:
            continue
        parents = _git("rev-parse", commit + "^", check=False).split()
        if not parents:
            continue
        subject = _git("log", "-1", "--format=%s", commit).strip()
        specs.append(
            RepoSweSpec(
                commit=commit,
                parent=parents[0],
                subject=subject,
                source_files=sources,
                test_files=tests,
            )
        )
        if len(specs) >= limit:
            break
    return specs


def materialize(spec: RepoSweSpec, root: Path) -> None:
    """부모 커밋의 코드 + 고친 커밋의 테스트."""
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw:
        archive = Path(raw) / "base.tar"
        with archive.open("wb") as handle:
            result = subprocess.run(
                ["git", "archive", spec.parent, PREFIX.rstrip("/")],
                cwd=str(REPO),
                stdout=handle,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError("git archive 실패: " + str(result.stderr[:200]))
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if not member.name.startswith(PREFIX):
                    continue
                member.name = member.name[len(PREFIX):]
                if member.name:
                    tar.extract(member, root)
    # 고친 커밋의 테스트로 덮는다 — 이게 실패해야 할 테스트다.
    for test in spec.test_files:
        content = _git("show", spec.commit + ":" + test, check=False)
        target = root / test[len(PREFIX):]
        target.parent.mkdir(parents=True, exist_ok=True)
        if content:
            target.write_text(content, encoding="utf-8")
        elif target.exists():
            target.unlink()


def run_tests(
    root: Path, targets: list[str], *, timeout: int = 900
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(VENV_PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def apply_reference(spec: RepoSweSpec, root: Path) -> None:
    """정답 소스를 넣는다. 자체 검증에만 쓰고 모델에게는 절대 안 준다."""
    for source in spec.source_files:
        content = _git("show", spec.commit + ":" + source, check=False)
        target = root / source[len(PREFIX):]
        target.parent.mkdir(parents=True, exist_ok=True)
        if content:
            target.write_text(content, encoding="utf-8")
        elif target.exists():
            target.unlink()


def failure_summary(output: str) -> str:
    keep = ("E ", "FAILED", "assert", "TypeError", "AttributeError", "ImportError")
    lines = [
        line for line in (output or "").splitlines() if line.strip().startswith(keep)
    ]
    return "\n".join(lines)[:1200]


def validate(specs: list[RepoSweSpec], *, limit: int = 0) -> list[RepoSweSpec]:
    """부모에선 실패하고 정답을 넣으면 통과하는가."""
    good: list[RepoSweSpec] = []
    chosen = specs[:limit] if limit else specs
    for index, spec in enumerate(chosen, 1):
        rel_tests = [t[len(PREFIX):] for t in spec.test_files]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            try:
                materialize(spec, root)
            except Exception as exc:
                print("  [%d] %s 물질화 실패: %s" % (index, spec.commit[:8], exc))
                continue
            try:
                broken = run_tests(root, rel_tests)
            except subprocess.TimeoutExpired:
                print("  [%d] %s 건너뜀 — 테스트가 안 끝난다" % (index, spec.commit[:8]))
                continue
            if broken.returncode == 0:
                print(
                    "  [%d] %s 건너뜀 — 부모에서도 통과한다" % (index, spec.commit[:8])
                )
                continue
            head = failure_summary(broken.stdout)
            apply_reference(spec, root)
            try:
                fixed = run_tests(root, rel_tests)
            except subprocess.TimeoutExpired:
                print("  [%d] %s 건너뜀 — 정답 검증이 안 끝난다" % (index, spec.commit[:8]))
                continue
            if fixed.returncode != 0:
                print(
                    "  [%d] %s 건너뜀 — 정답을 넣어도 실패한다" % (index, spec.commit[:8])
                )
                continue
        good.append(
            RepoSweSpec(
                commit=spec.commit,
                parent=spec.parent,
                subject=spec.subject,
                source_files=spec.source_files,
                test_files=spec.test_files,
                failure_head=head,
                validated=True,
            )
        )
        print("  [%d] %s OK %s" % (index, spec.commit[:8], spec.subject[:52]))
    return good


def load_specs() -> list[RepoSweSpec]:
    raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return [
        RepoSweSpec(
            **{k: (tuple(v) if isinstance(v, list) else v) for k, v in row.items()}
        )
        for row in raw
    ]


def save_specs(specs: list[RepoSweSpec]) -> None:
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(
        json.dumps([spec.__dict__ for spec in specs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", type=int, default=0)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if args.discover:
        specs = discover(limit=args.discover)
        print("후보 %d건" % len(specs))
        for spec in specs[:20]:
            print(
                "  %s src=%d test=%d | %s"
                % (
                    spec.commit[:8],
                    len(spec.source_files),
                    len(spec.test_files),
                    spec.subject[:56],
                )
            )
        save_specs(specs)
        print("기록: %s" % SPEC_PATH)
        return 0

    if args.validate:
        good = validate(load_specs(), limit=args.limit)
        print("눈금으로 쓸 수 있는 과제 %d건" % len(good))
        save_specs(good)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
