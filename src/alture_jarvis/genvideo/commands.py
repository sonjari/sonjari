"""엔진마다 `sd-cli` 명령줄과 필요한 파일 (2026-11-16 · 실측 줄 그대로).

실측 줄(시험 `test_genvideo_1116.py` 가 이 줄들과 인자를 하나씩 대조한다):
- FastWan(시안) · Wan 원본 — `D:\\models\\video\\out_1116\\night\\run.sh` (11-16 04:5x · 3060 · 4프롬프트 × 2모델)
- LTX-2.5 distilled — `D:\\models\\video\\out_1116\\ltx\\run.sh` (11-16 13시 · 3060 · `--offload-to-cpu` 로 27B 를 안 내림)

엔진:
| 이름 | 쓰임 | 풀기 | 단계 · CFG | 소리 |
|---|---|---|---|---|
| fastwan | 시안(후보 여럿) | 빠른 풀기(taew2_2) | 3단계 · 1.0 | 없음 |
| wan | 본판(Apache 기본) | 정식 VAE(wan2.2_vae) | 실행기 기본 단계 · 5.0 | 없음 |
| ltx | 본판(선택 · 사용자가 공식 저장소에서 직접 받아 둔 경우만) | conv VAE + 소리 VAE | 8단계 · 1.0 | 있음 |

wan 본판의 정식 VAE 는 §10-1 의 「정식 풀기 173초」 판과 같은 파일이다. 단계 수는 run.sh 처럼 적지 않는다(실행기 기본).
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

ENGINES = ("fastwan", "wan", "ltx")
DRAFT_ENGINE = "fastwan"
FINAL_ENGINES = ("wan", "ltx")

#: Wan 원본이 권하는 반대 프롬프트(run.sh 의 NEG 그대로 · CFG 1 인 FastWan 에는 안 먹지만 실측 줄과 같게 넘긴다).
WAN_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，"
    "多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)

#: 역할 → 파일 이름 무늬(대소문자 무시). 모델 폴더 아래를 두 칸까지 찾는다(허깅페이스 include 가 하위 폴더를 남긴다).
FILE_PATTERNS: dict[str, tuple[str, ...]] = {
    "fastwan": ("FastWan2.2-TI2V-5B*.gguf",),
    "wan": ("Wan2.2-TI2V-5B*.gguf",),
    "umt5": ("umt5-xxl-encoder*.gguf",),
    "wan_vae": ("wan2.2_vae*.safetensors",),
    "tae": ("taew2_2.safetensors",),
    "ltx": ("ltx-2.5-22b-distilled*.gguf",),
    "ltx_vae": ("ltx-2.5-video-vae*.safetensors",),
    "ltx_audio_vae": ("ltx-2.5-audio-vae*.safetensors",),
    "ltx_text": ("gemma4-*ltx-2.5*.gguf", "gemma4-*ltx-2.5*.safetensors"),
}
#: 엔진마다 꼭 있어야 하는 역할.
NEEDS: dict[str, tuple[str, ...]] = {
    "fastwan": ("fastwan", "umt5", "tae"),
    "wan": ("wan", "umt5", "wan_vae"),
    "ltx": ("ltx", "ltx_vae", "ltx_audio_vae", "ltx_text"),
}
#: 엔진마다 받는 법(없을 때 영수증 · 「되나」에 그대로 싣는다).
LTX_HOW = ("LTX-2.5 는 손자리가 받아 주지 않는다 — 사용자가 허깅페이스 공식 저장소(Lightricks/LTX-2.5)에서 "
           "LTX-2.x 커뮤니티 라이선스에 직접 동의하고 받아 「{dir}」에 둔다. 조건: 연 매출 1천만 달러 이상 회사는 유료 라이선스, "
           "Lightricks 제품과 경쟁하는 용도는 따로 허락, 만든 영상은 「AI 생성」이라고 밝힌다(라이선스 첨부 A). "
           "sd-cli 가 읽는 GGUF(본체 · 글 읽기)로 바꾸는 것도 사용자 몫이다.")


def _match(name: str, patterns: tuple[str, ...]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pattern.lower()) for pattern in patterns)


def find_files(roots: list[Path], depth: int = 3) -> dict[str, Path]:
    """모델 폴더들 아래에서 역할마다 첫 파일(이름순). 못 찾은 역할은 빠진다."""
    found: dict[str, Path] = {}
    for root in roots:
        if not root or not Path(root).is_dir():
            continue
        base = Path(root)
        for current, dirs, files in os.walk(base):
            level = len(Path(current).relative_to(base).parts)
            if level >= depth:
                dirs[:] = []
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if name.endswith((".part", ".tmp")):
                    continue
                for role, patterns in FILE_PATTERNS.items():
                    if role not in found and _match(name, patterns):
                        found[role] = Path(current) / name
    return found


def missing(engine: str, files: dict[str, Path]) -> list[str]:
    return [role for role in NEEDS[engine] if role not in files]


def find_exe(bin_dirs: list[Path], name: str = "sd-cli.exe") -> Path | None:
    """실행기 자리 — 풀어 둔 zip 이 하위 폴더를 하나 더 가질 수 있어 한 칸 아래까지."""
    for bin_dir in bin_dirs:
        if not bin_dir:
            continue
        for candidate in (Path(bin_dir) / name, *sorted(Path(bin_dir).glob(f"*/{name}"))):
            if candidate.is_file():
                return candidate
    return None


#: LTX-2.5 distilled 전용 단계표(sd.cpp 이슈 #2220 신고자가 쓴 값 · 8단계). 11-16 첫 본판은 이것 없이 실행기 기본 단계표였다.
LTX_DISTILLED_SIGMAS = "1,0.99375,0.9875,0.98125,0.975,0.909375,0.725,0.421875,0"


def build(engine: str, exe: Path, files: dict[str, Path], *, prompt: str, out: Path, width: int, height: int,
          frames: int, seed: int, first_image: str | None = None, fps: int = 24,
          end_image: str | None = None, sigmas: str | None = None) -> list[str]:
    """한 컷 한 후보의 명령줄. 인자 순서까지 실측 run.sh 와 같다(끝 그림 · 단계표는 `-v` 앞에 덧붙인다).

    끝 그림(`--end-img` · 처음·끝 고정)과 단계표는 LTX 에서만 받는다 — Wan 5B 에서는 안 쟀다.
    """
    if engine not in ENGINES:
        raise ValueError(f"engine 은 {list(ENGINES)} 가운데 하나")
    if (end_image or sigmas) and engine != "ltx":
        raise ValueError("end_image · sigmas 는 ltx 에서만(Wan 에서는 안 쟀다)")
    lack = missing(engine, files)
    if lack:
        raise ValueError(f"{engine}: 모델 파일이 없다 — {', '.join(lack)}")
    cmd = [str(exe), "-M", "vid_gen"]
    image = ["-i", str(first_image)] if first_image else []
    size = ["-W", str(width), "-H", str(height), "--video-frames", str(frames), "--fps", str(fps), "--seed", str(seed)]
    if engine == "ltx":
        cmd += ["--diffusion-model", str(files["ltx"]), "--vae", str(files["ltx_vae"]),
                "--audio-vae", str(files["ltx_audio_vae"]), "--llm", str(files["ltx_text"]),
                "-p", prompt, *image, "--cfg-scale", "1.0", "--steps", "8", "--sampling-method", "euler",
                *size, "--backend", "te=cpu", "--offload-to-cpu",
                *(["--end-img", str(end_image)] if end_image else []), *(["--sigmas", sigmas] if sigmas else []),
                "-v", "-o", str(out)]
        return cmd
    if engine == "fastwan":
        model, decode, extra = files["fastwan"], ["--taesd", str(files["tae"])], ["--cfg-scale", "1.0", "--steps", "3"]
    else:
        model, decode, extra = files["wan"], ["--vae", str(files["wan_vae"])], ["--cfg-scale", "5.0"]
    cmd += ["--diffusion-model", str(model), *decode, "--t5xxl", str(files["umt5"]),
            "-p", prompt, "-n", WAN_NEGATIVE, *extra, *image, "--sampling-method", "euler", "--flow-shift", "5.0",
            *size, "--backend", "te=cpu", "--diffusion-fa", "-v", "-o", str(out)]
    return cmd


def model_block(engine: str, files: dict[str, Path]) -> dict[str, Any]:
    """영수증의 모델 칸 — 이름 · 라이선스(경로는 파일 이름만)."""
    if engine == "ltx":
        return {"engine": "ltx", "name": files.get("ltx", Path("?")).name, "license": "LTX-2.x Community License(2026-08-11) — 사용자가 직접 받음",
                "runner": "stable-diffusion.cpp sd-cli", "audio": True, "ai_disclosure_required": True}
    key = "fastwan" if engine == "fastwan" else "wan"
    return {"engine": engine, "name": files.get(key, Path("?")).name, "license": "Apache-2.0",
            "decoder": "taew2_2(빠른 풀기 · MIT)" if engine == "fastwan" else "wan2.2_vae(정식 풀기)",
            "runner": "stable-diffusion.cpp sd-cli", "audio": False}
