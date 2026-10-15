"""버릴 수 있는 상자 — 그 안에서는 코드를 돌린다.

## 왜 상자인가

`shell_probe` 는 **허용목록에 있는 실행파일만** 돌린다. 인터프리터는 영원히 안
들어온다(`test_no_interpreter_is_ever_allowed`). 그 규칙은 옳고 바뀌지 않는다 —
호스트에서 임의 코드를 돌리면 되돌릴 것이 없기 때문이다.

클라우드 에이전트가 터미널을 마음껏 쓰는 이유는 담대해서가 아니라 **버릴 수 있는
상자 안에 있기 때문이다.** 그래서 상자를 따로 판다. 되돌림이 상자 단위로 성립하면
저장소 원칙("자율은 되돌릴 수 있어서 얻는다")이 그대로 지켜진다.

## ★ 기본 WSL 은 상자가 아니었다 (2026-08-21 실측)

깔자마자 재 보니 넷이 뚫려 있었다:

    /mnt/c · /mnt/e · /mnt/f 전부 마운트   → 저장소와 .env 가 읽혔다
    자비스 control.token 이 읽혔다          → `lwjh8fJt…` 를 실제로 뽑아 봤다
    powershell.exe · cmd.exe 호출 가능      → ★ 이게 제일 나쁘다
    /init 로 interop 직접 호출 가능

세 번째가 치명적이다. 상자 안에서 `/mnt/c/WINDOWS/…/powershell.exe` 를 부를 수
있으면 **`shell_probe` 의 허용목록 설계가 그 순간 통째로 무의미해진다.** 인터프리터를
막아 온 방벽을, 상자를 연다면서 뒷문으로 열어 주는 꼴이다.

`/etc/wsl.conf` 에서 `automount` 와 `interop` 을 껐고 넷 다 막힌 것을 다시 재서
확인했다. **그 파일을 되돌리면 상자가 상자가 아니게 된다.**

## 등급이 갈리는 자리는 망이다

상자는 호스트를 못 건드리므로 계산은 되돌릴 것이 없다 → **L1**.
하지만 망은 밖으로 나가는 유일한 길이고, 나간 것은 되돌릴 수 없다 → **L2**.

그래서 기본은 `unshare -n` 으로 **망을 끊고** 돌린다. 망이 필요하면 인자로 켜되
그때는 사람 앞에 선다. 실측으로 확인했다 — 끊으면 `OSError`, 계산은 그대로 된다.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .proof import ProofSpec, same_fingerprint
from .tool_gateway import InverseSpec, RiskLevel, ToolGateway, ToolSpec

# 상자 안의 자리. `/work` 는 실행 사용자 소유(700)이고 매 판마다 하위 폴더를 판다.
_BOX_USER = "jarvisbox"
_BOX_PYTHON = "/opt/boxvenv/bin/python"
_WORK_ROOT = "/work"

#: **사람에게 줄 결과물**의 확장자. 중간 산출물(json·log·png)과 자리를 달리한다.
#
# ★ 2026-09-01 라이브. 「다른 사용자 이력서 정리해 줘」에 자비스는 `local_write_document`
#   가 아니라 `sandbox_run` 으로 python-docx 를 직접 돌렸다. 도구를 만들어도
#   **갈래가 없으면 다른 길로 샌다** — 이 저장소가 여섯 번 겪은 그 병이다.
#   그래서 결과물의 자리·미리보기·띄우기를 **만든 도구**에 붙이면 또 샌다.
#   상자에서 호스트로 건너오는 문은 `fetch()` 하나뿐이니, 여기서 잡는다.
_DELIVERABLE_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx", ".hwpx", ".hwp", ".pdf", ".csv"})

#: 미리보기로 실을 글자 수. `documents.PREVIEW_CHARS` 와 같은 눈금이다.
_PREVIEW_CHARS = 700

# ── 패키지 설치 (2026-09-30 대표 결정: 「상자는 어마무시하게 연다, 최소 헤르메스 수준」) ─────────────
#
# ★ QR 과제 실측: `qrcode` 가 없자 모델은 도구 설명의 「다른 것은 설치돼 있지 않다 · 인터넷도 끊겨 있다」를 믿고
#   설치를 포기, 외부 QR 사이트·손수 짠 스크립트로 11걸음·347초 헤맸다. 헤르메스는 터미널 `pip install` 을 승인 없이
#   하고, 없는 모듈 오류에 「venv 로 설치해 돌려라」를 붙여 준다. 우리는 상자가 진짜 격리(드라이브·interop 없음)라
#   **더 열어도 더 안전하다** — 설치는 상자 안에만 남는다.
# ★ 벽은 더 단단히: 설치는 **jarvisbox(sudo 없음)** 로, **휠만**(`--only-binary=:all:`) 받는다. root 로 설치 스크립트를
#   돌리면 악성 패키지가 `/etc/wsl.conf` 를 고쳐 드라이브 마운트를 다시 켤 수 있다 — 상자가 상자가 아니게 된다.
#   설치는 사용자 파일을 넣기 **전에** 따로 돈다. 그래서 망이 켜진 동안 상자에 사용자 데이터가 없다(L1).
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}(\[[A-Za-z0-9,._-]{1,60}\])?([<>=!~]=?[A-Za-z0-9.*+!_-]{1,40})?$")
_MAX_PACKAGES = 8
_INSTALL_TIMEOUT_SEC = 240
#: import 이름 ≠ 설치 이름. 모델이 `pip install PIL` 처럼 틀리게 부르는 것을 막는다.
_MODULE_TO_PACKAGE = {
    "PIL": "pillow", "cv2": "opencv-python-headless", "yaml": "pyyaml", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "docx": "python-docx", "pptx": "python-pptx", "fitz": "pymupdf",
    "dateutil": "python-dateutil", "Crypto": "pycryptodome", "qrcode": "qrcode[pil]", "dotenv": "python-dotenv",
    "skimage": "scikit-image", "google": "google-api-python-client",
}


#: 코드 안의 윈도우 드라이브 경로(`C:\…`·`E:/…`) — 상자(리눅스)는 이 PC 의 폴더를 볼 수 없다.
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
#: bash 가 「그런 실행 파일 없다」고 말한 이름.
_MISSING_PROGRAM = re.compile(r"(?:^|\n|: )([\w.+-]+): (?:command not found|not found)")


def _box_mismatch_hint(code: str, stderr: str) -> str:
    """상자에 시킬 수 없는 일을 시켰으면 **어디로 가라**는 한 줄. 아니면 빈 문자열.

    둘 다 오류·코드에 박혀 오는 사실로만 가른다 — 윈도우 경로가 코드에 있다 / bash 가 실행 파일이 없다고 했다.
    """
    missing = _MISSING_PROGRAM.search(stderr or "")
    if missing:
        program = missing.group(1)
        return (
            f"상자에는 `{program}` 이 없다(상자는 파이썬·bash 전용). 작업 폴더의 파일을 그 프로그램으로 돌리려면 "
            f"`local_run_project_command` 로 이 PC 에서 돌려라(예: node test.js · npm test · python 스크립트.py). "
            "상자 안에서 찾거나 설치하려고 하지 마라."
        )
    if _WINDOWS_PATH.search(code or ""):
        return (
            "상자는 격리된 리눅스라 이 PC 의 폴더(C:\\…·E:\\…)를 못 본다. 작업 폴더의 파일을 돌리거나 시험하려면 "
            "`local_run_project_command` 로 이 PC 에서 돌려라(예: node test.js · python -m pytest -q). "
            "상자에서 그 파일이 꼭 필요하면 `files` 로 넣어 주면 `in/` 에 들어온다."
        )
    return ""


def package_for_module(module: str) -> str:
    """없는 모듈 이름 → 설치할 패키지 이름."""
    top = str(module or "").split(".", 1)[0]
    return _MODULE_TO_PACKAGE.get(top, top)


def echo_last_expression(code: str) -> str:
    """파이썬 코드의 **마지막 줄이 식이면 그 값을 찍는다** — 대화형 파이썬처럼 (2026-09-24).

    라이브에서 「12, 15, 20 의 평균」을 시켰더니 모델이 `(12 + 15 + 20) / 3` 한 줄만 보냈다(세 판 모두). `print` 가
    없으니 stdout 이 **비어서** 돌아왔고, 모델은 빈 결과를 받고 암산해 15.666… 을 답했다. 근거 대조는 그 숫자를 「도구가
    준 적 없는 숫자」로 옳게 찍었다 — 틀린 건 눈금이 아니라, 계산을 시키고도 값을 못 돌려준 상자였다.

    문법이 깨졌거나, 마지막이 식이 아니거나(`print(...)` 포함, 값이 None 이면 안 찍음) 하면 코드를 그대로 둔다.
    """
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    if not tree.body or not isinstance(tree.body[-1], ast.Expr):
        return code
    last = tree.body[-1]
    if isinstance(last.value, ast.Call) and getattr(last.value.func, "id", "") == "print":
        return code
    lines = code.splitlines()
    head = "\n".join(lines[: last.lineno - 1])
    expression = ast.get_source_segment(code, last) or ""
    if not expression or last.end_lineno != len(lines):
        return code
    return (head + "\n" if head else "") + f"__value = ({expression})\nif __value is not None:\n    print(__value)\n"


def _made_by(local: Any, job_id: str) -> "set[str] | None":
    """이 판이 만든 파일의 명부(`LocalComputerTools._made_by_job`). 판 번호나 명부가 없으면 None."""
    registry = getattr(local, "_made_by_job", None) if local is not None else None
    if not job_id or not isinstance(registry, dict):
        return None
    return registry.setdefault(str(job_id), set())


def _fetch_target(target_dir: Path, name: str, run_id: str, *, keep_name: bool, made: "set[str] | None") -> Path:
    """상자에서 꺼낸 파일을 둘 자리. **이 판이 만든** 같은 이름은 덮어쓰고, 남의 것이면 실행 번호를 붙여 비켜 간다.

    ★ 2026-10-04 레딧 기준선 판(b79871c7): 상자에서 엑셀을 만들었는데 「지난 시간」 계산이 틀려(「-159분 전」) 다시
      만들었다. 그러자 방금 자기가 만든 파일을 **남의 것**으로 보고 `1889d62fdad8_이름.xlsx` 로 비켜 갔고, 문서 쓰기 손으로
      한 번 더 쓰자 `이름 (2).xlsx` 가 됐다 — 요청한 이름에는 틀린 판이 남고, 고친 판은 다른 이름 둘이 됐다. 모델은
      「이름을 바꿔 옮기겠습니다」 예고로 끝났다. 문서 쓰기에는 「이 판이 만든 것은 덮는다」 규칙이 있었는데(09-28),
      상자가 내보낸 파일은 그 명부에 안 올라가 있었다. 같은 명부를 본다.
    """
    target = target_dir / (name if keep_name else f"{run_id}_{name}")
    if target.exists():
        own = made is not None and str(target).lower() in {item.lower() for item in made}
        if not own:
            target = target_dir / f"{run_id}_{name}"
    return target


class SandboxError(RuntimeError):
    pass


def _preview_of_file(path: Path) -> str:
    """미리보기는 **한 곳에서만** 만든다 (`document_reader.preview_of_file`).

    두 곳에 적으면 갈린다 — 이 저장소가 「상한이 여러 군데」로 하루에 네 번 겪은
    그 모양이다. 화면(`/v1/outputs/preview`)과 도구 결과가 같은 글을 보여야 한다.
    """
    from .document_reader import preview_of_file

    return preview_of_file(path, chars=_PREVIEW_CHARS)


def _wrap(script: str) -> str:
    """원격 셸에 넘기는 코드는 **따옴표를 겹치지 않는다 — base64 로 감싼다.**

    이 저장소의 사고 K 가 정확히 그것이다(원격 python 의 중첩 따옴표가 깨져
    "Argument expected for the -c option" 이 났다). 표준을 그대로 재사용한다.
    """
    payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f"echo {payload} | base64 -d | bash"


def _clip(text: str, limit: int) -> tuple[str, int]:
    """길면 **줄 단위로** 자르고 몇 줄을 잘랐는지 같이 돌려준다.

    글자 중간에서 끊으면 마지막 줄이 반쪽이 돼 읽는 쪽이 오해한다. 그리고
    잘림은 침묵으로 오면 안 된다 — 몇 줄인지 말한다.
    """
    if len(text) <= limit:
        return text, 0
    lines = text.splitlines()
    kept: list[str] = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > limit:
            break
        kept.append(line)
        total += len(line) + 1
    return "\n".join(kept), len(lines) - len(kept)


#: 산출물 한 줄이 **내용을 담고 있나.** 배관 기록과 조사 결과를 가른다.
#
# ★ 2026-09-10 사슬 벤치에서 찾았다. 한 판이 37KB 워드를 내고 「상세 내용은 첨부된
#   문서에 구조화하여 담았습니다」라고 답했는데, 열어 보니 경쟁 분석이 아니라
#   자비스 내부 배관이었다 — `step/tool/ok/kind/title/payload` 여섯 칸에
#   `ui_find_target`(검색창 찾기)·`browser_fill`(검색어 넣기)이 들어 있었다.
#
#   모델이 `step_ids: [2, 5, 6]` 을 줬고 **그 셋에는 프로젝트 내용이 없었다.**
#   도구는 시킨 대로 구웠고 아무도 그게 말이 되는지 안 봤다. 옛 채점기로는
#   완벽한 통과다 — 파일 있고, 형식 맞고, 숫자를 안 지어냈다.
_ARTIFACT_TEXT_KEYS = ("text", "body", "content", "markdown", "answer", "summary")

#: 이 아래면 「본문」이라 부르지 않는다. `{"action": "filled", "url": "…"}` 같은
#  배관 기록이 대개 100자 안팎이라 200자로 둔다. 재 보고 옮길 값이다.
_ARTIFACT_MIN_BODY_CHARS = 200


def _artifact_source_result(item: Mapping[str, Any]) -> Any:
    """상자 안 `source_result` 와 **같은 것을 본다.** 여기서 다르게 보면
    「내용 있다」고 통과시킨 뒤 상자가 빈 표를 굽는다."""
    raw = item.get("raw_result_json")
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw_result": raw}
    return item.get("payload") or {}


def _artifact_step_has_substance(item: Mapping[str, Any] | None) -> bool:
    """이 걸음이 **표로 구울 만한 것**을 들고 있나.

    둘 중 하나면 그렇다:
      - 결과 어딘가에 **딕셔너리 목록**이 있다 (상자가 그걸 표의 행으로 편다)
      - 본문 글자가 `_ARTIFACT_MIN_BODY_CHARS` 이상이다

    스냅샷처럼 배관인데 딕셔너리 목록을 가진 것도 통과한다. **일부러 그렇게 둔다** —
    이 저장소가 막기로 고쳤다가 사람이 검토한 길까지 걸린 적이 있다(사고 R).
    여기서 잡으려는 것은 「아무 내용도 없는 판」 하나뿐이다.
    """
    if not item:
        return False
    result = _artifact_source_result(item)
    if isinstance(result, dict):
        for values in result.values():
            if (
                isinstance(values, list)
                and values
                and all(isinstance(value, dict) for value in values)
            ):
                return True
    seen = 0
    for source in (result if isinstance(result, dict) else {}, item.get("payload") or {}):
        if not isinstance(source, Mapping):
            continue
        for key in _ARTIFACT_TEXT_KEYS:
            value = source.get(key)
            if isinstance(value, str):
                seen = max(seen, len(value.strip()))
    return seen >= _ARTIFACT_MIN_BODY_CHARS


class SandboxBox:
    """WSL 배포판 하나를 자비스의 격리 상자로 쓴다."""

    def __init__(
        self,
        config: Any,
        events: Any = None,
        local_computer: Any = None,
        observations: Any = None,
    ) -> None:
        self.config = config
        self.events = events
        # 밖에서 안으로 파일을 넣을 때 **경로 검사**를 맡는다. 지메일 첨부가 쓰는
        # 그 검사(`resolve_allowed_path`)를 그대로 쓴다 — 두 벌을 두면 갈린다.
        self.local_computer = local_computer
        # 에이전트 장부의 200자 증거가 아니라, 걸음이 실제로 본 원문을 산출물로
        # 옮기는 길이다. 보관소를 여기 직접 꽂아야 요약의 요약을 굽지 않는다.
        self.observations = observations

    # ---- 실행 ------------------------------------------------------------
    def _exec(self, script: str, *, timeout: int) -> tuple[int, str, str]:
        """스크립트를 **표준입력으로** 넘긴다 (2026-09-30).

        ★ 예전에는 스크립트를 base64 로 감싸 **명령줄 인자**로 넘겼다(`_wrap`). 넣을 파일도 그 안에 base64 로 실렸다.
          한글 워드클라우드 과제에서 모델이 맑은 고딕(13.4MB)을 넣자 명령줄이 약 18MB — 윈도우 한도(32,767자)를 넘어
          `WinError 206` 이 났고, 파이썬은 그것을 `FileNotFoundError` 로 던졌다. 우리는 그걸 「wsl.exe 가 없다 —
          상자가 설치되지 않았다」로 옮겨 적었다. 모델은 그 거짓 이유를 믿고 상자를 버린 채 `where python` 만
          세 번 돌리며 헤맸다(57ad46ce). 모델은 옳게 했다 — 패키지도 파일도 제대로 시켰다.
          이제 명령줄엔 짧은 부트스트랩만 두고 본문은 stdin 으로 보낸다. 부트스트랩은 stdin 을 **먼저 파일로 다
          받은 뒤** stdin 을 /dev/null 로 막고 실행한다 — 상자 안 프로그램이 스크립트 나머지를 읽어 먹지 않게.
        """
        distro = str(getattr(self.config, "sandbox_distro", "Ubuntu"))
        bootstrap = 'f=$(mktemp) && cat > "$f" && bash "$f" < /dev/null; s=$?; rm -f "$f"; exit $s'
        # `--exec`: 리눅스 기본 셸을 안 거친다 — `--` 로 넘기면 그 셸이 $f·$(mktemp) 를 먼저 풀어 빈 값이 된다(실측).
        cmd = ["wsl.exe", "-d", distro, "--user", "root", "--exec", "bash", "-c", bootstrap]
        try:
            proc = subprocess.run(  # noqa: S603 - 인자는 리스트고 셸을 안 거친다
                cmd,
                input=script.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                env={"WSL_UTF8": "1", "SystemRoot": r"C:\Windows", "PATH": r"C:\Windows\System32"},
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise SandboxError(f"상자가 {timeout}초 안에 안 끝났다") from None
        except FileNotFoundError as exc:
            # 206 = 명령줄이 너무 길다. 이것까지 「wsl 없음」이라 하면 모델이 멀쩡한 상자를 버린다.
            if getattr(exc, "winerror", None) == 206:
                raise SandboxError("상자에 넘기는 명령이 너무 길다(윈도우 명령줄 한도) — 파일을 나눠 넣어라") from None
            raise SandboxError("wsl.exe 가 없다 — 상자가 설치되지 않았다") from None
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )

    def run(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        code = str(args.get("code") or "").strip()
        if not code:
            return {"ok": False, "action": "sandbox_run", "error": "돌릴 코드가 없다."}
        language = str(args.get("language") or "python").lower()
        if language not in {"python", "bash"}:
            return {
                "ok": False,
                "action": "sandbox_run",
                "error": f"'{language}' 는 못 돈다. python 또는 bash.",
            }
        allow_network = bool(args.get("allow_network"))
        timeout = int(getattr(self.config, "sandbox_timeout_sec", 60))
        if language == "python":
            code = echo_last_expression(code)

        # ── 먼저 설치한다 — 사용자 파일을 넣기 전, 따로 (2026-09-30) ──────
        installed: dict[str, Any] | None = None
        packages = [str(p).strip() for p in (args.get("packages") or []) if str(p).strip()]
        if packages:
            installed = self._install_packages(packages)
            if not installed.get("ok"):
                return {"ok": False, "action": "sandbox_run", "installed": installed,
                        "error": f"패키지 설치 실패: {installed.get('error') or installed.get('log_tail', '')[-300:]}",
                        "next": "패키지 이름이 맞는지 확인해라(import 이름과 다를 수 있다 — PIL→pillow, cv2→opencv-python-headless, "
                                "yaml→pyyaml). 휠이 없는 패키지는 상자에 못 깐다 — 표준 라이브러리나 다른 패키지로 바꿔라."}

        run_id = uuid.uuid4().hex[:12]
        work = f"{_WORK_ROOT}/{run_id}"
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        source = "main.py" if language == "python" else "main.sh"
        runner = _BOX_PYTHON if language == "python" else "bash"

        # ── 밖에서 안으로: 다뤄야 할 파일을 넣어 준다 (2026-08-23 신설) ──────
        #
        # ★ 왜 없으면 안 되나. 상자는 격리돼 있어(`windows_mounts: 0`) E:\ 를 못 본다.
        #   그런데 로컬 도구는 **읽기 전용**이다(list·read·search — 쓰기가 없다).
        #   그래서 실무의 절반이 통째로 막혀 있었다:
        #
        #       "이 엑셀 읽어서 반별 평균 내고 새 파일로 저장해줘"
        #           로컬 도구  → 읽지만 계산·저장을 못 함
        #           상자      → 계산·저장은 하는데 그 파일을 못 봄
        #
        #   나가는 길(`saved_to`)은 진작 있었는데 **들어오는 길만 없었다.**
        #
        # ★ 격리는 그대로 지킨다. 드라이브를 마운트하지 않고 **고른 파일만 복사**한다.
        #   경로 검증은 `local_computer.resolve_allowed_path` 를 그대로 쓴다 — 지메일
        #   첨부가 쓰는 그 검사다. 두 벌을 두면 갈리고, 갈린 쪽이 구멍이 된다.
        staged: list[str] = []
        stage_cmds: list[str] = []
        raw_inputs = list(args.get("files") or [])
        if raw_inputs:
            local = getattr(self, "local_computer", None)
            if local is None:
                return {
                    "ok": False,
                    "action": "sandbox_run",
                    "error": "파일을 넣을 수 없다 — 경로 검사기가 없다.",
                }
            max_bytes = int(getattr(self.config, "sandbox_input_max_bytes", 32 * 1024 * 1024))
            total = 0
            for raw in raw_inputs[:10]:
                try:
                    path = local.resolve_allowed_path(str(raw))
                except Exception as exc:  # noqa: BLE001 — 거절 사유를 그대로 돌려준다
                    return {"ok": False, "action": "sandbox_run", "error": str(exc)[:200]}
                if not path.is_file():
                    return {
                        "ok": False,
                        "action": "sandbox_run",
                        "error": f"파일이 아니다: {path.name}",
                    }
                total += path.stat().st_size
                if total > max_bytes:
                    return {
                        "ok": False,
                        "action": "sandbox_run",
                        "error": f"넣으려는 파일이 너무 크다(합계 {total:,}바이트).",
                    }
                blob = base64.b64encode(path.read_bytes()).decode("ascii")
                safe = path.name.replace("'", "").replace('"', "")
                stage_cmds.append(f"echo {blob} | base64 -d > {work}/in/{safe}")
                staged.append(safe)
        # 망을 끊는 것은 root 가 하고, 그 안에서 실행 사용자로 내려간다.
        # 실측으로 확인한 순서다 — 반대로 하면 권한이 모자라 unshare 가 실패한다.
        isolate = "" if allow_network else "unshare -n --"
        stage_block = ("\n".join(stage_cmds) + "\n") if stage_cmds else ""
        script = f"""
