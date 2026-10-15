// @vitest-environment jsdom
/**
 * 모델 카드의 라이선스 한 줄 · 「조건 없는 대안」 배지 · 「크기 고르기」 줄 (2026-10-08, 전략안 §55-24 덧붙임 2).
 *
 * 지키는 약속:
 * - 조건이 붙은 라이선스는 「조건이 있다」는 사실과 원문 링크만 보인다. 자유 라이선스는 이름만.
 * - 같은 `family`(같은 모델의 다른 크기)는 카드 하나다. 크기를 바꾸면 받는 크기·창 칩이 그 크기의 것으로 바뀌고,
 *   받기·적용에 쓰이는 key 도 **고른 크기의 key** 다.
 * - 옛 백엔드(새 칸을 안 준다)와 `family` 가 빈 모델은 예전 카드 그대로다.
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ModelCard, ModelGallery, groupFamilies, modelCardId } from "./SetupWizard";
import { createFixtureSetupApi } from "./fixtureSetupApi";
import type { CatalogModel, ModelPick } from "./setupApi";

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

/** 리허설 표본(RTX 3090)의 목록과 추천 — 화면 미리보기가 보는 것과 같은 데이터로 시험한다. */
async function sample(pc = "3090") {
  const api = createFixtureSetupApi(pc)!;
  const [view, rec] = await Promise.all([api.models(), api.recommendation()]);
  return { models: view.models, picks: rec.picks ?? [] };
}

const kindsOf = (picks: Pick<ModelPick, "model_key" | "kind">[]) =>
  new Map(picks.map((pick) => [pick.model_key, pick.kind]));

/** 고른 것을 들고 있는 바깥(마법사) 흉내 — 받기·적용은 여기 `picked.key` 를 쓴다. */
function Gallery({ models, kinds, usable = 23.5, asked = true, pulse = "", onPick, onPulseEnd = () => {} }: {
  models: CatalogModel[]; kinds: Map<string, ModelPick["kind"]>; usable?: number; asked?: boolean; pulse?: string;
  onPick?: (key: string, ctx: number) => void; onPulseEnd?: () => void;
}) {
  const [picked, setPicked] = useState<{ key: string; ctx: number } | null>(null);
  return (
    <ModelGallery models={models} pickKinds={kinds} usable={usable} asked={asked} pulse={pulse} onPulseEnd={onPulseEnd}
      picked={picked} onPick={(key, ctx) => { setPicked({ key, ctx }); onPick?.(key, ctx); }} />
  );
}

const SWIFT_CARD = "#model-family-verified-swift-27b";
const cardProps = { usable: 23.5, recommended: null, pulsing: false, onPulseEnd: () => {}, picked: null, onPick: () => {} } as const;
const chips = (root: Element, group: string) => [...root.querySelectorAll<HTMLButtonElement>(`${group} [role="radio"]`)];
const sizeChips = (root: Element) => chips(root, ".model-size-chips");
const ctxChips = (root: Element) => chips(root, ".model-ctx:not(.model-size-chips)");

it("ⓐ 자유 라이선스는 이름만, 조건 있는 라이선스는 「사용 조건 있음」과 원문 링크가 보인다", async () => {
  const { models, picks } = await sample();
  const root = mount(<Gallery models={models} kinds={kindsOf(picks)} />);

  const open = root.querySelector("#model-qwen3\\.8-27b-gsq .model-license")!;
  expect(open.textContent).toBe("라이선스Apache 2.0");
  expect(open.querySelector("a")).toBeNull();

  const terms = root.querySelector(`${SWIFT_CARD} .model-license`)!;
  expect(terms.textContent).toContain("Swift Open License v1.0");
  expect(terms.querySelector(".model-license-terms")?.textContent).toBe("사용 조건 있음");
  const link = terms.querySelector("a")!;
  expect(link.textContent).toBe("원문 보기");
  expect(link.getAttribute("href")).toBe("https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF/blob/main/LICENSE");
  expect(link.getAttribute("target")).toBe("_blank");
  expect(link.getAttribute("rel")).toBe("noreferrer");

  // 옛 백엔드(`license_open` 칸이 없다)는 표시 없이 이름만.
  const old = root.querySelector("#model-gemma4-26b-qat .model-license")!;
  expect(old.textContent).toBe("라이선스Apache 2.0");
});

