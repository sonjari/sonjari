// @vitest-environment jsdom
/**
 * 같은 자리에서 헛돌아 멈춘 판은 **「더 할까요?」가 아니라 「여기서 막혔습니다 — 이것만 해 주세요」** 다 (2026-09-23).
 *
 * 시간이 모자란 게 아니라서 「3분 더」는 뜻이 없다. 사람이 손본 뒤 「이어서」, 아니면 가진 것으로 「여기까지 정리」.
 */
import { createRef, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ContinuationCard } from "./DecisionCards";
import { gateSiteLabel } from "./humanGate";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("막힌 판은 한 것·막힌 곳·해 주실 일을 보이고 「3분 더」를 내지 않는다", () => {
  const onDecide = vi.fn();
  act(() => {
    root.render(
      <ContinuationCard
        continuation={{
          job_id: "j1",
          goal: "장바구니 결제해줘",
          reason: "stuck",
          report: { done: "장바구니를 열었습니다", blocked: "결제 단추를 5번 눌렀지만 넘어가지 않았습니다", ask: "결제 수단을 등록해 주세요", url: "https://shop.example/cart" },
        }}
        busy={false}
        cardRef={createRef<HTMLElement>()}
        onDecide={onDecide}
      />,
    );
  });
  const text = container.textContent ?? "";
  expect(text).toContain("여기서 막혔습니다");
  expect(text).toContain("장바구니를 열었습니다");
  expect(text).toContain("결제 수단을 등록해 주세요");
  expect(text).toContain("shop.example/cart");
  expect(text).not.toContain("3분 더");
  const resume = [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("이어서"));
  act(() => resume?.click());
  expect(onDecide).toHaveBeenCalledWith("continue_task");
});

it("★ 좋은 표본 — 예산으로 멈춘 판은 예전 카드 그대로(「3분 더」가 있다)", () => {
  act(() => {
    root.render(
      <ContinuationCard
        continuation={{ job_id: "j2", goal: "조사해줘", reason: "time_budget", steps: 12 }}
        busy={false}
        cardRef={createRef<HTMLElement>()}
        onDecide={() => {}}
      />,
    );
  });
  const text = container.textContent ?? "";
  expect(text).toContain("3분 더");
  expect(text).not.toContain("여기서 막혔습니다");
});

it("★ 사람 문에서 멈춘 판은 「시간 다 씀」이 아니라 그 문과 할 일을 말한다(2026-09-29)", () => {
  const onDecide = vi.fn();
  act(() => {
    root.render(
      <ContinuationCard
        continuation={{ job_id: "j3", goal: "깃허브 조직 만들어줘", reason: "human_gate:bot_check", steps: 3,
          gate_url: "https://github.com/account/organizations/new" }}
        busy={false}
        cardRef={createRef<HTMLElement>()}
        onDecide={onDecide}
      />,
    );
  });
  const text = container.textContent ?? "";
  expect(text).toContain("사람인지 확인하는 화면이에요");
  expect(text).toContain("github.com/account/organizations/new");
  expect(text).not.toContain("시간");
  expect(text).not.toContain("3분 더");
  const resume = [...container.querySelectorAll("button")].find((b) => b.textContent?.includes("이어서"));
  act(() => resume?.click());
  expect(onDecide).toHaveBeenCalledWith("continue_task");
});

it("모르는 이유에 「시간 다 씀」을 붙이지 않는다", () => {
  act(() => {
    root.render(
      <ContinuationCard
        continuation={{ job_id: "j4", goal: "조사해줘", reason: "something_new" }}
        busy={false}
        cardRef={createRef<HTMLElement>()}
        onDecide={() => {}}
      />,
    );
  });
  expect(container.textContent ?? "").not.toContain("작업 시간을 다 썼습니다");
});

const GENSPARK_OAUTH =
  "https://login.genspark.ai/oauth2/authorize?client_id=8f3a9c&redirect_uri=https%3A%2F%2Fwww.genspark.ai%2Fapi%2Fauth%2Fcallback"
  + "&response_type=code&scope=openid%20email%20profile&state=eyJhbGciOiJIUzI1NiJ9.eyJyZXR1cm4iOiIvcHJpY2luZyJ9.x1y2z3";

it("★ 로그인 카드는 OAuth 주소 대신 사이트 이름을 보이고, 할 곳 버튼을 같이 싣는다(2026-10-02)", () => {
  act(() => {
    root.render(
      <ContinuationCard
        continuation={{ job_id: "j5", goal: "가격표 만들어줘", reason: "human_gate:login_required", steps: 9,
          gate_url: GENSPARK_OAUTH }}
        busy={false}
        cardRef={createRef<HTMLElement>()}
        onDecide={() => {}}
        gateActions={<button type="button">크롬 창 보기</button>}
      />,
    );
  });
  const text = container.textContent ?? "";
  expect(text).toContain("login.genspark.ai/oauth2/authorize");
  expect(text).not.toContain("client_id");
  expect(text).not.toContain("state=");
  expect(text).toContain("크롬 창 보기");
});

it("사이트 이름 줄이기 — 쿼리는 버리고 긴 경로는 사이트 이름만", () => {
  expect(gateSiteLabel("https://www.perplexity.ai/hub/pricing?ref=x")).toBe("perplexity.ai/hub/pricing");
  expect(gateSiteLabel("https://accounts.example.com/" + "a".repeat(60))).toBe("accounts.example.com");
  expect(gateSiteLabel("https://manus.im/")).toBe("manus.im");
  expect(gateSiteLabel("")).toBe("");
  expect(gateSiteLabel("주소 아님 ".repeat(20)).length).toBeLessThanOrEqual(60);
});
