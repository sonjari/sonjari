/**
 * 화면 리허설 진입점 — **개발 빌드 전용**.
 *
 * 이 모듈은 `backend.ts` 의 `createBackendClient` 가 동적 import 로만 가져온다.
 * 정적으로 가져오면 시나리오 원문과 조종대 CSS 가 릴리스 번들에 그대로 실린다
 * (2026-08-19 실측: `fixture-action-1` 과 시나리오 본문이 릴리스 js 에서 발견됨).
 */
import type { JarvisEvent } from "../types";
import { FixtureClient } from "./FixtureClient";
import { findScenario } from "./scenarios";

let active: FixtureClient | null = null;

/** 지금 재생 중인 시나리오 이름. 리허설이 아니면 빈 문자열. */
export function fixtureName(): string {
  if (!import.meta.env.DEV) return "";
  return new URLSearchParams(window.location.search).get("fixture") ?? "";
}

/** FixtureBar 가 재생을 조종할 때 쓰는 손잡이. */
export function activeFixture(): FixtureClient | null {
  return active;
}

/** 이름에 해당하는 시나리오가 있으면 가짜 클라이언트를, 없으면 null 을 준다. */
export function createFixtureClient(
  name: string,
  onEvent: (event: JarvisEvent) => void,
  onConnection: (connected: boolean) => void,
): FixtureClient | null {
  const scenario = findScenario(name);
  if (!scenario) return null;
  active = new FixtureClient(scenario, onEvent, onConnection);
  return active;
}