it("ⓐ 라이선스가 빈 글이면 줄이 없고, 원문 주소가 비면 링크만 빠진다 · 외부 모델 카드는 라이선스를 한 번만 적는다", async () => {
  const { models } = await sample();
  const swift = models.find((m) => m.key === "qwen3.8-27b-swift")!;
  const none = mount(<ModelCard model={{ ...swift, family: "", license: "" }} {...cardProps} />);
  expect(none.querySelector(".model-license")).toBeNull();
  host?.remove();

  const noUrl = mount(<ModelCard model={{ ...swift, family: "", license_url: "" }} {...cardProps} />);
  expect(noUrl.querySelector(".model-license-terms")).not.toBeNull();
  expect(noUrl.querySelector(".model-license a")).toBeNull();
  host?.remove();

  const external = models.find((m) => m.status === "external" && m.license)!;
  const card = mount(<ModelCard model={external} {...cardProps} />);
  expect(card.querySelector(".model-unverified")?.textContent).toBe("Sonjari가 직접 시험한 모델은 아닙니다");
  expect(card.textContent!.split(external.license).length - 1).toBe(1);
});

it("ⓑ 추천의 open_alternative 카드에 「조건 없는 대안」 배지 — 추천을 듣기 전에는 다른 배지처럼 안 보인다", async () => {
  const { models, picks } = await sample();
  expect(picks.some((pick) => pick.kind === "open_alternative" && pick.model_key === "qwen3.8-27b-gsq")).toBe(true);

  const root = mount(<Gallery models={models} kinds={kindsOf(picks)} />);
  const badge = root.querySelector("#model-qwen3\\.8-27b-gsq .model-badge")!;
  expect(badge.textContent).toBe("조건 없는 대안");
  expect(badge.classList.contains("is-open")).toBe(true);
  expect(badge.classList.contains("is-external")).toBe(false);
  expect(root.querySelector("#model-gemma4-26b-qat .model-badge")?.textContent).toBe("Sonjari 추천 · 실측");
  host?.remove();

  const before = mount(<Gallery models={models} kinds={kindsOf(picks)} asked={false} />);
  expect(before.querySelector(".model-badge")).toBeNull();
});

it("ⓒ 같은 family 둘은 카드 하나로 합쳐지고, 크기 칩 둘이 받는 크기 순서로 보인다", async () => {
  const { models, picks } = await sample();
  const swifts = models.filter((m) => m.family === "swift-27b");
  expect(swifts.map((m) => m.key).sort()).toEqual(["qwen3.8-27b-swift", "qwen3.8-27b-swift-iq3xxs"]);

  const root = mount(<Gallery models={models} kinds={kindsOf(picks)} />);
  expect(root.querySelectorAll(SWIFT_CARD).length).toBe(1);
  expect(root.querySelectorAll(".model-card").length).toBe(models.length - 1);
  const card = root.querySelector(SWIFT_CARD)!;
  expect(card.querySelector("h2")?.textContent).toBe("Swift 1.5 · Qwen 3.8 27B");
  expect(card.querySelector(".model-size-label")?.textContent).toBe("크기 고르기");
  expect(card.querySelector(".model-size-chips")?.getAttribute("role")).toBe("radiogroup");

  const sizes = sizeChips(card);
  expect(sizes.map((chip) => chip.textContent)).toEqual(["3비트 작게 · 11.4GB", "3비트 · 13.1GB"]);
  // 양자화 코드는 이름표가 아니라 title 로만.
  expect(sizes.map((chip) => chip.title)).toEqual(["IQ3_XXS", "IQ3_S"]);
  expect(card.textContent).not.toContain("IQ3_S");
  expect(card.textContent).not.toContain("양자화");
});

it("ⓒ 묶음 카드는 묶음에서 먼저 나온 변형의 자리에 선다", () => {
  const row = (key: string, family = "") => ({ key, family, status: "verified" }) as CatalogModel;
  const groups = groupFamilies([row("a"), row("s1", "fam"), row("b"), row("s2", "fam")]);
  expect(groups.map((group) => group.variants.map((m) => m.key))).toEqual([["a"], ["s1", "s2"], ["b"]]);
  expect(groups[1].id).toBe(modelCardId(row("s2", "fam")));
});

