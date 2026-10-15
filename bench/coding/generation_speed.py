"""같은 프롬프트를 여러 번 생성하며 **토큰 속도와 GPU 상태를 같이** 잰다 (2026-09-21, 「편차 3배」의 원인 가르기).

관찰: 같은 과제 AURORA 의 **첫 `write_file`**(index.html 전체 생성) 호출이 88초·87초인 판과 283초·297초인 판이 있었다.
파일 크기(13~20KB)는 비슷했고, 사고량은 오히려 느린 쪽이 적었다(7.4KB). 그러면 남는 것은 **생성 속도 자체**다.

후보:  ① 그 시각의 부하(MSIX 빌드·git)   ② GPU 클럭이 오르내리는 고장(2070 사건과 같은 모양 — 진동하는 고장은 점 측정에 속는다)
       ③ 다른 Ollama 손님이 큐에서 끼어듦   ④ 그냥 표본 잡음

그래서 **분포로** 잰다: 한 번이 아니라 n 번, 속도와 함께 GPU SM 클럭·전력·상태(pstate)를 1초마다 적는다.
`--load cpu` 를 주면 모든 코어를 태우면서 재서 「부하 탓」을 직접 시험한다.

    python generation_speed.py --n 6
    python generation_speed.py --n 6 --load cpu
"""
from __future__ import annotations

import argparse
import io
import json
import multiprocessing
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
OLLAMA = "http://127.0.0.1:11434"
PROMPT = (
    "index.html 단일 파일로 '한밤의 오로라 항해 관측소' 페이지를 만들어라. CSS 애니메이션 오로라, 관측 목적지 카드 3개, "
    "각 카드의 관측 확률, 클릭하면 반응하는 버튼을 넣어라. 파일 내용만 출력하라."
)


def _burn() -> None:
    while True:
        pass


def gpu_sample() -> list[dict]:
    done = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,clocks.sm,clocks.max.sm,power.draw,pstate,utilization.gpu,temperature.gpu",
         "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    rows = []
    for line in done.stdout.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 7:
            rows.append({"gpu": p[0], "sm": float(p[1] or 0), "sm_max": float(p[2] or 0), "watt": float(p[3] or 0),
                         "pstate": p[4], "util": float(p[5] or 0), "temp": float(p[6] or 0)})
    return rows


def loaded() -> tuple[str, int]:
    running = json.load(urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10)).get("models") or []
    if not running:
        raise SystemExit("올라와 있는 모델이 없다 — 운영 모델이 떠 있을 때 돌려라")
    return running[0]["name"], int(running[0].get("context_length") or 0)


def generate(model: str, ctx: int, tokens: int) -> dict:
    body = {"model": model, "prompt": PROMPT, "stream": False, "think": False,
            "options": {"num_ctx": ctx, "num_predict": tokens, "temperature": 0.2}, "keep_alive": "24h"}
    request = urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=900))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=6)
    parser.add_argument("--tokens", type=int, default=1500)
    parser.add_argument("--load", choices=["none", "cpu"], default="none")
    args = parser.parse_args()
    model, ctx = loaded()
    print(f"모델 {model} · 컨텍스트 {ctx:,} · n={args.n} · 생성 {args.tokens} 토큰 · 부하={args.load}")

    burners = []
    if args.load == "cpu":
        burners = [multiprocessing.Process(target=_burn, daemon=True) for _ in range(max(2, multiprocessing.cpu_count() - 2))]
        for proc in burners:
            proc.start()
        print(f"CPU 부하 프로세스 {len(burners)}개 가동")
        time.sleep(3)

    generate(model, ctx, 8)  # 예열 — 첫 호출의 로딩 시간을 재지 않는다
    results = []
    for index in range(1, args.n + 1):
        samples: list[list[dict]] = []
        stop = threading.Event()

        def watch() -> None:
            while not stop.is_set():
                try:
                    samples.append(gpu_sample())
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(1.0)

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        started = time.time()
        out = generate(model, ctx, args.tokens)
        wall = time.time() - started
        stop.set()
        thread.join(timeout=3)
        eval_count = int(out.get("eval_count") or 0)
        eval_seconds = float(out.get("eval_duration") or 0) / 1e9
        prompt_seconds = float(out.get("prompt_eval_duration") or 0) / 1e9
        rate = eval_count / eval_seconds if eval_seconds else 0.0
        per_gpu: dict[str, dict] = {}
        for snap in samples:
            for row in snap:
                g = per_gpu.setdefault(row["gpu"], {"sm": [], "watt": [], "pstate": set(), "util": [], "sm_max": row["sm_max"]})
                g["sm"].append(row["sm"]); g["watt"].append(row["watt"]); g["pstate"].add(row["pstate"]); g["util"].append(row["util"])
        gpus = {gpu: {"sm_min": min(v["sm"]), "sm_avg": round(statistics.mean(v["sm"])), "sm_max": v["sm_max"],
                      "watt_avg": round(statistics.mean(v["watt"])), "util_avg": round(statistics.mean(v["util"])),
                      "pstates": sorted(v["pstate"])} for gpu, v in per_gpu.items() if v["sm"]}
        results.append({"n": index, "tok_s": round(rate, 1), "eval_s": round(eval_seconds, 1), "wall_s": round(wall, 1),
                        "prompt_s": round(prompt_seconds, 2), "tokens": eval_count, "gpus": gpus})
        print(f"#{index}: {rate:5.1f} tok/s · 생성 {eval_seconds:5.1f}s · 벽시계 {wall:5.1f}s · "
              + " | ".join(f"GPU{g} SM {v['sm_avg']}/{v['sm_max']:.0f}MHz {v['watt_avg']}W util {v['util_avg']}% {v['pstates']}"
                           for g, v in gpus.items()), flush=True)

    for proc in burners:
        proc.terminate()
    rates = [r["tok_s"] for r in results if r["tok_s"]]
    if rates:
        print(f"\n속도 분포: 최소 {min(rates)} · 중앙 {statistics.median(rates):.1f} · 최대 {max(rates)} tok/s "
              f"(최대/최소 = {max(rates) / max(min(rates), 0.1):.2f}배)")
        print("→ 판의 3배 편차(88초 대 283초)가 여기서 재현되면 원인은 생성 속도이고, 안 되면 다른 곳이다.")
    print("JSON:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
