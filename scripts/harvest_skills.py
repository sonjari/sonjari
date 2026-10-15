"""GitHub 분야별 스킬 수집 — 라이선스·출처·위생을 지키는 들여오기 (W4).

    # 이미 받아 둔(또는 사람이 검토한) 체크아웃에서 들여오기 — 네트워크 없음
    python scripts/harvest_skills.py --from-dir <repo 폴더> --repo owner/name --commit <sha> --collection <묶음> [--apply]

    # 고정 커밋을 얕게 받아 들여오기 — 내려받기라서 사람이 승인한 목록(skills/sources.json)만, --fetch 를 줘야 돈다
    python scripts/harvest_skills.py --manifest skills/sources.json --fetch [--apply]

기본은 **미리보기**다(`--apply` 없으면 아무것도 안 쓴다).

## 이 저장소가 이미 대가를 치르고 배운 규칙 (인수인계서 W4)

1. 허용 라이선스만: MIT · Apache-2.0 · CC-BY-4.0. 원본 LICENSE/NOTICE·출처 URL·커밋 해시를 `SOURCE.json` 에 같이 둔다.
   라이선스를 못 알아보면 **가져오지 않는다.**
2. 실행 코드는 가져오지 않는다(스토어 10.2.2 — 원격 코드를 받아 설명과 다르게 실행 금지). 스킬 폴더에서 `.md`·LICENSE·NOTICE 만.
   빠진 파일 수를 적는다 — 스크립트에 기대는 스킬이면 사람이 판단한다.
3. `description` 이 없는 스킬은 코드가 고를 근거가 없어 안 들인다.
4. 위생: 승인·확인 없이 진행하라는 문장 수를 센다(읽을 때 `skill_hygiene` 가 걷는다).
5. 이름이 기존 스킬과 겹치면 안 들인다 — 조용히 덮으면 트리거가 남의 본문을 가리킨다.
6. 들였다고 닿는 게 아니다. 한국어 트리거는 실제 발화에서 캐서 따로 넣는다(`scripts/measure_skill_reach.py`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alture_jarvis.skill_hygiene import neutralize  # noqa: E402
from alture_jarvis.skills import _parse_frontmatter, _SAFE_NAME, load_skills  # noqa: E402

TEXT_KEEP = {".md", ".markdown", ".txt"}
NOTICE_NAMES = re.compile(r"^(LICENSE|LICENCE|NOTICE|COPYING)(\..*)?$", re.I)


def detect_license(text: str) -> str:
    head = " ".join(text.split())[:4000]
    if "Permission is hereby granted, free of charge" in head:
        return "MIT"
    if "Apache License" in head and "Version 2.0" in head:
        return "Apache-2.0"
    if "Attribution 4.0 International" in head and "Creative Commons" in head:
        return "CC-BY-4.0"
    return ""


ALLOWED = {"MIT", "Apache-2.0", "CC-BY-4.0"}


def repo_license(repo_dir: Path) -> tuple[str, list[Path]]:
    files = [p for p in repo_dir.iterdir() if p.is_file() and NOTICE_NAMES.match(p.name)]
    for path in files:
        found = detect_license(path.read_text(encoding="utf-8", errors="replace"))
        if found:
            return found, files
    return "", files


def plan(repo_dir: Path, existing: set[str], *, max_dropped: int | None = None) -> dict:
    """`max_dropped`: 빠지는(실행) 파일이 이보다 많은 스킬은 안 들인다 — 스크립트에 기대는 본문은 들여도 못 쓴다."""
    license_id, notice_files = repo_license(repo_dir)
    rows = []
    skill_files = sorted(repo_dir.rglob("SKILL.md"))
    # ★ 2026-09-15 실측: 한 저장소 안에 `best-practices`·`language` 같은 같은 폴더 이름이 수십 개였다.
    #   이름으로 들이면 뒤의 것이 앞의 것을 조용히 덮는다 — 겹치는 이름은 전부 거절한다.
    name_counts: dict[str, int] = {}
    for skill_md in skill_files:
        name_counts[skill_md.parent.name.lower()] = name_counts.get(skill_md.parent.name.lower(), 0) + 1
    for skill_md in skill_files:
        skill_dir = skill_md.parent
        name = skill_dir.name.lower()
        fields, body = _parse_frontmatter(skill_md.read_text(encoding="utf-8-sig", errors="replace"))
        own_license = ""
        for path in skill_dir.iterdir():
            if path.is_file() and NOTICE_NAMES.match(path.name):
                own_license = detect_license(path.read_text(encoding="utf-8", errors="replace")) or own_license
        effective = own_license or license_id
        keep = [p for p in skill_dir.rglob("*") if p.is_file() and (p.suffix.lower() in TEXT_KEEP or NOTICE_NAMES.match(p.name))]
        dropped = [p for p in skill_dir.rglob("*") if p.is_file() and p not in keep]
        _, neutralized = neutralize(body)
        refusal = ""
        if not _SAFE_NAME.match(name):
            refusal = "unsafe_name"
        elif effective not in ALLOWED:
            refusal = f"license_not_allowed:{effective or 'unknown'}"
        elif not fields.get("description"):
            refusal = "no_description"
        elif name in existing:
            refusal = "name_exists"
        elif name_counts[name] > 1:
            refusal = "name_duplicate_in_source"
        elif max_dropped is not None and len(dropped) > max_dropped:
            refusal = f"depends_on_dropped_files:{len(dropped)}"
        rows.append({
            "name": name, "path": str(skill_md.parent.relative_to(repo_dir)), "license": effective,
            "keep_files": len(keep), "dropped_files": [str(p.relative_to(skill_dir)) for p in dropped][:20],
            "dropped_count": len(dropped), "hygiene_sentences": neutralized, "refused": refusal,
        })
    return {"license": license_id, "notice_files": [p.name for p in notice_files], "skills": rows}


def apply(repo_dir: Path, report: dict, *, repo: str, commit: str, collection: str, skills_root: Path) -> list[str]:
    if not _SAFE_NAME.match(collection):
        raise SystemExit("unsafe collection name")
    target = skills_root / "vendor" / collection
    added = []
    for row in report["skills"]:
        if row["refused"]:
            continue
        source = repo_dir / row["path"]
        dest = target / row["name"]
        dest.mkdir(parents=True, exist_ok=True)
        for path in source.rglob("*"):
            if path.is_file() and (path.suffix.lower() in TEXT_KEEP or NOTICE_NAMES.match(path.name)):
                out = dest / path.relative_to(source)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, out)
        added.append(row["name"])
    for name in report["notice_files"]:
        shutil.copy2(repo_dir / name, target / name)
    if added:
        (target / "SOURCE.json").write_text(json.dumps({
            "repo": f"https://github.com/{repo}" if repo and "://" not in repo else repo,
            "commit": commit, "license": report["license"], "fetched_at": time.strftime("%Y-%m-%d"),
            "skills": added, "dropped_executable_files": {r["name"]: r["dropped_count"] for r in report["skills"] if not r["refused"]},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def fetch(repo: str, commit: str, into: Path) -> Path:
    """고정 커밋만 받는다. 브랜치 이름을 받지 않는다 — 받을 때마다 내용이 바뀌면 검토가 무의미하다."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("commit must be a full 40-char sha")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SystemExit("repo must be owner/name")
    dest = into / repo.replace("/", "__")
    subprocess.run(["git", "init", "-q", str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--depth", "1", f"https://github.com/{repo}.git", commit], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"], check=True)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir")
    ap.add_argument("--repo", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--collection", default="")
    ap.add_argument("--manifest")
    ap.add_argument("--fetch", action="store_true", help="network download of pinned commits (needs human approval)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skills-root", default=str(ROOT / "skills"))
    ap.add_argument("--max-dropped", type=int, default=None, help="skip skills that would lose more than N non-text files")
    args = ap.parse_args()
    skills_root = Path(args.skills_root)
    existing = {name.split("/")[-1] for name in load_skills(skills_root)}
    jobs = []
    if args.from_dir:
        jobs.append((Path(args.from_dir), args.repo, args.commit, args.collection, args.max_dropped))
    elif args.manifest:
        if not args.fetch:
            raise SystemExit("--manifest needs --fetch (a download). Get approval first.")
        temp = Path(tempfile.mkdtemp(prefix="skill-harvest-"))
        for entry in json.loads(Path(args.manifest).read_text(encoding="utf-8")).get("sources", []):
            jobs.append((fetch(entry["repo"], entry["commit"], temp) / entry.get("path", ""), entry["repo"],
                         entry["commit"], entry["collection"], entry.get("max_dropped", args.max_dropped)))
    out = []
    for repo_dir, repo, commit, collection, max_dropped in jobs:
        report = plan(repo_dir, existing, max_dropped=max_dropped)
        report.update({"repo": repo, "commit": commit, "collection": collection})
        if args.apply:
            report["added"] = apply(repo_dir, report, repo=repo, commit=commit, collection=collection, skills_root=skills_root)
            existing |= set(report["added"])
        out.append(report)
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