it("ⓓ 다른 크기 칩을 누르면 받는 크기·창 칩이 그 크기의 것으로 바뀌고, 고른 key 도 그 크기의 key 다", async () => {
  const { models, picks } = await sample();
  const onPick = vi.fn();
  const root = mount(<Gallery models={models} kinds={kindsOf(picks)} onPick={onPick} />);
  const card = root.querySelector(SWIFT_CARD)!;

  // 처음: 추천에 이 묶음이 없으니 들어가는 것 가운데 가장 큰 크기. 아직 아무것도 고르지 않았다.
  expect(sizeChips(card).map((chip) => chip.getAttribute("aria-checked"))).toEqual(["false", "true"]);
  expect(card.querySelector("header p")?.textContent).toContain("13.1GB");
  expect(ctxChips(card).map((chip) => chip.textContent)).toEqual(["128K18.9", "64K16.1", "32K14.8"]);
  expect(onPick).not.toHaveBeenCalled();
  expect(card.classList.contains("is-picked")).toBe(false);

  act(() => sizeChips(card)[0].click());
  expect(sizeChips(card).map((chip) => chip.getAttribute("aria-checked"))).toEqual(["true", "false"]);
  expect(card.querySelector("header p")?.textContent).toContain("11.4GB");
  expect(ctxChips(card).map((chip) => chip.textContent)).toEqual(["128K17.3", "64K14.6", "32K13.5"]);
  expect(card.querySelector(".model-blurb")?.textContent).toBe("같은 모델을 더 작게 눌러 담은 크기입니다. 받는 크기와 메모리가 조금 줄어듭니다.");
  // 고른 창은 그 크기에 들어가는 가장 큰 창으로 다시 맞춘다.
  expect(onPick).toHaveBeenLastCalledWith("qwen3.8-27b-swift-iq3xxs", 131072);
  expect(ctxChips(card).map((chip) => chip.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
  expect(card.classList.contains("is-picked")).toBe(true);
  // 카드의 자리(id)는 크기를 바꿔도 그대로다 — 추천 뒤 스크롤이 이 자리를 찾는다.
  expect(root.querySelector(SWIFT_CARD)).toBe(card);

  // 창을 누르면 지금 보이는 크기의 key 로 간다.
  act(() => ctxChips(card)[1].click());
  expect(onPick).toHaveBeenLastCalledWith("qwen3.8-27b-swift-iq3xxs", 65536);
  act(() => sizeChips(card)[1].click());
  expect(onPick).toHaveBeenLastCalledWith("qwen3.8-27b-swift", 131072);
});

it("ⓓ 추천(verified)이 묶음 안에 있으면 그 크기가 처음 골라져 있고 「이 PC 추천」 표시가 그 칩에만 붙는다", async () => {
  const { models } = await sample();
  const kinds = kindsOf([{ model_key: "qwen3.8-27b-swift-iq3xxs", kind: "verified" }]);
  const ends = vi.fn();
  const root = mount(<Gallery models={models} kinds={kinds} pulse="qwen3.8-27b-swift-iq3xxs" onPulseEnd={ends} />);
  const card = root.querySelector(SWIFT_CARD)!;
  const [small, big] = sizeChips(card);

  expect(small.getAttribute("aria-checked")).toBe("true");
  expect(small.textContent).toBe("3비트 작게 · 11.4GB이 PC 추천");
  expect(small.classList.contains("is-rec")).toBe(true);
  expect(big.textContent).toBe("3비트 · 13.1GB");
  expect(big.classList.contains("is-rec")).toBe(false);
  expect(card.querySelector(".model-badge")?.textContent).toBe("Sonjari 추천 · 실측");
  // 묶음 안의 key 로 깜빡이라고 하면 그 카드가 깜빡인다.
  expect(card.classList.contains("is-pulsing")).toBe(true);

  // 다른 크기를 봐도 표시는 추천 칩에 그대로 남는다(늘 붙는다).
  act(() => big.click());
  expect(sizeChips(card)[0].classList.contains("is-rec")).toBe(true);
  expect(sizeChips(card)[1].classList.contains("is-rec")).toBe(false);

  // 칩의 강조가 끝난 것을 카드 깜빡임이 끝난 것으로 읽지 않는다.
  // (가짜 브라우저에서 React 가 듣는 이름이 환경마다 달라 둘 다 보낸다. 카드에서 불리는 것을 같이 봐야 앞의 「안 불림」이 뜻을 가진다.)
  const animationEnds = (target: Element) => act(() => {
    for (const name of ["animationend", "webkitAnimationEnd"]) target.dispatchEvent(new Event(name, { bubbles: true }));
  });
  animationEnds(small);
  expect(ends).not.toHaveBeenCalled();
  animationEnds(card);
  expect(ends).toHaveBeenCalledTimes(1);
});

it("ⓓ 바깥에서 묶음의 다른 크기를 고르면(추천을 받아 고른 경우) 카드가 그 크기를 보인다", async () => {
  const { models } = await sample();
  const swifts = models.filter((m) => m.family === "swift-27b");
  const root = mount(
    <ModelCard model={swifts[0]} variants={swifts} {...cardProps} pickedKey="qwen3.8-27b-swift-iq3xxs" picked={32768} />,
  );
  expect(sizeChips(root).map((chip) => chip.getAttribute("aria-checked"))).toEqual(["true", "false"]);
  expect(ctxChips(root).map((chip) => chip.getAttribute("aria-checked"))).toEqual(["false", "false", "true"]);
});

it("ⓔ 이 PC 에 안 들어가는 크기 칩은 누를 수 없고, 처음에는 들어가는 것 가운데 가장 큰 크기가 골라져 있다", async () => {
  const { models } = await sample();
  const swifts = models.filter((m) => m.family === "swift-27b")
    .map((m) => (m.key === "qwen3.8-27b-swift" ? { ...m, fits: false, largest_fitting_ctx: null } : m));
  const onPick = vi.fn();
  const root = mount(<ModelCard model={swifts[0]} variants={swifts} {...cardProps} usable={14.0} onPick={onPick} />);
  const [small, big] = sizeChips(root);

  expect(big.disabled).toBe(true);
  expect(big.title).toBe("IQ3_S — 이 PC 에 안 들어갑니다");
  expect(small.disabled).toBe(false);
  expect(small.getAttribute("aria-checked")).toBe("true");
  act(() => big.click());
  expect(onPick).not.toHaveBeenCalled();
  expect(root.querySelector("header p")?.textContent).toContain("11.4GB");
});

it("ⓔ 어느 크기도 안 들어가는 PC 에서는 칩이 전부 꺼지고 카드는 예전처럼 「안 들어갑니다」를 말한다", async () => {
  const { models, picks } = await sample("4060-8gb");
  const root = mount(<Gallery models={models} kinds={kindsOf(picks)} usable={7} />);
  const card = root.querySelector(SWIFT_CARD)!;
  expect(sizeChips(card).every((chip) => chip.disabled)).toBe(true);
  expect(card.classList.contains("is-nofit")).toBe(true);
  expect(card.textContent).toContain("이 PC 에는 어느 설정도 안 들어갑니다.");
  // 그 PC 에 안 들어가는 대안은 추천에 넣지 않는다.
  expect(picks.some((pick) => pick.kind === "open_alternative")).toBe(false);
});

it("ⓕ family 가 빈 모델과 옛 백엔드의 모델에는 크기 줄이 없다 — 예전 카드 그대로", async () => {
  const { models, picks } = await sample();
  const onPick = vi.fn();
  const root = mount(<Gallery models={models} kinds={kindsOf(picks)} onPick={onPick} />);

  for (const key of ["qwen3.8-27b-gsq", "gemma4-26b-qat"]) {
    const model = models.find((m) => m.key === key)!;
    const card = root.querySelector(`[id="model-${key}"]`)!;
    expect(card.querySelector(".model-size")).toBeNull();
    expect(card.querySelector("h2")?.textContent).toBe(model.name);
    expect(card.querySelectorAll('[role="radiogroup"]').length).toBe(1);
  }
  expect("family" in models.find((m) => m.key === "gemma4-26b-qat")!).toBe(false);

  const gemma = root.querySelector('[id="model-gemma4-26b-qat"]')!;
  act(() => ctxChips(gemma)[0].click());
  expect(onPick).toHaveBeenLastCalledWith("gemma4-26b-qat", 131072);
  expect(gemma.classList.contains("is-picked")).toBe(true);

  // family 는 있는데 그 크기 하나뿐이면 고를 것이 없다 — 줄을 그리지 않는다.
  host?.remove();
  const swift = models.find((m) => m.key === "qwen3.8-27b-swift")!;
  const alone = mount(<ModelCard model={swift} variants={[swift]} {...cardProps} />);
  expect(alone.querySelector(".model-size")).toBeNull();
  expect(alone.querySelector("h2")?.textContent).toBe(swift.name);
});
