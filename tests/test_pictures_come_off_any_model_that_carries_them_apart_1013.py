"""「글만 읽기」를 목록 밖 모델과, 받아 보니 그림 부속이 따로 붙어 온 모델로 넓힌다 (2026-10-13).

그날 밤 6GB 노트북(RTX 3050 · 바깥 모니터를 그 카드가 그림)에서 본 것:

- 눈(그림 부속)을 단 4B · 창 32K 가 **34층 중 30층만** 카드에 올라갔다. 빈 자리는 5.1GB 였는데, Ollama 0.35 가 모델을
  올릴 때 「눈의 무게 + 1GiB」를 비워 두기 때문이다(`llm/llama_server.go` 의 `mmprojOffloadHeadroom`). 마법사는 2B 로 내렸다.
- 같은 모델에서 눈만 뺀 이름을 만들어 올리니 여유가 1,024MiB 로 줄고, 창 32K(3,483MiB) · 48K(4,011MiB) 가 전부 올라갔다.
- 그 길이 목록 모델 가운데 우리가 부속을 붙인 것(`projector_tag`)에만 있었다. 허깅페이스에서 고른 모델에는 없었다.

여기서 지키는 것:

- 뗄 수 있는지는 **이름이 아니라 받아 둔 파일**로 본다 — 파일 줄이 둘이면 뗄 수 있다(`qwen3.5:2b` 는 둘, `qwen3.5:4b` 는 하나).
- 그림이 모델 파일 안에 든 목록 밖 모델에 「글만 읽기」를 시키면 **못 한다고 돌려준다** — 말없이 그림을 단 채 올리지 않는다.
- 새로 받는 것도 지우는 것도 없다. 원래 이름은 남고, 돌아갈 길(원래 이름)을 적어 둔다.
- 말하지 않으면(`eyes=None`) 예전 그대로다.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_catalog import CATALOG, TEXT_ONLY_PREFIX, is_text_only_name, text_only_name, text_only_name_for_tag
from alture_jarvis.model_setup import OLLAMA_TAG, SetupService, read_text_only_sources

PICKED = "hf.co/someone/Sample-4B-GGUF:UD-Q3_K_XL"
PICKED_PLAIN = "sonjari-text-someone-sample-4b-gguf-ud-q3_k_xl"
INLINE = "hf.co/someone/Inline-4B-GGUF:Q4_K_M"
MODEL_BLOB, EYES_BLOB, INLINE_BLOB = "a" * 64, "b" * 64, "c" * 64


class Rig:
    """`/api/show` · `/api/create` 만 아는 가짜 Ollama. 모델마다 파일(지문)과 능력을 들고 있다."""

    #: 파일 크기는 **표로만** 알려 준다. ★ 진짜 파일을 만들지 않는다 — 처음엔 빈 파일을 그 크기로 늘렸는데(`truncate`),
    #: 윈도우에서는 그게 실제 자리를 차지해 시험 한 번에 6GB 씩 쌓였고 C: 를 100GB 넘게 채웠다(2026-10-13 밤).
    SIZES = {MODEL_BLOB: 2_324_000_000, EYES_BLOB: 644_000_000, INLINE_BLOB: 3_233_000_000}

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.models: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.shown: list[str] = []
        self.add(PICKED, [MODEL_BLOB, EYES_BLOB], vision=True)
        self.add(INLINE, [INLINE_BLOB], vision=True)

    def size(self, path: Path) -> int:
        digest = path.name.removeprefix("sha256-")
        if digest not in self.SIZES:
            raise FileNotFoundError(str(path))
        return self.SIZES[digest]

    def add(self, name: str, digests: list[str], *, vision: bool, **more: Any) -> None:
        self.models[name.lower()] = {
            "modelfile": "".join(f"FROM {self.folder / ('sha256-' + d)}\n" for d in digests),
            "parameters": "", "capabilities": ["tools", "thinking", "completion"] + (["vision"] if vision else []), **more,
        }

    def post(self, url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if url.endswith("/api/show"):
            self.shown.append(str(body["model"]))
            found = self.models.get(str(body["model"]).lower())
            if found is None:
                raise RuntimeError("model not found")
            return found
        if url.endswith("/api/create"):
            self.created.append(dict(body))
            digest = str(body["files"]["model.gguf"]).removeprefix("sha256:")
            # 그림이 모델 파일 안에 든 모델은 그 파일만으로 다시 만들어도 그림 능력이 남는다.
            self.add(str(body["model"]), [digest], vision=digest == INLINE_BLOB)
            return {"status": "success"}
        return {}


def _service(tmp_path: Path, rig: Rig, *, chat: str = "") -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    if chat:
        config.model_roles = {"chat": chat}
    service = SetupService(config, post=rig.post, get=lambda url: {"models": []}, stream=lambda url, body: iter(()))
    service._blob_size = rig.size
    return service


def _recording(tmp_path: Path, rig: Rig, **kwargs: Any) -> tuple[SetupService, list[dict[str, Any]]]:
    service = _service(tmp_path, rig, **kwargs)
    seen: list[dict[str, Any]] = []
    service._try_and_save = lambda tag, ctx, previous, **more: seen.append({"tag": tag, "ctx": ctx, **more}) or {"ok": True}
    return service, seen


# ── 이름 ────────────────────────────────────────────────────────────────────────

def test_an_unlisted_model_gets_a_text_only_name_made_from_its_own_name() -> None:
    name = text_only_name_for_tag(PICKED)

    assert name == PICKED_PLAIN and is_text_only_name(name)
    assert OLLAMA_TAG.fullmatch(name), "적용 길이 받는 이름 모양이어야 한다"
    assert text_only_name_for_tag(name) == name and text_only_name_for_tag(name + ":latest") == name, "이미 그 이름이면 그대로"
    assert text_only_name_for_tag("hf.co/other/Sample-4B-GGUF:UD-Q3_K_XL") != name, "주인이 다르면 이름도 다르다"


def test_a_very_long_name_still_fits_the_name_rule() -> None:
    long = "hf.co/" + "o" * 60 + "/" + "r" * 90 + ":" + "q" * 40

    assert OLLAMA_TAG.fullmatch(text_only_name_for_tag(long))


# ── 뗄 수 있는지는 파일로 본다 ──────────────────────────────────────────────────

def test_two_files_mean_the_pictures_part_can_come_off(tmp_path: Path) -> None:
    service = _service(tmp_path, Rig(tmp_path))

    assert service.eyes_of(PICKED) == {"vision": True, "separable": True, "eyes_gb": 0.64}, "크기는 작은 쪽 파일"
    assert service.eyes_of(INLINE) == {"vision": True, "separable": False, "eyes_gb": 0.0}, "한 파일이면 못 뗀다"


def test_a_model_that_is_not_here_says_no_and_is_asked_again_later(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    service = _service(tmp_path, rig)

    assert service.eyes_of("hf.co/x/Not-Yet:Q4") == {"vision": False, "separable": False, "eyes_gb": 0.0}
    rig.add("hf.co/x/Not-Yet:Q4", [MODEL_BLOB, EYES_BLOB], vision=True)

    assert service.eyes_of("hf.co/x/Not-Yet:Q4")["separable"] is True, "못 물어본 답은 들고 있지 않는다 — 받고 나면 달라진다"


def test_the_answer_is_held_for_a_while(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    service = _service(tmp_path, rig)

    for _ in range(4):
        service.eyes_of(PICKED)

    assert rig.shown.count(PICKED) == 1, "화면이 1초마다 불러도 Ollama 에는 한 번만 묻는다"


# ── 목록 밖 모델을 「글만 읽기」로 ──────────────────────────────────────────────

def test_an_unlisted_model_is_applied_without_its_pictures_part(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    service, seen = _recording(tmp_path, rig)

    assert service.apply_tag(PICKED, 49152, eyes=False) == {"ok": True}

    assert rig.created[0]["model"] == PICKED_PLAIN and rig.created[0]["files"] == {"model.gguf": "sha256:" + MODEL_BLOB}
    assert seen == [{"tag": PICKED_PLAIN, "ctx": 49152, "catalog_key": "", "vision": False, "status": "unlisted",
                     "remembered_first": False}]
    assert read_text_only_sources(tmp_path / "data") == {PICKED_PLAIN: PICKED}, "돌아갈 길을 적어 둔다"


def test_saying_nothing_keeps_the_pictures(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    service, seen = _recording(tmp_path, rig)

    service.apply_tag(PICKED, 32768)
    service.apply_tag(PICKED, 32768, eyes=True)

    assert [(row["tag"], row["vision"]) for row in seen] == [(PICKED, True), (PICKED, True)] and rig.created == []


def test_pictures_inside_the_model_file_are_not_silently_kept(tmp_path: Path) -> None:
    """자리를 아끼려고 끈 것이다 — 조용히 켠 채 올리면 다 못 올라간 까닭을 알 수 없다."""
    rig = Rig(tmp_path)
    service, seen = _recording(tmp_path, rig, chat="qwen3.5:2b")

    result = service.apply_tag(INLINE, 32768, eyes=False)

    assert result == {"ok": False, "error": "pictures_inside_model_file", "kept": "qwen3.5:2b"}
    assert seen == [] and rig.created == []


def test_going_back_to_reading_pictures_uses_the_name_it_came_from(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    service, seen = _recording(tmp_path, rig)
    service.apply_tag(PICKED, 49152, eyes=False)

    service.apply_tag(PICKED_PLAIN, 32768, eyes=True)

    assert (seen[-1]["tag"], seen[-1]["vision"], seen[-1]["ctx"]) == (PICKED, True, 32768)


def test_a_text_only_name_whose_origin_is_unknown_cannot_go_back(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.add(PICKED_PLAIN, [MODEL_BLOB], vision=False)  # 손으로 만든 이름 — 적어 둔 것이 없다
    service, seen = _recording(tmp_path, rig, chat=PICKED_PLAIN)

    assert service.apply_tag(PICKED_PLAIN, 32768, eyes=True) == {"ok": False, "error": "text_only_source_unknown", "kept": PICKED_PLAIN}
    assert service.apply_tag(PICKED_PLAIN, 32768) == {"ok": True}, "그 이름 그대로 쓰는 것은 된다"
    assert seen[-1]["tag"] == PICKED_PLAIN and seen[-1]["vision"] is False


def test_the_frame_written_on_an_official_tag_is_carried_over(tmp_path: Path) -> None:
    """공식 태그는 말하는 틀을 태그에 적어 둔다 — 파일만으로 다시 만들면 떨어져 도구 쓰기가 사라질 수 있다."""
    rig = Rig(tmp_path)
    rig.add("official:2b", [MODEL_BLOB, EYES_BLOB], vision=True, renderer="qwen3.5", parser="qwen3.5")
    service = _service(tmp_path, rig)

    service.text_only_tag("official:2b", "sonjari-text-official-2b")
    service.text_only_tag(PICKED, PICKED_PLAIN)

    assert rig.created[0]["renderer"] == "qwen3.5" and rig.created[0]["parser"] == "qwen3.5"
    assert "renderer" not in rig.created[1] and "parser" not in rig.created[1], "그 칸이 없는 모델은 예전과 같은 요청"


def test_a_picked_model_can_be_fetched_and_applied_without_pictures(tmp_path: Path) -> None:
    service = _service(tmp_path, Rig(tmp_path))
    applied: list[tuple[Any, ...]] = []
    service._pull = lambda key, tag, after=None: after()
    service.apply_tag = lambda tag, ctx, **kwargs: applied.append((tag, ctx, kwargs.get("eyes"))) or {"ok": True}

    service.start_pull_tag(PICKED, 49152, eyes=False)
    service.start_pull_tag(INLINE, 32768)
    for _ in range(100):
        if len(applied) == 2:
            break
        time.sleep(0.02)

    assert sorted(applied) == [(INLINE, 32768, None), (PICKED, 49152, False)]


# ── 목록 모델 — 받아 보니 부속이 따로 붙어 온 것 ───────────────────────────────

def _plain_listed():
    """그림을 읽지만 우리가 부속을 붙이지는 않는 목록 모델 하나."""
    return next(model for model in CATALOG if model.vision and not model.projector_tag)


def test_a_listed_model_drops_its_pictures_part_when_this_pc_has_it_apart(tmp_path: Path) -> None:
    listed = _plain_listed()
    rig = Rig(tmp_path)
    rig.add(listed.ollama_tag, [MODEL_BLOB, EYES_BLOB], vision=True)
    service, seen = _recording(tmp_path, rig)
    ctx = min(listed.vram_gb)

    assert service.apply(listed.key, ctx, eyes=False) == {"ok": True}

    assert seen[0]["tag"] == text_only_name(listed.key) and seen[0]["vision"] is False and seen[0]["catalog_key"] == listed.key
    assert rig.created[0]["files"] == {"model.gguf": "sha256:" + MODEL_BLOB}


def test_a_listed_model_with_pictures_inside_is_applied_as_before(tmp_path: Path) -> None:
    listed = _plain_listed()
    rig = Rig(tmp_path)
    rig.add(listed.ollama_tag, [INLINE_BLOB], vision=True)
    service, seen = _recording(tmp_path, rig)

    service.apply(listed.key, min(listed.vram_gb), eyes=False)

    assert seen[0]["tag"] == listed.ollama_tag and seen[0]["vision"] is True and rig.created == []


# ── 화면에 알리는 것 ────────────────────────────────────────────────────────────

def _with_profile(service: SetupService, installed: list[str]) -> SetupService:
    service._profile = {"gpus": [], "ollama": {"installed": installed}}
    service._profile_at = time.monotonic()
    return service


def test_the_card_of_an_installed_model_says_its_pictures_can_be_turned_off(tmp_path: Path) -> None:
    listed = _plain_listed()
    rig = Rig(tmp_path)
    rig.add(listed.ollama_tag, [MODEL_BLOB, EYES_BLOB], vision=True)
    service = _with_profile(_service(tmp_path, rig), [listed.ollama_tag])

    rows = {row["key"]: row for row in service.models()["models"]}

    mine = rows[listed.key]
    assert mine["pictures_optional"] is True and mine["text_only_tag"] == TEXT_ONLY_PREFIX + listed.key
    assert mine["text_only_saves_gb"] == 0.64, "덜 쓰는 메모리는 이 PC 의 부속 파일 크기"
    others = [row for key, row in rows.items() if key != listed.key and not by_projector(key)]
    assert not any(row["pictures_optional"] for row in others), "안 받은 모델은 받아 봐야 안다"


def by_projector(key: str) -> bool:
    return bool(next(model for model in CATALOG if model.key == key).projector_tag)


def test_the_screen_is_told_about_the_model_in_use_even_when_it_is_unlisted(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    reading = _with_profile(_service(tmp_path, rig, chat=PICKED), [])

    assert reading.models()["eyes"] == {"tag": PICKED, "reads_pictures": True, "can_switch": True, "source_tag": PICKED,
                                        "saves_gb": 0.64, "listed": False}

    service, _seen = _recording(tmp_path, rig, chat=PICKED_PLAIN)
    service.apply_tag(PICKED, 49152, eyes=False)

    assert _with_profile(service, []).models()["eyes"] == {
        "tag": PICKED_PLAIN, "reads_pictures": False, "can_switch": True, "source_tag": PICKED, "saves_gb": 0.64, "listed": False}


def test_a_model_with_pictures_inside_is_shown_as_not_switchable(tmp_path: Path) -> None:
    service = _with_profile(_service(tmp_path, Rig(tmp_path), chat=INLINE), [])

    eyes = service.models()["eyes"]

    assert eyes["reads_pictures"] is True and eyes["can_switch"] is False
