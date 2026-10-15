from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.person_search import PersonSearch, PersonSearchTools
from alture_jarvis.tool_gateway import ToolGateway

FRAME_WIDTH = 1035
FRAME_HEIGHT = 1840


def _frame() -> np.ndarray:
    return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)


class FakeController:
    def __init__(self) -> None:
        self.pans: list[tuple[str, float]] = []
        self.recentered = 0
        self.returned = 0

    def return_to_camera_view(self, **_: object) -> dict:
        self.returned += 1
        return {"ok": True}

    def recenter(self) -> dict:
        self.recentered += 1
        return {"ok": True}

    def pan(self, direction: str, *, seconds: float = 1.0, **_: object) -> dict:
        self.pans.append((direction, seconds))
        return {"ok": True}


class FakeVision:
    """Serves a scripted sequence of frames, one per look."""

    def __init__(self, people_per_step: list[int] | None = None) -> None:
        self.people_per_step = people_per_step or []
        self.looks = 0
        self.sequence = 0

    def latest_frame(self) -> tuple[Any, int]:
        return _frame(), self.sequence

    def wait_for_frame_after(self, sequence: int, timeout: float = 5.0) -> tuple[Any, int]:
        self.sequence = sequence + 1
        return _frame(), self.sequence

    def detect_people(self, frame: Any) -> list[tuple[int, int, int, int]]:
        index = min(self.looks, len(self.people_per_step) - 1) if self.people_per_step else 0
        count = self.people_per_step[index] if self.people_per_step else 0
        self.looks += 1
        return [(400, 800, 600, 1400)] * count


class FakeMatch:
    def __init__(self, name: str, similarity: float, box=(400, 800, 600, 1400)) -> None:
        self.name = name
        self.similarity = similarity
        self.box = box

    def to_dict(self) -> dict:
        return {"name": self.name, "similarity": self.similarity, "box": list(self.box)}


class FakeIdentity:
    threshold = 0.363

    def __init__(self, script: list[list[FakeMatch]] | None = None, registry=("가람",)) -> None:
        self.script = script or []
        self.calls = 0
        self._registry = {name: [[0.0]] for name in registry}

    def load_registry(self) -> dict:
        return self._registry

    def identify(self, frame: Any) -> list[FakeMatch]:
        result = self.script[self.calls] if self.calls < len(self.script) else []
        self.calls += 1
        return result


def _search(vision: FakeVision, identity: Any = None, **kwargs) -> tuple[PersonSearch, FakeController]:
    controller = FakeController()
    # settle_sec=0: the real sweep waits for the gimbal to stop wobbling, which
    # is 20+ seconds of nothing per test here.
    kwargs.setdefault("settle_sec", 0.0)
    return PersonSearch(controller, vision, identity, **kwargs), controller


# ── the sweep shape ──────────────────────────────────────────────────────────
def test_the_sweep_is_asymmetric_because_the_gimbal_is() -> None:
    # Measured: about 3 one-second holds of travel to the left of home and
    # about 13 to the right. A symmetric sweep spends half its time pressing
    # against a mechanical stop and never sees the right-hand side of the room.
    search, controller = _search(FakeVision([0] * 40), left_steps=3, right_steps=16)
    search.find(None)
    lefts = [step for step in controller.pans if step[0] == "left"]
    rights = [step for step in controller.pans if step[0] == "right"]
    assert len(lefts) == 3
    assert len(rights) == 19, "must cross back over the left travel and then the right"


def test_the_sweep_starts_by_looking_where_it_already_points() -> None:
    # Driving to the far left before looking at all makes the camera appear
    # broken when the person is standing right in front of it.
    search, controller = _search(FakeVision([0] * 40))
    search.find(None)
    assert controller.recentered == 1
    assert controller.returned == 1


def test_a_quiet_step_does_not_end_the_sweep() -> None:
    # Panning right, holds 8 and 9 moved the picture by 8.1 and 0.32 against a
    # noise floor of 1.15, then hold 10 moved it 52.7. Any "the picture stopped
    # changing, so we are at the limit" rule stops halfway and reports an empty
    # room. The sweep therefore walks a measured budget and never guesses.
    search, controller = _search(FakeVision([0] * 40), left_steps=3, right_steps=16)
    result = search.find(None)
    assert result["steps"] == 23, "every planned stop must be looked at"
    assert len(controller.pans) == 22


