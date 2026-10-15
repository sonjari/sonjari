// @vitest-environment jsdom
/**
 * 모델 카드의 「그림 읽기」 줄 — 그림도 읽기 / 글만 읽기 (2026-10-12).
 *
 * 지키는 약속:
 * - 그림 부속을 따로 붙이는 모델(`pictures_optional`)에서만 줄이 보인다. 옛 백엔드(그 칸을 안 준다)는 예전 카드 그대로다.
 * - 기본은 「그림도 읽기」다 — 말하지 않으면 예전처럼 그림을 읽게 올린다.
 * - 「글만 읽기」를 고르면 창마다의 메모리가 백엔드가 잰 만큼 줄어, 안 들어가던 긴 창이 들어갈 수 있다.
 *   고른 뜻은 바깥(마법사)으로 셋째 인자로 나간다 — 적용 호출이 그 값을 싣는다.
 * - 다시 켜서 고른 창이 안 들어가게 되면, 들어가는 가장 긴 창으로 맞춘다.
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ModelCard } from "./SetupWizard";
import { createFixtureSetupApi } from "./fixtureSetupApi";
import type { CatalogModel } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
afterEach(() => {
  host?.remove();
  host = null;
});

function mount(node: JSX.Element): HTMLDivElement {
  host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  act(() => root.render(node));
  return host;
}

/** 16GB 급에 들어가는 크기를 본뜬 모델 — 그림을 읽으면 64K 가 14.6GB, 부속을 떼면 1.1GB 덜 든다. */
async function model(extra: Partial<CatalogModel> = {}): Promise<CatalogModel> {
  const view = await createFixtureSetupApi("3090")!.models();
  return {
    ...view.models[0],
    key: "sample-27b-small",
    name: "Sample 27B",
    family: "",
    status: "verified",
    fits: true,
    installed: true,
    vram_gb: { "65536": 14.6, "49152": 14.2, "32768": 13.5 },
    pictures_optional: true,
    text_only_tag: "sonjari-text-sample-27b-small",
    text_only_saves_gb: 1.1,
    ...extra,
  };
}

/** 쓸 수 있는 메모리 14.3GB — 그림을 읽으면 48K 까지, 글만 읽으면 64K(13.5GB)가 들어간다. */
const USABLE = 14.3;

function Held({ sample, onPick }: { sample: CatalogModel; onPick: (ctx: number, key: string, textOnly?: boolean) => void }) {
  const [picked, setPicked] = useState<{ ctx: number; textOnly?: boolean } | null>(null);
  return (
    <ModelCard model={sample} usable={USABLE} recommended={null} pulsing={false} onPulseEnd={() => {}}
      pickedKey={picked ? sample.key : null} picked={picked?.ctx ?? null} pickedTextOnly={picked?.textOnly}
      onPick={(ctx, key, textOnly) => { setPicked({ ctx, textOnly }); onPick(ctx, key, textOnly); }} />
  );
}

const eyes = (root: Element) => [...root.querySelectorAll<HTMLButtonElement>('.model-eyes-chips [role="radio"]')];
const windows = (root: Element) => [...root.querySelectorAll<HTMLButtonElement>('.model-ctx [role="radio"]')];
const windowOf = (root: Element, label: string) => windows(root).find((chip) => chip.textContent?.startsWith(label))!;
const click = (button: HTMLButtonElement) => act(() => button.dispatchEvent(new MouseEvent("click", { bubbles: true })));

it("그림을 끌 수 없는 모델 · 옛 백엔드에는 줄이 없다", async () => {
  const plain = await model({ pictures_optional: false });
  expect(mount(<Held sample={plain} onPick={() => {}} />).querySelector(".model-eyes")).toBeNull();
  host?.remove();
  const old = await model();
  delete (old as Partial<CatalogModel>).pictures_optional;
  expect(mount(<Held sample={old} onPick={() => {}} />).querySelector(".model-eyes")).toBeNull();
});

