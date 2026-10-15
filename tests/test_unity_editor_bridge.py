"""유니티 에디터 다리 (2026-09-27 · 게임 팩 2단계) — 가짜 유니티 소켓으로 실제 프로토콜(인사·8바이트 길이·JSON)을 돈다.

실측에서 잡은 것들을 그대로 시험으로 둔다:
- 다리 겉은 `success` 인데 도구 안이 실패(`result.success: false`)면 실패로 읽는다(번호 찾기가 전부 실패했는데 「됐다」로 읽혔다).
- 되돌리기는 **결과로** 확인한다 — 유니티가 주는 되돌린 작업 이름은 비어 있을 때가 많았다. 사람이 그 뒤에 한 일이 맨 위면
  되살린다(redo).
- 우리 방: 기록은 이 PC 에만. 「같이 보내기」를 켜기 전에는 **한 번도** 밖으로 안 부른다.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.unity_editor import COPLAY_TELEMETRY_URL, PACKAGE_NAME, UnityBridgeError, UnityEditorBridge

REPO = Path(__file__).resolve().parents[1]


class FakeUnity:
    """원본 다리와 같은 말을 하는 작은 유니티. 씬은 dict, Undo 는 목록."""

    def __init__(self) -> None:
        self.objects: dict[int, dict[str, Any]] = {}
        self.undo: list[tuple[str, Any]] = []
        self.redo: list[tuple[str, Any]] = []
        self.next_id = 100
        self.commands: list[dict[str, Any]] = []
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self._stop = True
        self.server.close()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        with conn:
            conn.sendall(b"WELCOME UNITY-MCP 1 FRAMING=1\n")
            try:
                header = conn.recv(8)
                if len(header) < 8:
                    return
                (length,) = struct.unpack(">Q", header)
                body = b""
                while len(body) < length:
                    body += conn.recv(length - len(body))
            except OSError:
                return
            command = json.loads(body.decode("utf-8"))
            self.commands.append(command)
            reply = json.dumps({"status": "success", "result": self.handle(command["type"], command["params"])}).encode("utf-8")
            conn.sendall(struct.pack(">Q", len(reply)) + reply)

    def _find(self, term: str) -> list[int]:
        return [oid for oid, obj in self.objects.items() if obj["name"] == term]

    def handle(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        if kind == "manage_gameobject":
            action = params["action"]
            if action == "create":
                oid = self.next_id
                self.next_id += 1
                self.objects[oid] = {"name": params["name"], "position": params.get("position", [0, 0, 0])}
                self.undo.append(("create", oid))
                self.redo.clear()
                return {"success": True, "data": {"instanceID": oid, "name": params["name"]}}
            target = params["target"]
            ids = [int(target)] if str(target).isdigit() else self._find(str(target))
            if not ids:
                return {"success": False, "error": "not found"}
            oid = ids[0]
            if action == "modify":
                before = dict(self.objects[oid])
                if "position" in params:
                    self.objects[oid]["position"] = params["position"]
                self.undo.append(("modify", (oid, before)))
                return {"success": True, "data": {"instanceID": oid}}
            if action == "delete":
                self.undo.append(("delete", (oid, self.objects.pop(oid))))
                return {"success": True, "data": {"deleted": [oid]}}
        if kind == "find_gameobjects":
            term = str(params["searchTerm"])
            ids = ([int(term)] if int(term) in self.objects else []) if params["searchMethod"] == "by_id" else self._find(term)
            return {"success": True, "data": {"instanceIDs": ids, "totalCount": len(ids)}}
        if kind == "get_gameobject":
            obj = self.objects.get(int(params["instanceID"]))
            return {"success": True, "data": obj} if obj else {"success": False, "error": "Error getting GameObject"}
        if kind == "manage_editor":
            source, target = (self.undo, self.redo) if params["action"] == "undo" else (self.redo, self.undo)
            if not source:
                return {"success": True, "message": "nothing"}
            op, data = source.pop()
            if op == "create":
                if params["action"] == "undo":
                    self._stash = self.objects.pop(data)
                else:
                    self.objects[data] = self._stash
            elif op == "modify":
                oid, before = data
                now = dict(self.objects[oid])
                self.objects[oid] = before
                data = (oid, now)
            elif op == "delete":
                oid, obj = data
                if params["action"] == "undo":
                    self.objects[oid] = obj
                else:
                    self.objects.pop(oid, None)
            target.append((op, data))
            return {"success": True, "data": {"undone_group": ""}}  # ★ 실측: 이름이 비어 온다
        if kind == "manage_scene":
            return {"success": True, "data": {"items": [{"name": obj["name"]} for obj in self.objects.values()]}}
        if kind == "broken":
            return {"success": False, "code": "Exception has been thrown by the target of an invocation."}
        return {"success": True, "data": {}}


@pytest.fixture()
def unity(tmp_path: Path):
    fake = FakeUnity()
    status = tmp_path / "status"
    status.mkdir()
    project = tmp_path / "Game"
    (status / "unity-mcp-status-abcd1234.json").write_text(json.dumps({
        "unity_port": fake.port, "reloading": False, "reason": "ready",
        "project_path": str(project).replace("\\", "/") + "/Assets", "project_name": "Game", "unity_version": "6000.6.3f1",
    }), encoding="utf-8")
    yield fake, status, project
    fake.close()


def _bridge(tmp_path: Path, status: Path, **kwargs: Any) -> UnityEditorBridge:
    config = SimpleNamespace(data_dir=tmp_path / "data", packs_dir=REPO / "packs")
    return UnityEditorBridge(config, None, status_dir=status, **kwargs)


def test_it_finds_the_open_editor_and_talks_the_framed_protocol(tmp_path: Path, unity) -> None:
    fake, status, project = unity
    bridge = _bridge(tmp_path, status)
    editors = bridge.live_editors()
    assert editors and editors[0]["alive"] and editors[0]["port"] == fake.port
    assert editors[0]["project"].lower() == str(project).replace("\\", "/").lower(), "끝의 /Assets 를 뗀 프로젝트 자리"
    out = bridge.look({"what": "hierarchy"})
    assert out["verified"] and fake.commands[-1] == {"type": "manage_scene", "params": {"action": "get_hierarchy", "pageSize": 50, "maxDepth": 3}}


def test_it_only_ever_connects_to_loopback(tmp_path: Path, unity) -> None:
    fake, status, _ = unity
    seen: list[tuple[str, int]] = []

    def connect(address: tuple[str, int], timeout: float):
        seen.append(address)
        return socket.create_connection(address, timeout)

    bridge = _bridge(tmp_path, status, connect=connect)
    bridge.status({})
    assert seen and all(host == "127.0.0.1" for host, _ in seen)


def test_an_inner_tool_failure_is_a_failure(tmp_path: Path, unity) -> None:
    fake, status, _ = unity
    out = _bridge(tmp_path, status).call(fake.port, "broken", {})
    assert out["ok"] is False and "invocation" in out["error"], "겉 status 만 보면 「됐다」로 읽힌다(2026-09-27 실측)"


def test_undo_checks_the_effect_and_restores_a_humans_later_work(tmp_path: Path, unity) -> None:
    fake, status, _ = unity
    bridge = _bridge(tmp_path, status)
    bridge.change({"op": "create", "name": "A", "primitive_type": "Cube"})
    assert bridge.undo({})["undone"] is True and not fake._find("A")

    bridge.change({"op": "create", "name": "B"})
    bridge.change({"op": "modify", "target": "B", "position": [5, 5, 5]})
    assert bridge.undo({})["undone"] is True
    assert fake.objects[fake._find("B")[0]]["position"] == [0, 0, 0] and fake._find("B"), "바꾸기만 되돌리고 만들기는 남는다"

    bridge.change({"op": "delete", "target": "B"})
    assert bridge.undo({})["undone"] is True and fake._find("B"), "지운 것이 돌아온다"

    bridge.change({"op": "create", "name": "C"})
    fake.handle("manage_gameobject", {"action": "create", "name": "HumanMade"})  # 사람이 그 뒤에 한 일
    out = bridge.undo({})
    assert out["undone"] is False and out["restored"] is True
    assert fake._find("C") and fake._find("HumanMade"), "사람의 작업을 지우지 않고 되살렸다"


def test_change_only_forwards_whitelisted_arguments(tmp_path: Path, unity) -> None:
    fake, status, _ = unity
    bridge = _bridge(tmp_path, status)
    bridge.change({"op": "create", "name": "P", "saveAsPrefab": True, "save_as_prefab": True, "prefab_path": "Assets/P.prefab"})
    sent = [c for c in fake.commands if c["type"] == "manage_gameobject"][-1]["params"]
    assert "saveAsPrefab" not in sent and "save_as_prefab" not in sent, "프리팹으로 저장 같은 원본 인자는 이 길로 안 보낸다"
    assert sent["prefabPath"] == "Assets/P.prefab"
    with pytest.raises(ValueError):
        bridge.change({"op": "execute_code", "target": "x"})


def test_the_room_stays_on_this_pc_until_a_person_turns_sharing_on(tmp_path: Path, unity) -> None:
    fake, status, _ = unity
    posted: list[tuple[str, dict[str, Any]]] = []
    bridge = _bridge(tmp_path, status, post=lambda url, payload: posted.append((url, payload)))
    bridge.status({})
    bridge.look({"what": "console"})
    room = bridge.room()
    assert room["calls"] >= 4 and room["share_with_coplay"] is False and posted == [], "기본은 밖으로 0건"
    assert bridge.log_path.is_file()

    bridge.set_share(True)
    bridge.look({"what": "selection"})
    assert len(posted) == 1 and posted[0][0] == COPLAY_TELEMETRY_URL
    payload = posted[0][1]
    assert payload["record"] == "tool_execution" and payload["data"]["tool_name"] == "get_selection"
    assert set(payload["data"]) <= {"tool_name", "sub_action", "success", "duration_ms", "error"}, "내용은 안 보낸다"
    assert bridge.room()["shared_count"] == 1, "보낸 것은 따로 적어 사람이 본다"


def test_link_and_unlink_restore_the_manifest(tmp_path: Path, unity) -> None:
    _, status, _ = unity
    project = tmp_path / "Proj"
    (project / "Packages").mkdir(parents=True)
    original = {"dependencies": {"com.unity.ugui": "2.6.0", PACKAGE_NAME: "https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity"}}
    (project / "Packages" / "manifest.json").write_text(json.dumps(original), encoding="utf-8")
    bridge = _bridge(tmp_path, status)
    assert bridge.install_state(project)["other_version"] is True

    out = bridge.install(project)
    value = json.loads((project / "Packages" / "manifest.json").read_text(encoding="utf-8"))["dependencies"][PACKAGE_NAME]
    assert value.startswith("file:") and "unity-mcp" in value and Path(out["backup"]).is_file()
    assert (bridge.installed_copy() / "Editor" / "OntelicLock.cs").is_file(), "사용자 데이터 폴더에 사본을 둔다(앱 폴더가 바뀌어도 그대로)"
    assert bridge.install_state(project)["installed"] is True

    bridge.install(project)  # 두 번 이어도 맨 처음 값을 기억한다
    assert bridge.uninstall(project)["removed"] is True
    restored = json.loads((project / "Packages" / "manifest.json").read_text(encoding="utf-8"))["dependencies"]
    assert restored == original["dependencies"], "풀면 원래 줄로 돌아간다"


def test_not_connected_says_what_to_press(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, tmp_path / "nowhere")
    with pytest.raises(UnityBridgeError) as error:
        bridge.look({"what": "hierarchy"})
    assert "에디터 잇기" in str(error.value)


# ── 스토어판에서는 연결 부품을 유니티가 볼 수 있는 자리에 둔다 (2026-10-12) ─────────────────────────────
# 스토어판으로 게임 팩을 처음 쓴 사람의 화면이 「에디터가 패키지를 읽는 중」에서 안 넘어갔다. 스토어 앱이 자기 데이터 폴더
# (AppData)에 새로 만든 파일은 그 앱만 보는 전용 칸으로 간다 — 프로젝트 설정에 적어 준 폴더에 유니티가 가 보면 아무것도 없다.
# 2026-09-18 에 Ollama 가 같은 까닭으로 모델을 못 올려 엔진 자리를 사용자 폴더로 옮겼는데, 이 사본은 빠져 있었다.


def _manifest_value(project: Path) -> str:
    return json.loads((project / "Packages" / "manifest.json").read_text(encoding="utf-8"))["dependencies"][PACKAGE_NAME]


def _empty_project(tmp_path: Path, name: str = "Proj") -> Path:
    project = tmp_path / name
    (project / "Packages").mkdir(parents=True)
    (project / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": {"com.unity.ugui": "2.6.0"}}), encoding="utf-8")
    return project


def test_a_store_install_keeps_the_copy_where_unity_can_read_it(tmp_path: Path, unity) -> None:
    _, status, _ = unity
    home = tmp_path / "home"
    project = _empty_project(tmp_path)
    data = tmp_path / "data"
    bridge = _bridge(tmp_path, status, home=home, hidden=lambda path: str(path).startswith(str(data)))

    bridge.install(project)

    copy = bridge.installed_copy()
    assert str(copy).startswith(str(home)) and not str(copy).startswith(str(data)), "데이터 폴더(전용 칸) 밖 — 사용자 폴더"
    assert (copy / "package.json").is_file()
    value = _manifest_value(project)
    assert value == "file:" + str(copy).replace("\\", "/")
    state = bridge.install_state(project)
    assert state["installed"] is True and state["broken"] is False


def test_outside_the_store_nothing_moves(tmp_path: Path, unity) -> None:
    _, status, _ = unity
    project = _empty_project(tmp_path)
    bridge = _bridge(tmp_path, status, home=tmp_path / "home", hidden=lambda path: False)
    bridge.install(project)
    assert str(bridge.installed_copy()).startswith(str(tmp_path / "data")), "설치형 · 개발 실행은 예전 자리 그대로"
    assert bridge.install_state(project)["broken"] is False


def test_a_link_that_points_into_the_private_folder_is_called_broken_and_linking_again_repairs_it(tmp_path: Path, unity) -> None:
    _, status, _ = unity
    home = tmp_path / "home"
    data = tmp_path / "data"
    project = _empty_project(tmp_path)
    # 예전 판이 적어 둔 줄 — 데이터 폴더 속(스토어판에서는 유니티가 못 보는 자리)을 가리킨다.
    stale = "file:" + str(data / "packs" / "game" / "unity-mcp" / "10.2.0-ontelic.4" / "MCPForUnity").replace("\\", "/")
    manifest = project / "Packages" / "manifest.json"
    manifest.write_text(json.dumps({"dependencies": {PACKAGE_NAME: stale}}), encoding="utf-8")
    bridge = _bridge(tmp_path, status, home=home, hidden=lambda path: str(path).startswith(str(data)))

    state = bridge.install_state(project)
    assert state["installed"] is True and state["broken"] is True, "이어 두었지만 유니티가 못 읽는다"

    bridge.install(project)                                  # 「다시 잇기」
    assert _manifest_value(project).startswith("file:" + str(home).replace("\\", "/"))
    assert bridge.install_state(project)["broken"] is False
    # 풀면 줄이 사라진다 — 우리가 적었던 못 읽는 줄을 「원래 값」으로 되살리지 않는다.
    assert bridge.uninstall(project)["removed"] is True
    assert PACKAGE_NAME not in json.loads(manifest.read_text(encoding="utf-8"))["dependencies"]