def test_finding_the_target_stops_the_sweep_early() -> None:
    # Nobody for two looks, then 가람 on the third.
    identity = FakeIdentity([[], [], [FakeMatch("가람", 0.71)]])
    search, controller = _search(FakeVision([1] * 40), identity)
    result = search.find("가람", track=False)
    assert result["found"] is True
    assert result["steps"] == 3
    assert len(controller.pans) == 2, "kept sweeping after finding them"


# ── never claim a find without the number ────────────────────────────────────
def test_a_find_always_carries_its_similarity() -> None:
    # The project has already had a model announce an action it never took. A
    # sweep result that says "found" without the score behind it invites the
    # same sentence with nothing underneath it.
    identity = FakeIdentity([[FakeMatch("가람", 0.68)]])
    search, _ = _search(FakeVision([1] * 40), identity)
    result = search.find("가람", track=False)
    assert result["similarity"] == 0.68
    assert result["threshold"] == 0.363


def test_a_near_miss_is_distinguishable_from_an_empty_room() -> None:
    # 0.35 against a 0.363 bar and 0.0 are completely different situations, and
    # a bare "not found" collapses them into the same answer.
    identity = FakeIdentity([[FakeMatch("(unknown)", 0.35)]] + [[]] * 40)
    search, _ = _search(FakeVision([1] * 40), identity)
    result = search.find("가람", track=False)
    assert result["found"] is False
    assert result["similarity"] is None
    assert result["best_similarity_seen"] == 0.35


def test_an_unregistered_name_is_refused_before_moving_anything() -> None:
    search, controller = _search(FakeVision(), FakeIdentity(registry=("나래",)))
    with pytest.raises(ValueError, match="unknown_person"):
        search.find("가람")
    assert controller.pans == []


def test_asking_for_a_person_without_face_models_says_so() -> None:
    search, _ = _search(FakeVision(), None)
    with pytest.raises(ValueError, match="face_recognition_unavailable"):
        search.find("가람")


def test_sweeping_for_anyone_works_without_face_recognition() -> None:
    search, _ = _search(FakeVision([0, 0, 2] + [0] * 40), None)
    result = search.find(None)
    assert result["people_seen"] >= 2


# ── centring on the subject ──────────────────────────────────────────────────
class CenteringVision(FakeVision):
    """Moves the subject towards the middle as the controller pans."""

    def __init__(self, boxes: list[tuple[int, int, int, int]]) -> None:
        super().__init__()
        self.boxes = boxes
        self.index = 0

    def detect_people(self, frame: Any) -> list[tuple[int, int, int, int]]:
        box = self.boxes[min(self.index, len(self.boxes) - 1)]
        self.index += 1
        return [box]


def test_centering_pans_towards_the_subject_and_stops_when_close() -> None:
    # Subject far right, then near the middle after one correction.
    vision = CenteringVision([(500, 800, 560, 1400)])
    search, controller = _search(vision)
    result = search.center_on((900, 800, 1000, 1400), _frame())
    assert result["centered"] is True
    assert controller.pans and controller.pans[0][0] == "right"


def test_centering_reports_the_offsets_it_achieved() -> None:
    vision = CenteringVision([(500, 800, 560, 1400)])
    search, _ = _search(vision)
    result = search.center_on((900, 800, 1000, 1400), _frame())
    # "가운데 뒀습니다" has to be checkable against something.
    assert len(result["offsets"]) >= 2
    assert abs(result["offsets"][-1]) < abs(result["offsets"][0])


def test_centering_flips_direction_when_the_preview_is_mirrored() -> None:
    # Whether panning right moves a subject left depends on Mimo's mirror
    # toggle. Assuming the sign gives a loop that drives the subject out of
    # frame while reporting progress, so the first correction is measured.
    vision = CenteringVision([(1000, 800, 1030, 1400), (500, 800, 560, 1400)])
    search, controller = _search(vision)
    result = search.center_on((900, 800, 1000, 1400), _frame())
    assert result["mirrored"] is True
    assert [step[0] for step in controller.pans][:2] == ["right", "left"]


def test_losing_the_subject_stops_rather_than_panning_on_blindly() -> None:
    class LosesThem(FakeVision):
        def detect_people(self, frame: Any) -> list:
            return []

    search, controller = _search(LosesThem())
    result = search.center_on((900, 800, 1000, 1400), _frame())
    assert result["ok"] is False
    assert result["error"] == "subject_lost_after_move"
    assert len(controller.pans) == 1, "kept moving after losing them"


