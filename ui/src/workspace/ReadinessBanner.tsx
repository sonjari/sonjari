import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import { isTauri, type JarvisClient } from "../backend";
import { t } from "../i18n";
import { readinessProblem, type ReadinessProblem } from "./readiness";

/**
 * 부탁하기 전에 「모델 없음 · 엔진 꺼짐 · 집 PC 안 닿음」을 안다(F2 · G2) — 판정은 백엔드 `/health` 값만 읽는다.
 *
 * ★ 11-08 대표: 입력창 위에 툭 튀어나오던 노란 카드가 거슬린다 — 「이모티콘 말고 그림으로」.
 *   그래서 카드를 없애고 **모델 칩의 자리 그림**(`PlaceMark`)이 상태를 말한다. 까닭과 단추는 칩을 누르면 펼쳐지는 창 맨 위에.
 */
export function useReadiness(client: JarvisClient | null, connected: boolean): ReadinessProblem | null {
  const [problem, setProblem] = useState<ReadinessProblem | null>(null);
  useEffect(() => {
    if (!client || !connected) {
      setProblem(null);
      return;
    }
    let alive = true;
    const check = async () => {
      try {
        const health = await client.getHealth();
        if (alive) setProblem(readinessProblem(health.ollama));
      } catch {
        if (alive) setProblem(null); // 백엔드에 못 닿는 것은 다른 배너가 말한다
      }
    };
    void check();
    // ★ 2026-09-20: 문제가 떠 있는 동안은 3초마다(풀리는 순간 사라지게) · 아무 문제 없을 때는 30초.
    const timer = window.setInterval(check, problem ? 3_000 : 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, connected, problem?.kind]);
  return problem;
}

export async function openSetupWindow(): Promise<void> {
  if (isTauri()) {
    try {
      await invoke("open_setup");
      return;
    } catch {
      /* 창을 못 열면 같은 창에서 연다 */
    }
  }
  window.location.search = "?mode=setup";
}

/** 모델 창 맨 위 한 줄 — 무엇이 문제인지와(있으면) 누를 것 하나. */
export function ReadinessStatus({ problem }: { problem: ReadinessProblem }) {
  return (
    <div className={`readiness-status is-${problem.kind}`} role="status">
      <strong>{problem.title}</strong>
      <p>{problem.detail}</p>
      {problem.action && (
        <button type="button" className="readiness-action" onClick={() => void openSetupWindow()}>{problem.action}</button>
      )}
    </div>
  );
}

/** 칩 제목(마우스를 올렸을 때)에 붙일 한 줄. */
export function readinessTitle(problem: ReadinessProblem | null): string {
  return problem ? t("{0} — 눌러서 자세히", problem.title) : "";
}
