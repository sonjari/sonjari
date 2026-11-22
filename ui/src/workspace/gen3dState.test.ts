import { describe, expect, it } from "vitest";
import { applyGen3dEvent, fileName, formatFaces, stepFill } from "./gen3dState";

// 백엔드 gen3d_tools._emit 이 실제로 보내는 꼴(11-14 · 실행기 로그 이름 그대로 · part/parts).
const running = (index: number, extra: Record<string, unknown> = {}) => ({
  job_id: "job_a", gen_id: "g3_1", state: "running", res: 512, image: "input.png", vram_mib: 2802,
  stage: { index, total: 7, name: index === 2 ? "DINOv3 conditioning" : "shape SLAT flow (512)", ...extra },
  stages: [],
});

describe("3D 무대 상태", () => {
  it("로그의 영어 단계 이름 대신 한국어 이름을 쓴다", () => {
    const state = applyGen3dEvent(undefined, running(2), 1000);
    expect(state?.takes[0].name).toBe("그림 읽기");
  });

  it("단계 안 비율은 part · parts 로만 받고, 단계가 바뀌면 지운다", () => {
    let state = applyGen3dEvent(undefined, running(3, { part: 7, parts: 12 }), 1000);
    expect(state?.takes[0].part).toEqual([7, 12]);
    state = applyGen3dEvent(state, running(4), 2000);
    expect(state?.takes[0].part).toBeUndefined();
    expect(state?.takes[0].stepStartedAt).toBe(2000);
  });

  it("같은 판 알림은 판을 늘리지 않고, 새 판(1024 다시 굽기)은 그 판으로 옮겨 간다", () => {
    let state = applyGen3dEvent(undefined, running(3), 1000);
    state = applyGen3dEvent(state, running(5), 1100);
    expect(state?.takes).toHaveLength(1);
    state = applyGen3dEvent(state, { ...running(1), gen_id: "g3_2", res: 1024 }, 1200);
    expect(state?.takes.map((take) => take.genId)).toEqual(["g3_1", "g3_2"]);
    expect(state?.current).toBe("g3_2");
  });

  it("사람이 판을 골라 두었으면 새 판이 와도 그대로 둔다", () => {
    let state = applyGen3dEvent(undefined, running(3), 1000);
    state = { ...state!, pinned: true };
    state = applyGen3dEvent(state, { ...running(1), gen_id: "g3_2" }, 1200);
    expect(state?.current).toBe("g3_1");
  });

  it("끝난 판은 모든 칸이 차고, 지어낸 진행률을 쓰지 않는다", () => {
    const state = applyGen3dEvent(undefined, { ...running(7), state: "done", stage: undefined }, 1000)!;
    expect([1, 4, 7].map((i) => stepFill(state.takes[0], i))).toEqual([1, 1, 1]);
    const live = applyGen3dEvent(undefined, running(3), 1000)!.takes[0];
    expect([stepFill(live, 2), stepFill(live, 4)]).toEqual([1, 0]);
  });

  it("gen_id 없는 알림은 버린다 · 면 수는 만 단위", () => {
    expect(applyGen3dEvent(undefined, { job_id: "x" })).toBeUndefined();
    expect(formatFaces(143964)).toBe("14.4만");
  });

  it("영수증의 전체 경로에서 파일 이름만 뽑는다(백엔드 파일 문은 이름만 받는다)", () => {
    expect(fileName("C:\\Users\\me\\Documents\\Sonjari\\gen3d\\g3_1\\char.glb")).toBe("char.glb");
    expect(fileName("/Users/me/gen3d/g3_1/char.glb")).toBe("char.glb");
    expect(fileName("input.png")).toBe("input.png");
    expect(fileName(undefined)).toBeUndefined();
  });
});
