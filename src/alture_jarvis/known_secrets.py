"""**아는** 비밀 값을 도구 결과에서 가린다 — 모양으로 찾지 않고 값으로 찾는다 (2026-10-11).

## 왜

손자리가 돌린 명령은 무엇이든 찍을 수 있다. 오류 글에 API 키가 섞여 나오면 그 출력은 모델에게 가고, 걸음 장부와 답에도 남는다.
`secret_scrub` 은 **모양**으로 비밀을 찾는 부품인데, 처음 만들 때 저장소에 대 보니 멀쩡한 글 74곳을 걷어 냈다 — 명령 출력처럼
코드와 해시가 흔한 글에는 걸 수 없다.

여기는 다른 길이다. 손자리는 **값을 이미 아는** 비밀이 있다:

    - 손자리 자신의 제어 토큰 · 구글 토큰
    - 명령에 넘기는 환경 가운데 이름이 비밀인 것(`OPENAI_API_KEY` …) — 넘기는 것이 우리라 값을 안다
    - 작업 폴더의 `.env` 류 파일에 적힌 것 — 명령이 스스로 읽어 쓰지만, 우리도 같은 파일을 읽을 수 있다

아는 값을 **글자 그대로** 찾으니 엉뚱한 것을 가릴 일이 없다. 값은 프로그램에 그대로 전달되고, 모델이 보는 글에서만 가린다.
(레딧에서 받은 조언을 구조에 맞춰 옮긴 것: 명령과 모델 사이에 거름망 · 값을 모르는 것은 지우지 말고 표시만.)

## 규율

1. **지우지 않고 표시를 남긴다** — `[비밀 가림: OPENAI_API_KEY]`. 무엇이 가려졌는지 모르면 모델이 같은 값을 다시 찍어 보려 한다.
2. **값을 모르는 것은 가리지 않는다.** 비밀처럼 보이는 긴 글자는 세기만 한다(`count_secret_looking`) — 가릴지는 사람 몫.
3. **이름이 비밀이어도 값이 비밀 같지 않으면 배우지 않는다** — 자리 표시(`changeme`) · 주소 · 경로 · 숫자 · 짧은 것.
   한 번 배운 값은 모든 도구 결과에서 가려지므로, 흔한 낱말을 배우면 멀쩡한 글이 구멍 난다.
4. 여기 든 값은 **메모리에만** 있다. 파일·기록·이벤트에 쓰지 않는다.
"""

from __future__ import annotations

import base64
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from .secret_scrub import _PLACEHOLDER, looks_random

#: 이보다 짧은 값은 배우지 않는다 — 짧은 값은 멀쩡한 글에도 우연히 나온다.
MIN_VALUE_CHARS = 8
MAX_VALUE_CHARS = 4096
#: 이름을 `_`·`-`·`.` 로 쪼갠 조각 가운데 이것이 있으면 비밀 이름이다. (`KEYBOARD` 는 `KEY` 가 아니다.)
_SECRET_NAME_PARTS = frozenset({
    "KEY", "APIKEY", "TOKEN", "SECRET", "SECRETS", "PASSWORD", "PASSWD", "PWD", "PASS",
    "CREDENTIAL", "CREDENTIALS", "PRIVATE", "PAT",
})
#: 셸이 스스로 채우는 폴더 변수 — 이름에 `PWD` 가 있어도 비밀이 아니다.
_SHELL_DIRECTORY_NAMES = frozenset({"PWD", "OLDPWD"})
#: 붙여 쓴 이름(`githubToken` · `apikey`)의 끝.
_SECRET_NAME_ENDS = ("token", "secret", "password", "passwd", "apikey")
#: 이름에 비밀 낱말이 있어도 **값이 비밀이 아닌** 칸 — 주소·경로·이름·식별자·수명.
_PLAIN_NAME_ENDS = (
    "_URL", "_URI", "_PATH", "_FILE", "_DIR", "_NAME", "_HOST", "_PORT", "_TTL", "_EXPIRES", "_EXPIRY", "_EXPIRATION",
    "_TYPE", "_ALG", "_ALGORITHM", "_HEADER", "_LENGTH", "_SIZE", "_ID", "_PREFIX", "_ENDPOINT", "_REGION", "_VERSION",
)
#: `.env` 류 파일. 본보기 파일은 뺀다(값이 자리 표시다).
_DOTENV_NAME = re.compile(r"^(?:\.env(?:\.[\w.-]+)?|[\w.-]+\.env)$", re.IGNORECASE)
_DOTENV_SAMPLE = re.compile(r"\.(?:example|sample|template|dist|defaults?)$", re.IGNORECASE)
_DOTENV_LINE = re.compile(r"^\s*(?:export\s+|set\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(.*?)\s*$")
_DOTENV_MAX_BYTES = 256_000
_DOTENV_MAX_FILES = 12
#: 값만 봐도 비밀인 모양 — 이름이 평범해도 `.env` 에 적혀 있으면 배운다. (모양으로 **가리는** 것이 아니라, 적힌 값을 **배우는** 기준이다.)
_KEY_SHAPED = re.compile(
    r"^(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|xox[abprs]-[A-Za-z0-9-]{10,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|hf_[A-Za-z0-9]{30,}|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})$"
)
#: 걷지 않고 지나갈 글 — 그림 같은 큰 덩어리.
_SKIP_OVER_CHARS = 2_000_000
#: 비밀처럼 보이는 긴 글자를 셀 때 보는 낱말. 해시 표기 뒤의 것은 뺀다(`sha512-…` 는 무결성 값이다).
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{32,200}(?![A-Za-z0-9_+/=-])")
_AFTER_HASH_NAME = re.compile(r"(?:sha(?:1|224|256|384|512)|md5|integrity)[-:=\"' ]{1,3}$", re.IGNORECASE)


