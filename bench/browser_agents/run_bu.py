"""Browser Use 를 자비스와 같은 모델·같은 예산으로 돌리고, 이동한 주소를 전부 남긴다.

재는 것:  갔는가(어느 호스트) · 몇 걸음 · 몇 초 · 이동한 URL 전부 · 벽을 만났는가
안 재는 것: 답이 좋았는가 (사람이 읽는다)
"""
from __future__ import annotations
import argparse, asyncio, json, sys, time, traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "plopfit-gemma4-qat:latest"
NUM_CTX = 131072
OLLAMA_HOST = "http://127.0.0.1:11434"

# 벽은 200 으로 온다. 본문 마커로만 잡힌다.
WALL_MARKERS = [
    "access denied", "reference #", "captcha", "cloudflare",
    "비정상적인 접근", "잠시 후 다시", "자동입력 방지", "robot",
    "unusual traffic", "blocked", "forbidden",
]


async def run_task(prompt: str, host: str, budget: int, max_steps: int,
                   provider: str = "ollama", frontier_model: str = "claude-sonnet-5") -> dict:
    from browser_use import Agent
    if provider == "anthropic":
        # 대조군. "로컬 26B 로 돌려놓고 못한다고 하네" 라는 반론을 없애기 위한 팔.
        # 키는 환경변수로만 들어온다 — 코드에도 로그에도 안 남는다.
        from browser_use import ChatAnthropic
        llm = ChatAnthropic(model=frontier_model)
    else:
        from browser_use import ChatOllama
        # ★ 이 PC 의 OLLAMA_HOST 는 0.0.0.0 (서버 바인딩 주소)이다. 클라이언트
        # 라이브러리가 같은 변수를 "접속할 곳"으로 읽어서 죽는다. 명시로 못 박는다.
        llm = ChatOllama(model=MODEL, host=OLLAMA_HOST,
                         ollama_options={"num_ctx": NUM_CTX})
    row = {"prompt": prompt, "expect_host": host, "urls": [], "steps": 0,
           "seconds": 0.0, "answer": "", "error": "", "wall": False}
    started = time.time()
    agent = Agent(task=prompt, llm=llm)
    try:
        history = await asyncio.wait_for(agent.run(max_steps=max_steps), timeout=budget)
        row["seconds"] = round(time.time() - started, 1)
        for getter in ("urls", "action_names", "final_result", "number_of_steps"):
            try:
                value = getattr(history, getter)()
                if getter == "urls":
                    row["urls"] = [u for u in value if u and u != "about:blank"]
                elif getter == "final_result":
                    row["answer"] = (value or "")[:1500]
                elif getter == "number_of_steps":
                    row["steps"] = int(value or 0)
                elif getter == "action_names":
                    row["actions"] = list(value)[:80]
            except Exception as exc:                      # 없는 접근자는 조용히 넘어간다
                row.setdefault("history_gaps", []).append(f"{getter}: {exc}")
    except asyncio.TimeoutError:
        row["seconds"] = round(time.time() - started, 1)
        row["error"] = f"timeout>{budget}s"
    except Exception as exc:
        row["seconds"] = round(time.time() - started, 1)
        row["error"] = f"{type(exc).__name__}: {exc}"[:400]
        row["trace"] = traceback.format_exc()[-1200:]
    finally:
        try:
            await agent.close()
        except Exception:
            pass
    blob = (row.get("answer", "") + " ".join(row["urls"])).lower()
    row["wall"] = any(m in blob for m in WALL_MARKERS)
    row["reached"] = bool(host) and any(host in u for u in row["urls"])
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--host", default="")
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--max-steps", type=int, default=25)
    ap.add_argument("--out", default="")
    ap.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"])
    ap.add_argument("--frontier-model", default="claude-sonnet-5")
    args = ap.parse_args()
    row = await run_task(args.prompt, args.host, args.budget, args.max_steps,
                         args.provider, args.frontier_model)
    row["provider"] = args.provider
    row["model"] = args.frontier_model if args.provider == "anthropic" else MODEL
    text = json.dumps(row, ensure_ascii=False, indent=1)
    print(text)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    asyncio.run(main())
