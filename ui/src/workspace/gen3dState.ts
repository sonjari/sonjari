/**
 * 3D 무대의 상태 — 백엔드 `gen3d_stage` 알림을 판(take)마다 모은다 (2026-11-14 대표 「무대가 핵심」).
 *
 * 알림 모양(백엔드 `gen3d` 팩이 단계가 바뀔 때마다 보낸다 · 계약 노트 gen3d_계약_1114.md 의 GET 응답과 같은 칸):
 *   { job_id, gen_id, state: queued|running|done|failed, res, stage:{index,total,name,part?,parts?},
 *     stages:[{index,name,sec}], vram_mib?, image?, mesh_preview?, receipt?, error? }
 * - `job_id` 는 손자리 판(대화) · `gen_id` 는 3D 한 판. 한 대화에서 512 → 1024 로 다시 구우면 판이 둘이다.
 * - 남은 시간은 만들지 않는다 — 단계마다 **실제 걸린 초**만 보인다.
 */

export type Gen3dStep = { index: number; name: string; sec?: number };

export type Gen3dReceipt = {
  did?: string;
  files?: { glb?: string; texture?: string; preview?: string[]; stl?: string; "3mf"?: string };
  measured?: {
    faces?: number; holes_filled?: number; floaters_dropped?: number;
    vram_peak_mib?: number; sec?: number; watertight?: boolean;
  };
  printable?: { ok: boolean; why?: string[] };
  not_done?: string[];
  model?: { name?: string; precision?: string; res?: number; license?: string };
};

/** 모델 갈아타기 — 글 모델(예: Swift 27B)을 내리고 3D 모델을 그래픽카드에 올리는 동안(11-14 대표 「글로만 하지 말고」).
 *  메모리 칸은 **백엔드가 잰 값**만 그린다(못 재면 띠만 오간다 · `ModelLoadLine` 과 같은 규칙). */
export type Gen3dSwap = {
  from?: string;
  to: string;
  phase: "unload" | "load" | "ready";
  /** 내리는 모델이 쥐고 있던 메모리(MiB) — 내리는 동안 줄어든다. */
  fromMib?: number;
  loadedMib?: number;
  expectedMib?: number;
};

export type Gen3dTake = {
  genId: string;
  state: "queued" | "running" | "done" | "failed";
  res?: number;
  /** 지금 단계(1부터). 끝나면 total. */
  index: number;
  total: number;
  name: string;
  /** 지금 단계 안의 걸음(예: 색 · 재질 7/12). 실행기 로그에 있을 때만. */
  part?: [number, number];
  /** 지금 단계가 시작된 시각(ms) — 칸 안의 흐르는 초. */
  stepStartedAt: number;
  /** 판이 시작된 시각(ms). */
  startedAt: number;
  steps: Gen3dStep[];
  vramMib?: number;
  /** 넣은 그림(배경 지운 것이 오면 그것) — 파일 이름. */
  image?: string;
  /** 색 입히기 전 회색 메시가 나왔으면 그 파일 이름. */
  meshPreview?: string;
  receipt?: Gen3dReceipt;
  error?: string;
  swap?: Gen3dSwap;
};

export type Gen3dState = { takes: Gen3dTake[]; current: string; pinned?: boolean };

/** 화면에 쓰는 단계 이름 — 로그 이름이 아니라 사람이 알아듣는 말. 단계 번호(1~7)로 고른다(백엔드 이름은 칸이 모자랄 때만). */
export const GEN3D_STEP_NAMES = ["배경 지우기", "그림 읽기", "큰 모양", "모양 다듬기", "겉면 뽑기", "색 · 재질", "정리 · 저장"];

const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : undefined);

