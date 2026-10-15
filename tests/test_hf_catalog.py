"""허깅페이스에서 직접 고르기 — 내려받기 전에 아는 것만으로 거른다 (2026-10-01 밤).

실측 값(같은 날 허깅페이스 API): unsloth/Qwen3.8-27B-GGUF 는 구조 qwen35 · 27.3B · 템플릿에 tools,
UD-IQ3_S 12.04GB · UD-Q3_K_XL 13.15GB · UD-IQ4_XS 14.25GB · UD-Q4_K_M 16.46GB. 16GB 카드 실사용 14.9GB.
"""

from __future__ import annotations

from alture_jarvis.hf_catalog import HfCatalog, best_bits_for, bits_of, fit_of

TEMPLATE_WITH_TOOLS = "{%- if tools %}<tools>{{ tools }}</tools>{%- endif %}"

LIST = [
    {"id": "unsloth/Qwen3.8-27B-GGUF", "downloads": 6271224, "likes": 4767, "lastModified": "2026-09-20T00:00:00Z",
     "pipeline_tag": "image-text-to-text",
     "gguf": {"total": 27_320_697_856, "architecture": "qwen35", "context_length": 262144,
              "chat_template": TEMPLATE_WITH_TOOLS}},
    {"id": "someone/no-tools-7B-GGUF", "downloads": 10,
     "gguf": {"total": 7_000_000_000, "chat_template": "{{ messages }}"}},
    {"id": "big/Huge-235B-GGUF", "downloads": 10,
     "gguf": {"total": 235_000_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
    {"id": "bad id with spaces", "gguf": {"total": 1, "chat_template": TEMPLATE_WITH_TOOLS}},
]

TREE = [
    {"path": "Qwen3.8-27B-UD-IQ3_S.gguf", "size": 12_040_000_000},
    {"path": "Qwen3.8-27B-UD-Q3_K_XL.gguf", "size": 13_150_000_000},
    {"path": "Qwen3.8-27B-UD-IQ4_XS.gguf", "size": 14_250_000_000},
    {"path": "Qwen3.8-27B-UD-Q4_K_M.gguf", "size": 16_460_000_000},
    {"path": "mmproj-F16.gguf", "size": 900_000_000},
    {"path": "BF16/Qwen3.8-27B-BF16-00001-of-00002.gguf", "size": 50_000_000_000},
    {"path": "README.md", "size": 100},
]


def _catalog(fail: bool = False) -> HfCatalog:
    def fetch(url: str):
        if fail:
            raise OSError("HTTP Error 403: Forbidden")
        return TREE if "/tree/main" in url else LIST
    return HfCatalog(fetch=fetch)


def test_search_keeps_only_models_that_can_work_and_fit() -> None:
    found = _catalog().search("qwen", 14.9)
    assert found["ok"]
    assert [m["repo"] for m in found["models"]] == ["unsloth/Qwen3.8-27B-GGUF"]
    assert found["hidden"] == {"no_tools": 1, "too_big": 1}
    model = found["models"][0]
    assert model["best_bits"] == 3 and model["params_b"] == 27.3 and model["vision"] is True


def test_files_are_sorted_and_judged_against_the_card() -> None:
    files = _catalog().files("unsloth/Qwen3.8-27B-GGUF", 14.9)["files"]
    assert [f["quant"] for f in files] == ["UD-IQ3_S", "UD-Q3_K_XL", "UD-IQ4_XS", "UD-Q4_K_M"]
    # 화면 읽기 부속(mmproj-F16 0.9GB)을 더한 크기로 판정한다 — Ollama 가 같이 받아 같이 올린다(10-01 실측 13.15 → 14.08).
    assert [f["gb"] for f in files] == [12.94, 14.05, 15.15, 17.36]
    assert [f["fit"] for f in files] == ["fits", "tight", "over", "over"]
    assert files[0]["tag"] == "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S"


def test_blocked_network_says_so_instead_of_an_empty_list() -> None:
    assert _catalog(fail=True).search("", 14.9)["error"] == "hf_unreachable"
    assert _catalog(fail=True).files("unsloth/Qwen3.8-27B-GGUF", 14.9)["error"] == "hf_unreachable"


def test_a_repo_name_with_odd_characters_is_refused() -> None:
    assert _catalog().files("../etc/passwd", 14.9)["error"] == "bad_repo"


def test_small_helpers() -> None:
    assert bits_of("UD-IQ3_S") == 3 and bits_of("Q4_K_M") == 4 and bits_of("BF16") == 16
    assert fit_of(12.0, 14.9) == "fits" and fit_of(14.25, 14.9) == "tight" and fit_of(16.5, 14.9) == "over"
    assert best_bits_for(9_000_000_000, 14.9) >= 8 and best_bits_for(235_000_000_000, 14.9) == 0


def test_recommendations_follow_the_written_rule() -> None:
    """추천은 규칙이다(잰 것 아님): 믿을 만한 제작자 · 개조판 아님 · 3비트 이상 · 같은 모델은 한 번. 양자화는 여유 있게 들어가는 것 중 가장 큰 것."""
    rows = [
        {"id": "unsloth/Qwen3.8-27B-GGUF", "downloads": 9, "gguf": {"total": 27_300_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
        {"id": "lmstudio-community/Qwen3.8-27B-GGUF", "downloads": 8, "gguf": {"total": 27_300_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
        {"id": "someone/Qwen3.8-27B-Uncensored-GGUF", "downloads": 99, "gguf": {"total": 27_300_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
        {"id": "bartowski/Qwen_Qwen3.5-9B-GGUF", "downloads": 5, "gguf": {"total": 9_000_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
    ]
    found = HfCatalog(fetch=lambda url: rows).search("", 14.9)
    picked = [m["repo"] for m in found["models"] if m["recommended"]]
    assert picked == ["unsloth/Qwen3.8-27B-GGUF", "bartowski/Qwen_Qwen3.5-9B-GGUF"]
    by = {m["repo"]: m for m in found["models"]}
    assert by["someone/Qwen3.8-27B-Uncensored-GGUF"]["modded"] is True
    assert by["bartowski/Qwen_Qwen3.5-9B-GGUF"]["measured_family"] == "Qwen 3.5 9B"
    files = _catalog().files("unsloth/Qwen3.8-27B-GGUF", 14.9)["files"]
    assert [f["quant"] for f in files if f["recommended"]] == ["UD-IQ3_S"]


def test_code_upgrade_offers_a_bigger_model_only_when_it_fits_and_helps() -> None:
    """대표 10-01 밤: 16GB 는 9B 메인, 코드 일에는 큰 모델을 권한다. 규칙 추천이라 measured=False 로 적는다."""
    from alture_jarvis.hf_catalog import code_upgrade, params_in_tag

    offer = code_upgrade(14.9, "qwen3.5:9b")
    assert offer and offer["tag"].endswith(":UD-IQ3_S") and offer["measured"] is False and "규칙" in offer["basis"]
    assert code_upgrade(23.5, "qwen3.5:9b")["tag"].endswith(":UD-Q4_K_M")
    assert code_upgrade(5.0, "qwen3.5:4b") is None          # 6GB 노트북엔 안 들어간다
    assert code_upgrade(23.5, "qwen3.6:35b-a3b") is None     # 이미 크다
    assert code_upgrade(14.9, "my-custom-model") is None      # 크기를 모르면 권하지 않는다
    assert params_in_tag("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL") == 27


def test_pulling_for_code_applies_to_the_code_role_only(tmp_path) -> None:
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.model_setup import SetupService

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    service = SetupService(config, post=lambda *a, **k: {}, get=lambda url: {}, stream=lambda url, body: iter([{"status": "success"}]),
                           publish=lambda e, p: None)
    seen: list[tuple] = []
    service.select = lambda tag, role="chat", num_ctx=0: seen.append(("select", tag, role, num_ctx)) or {"ok": True}  # type: ignore[method-assign]
    service.apply_tag = lambda tag, num_ctx=32768: seen.append(("apply_tag", tag, num_ctx)) or {"ok": True}  # type: ignore[method-assign]
    service._pull = lambda key, tag, after=None: after() if after else None  # type: ignore[method-assign]
    import threading

    started = threading.Thread.start
    threading.Thread.start = lambda self: self.run()  # type: ignore[method-assign]
    try:
        assert service.start_pull_tag("hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL", 65536, "code")["ok"]
    finally:
        threading.Thread.start = started  # type: ignore[method-assign]
    assert seen == [("select", "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL", "code", 65536)]


def test_new_versions_win_and_one_model_is_recommended_once() -> None:
    """「Ornith」로 찾자 1.0 9B 가 1.5 9B 와 나란히 추천됐고, 같은 27B 가 unsloth·ISTA-DASLab 두 번 추천됐다(10-01 밤)."""
    from alture_jarvis.hf_catalog import family_key, version_of

    assert version_of("Ornith-1.5-9B-GGUF") == 1.5 and version_of("Qwen3.8-27B-GGUF") == 3.8 and version_of("gemma-4-12b-it-GGUF") == 4
    assert family_key("Ornith-1.0-35B-GGUF") == family_key("Ornith-1.5-35B-A3B-GGUF")
    assert family_key("Qwen3.8-27B-GGUF") == family_key("Qwen3.8-27B-GSQ-RCO-GGUF")
    rows = [
        {"id": "ornith-ai/Ornith-1.5-9B-GGUF", "downloads": 5, "gguf": {"total": 9_000_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
        {"id": "ornith-ai/Ornith-1.0-9B-GGUF", "downloads": 9, "gguf": {"total": 9_000_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
        {"id": "unsloth/Qwen3.8-27B-GGUF", "downloads": 8, "gguf": {"total": 27_300_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
        {"id": "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", "downloads": 7, "gguf": {"total": 27_300_000_000, "chat_template": TEMPLATE_WITH_TOOLS}},
    ]
    found = HfCatalog(fetch=lambda url: rows).search("", 14.9)
    assert {m["repo"] for m in found["models"] if m["recommended"]} == {"unsloth/Qwen3.8-27B-GGUF", "ornith-ai/Ornith-1.5-9B-GGUF"}


def test_vision_comes_from_the_projector_file_not_the_tag() -> None:
    """10-03 레딧 댓글(「태그를 믿지 말고 실제를 봐라」): lmstudio-community 9B 는 태그가 비었는데 mmproj 가 있었다."""
    from alture_jarvis.hf_catalog import vision_of

    assert vision_of({"pipeline_tag": None, "siblings": [{"rfilename": "Qwen3.5-9B-Q4_K_M.gguf"},
                                                        {"rfilename": "mmproj-Qwen3.5-9B-BF16.gguf"}]}) is True
    # 태그는 그림이라는데 부속이 없으면 Ollama 로는 그림을 못 본다.
    assert vision_of({"pipeline_tag": "image-text-to-text", "siblings": [{"rfilename": "a-Q4_K_M.gguf"}]}) is False
    # 파일 목록이 안 왔을 때만(옛 응답) 태그로 짐작한다.
    assert vision_of({"pipeline_tag": "image-text-to-text"}) is True
    assert _catalog().files("unsloth/Qwen3.8-27B-GGUF", 14.9)["vision"] is True


def test_mradermacher_is_recommended_only_when_the_original_is_official() -> None:
    """mradermacher 는 무엇이든 양자화한다 — 이름 거름망을 통과한 것도 대부분 파생판이었다(10-03 실측). 원본으로 거른다."""
    def row(repo: str, base: str, downloads: int) -> dict:
        return {"id": repo, "downloads": downloads, "cardData": {"base_model": base},
                "gguf": {"total": 9_000_000_000, "chat_template": TEMPLATE_WITH_TOOLS}}

    rows = [
        row("mradermacher/Qwen3.5-9B-Claude-Opus-Reasoning-Distilled-GGUF", "Jackrong/Qwen3.5-9B-Claude-Distilled", 99),
        row("mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF", "huihui-ai/Huihui-Qwen3.5-9B-abliterated", 98),
        row("mradermacher/Cyber-Ornith-1.5-9B-OBLITERATED-i1-GGUF", "someone/Cyber-Ornith-1.5-9B-OBLITERATED", 97),
        row("mradermacher/granite-4.1-8b-GGUF", "ibm-granite/granite-4.1-8b", 5),
    ]
    found = HfCatalog(fetch=lambda url: rows).search("", 14.9)
    picked = [m["repo"] for m in found["models"] if m["recommended"]]
    assert picked == ["mradermacher/granite-4.1-8b-GGUF"]
    by = {m["repo"]: m for m in found["models"]}
    assert by["mradermacher/Cyber-Ornith-1.5-9B-OBLITERATED-i1-GGUF"]["modded"] is True


# ── 「추천」 대신 「확인한 사실」 (2026-10-03 레딧 댓글 Quiet-Harbor1234) ──────────────────────────────────
def test_checks_say_only_what_was_verified() -> None:
    from alture_jarvis.hf_catalog import checks_of

    assert checks_of({"author": "Qwen"}) == ["official"]
    assert checks_of({"author": "unsloth", "base_authors": ["qwen"]}) == ["official_base"]
    # 원본 중 하나라도 공식이 아니면 「공식 원본」이라고 적지 않는다.
    assert checks_of({"author": "unsloth", "base_authors": ["qwen", "someone"]}) == []
    assert checks_of({"author": "unsloth", "base_authors": []}) == []
    assert checks_of({"author": "unsloth", "pc_measured": {"ceiling": 32768}}) == ["pc_measured"]
    # 개조판·다시 가르친 파생판도 카드에 원본을 공식으로 적는다 — 「공식 원본」은 그대로 양자화하는 곳만(10-03 실측).
    assert checks_of({"author": "huihui-ai", "repo": "huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF", "base_authors": ["qwen"]}) == []
    assert checks_of({"author": "JonathanColetti", "repo": "JonathanColetti/Qwen3.8-27B-Uncensored-GGUF", "base_authors": ["qwen"]}) == []
    assert checks_of({"author": "bartowski", "repo": "bartowski/Qwen3.8-27B-abliterated-GGUF", "base_authors": ["qwen"]}) == []


def test_this_pc_measurement_shows_on_the_model_and_the_exact_quant() -> None:
    ceilings = {
        # Ollama 가 소문자로 적어도 같은 것으로 본다.
        "hf.co/unsloth/qwen3.8-27b-gguf:ud-iq3_s": {
            "ok": True, "ceiling": 65536,
            "steps": [{"num_ctx": 32768, "passed": True, "tokens_per_sec": 41.2},
                      {"num_ctx": 65536, "passed": True, "tokens_per_sec": 40.1}]},
        # 고르기만 하고 잰 적 없는 줄은 「실측」이 아니다.
        "hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL": {"model": "x", "chosen": 32768},
        "qwen3.5:9b": {"ceiling": 131072, "steps": [{"num_ctx": 131072, "passed": True}]},
    }

    def fetch(url: str):
        return TREE if "/tree/main" in url else LIST

    catalog = HfCatalog(fetch=fetch, measured=lambda: ceilings)
    model = catalog.search("qwen", 14.9)["models"][0]
    assert model["pc_measured"] == {"quant": "UD-IQ3_S", "ceiling": 65536, "tokens_per_sec": 41.2}
    assert "pc_measured" in model["checks"]
    files = {f["quant"]: f for f in catalog.files("unsloth/Qwen3.8-27B-GGUF", 14.9)["files"]}
    assert files["UD-IQ3_S"]["pc_measured"] == {"ceiling": 65536, "tokens_per_sec": 41.2}
    assert "pc_measured" not in files["UD-Q3_K_XL"]


def test_a_broken_measurement_record_does_not_hide_the_list() -> None:
    def boom():
        raise OSError("locked")

    catalog = HfCatalog(fetch=lambda url: TREE if "/tree/main" in url else LIST, measured=boom)
    found = catalog.search("qwen", 14.9)
    assert found["ok"] and found["models"][0]["checks"] == []


def test_headroom_follows_the_context_we_will_promise() -> None:
    """레딧 Quiet-Harbor1234 (10-03): 여유는 적용할 대화 길이에서. 64K 로 올릴 거면 64K 의 KV 여유로 판정한다."""
    from alture_jarvis.hf_catalog import run_margin_gb

    assert run_margin_gb(32768) == 1.2
    assert run_margin_gb(65536) == 2.0
    assert run_margin_gb(131072) == 3.6
    at32 = {f["quant"]: f["fit"] for f in _catalog().files("unsloth/Qwen3.8-27B-GGUF", 16.0)["files"]}
    found64 = _catalog().files("unsloth/Qwen3.8-27B-GGUF", 16.0, 65536)
    at64 = {f["quant"]: f["fit"] for f in found64["files"]}
    # 14.05GB(Q3_K_XL + 부속)는 32K 면 여유 있게, 64K 면 빠듯하다.
    assert at32["UD-Q3_K_XL"] == "fits" and at64["UD-Q3_K_XL"] == "tight"
    assert found64["ctx"] == 65536 and found64["margin_gb"] == 2.0
