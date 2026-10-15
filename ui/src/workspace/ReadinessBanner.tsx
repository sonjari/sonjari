import { invoke } from "@tauri-apps/api/core";
import { Cpu } from "lucide-react";
import { useEffect, useState } from "react";
import { isTauri, type JarvisClient } from "../backend";
import { readinessProblem, type ReadinessProblem } from "./readiness";

/** 부탁하기 전에 「모델 없음·엔진 꺼짐」을 말하고 첫 실행 화면으로 보낸다(F2 · G2). */
export function ReadinessBanner({ client, connected }: { client: JarvisClient | null; connected: boolean }) {
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
    return () => {
      alive = false;
    };
  }, [client, connected]);

  // ★ 2026-09-20: 30초마다만 다시 봐서, 엔진이 켜진 뒤에도 경고가 최대 30초 남았다.
  //   문제가 떠 있는 동안은 3초마다 본다(켜지는 순간 사라지게). 아무 문제 없을 때는 30초.
  useEffect(() => {
    if (!client || !connected) return;
    let alive = true;
    const timer = window.setInterval(async () => {
      try {
        const health = await client.getHealth();
        if (alive) setProblem(readinessProblem(health.ollama));
      } catch {
        if (alive) setProblem(null);
      }
    }, problem ? 3_000 : 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [client, connected, problem?.kind]);

  if (!problem) return null;
  const openSetup = async () => {
    if (isTauri()) {
      try {
        await invoke("open_setup");
        return;
      } catch {
        /* 창을 못 열면 같은 창에서 연다 */
      }
    }
    window.location.search = "?mode=setup";
  };
  return (
    <div className="attention-banner readiness-banner" role="status">
      <span className="attention-banner-icon"><Cpu size={16} /></span>
      <div>
        <strong>{problem.title}</strong>
        <p>{problem.detail}</p>
      </div>
      {problem.action && (
        <button type="button" className="readiness-action" onClick={() => void openSetup()}>{problem.action}</button>
      )}
    </div>
  );
}
