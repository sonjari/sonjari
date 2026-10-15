"""그림 읽기를 끌 수 있다 — 같은 모델 파일로 그림 부속만 뺀 이름을 만들어 올린다 (2026-10-12).

대표: 「16GB 는 굳이 그림을 봐야 하나 — 켜고 끌 수 있는 선택지를」. 그림 부속은 우리가 따로 받아 붙인 것이라 떼는 것은
그 거꾸로다. 그날 3090 에서 잰 것: 부속을 떼면 1.1GB 쯤 비고, 창을 48K → 64K 로 넓혀도 원래보다 덜 쓴다.

- 새로 받는 것도 지우는 것도 없다. 원래 이름(그림 읽는 것)은 그대로 남는다.
- 뗀 이름은 목록 키를 싣고 있어, 이름만 보고 어느 모델인지 안다(능력 등급 · 「지금 쓰는 것」).
- 부속을 뗄 수 없는 모델에서는 끄라는 말을 무시한다(그림이 모델 파일 안에 든 모델 · 공식 태그).
- 기본값은 안 바꿨다 — 말하지 않으면 예전 그대로 그림을 읽게 올린다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_catalog import TEXT_ONLY_PREFIX, by_key, by_tag, text_only_key, text_only_name
from alture_jarvis.model_setup import SetupService

SOURCE = "hf.co/example/Model-27B-GGUF:Model-27B-IQ3_S-mtp.gguf"
NAME = "sonjari-text-example-27b"
MODEL_BLOB, PROJECTOR_BLOB = "a" * 64, "b" * 64


class Rig:
    """`/api/show` · `/api/create` 만 아는 가짜 서버. 원래 이름은 모델 + 그림 부속, 뗀 이름은 만들기 전에는 없다."""

    def __init__(self, *, folder: Path | None = None, projector_first: bool = False, strips: bool = True,
                 installed: bool = True) -> None:
        self.folder, self.projector_first, self.strips, self.installed = folder, projector_first, strips, installed
        self.created: list[dict[str, Any]] = []
        self.made: dict[str, dict[str, Any]] = {}

    def _path(self, digest: str) -> str:
        return str(self.folder / f"sha256-{digest}") if self.folder else f"D:\\models\\blobs\\sha256-{digest}"

    def post(self, url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if url.endswith("/api/show"):
            name = body["model"]
            if name == SOURCE:
                if not self.installed:
                    raise RuntimeError("model not found")
                order = (PROJECTOR_BLOB, MODEL_BLOB) if self.projector_first else (MODEL_BLOB, PROJECTOR_BLOB)
                return {"modelfile": "".join(f"FROM {self._path(d)}\n" for d in order),
                        "parameters": "draft_num_predict              4\n",
                        "capabilities": ["tools", "thinking", "completion", "vision"]}
            if name in self.made:
                return self.made[name]
            raise RuntimeError("model not found")
        if url.endswith("/api/create"):
            self.created.append(dict(body))
            digest = str(body["files"]["model.gguf"]).removeprefix("sha256:")
            self.made[body["model"]] = {
                "modelfile": f"FROM {self._path(digest)}\n", "parameters": "draft_num_predict              4\n",
                "capabilities": ["tools", "thinking", "completion"] + ([] if self.strips else ["vision"]),
            }
            return {"status": "success"}
        return {}


def _service(tmp_path: Path, rig: Rig) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    return SetupService(config, post=rig.post, get=lambda url: {"models": []}, stream=lambda url, body: iter(()))


# ── 뗀 이름 만들기 ──────────────────────────────────────────────────────────────

def test_the_text_only_name_is_made_from_the_model_file_alone(tmp_path: Path) -> None:
    rig = Rig()

    result = _service(tmp_path, rig).text_only_tag(SOURCE, NAME)

    assert result == {"ok": True, "tag": NAME, "created": True}
    made = rig.created[0]
    assert made["model"] == NAME, "원래 이름은 건드리지 않는다 — 다시 켜면 그쪽으로 돌아간다"
    assert made["files"] == {"model.gguf": "sha256:" + MODEL_BLOB}, "그림 부속은 넣지 않는다 · 새로 받는 것도 없다"
    assert made["parameters"] == {"draft_num_predict": 4}, "원래 기본값(미리 내다보기)을 잃지 않는다"


def test_an_existing_text_only_name_is_reused(tmp_path: Path) -> None:
    rig = Rig()
    service = _service(tmp_path, rig)
    service.text_only_tag(SOURCE, NAME)

    again = service.text_only_tag(SOURCE, NAME)

    assert again == {"ok": True, "tag": NAME, "created": False}
    assert len(rig.created) == 1


def test_the_bigger_file_is_the_model_whatever_the_order(tmp_path: Path) -> None:
    (tmp_path / f"sha256-{MODEL_BLOB}").write_bytes(b"m" * 4000)
    (tmp_path / f"sha256-{PROJECTOR_BLOB}").write_bytes(b"p" * 300)
    rig = Rig(folder=tmp_path, projector_first=True)

    assert _service(tmp_path, rig).text_only_tag(SOURCE, NAME)["ok"] is True
    assert rig.created[0]["files"] == {"model.gguf": "sha256:" + MODEL_BLOB}


def test_a_model_whose_pictures_cannot_be_taken_off_is_refused(tmp_path: Path) -> None:
    """그림이 모델 파일 안에 든 모델 — 뗀 이름을 만들어도 그림 능력이 남는다. 그 이름으로 올리지 않는다."""
    rig = Rig(strips=False)

    result = _service(tmp_path, rig).text_only_tag(SOURCE, NAME)

    assert result["ok"] is False and result["error"] == "text_only_not_usable"


def test_a_model_that_is_not_installed_is_reported(tmp_path: Path) -> None:
    rig = Rig(installed=False)

    assert _service(tmp_path, rig).text_only_tag(SOURCE, NAME) == {"ok": False, "error": "model_not_installed"}
    assert rig.created == []


# ── 이름만 보고 어느 모델인지 안다 ──────────────────────────────────────────────

def test_the_text_only_name_maps_back_to_its_catalog_model() -> None:
    swift = by_key("qwen3.8-27b-swift-iq3xxs")
    name = text_only_name(swift.key)
    assert name == TEXT_ONLY_PREFIX + swift.key
    assert by_tag(name) is swift and by_tag(name + ":latest") is swift and by_tag(name.upper()) is swift
    assert text_only_key(name) == swift.key and text_only_key(swift.ollama_tag) == ""
    assert by_tag(TEXT_ONLY_PREFIX + "no-such-model") is None and text_only_key(TEXT_ONLY_PREFIX + "no-such-model") == ""


def test_the_screen_is_told_which_models_can_turn_pictures_off() -> None:
    swift = by_key("qwen3.8-27b-swift").public()
    assert swift["pictures_optional"] is True and swift["text_only_tag"] == TEXT_ONLY_PREFIX + "qwen3.8-27b-swift"
    official = by_key("qwen3.5-9b").public()
    assert official["pictures_optional"] is False and official["text_only_tag"] == "", "공식 태그는 틀이 태그에 들어 있어 떼지 않는다"


# ── 적용 ────────────────────────────────────────────────────────────────────────

def _recording(tmp_path: Path, rig: Rig) -> tuple[SetupService, list[dict[str, Any]]]:
    service = _service(tmp_path, rig)
    seen: list[dict[str, Any]] = []
    service._tag_for = lambda catalog_tag: SOURCE if "swift" in catalog_tag.lower() else catalog_tag

    def try_and_save(tag: str, ctx: int, previous: str, **kwargs: Any) -> dict[str, Any]:
        seen.append({"tag": tag, "ctx": ctx, **kwargs})
        return {"ok": True}

    service._try_and_save = try_and_save
    return service, seen


def test_applying_without_pictures_uses_the_text_only_name(tmp_path: Path) -> None:
    rig = Rig()
    service, seen = _recording(tmp_path, rig)
    key = "qwen3.8-27b-swift-iq3xxs"

    assert service.apply(key, 65536, eyes=False) == {"ok": True}

    assert seen[0]["tag"] == text_only_name(key) and seen[0]["vision"] is False and seen[0]["catalog_key"] == key
    assert seen[0]["ctx"] == 65536
    assert rig.created[0]["model"] == text_only_name(key)


def test_the_default_still_reads_pictures(tmp_path: Path) -> None:
    rig = Rig()
    service, seen = _recording(tmp_path, rig)

    service.apply("qwen3.8-27b-swift-iq3xxs", 49152)
    service.apply("qwen3.8-27b-swift-iq3xxs", 49152, eyes=True)

    assert [row["tag"] for row in seen] == [SOURCE, SOURCE] and all(row["vision"] is True for row in seen)
    assert rig.created == [], "말하지 않으면 뗀 이름을 만들지 않는다"


def test_turning_pictures_off_is_ignored_where_it_cannot_be_done(tmp_path: Path) -> None:
    rig = Rig()
    service, seen = _recording(tmp_path, rig)

    service.apply("qwen3.5-9b", 32768, eyes=False)

    assert seen[0]["tag"] == "qwen3.5:9b" and rig.created == []


def test_a_failed_text_only_name_does_not_change_the_model(tmp_path: Path) -> None:
    rig = Rig(strips=False)
    service, seen = _recording(tmp_path, rig)

    result = service.apply("qwen3.8-27b-swift-iq3xxs", 65536, eyes=False)

    assert result["ok"] is False and result["error"] == "text_only_not_usable" and seen == []


def test_picking_the_text_only_name_keeps_pictures_off(tmp_path: Path) -> None:
    """모델 고르개에서 「글만 읽는」 이름을 집었다 — 목록 모델로 풀면서 그림을 다시 붙이면 안 된다."""
    service = _service(tmp_path, Rig())
    seen: list[dict[str, Any]] = []
    service.apply = lambda key, ctx, **kwargs: seen.append({"key": key, "ctx": ctx, **kwargs}) or {"ok": True}

    service.apply_tag(text_only_name("qwen3.8-27b-swift-iq3xxs"), 65536)
    service.apply_tag(by_key("qwen3.8-27b-swift-iq3xxs").ollama_tag, 49152)
    service.apply_tag(by_key("qwen3.8-27b-swift-iq3xxs").ollama_tag, 49152, eyes=False)

    assert [(row["key"], row["eyes"]) for row in seen] == [
        ("qwen3.8-27b-swift-iq3xxs", False), ("qwen3.8-27b-swift-iq3xxs", None), ("qwen3.8-27b-swift-iq3xxs", False),
    ]

