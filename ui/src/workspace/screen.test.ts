import { describe, expect, it } from "vitest";
import type { BrowserFrame, BrowserStatus } from "../types";
import { agoLabel, screenProblem, screenWarnings, seamLabel, shortUrl, staleLabel } from "./screen";

function status(extra: Partial<BrowserStatus> = {}): BrowserStatus {
  return {
    enabled: true, started: true, liveness: "probed", headless: false, read_only: false,
    connect_mode: "attached", automation_flag: false, attach_error: "", last_error: "",
    stuck: false, circuit_open: false, recoveries: 0,
    ...extra,
  };
}

function frame(extra: Partial<BrowserFrame> = {}): BrowserFrame {
  return { ok: false, blob: null, pageUrl: "", title: "", ageSec: 0, fresh: false, reason: "", ...extra };
}

const PICTURE = new Blob(["x"], { type: "image/jpeg" });

describe("빈 화면은 왜 비었는지 말한다", () => {
  it("그림이 있으면 아무 말도 안 한다", () => {
    expect(screenProblem(status(), frame({ ok: true, blob: PICTURE }))).toBeNull();
  });

  it("자비스 자체에 못 닿은 것과 브라우저가 없는 것을 가른다", () => {
    // 이 둘은 사람이 할 일이 완전히 다르다 — 하나는 스케줄러, 하나는 크롬이다.
    const dead = screenProblem(status(), frame({ reason: "backend_unreachable: Failed to fetch" }));
    expect(dead?.title).toContain("Sonjari");
    expect(dead?.tone).toBe("fail");
  });

  it("사람이 할 일이 있는 것을 위로 올린다", () => {
    // 붙기 실패는 크롬을 껐다 켜면 풀린다. 그냥 "안 떠 있음"으로 뭉개면 그 사실이 사라진다.
    const both = screenProblem(status({ started: false, attach_error: "9222 연결 거부" }), frame());
    expect(both?.title).toContain("붙지 못했습니다");
    expect(both?.detail).toContain("9222 연결 거부");
  });

  it("크롬도 엣지도 없으면 껐다 켜라고 하지 않는다", () => {
    const none = screenProblem(status({ started: false, attach_error: "browser_not_found — 브라우저 일을 하려면 크롬이나 엣지가 필요합니다." }), frame());
    expect(none?.title).toBe("브라우저를 찾지 못했습니다");
    expect(none?.detail).toContain("크롬이나 엣지");
    expect(none?.detail).not.toContain("browser_not_found");
    expect(none?.detail).not.toContain("껐다 켜면");
  });

  it("회로가 열렸으면 그것부터 말한다", () => {
    const opened = screenProblem(status({ circuit_open: true, attach_error: "무언가" }), frame());
    expect(opened?.title).toContain("재시도");
    expect(opened?.tone).toBe("fail");
  });

  it("안 떠 있는 것은 고장이 아니라고 말한다", () => {
    // 여기서 크롬을 열지 않는 것이 설계다. 사람이 "고장났나" 하게 두면 안 된다.
    const idle = screenProblem(status({ started: false }), frame());
    expect(idle?.tone).toBe("mute");
    expect(idle?.detail).toContain("스스로 엽니다");
  });

  it("앞 동작에 물린 것은 잠깐이라고 말한다", () => {
    const busy = screenProblem(status(), frame({ reason: "browser_busy_active — 12초째" }));
    expect(busy?.tone).toBe("hold");
    expect(busy?.title).toContain("잠시 뒤");
    expect(busy?.title).not.toContain("다른 동작"); // 「딴짓하나?」로 읽혔다(2026-09-23)
  });

  it("모르는 이유는 지어내지 않고 그대로 보여 준다", () => {
    const odd = screenProblem(status(), frame({ reason: "Timeout 4000ms exceeded" }));
    expect(odd?.detail).toBe("Timeout 4000ms exceeded");
  });
});

describe("그림이 나와도 숨기지 않는 것", () => {
  it("자비스만 막혀 있는 모양을 화면이 감추지 않는다", () => {
    // 이게 제일 알아채기 어려운 고장이다 — 화면은 멀쩡하고 도구만 전부 실패한다.
    const lines = screenWarnings(status({ stuck: true, circuit_open: true }));
    expect(lines).toHaveLength(2);
  });

  it("자동화 모드면 막히는 곳이 있다고 미리 말한다", () => {
    const lines = screenWarnings(status({ automation_flag: true }));
    expect(lines.join(" ")).toContain("Akamai");
  });

  it("모르는 값(null)을 자동화 모드로 읽지 않는다", () => {
    expect(screenWarnings(status({ automation_flag: null }))).toStrictEqual([]);
  });

  it("되살린 횟수가 잦아지면 원인을 보라고 한다", () => {
    expect(screenWarnings(status({ recoveries: 2 }))).toStrictEqual([]);
    expect(screenWarnings(status({ recoveries: 3 })).join(" ")).toContain("3번");
  });
});

