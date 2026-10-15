"""Sweep the room with the gimbal and report who was seen, with numbers.

This is the thing the whole screen-capture switch was for: over RTMP the camera
could be watched or aimed but never both, so "look around until you find
someone" was impossible. Watching the tablet's screen instead leaves Mimo on
its camera view, where the joystick still exists, and the loop below can look,
move, and look again.

Three measured facts shape it, and all three are easy to get wrong:

  * **The travel is asymmetric.** From the recentred home position the gimbal
    reaches its stop after roughly a quarter as much travel to the left as to
    the right. A sweep written symmetrically spends half its time pushing
    against a stop and never sees the right-hand side of the room.

  * **A step sometimes does nothing.** Panning right, two consecutive holds
    moved the picture by 8.1 and 0.32 (noise is ~1.2) and the next moved it
    52.7. So a quiet step is not the end of the travel, and treating it as one
    stops the sweep halfway with a confident "nobody here".

  * **Most of a short pan is dead time.** See the constants below. This is what
    made the original sweep crawl, and it is why the steps here are long.

Because of the second point this does not try to detect the limits at all. It
walks a budget measured off the real device, and reports what it saw at each
stop. Detecting limits live costs frames and, as above, gets the answer wrong.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .android_bridge import AdbError
from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

# Why the steps are long and few, measured on the real device:
#
#   * A pan has ~0.85s of dead time before the gimbal moves at all -- three adb
#     round trips (DOWN, MOVE, UP) at ~230ms each. That cost is per pan, not
#     per second of pan.
#   * Once moving, the view travels ~379 px/s across a 1035px frame.
#
# So a 1.0s hold advanced the view by only ~14% of a frame width while paying
# the full overhead: consecutive scans overlapped by 86% and the sweep crawled.
# A 2.5s hold advances ~70% instead -- still a 30% overlap, so nobody falls
# between two looks -- and covers the same room in a third of the stops.
#
# Scanning *during* the motion was tested and does not work: sharpness drops
# from 20 to 4-9 (about 75% of the detail) while the gimbal is moving, and face
# embedding needs that detail. Hence stop-look-stop, just with fewer stops.
#
# Config rather than constants in the code path: a remount or a different room
# changes these, and then they would be wrong everywhere at once.
DEFAULT_LEFT_STEPS = 1
DEFAULT_RIGHT_STEPS = 4
STEP_SECONDS = 2.5

# After a pan, the gimbal is still settling and the h264 stream is still
# catching up. Scanning immediately reads a motion-blurred frame.
SETTLE_AFTER_PAN_SEC = 0.6

# Measured rotation, used to size a centring correction rather than guessing at
# it: the view travels ~379 px/s once moving, and the stick stays deflected for
# the requested hold plus the ~0.23s it takes the release to reach the tablet.
PAN_PX_PER_SEC = 379.0
PAN_RELEASE_LATENCY_SEC = 0.23
# Correct only part of the error each time. Aiming for the whole of it
# overshot and oscillated on the real device -- 0.54 -> -0.30 -> 0.21 -> -0.09,
# four moves to do the work of two. Undershooting converges; overshooting
# hunts, and every extra correction costs a pan and a look.
CENTERING_GAIN = 0.6


@dataclass
class Observation:
    step: int
    heading: int
    people: int
    matches: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "heading": self.heading, "people": self.people, "matches": self.matches}


class PersonSearch:
    """Look around the room, optionally for one particular person."""

    def __init__(
        self,
        controller: Any,
        vision: Any,
        identity: Any | None = None,
        *,
        left_steps: int = DEFAULT_LEFT_STEPS,
        right_steps: int = DEFAULT_RIGHT_STEPS,
        step_seconds: float = STEP_SECONDS,
        settle_sec: float = SETTLE_AFTER_PAN_SEC,
    ) -> None:
        self.controller = controller
        self.vision = vision
        self.identity = identity
        self.left_steps = max(0, left_steps)
        self.right_steps = max(1, right_steps)
        self.step_seconds = step_seconds
        self.settle_sec = settle_sec

    # ── one look ─────────────────────────────────────────────────────────────
    def _scan(self, step: int, heading: int, target: str | None) -> tuple[Observation, Any, dict[str, Any] | None]:
        """Grab a frame that is definitely newer than the last move, and read it."""
        _, sequence = self.vision.latest_frame()
        frame, _ = self.vision.wait_for_frame_after(sequence, timeout=5.0)
        if frame is None:
            return Observation(step, heading, 0), None, None

        people = self.vision.detect_people(frame)
        observation = Observation(step, heading, len(people))
        hit: dict[str, Any] | None = None
        # No point running face recognition on a frame with nobody in it, and
        # skipping it keeps the sweep quick across empty parts of the room.
        if people and self.identity is not None:
            try:
                matches = self.identity.identify(frame)
            except Exception as exc:
                observation.matches = [{"error": str(exc)[:120]}]
                return observation, frame, None
            observation.matches = [match.to_dict() for match in matches]
            for match in matches:
                if target is None or match.name != target:
                    continue
                if hit is None or match.similarity > hit["similarity"]:
                    hit = match.to_dict()
        return observation, frame, hit

    def _prepare(self, *, attempts: int = 2) -> None:
        """Get to the camera view and back to home before sweeping.

        Retried as a unit because both steps read the screen, and screen reads
        fail in bursts while the capture is running -- a whole 40-second sweep
        died on one such burst. Losing the sweep to a transient is worse than
        waiting a couple of seconds and asking again.
        """
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                self.controller.return_to_camera_view()
                self.controller.recenter()
                time.sleep(max(self.settle_sec, 1.5) if self.settle_sec else 0.0)
                return
            except AdbError as exc:
                last = exc
                time.sleep(2.0 * (attempt + 1) if self.settle_sec else 0.0)
        raise AdbError(f"sweep_setup_failed:{last}")

    # ── the sweep ────────────────────────────────────────────────────────────
    def find(self, target: str | None = None, *, track: bool = True) -> dict[str, Any]:
        """Sweep left-to-right, stopping early if `target` turns up.

        The return value always carries the similarity score behind the
        decision. A caller -- or a model writing the sentence the user hears --
        must not be able to say "found 사용자" without that number existing.
        """
        if target and self.identity is None:
            raise ValueError("face_recognition_unavailable: 얼굴 모델이 없어 특정 인물은 못 찾습니다")
        if target:
            registered = self.identity.load_registry()
            if target not in registered:
                raise ValueError(
                    f"unknown_person:{target} (등록된 사람: {', '.join(sorted(registered)) or '없음'})"
                )

        self._prepare()

        observations: list[Observation] = []
        heading = 0
        found: dict[str, Any] | None = None
        found_frame: Any = None
        best_seen = 0.0

        def look(step: int) -> bool:
            nonlocal found, found_frame, best_seen
            observation, frame, hit = self._scan(step, heading, target)
            observations.append(observation)
            for match in observation.matches:
                best_seen = max(best_seen, float(match.get("similarity") or 0.0))
            if hit is not None:
                found, found_frame = hit, frame
                return True
            return False

        # Start where it already points: the person asked about is often right
        # there, and a sweep that always drives to the far left first looks
        # broken even when it works.
        step = 0
        if look(step):
            return self._result(target, found, found_frame, observations, best_seen, track, heading)

        for _ in range(self.left_steps):
            self.controller.pan("left", seconds=self.step_seconds)
            time.sleep(self.settle_sec)
            step += 1
            heading -= 1
            if look(step):
                return self._result(target, found, found_frame, observations, best_seen, track, heading)

        for _ in range(self.left_steps + self.right_steps):
            self.controller.pan("right", seconds=self.step_seconds)
            time.sleep(self.settle_sec)
            step += 1
            heading += 1
            if look(step):
                return self._result(target, found, found_frame, observations, best_seen, track, heading)

        return self._result(target, None, None, observations, best_seen, track, heading)

    def _result(
        self,
        target: str | None,
        found: dict[str, Any] | None,
        frame: Any,
        observations: list[Observation],
        best_seen: float,
        track: bool,
        heading: int,
    ) -> dict[str, Any]:
        people_seen = sum(observation.people for observation in observations)
        tracking: dict[str, Any] | None = None
        if found is not None and track:
            tracking = self.center_on(found["box"], frame)
        return {
            "ok": True,
            "target": target,
            "found": found is not None,
            # The number the decision was made on, present either way. Without
            # it "못 찾았습니다" cannot be told apart from "얼굴 모델이 아무것도
            #못 봤습니다", and a near miss looks identical to a clear absence.
            "similarity": found["similarity"] if found else None,
            "threshold": getattr(self.identity, "threshold", None),
            "best_similarity_seen": round(best_seen, 4),
            "heading": heading,
            "steps": len(observations),
            "people_seen": people_seen,
            "tracking": tracking,
            "observations": [observation.to_dict() for observation in observations],
        }

    # ── finding somebody nobody has met ──────────────────────────────────────
    def find_unregistered(self, *, samples: int = 5) -> dict[str, Any]:
        """Sweep until a face turns up that matches nobody already on file.

        For "신규 인원 등록": rather than making the new person come and stand
        in front of the camera, the camera goes and finds them.

        Two things are deliberately refused rather than guessed at, because
        both write the wrong face under a real name and every later answer
        inherits the mistake:

          * nobody unfamiliar in the room -- register nothing, say so
          * more than one unfamiliar face in the same view -- which one was
            meant? Ask instead of picking

        The evidence for "this is somebody new" is a number: the best
        similarity their face scored against everyone already registered. Below
        the threshold means unfamiliar, and that figure is returned so the
        claim can be checked rather than believed.
        """
        if self.identity is None:
            raise ValueError("face_recognition_unavailable: 얼굴 모델이 없습니다")
        known = sorted(self.identity.load_registry())
        self._prepare()

        heading = 0
        observations: list[Observation] = []
        checked = 0

        def inspect() -> dict[str, Any] | None:
            nonlocal checked
            _, sequence = self.vision.latest_frame()
            frame, _ = self.vision.wait_for_frame_after(sequence, timeout=5.0)
            if frame is None:
                return None
            people = self.vision.detect_people(frame)
            observation = Observation(len(observations), heading, len(people))
            observations.append(observation)
            if not people:
                return None
            matches = self.identity.identify(frame)
            observation.matches = [match.to_dict() for match in matches]
            checked += len(matches)
            # "(too_small)" is a face we could not embed, not a stranger.
            strangers = [m for m in matches if m.name == "(unknown)"]
            if not strangers:
                return None
            if len(strangers) > 1:
                return {
                    "ambiguous": True,
                    "count": len(strangers),
                    "similarities": [round(m.similarity, 4) for m in strangers],
                }
            return {"ambiguous": False, "match": strangers[0], "frame": frame}

        hit = inspect()
        for direction, count in (("left", self.left_steps), ("right", self.left_steps + self.right_steps)):
            if hit is not None:
                break
            for _ in range(count):
                self.controller.pan(direction, seconds=self.step_seconds)
                time.sleep(self.settle_sec)
                heading += -1 if direction == "left" else 1
                hit = inspect()
                if hit is not None:
                    break

        base = {
            "known": known,
            "heading": heading,
            "steps": len(observations),
            "faces_checked": checked,
            "threshold": self.identity.threshold,
        }
        if hit is None:
            return {**base, "found": False, "reason": "no_unfamiliar_face"}
        if hit["ambiguous"]:
            return {
                **base,
                "found": False,
                "reason": "several_unfamiliar_faces",
                "count": hit["count"],
                "similarities": hit["similarities"],
            }

        # Gather a few frames of them rather than the one that caught them: a
        # single frame pins the registration to one pose and one bit of light.
        frames = [hit["frame"]]
        _, sequence = self.vision.latest_frame()
        for _ in range(max(0, samples - 1)):
            frame, sequence = self.vision.wait_for_frame_after(sequence, timeout=5.0)
            if frame is not None:
                frames.append(frame)
            time.sleep(0.35)
        return {
            **base,
            "found": True,
            # How close they came to being somebody we already know. Low is the
            # point: it is what makes "새로운 사람" a measurement.
            "similarity_to_known": round(hit["match"].similarity, 4),
            "box": list(hit["match"].box),
            "frames": frames,
        }

    # ── keeping the subject centred ──────────────────────────────────────────
    #
    # Mimo's own ActiveTrack turned out to be unreachable over ADB: a tap, a
    # drag, a held box drag, a long press and a double tap on `id/tracking` all
    # left the screen byte-for-byte unchanged (preview change 1.1-1.9 against a
    # noise floor of 1.15, and not one new node in the tree). `id/tracking` is
    # clickable=false, a custom touch view like the joystick, and even the
    # held-touch shape that worked for the joystick does nothing here.
    #
    # So the subject is centred with the gimbal we already control instead.
    # That is better than it sounds: it is our loop, every correction is
    # verifiable, and it does not rest on an undocumented gesture that a Mimo
    # update could take away.

    def center_on(
        self,
        box: list[int] | tuple[int, ...],
        frame: Any,
        *,
        max_corrections: int = 3,
        deadband: float = 0.12,
    ) -> dict[str, Any]:
        """Pan until the subject sits near the middle of the frame.

        The direction mapping is *checked, not assumed*: whether panning right
        moves a subject left in the picture depends on the preview's mirror
        setting (`fpv_liveview_mirror` is a real toggle on this screen). So the
        first correction is measured, and if the offset grew instead of
        shrinking the mapping is inverted for the rest. Assuming the sign would
        produce a loop that confidently drives the subject out of frame.
        """
        if frame is None:
            return {"ok": False, "error": "no_frame"}
        width = frame.shape[1]
        offset = self._offset(box, width)
        history = [round(offset, 4)]
        inverted = False
        corrections = 0

        for _ in range(max_corrections):
            if abs(offset) <= deadband:
                break
            direction = "right" if (offset > 0) != inverted else "left"
            seconds = self._seconds_to_close(abs(offset), width)
            try:
                self.controller.pan(direction, seconds=seconds)
            except AdbError as exc:
                return {"ok": False, "error": str(exc)[:160], "offsets": history}
            corrections += 1
            time.sleep(self.settle_sec)

            _, sequence = self.vision.latest_frame()
            frame, _ = self.vision.wait_for_frame_after(sequence, timeout=5.0)
            found = self._largest_person(frame)
            if found is None:
                # Lost them. Say so rather than continuing to pan on a stale
                # position, which is how a follow loop walks off into a wall.
                return {
                    "ok": False,
                    "error": "subject_lost_after_move",
                    "offsets": history,
                    "corrections": corrections,
                }
            previous, offset = offset, self._offset(found, frame.shape[1])
            history.append(round(offset, 4))
            if corrections == 1 and abs(offset) > abs(previous) + 0.02:
                inverted = True

        return {
            "ok": abs(offset) <= deadband,
            "centered": abs(offset) <= deadband,
            # The numbers behind the claim, so "가운데 뒀습니다" is checkable.
            "offset": round(offset, 4),
            "offsets": history,
            "deadband": deadband,
            "corrections": corrections,
            "mirrored": inverted,
        }

    @staticmethod
    def _seconds_to_close(offset: float, width: int) -> float:
        """How long to hold the stick to close `offset` (0..1) of half a frame.

        Derived from the measured rotation rate rather than a tuned constant,
        and deliberately short of the full correction -- see CENTERING_GAIN.
        """
        pixels = offset * (width / 2.0)
        needed = pixels / PAN_PX_PER_SEC - PAN_RELEASE_LATENCY_SEC
        return max(0.15, min(1.2, CENTERING_GAIN * needed))

    @staticmethod
    def _offset(box: list[int] | tuple[int, ...], width: int) -> float:
        """How far the box's centre sits from the frame's, as -1..1."""
        centre = (int(box[0]) + int(box[2])) / 2.0
        return (centre - width / 2.0) / max(1.0, width / 2.0)

    def _largest_person(self, frame: Any) -> tuple[int, int, int, int] | None:
        if frame is None:
            return None
        people = self.vision.detect_people(frame)
        if not people:
            return None
        return max(people, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))


class PersonSearchTools:
    """Sweeping and face recognition, exposed to the model."""

    def __init__(self, config: JarvisConfig, search: PersonSearch, identity: Any | None) -> None:
        self.config = config
        self.search = search
        self.identity = identity
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or []},
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "camera_find_person",
                "사무실 카메라를 좌우로 훑으며 사람을 찾는다. "
                "'사용자 좀 봐봐', '다른 사용자이 어디 있나 찾아봐'처럼 특정 인물을 찾을 때는 name을 채우고, "
                "'누구 있나 둘러봐'처럼 아무나 찾을 때는 비워둔다. "
                "느리다: 한 스텝에 6초쯤 걸려서 찾는 데 1~2분, 아무도 못 찾고 한 바퀴 다 돌면 2분 15초쯤 된다. "
                "이 도구를 지금 바로 호출하라 — 먼저 '찾아보겠습니다'라고만 답하고 도구 호출은 "
                "다음 턴으로 미루지 마라. 시간이 걸린다는 안내는 이 도구가 끝난 뒤 결과를 "
                "전달하는 답변에 자연스럽게 넣으면 된다.",
                {
                    "name": {
                        "type": "string",
                        "description": "찾을 사람 이름. 등록된 사람만 가능. 아무나 찾으면 생략",
                    }
                },
            ),
            self._function(
                "camera_who_is_there",
                "카메라를 움직이지 않고, 지금 보이는 화면에 누가 있는지만 확인한다.",
                {},
            ),
            self._function(
                "camera_register_face",
                "지금 카메라에 보이는 사람의 얼굴을 이름과 함께 등록한다. "
                "등록해야 나중에 그 사람을 찾을 수 있다. 화면에 그 사람만 있어야 한다.",
                {"name": {"type": "string", "description": "등록할 사람 이름"}},
                ["name"],
            ),
            self._function(
                "camera_register_new_person",
                "카메라가 방을 훑어서 **아직 등록되지 않은 사람**을 찾아 그 이름으로 등록한다. "
                "'신규 인원 등록', '새로 온 사람 등록해줘'처럼 새 사람을 추가할 때 쓴다. "
                "그 사람이 카메라 앞에 와 있지 않아도 된다 — 카메라가 찾아간다. "
                "이미 등록된 사람만 보이면 아무것도 등록하지 않고 그렇게 알려준다.",
                {"name": {"type": "string", "description": "새로 등록할 사람 이름"}},
                ["name"],
            ),
            self._function(
                "camera_forget_face",
                "등록된 얼굴을 지운다.",
                {"name": {"type": "string", "description": "지울 사람 이름"}},
                ["name"],
            ),
        ]

    @property
    def enabled(self) -> bool:
        return bool(self.config.face_recognition_enabled and self.config.camera_control_enabled)

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions) if self.enabled else []

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self.ollama_tools}

    # ── handlers ─────────────────────────────────────────────────────────────
    def find_person(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name") or "").strip() or None
        return self.search.find(name)

    def who_is_there(self, _: dict[str, Any] | None = None) -> dict[str, Any]:
        frame, _sequence = self.search.vision.latest_frame()
        if frame is None:
            return {"ok": False, "error": "no_frame", "people": 0, "matches": []}
        people = self.search.vision.detect_people(frame)
        matches: list[dict[str, Any]] = []
        if self.identity is not None:
            try:
                matches = [match.to_dict() for match in self.identity.identify(frame)]
            except Exception as exc:
                return {"ok": False, "error": str(exc)[:160], "people": len(people), "matches": []}
        return {
            "ok": True,
            "people": len(people),
            # Scores travel with the names. A model handed only names will
            # state them as fact; handed the numbers it can hedge honestly.
            "matches": matches,
            "threshold": getattr(self.identity, "threshold", None),
        }

    def register_face(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("empty_name: 등록할 이름이 필요합니다")
        if self.identity is None:
            raise ValueError("face_recognition_unavailable")
        # Several frames over a couple of seconds rather than one: a single
        # frame pins the person to one pose and one bit of lighting, and the
        # office camera will not see either again.
        frames: list[Any] = []
        _, sequence = self.search.vision.latest_frame()
        for _ in range(5):
            frame, sequence = self.search.vision.wait_for_frame_after(sequence, timeout=5.0)
            if frame is not None:
                frames.append(frame)
            time.sleep(0.4)
        if not frames:
            raise ValueError("no_frames: 카메라 영상이 없습니다")
        return self.identity.register(name, frames)

    def register_new_person(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("empty_name: 등록할 이름이 필요합니다")
        if self.identity is None:
            raise ValueError("face_recognition_unavailable")
        if name in self.identity.load_registry():
            raise ValueError(
                f"already_registered:{name} — 다시 등록하려면 먼저 지워야 합니다"
            )

        outcome = self.search.find_unregistered()
        if not outcome["found"]:
            # Nothing was written. Say which of the two "no" answers this is:
            # an empty room and an ambiguous one need different next moves.
            return {
                "ok": False,
                "registered": False,
                "reason": outcome["reason"],
                **{k: v for k, v in outcome.items() if k not in ("frames", "found")},
            }

        frames = outcome.pop("frames")
        result = self.identity.register(name, frames)
        return {
            "ok": True,
            "registered": True,
            "name": name,
            # The evidence that this really was somebody new, not a second copy
            # of someone already on file.
            "similarity_to_known": outcome["similarity_to_known"],
            "threshold": outcome["threshold"],
            "known_before": outcome["known"],
            "heading": outcome["heading"],
            "steps": outcome["steps"],
            "embeddings": result["added"],
            "skipped": result["skipped"],
        }

    def forget_face(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("empty_name")
        if self.identity is None:
            raise ValueError("face_recognition_unavailable")
        return self.identity.forget(name)

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "camera_find_person": self.find_person,
            "camera_who_is_there": self.who_is_there,
            "camera_register_face": self.register_face,
            "camera_register_new_person": self.register_new_person,
            "camera_forget_face": self.forget_face,
        }
        risks = {
            # Sweeping moves the camera and is undone by recentering, like the
            # other gimbal tools.
            "camera_find_person": RiskLevel.L1,
            "camera_who_is_there": RiskLevel.L0,
            # L2 on purpose: this writes a colleague's face to disk. It is the
            # one thing here that is about a person rather than a camera, and
            # one approval click is a fair price for that.
            "camera_register_face": RiskLevel.L2,
            "camera_register_new_person": RiskLevel.L2,
            "camera_forget_face": RiskLevel.L1,
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=self.enabled,
                )
            )
