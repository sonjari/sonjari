/**
 * 리허설 조종대. 개발 빌드에서 `?fixture=` 가 있을 때만 뜬다.
 *
 * 배속이 핵심 기능이다. 180ms 짜리 움직임은 실시간으로는 "그냥 나타났다"로만
 * 보이고, 어디서 나와서 어디로 가는지는 0.25배속에서만 보인다.
 */
import { useEffect, useState } from "react";
import { activeFixture, fixtureName } from "./index";
import { SCENARIOS, findScenario } from "./scenarios";
import "./fixtures.css";

const SPEEDS = [1, 0.5, 0.25];

/** 작성창에 문장을 넣고 실제 보내기 흐름을 태운다 — 리허설도 진짜 문으로 들어간다. */
function sendThroughComposer(text: string) {
  const textarea = document.querySelector<HTMLTextAreaElement>(".workspace-composer textarea");
  const form = document.querySelector<HTMLFormElement>("form.workspace-composer");
  if (!textarea || !form) return;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
  setter?.call(textarea, text);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  window.setTimeout(() => form.requestSubmit(), 30);
}

export function FixtureBar() {
  const current = fixtureName();
  const scenario = findScenario(current);
  const [speed, setSpeed] = useState(1);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    activeFixture()?.setSpeed(speed);
  }, [speed]);

  if (!import.meta.env.DEV || !scenario) return null;

  const go = (id: string) => {
    const params = new URLSearchParams(window.location.search);
    params.set("mode", "workspace");
    params.set("fixture", id);
    window.location.search = params.toString();
  };

  const replay = () => {
    activeFixture()?.replayAmbient();
    if (scenario.prompt) window.setTimeout(() => sendThroughComposer(scenario.prompt!), 120);
  };

  return (
    <div className={`fixture-bar ${open ? "" : "closed"}`}>
      <button className="fixture-toggle" onClick={() => setOpen((value) => !value)} title="리허설 조종대">
        리허설
      </button>
      {open && (
        <div className="fixture-body">
          <select value={current} onChange={(event) => go(event.target.value)}>
            {SCENARIOS.map((row) => (
              <option key={row.id} value={row.id}>{row.label}</option>
            ))}
          </select>
          <div className="fixture-speeds">
            {SPEEDS.map((value) => (
              <button
                key={value}
                className={speed === value ? "on" : ""}
                onClick={() => setSpeed(value)}
              >
                {value === 1 ? "1x" : `${value}x`}
              </button>
            ))}
            <button className="fixture-replay" onClick={replay}>다시 재생</button>
          </div>
          <p>{scenario.hint}</p>
        </div>
      )}
    </div>
  );
}

export default FixtureBar;