it("처음에는 그림도 읽기 — 긴 창은 안 들어간다고 보인다", async () => {
  const root = mount(<Held sample={await model()} onPick={() => {}} />);
  const [reading, textOnly] = eyes(root);
  expect(reading.getAttribute("aria-checked")).toBe("true");
  expect(textOnly.getAttribute("aria-checked")).toBe("false");
  expect(textOnly.textContent).toContain("1.1GB");
  expect(windowOf(root, "64K").disabled).toBe(true);
  expect(windowOf(root, "48K").disabled).toBe(false);
  expect(root.querySelector(".model-eyes-note")?.textContent).toContain("그림까지 읽습니다");
});

it("글만 읽기를 고르면 긴 창이 들어가고, 그 뜻이 바깥으로 나간다", async () => {
  const onPick = vi.fn();
  const sample = await model();
  const root = mount(<Held sample={sample} onPick={onPick} />);
  click(eyes(root)[1]);
  expect(onPick).toHaveBeenLastCalledWith(65536, sample.key, true);
  expect(eyes(root)[1].getAttribute("aria-checked")).toBe("true");
  expect(windowOf(root, "64K").disabled).toBe(false);
  expect(windowOf(root, "64K").textContent).toContain("13.5");
  expect(windowOf(root, "64K").getAttribute("aria-checked")).toBe("true");
  expect(root.querySelector(".model-eyes-note")?.textContent).toContain("읽지 못합니다");
  // 창을 다시 고를 때도 그 뜻이 같이 간다.
  click(windowOf(root, "48K"));
  expect(onPick).toHaveBeenLastCalledWith(49152, sample.key, true);
});

it("다시 켜서 고른 창이 안 들어가면 들어가는 가장 긴 창으로 맞춘다", async () => {
  const onPick = vi.fn();
  const sample = await model();
  const root = mount(<Held sample={sample} onPick={onPick} />);
  click(eyes(root)[1]);
  click(eyes(root)[0]);
  expect(onPick).toHaveBeenLastCalledWith(49152, sample.key, false);
  expect(windowOf(root, "64K").disabled).toBe(true);
  expect(windowOf(root, "48K").getAttribute("aria-checked")).toBe("true");
});

it("고른 창이 그대로 들어가면 창은 바꾸지 않는다", async () => {
  const onPick = vi.fn();
  const sample = await model();
  const root = mount(<Held sample={sample} onPick={onPick} />);
  click(windowOf(root, "32K"));
  click(eyes(root)[1]);
  expect(onPick).toHaveBeenLastCalledWith(32768, sample.key, true);
});

it("follows a recommendation that arrives after the card was drawn — text only, with the measured number", async () => {
  // 2026-10-12: 16GB 급의 추천은 「글만 읽기 · 64K」다. 추천은 카드보다 늦게 온다 — 그때 「글만 읽기」가 골라져야 하고,
  // 그 창의 메모리는 어림(14.6 − 1.1 = 13.5)이 아니라 잰 값(13.8)이어야 추천이 말한 숫자와 같다.
  const sample = await model({ text_only_vram_gb: { "65536": 13.8 } });
  function Late() {
    const [picked, setPicked] = useState<{ ctx: number; textOnly?: boolean } | null>(null);
    return (
      <>
        <button type="button" data-testid="recommend" onClick={() => setPicked({ ctx: 65536, textOnly: true })}>rec</button>
        <ModelCard model={sample} usable={USABLE} recommended={null} pulsing={false} onPulseEnd={() => {}}
          pickedKey={picked ? sample.key : null} picked={picked?.ctx ?? null} pickedTextOnly={picked?.textOnly}
          onPick={(ctx, _key, textOnly) => setPicked({ ctx, textOnly })} />
      </>
    );
  }
  const root = mount(<Late />);
  expect(eyes(root)[0].getAttribute("aria-checked")).toBe("true");          // 처음에는 그림도 읽기
  click(root.querySelector<HTMLButtonElement>('[data-testid="recommend"]')!);
  expect(eyes(root)[1].getAttribute("aria-checked")).toBe("true");          // 추천이 오면 글만 읽기
  const big = windowOf(root, "64K");
  expect(big.getAttribute("aria-checked")).toBe("true");
  expect(big.textContent).toContain("13.8");
  expect(big.textContent).not.toContain("13.5");
});