def secret_name(name: str) -> bool:
    """환경변수·설정 **이름**이 비밀을 담는 칸인가."""
    upper = str(name or "").upper()
    if not upper or upper.endswith(_PLAIN_NAME_ENDS):
        return False
    # `PWD` · `OLDPWD` 는 셸이 「지금 있는 폴더」를 적어 두는 변수다 — 비밀번호가 아니다. 그 값(경로)을 비밀로 배우면
    # 명령 결과의 그 경로가 전부 가려진다(2026-10-11). `DB_PWD` 처럼 줄임말로 쓰인 이름은 아래에서 그대로 걸린다.
    if upper in _SHELL_DIRECTORY_NAMES:
        return False
    if _SECRET_NAME_PARTS & set(re.split(r"[^A-Z0-9]+", upper)):
        return True
    return str(name).lower().endswith(_SECRET_NAME_ENDS)


def learnable_value(value: str) -> bool:
    """배워도 되는 값인가 — 한 번 배우면 모든 도구 결과에서 가려지므로, 흔한 글은 배우지 않는다."""
    value = str(value or "")
    if not (MIN_VALUE_CHARS <= len(value) <= MAX_VALUE_CHARS) or "\n" in value or "\r" in value:
        return False
    if _PLACEHOLDER.match(value) or value.strip() != value:
        return False
    if value.replace(".", "").replace("_", "").replace("-", "").isdigit():
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://[^@\s]*$", value):
        return False                      # 사용자 정보가 없는 주소
    if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/|~[\\/]|\.{1,2}[\\/])", value):
        return False                      # 경로
    if value.isalpha() and value.islower():
        return False                      # 낱말 하나(`development`)
    return True


def marker(label: str) -> str:
    return f"[비밀 가림: {label}]"


def dotenv_like(path: Path | str) -> bool:
    name = Path(str(path)).name
    return bool(_DOTENV_NAME.match(name)) and not _DOTENV_SAMPLE.search(name)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
        return value[1:-1]
    # 따옴표 없는 값의 줄 끝 주석(` # …`)은 뗀다.
    return re.sub(r"\s+#.*$", "", value)