export function applyGen3dEvent(
  state: Gen3dState | undefined, payload: Record<string, unknown>, now: number = Date.now(),
): Gen3dState | undefined {
  const genId = String(payload.gen_id ?? "");
  if (!genId) return state;
  const rawState = String(payload.state ?? "running");
  const take0 = state?.takes.find((take) => take.genId === genId);
  const stage = (payload.stage ?? {}) as Record<string, unknown>;
  const total = num(stage.total) ?? take0?.total ?? GEN3D_STEP_NAMES.length;
  const index = num(stage.index) ?? take0?.index ?? 0;
  const steps = Array.isArray(payload.stages)
    ? (payload.stages as Record<string, unknown>[]).map((row) => ({
        index: Number(row.index ?? 0), name: String(row.name ?? ""), sec: num(row.sec),
      })).filter((row) => row.index > 0)
    : take0?.steps ?? [];
  const moved = !take0 || take0.index !== index;
  const take: Gen3dTake = {
    genId,
    state: rawState === "done" || rawState === "failed" || rawState === "queued" ? rawState : "running",
    res: num(payload.res) ?? take0?.res,
    index,
    total,
    // 백엔드는 로그 그대로의 단계 이름(「DINOv3 conditioning」)을 준다 — 화면에는 사람이 알아듣는 한국어 이름이 먼저다.
    name: GEN3D_STEP_NAMES[index - 1] || String(stage.name ?? "") || take0?.name || "",
    part: num(stage.part) && num(stage.parts) ? [num(stage.part)!, num(stage.parts)!] : moved ? undefined : take0?.part,
    stepStartedAt: moved ? now : take0!.stepStartedAt,
    startedAt: take0?.startedAt ?? now,
    steps,
    vramMib: num(payload.vram_mib) ?? take0?.vramMib,
    image: String(payload.image ?? "") || take0?.image,
    meshPreview: String(payload.mesh_preview ?? "") || take0?.meshPreview,
    receipt: (payload.receipt as Gen3dReceipt | undefined) ?? take0?.receipt,
    error: payload.error ? String(payload.error) : take0?.error,
    swap: readSwap(payload.swap) ?? take0?.swap,
  };
  const takes = take0
    ? state!.takes.map((row) => (row.genId === genId ? take : row))
    : [...(state?.takes ?? []), take];
  // 새 판이 오면 그 판을 본다. 사람이 아래 판을 눌러 두었으면(pinned) 그대로 둔다.
  const current = !take0 && !state?.pinned ? genId : state?.current || genId;
  return { takes, current, pinned: state?.pinned };
}

/** 단계 칸 하나가 얼마나 찼나(0~1). 끝난 칸 1 · 지금 칸은 백엔드가 준 걸음 비율이 없으면 0.5 로 둔다(지어낸 진행률을 보이지 않는다). */
export function stepFill(take: Gen3dTake, index: number, partial?: number): number {
  if (take.state === "done") return 1;
  if (index < take.index) return 1;
  if (index > take.index) return 0;
  return partial ?? 0.5;
}

export function formatFaces(faces: number | undefined): string {
  if (!faces) return "";
  return faces >= 10_000 ? `${(faces / 10_000).toFixed(1).replace(/\.0$/, "")}만` : faces.toLocaleString("ko-KR");
}

export function formatGb(mib: number | undefined): string {
  return mib ? `${(mib / 1024).toFixed(1)}GB` : "";
}

function readSwap(value: unknown): Gen3dSwap | undefined {
  if (!value || typeof value !== "object") return undefined;
  const row = value as Record<string, unknown>;
  const phase = row.phase === "unload" || row.phase === "load" || row.phase === "ready" ? row.phase : undefined;
  if (!phase || !row.to) return undefined;
  return {
    from: row.from ? String(row.from) : undefined, to: String(row.to), phase,
    fromMib: num(row.from_mib), loadedMib: num(row.loaded_mib), expectedMib: num(row.expected_mib),
  };
}

/** 영수증의 파일 칸은 전체 경로(`C:\…\ship.glb`)다 — 백엔드 파일 문은 **이름만** 받는다(판 폴더 밖으로 못 나가게).
 *  11-14 진짜 한 판: 경로를 그대로 보내 404 → 다 만들었는데 3D 대신 넣은 그림이 남았다. */
export function fileName(path: string | undefined): string | undefined {
  if (!path) return undefined;
  return path.split(/[\\/]/).pop() || undefined;
}
