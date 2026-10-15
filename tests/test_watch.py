"""초소가 **언제 말을 걸고 언제 조용한가.**

알림은 두 주면 무시당한다. 그러니 이 파일이 지키는 것은 하나다:
**말할 이유가 있을 때만 말한다.**
"""

from __future__ import annotations

import time

from alture_jarvis.watch import (
    Change,
    Watch,
    WatchStore,
    diff,
    fingerprint,
    items_of,
    should_notify,
)


def step(url: str = "", title: str = "") -> dict:
    return {"tool": "browser_extract", "ok": True, "evidence": {"url": url, "title": title}}


class TestWhatWeCompare:
    def test_we_compare_evidence_not_prose(self) -> None:
        """★ 모델의 답을 비교하면 매번 다르다. 도구가 가져온 것을 본다."""
        steps = [step("https://kmong.com/gig/1?ref=abc", "공고 하나"), step("", "")]
        assert items_of(steps) == ["https://kmong.com/gig/1|공고 하나"]

    def test_tracking_params_are_stripped(self) -> None:
        """같은 것이 매번 다른 주소로 보이면 지문이 매번 달라진다."""
        a = items_of([step("https://a.com/x?utm=1", "제목")])
        b = items_of([step("https://a.com/x?utm=2", "제목")])
        assert a == b

    def test_order_does_not_matter(self) -> None:
        a = items_of([step("https://a.com/1", "가"), step("https://a.com/2", "나")])
        b = items_of([step("https://a.com/2", "나"), step("https://a.com/1", "가")])
        assert fingerprint(a) == fingerprint(b)

    def test_same_sighting_same_fingerprint(self) -> None:
        assert fingerprint(["a", "b"]) == fingerprint(["a", "b"])
        assert fingerprint(["a"]) != fingerprint(["a", "b"])


class TestDiff:
    def test_removed_counts_too(self) -> None:
        """새로 생긴 것만 보면 「공고가 내려갔다」를 놓친다."""
        change = diff(["a", "b"], ["b", "c"])
        assert change.added == ["c"]
        assert change.removed == ["a"]
        assert change.changed

    def test_nothing_changed(self) -> None:
        change = diff(["a"], ["a"])
        assert not change.changed
        assert change.note() == "달라진 것 없음"

    def test_note_leads_with_numbers(self) -> None:
        assert diff([], ["a", "b"]).note() == "새로 2건"


class TestWhenToSpeak:
    def test_first_run_is_a_baseline_not_a_notice(self) -> None:
        """★ 처음 본 것은 전부 새것이다. 그때 알리면 알림이 무의미하게 커진다."""
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=3600)
        assert should_notify(watch, diff([], ["a", "b", "c"])) is False

    def test_after_baseline_a_change_speaks(self) -> None:
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=3600, baseline_done=True)
        assert should_notify(watch, diff(["a"], ["a", "b"])) is True

    def test_no_change_stays_quiet(self) -> None:
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=3600, baseline_done=True)
        assert should_notify(watch, diff(["a"], ["a"])) is False

    def test_disabled_watch_is_never_due(self) -> None:
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=60, enabled=False)
        assert watch.due(time.time() + 10_000) is False

    def test_interval_floor_protects_the_site(self) -> None:
        """1분마다 훑으면 사이트가 막는다. 바닥은 10분."""
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=60, last_run_at=time.time())
        assert watch.due(time.time() + 120) is False
        assert watch.due(time.time() + 601) is True


class TestNoiseMeter:
    def test_ratio_is_silent_until_there_is_a_sample(self) -> None:
        """3건으로 비율을 말하지 않는다 — 이 저장소의 규율."""
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=3600, notices=3, acted=0)
        assert watch.noise_ratio() is None

    def test_ratio_shows_when_the_sample_is_enough(self) -> None:
        watch = Watch(id="w1", name="크몽", prompt="…", every_sec=3600, notices=10, acted=4)
        assert watch.noise_ratio() == 0.6


class TestStore:
    def test_round_trip_through_the_file(self, tmp_path) -> None:
        path = tmp_path / "watches.json"
        store = WatchStore(path)
        store.add(Watch(id="w1", name="크몽 신규", prompt="크몽에서 …", every_sec=3600))
        again = WatchStore(path)
        assert again.get("w1") is not None
        assert again.get("w1").name == "크몽 신규"

    def test_first_run_sets_the_baseline_and_says_nothing(self, tmp_path) -> None:
        store = WatchStore(tmp_path / "w.json")
        watch = store.add(Watch(id="w1", name="크몽", prompt="…", every_sec=3600))
        change = store.record_run(watch, ["a", "b"])
        assert change.added == ["a", "b"]
        assert should_notify(watch, change) is False
        assert watch.baseline_done is True

    def test_second_run_speaks_only_about_the_difference(self, tmp_path) -> None:
        store = WatchStore(tmp_path / "w.json")
        watch = store.add(Watch(id="w1", name="크몽", prompt="…", every_sec=3600))
        store.record_run(watch, ["a", "b"])
        change = store.record_run(watch, ["b", "c"])
        assert should_notify(watch, change) is True
        assert change.added == ["c"] and change.removed == ["a"]

    def test_removing_a_watch(self, tmp_path) -> None:
        store = WatchStore(tmp_path / "w.json")
        store.add(Watch(id="w1", name="x", prompt="…", every_sec=3600))
        assert store.remove("w1") is True
        assert store.remove("w1") is False