class KnownSecrets:
    """아는 비밀 값의 모음과, 그것을 글에서 가리는 일. 값은 메모리에만 든다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._labels: dict[str, str] = {}          # 가릴 글자(값 · 그 값의 흔한 변형) → 이름
        self._pattern: re.Pattern[str] | None = None
        self._dotenv_seen: dict[str, tuple[int, int]] = {}   # 파일 → (고친 시각, 크기)
        self._folder_seen: dict[str, tuple[int, list[Path]]] = {}   # 폴더 → (고친 시각, 그 안의 .env 류 파일)

    def __len__(self) -> int:
        with self._lock:
            return len(set(self._labels.values()))

    # --- 배우기 ---------------------------------------------------------------

    def learn(self, value: str, label: str) -> bool:
        """값 하나를 배운다 → 새로 배웠는가. 배울 만한 값이 아니면 아무것도 하지 않는다."""
        value = str(value or "")
        if not learnable_value(value):
            return False
        label = str(label or "비밀")[:60]
        forms = {value}
        try:
            raw = value.encode("utf-8")
            quoted = quote(value, safe="")
            standard = base64.b64encode(raw).decode("ascii")
            forms.update(form for form in (quoted, standard, standard.rstrip("="),
                                           base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="))
                         if len(form) >= 12)
        except Exception:  # noqa: BLE001 — 변형을 못 만들어도 원래 값은 배운다
            pass
        with self._lock:
            fresh = value not in self._labels
            for form in forms:
                self._labels.setdefault(form, label)
            if fresh:
                self._pattern = None
        return fresh

    def learn_environment(self, environment: Mapping[str, str]) -> int:
        """명령에 넘기는 환경에서 이름이 비밀인 것의 값을 배운다 → 새로 배운 수."""
        return sum(1 for name, value in environment.items() if secret_name(name) and self.learn(str(value), str(name)))

    def learn_dotenv(self, path: Path | str) -> int:
        """`.env` 류 파일 하나에 적힌 비밀을 배운다 → 새로 배운 수. 파일이 그대로면 다시 읽지 않는다."""
        target = Path(str(path))
        try:
            if not dotenv_like(target) or not target.is_file():
                return 0
            stat = target.stat()
            if stat.st_size > _DOTENV_MAX_BYTES:
                return 0
            key, stamp = str(target.resolve()).lower(), (int(stat.st_mtime_ns), int(stat.st_size))
            with self._lock:
                if self._dotenv_seen.get(key) == stamp:
                    return 0
                self._dotenv_seen[key] = stamp
            text = target.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return 0
        learned = 0
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            found = _DOTENV_LINE.match(line)
            if not found:
                continue
            name, value = found.group(1), _unquote(found.group(2))
            if secret_name(name) or _KEY_SHAPED.match(value) or looks_random(value, min_len=24):
                learned += int(self.learn(value, name))
        return learned

    def learn_dotenvs_in(self, folder: Path | str) -> int:
        """폴더 바로 아래의 `.env` 류 파일들 — 명령이 스스로 읽어 쓸 것들이다."""
        try:
            files = [entry for entry in Path(str(folder)).iterdir() if dotenv_like(entry)][:_DOTENV_MAX_FILES]
        except OSError:
            return 0
        return sum(self.learn_dotenv(entry) for entry in files)

    def learn_near(self, path: Path | str) -> int:
        """도구가 건드린 경로 가까이의 `.env` 류 파일을 배운다 — 폴더면 그 안, 파일이면 그 파일과 같은 폴더.

        도구를 부를 때마다 불리므로 싸야 한다: 폴더 목록은 폴더가 바뀌었을 때만 다시 훑고, 파일은 바뀌었을 때만 다시 읽는다.
        """
        try:
            target = Path(str(path))
            folder = target if target.is_dir() else target.parent
            stamp = int(folder.stat().st_mtime_ns)
        except (OSError, ValueError):
            return 0
        key = str(folder).lower()
        with self._lock:
            known = self._folder_seen.get(key)
        if known is None or known[0] != stamp:
            try:
                files = [entry for entry in folder.iterdir() if dotenv_like(entry)][:_DOTENV_MAX_FILES]
            except OSError:
                return 0
            with self._lock:
                if len(self._folder_seen) > 512:
                    self._folder_seen.clear()
                self._folder_seen[key] = (stamp, files)
        else:
            files = known[1]
        return sum(self.learn_dotenv(entry) for entry in files)

    # --- 가리기 ---------------------------------------------------------------

    def _compiled(self) -> tuple[re.Pattern[str] | None, dict[str, str]]:
        with self._lock:
            if self._pattern is None and self._labels:
                # 긴 것부터 — 한 값이 다른 값의 앞부분일 때 긴 쪽이 먼저 걸리게.
                self._pattern = re.compile("|".join(re.escape(form) for form in sorted(self._labels, key=len, reverse=True)))
            return self._pattern, dict(self._labels) if self._pattern is not None else {}

    def hide(self, text: str) -> tuple[str, int]:
        """글에서 아는 값을 가린다 → (가린 글, 가린 곳 수)."""
        if not isinstance(text, str) or len(text) < MIN_VALUE_CHARS or len(text) > _SKIP_OVER_CHARS or text.startswith("data:"):
            return text, 0
        pattern, labels = self._compiled()
        if pattern is None:
            return text, 0
        hidden, count = pattern.subn(lambda found: marker(labels.get(found.group(0), "비밀")), text)
        return hidden, count

    def hide_in(self, value: Any) -> tuple[Any, int]:
        """도구 결과(딕셔너리·목록·글)의 글자 칸을 전부 지나며 가린다 → (같은 모양의 결과, 가린 곳 수).

        가린 곳이 없으면 **받은 것을 그대로** 돌려준다 — 결과를 쓸데없이 베끼지 않는다. 칸 이름은 건드리지 않는다.
        """
        if isinstance(value, str):
            return self.hide(value)
        if isinstance(value, Mapping):
            changed, total, out = False, 0, {}
            for key, item in value.items():
                new, count = self.hide_in(item)
                out[key] = new
                total += count
                changed = changed or count > 0
            return (out if changed else value), total
        if isinstance(value, (list, tuple)):
            pairs = [self.hide_in(item) for item in value]
            total = sum(count for _, count in pairs)
            if not total:
                return value, 0
            items = [new for new, _ in pairs]
            return (tuple(items) if isinstance(value, tuple) else items), total
        return value, 0


def count_secret_looking(text: str, *, limit: int = 20) -> int:
    """비밀처럼 보이는 **긴 무작위 글자**의 수 — 가리지 않고 세기만 한다(표시용).

    커밋 해시·UUID·무결성 값(`sha512-…`)은 세지 않는다. 틀려도 잃는 것이 없게: 세기만 하고 글은 그대로다.
    """
    if not isinstance(text, str) or len(text) > _SKIP_OVER_CHARS:
        return 0
    count = 0
    for found in _LONG_TOKEN.finditer(text):
        token = found.group(0)
        if "[비밀 가림" in token or _AFTER_HASH_NAME.search(text[max(0, found.start() - 14):found.start()]):
            continue
        if looks_random(token.strip("=-_"), min_len=32):
            count += 1
            if count >= limit:
                break
    return count


def learn_all(secrets: KnownSecrets, pairs: Iterable[tuple[str, str]]) -> int:
    return sum(1 for value, label in pairs if secrets.learn(value, label))