# ── tools ────────────────────────────────────────────────────────────────────
def _tools(**overrides) -> tuple[PersonSearchTools, FakeController]:
    config = JarvisConfig(camera_control_enabled=True, face_recognition_enabled=True, **overrides)
    identity = FakeIdentity()
    search, controller = _search(FakeVision([1] * 40), identity)
    return PersonSearchTools(config, search, identity), controller


def test_registering_a_face_needs_approval() -> None:
    # It is the one tool here that writes a colleague's face to disk rather
    # than moving a camera, so it does not run on a spoken sentence alone.
    gateway = ToolGateway(JobStore(":memory:"), EventBus())
    tools, _ = _tools()
    tools.register(gateway)
    by_name = {row["name"]: row for row in gateway.list_tools()}
    assert by_name["camera_register_face"]["risk_level"] == RiskLevel.L2.label()
    assert by_name["camera_find_person"]["risk_level"] == RiskLevel.L1.label()
    assert by_name["camera_who_is_there"]["risk_level"] == RiskLevel.L0.label()


def test_tools_disappear_when_face_recognition_is_off() -> None:
    config = JarvisConfig(camera_control_enabled=True, face_recognition_enabled=False)
    search, _ = _search(FakeVision())
    tools = PersonSearchTools(config, search, None)
    assert tools.names == set()
    assert tools.ollama_tools == []


def test_who_is_there_reports_scores_alongside_names() -> None:
    tools, controller = _tools()
    tools.identity.script = [[FakeMatch("가람", 0.72)]]  # type: ignore[attr-defined]
    report = tools.who_is_there({})
    assert report["matches"][0]["similarity"] == 0.72
    assert report["threshold"] == 0.363
    assert controller.pans == [], "looking must not move the camera"


class FlakyController(FakeController):
    """Fails the first screen read, as a burst of dump contention does."""

    def __init__(self, failures: int = 1) -> None:
        super().__init__()
        self.failures = failures
        self.attempts = 0

    def return_to_camera_view(self, **_: object) -> dict:
        self.attempts += 1
        if self.attempts <= self.failures:
            from alture_jarvis.android_bridge import AdbError

            raise AdbError("ui_dump_failed:adb_failed:shell uiautomator dump")
        return super().return_to_camera_view()


def test_a_burst_of_dump_failures_does_not_lose_the_whole_sweep() -> None:
    # Screen reads fail in bursts while the capture runs, and one such burst
    # killed a real 40-second sweep at the setup step.
    from alture_jarvis.person_search import PersonSearch

    controller = FlakyController(failures=1)
    search = PersonSearch(controller, FakeVision([0] * 40), None, settle_sec=0.0)
    result = search.find(None)
    assert result["ok"] is True
    assert controller.attempts == 2


def test_a_persistent_failure_still_surfaces() -> None:
    # Retrying forever would hide a tablet that is genuinely gone.
    from alture_jarvis.android_bridge import AdbError
    from alture_jarvis.person_search import PersonSearch

    controller = FlakyController(failures=99)
    search = PersonSearch(controller, FakeVision([0] * 40), None, settle_sec=0.0)
    with pytest.raises(AdbError, match="sweep_setup_failed"):
        search.find(None)


# ── registering somebody nobody has met ──────────────────────────────────────
class RegistryIdentity(FakeIdentity):
    """Records what got registered, so the guards can be asserted."""

    def __init__(self, script, registry=("가람",)) -> None:
        super().__init__(script, registry)
        self.registered: list[tuple[str, int]] = []

    def register(self, name: str, images: list[Any]) -> dict:
        self.registered.append((name, len(images)))
        self._registry[name] = [[0.0]]
        return {"ok": True, "name": name, "added": len(images), "total": len(images), "skipped": []}


def _new_person_tools(script, registry=("가람",)):
    identity = RegistryIdentity(script, registry)
    search, controller = _search(FakeVision([1] * 40), identity)
    config = JarvisConfig(camera_control_enabled=True, face_recognition_enabled=True)
    return PersonSearchTools(config, search, identity), identity, controller


