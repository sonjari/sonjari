# -*- coding: utf-8 -*-
"""애니메이터 팩 도구 — 엇박자 루프 두 걸음 (2026-11-02 · 설계: docs/설계_게임애니메이션팩_2026-11-02.ko.md).

손자리는 MCP 서버만 있고 3ds Max 를 직접 부르지 못한다. 그래서 **클로드가 두 문을 오간다**:

    anim_offset_read   → 키 읽기 스크립트 파일 + 맥스에 보낼 한 줄
    (클로드) 3dsmax-mcp execute_maxscript(한 줄)    → 맥스가 키를 파일로 쓴다(장면은 안 바뀐다)
    anim_offset_plan   → 계산(시험 통과한 파이썬) · 미리 보기 표 · 쓰기 스크립트 파일 + 한 줄
    (사람이 표를 보고 「해」)
    (클로드) 3dsmax-mcp execute_maxscript(한 줄)    → 맥스가 Ctrl+Z 한 묶음으로 키를 쓰고 이음매를 다시 확인

키는 파일로만 오간다 — 대화에 싣지 않는다(뼈 10개 × 6트랙이면 수만 자다). 손자리 자신의 모델 목록에는 넣지 않는다
(맥스를 부를 손이 없다 — 클로드 · 코덱스 전용 문).
"""
from __future__ import annotations

import glob
import json
import re
import time
from pathlib import Path
from typing import Any

from .animator import habits, library, parts, refpose, specs
from .animator.maxscript import TRACKS, apply_script, load_dump, read_script, run_line, write_script
from .animator.plan import build_plan
from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

PACK_ID = "animator"
ANIMATOR_TOOL_NAMES = frozenset({
    "anim_offset_read", "anim_offset_plan",
    "anim_library_add", "anim_library_find", "anim_library_tag", "anim_library_apply", "anim_habit",
    "anim_parts", "anim_pose_sheet", "anim_video_to_biped", "anim_fit_check", "anim_fit_fix",
    "anim_blender_check", "anim_blender_fix", "anim_blender_block",
})

#: anim_library_tag 의 영문 칸 → 창고의 한글 꼬리표 칸(library.FACETS). 칸 이름 규칙은 specs.LIBRARY_TAG 주석.
FACET_ARGS: dict[str, str] = {"weapon": "무기", "concept": "컨셉", "weight": "무게감", "speed": "속도감"}

_TRACK_DESC = "다룰 트랙(기본 전부): rx ry rz(회전) px py pz(위치)"

ANIM_OFFSET_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "anim_offset_read",
        "description": (
            "(클로드 · 코덱스용 · 3ds Max) 엇박자 루프 1걸음: 뼈 줄(꼬리 · 머리카락 · 옷자락 · 장식의 포인트/본)의 위치 · 회전 키를 "
            "읽는 맥스 스크립트를 만들어 준다. 결과의 run_line 한 줄을 3dsmax-mcp 의 execute_maxscript 로 그대로 보내라 — "
            "맥스가 키를 파일로 쓰고 장면은 바꾸지 않는다. 그다음 anim_offset_plan 을 불러라. "
            "nodes 를 비우면 맥스에서 지금 고른 것을 뿌리 → 끝 순서로 쓴다. 바이페드 몸은 건너뛴다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start": {"type": "integer", "description": "루프 시작 프레임"},
                "end": {"type": "integer", "description": "루프 끝 프레임(끝 = 처음으로 이어지는 프레임)"},
                "nodes": {"type": "array", "items": {"type": "string"},
                          "description": "뼈 줄 노드 이름, 뿌리 → 끝 순서. 비우면 맥스의 현재 선택(계층 순)"},
                "tracks": {"type": "array", "items": {"type": "string"}, "description": _TRACK_DESC},
            },
            "required": ["start", "end"],
        },
    },
}

ANIM_OFFSET_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "anim_offset_plan",
        "description": (
            "(클로드 · 코덱스용 · 3ds Max) 엇박자 루프 2걸음: anim_offset_read 로 읽은 키로 마디마다 늦춘 루프를 계산한다. "
            "구간 끝을 넘은 키는 앞으로 감고, 처음과 끝 키를 같은 값으로 놓아 루프를 닫고, 탄젠트 종류는 원래 키를 따른다. "
            "결과의 preview(마디마다 늦춤 · 옮긴 키 · 감긴 키)를 **먼저 사람에게 보이고 「해」를 받은 뒤에만** run_line 을 "
            "execute_maxscript 로 보내라. 맥스는 Ctrl+Z 한 번으로 되돌릴 수 있게 한 묶음으로 쓰고, 다 쓴 뒤 이음매를 다시 확인한 "
            "한 줄(check OK 또는 notes)을 돌려준다 — 그 줄을 그대로 전해라. 늦춤은 캐릭터마다 다르다: 사람이 말한 값을 쓰고, "
            "모르면 물어라(흔히 마디당 1~3프레임)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "per_link": {"type": "number", "description": "마디마다 늦출 프레임(뿌리 = 0, 다음 = 1×, 그다음 = 2× …)"},
                "shifts": {"type": "array", "items": {"type": "number"},
                           "description": "마디마다 늦춤을 직접(뿌리부터). 주면 per_link 대신 쓴다"},
                "whole_frames": {"type": "boolean", "description": "늦춤을 정수 프레임으로 반올림(기본 true — 반 프레임 키를 만들지 않는다)"},
                "tracks": {"type": "array", "items": {"type": "string"}, "description": _TRACK_DESC},
                "read_file": {"type": "string", "description": "anim_offset_read 가 준 read_file(비우면 가장 최근 것)"},
                "character": {"type": "string", "description": "이 캐릭터 이름(다듬은 것 기억하기의 상황 열쇠 — 같은 캐릭터에 같은 늦춤을 두 번 쓰면 남길지 묻는다)"},
            },
            "required": [],
        },
    },
}


