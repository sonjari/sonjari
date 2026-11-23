"""Sonjari MCP 다리 꾸러미(.mcpb) 굽기 — 공식 MCP 레지스트리 · 스미더리 · 클로드 데스크톱 설치용(2026-11-23).

    python scripts/build_mcpb.py --out dist/mcpb

- 담는 것: `packaging/mcpb/`(manifest · pyproject · server/main.py) + 앱 아이콘 + `src/alture_jarvis` 의 깃 추적 파일.
- 판 번호는 앱(`ui/src-tauri/tauri.conf.json`)에서 가져와 manifest · pyproject 에 같이 적는다(두 벌이 갈리지 않게).
- ★ 꾸러미는 공개로 나간다 — 공개본(`export_public.py`)과 **같은 치환 · 같은 가드**를 지난 것만 굽는다. 가드에 걸리면 종료 코드 1.
- 굽기는 공식 도구(`npx @anthropic-ai/mcpb validate · pack`)로 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging" / "mcpb"
ICON = ROOT / "ui" / "src-tauri" / "icons" / "128x128.png"
MCPB = "@anthropic-ai/mcpb@2.1.2"


def _export_public():
    spec = importlib.util.spec_from_file_location("export_public", ROOT / "scripts" / "export_public.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def app_version() -> str:
    return str(json.loads((ROOT / "ui" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"])


def stage(out: Path) -> Path:
    ep = _export_public()
    stage_dir = out / "stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    # 가드가 「내보낸 폴더」로 알아보게 표시를 둔다(공개본과 같은 규칙).
    (stage_dir / ep.EXPORT_MARKER).write_text("build_mcpb.py\n", encoding="utf-8")
    version = app_version()
    manifest = json.loads((TEMPLATE / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    (stage_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    py = (TEMPLATE / "pyproject.toml").read_text(encoding="utf-8")
    py = "\n".join(f'version = "{version}"' if line.startswith("version = ") else line for line in py.splitlines()) + "\n"
    (stage_dir / "pyproject.toml").write_text(py, encoding="utf-8")
    (stage_dir / "server").mkdir()
    shutil.copyfile(TEMPLATE / "server" / "main.py", stage_dir / "server" / "main.py")
    shutil.copyfile(ICON, stage_dir / "icon.png")
    # ★ 작업 폴더가 아니라 **커밋(HEAD)** 에서 뽑는다 — 같은 폴더를 쓰는 다른 세션의 미커밋 변경이 공개 꾸러미에 섞이지 않게(11-23).
    prefix = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-prefix"],
                            capture_output=True, check=True, text=True).stdout.strip()
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD", "--", "src/alture_jarvis"],
                             capture_output=True, check=True).stdout
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        blobs = {m.name[len(prefix):] if m.name.startswith(prefix) else m.name: tar.extractfile(m).read() for m in members}
    for rel, data in sorted(blobs.items()):
        if "__pycache__" in rel or ".." in Path(rel).parts:
            continue
        dst = stage_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            dst.write_bytes(data)
            continue
        dst.write_bytes(ep.transform(text).encode("utf-8"))
    problems = ep.guard(stage_dir)
    (stage_dir / ep.EXPORT_MARKER).unlink()
    if problems:
        raise SystemExit("가드에 걸림 — 굽지 않습니다:\n" + "\n".join(problems[:30]))
    return stage_dir


def pack(stage_dir: Path, out: Path) -> Path:
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    subprocess.run([npx, "-y", MCPB, "validate", str(stage_dir / "manifest.json")], check=True)
    target = out / f"sonjari-mcp-{app_version()}.mcpb"
    target.unlink(missing_ok=True)
    subprocess.run([npx, "-y", MCPB, "pack", str(stage_dir), str(target)], check=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "dist" / "mcpb"))
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    stage_dir = stage(out)
    if args.stage_only:
        print(stage_dir)
        return 0
    target = pack(stage_dir, out)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(json.dumps({"mcpb": str(target), "bytes": target.stat().st_size, "sha256": digest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