set -u
install -d -o {_BOX_USER} -g {_BOX_USER} -m 700 {work} {work}/out {work}/in
echo {encoded} | base64 -d > {work}/{source}
{stage_block}chown -R {_BOX_USER}:{_BOX_USER} {work}
cd {work}
set +e
{isolate} sudo -u {_BOX_USER} --preserve-env=HOME env HOME={work} {runner} {work}/{source}
run_status=$?
# 모델이 안내대로 out/에 저장하는 것이 정석이다. 다만 실측에서는
# ``to_excel('파일.xlsx')``처럼 작업 루트에 바로 쓰고도 생성했다고 답했다.
# 실행 전부터 있던 source/in/out은 제외하고, 성공한 실행이 루트에 새로 만든
# 일반 파일만 결정론적으로 out/으로 옮겨 자동 반출 사다리를 끊지 않는다.
if [ "$run_status" -eq 0 ]; then
  find {work} -maxdepth 1 -type f ! -name {source} -exec mv -- {{}} {work}/out/ \\;
fi
exit "$run_status"
"""
        started = time.time()
        try:
            rc, out, err = self._exec(script, timeout=timeout)
        except SandboxError as exc:
            return {
                "ok": False,
                "action": "sandbox_run",
                "error": str(exc),
                "network": allow_network,
            }
        elapsed = round(time.time() - started, 2)

        limit = int(getattr(self.config, "sandbox_output_max_chars", 8000))
        stdout, out_clipped = _clip(out, limit)
        stderr, err_clipped = _clip(err, limit // 2)
        produced = self._list_outputs(work)

        # ★ 만든 파일은 **자동으로 꺼내 온다.**
        #
        # 처음엔 `sandbox_fetch` 를 따로 부르게 두고 도구 설명에 "out/ 에 저장하고
        # sandbox_fetch 로 가져온다"고 적어 뒀다. 라이브에서 자비스는 파일을 만들고
        # **fetch 를 안 불렀다.** 그리고 "파일 생성이 완료되었습니다"라고 답했다 —
        # 파일은 상자 안에만 있고 사용자 손에는 아무것도 없었다.
        #
        # 안내문은 안 먹는다(사고 R). 결정론으로 박을 수 있으면 코드로 옮긴다.
        # `sandbox_fetch` 는 다시 꺼낼 때를 위해 남겨 둔다.
        delivered: list[dict[str, Any]] = []
        if rc == 0:
            for item in produced:
                got = self.fetch(
                    {
                        "run_id": run_id,
                        "name": item["name"],
                        "__job_id": str(args.get("__job_id") or ""),
                    }
                )
                if got.get("ok"):
                    entry = {"name": item["name"], "path": got["path"], "bytes": got["bytes"]}
                    for key in ("delivered_to_request", "renamed_because_exists", "delivery_error"):
                        if got.get(key):
                            entry[key] = got[key]
                    if got.get("deliverable"):
                        entry["deliverable"] = True
                        preview = _preview_of_file(Path(got["path"]))
                        if preview:
                            entry["preview"] = preview
                    delivered.append(entry)
            # ★ 만들었으면 띄워 주되 **판이 끝난 뒤에** 띄운다.
            #
            #   처음엔 여기서 바로 `os.startfile` 을 불렀다. 두 가지가 났다:
            #     ① 한글·엑셀이 그 파일을 붙잡아 다음 걸음이 Access Denied 로 죽는다
            #        (`local_computer.write_document_file` 에서 겪은 그대로다)
            #     ② **검사가 엑셀을 띄웠다.** 라이브 상자 검사가 `성적표.csv` 를
            #        만들자마자 엑셀이 뜨면서 회귀가 통째로 멎었다.
            #
            #   그래서 `local_computer` 와 **같은 규칙**을 쓴다: 적어만 두고
            #   런타임이 판 끝에 연다. 잡이 없으면(검사·MCP 직접 호출) 안 띄운다 —
            #   그 자리에는 띄워 줄 사람이 없고, 경로는 결과에 이미 들어 있다.
            local = self.local_computer
            job_id = str(args.get("__job_id") or "")
            if args.get("open", True) and job_id and local is not None:
                for entry in delivered:
                    if not entry.get("deliverable"):
                        continue
                    local.remember_to_open(job_id, Path(entry["path"]))
                    entry["opened"] = "deferred"
                    break

        result = {
            # ★ 종료코드가 0 이 아니면 실패다. 예외가 없다고 성공이 아니다 —
            #   이 저장소는 "도구가 예외 없음을 성공으로 반환"해서 한 번 속았다.
            "ok": rc == 0,
            "action": "sandbox_run",
            "run_id": run_id,
            "language": language,
            "exit_code": rc,
            "elapsed_sec": elapsed,
            "network": allow_network,
            "stdout": stdout,
            "stderr": stderr,
            "outputs": produced,
            # 이 PC 의 실제 경로. 답할 때 이 값을 그대로 말하면 된다.
            "saved_to": delivered,
        }
        if staged:
            # ★ 무엇을 받았는지 **말해 준다.** 안 그러면 모델이 `in/` 에 뭐가 있는지
            #   몰라 파일 이름을 지어낸다 — 이 저장소가 아는 그 병이다.
            result["staged_in"] = staged
            result["instruction"] = (
                f"넣어 준 파일 {len(staged)}개는 `in/` 안에 있다: "
                + ", ".join(f"in/{name}" for name in staged)
                + ". 코드에서 그 경로로 열어라. 만든 것은 `out/` 에 저장하면 "
                "밖으로 나온다(saved_to 에 실제 경로가 온다)."
            )
        if out_clipped or err_clipped:
            result["clipped_lines"] = {"stdout": out_clipped, "stderr": err_clipped}
        if installed is not None:
            result["installed"] = installed
        # ★ 없는 모듈이면 **다음 걸음을 박아 준다**(헤르메스 방식, 사고 R: 안내문보다 결과에 붙은 한 줄).
        missing = re.search(r"(?:ModuleNotFoundError|ImportError): No module named '?([\w.]+)", err or "")
        if rc != 0 and missing:
            package = package_for_module(missing.group(1))
            # ★ 2026-09-30 대표: 「패키지 설치는 우선적으로 해야 하는 거 아니가 — 헤르메스는 그렇게 하더라」.
            #   안내 한 줄만 붙이면 모델이 한 걸음 더 써야 하고, 안 따르면 헤맨다(사고 R: 안내문은 안 먹는다).
            #   없는 모듈은 오류 문구에 이름이 박혀 오는 **구조적 사실**이다 — 도구가 깔고 같은 코드를 **한 번** 다시 돌린다.
            #   이미 이 판에서 자동으로 깐 것이면 되풀이하지 않는다(무한 고리 방지). 깔기 실패면 예전처럼 안내만 남긴다.
            already = [str(p) for p in args.get("_auto_installed") or []]
            if package not in already and package not in packages:
                auto = self._install_packages([package])
                if auto.get("ok"):
                    again = self.run({**args, "packages": [], "_auto_installed": [*already, package]})
                    again["auto_installed"] = [*already, package]
                    again.setdefault(
                        "note", f"상자에 없던 '{missing.group(1)}' 를 도구가 깔고({package}) 같은 코드를 다시 돌렸다."
                    )
                    return again
                result["auto_install_failed"] = {k: auto.get(k) for k in ("error", "log_tail") if auto.get(k)}
            result["next"] = (
                f"상자에 '{missing.group(1)}' 가 없다. 포기하거나 다른 길로 돌지 말고 **같은 코드를 "
                f"packages=[\"{package}\"] 로 다시 불러라** — 도구가 상자에 설치한 뒤 돌린다(승인 필요 없음, 다음 판에도 남는다)."
            )
        # ★ 상자가 **할 수 없는 일**을 시켰으면 날 오류 대신 갈 곳을 댄다 (2026-09-30 코드 벤치).
        #   「node 로 test.js 를 돌려 통과시켜」에 모델이 상자 안에서 `cd "C:\Users\…" && node test.js` 를 돌렸고, 상자는
        #   리눅스 오류(「cd: C:\Users\… No such file or directory」)만 돌려줬다 — 모델은 node 를 찾아 네 걸음을 헤맸다.
        #   도구 오류 문구가 원인을 가리지 않으면 모델은 같은 벽을 두드린다(메모 a_wrong_error_message…). 낱말이 아니라
        #   **사실**로 가른다: 코드에 윈도우 경로가 있다(상자는 이 PC 를 못 본다) · 상자에 없는 실행 파일을 불렀다.
        if rc != 0 and not result.get("next"):
            hint = _box_mismatch_hint(code, err or "")
            if hint:
                result["next"] = hint
        if self.events is not None:
            self.events.publish(
                "sandbox_run",
                {
                    "run_id": run_id,
                    "language": language,
                    "exit_code": rc,
                    "elapsed_sec": elapsed,
                    "network": allow_network,
                    "outputs": len(produced),
                },
            )
        return result

    def _install_packages(self, packages: list[str]) -> dict[str, Any]:
        """상자 venv 에 패키지를 깐다 — jarvisbox(sudo 없음)로, 휠만, 망은 이때만 켠다.

        상자 venv(`/opt/boxvenv`)는 jarvisbox 소유라 root 가 필요 없다. 깐 것은 다음 판에도 남는다.
        """
        if len(packages) > _MAX_PACKAGES:
            return {"ok": False, "packages": packages, "error": f"한 번에 {_MAX_PACKAGES}개까지만 깐다."}
        bad = [p for p in packages if not _PACKAGE_RE.match(p)]
        if bad:
            return {"ok": False, "packages": packages, "error": f"패키지 이름이 이상하다: {', '.join(bad)}"}
        quoted = " ".join(shlex.quote(p) for p in packages)
        script = f"""
