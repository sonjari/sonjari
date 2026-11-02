# -*- coding: utf-8 -*-
"""영상 팩 도구 — `video_read` 하나 (2026-11-02, 설계: docs/설계_영상읽기_도구_2026-11-02.ko.md · 시험 계획 7-2).

레퍼런스 영상 주소를 손자리 크롬의 **새 탭**에서 소리 끄고 2배속으로 틀며 짜임(컷 · 겹침 · 확대 · 자막 박자 · 다시 본 구간)을
읽어 표 한 장 · 사진 한 장으로 돌려준다. 모델을 쓰지 않는다. 영상은 내려받지 않는다.

지키는 것(시험 계획에서 정함)
- 브라우저 동작은 **짧게 쪼개** 일꾼에 넘긴다. 일꾼은 하나라 2분을 붙잡으면 그동안 오는 다른 브라우저 호출이 전부
  「앞 동작에 물려 있다」로 거절된다(08-16). 기다림은 일꾼 밖에서 한다.
- 영상 탭은 다른 일의 탭 정리(`_prune_tabs`)에 닫히지 않게 정리 대상(`_our_pages`)에서 빼고, 끝나면 **실패해도** 우리가 닫는다.
  작업 탭(`_page`)은 바꾸지 않는다.
- 전체 240초 마감(MCP 호출 상한 300초) — 못 본 구간은 결과에 적는다.
- 이 PC 파일은 ffmpeg 가 있을 때만(스토어 판에는 없다). 없으면 지어내지 않고 분명하게 거절한다.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

PACK_ID = "video"
#: 일꾼에 넘기는 동작 하나의 상한(초). 페이지 열기 60초가 가장 길다.
STEP_TIMEOUT = 75.0

VIDEO_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "video_read",
        "description": (
            "레퍼런스 영상의 짜임을 읽는다 — 유튜브 주소(url)면 손자리 크롬 새 탭에서 소리 끄고 2배속으로 틀며, "
            "이 PC 영상 파일(path)이면 ffmpeg 로. 컷 · 컷 길이 · 첫 3초 컷 · 겹쳐 넘기기 · 확대/축소 · 자막 박자 · "
            "시청자가 다시 본 구간을 표 한 장(table)과 대표 장면 사진 한 장(sheet.png)으로 돌려준다. 영상은 내려받지 않는다. "
            "긴 영상은 앞 60초와 다시 본 구간 몇 곳만 본다(최대 240초). 결과의 ruler_note(눈금)를 같이 전해라 — "
            "「찾았다」는 믿고 「없다」는 「못 찾았을 수 있다」. reliable 이 false 면 컷 숫자를 쓰지 마라."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "영상 페이지 주소(https://www.youtube.com/watch?v=… · shorts 도 된다)"},
                "path": {"type": "string", "description": "이 PC 의 영상 파일 절대 경로(url 대신 · ffmpeg 필요)"},
                "rate": {"type": "number", "description": "재생 배속(기본 2 · 1~2)"},
            },
        },
    },
}


def _slug(text: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(text or "")).strip("_.")
    return cleaned[:40] or "video"


class VideoTools:
    """영상 팩의 도구 묶음. 팩이 꺼져 있으면 모델 목록에도 안 끼고, 불러도 거절한다."""

    def __init__(self, config: JarvisConfig, browser: Any, packs: Any = None) -> None:
        self.config = config
        self.browser = browser
        self.packs = packs

    # ── 목록 · 등록 ─────────────────────────────────────────────────────
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return [VIDEO_READ_TOOL]

    def enabled(self) -> bool:
        return self.packs is not None and self.packs.is_enabled(PACK_ID)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        return self.ollama_tools if self.enabled() else []

    def register(self, gateway: ToolGateway) -> None:
        spec = VIDEO_READ_TOOL["function"]
        gateway.register(ToolSpec(
            name=spec["name"], description=str(spec["description"]), parameters=dict(spec["parameters"]),
            risk_level=RiskLevel.L0, handler=self.video_read,
        ))

    # ── 실행 ────────────────────────────────────────────────────────────
    def _out_dir(self, title: str) -> Path:
        base = Path(getattr(self.config, "documents_dir", None) or self.config.output_dir) / "video_read"
        return base / f"{time.strftime('%Y%m%d_%H%M%S')}_{_slug(title)}"

    def video_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled():
            raise PermissionError("pack_disabled: 영상 팩이 꺼져 있다 — 설정 › 팩에서 「영상 팩」을 켜야 쓸 수 있다고 사람에게 말해라.")
        url = str(arguments.get("url") or "").strip()
        path = str(arguments.get("path") or "").strip()
        if bool(url) == bool(path):
            raise ValueError("video_read: url(영상 주소) 또는 path(이 PC 영상 파일) 중 하나만 준다.")
        try:
            rate = float(arguments.get("rate") or 2.0)
        except (TypeError, ValueError):
            rate = 2.0
        rate = min(2.0, max(1.0, rate))
        started = time.monotonic()
        if path:
            report, out = self._read_file(path)
        else:
            if not re.match(r"^https?://", url, re.IGNORECASE):
                raise ValueError("video_read: url 은 http(s) 주소여야 한다.")
            report, out = self._read_url(url, rate)
        # 화면 묶음(frames.npz · 긴 영상이면 수십 MB)은 사람이 볼 파일이 아니다 — 내 문서에 쌓지 않고 손자리 내부 폴더로(코드 리뷰 11-02).
        frames = out / "frames.npz"
        if frames.is_file():
            keep = Path(self.config.output_dir) / "video_read_frames"
            try:
                keep.mkdir(parents=True, exist_ok=True)
                frames.replace(keep / f"{out.name}.npz")
            except OSError:
                pass
        files = [str(out / name) for name in ("table.md", "sheet.png", "report.json") if (out / name).is_file()]
        table = (out / "table.md").read_text(encoding="utf-8") if (out / "table.md").is_file() else ""
        return {
            "ok": True, "source": report.get("source"), "duration": report.get("duration"),
            "table": table, "files": files, "folder": str(out),
            "reliable": report.get("reliable"), "ruler_note": report.get("ruler_note"),
            "errors": report.get("errors") or [], "took_sec": round(time.monotonic() - started, 1),
            "instruction": "표(table)와 사진(sheet.png)이 결과다. 숫자는 표에서만 옮기고, 눈금(ruler_note)을 같이 전해라.",
        }

    def _read_file(self, path: str) -> tuple[dict[str, Any], Path]:
        from .video_read.capture import capture_file

        file = Path(path)
        if not file.is_file():
            raise FileNotFoundError(f"video_read: 파일이 없다 — {path}")
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise RuntimeError("ffmpeg_missing: 이 PC 에 ffmpeg 가 없어 영상 파일은 못 잰다(유튜브 주소는 된다). "
                               "ffmpeg 를 깔면 파일도 같은 눈금으로 잰다고 사람에게 말해라.")
        out = self._out_dir(file.stem)
        return capture_file(str(file), out), out

    def _read_url(self, url: str, rate: float) -> tuple[dict[str, Any], Path]:
        from .video_read.capture import capture_page

        browser = self.browser

        def run(function: Any) -> Any:
            # 일꾼이 다른 일의 짧은 동작으로 잠깐 바쁘면 `_submit` 은 기다리지 않고 거절한다(`browser_busy_*`).
            # 우리는 급하지 않다 — 1초 쉬고 다시 넘긴다(최대 30번). 그 밖의 오류는 그대로 올린다.
            for attempt in range(30):
                try:
                    return browser._submit(function, STEP_TIMEOUT, operation="video_read")
                except RuntimeError as exc:
                    if "browser_busy" not in str(exc) or attempt == 29:
                        raise
                    time.sleep(1.0)
            return None

        def open_tab() -> Any:
            browser._ensure_started()
            page = browser._context.new_page()
            # 다른 일의 탭 정리에 닫히지 않게 — 우리가 끝에서 닫는다.
            try:
                browser._our_pages.remove(id(page))
            except (ValueError, AttributeError):
                pass
            return page

        page = run(open_tab)
        out = self._out_dir(url)
        try:
            report = capture_page(page, url, out, rate=rate, run=run)
        finally:
            try:
                run(lambda: page.close())
            except Exception:  # noqa: BLE001 — 닫기 실패로 결과를 버리지 않는다
                pass
        title = str(report.get("source") or "")
        if title and title != url:
            better = out.with_name(out.name.split("_", 2)[0] + "_" + out.name.split("_", 2)[1] + "_" + _slug(title))
            if not better.exists():
                try:
                    out.rename(better)
                    out = better
                except OSError:
                    pass
        return report, out