describe("주소와 나이", () => {
  it("추적 인자를 걷어내고 어디인지만 남긴다", () => {
    expect(shortUrl("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=51000003&view_type=list"))
      .toBe("www.saramin.co.kr/zf_user/jobs/relay/view");
  });

  it("주소가 아니어도 죽지 않는다", () => {
    expect(shortUrl("about:blank")).toBe("about:blank");
    expect(shortUrl("")).toBe("");
  });

  it("방금 찍은 장에는 나이를 안 적는다", () => {
    // 모든 장에 "0초 전"이 붙으면 아무도 안 읽고, 정작 낡았을 때도 안 읽힌다.
    expect(staleLabel(frame({ blob: PICTURE, fresh: true, ageSec: 0.2 }))).toBe("");
    expect(staleLabel(frame({ blob: PICTURE, fresh: false, ageSec: 12.4 }))).toBe("12초 전 화면");
  });

  it("그림이 없으면 나이도 없다", () => {
    expect(staleLabel(frame({ ageSec: 30 }))).toBe("");
  });
});

// ── 화면과 본문 사이의 선 ────────────────────────────────────────────────
//
// ★ 이 칸은 지금까지 화면이냐 본문이냐 **하나만** 보여 줬다. 둘을 같이 놓기로
//   하면서 거짓말 하나가 생길 뻔했다: 관측 보관소에는 그림이 없으므로
//   (`observations.shape` 는 글·표·초안만 저장한다) 3걸음 위에 지금 화면을
//   얹으면 사람은 그것을 3걸음의 화면으로 읽는다.
//
//   규칙: **화면은 언제나 지금이고, 본문이 지금이 아니면 적는다.**

describe("seamLabel", () => {
  it("본문이 없으면 선도 없다", () => {
    // 선만 덩그러니 있으면 뭔가 잘린 것처럼 보인다.
    expect(seamLabel(null, null, true)).toBeNull();
    expect(seamLabel(3, null, false)).toBeNull();
  });

  it("도는 중에 「지금」을 보면 되감은 것이 아니다", () => {
    // 본문이 마지막 걸음이고 그것이 곧 지금이다 — 시각이 어긋나지 않는다.
    expect(seamLabel(null, 5, true)).toEqual({ label: "지금 걸음", rewound: false });
  });

  it("끝난 뒤에 「지금」을 보면 마지막 걸음이라고 부른다", () => {
    expect(seamLabel(null, 5, false)).toEqual({ label: "마지막 걸음", rewound: false });
  });

  it("마지막 걸음을 직접 고른 것은 되감은 것이 아니다", () => {
    // 같은 것을 보고 있는데 "되감았다"고 하면 그 표시를 아무도 안 믿게 된다.
    expect(seamLabel(5, 5, true)).toEqual({ label: "5걸음", rewound: false });
  });

  it("★ 지난 걸음을 고르면 되감았다고 **글자로** 말한다", () => {
    // 이 한 줄이 없으면 3걸음의 글 위에 있는 지금 화면이 3걸음의 화면으로 읽힌다.
    // 색만으로는 안 된다 — 색을 못 보는 사람에게는 아무 말도 안 한 것이 된다.
    expect(seamLabel(3, 5, true)).toEqual({ label: "3걸음 · 그때", rewound: true });
  });
});

describe("agoLabel", () => {
  const now = 1_700_000_000_000;

  it("갓 지난 것은 초를 세지 않는다", () => {
    // 초를 적으면 1초마다 다시 그린다 — 읽는 사람에게 값은 없고 화면만 떨린다.
    expect(agoLabel(now - 3_000, now)).toBe("방금");
    expect(agoLabel(now - 44_000, now)).toBe("방금");
  });

  it("분과 시간으로 올라간다", () => {
    expect(agoLabel(now - 90_000, now)).toBe("2분 전");
    expect(agoLabel(now - 20 * 60_000, now)).toBe("20분 전");
    expect(agoLabel(now - 130 * 60_000, now)).toBe("2시간 전");
  });

  it("시계가 어긋나도 미래로 가지 않는다", () => {
    // 백엔드와 화면의 시계가 조금 다를 수 있다. "-3분 전"은 고장으로 보인다.
    expect(agoLabel(now + 5_000, now)).toBe("방금");
  });
});


describe("캡처 실패는 원문 오류가 아니라 사람 말로 (2026-09-17)", () => {
  const started = { enabled: true, started: true, stuck: false, circuit_open: false, attach_error: "" } as never;
  const frame = (reason: string) => ({ ok: false, blob: null, pageUrl: "", title: "", ageSec: 0, fresh: false, reason });

  it("최소화된 크롬은 창 상태로 말한다", () => {
    const problem = screenProblem(started, frame("capture_window_minimized"));
    expect(problem?.title).toContain("내려가");
    expect(problem?.tone).toBe("mute");
  });

  it("모르는 이유여도 Protocol error 원문을 보이지 않는다", () => {
    const problem = screenProblem(started, frame("capture_failed: Page.screenshot: Protocol error (Page.captureScreenshot): Cannot take screenshot with 0 width."));
    expect(`${problem?.title} ${problem?.detail}`).not.toContain("Protocol error");
  });
});