set -u
out=$(sudo -u {_BOX_USER} env HOME=/tmp/boxpip PIP_CACHE_DIR=/tmp/boxpip/cache timeout {_INSTALL_TIMEOUT_SEC} \\
  {_BOX_PYTHON} -m pip install --disable-pip-version-check --no-input --only-binary=:all: --quiet {quoted} 2>&1)
status=$?
printf '%s\\n' "$out" | tail -n 15
exit $status
"""
        started = time.time()
        try:
            rc, out, err = self._exec(script, timeout=_INSTALL_TIMEOUT_SEC + 30)
        except SandboxError as exc:
            return {"ok": False, "packages": packages, "error": str(exc)}
        tail = ((out or "") + (err or "")).strip()[-1200:]
        return {"ok": rc == 0, "packages": packages, "elapsed_sec": round(time.time() - started, 1),
                "log_tail": tail, **({} if rc == 0 else {"error": tail[-300:] or f"exit {rc}"})}

    def _list_outputs(self, work: str) -> list[dict[str, Any]]:
        """`out/` 에 남긴 파일 목록.

        ★ 이름을 **base64 로 받는다.** 처음엔 `find -printf '%p'` 로 날것을
        받았는데, 한글 파일명이 파이썬 디코딩 경로에서 깨져
        `'\\udcec…\\udced….csv'` 로 돌아왔다. 그러면 `sandbox_fetch` 가 그 이름으로
        파일을 못 찾는다 — 만들어 놓고 못 꺼내는 것이다(2026-08-21 실측).

        WSL 쪽 출력은 멀쩡했으므로 상자를 고칠 일이 아니라 **경계를 건너는 방식**을
        바꿀 일이었다. base64 면 이 부류가 통째로 사라진다.
        """
        try:
            rc, out, _ = self._exec(
                f"cd {work}/out 2>/dev/null || exit 0; "
                f"for f in *; do [ -f \"$f\" ] || continue; "
                f"printf '%s\\t%s\\n' \"$(printf '%s' \"$f\" | base64 -w0)\" "
                f"\"$(stat -c %s \"$f\")\"; done | head -50",
                timeout=20,
            )
        except SandboxError:
            return []
        files: list[dict[str, Any]] = []
        if rc != 0:
            return files
        for line in out.splitlines():
            if "\t" not in line:
                continue
            encoded, _, size = line.partition("\t")
            try:
                name = base64.b64decode(encoded.strip()).decode("utf-8")
            except Exception:
                continue
            files.append({"name": name, "bytes": int(size.strip() or 0)})
        return files

    def fetch(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """상자가 만든 파일을 호스트로 꺼낸다.

        상자에서 윈도우 파일시스템이 안 보이므로(그게 격리의 핵심이다) 파일은
        **base64 로 표준출력을 타고** 나온다. 나가는 자리는 자비스 outputs 폴더
        하나로 고정한다 — 상자가 경로를 정하게 하면 격리가 의미를 잃는다.
        """
        args = arguments or {}
        run_id = str(args.get("run_id") or "").strip()
        name = str(args.get("name") or "").strip()
        if not run_id.isalnum() or not name:
            return {"ok": False, "action": "sandbox_fetch", "error": "run_id 와 name 이 필요하다."}
        if "/" in name or "\\" in name or ".." in name:
            return {"ok": False, "action": "sandbox_fetch", "error": "파일 이름만 준다."}
        max_bytes = int(getattr(self.config, "sandbox_fetch_max_bytes", 8_000_000))
        # 이름도 base64 로 **넣는다.** 한글·공백·따옴표가 섞여도 명령줄에서 안 깨진다.
        encoded_name = base64.b64encode(name.encode("utf-8")).decode("ascii")
        try:
            rc, out, err = self._exec(
                f"n=$(echo {encoded_name} | base64 -d); "
                f"f={_WORK_ROOT}/{run_id}/out/$n; "
                f"[ -f \"$f\" ] || {{ echo MISSING >&2; exit 3; }}; "
                f"s=$(stat -c %s \"$f\"); "
                f"[ \"$s\" -le {max_bytes} ] || {{ echo TOOBIG >&2; exit 4; }}; "
                f"base64 -w0 \"$f\"",
                timeout=int(getattr(self.config, "sandbox_timeout_sec", 60)),
            )
        except SandboxError as exc:
            return {"ok": False, "action": "sandbox_fetch", "error": str(exc)}
        if rc != 0:
            reason = "파일이 없다" if "MISSING" in err else "파일이 너무 크다" if "TOOBIG" in err else err[:200]
            return {"ok": False, "action": "sandbox_fetch", "error": reason}
        try:
            blob = base64.b64decode(out.strip())
        except Exception:
            return {"ok": False, "action": "sandbox_fetch", "error": "내용을 읽지 못했다."}
        job_id = str(args.get("__job_id") or "").strip()
        local = self.local_computer
        # ★ 사람이 자리와 이름을 **둘 다** 댔고 같은 이름이 나왔으면 거기로 보낸다 (2026-09-30, `expect_delivery` 주석).
        #   못 보내면(쓰기 범위 밖 등) 아래 원래 자리로 가고 **왜 못 보냈는지** 결과에 남긴다 — 모델이 사람에게 말할 수 있게.
        delivery_error = ""
        wanted = local.delivery_for(job_id, name) if (job_id and local is not None) else None
        if wanted is not None:
            try:
                done = local.deliver_bytes(job_id, wanted, blob)
                return {
                    "ok": True,
                    "action": "sandbox_fetch",
                    "path": str(done["path"]),
                    "bytes": len(blob),
                    "deliverable": Path(name).suffix.lower() in _DELIVERABLE_SUFFIXES,
                    "delivered_to_request": True,
                    **({"renamed_because_exists": done["renamed_because_exists"]}
                       if done.get("renamed_because_exists") else {}),
                }
            except (PermissionError, OSError, ValueError) as exc:
                delivery_error = f"{type(exc).__name__}: {exc}"[:300]
        # ★ **결과물은 나온 파일의 종류로 자리를 정한다** (2026-09-01).
        #
        #   잡별 UUID 폴더는 중간 산출물에는 맞다 — 판이 끝나면 치울 것들이니까.
        #   그런데 사람이 달라고 한 문서가 거기 떨어지면 탐색기에서 찾을 길이 없다.
        #   실제로 이력서 docx 를 37,808바이트로 제대로 만들어 놓고
        #   `outputs/workspace/e30e5408-…/다른 사용자_이력서_수정제안본.docx` 에 두었다.
        #   **만든 것을 사람이 못 찾으면 안 만든 것과 같다.**
        deliverable = Path(name).suffix.lower() in _DELIVERABLE_SUFFIXES
        docs_root = getattr(local, "documents_root", None) if local is not None else None
        if deliverable and docs_root is not None:
            target_dir = docs_root
        elif job_id and local is not None:
            target_dir = local.job_workspace(job_id, create=True)
        else:
            target_dir = Path(getattr(self.config, "sandbox_output_dir"))
        target_dir.mkdir(parents=True, exist_ok=True)
        # 잡 작업폴더는 그 잡만 쓰므로 사람이 요청한 이름을 그대로 보존한다.
        # 옛 공용 sandbox 폴더만 충돌 방지를 위해 run_id 접두사를 유지한다.
        target = _fetch_target(target_dir, name, run_id, keep_name=bool(job_id or deliverable),
                               made=_made_by(local, job_id))
        target.write_bytes(blob)
        made = _made_by(local, job_id)
        if made is not None:
            made.add(str(target))
        return {
            "ok": True,
            "action": "sandbox_fetch",
            "path": str(target),
            "bytes": len(blob),
            "deliverable": deliverable,
            **({"delivery_error": f"달라고 한 자리({wanted})에 못 보냈다 — {delivery_error}"} if delivery_error else {}),
        }

    def reset(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """작업 자리를 통째로 비운다. **버릴 수 있다는 것이 이 상자의 존재 이유다.**"""
        try:
            rc, _, err = self._exec(
                f"rm -rf {_WORK_ROOT}/* && install -d -o {_BOX_USER} -g {_BOX_USER} "
                f"-m 700 {_WORK_ROOT} && echo cleared",
                timeout=60,
            )
        except SandboxError as exc:
            return {"ok": False, "action": "sandbox_reset", "error": str(exc)}
        return {"ok": rc == 0, "action": "sandbox_reset", "error": err[:200] if rc else ""}

    # ---- 관측 원문 → 산출물 ---------------------------------------------
    _ARTIFACT_SUFFIXES = {
        "csv": ".csv",
        "xlsx": ".xlsx",
        "docx": ".docx",
        "json": ".json",
        "md": ".md",
    }

    def _artifact_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """확장자까지 포함한 실제 대상을 승인·증명·실행이 똑같이 보게 한다."""
        out = dict(arguments)
        format_name = str(out.get("format") or "").lower().strip()
        if format_name == "markdown":
            format_name = "md"
        suffix = self._ARTIFACT_SUFFIXES.get(format_name)
        if suffix is None:
            raise ValueError("unsupported_artifact_format")
        raw_path = str(out.get("path") or "").strip()
        if not raw_path:
            raise ValueError("path_required")
        path = Path(raw_path)
        if path.suffix:
            if path.suffix.lower() != suffix:
                raise ValueError(f"path_extension_mismatch:{suffix}")
        else:
            out["path"] = raw_path + suffix
        out["format"] = format_name
        return out

    def _artifact_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        local = self.local_computer
        if local is None:
            return RiskLevel.L2
        try:
            return local._mutation_risk(self._artifact_arguments(arguments))
        except Exception:
            return RiskLevel.L2

    def _artifact_proof(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.local_computer is None:
            raise RuntimeError("local_file_writer_unavailable")
        return self.local_computer._capture_file_proof(self._artifact_arguments(arguments))

    def _run_undo_handle(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """상자가 이번 판에 새로 꺼낸 파일들만 되돌리기 대상으로 묶는다."""
        local = self.local_computer
        if local is None or result.get("ok") is not True:
            return None
        files: list[dict[str, Any]] = []
        for item in result.get("saved_to") or []:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            try:
                path = local.resolve_allowed_path(str(item["path"]))
                state = local._file_state(path)
            except Exception:
                return None
            if not state["exists"]:
                return None
            files.append({"path": str(path), "sha256": state["sha256"]})
        return {"files": files} if files else None

    def _undo_run_outputs(self, handle: dict[str, Any]) -> dict[str, Any]:
        local = self.local_computer
        if local is None:
            raise RuntimeError("local_file_writer_unavailable")
        checked: list[Path] = []
        for item in handle.get("files") or []:
            path = local.resolve_allowed_path(str(item.get("path") or ""))
            state = local._file_state(path)
            if not state["exists"] or state["sha256"] != str(item.get("sha256") or ""):
                raise RuntimeError("undo_target_drifted")
            checked.append(path)
        for path in checked:
            path.unlink()
        return {"paths": [str(path) for path in checked], "verified": all(not p.exists() for p in checked)}

    def artifact_from_observations(
        self, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """보관소의 원문을 상자에 넣어 사람이 열 수 있는 파일로 굽는다."""
        args = self._artifact_arguments(arguments or {})
        local = self.local_computer
        observations = self.observations
        if local is None or observations is None:
            raise RuntimeError("artifact_pipeline_unavailable")
        job_id = str(args.get("__job_id") or "").strip()
        workspace = local.job_workspace(job_id, create=True)
        raw_steps = args.get("step_ids")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("step_ids_required")
        step_ids: list[int] = []
        for raw in raw_steps[:50]:
            step = int(raw)
            if step <= 0:
                raise ValueError("invalid_step_id")
            if step not in step_ids:
                step_ids.append(step)
        rows: list[dict[str, Any]] = []
        missing: list[int] = []
        getter = getattr(observations, "get_for_artifact", observations.get)
        for step in step_ids:
            item = getter(job_id, step)
            if item is None:
                missing.append(step)
            else:
                rows.append(item)
        if missing:
            raise ValueError("observation_steps_missing:" + ",".join(map(str, missing)))
        # ★ 고른 걸음에 **내용이 하나도 없으면 굽지 않는다** (2026-09-10).
        #
        #   막기만 하지 않고 **내용이 있는 걸음 번호를 같이 알려 준다.** 이 저장소가
        #   막기로만 고쳤다가 사람이 검토한 레시피까지 걸린 적이 있다(사고 R).
        #   모델은 이 말을 받고 번호를 바꿔 다시 부르면 된다.
        if not any(_artifact_step_has_substance(row) for row in rows):
            usable = [
                int(row.get("step") or 0)
                for row in (observations.list_steps(job_id) or [])
                if int(row.get("step") or 0) not in step_ids
                and _artifact_step_has_substance(getter(job_id, int(row.get("step") or 0)))
            ]
            hint = (
                "내용이 있는 걸음은 " + ", ".join(map(str, usable[:12])) + " 이다."
                if usable
                else "이 판에는 아직 내용을 담은 걸음이 없다 — 먼저 읽어 와라."
            )
            raise ValueError(
                "고른 걸음("
                + ", ".join(map(str, step_ids))
                + ")에 표로 구울 내용이 없다. 그대로 만들면 도구 호출 기록만 담긴 "
                "빈 문서가 나온다. " + hint
            )

        staging = workspace / f".jarvis-observations-{uuid.uuid4().hex[:12]}.json"
        local._atomic_write(
            staging,
            json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        )
        output_name = Path(str(args["path"])).name
        format_name = str(args["format"])
        # 코드는 고정이고 입력·형식·이름만 JSON 리터럴로 넣는다. 원문을 코드에
        # 보간하지 않으므로 관측값 안의 따옴표나 명령문이 실행될 자리가 없다.
        code = f'''import csv
import json
from pathlib import Path

source = Path("in/{staging.name}")
items = json.loads(source.read_text(encoding="utf-8"))
format_name = {json.dumps(format_name)}
target = Path("out") / {json.dumps(output_name, ensure_ascii=False)}

def scalar(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value

def source_result(item):
    raw = item.get("raw_result_json")
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {{"raw_result": raw, "truncated": True}}
    return item.get("payload", {{}})

def expand(item):
    base = {{
        "step": item.get("step", ""),
        "tool": item.get("tool", ""),
        "ok": item.get("ok", False),
        "kind": item.get("kind", ""),
        "title": item.get("title", ""),
    }}
    result = source_result(item)
    if isinstance(result, dict):
        known = ["rows", "results", "candidates", "records", "items"]
        keys = known + [key for key in result if key not in known]
        for key in keys:
            values = result.get(key)
            if isinstance(values, list) and values and all(isinstance(value, dict) for value in values):
                return [{{**base, **{{str(k): scalar(v) for k, v in value.items()}}}} for value in values]
    return [{{**base, "payload": json.dumps(result, ensure_ascii=False, default=str)}}]

rows = [row for item in items for row in expand(item)]
headers = []
for row in rows:
    for key in row:
        if key not in headers:
            headers.append(key)
if format_name == "csv":
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
elif format_name == "xlsx":
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "observations"
    sheet.append(headers)
    for row in rows:
        sheet.append([str(row.get(key, ""))[:32000] for key in headers])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        sheet.column_dimensions[cell.column_letter].width = 24
    book.save(target)
elif format_name == "docx":
    from docx import Document
    document = Document()
    document.add_heading("손자리 작업 근거", level=0)
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for row in rows:
        cells = table.add_row().cells
        for index, header in enumerate(headers):
            cells[index].text = str(row.get(header, ""))[:32000]
    document.save(target)
elif format_name == "json":
    target.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
else:
    chunks = ["# 손자리 작업 근거"]
    for item in items:
        chunks.extend([
            f"## {{item.get('step', '')}}. {{item.get('title') or item.get('tool', '')}}",
            f"- 도구: `{{item.get('tool', '')}}`",
            f"- 종류: `{{item.get('kind', '')}}`",
            "```json",
            item.get("raw_result_json") or json.dumps(item.get("payload", {{}}), ensure_ascii=False, indent=2, default=str),
            "```",
        ])
    target.write_text("\\n\\n".join(chunks) + "\\n", encoding="utf-8")
print(target)
'''
        delivered_path: Path | None = None
        try:
            baked = self.run(
                {"language": "python", "code": code, "files": [str(staging)]}
            )
            if not baked.get("ok"):
                raise SandboxError(str(baked.get("error") or baked.get("stderr") or "artifact_bake_failed"))
            delivered = baked.get("saved_to") or []
            delivered_path = next(
                (
                    Path(str(item.get("path") or ""))
                    for item in delivered
                    if isinstance(item, dict) and item.get("path")
                ),
                None,
            )
            if delivered_path is None or not delivered_path.is_file():
                raise SandboxError("artifact_not_delivered")
            blob = delivered_path.read_bytes()
            target = local._resolve_mutation_path(args, must_exist=False)
            result = local._commit_bytes(
                target, blob, job_id=job_id, action="artifact_from_observations"
            )
            result.update(
                {
                    "format": format_name,
                    "source_steps": step_ids,
                    "sandbox_run_id": str(baked.get("run_id") or ""),
                }
            )
            return result
        finally:
            if delivered_path is not None:
                delivered_path.unlink(missing_ok=True)
            staging.unlink(missing_ok=True)

    # ---- 도구 정의 -------------------------------------------------------
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "sandbox_run",
                    "description": (
                        "격리된 리눅스 상자에서 파이썬(또는 bash)을 실제로 돌린다. "
                        "계산·표·엑셀·워드·그래프처럼 **말로는 못 하고 실행해야 나오는 것**에 쓴다. "
                        "처음부터 있는 것: openpyxl(엑셀) · python-docx(워드) · pandas · matplotlib · 표준 라이브러리. "
                        "★ **없는 패키지는 packages 로 달라고 하면 도구가 깔아 준다**(예: packages=[\"qrcode[pil]\"]) — "
                        "승인이 필요 없고 다음 판에도 남는다. 없다고 포기하거나 외부 사이트로 돌지 마라. "
                        "파일은 `out/` 폴더에 저장해라. 저장하면 **자동으로 이 PC 로 나온다**"
                        "(결과의 saved_to 에 실제 경로가 온다). "
                        "상자는 이 PC 의 파일을 못 본다(files 로 넣어 준 것만 본다). 코드가 인터넷을 써야 하면 allow_network=true."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "language": {"type": "string", "enum": ["python", "bash"]},
                            "code": {"type": "string", "description": "돌릴 코드 전문"},
                            "files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "상자 안으로 넣을 파일 경로들(최대 10개). 넣으면 "
                                    "코드에서 in/<파일이름> 으로 읽는다. 엑셀·csv·문서를 "
                                    "다뤄야 할 때 쓴다 — 상자는 격리돼 있어 이걸 안 주면 "
                                    "이 PC 의 파일을 못 본다."
                                ),
                            },
                            "packages": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "상자에 없는 파이썬 패키지(pip 이름, 최대 8개). 코드를 돌리기 전에 도구가 깔아 준다. "
                                    "import 이름과 다를 수 있다: PIL→pillow, cv2→opencv-python-headless, yaml→pyyaml, "
                                    "sklearn→scikit-learn, bs4→beautifulsoup4, qrcode→qrcode[pil]."
                                ),
                            },
                            "allow_network": {
                                "type": "boolean",
                                "description": "코드가 실행 중에 인터넷을 써야 할 때 true(패키지 설치에는 필요 없다 — packages 를 써라).",
                            },
                        },
                        "required": ["code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "artifact_from_observations",
                    "description": (
                        "앞선 도구 걸음의 잘리지 않은 관측 원문을 CSV·XLSX·DOCX·JSON·MD 파일로 만든다. "
                        "조사한 내용을 표나 문서로 남길 때 쓴다. path는 상대 경로를 권장하며, "
                        "step_ids에는 근거로 쓸 성공 걸음 번호를 넣는다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "step_ids": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 1},
                                "minItems": 1,
                                "maxItems": 50,
                            },
                            "path": {"type": "string", "description": "만들 파일 경로"},
                            "format": {
                                "type": "string",
                                "enum": ["csv", "xlsx", "docx", "json", "md"],
                            },
                        },
                        "required": ["step_ids", "path", "format"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sandbox_fetch",
                    "description": (
                        "상자가 out/ 에 만든 파일을 이 PC 로 꺼낸다. "
                        "sandbox_run 결과의 run_id 와 파일 이름이 필요하다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "run_id": {"type": "string"},
                            "name": {"type": "string"},
                        },
                        "required": ["run_id", "name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sandbox_reset",
                    "description": "상자의 작업 자리를 통째로 비운다. 꼬였을 때 되돌리는 방법이다.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    @property
    def names(self) -> set[str]:
        return {"sandbox_run", "artifact_from_observations", "sandbox_fetch", "sandbox_reset"}

    # ---- 등급 -----------------------------------------------------------
    @staticmethod
    def _run_risk(arguments: dict[str, Any]) -> RiskLevel:
        """망이 열리면 **밖으로 나가는 길**이 생긴다. 나간 것은 되돌릴 수 없다.

        ★ 2026-09-30 대표 결정으로 좁혔다: 나갈 수 있는 것은 **상자 안에 있는 것뿐**이다(드라이브·interop 없음).
          사용자 파일을 넣지 않았으면 망을 켜도 샐 것이 없다 → L1. 넣은 파일 + 망일 때만 L2 로 남긴다.
          `packages` 설치는 파일을 넣기 **전에** 따로 도니 등급을 올리지 않는다.
        게이트웨이는 등급을 올리는 것만 허용하므로 바닥(L1)이 곧 최소 보장이다.
        """
        if arguments.get("allow_network") and arguments.get("files"):
            return RiskLevel.L2
        return RiskLevel.L1

    def register(self, gateway: ToolGateway) -> None:
        risks = {
            "sandbox_run": RiskLevel.L1,
            "artifact_from_observations": RiskLevel.L1,
            # 상자 밖(이 PC)에 파일을 만든다. 자리는 outputs 폴더 하나로 고정돼 있고
            # 덮어쓰기가 아니라 run_id 가 붙으므로 되돌릴 것이 작다.
            "sandbox_fetch": RiskLevel.L1,
            "sandbox_reset": RiskLevel.L1,
        }
        for name, handler in (
            ("sandbox_run", self.run),
            ("artifact_from_observations", self.artifact_from_observations),
            ("sandbox_fetch", self.fetch),
            ("sandbox_reset", self.reset),
        ):
            definition = next(
                item["function"] for item in self.ollama_tools if item["function"]["name"] == name
            )
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["description"]),
                    parameters=dict(definition.get("parameters") or {}),
                    risk_level=risks[name],
                    dynamic_risk=(
                        self._run_risk if name == "sandbox_run"
                        else self._artifact_risk if name == "artifact_from_observations"
                        else None
                    ),
                    handler=handler,
                    enabled=bool(getattr(self.config, "sandbox_enabled", False)),
                    inverse=(
                        InverseSpec(
                            label="상자가 만든 파일을 지우기",
                            handle_from=self._run_undo_handle,
                            undo=self._undo_run_outputs,
                        )
                        if name == "sandbox_run" and self.local_computer is not None
                        else InverseSpec(
                            label="관측 원문으로 만든 산출물을 이전 상태로 되돌리기",
                            handle_from=self.local_computer._undo_handle,
                            undo=self.local_computer._undo_mutation,
                        )
                        if name == "artifact_from_observations" and self.local_computer is not None
                        else None
                    ),
                    proof=(
                        ProofSpec(
                            capture_before=self._artifact_proof,
                            capture_current=self._artifact_proof,
                            capture_after=lambda args, result: self._artifact_proof(args),
                            same_target=same_fingerprint,
                            finalize=self.local_computer._finalize_file_proof,
                        )
                        if name == "artifact_from_observations" and self.local_computer is not None
                        else None
                    ),
                    needs_job_context=name in {
                        "sandbox_run", "sandbox_fetch", "artifact_from_observations"
                    },
                )
            )

    def status(self) -> dict[str, Any]:
        enabled = bool(getattr(self.config, "sandbox_enabled", False))
        info: dict[str, Any] = {
            "enabled": enabled,
            "distro": str(getattr(self.config, "sandbox_distro", "Ubuntu")),
        }
        if not enabled:
            return info
        try:
            rc, out, _ = self._exec(
                "grep -c drvfs /proc/mounts || true; "
                f"id -u {_BOX_USER} 2>/dev/null || echo -1; "
                f"[ -x {_BOX_PYTHON} ] && echo py || echo nopy",
                timeout=30,
            )
        except SandboxError as exc:
            info["reachable"] = False
            info["error"] = str(exc)
            return info
        parts = out.split()
        info["reachable"] = rc == 0
        # ★ 격리가 살아 있는지를 **매번 다시 읽는다.** wsl.conf 가 되돌려지면
        #   여기 숫자가 0 이 아니게 된다 — 캐시된 플래그는 물어보는 순간 낡는다.
        info["windows_mounts"] = int(parts[0]) if parts else -1
        info["isolated"] = info["windows_mounts"] == 0
        info["box_user"] = parts[1] if len(parts) > 1 else ""
        info["python"] = parts[2] if len(parts) > 2 else ""
        return info


__all__ = ["SandboxBox", "SandboxError"]
