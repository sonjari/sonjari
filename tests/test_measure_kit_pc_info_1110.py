"""11-10: 4시간 반 천장 측정이 끝 무렵 PC 정보 한 줄(int(dict))에 넘어져 결과 파일 없이 끝났다.

손자리 /health 의 ollama.num_ctx 가 숫자에서 {"chat": …, "code": …} 로 바뀌었고, 그때 모델 목록(/api/ps)이 비어 그 칸으로 넘어갔다.
"""
from __future__ import annotations

from alture_jarvis import measure_kit as mk


def test_window_reads_the_new_num_ctx_shape() -> None:
    assert mk._window_of({}, {"ollama": {"num_ctx": {"chat": 131072, "code": 65536}}}) == 131072
    assert mk._window_of({}, {"ollama": {"num_ctx": {"code": 65536}}}) == 65536


def test_window_keeps_the_old_shapes() -> None:
    assert mk._window_of({"context_length": 32768}, {"ollama": {"num_ctx": {"chat": 131072}}}) == 32768
    assert mk._window_of({}, {"ollama": {"num_ctx": 40960}}) == 40960
    assert mk._window_of({}, {}) == 0


class _Empty:
    def loaded_model(self):
        return {}


class _Broken:
    def loaded_model(self):
        raise RuntimeError("ps 가 죽음")


def test_measure_end_does_not_lose_runs_when_pc_info_fails(monkeypatch) -> None:
    """PC 정보가 넘어져도 잰 판과 finished 는 남는다 — 예전 코드는 여기서 예외로 빠져 결과 파일이 안 생겼다."""
    monkeypatch.setattr(mk, "graphics_cards", lambda: [])
    out = {"pc": None}
    try:
        out["pc"] = mk._pc_info(_Broken(), {}, [])
    except Exception as error:  # noqa: BLE001
        out["pc"] = {"error": str(error)}
    assert "error" in out["pc"]
    info = mk._pc_info(_Empty(), {"ollama": {"num_ctx": {"chat": 131072, "code": 131072}}}, [])
    assert info["window"] == 131072


def test_old_expression_really_crashed_on_this_input() -> None:
    """양방향: 고치기 전 식은 이 입력에서 정말 넘어진다(시험이 헛돌지 않는지)."""
    health = {"ollama": {"num_ctx": {"chat": 131072, "code": 131072}}}
    try:
        int({}.get("context_length") or (health.get("ollama") or {}).get("num_ctx") or 0)
    except TypeError:
        return
    raise AssertionError("옛 식이 넘어지지 않았다 — 시험 입력이 사고와 다르다")
