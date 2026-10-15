import { describe, expect, it } from "vitest";
import type { CapabilityTool } from "../types";
import { disabledCount, groupKeyOf, groupTools, riskMeaning } from "./capabilities";

const tool = (name: string, risk_level = "L0", enabled = true): CapabilityTool =>
  ({ name, description: name, risk_level, enabled });

describe("102개를 사람이 훑을 수 있게", () => {
  it("이름 앞머리로 묶는다", () => {
    expect(groupKeyOf(tool("browser_extract"))).toBe("browser");
    expect(groupKeyOf(tool("google_gmail_send"))).toBe("google");
    expect(groupKeyOf(tool("local_read_document"))).toBe("computer");
  });

  it("분류표에 없는 도구를 **버리지 않는다**", () => {
    // 조용히 빠지는 것이 제일 나쁘다 — 눈금에 구멍이 나던 것이 정확히 이 모양이다
    // (WRITE_TOOLS 에 새 도구를 안 넣어 화면이 "읽기만 함"이라고 거짓말했다).
    const groups = groupTools([tool("quantum_flux")]);
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe("other");
    expect(groups[0].tools[0].name).toBe("quantum_flux");
  });

  it("빈 묶음은 안 그린다", () => {
    // 있지도 않은 능력을 진열하면 목록 전체가 못 미더워진다.
    const groups = groupTools([tool("browser_open")]);
    expect(groups.map((row) => row.key)).toStrictEqual(["browser"]);
  });

  it("모르는 묶음은 언제나 맨 뒤다", () => {
    const groups = groupTools([tool("zzz_unknown"), tool("browser_open"), tool("google_x")]);
    expect(groups[groups.length - 1].key).toBe("other");
  });

  it("등급으로 거를 수 있다", () => {
    // "되돌릴 수 없는 것이 정확히 무엇인가"가 이 화면에서 제일 중요한 질문이다.
    const tools = [tool("browser_open", "L0"), tool("browser_fill", "L1"), tool("google_gmail_send", "L2")];
    const l2 = groupTools(tools, "L2");
    expect(l2.flatMap((row) => row.tools).map((row) => row.name)).toStrictEqual(["google_gmail_send"]);
  });

  it("같은 묶음 안에서는 이름 순이다", () => {
    const groups = groupTools([tool("browser_scroll"), tool("browser_click"), tool("browser_open")]);
    expect(groups[0].tools.map((row) => row.name)).toStrictEqual(["browser_click", "browser_open", "browser_scroll"]);
  });
});

describe("등급은 숫자가 아니라 뜻이다", () => {
  it("L2 는 되돌릴 수 없다고 말하고 빨강이다", () => {
    expect(riskMeaning("L2").label).toBe("되돌릴 수 없음");
    expect(riskMeaning("L2").tone).toBe("fail");
  });

  it("L1 을 주황으로 칠하지 않는다", () => {
    // 주황은 "사람이 눌러야 움직인다"는 뜻이다(P3). L1 은 자비스가 그냥 한다 —
    // 여기서 주황을 쓰면 색의 뜻이 화면 전체에서 무너진다.
    expect(riskMeaning("L1").tone).toBe("mute");
    expect(riskMeaning("L0").tone).toBe("mute");
  });

  it("모르는 등급을 지어내지 않는다", () => {
    expect(riskMeaning("L9").label).toBe("L9");
  });
});

describe("꺼져 있는 도구", () => {
  it("목록에 있어도 못 쓴다는 사실을 센다", () => {
    expect(disabledCount([tool("a"), tool("b", "L0", false), tool("c", "L0", false)])).toBe(2);
  });
});