class TestARunThatNeverLooked:
    """★ 빈손에는 두 종류가 있다.

    "봤는데 0건"은 관측이고, "못 봤다"는 관측이 아니다. 섞으면 초소가 눈을 감는다.

    2026-08-20 실측: 위시켓 초소의 판이 **cancelled** 였고(걸음 0개) 그 빈손이
    기준선으로 적혔다(`watching 0`). 그대로 뒀으면 다음 관찰에서 위시켓에 뭐가
    있든 전부 "새로 N건"으로 알렸을 것이다 — 첫 알림부터 거짓이다.
    """

    def test_a_cancelled_run_is_not_an_observation(self) -> None:
        from alture_jarvis.watch import observed

        assert observed("cancelled", []) is False

    def test_a_failed_run_is_not_an_observation(self) -> None:
        from alture_jarvis.watch import observed

        assert observed("failed", []) is False

    def test_completing_without_calling_a_single_tool_is_not_an_observation(self) -> None:
        """도구를 한 번도 안 부르고 끝난 판은 **지어낸 것**이다. 근거가 없다."""
        from alture_jarvis.watch import observed

        assert observed("completed", []) is False

    def test_a_real_zero_result_page_IS_an_observation(self) -> None:
        """검색 결과가 진짜 0건인 사이트를 "못 봤다"로 몰면 그 초소는 영원히
        기준선을 못 잡는다. 걸음이 있으면 관측으로 친다."""
        from alture_jarvis.watch import observed

        assert observed("completed", [{"tool": "browser_open", "ok": True}]) is True


class TestAMissedRunLeavesTheBaselineAlone:
    def _store(self, tmp_path) -> WatchStore:
        return WatchStore(tmp_path / "watch.json")

    def _watch(self) -> Watch:
        return Watch(id="w1", name="위시켓", prompt="봐줘", every_sec=3600)

    def test_a_missed_first_run_does_not_become_the_baseline(self, tmp_path) -> None:
        """이게 위시켓에서 실제로 일어난 일이다."""
        store = self._store(tmp_path)
        watch = store.add(self._watch())
        store.record_missed(watch)

        assert watch.baseline_done is False, "못 본 판이 기준선이 됐다"
        assert watch.last_items == []
        assert watch.missed == 1

    def test_the_next_real_run_becomes_the_baseline_and_stays_quiet(self, tmp_path) -> None:
        store = self._store(tmp_path)
        watch = store.add(self._watch())
        store.record_missed(watch)

        change = store.record_run(watch, ["https://wishket.com/1|프로젝트"])
        assert change.baseline is True
        assert should_notify(watch, change) is False, "기준선을 알림으로 냈다"
        assert watch.baseline_done is True

    def test_a_missed_run_does_not_wipe_an_existing_baseline(self, tmp_path) -> None:
        """★ 사이트가 한 번 막았다고 지금까지 본 것을 잊으면, 복구된 다음 판이
        통째로 "새로 N건"이 된다."""
        store = self._store(tmp_path)
        watch = store.add(self._watch())
        store.record_run(watch, ["a|가", "b|나"])
        store.record_missed(watch)

        assert watch.last_items == ["a|가", "b|나"]
        change = store.record_run(watch, ["a|가", "b|나"])
        assert change.changed is False, "막힌 판 뒤에 헛알림이 났다"

    def test_a_missed_run_still_moves_the_clock_forward(self, tmp_path) -> None:
        """시각을 안 밀면 못 본 초소가 매 틱마다 다시 돈다."""
        store = self._store(tmp_path)
        watch = store.add(self._watch())
        watch.last_run_at = 0.0
        before = time.time()
        store.record_missed(watch)
        assert watch.last_run_at >= before

    def test_missed_survives_a_reload(self, tmp_path) -> None:
        """눈 감은 초소는 재시작해도 눈을 감고 있다 — 그 사실이 남아야 한다."""
        store = self._store(tmp_path)
        watch = store.add(self._watch())
        store.record_missed(watch)

        reloaded = WatchStore(tmp_path / "watch.json").get("w1")
        assert reloaded is not None
        assert reloaded.missed == 1
        assert reloaded.baseline_done is False