class AnimatorTools:
    """애니메이터 팩의 도구 묶음. 팩이 꺼져 있으면 불러도 거절한다."""

    def __init__(self, config: JarvisConfig, packs: Any = None) -> None:
        self.config = config
        self.packs = packs

    # ── 목록 · 등록 ─────────────────────────────────────────────────────
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return [ANIM_OFFSET_READ_TOOL, ANIM_OFFSET_PLAN_TOOL, *specs.V1_TOOLS]

    def enabled(self) -> bool:
        return self.packs is not None and self.packs.is_enabled(PACK_ID)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        """손자리 자신의 모델에게는 주지 않는다 — 맥스를 부를 손(3dsmax-mcp)은 클로드 쪽에만 있다."""
        return []

    def register(self, gateway: ToolGateway) -> None:
        pairs = ((ANIM_OFFSET_READ_TOOL, self.offset_read), (ANIM_OFFSET_PLAN_TOOL, self.offset_plan),
                 (specs.LIBRARY_ADD, self.library_add), (specs.LIBRARY_FIND, self.library_find), (specs.LIBRARY_TAG, self.library_tag), (specs.HABIT, self.habit),
                 (specs.LIBRARY_APPLY, self.library_apply), (specs.PARTS, self.parts),
                 (specs.POSE_SHEET, self.pose_sheet), (specs.VIDEO_TO_BIPED, self.video_to_biped),
                 (specs.FIT_CHECK, self.fit_check), (specs.FIT_FIX, self.fit_fix),
                 (specs.BLENDER_CHECK, self.blender_check), (specs.BLENDER_FIX, self.blender_fix),
                 (specs.BLENDER_BLOCK, self.blender_block))
        for tool, handler in pairs:
            spec = tool["function"]
            gateway.register(ToolSpec(
                name=spec["name"], description=str(spec["description"]), parameters=dict(spec["parameters"]),
                risk_level=RiskLevel.L0, handler=handler,
            ))

    # ── 실행 ────────────────────────────────────────────────────────────
    @property
    def root(self) -> Path:
        return Path(getattr(self.config, "documents_dir", None) or self.config.output_dir) / "animator"

    def _check(self) -> None:
        if not self.enabled():
            raise PermissionError("pack_disabled: 애니메이터 팩이 꺼져 있다 — 설정 › 팩에서 「애니메이터 팩」을 켜야 쓸 수 있다고 사람에게 말해라.")

    @staticmethod
    def _tracks(arguments: dict[str, Any]) -> list[str]:
        raw = arguments.get("tracks") or list(TRACKS)
        tracks = [str(t).strip().lower() for t in raw]
        bad = [t for t in tracks if t not in TRACKS]
        if bad:
            raise ValueError(f"tracks: 모르는 트랙 {bad} — {list(TRACKS)} 중에서")
        return tracks

    def offset_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        try:
            start, end = int(arguments["start"]), int(arguments["end"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("start · end(루프 시작 · 끝 프레임, 정수)를 줘라") from None
        if end - start < 2:
            raise ValueError("루프 구간이 너무 짧다(끝 - 시작 ≥ 2 프레임)")
        nodes = [str(n) for n in arguments.get("nodes") or [] if str(n).strip()]
        folder = self.root / time.strftime("%Y%m%d_%H%M%S")
        dump = folder / "keys.json"
        script = write_script(folder / "read.ms", read_script(dump, start, end, nodes, self._tracks(arguments)))
        return {
            "ok": True,
            "run_line": run_line(script),
            "read_file": str(dump),
            "next": "run_line 을 3dsmax-mcp execute_maxscript 로 보내고(장면은 안 바뀐다), 돌아온 「sonjari: read …」 줄을 확인한 뒤 "
                    "anim_offset_plan 을 불러라.",
            "nodes": nodes or "맥스의 현재 선택(뿌리 → 끝)",
            **({"first_time_test": {
                "run_line": run_line(test_scene),
                "when": "이 사람이 처음 쓰면, 실제 작업 장면 대신 **새 장면**에서 이 한 줄로 시험 줄(SJ_Tail01~05)을 만들어 두 걸음을 먼저 돌려 보자고 권해라.",
            }} if (test_scene := self._test_scene()) else {}),
        }

    def _test_scene(self) -> Path | None:
        pack = (getattr(self.packs, "packs", None) or {}).get(PACK_ID)
        path = Path(pack.root) / "maxscript" / "test_chain.ms" if pack is not None else None
        return path if path is not None and path.is_file() else None

    def _latest_dump(self) -> Path:
        found = sorted(self.root.glob("*/keys.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not found:
            raise FileNotFoundError("읽은 키가 없다 — anim_offset_read 의 run_line 을 맥스에서 먼저 돌려라")
        return found[0]

    def offset_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        given = str(arguments.get("read_file") or "").strip()
        dump_path = Path(given) if given else self._latest_dump()
        root = self.root.resolve()
        try:
            dump_path.resolve().relative_to(root)
        except ValueError:
            raise PermissionError(f"read_file 은 손자리 애니메이터 폴더({root}) 안의 것만 읽는다") from None
        if not dump_path.exists():
            raise FileNotFoundError(f"{dump_path} 가 없다 — 맥스에서 읽기 run_line 이 돌았는지 확인해라(돌아온 줄에 오류가 있었나)")
        dump = load_dump(dump_path)
        shifts = arguments.get("shifts")
        per_link = arguments.get("per_link")
        where = habits.situation(str(arguments.get("character") or ""), "엇박자")
        used_habit = None
        if not shifts and per_link is None and "per_link" in habits.lookup(self.root, where):
            per_link = used_habit = habits.lookup(self.root, where)["per_link"]      # 남긴 습관 — 결과에 늘 보인다
        if not shifts and per_link is None:
            raise ValueError("늦춤을 정해야 한다 — per_link(마디마다 몇 프레임) 또는 shifts 를 줘라. 모르면 사람에게 물어라.")
        plan = build_plan(dump, float(per_link or 0.0), shifts=[float(s) for s in shifts] if shifts else None,
                          whole_frames=bool(arguments.get("whole_frames", True)), tracks=self._tracks(arguments))
        folder = dump_path.parent
        items = [{"handle": tp.handle, "track": tp.track, "before": tp.before, "keys": tp.keys} for tp in plan.tracks]
        (folder / "plan.json").write_text(json.dumps({"start": plan.start, "end": plan.end, "items": items},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        result: dict[str, Any] = {
            "ok": True,
            "loop": [plan.start, plan.end],
            "preview": plan.preview(),
            "tracks_to_write": len(plan.tracks),
            "skipped": [{"node": n, "why": {"biped": "바이페드라 건너뜀", "not_found": "맥스에 그 이름이 없음"}.get(w, w)}
                        for n, w in plan.skipped],
            "no_xyz_track": plan.no_track,
            "root_unchanged": plan.unchanged,
        }
        if not plan.tracks:
            result.update(ok=False, note="쓸 트랙이 없다 — 늦춤이 모두 0 이거나 XYZ 로 나뉜 위치 · 회전 곡선이 없다.")
            return result
        script = write_script(folder / "apply.ms", apply_script(plan.start, plan.end, items))
        result.update(
            run_line=run_line(script),
            next="preview 를 사람에게 보이고 「해」를 받은 뒤에만 run_line 을 execute_maxscript 로 보내라. "
                 "돌아온 「sonjari: wrote …」 줄을 그대로 전하고, 마음에 안 들면 맥스에서 Ctrl+Z 한 번이면 통째로 되돌아간다.",
        )
        if any(tp.collisions for tp in plan.tracks):
            result["warning"] = "같은 프레임에 키 두 개가 겹쳐 하나를 버린 트랙이 있다(preview 의 「겹쳐 버린 키」) — 사람에게 말해라."
        if used_habit is not None:
            result["habits_applied"] = {"where": where, "per_link": used_habit,
                                        "note": "사람이 늦춤을 안 줘서 남긴 습관을 썼다 — 사람에게 「습관 적용: 마디당 늦춤 ○」이라고 말해라."}
        elif not shifts:
            ask = habits.record(self.root, "anim_offset_plan", where, {"per_link": per_link})
            if ask:
                result["habit_ask"] = ask
        return result

    # ── 모션 창고(v1 · 11-03) ───────────────────────────────────────────
    @staticmethod
    def _brief(e: dict[str, Any]) -> dict[str, Any]:
        out = {k: e.get(k) for k in ("id", "name", "character", "origin_label", "tags", "frames", "loop", "note")}
        if e.get("facets"):
            out["facets"] = e["facets"]
        if e.get("matched"):
            out["matched"] = e["matched"]
        out["shots"] = e.get("shots", [])[:4]
        if e.get("draft"):
            out["warning"] = "영상 변환 초안 — 블로킹 초안이지 완성 동작이 아니다(사람에게 말해라)"
        return out

    @staticmethod
    def _max_batch() -> str | None:
        found = sorted(glob.glob(r"C:\Program Files\Autodesk\3ds Max 20*\3dsmaxbatch.exe"))
        return found[-1] if found else None

    def library_add(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        source = str(arguments.get("source") or "")
        if source not in ("scene", "bip_file", "max_folder"):
            raise ValueError("source 는 scene · bip_file · max_folder 중 하나")
        common = {"origin": str(arguments.get("origin") or ""), "character": str(arguments.get("character") or ""),
                  "tags": [str(t) for t in arguments.get("tags") or []], "note": str(arguments.get("note") or "")}
        if common["origin"] not in library.ORIGINS:
            raise ValueError(f"origin 은 {list(library.ORIGINS)} 중 하나 — 이 동작이 어디서 왔는지 사람에게 물어라")
        biped = str(arguments.get("biped") or "").replace('"', "")
        if source == "scene":
            name = str(arguments.get("name") or "").strip()
            if not name:
                raise ValueError("name(동작 이름)을 줘라 — 사람이 부르는 이름으로")
            entry = library.new_entry(self.root, name=name, source="열린 맥스 장면", **common)
            script = write_script(entry["folder"] / "add.ms", library.add_scene_script(entry["folder"], biped))
            return {"ok": True, "id": entry["id"], "tags": entry["tags"], "run_line": run_line(script),
                    "next": "run_line 을 execute_maxscript 로 보내라(키는 안 바뀐다). 돌아온 「sonjari: added …」 줄을 전하면 창고에 들어간 것이다."}
        raw = str(arguments.get("path") or "").strip().strip('"')
        path = Path(raw)
        if not raw or not path.exists():
            raise FileNotFoundError(f"path 가 없다: {raw}")
        if source == "bip_file":
            files = sorted(path.glob("*.bip")) if path.is_dir() else [path]
            if not files:
                raise FileNotFoundError(f"{path} 에 .bip 가 없다")
            name = str(arguments.get("name") or "").strip()
            added = [library.import_bip(self.root, f, name=(name if len(files) == 1 else "") or f.stem, **common) for f in files]
            return {"ok": True, "added": [{"id": e["id"], "name": e["name"], "tags": e["tags"]} for e in added],
                    "note": "사진은 없다(.bip 만 받았다). 사진이 필요하면 맥스에서 입혀 본 뒤 source=scene 으로 다시 넣어라."}
        if not path.is_dir():
            raise NotADirectoryError(f"max_folder 는 폴더를 줘라: {path}")
        # 11-03 회사 폴더: 캐릭터/Animation/backup/… 처럼 깊고, backup 에 예전 판이 섞여 있다 → 하위까지 보되 예전 판 폴더는 기본으로 뺀다
        every = sorted(path.rglob("*.max"))
        old = re.compile(r"^(backup|back_up|bak|old|_old|temp|tmp|이전|백업)$", re.IGNORECASE)
        include_old = bool(arguments.get("include_backup"))
        files = [f for f in every if include_old or not any(old.match(part) for part in f.relative_to(path).parts[:-1])]
        skipped_old = len(every) - len(files)
        if not files:
            raise FileNotFoundError(f"{path} 아래에 .max 가 없다" + (f"(예전 판 폴더의 {skipped_old}개는 뺐다 — include_backup=true 로 넣을 수 있다)" if skipped_old else ""))
        # 이어 하기: 이미 창고에 들어간 파일은 건너뛰고, 지난번에 죽어 빈 칸만 남은 파일은 그 칸을 다시 쓴다(빈 칸이 쌓이지 않게)
        done: set[str] = set()
        pending: dict[str, Path] = {}
        for e in library.entries(self.root, include_pending=True):
            src = str(e.get("source") or "")
            if e.get("ready"):
                done.add(src)
            elif src:
                pending.setdefault(src, library.lib_dir(self.root) / e["id"])
        already = [f for f in files if str(f) in done]
        todo = [f for f in files if str(f) not in done]
        if not todo:
            return {"ok": True, "files": 0, "already_in_library": len(already), "skipped_backup": skipped_old,
                    "next": "이 폴더의 .max 는 이미 전부 창고에 있다. anim_library_find 로 찾아라."}
        jobs = [(f, pending.get(str(f)) or library.new_entry(self.root, name=f.stem, source=str(f), **common)["folder"]) for f in todo]
        stamp = time.strftime('%Y%m%d_%H%M%S')
        base = library.lib_dir(self.root)
        log = base / f"_batch_{stamp}_log.txt"
        exe = self._max_batch()
        size = library.BATCH_CHUNK
        scripts = []
        for n, k in enumerate(range(0, len(jobs), size), start=1):
            ms = base / f"_batch_{stamp}_{n:02d}.ms"
            write_script(ms, library.add_folder_batch_script(jobs[k:k + size], biped, log))
            scripts.append(ms)
        # 조각마다 새 맥스 — 한 조각이 죽어도 다음 조각은 돈다
        runner = base / f"_batch_{stamp}.cmd"
        runner.write_text("@echo off\r\nchcp 65001 >nul\r\n" + "".join(
            f'echo [{i}/{len(scripts)}] {ms.name}\r\n"{exe or "3dsmaxbatch.exe"}" "{ms}"\r\n' for i, ms in enumerate(scripts, start=1)),
            encoding="utf-8")
        return {"ok": True, "files": len(todo), "already_in_library": len(already), "skipped_backup": skipped_old,
                "chunks": len(scripts), "script": str(runner), "max_found": bool(exe), "log": str(log),
                "batch_command": f'"{runner}"',
                "next": (f"이 명령을 사람에게 보여 줘라. 열린 맥스와 따로 도는 맥스가 .max {len(todo)}개를 {size}개씩 {len(scripts)}번에 나눠 "
                         f"(조각마다 새 맥스) 창고에 넣는다(파일 하나에 수십 초). 중간에 멈춰도 같은 폴더로 다시 부르면 남은 것만 한다. "
                         f"파일마다 결과는 {log} — 「start」 다음 줄이 없는 파일에서 맥스가 죽은 것이다.")}

    def library_find(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        k = max(1, min(20, int(arguments.get("k") or 5)))
        found = library.find(self.root, str(arguments.get("query") or ""), k=k,
                             character=str(arguments.get("character") or ""), origin=str(arguments.get("origin") or ""))
        every = library.entries(self.root)
        total = len(every)
        models = sum(1 for e in every if e.get("kind") == "model")
        result: dict[str, Any] = {"ok": True, "library_size": total, "motions": total - models,
                                  "model_files": models, "found": [self._brief(e) for e in found]}
        if not total:
            result["note"] = "창고가 비어 있다 — anim_library_add 로 먼저 넣어라(회사 .max 폴더 · 퀵매직 .bip · 지금 장면)."
        elif not found:
            result["note"] = "맞는 것이 없다 — 다른 낱말로 다시 찾거나 query 를 비워 전체를 보여 줘라."
        query = str(arguments.get("query") or "").strip()
        if total and query:
            rep = library.query_report(self.root, query)
            if rep["read"] or not found or rep["missing_facets"]:
                result["query_report"] = rep
            if rep["missing_facets"] or (not found and rep["unknown_words"]):
                # 11-13: 아무 공격 5개를 채우지 않는다 — 무엇이 창고에 없는지 그대로 말하게
                result["note"] = (("맞는 것이 없다 — " if not found else "") + "찾는 말에서 읽은 꼬리표 중 창고에 하나도 안 붙은 것: " + (", ".join(rep["missing_facets"]) or "없음")
                                  + " · 창고 어디에도 안 맞은 낱말: " + (", ".join(rep["unknown_words"]) or "없음")
                                  + f" · 꼬리표 칸이 달린 동작 {rep['tagged_motions']}/{rep['motions']}. "
                                  "엉뚱한 동작을 내놓지 말고 이것을 사람에게 그대로 말해라. 어느 동작이 그 꼬리표인지 물어 anim_library_tag 로 달 수 있다"
                                  + (f" · 「공격 · 모션」 같은 뭉뚱그린 낱말로만 맞는 동작은 {rep['generic_only_matches']}개(원하면 그 낱말만으로 다시 찾기)."
                                     if rep["generic_only_matches"] else "."))
        return result

    def library_tag(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """꼬리표 칸(무기 · 컨셉 · 무게감 · 속도감) 달기 — 사람이 말한 것만(11-13 · 시험 중)."""
        self._check()
        # 도구 칸은 영문(weapon · concept · weight · speed) — 저장 칸은 한글. 옛 한글 칸 이름으로 와도 받는다.
        facets: dict[str, Any] = {}
        for arg, facet in FACET_ARGS.items():
            value = arguments.get(arg, arguments.get(facet))
            if isinstance(value, list):
                facets[facet] = value
        if not facets:
            raise ValueError("달 꼬리표가 없다 — weapon(무기) · concept(컨셉) · weight(무게감) · speed(속도감) 중 하나 이상을 "
                             "목록으로 줘라(빈 목록이면 그 칸을 지운다)")
        out = library.tag(self.root, str(arguments.get("id") or ""), facets, who=str(arguments.get("by") or ""))
        return {"ok": True, "status": "시험 중", **out}

    def habit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """다듬은 것 기억하기(11-13 · 시험 중): 남기기 · 묻지 않기 · 지우기 · 보기 — 사람이 말한 뒤에만."""
        self._check()
        action = str(arguments.get("action") or "list")
        if action == "list":
            return {"ok": True, **habits.listing(self.root)}
        where = str(arguments.get("where") or "").strip()
        if not where:
            raise ValueError("where 가 없다 — habit_ask 가 준 where 를 그대로 줘라")
        values = arguments.get("values") or {}
        if action == "save":
            return {"ok": True, "status": "시험 중", **habits.save(self.root, where, dict(values), by=str(arguments.get("by") or ""))}
        if action == "decline":
            return {"ok": True, **habits.decline(self.root, where, dict(values))}
        if action == "forget":
            return {"ok": True, **habits.forget(self.root, where, list(values))}
        raise ValueError("action 은 save · decline · forget · list 중 하나")

    def library_apply(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        e = library.get(self.root, str(arguments.get("id") or ""))
        if not e.get("ready"):
            raise FileNotFoundError("이 칸은 아직 .bip 가 없다(맥스 스크립트가 안 돌았거나 실패) — 넣기를 다시 해라")
        bip = Path(e["bip"])
        other = None
        blend = 0.0
        pf = library.prefs(self.root)
        # 다듬은 것 기억하기(11-13): 상황 = (입힐 캐릭터, 템플릿 목록). 사람이 안 준 손질만 남긴 습관으로 채운다 — 채운 것은 결과에 늘 보인다
        where = habits.situation(str(arguments.get("character") or arguments.get("biped") or ""),
                                 str((e.get("template") or {}).get("목록") or ""))
        mixing = bool(str(arguments.get("blend_with") or "").strip())
        given = {k: arguments.get(k) for k in ("arm_spread", "stride", "foot_lock", "bookend") if arguments.get(k) is not None}
        if mixing and arguments.get("blend") is not None:
            given["blend"] = arguments.get("blend")
        filled = {k: v for k, v in habits.lookup(self.root, where).items()
                  if k not in given and k != "per_link" and (k != "blend" or mixing)}
        arguments = {**arguments, **filled}
        if str(arguments.get("blend_with") or "").strip():
            other = library.get(self.root, str(arguments["blend_with"]).strip())
            if not other.get("ready"):
                raise FileNotFoundError("섞을 칸에 아직 .bip 가 없다 — 그 칸 넣기를 다시 해라")
            blend = max(0.0, min(float(arguments.get("blend") if arguments.get("blend") is not None else pf["blend"]), 1.0))
        bookend = pf["bookend"] if arguments.get("bookend") is None else bool(arguments.get("bookend"))
        script = write_script(bip.parent / f"apply_{time.strftime('%H%M%S')}.ms",
                              library.apply_script(bip, str(arguments.get("biped") or "").replace('"', ""), e["id"],
                                                   (e["start"], e["end"]) if "start" in e and "end" in e else None,
                                                   match_height=arguments.get("match_height", True) is not False,
                                                   stride=float(arguments.get("stride") or 1.0),
                                                   arm_spread=float(arguments.get("arm_spread") or 0.0),
                                                   blend_bip=Path(other["bip"]) if other else None, blend=blend,
                                                   blend_frames=(other["start"], other["end"]) if other and "start" in other and "end" in other else None,
                                                   bookend=bookend,
                                                   foot_lock=arguments.get("foot_lock", True) is not False))
        result = {"ok": True, "motion": self._brief(e), "run_line": run_line(script),
                  "next": "무엇을 어느 캐릭터에 입히는지 사람에게 말하고 「해」를 받은 뒤에만 run_line 을 보내라. "
                          "되돌리기는 맥스 편집 › 가져오기(Fetch)."}
        if not pf["confirmed"]:
            # 콜드 스타트: 기준점(첫 현업 애니메이터)으로 돌렸다 — 이 사람 습관은 창고 숫자를 들고 짧게 확인받는다
            ls = library.loop_share(self.root)
            result["habits_unconfirmed"] = {
                "used": {"bookend": bookend, "blend": blend if other else None},
                "library_loop_share": ls,
                "ask": ("입힌 동작의 첫 · 끝 키를 지금 이 캐릭터의 포즈로 맞춰 둘까요? 섞을 때 비율은 보통 어느 정도로 쓰세요? "
                        f"(참고: 창고 동작 {ls['motions']}개 중 {ls['looped']}개가 처음 = 끝 — 루프 판정 눈금 확인 전)" if ls["motions"] else
                        "입힌 동작의 첫 · 끝 키를 지금 이 캐릭터의 포즈로 맞춰 둘까요? 섞을 때 비율은 보통 어느 정도로 쓰세요?"),
                "save_to": str(library.prefs_path(self.root)),
                "note": "답을 들으면 save_to 파일에 JSON 으로 남겨라(bookend · blend · body_fit) — 다음부터 묻지 않는다.",
            }
        if filled:
            result["habits_applied"] = {"where": where, **filled,
                                        "note": "사람이 안 준 손질을 남긴 습관으로 채웠다 — 사람에게 「습관 적용: …」이라고 말해라(바꾸려면 그 인자를 주면 된다)."}
        ask = habits.record(self.root, "anim_library_apply", where, given)
        if ask:
            result["habit_ask"] = ask
        if other:
            result["blend"] = {"with": self._brief(other), "ratio": blend,
                               "note": f"{e['name']} 에 {other['name']} 를 {int(blend * 100)}% 섞는다(시간은 길이 비율로 맞춤 · 원래 키 자리만)."}
        if e.get("draft") or (other and other.get("draft")):
            result["warning"] = "영상 변환 초안이 섞여 있다 — 입히기 전에 사람에게 초안이라고 말해라."
        if "start" not in e or "end" not in e:
            result["range_note"] = ("이 칸은 구간 기록이 없다(.bip 만 받은 칸) — 맥스 재생 구간은 그대로 둔다. "
                                    "입힌 뒤 시간 구간(Time Configuration)을 동작 길이에 맞춰 달라고 사람에게 말해라.")
        return result

    # ── 관절 부품 · 포즈 시트 · 영상 → 바이페드(v1 · 11-03) ─────────────
    def parts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        if str(arguments.get("action") or "status") == "install":
            return parts.install(self.root, bool(arguments.get("agree")))
        st = parts.status(self.root)
        if not st["ready"]:
            st["notice"] = parts.NOTICE
            st["next"] = "부품이 없다. notice 를 사람에게 그대로 보이고, 「받아」라고 하면 action=install, agree=true."
        return {"ok": True, **st}

    def pose_sheet(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        raw = str(arguments.get("source") or "").strip().strip('"')
        if raw.lower().startswith(("http://", "https://")):
            raise ValueError("주소는 받지 않는다(영상을 내려받지 않는다) — 이 PC 의 영상 파일이나 프레임 폴더를 줘라")
        need = parts.require(self.root, ("det", "pose2d"))
        source = Path(raw)
        if not raw or not source.exists():
            raise FileNotFoundError(f"source 가 없다: {raw}")
        out = self.root / "refs" / time.strftime("%Y%m%d_%H%M%S")
        end = arguments.get("end_sec")
        n = max(2, min(16, int(arguments.get("n") or 8)))
        # 11-06: 본체 안에서 돌리면 4.6배 느리고 본체도 같이 막혔다 → 따로 된 프로세스에서(refpose.run_isolated 주석)
        info = refpose.run_isolated("sheet", {
            "source": str(source), "out": str(out), "parts": {k: str(v) for k, v in need.items()}, "n": n,
            "start_sec": float(arguments.get("start_sec") or 0.0), "end_sec": float(end) if end is not None else None,
            "stride": max(1, int(arguments.get("stride") or 1))})
        res = {"ok": bool(info.get("sheet")), "sheet_id": out.name, "sheet": info.get("sheet"), "frames": info["frames"],
               "found_person": info["found_person"], "picks": [{"no": p["no"], "sec": p["sec"]} for p in info["picks"]],
               "seconds": info["seconds"]}
        if len(info["picks"]) < n:
            res["fewer_picks"] = (f"{n}장을 달라고 했지만 {len(info['picks'])}장만 골랐다 — 몸이 멈춘 순간 중 서로 너무 가깝거나 "
                                  "자세가 비슷한 것은 뺀다. 더 원하면 stride 를 줄이거나 구간을 넓혀라.")
        return {**res,
                "next": "sheet 사진을 사람에게 보이고 쓸 장면 번호를 고르게 해라. 바이페드 블로킹을 원하면 anim_video_to_biped(poses=[…])."}

    def _sheet_dir(self, given: str) -> Path:
        base = (self.root / "refs").resolve()
        if given:
            d = (base / Path(given).name).resolve()
        else:
            found = sorted(base.glob("*/pose_sheet.json"), key=lambda p: p.stat().st_mtime, reverse=True) if base.is_dir() else []
            if not found:
                raise FileNotFoundError("포즈 시트가 없다 — anim_pose_sheet 를 먼저")
            d = found[0].parent.resolve()
        if d.parent != base or not (d / "pose_sheet.json").is_file():
            raise FileNotFoundError(f"그런 시트가 없다: {given}")
        return d

    def video_to_biped(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        d = self._sheet_dir(str(arguments.get("sheet") or "").strip())
        rep = d / "fit_report.json"
        if arguments.get("check"):
            if not rep.is_file():
                raise FileNotFoundError("맞춤 보고가 아직 없다 — run_line 이 맥스에서 돌았는지 확인해라")
            return {"ok": True, **refpose.read_fit_report(rep),
                    "note": "뼈마다 영상 방향과 얼마나 맞았나(1 = 꼭 맞음). 0.95 미만(weak)은 사람이 손볼 곳이다. "
                            "손 · 발 끝 · 머리 · 몸 위치는 맞추지 않았다 — 블로킹 초안이다."}
        need = parts.require(self.root, ("det", "pose3d"))
        sheet = json.loads((d / "pose_sheet.json").read_text(encoding="utf-8"))
        poses = refpose.run_isolated("lift", {"sheet": str(d / "pose_sheet.json"), "parts": {k: str(v) for k, v in need.items()},
                                              "use": [int(x) for x in arguments.get("poses") or []] or None})
        good = [p for p in poses if not p.get("missing")]
        if not good:
            return {"ok": False, "note": "고른 장면에서 사람을 찾지 못했다 — 다른 장면 번호를 골라라"}
        prefix = str(arguments.get("biped") or "Bip001").replace('"', "").strip() or "Bip001"
        start, spacing = int(arguments.get("start") or 0), max(1, int(arguments.get("spacing") or 10))
        # 11-05: 키 자리는 기본으로 영상 속 시각(예비 · 타격 · 회복 리듬 그대로). timing="even" 이면 spacing 간격
        secs = {p["no"]: p.get("sec") for p in sheet.get("picks", [])}
        for p in poses:
            p["sec"] = secs.get(p["no"])
        timing = str(arguments.get("timing") or "video")
        frames = refpose.key_frames(poses, start, spacing, float(arguments.get("fps") or 30), timing)
        rep.unlink(missing_ok=True)
        script = write_script(d / "to_biped.ms", refpose.biped_fit_script(poses, prefix, start, spacing, rep, frames))
        (d / "lifted.json").write_text(json.dumps(poses, ensure_ascii=False), encoding="utf-8")
        doubt = refpose.facing_report(poses)
        return {"ok": True, "sheet_id": d.name, "poses": [p["no"] for p in good],
                **({"facing_unsure": doubt} if doubt else {}),
                "missing": [p["no"] for p in poses if p.get("missing")],
                "keys_at": frames, "timing": "영상 속 시각" if timing != "even" and frames != [start + i * spacing for i in range(len(good))] else f"{spacing}프레임 간격",
                "run_line": run_line(script),
                "next": "어느 장면을 몇 프레임에 찍을지 사람에게 말하고 「해」를 받은 뒤에만 run_line 을 보내라. "
                        "돌아온 줄을 전한 뒤 check=true 로 다시 불러 맞춤 결과를 전해라. 창고에 넣으면 origin=video_draft."}

    def fit_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """입힌 뒤 뚫림 점검표(11-06 · 시험 중) — 계산은 fitcheck.py, 맥스는 읽기만."""
        from .animator import fitcheck

        self._check()
        base = self.root / "fitcheck"
        if arguments.get("check"):
            dump_path = self._fit_dump()
            out = fitcheck.check_file(dump_path)
            # 튐 점검(11-12 · 시험 중): 같은 읽기 파일로 몸통 · 허리 · 머리 · 손목의 갑작스러운 꺾임을 표로(고치기는 아직)
            if arguments.get("jitter", True) is not False:
                from .animator import jitter

                out["jitter"] = {**jitter.scan(load_dump(dump_path)),
                                 "note": "튐 점검(시험 중): 어디를 볼지 짚는 표다. 사람이 그 프레임을 재생해 진짜 튐인지 보게 해라 — "
                                         "일부러 확 꺾는 동작(타격 순간)도 걸릴 수 있다. 자동으로 고치지는 않는다."}
            return {"ok": True, "status": "시험 중", **out,
                    "note": "어디를 볼지 짚어 주는 표다. 장식은 스킨 가중치로 뺐지만(body_from) 얕은 뚫림은 놓칠 수 있다 — "
                            "숫자를 그대로 믿게 하지 말고, 사람이 그 프레임을 재생해 실제로 뚫렸는지 보게 해라."}
        folder = base / time.strftime("%Y%m%d_%H%M%S")
        dump = folder / "dump.json"
        start, end = arguments.get("start"), arguments.get("end")
        text = fitcheck.read_script(dump, int(start or 0), int(end or 0), int(start or 0), str(arguments.get("biped") or "Bip001"))
        if start is None or end is None:      # 구간을 안 주면 장면의 애니메이션 구간
            text = (text.replace("local S = 0", "local S = (animationRange.start.frame as integer)", 1)
                        .replace("local E = 0", "local E = (animationRange.end.frame as integer)", 1)
                        .replace("local R = 0", "local R = (animationRange.start.frame as integer)", 1))
        script = write_script(folder / "read.ms", text)
        return {"ok": True, "status": "시험 중", "run_line": run_line(script), "read_file": str(dump),
                "next": "run_line 을 execute_maxscript 로 보내라(장면은 안 바뀐다). 「손자리 점검 읽기: …」 줄이 오면 check=true 로 다시 불러라."}

    def _fit_dump(self) -> Path:
        base = self.root / "fitcheck"
        found = sorted(base.glob("*/dump.json"), key=lambda p: p.stat().st_mtime, reverse=True) if base.is_dir() else []
        if not found:
            raise FileNotFoundError("읽은 파일이 없다 — anim_fit_check 의 run_line 을 맥스에서 먼저 돌려라")
        return found[0]

    def fit_fix(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """뚫림 자동 수정(11-06 팔 · 11-10 다리 · 시험 중) — 계획은 fitcheck.plan_fix · plan_fix_legs, 맥스는 키 자리에서만 방향을 바꾼다."""
        from .animator import fitcheck

        self._check()
        dump_path = self._fit_dump()
        dump = load_dump(dump_path)
        plan = fitcheck.plan_fix(dump, max_deg=max(10, min(60, int(arguments.get("max_deg") or fitcheck.FIX_MAX_DEG))))
        base = self._fix_base(dump_path, dump)
        legs = (fitcheck.plan_fix_legs(dump, base=base) if arguments.get("legs", True) is not False
                else {"legs": {}, "frames_hit": {}, "unsolved": {}, "no_keys": []})
        plan["legs"] = legs["legs"]
        items = fitcheck.fix_items(plan)
        if not items:
            return {"ok": True, "status": "시험 중", "keys": 0, "note": "고칠 팔 · 다리 뚫림이 없다(가장 최근 점검 기준)."
                    + (f" 키가 없어 못 고친 뼈: {legs['no_keys']}" if legs["no_keys"] else "")}
        script = write_script(dump_path.parent / f"fix_{time.strftime('%H%M%S')}.ms",
                              fitcheck.write_fix_script(plan, str(arguments.get("biped") or "Bip001")))
        arm_degs = [r[2] for rows in plan["keys"].values() for r in rows]
        leg_degs = {b: max(r[2] for r in rows) for b, rows in plan["legs"].items()}
        out = {"ok": True, "status": "시험 중", "run_line": run_line(script), "from_check": str(dump_path),
               "keys": {**{f"{s} 위팔": len(v) for s, v in plan["keys"].items()}, **{b: len(v) for b, v in plan["legs"].items()}},
               "max_deg_used": {"팔": max(arm_degs) if arm_degs else 0, **leg_degs},
               "frames_hit": {**plan["frames_hit"], **legs["frames_hit"]}, "unsolved": {**plan["unsolved"], **legs["unsolved"]},
               "how_legs": "다리는 상체(Spine)를 뒤로 젖히거나 허벅지를 내린다 — 몸 좌우 축으로만 돌려 다리를 옆으로 벌리지 않는다. "
                           "두 발이 바닥이면 젖힘 15도까지 · 허벅지는 안 건드린다.",
               "next": f"「키 {len(items)}곳(위팔 · 허벅지 · 척추)을 max_deg_used 만큼까지 바꾼다 · Ctrl+Z 로 되돌림」을 사람에게 말하고 「해」를 받은 뒤 run_line 을 보내라. "
                       "그다음 anim_fit_check 로 다시 재서 전후를 보여라. unsolved 는 이번에 못 푸는 곳(사람 몫)."}
        if legs["no_keys"]:
            out["no_keys"] = {"bones": legs["no_keys"], "note": "이 뼈에는 키가 없어 고치지 않았다(새 키를 만들지 않는다)."}
        return out

    def _fix_base(self, dump_path: Path, dump: dict[str, Any]) -> dict[str, Any]:
        """다리 상한을 원본 대비 누적으로 걸 기준 읽기. 직전 고침(같은 뼈대 · 같은 기본 자세 · 6시간 안)의 기준을 이어받고, 없으면 이 읽기.
        고칠 때마다 fix_base.txt 에 기준 경로를 남긴다 — 「고침 → 다시 점검 → 또 고침」에서 각도가 쌓이지 않게(11-10)."""
        base_path = dump_path
        prev = sorted((p for p in (self.root / "fitcheck").glob("*/fix_base.txt") if p.parent != dump_path.parent),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if prev and time.time() - prev[0].stat().st_mtime < 6 * 3600:
            cand = Path(prev[0].read_text(encoding="utf-8").strip())
            try:
                old = load_dump(cand)
                if old.get("bones") == dump.get("bones") and old.get("fig") == dump.get("fig"):
                    base_path = cand
            except (OSError, ValueError):
                pass
        (dump_path.parent / "fix_base.txt").write_text(str(base_path), encoding="utf-8")
        return dump if base_path == dump_path else load_dump(base_path)

    # ── 블렌더(11-06) — 손자리가 창 없는 블렌더를 직접 띄운다 · 계산은 맥스와 같은 fitcheck.py ─────────────
    @staticmethod
    def _blend(arguments: dict[str, Any]) -> Path:
        raw = str(arguments.get("blend") or "").strip().strip('"')
        p = Path(raw)
        if not raw or p.suffix.lower() != ".blend" or not p.is_file():
            raise FileNotFoundError(f".blend 파일이 없다: {raw}")
        return p

    def _blender_read(self, blend: Path, arguments: dict[str, Any], work: Path) -> dict[str, Any]:
        from .animator import blender_bridge as bb, fitcheck

        dump = work / "dump.json"
        info = bb.run(blend, bb.READ_PY, {"armature": arguments.get("armature") or "", "candidates": bb.bone_candidates(),
                                          "required": bb.REQUIRED, "start": arguments.get("start"), "end": arguments.get("end"),
                                          "out": str(dump)}, work)
        data = json.loads(dump.read_text(encoding="utf-8"))
        return {"info": info, "dump": data, "check": fitcheck.check(data)}

    def blender_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check()
        blend = self._blend(arguments)
        work = self.root / "blender" / time.strftime("%Y%m%d_%H%M%S")
        got = self._blender_read(blend, arguments, work)
        out = {"ok": True, "status": "시험 중", "armature": got["info"]["armature"], "bone_map": got["dump"]["map"], **got["check"],
               "note": "어디를 볼지 짚어 주는 표다. 장식은 스킨 가중치로 뺐다(body_from.decoration). 얕은 뚫림은 놓칠 수 있다 — 사람이 재생해 확인."}
        if got["dump"].get("constrained"):
            out["constrained"] = got["dump"]["constrained"]
        # 튐 점검(11-13): 블렌더 읽기 파일도 맥스와 같은 꼴(bones · frames) — 같은 계산을 그대로 붙인다
        if arguments.get("jitter", True) is not False:
            from .animator import jitter

            out["jitter"] = {**jitter.scan(got["dump"]),
                             "note": "튐 점검(시험 중): 어디를 볼지 짚는 표다. 사람이 그 프레임을 재생해 진짜 튐인지 보게 해라 — "
                                     "일부러 확 꺾는 동작(타격 순간)도 걸릴 수 있다. 자동으로 고치지는 않는다."}
        return out

    def blender_fix(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from .animator import blender_bridge as bb, fitcheck

        self._check()
        blend = self._blend(arguments)
        passes = max(1, min(3, int(arguments.get("passes") or 3)))
        max_deg = max(10, min(60, int(arguments.get("max_deg") or fitcheck.FIX_MAX_DEG)))
        work = self.root / "blender" / time.strftime("%Y%m%d_%H%M%S")
        save = blend.with_name(f"{blend.stem}_sonjari_뚫림고침.blend")
        cur, history, base = blend, [], None
        for i in range(passes + 1):
            got = self._blender_read(cur, arguments, work / f"read{i}")
            base = base or got["dump"]                       # 다리 상한은 원본 대비 누적(여러 번 돌아도 쌓이지 않게)
            arm = sum(r["frames"] for r in got["check"]["table"] if " 팔 " in r["where"])
            leg = sum(r["frames"] for r in got["check"]["table"] if " 다리 " in r["where"])
            history.append({"pass": i, "arm_cells": arm, "leg_cells": leg, "frames_with_any_hit": got["check"]["frames_with_any_hit"]})
            fix_bones = {got["dump"]["map"].get(k) for k in ("L UpperArm", "R UpperArm", "L Thigh", "R Thigh", "Spine")}
            locked = [b for b in got["dump"].get("constrained") or [] if b in fix_bones]
            if i == 0 and locked:
                raise ValueError("이 뼈대의 고칠 뼈(위팔 · 허벅지 · 척추)에 제약(constraint)이 걸려 있다: " + ", ".join(locked)
                                 + " — 키를 써도 제약이 덮는다. 컨트롤 리그 쪽 파일로 하거나 구운(bake) 뒤에 하라고 사람에게 말해라.")
            if i == passes or arm + leg == 0:
                break
            plan = fitcheck.plan_fix(got["dump"], max_deg=max_deg)
            legs = fitcheck.plan_fix_legs(got["dump"], base=base)
            plan["legs"] = legs["legs"]
            history[-1]["unsolved"] = {**plan["unsolved"], **legs["unsolved"]}
            if legs["no_keys"]:
                history[-1]["no_keys"] = legs["no_keys"]
            items = fitcheck.fix_items(plan)
            if not items:
                break
            res = bb.run(cur, bb.WRITE_FIX_PY, {"armature": got["dump"]["armature"], "map": got["dump"]["map"],
                                                "items": items, "save": str(save)}, work / f"write{i}")
            history[-1]["keys_changed"] = res["keys"]
            cur = save
        changed = cur != blend
        return {"ok": True, "status": "시험 중", "saved": str(save) if changed else None, "original_untouched": str(blend),
                "passes": history,
                "note": ("전후 숫자를 그대로 전해라(뚫린 칸 = 팔 · 다리 × 몸 부위 × 프레임). 다리는 상체를 젖히거나 허벅지를 내려 풀었다"
                         "(옆으로 벌리지 않음). 자연스러운지는 사람이 재생해 본다. 남은 곳은 사람 몫."
                         if changed else "고칠 팔 · 다리 뚫림이 없었다 — 새 파일을 만들지 않았다.")}

    def blender_block(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from .animator import blender_bridge as bb

        self._check()
        blend = self._blend(arguments)
        d = self._sheet_dir(str(arguments.get("sheet") or "").strip())
        need = parts.require(self.root, ("det", "pose3d"))
        poses = refpose.run_isolated("lift", {"sheet": str(d / "pose_sheet.json"), "parts": {k: str(v) for k, v in need.items()},
                                              "use": [int(x) for x in arguments.get("poses") or []] or None})
        good = [p for p in poses if not p.get("missing")]
        if not good:
            return {"ok": False, "note": "고른 장면에서 사람을 찾지 못했다 — 다른 장면 번호를 골라라"}
        sheet = json.loads((d / "pose_sheet.json").read_text(encoding="utf-8"))
        secs = {p["no"]: p.get("sec") for p in sheet.get("picks", [])}
        for p in good:
            p["sec"] = secs.get(p["no"])
        start, fps = int(arguments.get("start") or 1), float(arguments.get("fps") or 30)
        frames = refpose.key_frames(good, start, 10, fps, "video")
        save = blend.with_name(f"{blend.stem}_sonjari_블로킹.blend")
        res = bb.run(blend, bb.BLOCK_PY, {"armature": arguments.get("armature") or "", "candidates": bb.bone_candidates(),
                                          "poses": good, "frames": frames, "save": str(save)},
                     self.root / "blender" / time.strftime("%Y%m%d_%H%M%S"))
        doubt = refpose.facing_report(good)
        return {"ok": True, "saved": res["saved"], "original_untouched": str(blend), "keys_at": res["frames"],
                "missing": [p["no"] for p in poses if p.get("missing")], "fit": res["fit"],
                **({"facing_unsure": doubt} if doubt else {}),
                "note": "척추 · 팔 · 다리 방향만 맞춘 블로킹 초안이다(1 = 영상 방향과 꼭 맞음 — 직접 돌려 맞췄으니 늘 1 에 가깝다, 눈금 아님). "
                        "손 · 발끝 · 머리 · 몸 위치는 사람이 다듬는다. facing_unsure 의 장면은 몸 방향이 뒤집혔을 수 있다 — 사람이 영상과 견줘 확인."}

