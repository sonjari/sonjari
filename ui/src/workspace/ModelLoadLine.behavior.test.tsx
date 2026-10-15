// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ModelLoadLine, type ModelLoading } from "./ModelLoadLine";

async function mount(answers: ModelLoading[]) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const client = { getModelLoading: vi.fn(async () => answers.length > 1 ? answers.shift()! : answers[0]) };
  const onResident = vi.fn();
  await act(async () => root.render(<ModelLoadLine client={client} onResident={onResident} />));
  await act(async () => { await Promise.resolve(); });
  return { host, root, onResident };
}

it("draws the measured fraction, the GB and the last load time", async () => {
  const { host, root } = await mount([{ loading: true, fraction: 0.42, loaded_gb: 3.1, expected_gb: 7.4,
    basis: "measured", elapsed_s: 12, last_seconds: 41 }]);
  try {
    expect(host.textContent).toContain("모델을 그래픽카드에 올리는 중 42%");
    expect(host.textContent).toContain("3.1 / 7.4GB");
    expect(host.textContent).toContain("지난번 41초");
    expect(host.querySelector<HTMLElement>(".workspace-load-track > span")?.style.width).toBe("42%");
  } finally {
    await act(async () => root.unmount());
  }
});

it("says the size is an estimate on the first load", async () => {
  const { host, root } = await mount([{ loading: true, fraction: 0.1, loaded_gb: 0.7, expected_gb: 6.9,
    basis: "estimated", elapsed_s: 4, last_seconds: null }]);
  try {
    expect(host.textContent).toContain("처음이라 크기는 추정");
  } finally {
    await act(async () => root.unmount());
  }
});

it("never invents a percentage when the card can't be measured", async () => {
  const { host, root } = await mount([{ loading: true, fraction: null, basis: "unmeasured", elapsed_s: 9, last_seconds: null }]);
  try {
    expect(host.textContent).not.toMatch(/\d+%/);
    expect(host.querySelector(".workspace-load-track.is-waiting")).not.toBeNull();
    expect(host.textContent).toContain("9초째");
  } finally {
    await act(async () => root.unmount());
  }
});

it("hands back as soon as the model is resident", async () => {
  const { root, onResident } = await mount([{ loading: false, resident: true }]);
  try {
    expect(onResident).toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
  }
});
