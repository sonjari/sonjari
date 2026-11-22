/**
 * 3D 무대 리허설(개발 모드 전용 · `?gen3dFixture=warrior`) — 백엔드 없이 진짜 앱 안에서 무대를 본다 (2026-11-14).
 *
 * 숫자는 실측 판 그대로다: 여전사 512 · RTX 3060 · q8 (`D:\models\img2_3d\results\w_512_3060_q8_warrior.log`).
 * - 단계 초는 로그에 찍힌 것만 넣는다(2 그림 읽기 0.27초 · 3 큰 모양 23.1초 · 4 모양 다듬기 21.9초 · 6 색 · 재질 13.3초). 나머지는 비워 둔다.
 * - 다 걸린 시간 138.7초 · 면 143,964 · 메운 구멍 2,842 · 떼어 낸 조각 433 · 메모리 최대 4,064MiB.
 * - 맨 앞 모델 갈아타기(글 모델 내림 → 3D 모델 올림)는 이 판에서 재지 않았다 — 이름 · 순서만 보이고 메모리 숫자는 없다.
 * - 재생은 3배 빠르게 한다(보는 용). 회색 메시는 실제로는 백엔드가 `mesh_preview` 를 보내야 나온다 — 여기서는 완성 GLB 를 회색으로 칠해 흉내 낸다.
 * 파일은 개발 서버의 `/__gen3d_fixture/` 로 읽는다 — `VITE_GEN3D_FIXTURE_SERVER`(결과 폴더를 띄운 http 서버)로 이어 준다(vite.config).
 */
const SPEED = 3;

type Emit = (jobId: string, payload: Record<string, unknown>) => void;

const STEPS: Array<{ name: string; sec: number; measured?: number; parts?: number; vram: number }> = [
  { name: "배경 지우기", sec: 4, vram: 1117 },
  { name: "그림 읽기", sec: 2, measured: 0.27, vram: 1788 },
  { name: "큰 모양", sec: 23.1, measured: 23.1, parts: 12, vram: 2802 },
  { name: "모양 다듬기", sec: 21.9, measured: 21.9, parts: 12, vram: 3274 },
  { name: "겉면 뽑기", sec: 18, vram: 4064 },
  { name: "색 · 재질", sec: 13.3, measured: 13.3, parts: 12, vram: 3274 },
  { name: "정리 · 저장", sec: 20, vram: 1788 },
];

export function playGen3dFixture(name: string, emit: Emit): { stop: () => void; fileUrl: (file: string) => string } {
  const jobId = `fixture-gen3d-${name}`;
  const genId = "w512";
  const timers: number[] = [];
  const at = (sec: number, fn: () => void) => { timers.push(window.setTimeout(fn, (sec / SPEED) * 1000)); };
  const done: Array<{ index: number; name: string; sec?: number }> = [];
  // 모델 갈아타기: 글 모델을 내리고(예시 이름) 3D 모델을 올린다. 메모리는 이 판에서 재지 않았으므로 숫자 없이 띠만 오간다.
  const swapBase = { job_id: jobId, gen_id: genId, res: 512, state: "queued", image: "input_warrior.png", stage: { index: 0, total: STEPS.length, name: "" } };
  at(0.3, () => emit(jobId, { ...swapBase, swap: { from: "Swift 27B", to: "TRELLIS.2 · q8", phase: "unload" } }));
  at(4, () => emit(jobId, { ...swapBase, swap: { from: "Swift 27B", to: "TRELLIS.2 · q8", phase: "load" } }));
  at(12, () => emit(jobId, { ...swapBase, swap: { from: "Swift 27B", to: "TRELLIS.2 · q8", phase: "ready" } }));
  let clock = 12.5;
  STEPS.forEach((step, i) => {
    const index = i + 1;
    const base = {
      job_id: jobId, gen_id: genId, res: 512, state: "running", image: "input_warrior.png",
      ...(index >= 5 ? { mesh_preview: "w_512_warrior.glb" } : {}),
    };
    const start = clock;
    at(start, () => emit(jobId, { ...base, vram_mib: step.vram, stage: { index, total: STEPS.length, name: step.name }, stages: [...done] }));
    if (step.parts) {
      for (let part = 1; part <= step.parts; part++) {
        at(start + (step.sec * part) / step.parts, () => emit(jobId, {
          ...base, vram_mib: step.vram, stage: { index, total: STEPS.length, name: step.name, part, parts: step.parts }, stages: [...done],
        }));
      }
    }
    clock += step.sec;
    at(clock - 0.01, () => { done.push({ index, name: step.name, sec: step.measured }); });
  });
  at(clock + 0.2, () => emit(jobId, {
    job_id: jobId, gen_id: genId, res: 512, state: "done", image: "input_warrior.png",
    stage: { index: STEPS.length, total: STEPS.length, name: "정리 · 저장" }, stages: [...done],
    receipt: {
      did: "3D 초안 1개 · 512",
      files: { glb: "w_512_warrior.glb", texture: "w_512_warrior_base.png", preview: ["input_warrior.png"] },
      measured: { faces: 143964, holes_filled: 2842, floaters_dropped: 433, vram_peak_mib: 4064, sec: 138.7 },
      printable: { ok: true, why: [] },
      not_done: [],
      model: { name: "trellis2", precision: "q8", res: 512, license: "MIT" },
    },
  }));
  return {
    stop: () => timers.forEach((timer) => window.clearTimeout(timer)),
    fileUrl: (file: string) => `/__gen3d_fixture/${file}`,
  };
}