def test_a_stranger_is_found_and_registered() -> None:
    # The point of the flow: the new person does not have to come and stand in
    # front of the camera, the camera goes and finds them.
    tools, identity, _ = _new_person_tools([[], [FakeMatch("(unknown)", 0.08)]])
    result = tools.register_new_person({"name": "나래"})
    assert result["registered"] is True
    assert identity.registered[0][0] == "나래"
    # The evidence that they really were new, not a second copy of 가람.
    assert result["similarity_to_known"] == 0.08
    assert result["threshold"] == 0.363
    assert result["known_before"] == ["가람"]


def test_nothing_is_registered_when_everyone_is_already_known() -> None:
    tools, identity, _ = _new_person_tools([[FakeMatch("가람", 0.81)]] * 40)
    result = tools.register_new_person({"name": "나래"})
    assert result["registered"] is False
    assert result["reason"] == "no_unfamiliar_face"
    assert identity.registered == []


def test_two_strangers_at_once_is_refused_rather_than_guessed() -> None:
    # Registering the wrong face under a real name poisons every later answer,
    # and picking the bigger one is exactly how that happens.
    strangers = [FakeMatch("(unknown)", 0.05), FakeMatch("(unknown)", 0.07)]
    tools, identity, _ = _new_person_tools([strangers])
    result = tools.register_new_person({"name": "나래"})
    assert result["registered"] is False
    assert result["reason"] == "several_unfamiliar_faces"
    assert result["count"] == 2
    assert identity.registered == []


def test_a_face_too_small_to_embed_is_not_a_stranger() -> None:
    # identify() labels an unembeddable face "(too_small)". Treating that as a
    # new person registers a smudge under someone's name.
    tools, identity, _ = _new_person_tools([[FakeMatch("(too_small)", 0.0)]] * 40)
    result = tools.register_new_person({"name": "나래"})
    assert result["registered"] is False
    assert result["reason"] == "no_unfamiliar_face"
    assert identity.registered == []


def test_registering_a_name_that_already_exists_is_refused() -> None:
    tools, identity, controller = _new_person_tools([[FakeMatch("(unknown)", 0.05)]])
    with pytest.raises(ValueError, match="already_registered"):
        tools.register_new_person({"name": "가람"})
    assert identity.registered == []
    assert controller.pans == [], "swept the room before noticing the name was taken"


def test_the_new_person_is_registered_from_several_frames() -> None:
    # One frame pins the registration to a single pose and a single light.
    tools, identity, _ = _new_person_tools([[FakeMatch("(unknown)", 0.05)]])
    tools.register_new_person({"name": "나래"})
    assert identity.registered[0][1] >= 3


def test_the_new_person_tool_also_needs_approval() -> None:
    gateway = ToolGateway(JobStore(":memory:"), EventBus())
    tools, _, _ = _new_person_tools([[]])
    tools.register(gateway)
    by_name = {row["name"]: row for row in gateway.list_tools()}
    assert by_name["camera_register_new_person"]["risk_level"] == RiskLevel.L2.label()


def test_centering_undershoots_rather_than_hunting() -> None:
    # Aiming for the whole error overshot on the device and oscillated:
    # 0.54 -> -0.30 -> 0.21 -> -0.09, four moves to do the work of two.
    from alture_jarvis.person_search import PAN_PX_PER_SEC, PersonSearch

    width = 1035
    seconds = PersonSearch._seconds_to_close(0.54, width)
    moved_px = (seconds + 0.23) * PAN_PX_PER_SEC
    needed_px = 0.54 * width / 2
    assert moved_px < needed_px, "a correction that overshoots will hunt"
    assert moved_px > needed_px * 0.4, "and one that barely moves will never arrive"


def test_a_tiny_offset_still_produces_a_usable_hold() -> None:
    # Below the dead time a pan does nothing at all, so corrections must not be
    # scaled down into no-ops.
    assert PersonSearch._seconds_to_close(0.01, 1035) >= 0.15


def test_the_tool_description_tells_the_model_to_call_now_not_later() -> None:
    # Measured live: the description used to end with "시간이 걸린다는 걸 먼저
    # 알리고 시작하라" ("announce it first, then start"), and the model read
    # that as license to answer "찾아볼게요" and stop -- agent_trace showed
    # zero tool calls. The instruction has to make it unambiguous that the
    # call happens in the same turn, not a promised one.
    tools, _ = _tools()
    definition = next(d for d in tools.ollama_tools if d["function"]["name"] == "camera_find_person")
    description = definition["function"]["description"]
    assert "지금 바로 호출" in description
    assert "먼저" not in description or "미루지 마" in description
