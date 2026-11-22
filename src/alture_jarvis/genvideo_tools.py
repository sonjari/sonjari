# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 OR PolyForm-Small-Business-1.0.0 (see LICENSE.md next to the gen3d / genvideo pack)
"""영상 생성 팩 도구 — gen_video_check · prep · batch · status · finish (2026-11-16 · 설계 §10-4 · §10-12).

클로드가 콘티를 짜서 `gen_video_batch` 로 맡기면 job_id 가 바로 오고, 손자리 그래픽카드가 컷 × 후보 시안(FastWan · 빠른 풀기)을
차례로 굽는다. `gen_video_status` 는 영상 본문 대신 영수증(걸린 초 · 검사 숫자 · 장면 사진 판 · 고르기 판 · 못 한 것)을 준다.
클로드가 고른 후보만 `gen_video_finish` 로 본판(Wan 정식 풀기 · 또는 사용자가 직접 받아 둔 LTX — 소리 포함).

- 팩(`genvideo`)이 꺼져 있으면 목록에도 안 끼고 불러도 거절한다(3D 팩과 같은 결).
- 그림 · 바탕 경로는 파일 도구와 **같은 검사**(`LocalComputerTools._resolve`).
- 윈도우(CUDA)만 손이 있다(`tool_gateway._PLATFORM_ONLY`) — 맥 Metal 판 sd-cli 는 아직 안 쟀다.
- 「사람이 손자리를 쓰는 중이면 기다림」: 이 기기 손자리 상태(runtime 이 꽂음) + 설정 `JARVIS_GENVIDEO_BUSY_CMD`(다른 기기 확인 명령 —
  출력에 working 이 있으면 바쁨). 우리 PC 는 맥 `/health` 를 ssh 로 읽는 줄을 넣는다(run.sh 와 같은 줄).
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import JarvisConfig
from .genvideo import commands
from .genvideo.runner import GenVideoError, VideoRunner
from .genvideo.storyboard import ASPECTS, StoryboardError, parse
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

PACK_ID = "genvideo"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

GEN_VIDEO_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_video_check",
        "description": (
            "영상 굽기 전에 이 PC 로 되나 본다(1초 안 · 그래픽카드 안 씀). 엔진마다 준비(fastwan 시안 · wan 본판 · ltx 본판-선택) · "
            "카드 · 남은 램 · 지금 사람이 손자리를 쓰는 중인지(busy) · 잰 적 있는 컷당 시간(조건과 같이)을 돌려준다. "
            "ltx 가 준비 안 됐으면 problems 의 받는 법 · 라이선스 조건을 사람에게 그대로 전한다 — 손자리는 LTX 를 받아 주지 않는다."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

GEN_VIDEO_PREP_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_video_prep",
        "description": (
            "참조 사진(제품 · 캐릭터)을 첫 그림으로 손질한다(모델 없음 · 1초 안 · 원본은 그대로). 투명 PNG 는 그대로, 가장자리가 한 색인 사진은 "
            "그 바탕을 지우고, 단색이나 바탕 그림 위 가운데에 얹어 콘티 화면비 크기로 만든다. 가장자리가 복잡하면 못 지운다고 돌려준다(cutout: none). "
            "결과 first_image 를 콘티 컷의 first_image 에 넣는다. 로고 · 글자가 화면에 남아야 하면 생성 대신 code 컷이 낫다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "참조 사진 절대 경로(png · jpg · webp)"},
                "aspect": {"type": "string", "enum": list(ASPECTS), "description": "화면비(기본 16:9 → 832×480)"},
                "background": {"type": "string", "description": "바탕: #rrggbb 색(기본 #1b1b1f) 또는 바탕 그림 절대 경로"},
                "scale": {"type": "number", "description": "물체 크기 — 화면 높이에 대한 비율 0.2~0.95(기본 0.62)"},
            },
            "required": ["image_path"],
        },
    },
}

GEN_VIDEO_BATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_video_batch",
        "description": (
            "콘티로 컷 × 후보 시안을 굽는다(FastWan 3단계 · 빠른 풀기). 바로 job_id 를 돌려주고 뒤에서 돈다 — gen_video_status 로 받는다. "
            "잰 시간: 832×480 · 3초 컷 하나 약 30~60초(RTX 3060 12GB · n=4). 사람이 손자리를 쓰는 중이면 컷마다 기다렸다 굽는다. "
            "콘티 규칙: 컷은 2~5초 · 한 컷 한 동작 · 카메라는 한 가지 · 글자 · 로고 · 앱 화면은 kind code(굽지 않음) · "
            "모양이 바뀌는 연출 · 제품은 first_image 를 준다. 한 묶음 후보 합 16 이하."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "storyboard": {
                    "type": "object",
                    "description": (
                        "{title, aspect(16:9|9:16|1:1), cuts:[{id, kind(gen|code|3d), prompt(영어 권장), seconds(2~5), "
                        "candidates(1~4 · 기본 2), seed(선택), first_image(선택 · 절대 경로), "
                        "last_image(선택 · 절대 경로 · 끝 장면을 이 그림(실물 사진 등)으로 — LTX 본판에서만 쓴다), note}]}"
                    ),
                },
            },
            "required": ["storyboard"],
        },
    },
}

GEN_VIDEO_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_video_status",
        "description": (
            "gen_video_batch · gen_video_finish 의 진행 · 영수증. running 이면 progress(컷 n/m · 단계 / 5 · 그리기 비율 · "
            "waiting_busy 면 사람이 쓰는 중이라 기다림)를 전하고 잠시 뒤 다시 부른다. done 이면 receipt 를 읽는다: "
            "files.pick_sheet(컷 × 후보 고르기 판 한 장)을 열어 보고, runs[].check(motion_mean · still_share · dark_share · jumps · 소리 dB)로 "
            "흠을 거른다 — still_share 1.0 은 정지 그림 · dark_share 높으면 너무 어둡다 · jumps 는 깨진 장면. 숫자는 영수증에서만 옮긴다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "gen_video_batch · finish 가 돌려준 job_id"}},
            "required": ["job_id"],
        },
    },
}

GEN_VIDEO_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "gen_video_finish",
        "description": (
            "기본은 고른 시안이 결과다 — 이 도구는 사람이 「더 좋게」를 원할 때만, 장면이 바뀔 수 있다고 말한 뒤 부른다(2026-11-16 대표 결정). "
            "끝난 시안 묶음에서 고른 후보만 본판으로 다시 굽는다(같은 프롬프트 · 씨앗 · 첫 그림). engine: wan(Apache · 정식 풀기 · "
            "소리 없음 · 컷당 약 370초 n=1 · 11-16 한 판은 시안과 다른 장면이 됐다 — drift 0.184) 또는 ltx(소리 포함 · 컷당 약 285~384초 n=4 · 사용자가 공식 저장소에서 직접 받아 둔 경우만). "
            "ltx 는 고른 시안의 첫 · 끝 프레임에 고정해 굽는다(anchor · 기본) — 고정이 없으면 다른 장면이 된다(11-16 n=3). "
            "콘티 컷에 last_image 를 줬으면 끝은 시안의 끝 프레임 대신 그 그림이다(ltx 만 · wan 으로 부르면 거절). "
            "영수증 runs[].drift.flag: kept(시안 장면 지킴) · drift(다른 장면 — 다시 굽거나 시안을 쓴다) · unclear(판을 본다). "
            "시안이 이미 충분하면 본판 없이 시안 파일을 그대로 써도 된다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "시안 묶음 job_id(gen_video_batch)"},
                "picks": {"type": "array", "items": {"type": "object"},
                          "description": "[{\"cut\": \"c1\", \"candidate\": 2}, …] — 1~8개"},
                "engine": {"type": "string", "enum": list(commands.FINAL_ENGINES), "description": "wan(기본) · ltx"},
                "anchor": {"type": "boolean", "description": (
                    "ltx 본판을 고른 시안의 첫 · 끝 프레임에 고정(기본 true). 11-16 실측: 고정 없으면 LTX 가 다른 장면을 그렸다(n=3) · "
                    "고정하면 시안 장면을 지켰다(n=2) — 대신 굽기 약 1.4배 · 화질 · 색감이 시안 쪽으로 끌린다")},
            },
            "required": ["job_id", "picks"],
        },
    },
}

ALL_TOOLS = [GEN_VIDEO_CHECK_TOOL, GEN_VIDEO_PREP_TOOL, GEN_VIDEO_BATCH_TOOL, GEN_VIDEO_STATUS_TOOL, GEN_VIDEO_FINISH_TOOL]


def genvideo_dirs(config: JarvisConfig) -> tuple[list[Path], list[Path], Path]:
    """(실행기 폴더들, 모델 폴더들, LTX 자리). 설정이 비면 팩이 받아 놓는 자리(`packs/genvideo/pack.json` 의 dir)."""
    data = Path(config.data_dir)
    root = Path(getattr(config, "pack_files_dir", "") or data)
    homes = [root] if root == data else [root, data]  # 「팩 파일 자리」 먼저 · 옛 자리도 본다(11-16)
    bins = [home / "tools" / PACK_ID / name for home in homes for name in ("sdcpp", "sdcpp-cudart")]
    if getattr(config, "genvideo_bin_dir", ""):
        bins = [Path(config.genvideo_bin_dir), *bins]
    models = [home / "models" / PACK_ID for home in homes]
    if getattr(config, "genvideo_models_dir", ""):
        models = [Path(config.genvideo_models_dir), *models]
    ltx = Path(getattr(config, "genvideo_ltx_dir", "") or root / "models" / PACK_ID / "ltx25")
    return bins, models, ltx


def command_probe(command: str, timeout: float = 15.0) -> Callable[[], str | None]:
    """설정 명령 한 줄 → 「working」 · 「idle」 · None(못 봄). 출력에 working 이 있으면 바쁨."""

    def probe() -> str | None:
        try:
            out = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout,  # 사람이 설정에 적은 줄
                                 creationflags=_NO_WINDOW, check=False, encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return None
        text = (out.stdout or "").strip()
        if not text:
            return None
        # `/health` JSON 을 통째로 찍었으면 state 칸만 본다 — 다른 칸의 글(이유 · 메모)에 working 이 섞여도 바쁨으로 치지 않게.
        try:
            import json

            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            state = str(data.get("state") or "").lower()
            return None if not state else ("working" if state == "working" else "idle")
        return "working" if "working" in text.lower() else "idle"

    probe.label = "다른 기기 손자리"  # type: ignore[attr-defined]
    return probe


class GenVideoTools:
    def __init__(self, config: JarvisConfig, resolve: Callable[[str], Path], packs: Any = None) -> None:
        self.config = config
        self._resolve = resolve
        self.packs = packs
        self._runner: VideoRunner | None = None
        #: runtime 이 꽂는 이 기기 손자리 상태(「working」 · 「idle」).
        self.local_state: Callable[[], str | None] | None = None
        self.publish: Callable[[str, dict[str, Any]], Any] | None = None

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(ALL_TOOLS)

    def enabled(self) -> bool:
        return self.packs is not None and self.packs.is_enabled(PACK_ID)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        return self.ollama_tools if self.enabled() else []

    def register(self, gateway: ToolGateway) -> None:
        for tool, risk, handler in (
            (GEN_VIDEO_CHECK_TOOL, RiskLevel.L0, self.gen_video_check),
            # 첫 그림: 영상 폴더 안 prep/ 새 파일(원본은 그대로).
            (GEN_VIDEO_PREP_TOOL, RiskLevel.L1, self.gen_video_prep),
            # 그래픽카드를 몇 분~몇십 분 쓰고 새 파일을 만든다(덮어쓰지 않는다).
            (GEN_VIDEO_BATCH_TOOL, RiskLevel.L1, self.gen_video_batch),
            (GEN_VIDEO_STATUS_TOOL, RiskLevel.L0, self.gen_video_status),
            (GEN_VIDEO_FINISH_TOOL, RiskLevel.L1, self.gen_video_finish),
        ):
            spec = tool["function"]
            gateway.register(ToolSpec(name=spec["name"], description=str(spec["description"]),
                                      parameters=dict(spec["parameters"]), risk_level=risk, handler=handler))

    def _local_probe(self) -> str | None:
        getter = self.local_state
        return getter() if getter is not None else None

    @property
    def runner(self) -> VideoRunner:
        if self._runner is None:
            bins, models, ltx = genvideo_dirs(self.config)
            out = Path(getattr(self.config, "documents_dir", None) or self.config.output_dir) / "genvideo"
            local = self._local_probe
            local.__func__.label = "이 기기 손자리"  # type: ignore[attr-defined]
            probes: list[Callable[[], str | None]] = [local]
            extra = str(getattr(self.config, "genvideo_busy_cmd", "") or "").strip()
            if extra:
                probes.append(command_probe(extra))
            text_models = None
            try:
                from .gen3d.swap import LocalTextModels

                text_models = LocalTextModels()
            except Exception:  # noqa: BLE001
                text_models = None
            pin = getattr(self.config, "genvideo_gpu", "")
            self._runner = VideoRunner(out, bins, models, ltx, busy_probes=probes, text_models=text_models,
                                       gpu_pin=int(pin) if str(pin).strip().isdigit() else None)
            self._runner.on_change = self._emit
        return self._runner

    def _emit(self, job_id: str) -> None:
        publish = self.publish
        if publish is None or self._runner is None:
            return
        found = self._runner.get(job_id)
        if found:
            publish("genvideo_stage", {k: v for k, v in found.items() if v is not None})

    def shutdown(self) -> None:
        if self._runner is not None:
            self._runner.shutdown()

    def _require_enabled(self) -> None:
        if not self.enabled():
            raise PermissionError("pack_disabled: 영상 생성 팩이 꺼져 있다 — 설정 › 팩에서 「영상 생성 팩」을 켜야 쓸 수 있다고 사람에게 말해라.")

    def _image(self, raw: Any, what: str = "image_path") -> Path:
        text = str(raw or "").strip()
        if not text:
            raise ValueError(f"{what} 가 비었다")
        path = self._resolve(text)
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXT:
            raise ValueError(f"그림 파일이 아니다({', '.join(sorted(IMAGE_EXT))}) — {path.name}")
        return path

    # ── 도구 ────────────────────────────────────────────────────────────
    def gen_video_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        return {"ok": True, **self.runner.check()}

    def gen_video_prep(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from .genvideo.firstframe import make_first_frame

        self._require_enabled()
        image = self._image(arguments.get("image_path"))
        aspect = str(arguments.get("aspect") or "16:9")
        if aspect not in ASPECTS:
            raise ValueError(f"aspect 는 {list(ASPECTS)} 가운데 하나")
        background = str(arguments.get("background") or "").strip() or None
        if background and not background.lstrip("#").isalnum():
            self._image(background, "background")  # 바탕 그림도 같은 경로 검사
        prep_dir = self.runner.out_root / "prep"
        index = 1
        while (prep_dir / f"{image.stem[:40]}_first_{index}.png").exists():
            index += 1
        out = prep_dir / f"{image.stem[:40]}_first_{index}.png"
        made = make_first_frame(image, out, size=ASPECTS[aspect], background=background,
                                scale=float(arguments.get("scale") or 0.62), resolve=self._resolve)
        return {"ok": True, **made}

    def gen_video_batch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        try:
            board = parse(arguments.get("storyboard"), resolve=self._resolve)
            job_id = self.runner.submit_batch(board)
        except (StoryboardError, GenVideoError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "job_id": job_id, "runs": board["runs"], "notes": board["notes"],
                "skipped_cuts": [c["id"] for c in board["cuts"] if c["kind"] != "gen"],
                "instruction": "뒤에서 돈다. gen_video_status(job_id) 로 진행 · 영수증을 받아라 — 3초 컷 하나 보통 30~60초(12GB 카드 실측)."}

    def gen_video_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        job_id = str(arguments.get("job_id") or "").strip()
        found = self.runner.get(job_id)
        if found is None:
            return {"ok": False, "error": f"not_found: {job_id}"}
        out = {"ok": True, **found}
        receipt = found.get("receipt") or {}
        if receipt.get("files"):
            out["folder"] = str(self.runner.out_root / job_id)
        return out

    def gen_video_finish(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        picks = arguments.get("picks") or []
        if isinstance(picks, dict):
            picks = [picks]
        try:
            job_id = self.runner.submit_finish(str(arguments.get("job_id") or "").strip(), list(picks),
                                               engine=str(arguments.get("engine") or "wan"),
                                               anchor=arguments.get("anchor") is not False)
        except GenVideoError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "job_id": job_id,
                "instruction": "뒤에서 돈다. gen_video_status(job_id) 로 받아라 — 본판은 컷당 5~6분 걸린다(12GB 카드 실측)."}
