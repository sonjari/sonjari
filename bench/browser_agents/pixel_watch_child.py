"""화면의 몇 점을 계속 읽어 **기준 색과 달라진 순간**을 파일에 적는다 (measure_chrome_flash.py 의 자식 프로세스).

같은 프로세스 스레드로 돌리면 GIL·화면 캡처 부하가 측정 대상의 타이밍을 바꿔 버려서 별도 프로세스다.

표집 주기: GDI `GetPixel` 은 점당 ~10ms 라 3점이면 한 번 훑는 데 ~30ms 다. PIL `ImageGrab` 은 점당 75ms
(판당 40번)여서 애니메이션조차 놓쳤다. 이 주기로는 10~30ms 짜리 번쩍임은 놓치고, 최소화 해제 애니메이션
(150~250ms)처럼 긴 것은 5~8 프레임으로 잡는다 — 그것이 이 눈금의 몫이다(짧은 것은 z 순서 눈금이 맡는다).

    python pixel_watch_child.py <출력.jsonl> <지속 초>
"""
import ctypes
import json
import sys
import time

POINTS = ((300, 300), (960, 500), (1500, 800))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = ctypes.c_uint
user32.GetDC.restype = ctypes.c_void_p


def main() -> None:
    hdc = user32.GetDC(0)
    out = open(sys.argv[1], "w", buffering=1, encoding="utf-8")
    base = [gdi32.GetPixel(hdc, x, y) for x, y in POINTS]
    out.write(json.dumps({"base": base}) + "\n")
    end = time.time() + float(sys.argv[2])
    grabs = 0
    while time.time() < end:
        now = [gdi32.GetPixel(hdc, x, y) for x, y in POINTS]
        grabs += 1
        changed = sum(1 for a, b in zip(now, base) if a != b)
        if changed:
            out.write(json.dumps({"t": time.time(), "changed": changed}) + "\n")
    out.write(json.dumps({"grabs": grabs}) + "\n")


if __name__ == "__main__":
    main()
