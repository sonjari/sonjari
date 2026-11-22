"""3D 프린트 — 뱀부 스튜디오 명령줄로 썰고 결과를 읽는다 (2026-11-14 · 설계 `설계_3D프린트갈래` §5).

- 사람의 PC 에 깔린 뱀부 스튜디오를 **명령줄로만** 부른다(화면 클릭 안 함). 출력 단추는 사람이 누른다 — 여기서는 프린터로 안 보낸다.
- 설정은 뱀부가 깔아 둔 시스템 설정(`resources/profiles/BBL/{machine,process,filament}`)에서 고른다. 그 파일들은 부모 설정을
  물려받는(`inherits`) 구조라, 파일 하나만 넘기면 부모 칸(필라멘트 밀도 등)이 빠진다(11-14 실측: 무게 0g). → 상속을 풀어 합친 뒤 넘긴다.
- 판정은 **종료 코드가 아니라 산출물**로 한다(11-14 실측: `--export-3mf` 를 주면 rc 139 로 죽어도 G-code 는 나왔다).
  `result.json`(뱀부가 쓰는 결과표)과 G-code 머리를 읽는다.
- 빠진 부분 의심(뱀부 위키 낙타 예시): 썬 높이가 메시 높이와 한 층 넘게 다르면 표시한다.
- 지원: 뱀부 P · X · H 시리즈(대표 11-14 · A 시리즈 제외). 실제로 뽑아 본 기종은 X2D 뿐 — 나머지는 「설정만 · 실측 전」.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: 대표 11-14: P · X · H 시리즈만. 값은 뱀부 스튜디오 기계 설정 이름(노즐 앞부분).
SUPPORTED_PRINTERS = (
    "Bambu Lab P1P", "Bambu Lab P1S", "Bambu Lab P2S",
    "Bambu Lab X1", "Bambu Lab X1 Carbon", "Bambu Lab X1E", "Bambu Lab X2D",
    "Bambu Lab H2C", "Bambu Lab H2D", "Bambu Lab H2D Pro", "Bambu Lab H2S",
)
#: 실제로 뽑아 확인한 기종.
MEASURED_PRINTERS = ("Bambu Lab X2D",)
#: 한 번 썰기 제한. 11-14 실측: 배 205만 면도 21초 · 23만 면 8~16초인데 X2D 가 가끔(약 스무 번에 두 번) 끝없이 멈췄다 — 10분을
#: 버리고 실패하던 것을 4분에 끊고 한 번 다시 썬다(다시 하면 10초에 끝났다).
SLICE_TIMEOUT_SEC = 240
PLA_DENSITY = 1.24  # g/cm³ — 설정에서 못 읽을 때만
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


#: 결과표가 나온 뒤 스스로 끝나기를 기다리는 시간. 넘으면 우리가 띄운 그 프로세스만 끊는다.
EXIT_GRACE_SEC = 10.0


def _result_ready(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _kill_own(proc: subprocess.Popen) -> None:
    """우리가 띄운 프로세스 하나만 끊는다. 11-17 실측: 종료에서 멈춘 뱀부는 끊어도 커널에서 못 빠져나와 「끝남」인 채 남기도
    했다(재부팅 전엔 못 치움) — 그래서 끊은 뒤 오래 기다리지 않는다. 산출물은 이미 나와 있다."""
    try:
        proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_bambu(cmd: list[str], *, capture_output: bool = True, timeout: float = SLICE_TIMEOUT_SEC,
              creationflags: int = _NO_WINDOW, poll: float = 0.2, grace: float = EXIT_GRACE_SEC) -> subprocess.CompletedProcess:
    """`subprocess.run` 과 같은 꼴로 뱀부 명령줄을 부르되, **끝은 프로세스 종료가 아니라 결과표(result.json)로** 가른다.

    11-17 실측: 뱀부 명령줄을 여럿 동시에 돌리면 60번 중 5번이 결과표(Success)와 G-code 를 다 쓰고도 종료에서 멈췄다
    (스레드 하나 · 창 없음 · CPU 0). `subprocess.run` 은 종료만 기다려 240초를 버리고 다시 썰었다. 뱀부는 `--slice` ·
    `--export-3mf` 모두 산출물을 먼저 쓰고 결과표를 맨 마지막에 쓰므로, 새 결과표가 읽히면 끝난 것으로 본다. 그 뒤
    `grace` 초 안에 안 나가면 **이 함수가 띄운 그 프로세스 하나만** 끊는다 — 사람이 띄운 뱀부 창은 건드리지 않는다.
    출력은 버린다(부르는 쪽은 종료 코드와 산출물만 본다 · 파이프가 차서 멈추는 일도 막음).
    """
    out_dir = Path(cmd[cmd.index("--outputdir") + 1]) if "--outputdir" in cmd else None
    marker = out_dir / "result.json" if out_dir is not None else None
    if marker is not None:
        marker.unlink(missing_ok=True)  # 앞 단계의 결과표를 끝 표시로 착각하지 않게(뱀부가 어차피 새로 쓴다)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,  # noqa: S603
                            creationflags=creationflags)
    started = time.monotonic()
    done_at: float | None = None
    rc_from_result: int | None = None
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                return subprocess.CompletedProcess(cmd, rc, b"", b"")
            now = time.monotonic()
            if done_at is None and marker is not None:
                result = _result_ready(marker)
                if result is not None:
                    done_at = now
                    try:
                        rc_from_result = int(result.get("return_code", 0))
                    except (TypeError, ValueError):
                        rc_from_result = 0
            if done_at is not None and now - done_at >= grace:
                _kill_own(proc)
                return subprocess.CompletedProcess(cmd, rc_from_result if rc_from_result is not None else 0, b"",
                                                   b"exit_hung: result.json written, process killed")
            if now - started >= timeout:
                _kill_own(proc)
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(poll)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        raise


def find_bambu() -> Path | None:
    """깔린 뱀부 스튜디오 실행 파일. 설정 `JARVIS_BAMBU_STUDIO` 가 먼저."""
    env = os.environ.get("JARVIS_BAMBU_STUDIO", "").strip()
    candidates = [Path(env)] if env else []
    if sys.platform == "win32":
        candidates += [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Bambu Studio" / "bambu-studio.exe",
                       Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Bambu Studio" / "bambu-studio.exe"]
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")]
    for path in candidates:
        if path and path.is_file():
            return path
    return None


def profiles_root(exe: Path) -> Path:
    if sys.platform == "darwin":
        return exe.parents[1] / "Resources" / "profiles" / "BBL"
    return exe.parent / "resources" / "profiles" / "BBL"


def _index(folder: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in folder.glob("*.json"):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            continue
        if isinstance(name, str):
            found[name] = path
    return found


def resolve(folder: Path, name: str) -> dict[str, Any]:
    """설정 이름 → 부모까지 합친 설정(자식 값이 이김). 고리 · 깊이 20 넘으면 멈춘다."""
    index = _index(folder)
    chain: list[dict[str, Any]] = []
    current: str | None = name
    seen: set[str] = set()
    while current and current not in seen and len(chain) < 20:
        seen.add(current)
        path = index.get(current)
        if path is None:
            if not chain:
                raise FileNotFoundError(f"뱀부 설정 없음: {name} ({folder})")
            break
        data = json.loads(path.read_text(encoding="utf-8"))
        chain.append(data)
        current = data.get("inherits") or None
    merged: dict[str, Any] = {}
    for data in reversed(chain):
        merged.update(data)
    merged.pop("inherits", None)
    merged["name"] = name
    return merged


def preset_names(printer: str, nozzle: float, process: str, filament: str) -> tuple[str, str, str]:
    """짐작한 이름(첫 후보). 맞는지는 `pick_preset` 이 설정 안의 「맞는 기계 목록」으로 가린다."""
    nz = f"{nozzle:g}"
    short = printer.replace("Bambu Lab ", "")
    machine = f"{printer} {nz} nozzle"
    proc = f"{process} @BBL {short}" + ("" if nz == "0.4" else f" {nz} nozzle")
    fil = f"{filament} @BBL {short} {nz} nozzle"
    return machine, proc, fil


def pick_preset(folder: Path, base: str, machine: str, first: list[str]) -> str:
    """`base @…` 설정 가운데 이 기계(`machine`)가 「맞는 기계 목록(compatible_printers)」에 든 것의 이름.

    이름을 짐작하면 틀린다(11-14 실측: P1S · X1 · X1E 는 「@BBL X1C」 설정을 쓴다 — 짐작한 「@BBL P1S」는 없어서
    지원 목록에 있는 기종이 아예 못 썰었다). 짐작한 이름(`first`)이 맞으면 그것을, 아니면 목록으로 찾는다.
    """
    index = _index(folder)

    def fits(name: str, *, unlisted_ok: bool) -> bool:
        try:
            listed = resolve(folder, name).get("compatible_printers")
        except (OSError, ValueError, FileNotFoundError):
            return False
        if not isinstance(listed, list) or not listed:
            return unlisted_ok  # 목록이 없는 설정 — 짐작한 이름이면 예전처럼 받는다
        return machine in listed

    for name in first:
        if name in index and fits(name, unlisted_ok=True):
            return name
    for name in sorted(index):
        if name.startswith(f"{base} @") and fits(name, unlisted_ok=False):
            return name
    raise FileNotFoundError(f"뱀부 설정 없음: 「{base}」 가운데 {machine} 에 맞는 것이 없다 ({folder})")


#: 고른 필라멘트가 그 기종에 없을 때 대신 쓰는 것(차례대로). 11-14: 뱀부 2.8 의 P1P 에는 「Bambu PLA Basic」이 없고
#: PLA 는 「Generic PLA High Speed」 뿐이다. 대신 쓰면 영수증에 적힌다(`slice_3mf` 의 notes).
FILAMENT_FALLBACKS = ("Generic PLA", "Generic PLA High Speed")


def _pick_filament(folder: Path, filament: str, machine: str, first: list[str]) -> str:
    try:
        return pick_preset(folder, filament, machine, first)
    except FileNotFoundError:
        if "PLA" not in filament:
            raise
    for other in FILAMENT_FALLBACKS:
        try:
            return pick_preset(folder, other, machine, [])
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"뱀부 설정 없음: 「{filament}」 · 대신할 PLA 도 {machine} 에 맞는 것이 없다 ({folder})")


def write_presets(root: Path, out_dir: Path, printer: str, nozzle: float, process: str, filament: str,
                  process_overrides: dict[str, str] | None = None) -> dict[str, Path]:
    machine, proc, fil = preset_names(printer, nozzle, process, filament)
    short = printer.replace("Bambu Lab ", "")
    data = {
        "machine": resolve(root / "machine", machine),
        "process": resolve(root / "process", pick_preset(root / "process", process, machine,
                                                         [proc, f"{process} @BBL {short}"])),
        # 노즐 이름이 없는 필라멘트 설정도 있다(예: 「Bambu PLA Basic @BBL X1C」).
        "filament": resolve(root / "filament", _pick_filament(root / "filament", filament, machine,
                                                              [fil, f"{filament} @BBL {short}"])),
    }
    data["process"].update(process_overrides or {})
    paths: dict[str, Path] = {}
    for kind, content in data.items():
        path = out_dir / f"_slice_{kind}.json"
        path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
        paths[kind] = path
    return paths


def _two_nozzles(machine_json: Path) -> bool:
    """기계 설정의 노즐 지름 칸이 둘 이상이면 노즐 둘 기종(X2D · H2C · H2D · H2D Pro)."""
    try:
        nozzles = json.loads(machine_json.read_text(encoding="utf-8")).get("nozzle_diameter")
    except (OSError, ValueError):
        return False
    return isinstance(nozzles, list) and len(nozzles) > 1


#: 판 가장자리 여유(mm) — 브림 · 스커트 · 닦기 자리.
BED_MARGIN_MM = 5.0


def bed_size(machine: dict[str, Any]) -> tuple[float, float, float] | None:
    """기계 설정의 출력 가능 넓이(점 넷 「XxY」) · 높이 → (가로, 세로, 높이). 못 읽으면 None."""
    try:
        pts = [tuple(float(v) for v in str(p).strip().split("x")) for p in machine.get("printable_area") or []]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return max(xs) - min(xs), max(ys) - min(ys), float(machine.get("printable_height") or 0)
    except (ValueError, TypeError, IndexError):
        return None


def fits_bed(mesh_dims: tuple[float, float, float], bed: tuple[float, float, float]) -> str | None:
    """안 들어가면 까닭 한 줄. 판 위에서 돌려 놓을 수 있으니 가로 · 세로는 큰 것끼리 견준다."""
    mx, my, mz = mesh_dims
    bx, by, bz = bed
    foot = sorted((mx, my))
    room = sorted((bx - 2 * BED_MARGIN_MM, by - 2 * BED_MARGIN_MM))
    if foot[0] > room[0] or foot[1] > room[1] or (bz and mz > bz):
        return (f"too_big: 모델 {mx:.0f}×{my:.0f}×{mz:.0f}mm 가 판 {bx:.0f}×{by:.0f}×{bz:.0f}mm"
                f"(가장자리 {BED_MARGIN_MM:g}mm 여유)에 안 들어간다 — 크기를 줄이거나 나눠 뽑아야 한다")
    return None


_HEADER = {
    "time": re.compile(r"^; (?:model printing time|estimated printing time[^=]*)[:=]\s*(.+?)(?:;|$)", re.M),
    "layers": re.compile(r"^; total layer number:\s*(\d+)", re.M),
    "length_mm": re.compile(r"^; total filament length \[mm\]\s*:\s*([\d.]+)", re.M),
    "max_z": re.compile(r"^; max_z_height:\s*([\d.]+)", re.M),
}


def read_gcode_head(path: Path, limit: int = 200_000) -> dict[str, Any]:
    with open(path, "rb") as fh:
        text = fh.read(limit).decode("utf-8", "replace")
    out: dict[str, Any] = {}
    for key, pattern in _HEADER.items():
        m = pattern.search(text)
        if m:
            out[key] = m.group(1).strip()
    for key in ("layers",):
        if key in out:
            out[key] = int(out[key])
    for key in ("length_mm", "max_z"):
        if key in out:
            out[key] = float(out[key])
    return out


def slice_3mf(model: Path, out_dir: Path, *, printer: str = "Bambu Lab X2D", nozzle: float = 0.4,
              process: str = "0.20mm Standard", filament: str = "Bambu PLA Basic", overrides: dict[str, str] | None = None,
              mesh_height: float | None = None, mesh_dims: tuple[float, float, float] | None = None,
              exe: Path | None = None,
              run: Any = run_bambu) -> dict[str, Any]:
    """썰어서 영수증 조각을 돌려준다. 뱀부가 없으면 `{"ok": False, "skipped": …}`."""
    if printer not in SUPPORTED_PRINTERS:
        return {"ok": False, "error": f"unsupported_printer: {printer} — 지원은 뱀부 P · X · H 시리즈"}
    exe = exe or find_bambu()
    if exe is None:
        return {"ok": False, "skipped": "뱀부 스튜디오가 이 PC 에 없다 — 3MF 를 슬라이서에서 직접 여세요"}
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        presets = write_presets(profiles_root(exe), out_dir, printer, nozzle, process, filament, overrides)
    except (OSError, ValueError, FileNotFoundError) as exc:
        return {"ok": False, "error": f"preset_failed: {exc}"}
    if mesh_dims is not None:
        try:
            machine = json.loads(presets["machine"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            machine = {}
        bed = bed_size(machine)
        if bed is None:
            return {"ok": False, "error": "bed_unknown: 기계 설정에서 판 크기를 못 읽었다 — 썰지 않는다"}
        too_big = fits_bed(mesh_dims, bed)
        if too_big:
            return {"ok": False, "error": too_big, "bed_mm": [round(v, 1) for v in bed]}
    for stale in ("plate_1.gcode", "result.json"):
        (out_dir / stale).unlink(missing_ok=True)
    cmd = [str(exe), "--load-settings", f"{presets['machine']};{presets['process']}",
           "--load-filaments", str(presets["filament"]),
           "--slice", "0", "--outputdir", str(out_dir), str(model)]
    started = time.time()
    rc: int | None = None
    notes: list[str] = []
    for attempt in (1, 2):
        try:
            done = run(cmd, capture_output=True, timeout=SLICE_TIMEOUT_SEC, creationflags=_NO_WINDOW)
            rc = done.returncode
            break
        except subprocess.TimeoutExpired:
            if attempt == 2:
                return {"ok": False, "error": f"timeout: 두 번 다 {SLICE_TIMEOUT_SEC}초 넘게 썰었다(뱀부가 멈춤)"}
            notes.append(f"첫 썰기가 {SLICE_TIMEOUT_SEC}초 넘게 멈춰 끊고 다시 썰었다")
            for stale in ("plate_1.gcode", "result.json"):
                (out_dir / stale).unlink(missing_ok=True)
    sec = round(time.time() - started, 1)
    gcode = out_dir / "plate_1.gcode"
    result_path = out_dir / "result.json"
    result: dict[str, Any] = {}
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            result = {}
    if not gcode.is_file():
        return {"ok": False, "rc": rc, "sec": sec,
                "error": f"slice_failed: G-code 가 안 나왔다 — {result.get('error_string') or '결과표 없음'}"}
    head = read_gcode_head(gcode)
    # 넘길 파일: 뱀부가 직접 쓴 「프로젝트 3MF」(고른 설정 · 미리보기 포함). 썰기와 한 번에 시키면 rc 139 로 죽어서(11-14)
    # 따로 한 번 더 부른다. 실패해도 썬 결과는 그대로 둔다.
    project = out_dir / f"{Path(model).stem}_bambu.3mf"
    project.unlink(missing_ok=True)
    try:
        run([str(exe), "--load-settings", f"{presets['machine']};{presets['process']}",
             "--load-filaments", str(presets["filament"]), "--export-3mf", project.name,
             "--outputdir", str(out_dir), str(model)],
            capture_output=True, timeout=SLICE_TIMEOUT_SEC, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        pass
    if project.is_file() and overrides and not mark_changed_settings(project, overrides):
        notes.append("넘길 프로젝트 파일에 「바꾼 설정」 목록을 못 적었다 — 뱀부 화면에서 열면 서포트 · 브림이 기본값으로 "
                     "돌아갈 수 있으니 켜졌는지 확인할 것")
    plate = (result.get("sliced_plates") or [{}])[0]
    density = _density(presets["filament"])
    grams = None
    if head.get("length_mm"):
        area = 3.14159265 * (1.75 / 2) ** 2  # mm²
        grams = round(head["length_mm"] * area / 1000 * density, 1)
    warning = str(plate.get("warning_message") or "").strip()
    if warning:
        notes.append(f"뱀부 경고: {warning}")
    if mesh_height and head.get("max_z") and abs(head["max_z"] - mesh_height) > _layer(presets["process"]) + 0.05:
        notes.append(f"썬 높이 {head['max_z']}mm 가 메시 높이 {mesh_height:.2f}mm 와 다르다 — 일부가 안 썰렸을 수 있다")
    if not project.is_file():
        notes.append("뱀부 프로젝트 3MF 를 못 만들었다 — 모양만 든 3MF 를 열면 프린터 · 서포트를 다시 골라야 한다")
    elif _two_nozzles(presets["machine"]):
        # 11-14 실측: 노즐 둘 기종(X2D · H2C · H2D · H2D Pro)이 내보낸 프로젝트 파일은 명령줄로 다시 썰면 4/4 실패(뱀부 -100 ·
        # 설정을 다시 줘도 · 필라멘트 배정 수동 · 프라임 타워 꺼도 같음), 화면에서는 썰린다. 노즐 하나 7기종은 7/7 다시 썰렸다.
        # 그래서 이 기종은 명령줄로 못 확인한다고 사실대로 적고, 헛 「실패」 경고를 내지 않는다.
        notes.append("노즐 둘 기종은 넘길 프로젝트 파일을 명령줄로 다시 썰어 확인할 수 없다(뱀부 명령줄 한계) — "
                     "뱀부 스튜디오에서 열어 「플레이트 슬라이스」를 한 번 누르고 출력할 것")
    else:
        # 넘길 파일을 그대로 한 번 썰어 본다 — 노즐 하나 기종은 늘 되므로 실패하면 진짜 이상이다.
        recheck = out_dir / "recheck"
        recheck.mkdir(exist_ok=True)
        for stale in ("plate_1.gcode", "result.json"):
            (recheck / stale).unlink(missing_ok=True)
        try:
            run([str(exe), "--slice", "0", "--outputdir", str(recheck), str(project)],
                capture_output=True, timeout=SLICE_TIMEOUT_SEC, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            pass
        if not (recheck / "plate_1.gcode").is_file():
            notes.append("넘길 프로젝트 파일을 다시 썰어 보니 실패했다 — 뱀부 스튜디오에서 「플레이트 슬라이스」로 확인하고, "
                         "안 되면 모양만 든 3MF 를 열어 프린터 · 서포트를 다시 골라 출력할 것")
    try:
        used_filament = str(json.loads(presets["filament"].read_text(encoding="utf-8")).get("name") or "")
    except (OSError, ValueError):
        used_filament = ""
    if used_filament and not used_filament.startswith(f"{filament} @"):
        notes.append(f"{printer} 에는 「{filament}」 설정이 없어 「{used_filament}」 로 썰었다 — 실제 넣을 필라멘트에 맞춰 뱀부에서 바꿀 것")
    if printer not in MEASURED_PRINTERS:
        notes.append(f"{printer} 는 설정만 맞췄다 — 실제 출력은 X2D 에서만 확인했다")
    return {
        "ok": True, "rc": rc, "sec": sec, "printer": printer, "nozzle": nozzle, "process": process, "filament": filament,
        "estimated_time": head.get("time"), "estimated_sec": round(float(plate["total_predication"]), 0) if plate.get("total_predication") else None,
        "layers": head.get("layers"), "filament_mm": head.get("length_mm"), "filament_g": grams,
        "max_z_mm": head.get("max_z"), "gcode": str(gcode), "notes": notes,
        "project_3mf": str(project) if project.is_file() else None,
    }


def mark_changed_settings(project: Path, overrides: dict[str, str]) -> bool:
    """넘길 프로젝트 3MF 의 `different_settings_to_system[0]`(공정 칸 중 시스템 값과 다른 것)에 우리가 바꾼 칸 이름을 적는다.

    ★ 11-16 실측: 명령줄이 내보낸 3MF 는 이 목록이 비어 있고, 뱀부 화면은 3MF 를 열 때 공정 이름이 시스템 프리셋이면
    **목록에 없는 칸을 모두 시스템 값으로 되돌린다**(BambuStudio `Preset.cpp` `load_external_preset` →
    `PrintConfig.cpp` `update_non_diff_values_to_base_config`). 그래서 대표가 연 판은 서포트가 꺼진 채 썰렸다.
    화면이 직접 저장한 파일은 이 목록을 채운다(예: 「enable_arc_fitting;enable_support;seam_position」).
    목록에 적힌 칸은 3MF 의 값이 남는다 — 시스템과 같은 값이 적혀도 해가 없다."""
    import zipfile

    name = "Metadata/project_settings.config"
    try:
        with zipfile.ZipFile(project) as zin:
            entries = [(info, zin.read(info.filename)) for info in zin.infolist()]
    except (OSError, zipfile.BadZipFile):
        return False
    out: list[tuple[Any, bytes]] = []
    done = False
    for info, data in entries:
        if info.filename == name:
            try:
                cfg = json.loads(data.decode("utf-8"))
            except ValueError:
                return False
            diff = cfg.get("different_settings_to_system")
            if not isinstance(diff, list) or not diff:
                diff = [""]
            have = [k for k in str(diff[0]).split(";") if k]
            diff[0] = ";".join(sorted(set(have) | {k for k in overrides if k}))
            cfg["different_settings_to_system"] = diff
            data = json.dumps(cfg, ensure_ascii=False, indent=4).encode("utf-8")
            done = True
        out.append((info, data))
    if not done:
        return False
    tmp = project.with_suffix(".tmp3mf")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in out:
                zout.writestr(info, data)
        tmp.replace(project)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


def _density(path: Path) -> float:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("filament_density")
        value = value[0] if isinstance(value, list) else value
        return float(value) or PLA_DENSITY
    except (OSError, ValueError, TypeError):
        return PLA_DENSITY


def _layer(path: Path) -> float:
    try:
        return float(json.loads(path.read_text(encoding="utf-8")).get("layer_height") or 0.2)
    except (OSError, ValueError, TypeError):
        return 0.2


def open_in_bambu(model: Path, exe: Path | None = None) -> bool:
    """사람이 보고 출력을 누르도록 뱀부 스튜디오를 그 3MF 로 연다(기다리지 않는다)."""
    exe = exe or find_bambu()
    if exe is None or not Path(model).is_file():
        return False
    # 뱀부는 창이 있는 프로그램이라 콘솔이 없지만, 뒤에서 띄우는 명령은 모두 숨김 표시를 단다(시험 test_no_console_window_popups_1030).
    subprocess.Popen([str(exe), str(model)], close_fds=True, creationflags=_NO_WINDOW)  # noqa: S603 — 우리가 찾은 뱀부 · 우리가 만든 파일
    return True
