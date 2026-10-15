"""포장본에 비밀이 실려 나가지 않았나 — 인터넷에서 받게 하기 전에 본다 (2026-09-17).

NAS 업데이트 경로(`/ontelic/update/<channel>/`)는 주소만 알면 누구나 받는다. 그래서 올리기 직전에 펼친 포장본을
통째로 훑는다. 찾는 것은 **진짜 비밀의 모양**뿐이다(키 접두사·개인키 블록·.env 파일·우리 운영 키의 앞자리).
구글 데스크톱 OAuth 의 client_id 는 공개값이라 세지 않는다.

    python scan_package_secrets.py C:\\RoboMetaFit\\tools\\JarvisAppStage\\app

찾으면 파일·줄·종류만 찍고(값은 앞 4자만) 종료 코드 1. 아무것도 없으면 0.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[bytes]]] = [
    ("openai/anthropic key", re.compile(rb"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}")),
    ("google api key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("github token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}")),
    ("aws key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("google client secret", re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{20,}")),
    ("toss secret key", re.compile(rb"\b(?:live|test)_sk_[A-Za-z0-9]{16,}")),
]


def _extra_prefixes() -> list[tuple[str, re.Pattern[bytes]]]:
    """우리 운영 값의 앞자리 — **소스에 적지 않는다** (2026-09-29 깃허브 공개 준비).

    예전엔 운영 API 키·워커 토큰 앞 12자를 여기 그대로 적었다. 공개 저장소에 그 앞자리가 실리면 그것 자체가 새는 것이다.
    이제 이 PC 에서만 읽는 `secret_prefixes.local.txt`(깃 제외 — 한 줄에 `이름=앞자리`)와
    환경변수 `JARVIS_SCAN_EXTRA_PREFIXES`(`이름=앞자리,이름=앞자리`)에서 읽는다. 없으면 일반 모양만 본다.
    """
    lines: list[str] = []
    local = Path(__file__).with_name("secret_prefixes.local.txt")
    if local.is_file():
        lines += local.read_text(encoding="utf-8").splitlines()
    lines += [part for part in (os.environ.get("JARVIS_SCAN_EXTRA_PREFIXES") or "").split(",")]
    out: list[tuple[str, re.Pattern[bytes]]] = []
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and len(value.strip()) >= 8 and not name.startswith("#"):
            out.append((name.strip(), re.compile(re.escape(value.strip().encode("utf-8")))))
    return out


PATTERNS += _extra_prefixes()
# `.env.example`·`.env.sample`·`.env.template` 은 견본이라 이름으로 걸지 않고 **내용을 본다**(2026-09-29 코덱스 교차 검사:
#   이름으로 걸고 건너뛰는 바람에 그 안에 진짜 키가 있어도 아무도 안 봤다).
SECRET_FILES = re.compile(
    r"^(?:\.env(?:\.(?!example$|sample$|template$)[^.]+)?|control\.token|credentials\.json|token\.json"
    r"|id_(?:rsa|ed25519)(?:\.pub)?)$",
    re.I,
)
# 서드파티 파이썬 패키지의 시험 자료·문서 속 가짜 키 모양은 건너뛴다 — 우리 코드·데이터만 본다.
SKIP_PARTS = {"__pycache__"}
# ★ .tsx·.rs 가 빠져 있어 화면·앱 껍데기 소스의 키를 못 봤다(2026-09-29 코덱스 교차 검사).
TEXT_SUFFIXES = {
    ".py", ".json", ".jsonl", ".md", ".txt", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env", ".html", ".js", ".ts",
    ".tsx", ".jsx", ".mjs", ".cjs", ".rs", ".cs", ".sh", ".xml", ".ps1", ".bat", ".cmd", ".example", ".sample",
    ".template", ".conf", ".properties",
}
MAX_BYTES = 8 * 1024 * 1024


def _placeholder_key(data: bytes, start: int) -> bool:
    """개인 키 블록의 본문이 **자리 표시뿐**인가(문서 예시). 진짜 키는 긴 base64 라 여기 안 걸린다.

    ★ 2026-09-26: pyright 에 node 를 같이 담자(`nodejs_wheel`) npm 설정 문서의 예시
      `key="-----BEGIN PRIVATE KEY-----\\nXXXX\\nXXXX\\n-----END PRIVATE KEY-----"` 가 두 곳에서 잡혀 게시가 멈췄다.
      경로를 통째로 빼지 않고, 본문이 X·점뿐일 때만 건너뛴다.
    """
    end = data.find(b"-----END", start, start + 400)
    if end < 0:
        return False
    body = data[start:end]
    for noise in (b"\\\\n", b"\\n", b"\n", b"\r", b" ", b"\t", b'"', b"'"):
        body = body.replace(noise, b"")
    if bool(body) and set(body) <= set(b"Xx."):
        return True
    # 진짜 키 본문은 base64 가 길게 이어진다. 24자 넘게 이어진 줄이 없으면 시험 코드의 조립식(`"..." + _fake(70)`)이다.
    return not re.search(rb"[A-Za-z0-9+/=]{24,}", body)


def _placeholder_token(value: bytes) -> bool:
    """`sk-ant-api03-xxxxxxxx…` 처럼 같은 글자가 12번 넘게 이어지면 자리 표시다 — 진짜 키엔 그런 줄이 없다.

    예전 공개판 검사는 가짜 키가 든 **시험 파일을 통째로** 면제했다. 그러면 그 파일에 진짜 키가 들어와도 안 걸린다
    (2026-09-29 코덱스 교차 검사). 파일이 아니라 **값**으로 판정한다.
    """
    return bool(re.search(rb"(.)\1{11,}", value))


def scan(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or SKIP_PARTS.intersection(path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if SECRET_FILES.match(path.name):
            hits.append(f"{rel}: secret-looking file name")
            continue
        ours = "/alture_jarvis/" in f"/{rel}" or not ("/site-packages/" in f"/{rel}" or "/Lib/" in f"/{rel}")
        if path.suffix.lower() not in TEXT_SUFFIXES and not (ours and path.suffix.lower() in {".exe", ".dll"} and path.stat().st_size < 64 * 1024 * 1024):
            continue
        if not ours and path.suffix.lower() in {".py", ".md", ".txt"}:
            continue
        try:
            data = path.read_bytes()[:MAX_BYTES]
        except OSError:
            continue
        for label, pattern in PATTERNS:
            for match in pattern.finditer(data):
                if label == "private key block" and _placeholder_key(data, match.end()):
                    continue
                if label != "private key block" and _placeholder_token(match.group(0)):
                    continue
                line = data.count(b"\n", 0, match.start()) + 1
                head = match.group(0)[:4].decode(errors="replace")
                hits.append(f"{rel}:{line}: {label} ({head}...)")
    return hits


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\RoboMetaFit\tools\JarvisAppStage\app")
    if not root.is_dir():
        print(f"not a folder: {root}")
        return 2
    hits = scan(root)
    for hit in hits:
        print(hit)
    print(f"scanned {root} - {len(hits)} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
