// @vitest-environment jsdom
/**
 * 추천 문으로 들어온 사람에게는 추천한 모델만 먼저 보인다 (2026-10-12).
 *
 * 처음 깐 사람: 「모델들이 너무 많아서 어렵다」. 추천 문으로 들어왔는데도 카드 열 장과 탭 셋이 한꺼번에 펼쳐졌다.
 * 지키는 것: 추천한 그 모델이 맨 앞 · 라이선스의 「조건 없는 대안」은 같이 · 같은 묶음의 다른 크기와 그 밖의 모델은 뒤에 ·
 * 추천이 없으면 추리지 않는다(빈 화면을 만들지 않는다).
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { ModelGallery, recommendedOnly } from "./SetupWizard";
import { createFixtureSetupApi } from "./fixtureSetupApi";
import type { CatalogModel, Recommendation } from "./setupApi";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function models(): Promise<CatalogModel[]> {
  const view = await createFixtureSetupApi("3090")!.models();
  const base = view.models[0];
  const make = (key: string, extra: Partial<CatalogModel> = {}): CatalogModel =>
    ({ ...base, key, name: key, family: "", status: "verified", fits: true, ...extra });
  return [
    make("big-27b", { family: "fam-27b" }),
    make("small-27b", { family: "fam-27b" }),
    make("open-9b"),
    make("tiny-4b"),
    make("outside-12b", { status: "external" }),
  ];
}

function rec(over: Partial<Recommendation> = {}): Recommendation {
  return {
    mode: "local", model_key: "small-27b", num_ctx: 65536, reasons: [], warnings: [],
    picks: [
      { kind: "verified", model_key: "small-27b" },
      { kind: "open_alternative", model_key: "open-9b" },
      { kind: "external", model_key: "outside-12b" },
    ],
    ...over,
  } as unknown as Recommendation;
}

it("keeps the recommended model and the condition-free alternative, in that order", async () => {
  const all = await models();
  expect(recommendedOnly(all, rec()).map((model) => model.key)).toEqual(["small-27b", "open-9b"]);
});

it("does not bring along the other sizes of the same family or the unverified pick", async () => {
  const keys = recommendedOnly(await models(), rec()).map((model) => model.key);
  expect(keys).not.toContain("big-27b");
  expect(keys).not.toContain("outside-12b");
  expect(keys).not.toContain("tiny-4b");
});

it("shows the outside pick when that is what was recommended", async () => {
  const outside = rec({ model_key: "outside-12b", picks: [{ kind: "external", model_key: "outside-12b" }] } as Partial<Recommendation>);
  expect(recommendedOnly(await models(), outside).map((model) => model.key)).toEqual(["outside-12b"]);
});

it("narrows nothing when there is no recommendation", async () => {
  const all = await models();
  expect(recommendedOnly(all, null)).toEqual([]);
  expect(recommendedOnly(all, rec({ model_key: null }))).toEqual([]);
});

it("draws the short list without group headings", async () => {
  const all = await models();
  const short = recommendedOnly(all, rec());
  const host = document.createElement("div");
  document.body.appendChild(host);
  const pickKinds = new Map<string, "verified" | "open_alternative" | "external">([["small-27b", "verified"], ["open-9b", "open_alternative"]]);
  await act(async () => {
    createRoot(host).render(
      <ModelGallery plain models={short} pickKinds={pickKinds as never} usable={15} asked pulse="" onPulseEnd={() => {}}
        picked={null} onPick={() => {}} />,
    );
  });
  expect(host.querySelector(".gallery-head")).toBeNull();
  expect(host.querySelectorAll(".setup-gallery.is-plain > *").length).toBe(2);
  host.remove();
});
