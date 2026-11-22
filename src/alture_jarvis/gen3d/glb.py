"""GLB 를 직접 읽는다 — 위치 · 삼각형 · UV · 바탕색 그림 (2026-11-14).

trimesh 같은 큰 꾸러미를 새로 넣지 않는다(본체 의존성은 numpy · Pillow 뿐). glTF 2.0 바이너리 규격에서 우리가 쓰는 만큼만:
삼각형(mode 4) 기본 도형 · 노드 변환(matrix 또는 TRS) · 접근자 성분 float/uint8/uint16/uint32 · byteStride.
"""
from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GlbError(ValueError):
    pass


@dataclass
class Mesh:
    positions: np.ndarray            # (N, 3) float64 — 노드 변환을 적용한 월드 좌표(glTF 는 y 위 · 미터)
    faces: np.ndarray                # (M, 3) int64
    uv: np.ndarray | None = None     # (N, 2) 또는 없음
    texture: Any = None              # PIL.Image 또는 없음(첫 재질의 바탕색 그림)

    @property
    def bbox(self) -> tuple[np.ndarray, np.ndarray]:
        if not len(self.positions):
            zero = np.zeros(3)
            return zero, zero
        return self.positions.min(axis=0), self.positions.max(axis=0)


def _chunks(data: bytes) -> tuple[dict[str, Any], bytes]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise GlbError("glb 머리가 아니다")
    _magic, version, length = struct.unpack_from("<4sII", data, 0)
    if version != 2:
        raise GlbError(f"glTF {version} 판은 안 읽는다(2 만)")
    offset, gltf, binary = 12, None, b""
    while offset + 8 <= min(length, len(data)):
        size, kind = struct.unpack_from("<II", data, offset)
        body = data[offset + 8: offset + 8 + size]
        if kind == 0x4E4F534A:      # JSON
            gltf = json.loads(body.decode("utf-8"))
        elif kind == 0x004E4942:    # BIN
            binary = body
        offset += 8 + size
    if gltf is None:
        raise GlbError("JSON 덩어리가 없다")
    return gltf, binary


def _accessor(gltf: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    dtype = np.dtype(_COMPONENT[int(acc["componentType"])])
    width = _WIDTH[str(acc["type"])]
    count = int(acc["count"])
    if "bufferView" not in acc:
        return np.zeros((count, width), dtype=dtype)
    view = gltf["bufferViews"][int(acc["bufferView"])]
    if int(view.get("buffer", 0)) != 0:
        raise GlbError("바깥 버퍼(.bin 파일)는 안 읽는다")
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride", 0)) or dtype.itemsize * width
    if stride == dtype.itemsize * width:
        out = np.frombuffer(binary, dtype=dtype, count=count * width, offset=start).reshape(count, width)
    else:
        rows = [np.frombuffer(binary, dtype=dtype, count=width, offset=start + i * stride) for i in range(count)]
        out = np.stack(rows) if rows else np.zeros((0, width), dtype=dtype)
    return out


def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T  # glTF 는 열 우선
    t = np.array(node.get("translation", [0, 0, 0]), dtype=np.float64)
    x, y, z, w = (float(v) for v in node.get("rotation", [0, 0, 0, 1]))
    s = np.array(node.get("scale", [1, 1, 1]), dtype=np.float64)
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def _texture(gltf: dict[str, Any], binary: bytes, material: int | None) -> Any:
    if material is None:
        return None
    try:
        from PIL import Image

        info = gltf["materials"][material]["pbrMetallicRoughness"]["baseColorTexture"]
        tex = gltf["textures"][int(info["index"])]
        # trellis.cpp 는 그림을 webp 로 싣고 `EXT_texture_webp` 확장에만 source 를 적는다(11-14 실측 GLB).
        source = tex.get("source", (tex.get("extensions") or {}).get("EXT_texture_webp", {}).get("source"))
        image = gltf["images"][int(source)]
        view = gltf["bufferViews"][int(image["bufferView"])]
        start = int(view.get("byteOffset", 0))
        raw = binary[start: start + int(view["byteLength"])]
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001 — 그림이 없거나 못 읽으면 회색으로 그린다
        return None


def read_glb(path: str | Path) -> Mesh:
    gltf, binary = _chunks(Path(path).read_bytes())
    meshes = gltf.get("meshes") or []
    nodes = gltf.get("nodes") or []
    # 장면의 노드를 따라가며 변환을 곱한다. 장면이 없으면 메시를 변환 없이.
    pairs: list[tuple[int, np.ndarray]] = []

    def walk(index: int, parent: np.ndarray, depth: int = 0) -> None:
        if depth > 64:
            return
        node = nodes[index]
        matrix = parent @ _node_matrix(node)
        if "mesh" in node:
            pairs.append((int(node["mesh"]), matrix))
        for child in node.get("children") or []:
            walk(int(child), matrix, depth + 1)

    scenes = gltf.get("scenes") or []
    if scenes and nodes:
        scene = scenes[int(gltf.get("scene", 0))]
        for root in scene.get("nodes") or []:
            walk(int(root), np.eye(4))
    if not pairs:
        pairs = [(i, np.eye(4)) for i in range(len(meshes))]

    positions, faces, uvs = [], [], []
    texture, base, has_uv = None, 0, True
    for mesh_index, matrix in pairs:
        for prim in meshes[mesh_index].get("primitives") or []:
            if int(prim.get("mode", 4)) != 4:
                continue
            attrs = prim.get("attributes") or {}
            if "POSITION" not in attrs:
                continue
            pos = _accessor(gltf, binary, int(attrs["POSITION"])).astype(np.float64)
            pos = pos @ matrix[:3, :3].T + matrix[:3, 3]
            if "indices" in prim:
                idx = _accessor(gltf, binary, int(prim["indices"])).astype(np.int64).reshape(-1, 3)
            else:
                idx = np.arange(len(pos), dtype=np.int64).reshape(-1, 3)
            if "TEXCOORD_0" in attrs:
                uvs.append(_accessor(gltf, binary, int(attrs["TEXCOORD_0"])).astype(np.float64))
            else:
                has_uv = False
            if texture is None:
                texture = _texture(gltf, binary, prim.get("material"))
            positions.append(pos)
            faces.append(idx + base)
            base += len(pos)
    if not positions:
        raise GlbError("삼각형 메시가 없다")
    return Mesh(
        positions=np.concatenate(positions), faces=np.concatenate(faces),
        uv=np.concatenate(uvs) if has_uv and uvs else None, texture=texture,
    )
