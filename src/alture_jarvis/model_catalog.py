"""첫 실행에서 보여 줄 **모델 목록** — 숫자는 전부 이 PC 에서 잰 것이다.

## 왜 따로 있나 (2026-09-13, 전략안 §43)

공개 제품이 되려면 사용자가 모델을 고를 수 있어야 하는데, 지금은 사용자가나
Claude 가 `.env` 에 태그를 손으로 적는다. 갤러리(헤비 유저)와 추천(아닌 사람)이
**같은 목록**을 봐야 둘이 갈리지 않는다 — 그래서 여기 한 곳에 둔다.

## 숫자를 어디서 가져왔나

지어낸 값이 하나도 없어야 한다. 모르는 칸은 `None` 이고, 화면은 그걸 「안 쟀다」로
보여 준다. 사양표로 추천하면 안 된다는 것이 이 저장소가 여러 번 배운 것이다
(윈도우 업데이트가 드라이버를 떨어뜨림 · 부팅 직후 Vulkan 을 잡음 · 태그가 갈리면
서로 GPU 에서 쫓아냄 — 전부 사양표로는 안 보였다).

    download_gb   Ollama /api/tags 가 이 PC 에서 보고한 크기 (2026-09-13)
    vram_gb       이 PC 3090 에서 모델을 올린 뒤 잰 값, 컨텍스트별 (2026-09-09~11)
    chain         사슬 벤치 — 조사해서 파일까지 만든 판 / 전체 판 (131K 에서만 쟀다)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


#: 조건 없이 쓸 수 있다고 널리 알려진 라이선스. 이 밖이면 화면이 「사용 조건 있음」과 원문 링크를 보여 준다.
#:
#: ★ 2026-10-08 대표·Claude(전략안 §55-24 덧붙임 2): 조건의 **내용을 우리 말로 풀어 쓰지 않는다** — 요약이 틀리면 우리 책임이
#:   되고, 제작사가 조건을 바꾸면 화면이 거짓이 된다. 「조건이 있다」는 사실과 원문 주소만 준다. 매출을 묻지도 막지도 않는다.
OPEN_LICENSES = frozenset({
    "apache 2.0", "apache-2.0", "apache2.0", "mit", "bsd-2-clause", "bsd-3-clause", "bsd 3-clause", "isc", "cc0-1.0", "unlicense",
})


def is_open_license(name: str) -> bool:
    return " ".join(str(name or "").lower().split()) in OPEN_LICENSES


@dataclass(frozen=True)
class CatalogModel:
    key: str
    name: str
    vendor: str
    ollama_tag: str
    download_gb: float
    #: 컨텍스트(토큰) → 올렸을 때 VRAM(GB). 잰 것만 넣는다.
    vram_gb: dict[int, float]
    #: 사슬 벤치 성적 `(성공, 전체)`. 잰 컨텍스트에서만.
    chain: tuple[int, int] | None
    chain_ctx: int | None
    roles: tuple[str, ...]
    blurb: str
    #: 화면 읽기(비전)까지 한 모델로 되는가.
    vision: bool = False
    #: 실측 출처(벤치 결과 파일). 사람이 따라가 확인할 수 있게.
    sources: tuple[str, ...] = field(default_factory=tuple)
    #: `verified` = 온텔릭이 직접 잰 모델 · `external` = 안 쟀지만 외부 근거가 좋은 모델(화면에 반드시 「미검증」).
    status: str = "verified"
    license: str = ""
    #: 외부 추천 근거(한 줄씩). 커뮤니티 평은 「평:」으로 시작한다.
    evidence: tuple[str, ...] = field(default_factory=tuple)
    #: 알려진 주의점 한 줄 — 없으면 빈 칸.
    caution: str = ""
    #: `(이름, 주소)` — 사람이 따라가 확인할 수 있게.
    links: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    checked_at: str = ""
    #: 메모리 실측 카드와 추천 최소 등급. 3090 숫자를 노트북에 그대로 대입하지 않는다.
    memory_device: str = ""
    minimum_vram_gb: float = 0.0
    #: 잘하는 일 / 약한 일 한 줄 — **잰 근거가 있는 것만**(§55-13 기대 맞추기, 2026-10-01 밤). 안 쟀으면 비운다.
    good_at: str = ""
    weak_at: str = ""
    #: 제작사 주장 · 참고용(2026-10-02 대표) — 공식 모델 카드의 「큰 모델 ○○ 와 같은 시험에서 비슷한 점수」 한 줄. **우리가 잰 숫자가 아니다** —
    #: 화면이 그렇게 적는다. 카드 원문에서만 옮기고 출처·확인 날짜를 붙인다. 원문에 큰 모델과의 비교가 없으면 비운다(지어내지 않는다).
    vendor_claim: str = ""
    vendor_claim_links: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    vendor_claim_checked: str = ""
    #: 라이선스 원문 주소 — 조건이 붙은 라이선스면 화면이 이 링크를 건다.
    license_url: str = ""
    #: 같은 모델의 **다른 크기(양자화)**끼리 같은 값. 화면이 카드 하나로 합쳐 「크기 고르기」 줄을 그린다. 단독이면 빈 글.
    family: str = ""
    family_name: str = ""
    #: 양자화 코드(`IQ3_S`)와 쉬운 말(「3비트」).
    quant: str = ""
    quant_label: str = ""
    #: 그림 읽는 부속(mmproj)이 저장소에 없는 모델에 **따로 받아 붙일** 부속의 태그. 맞는 부속은 모델마다 다르다 —
    #: 규칙이 아니라 이 목록이 아는 사실이다. 비어 있으면 아무것도 안 붙인다.
    projector_tag: str = ""
    #: 그림 부속을 뗀 채(「글만 읽기」) 올렸을 때의 메모리 — 창(토큰) → GB. **잰 것만.** 안 쟀으면 화면과 추천은
    #: `vram_gb − TEXT_ONLY_SAVES_GB` 로 어림한다(`text_only_need`).
    text_only_vram_gb: dict[int, float] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "vendor": self.vendor,
            "ollama_tag": self.ollama_tag,
            "download_gb": self.download_gb,
            "vram_gb": {str(ctx): gb for ctx, gb in sorted(self.vram_gb.items())},
            "chain": (
                {"ok": self.chain[0], "total": self.chain[1], "ctx": self.chain_ctx}
                if self.chain else None
            ),
            "roles": list(self.roles),
            "vision": self.vision,
            "blurb": self.blurb,
            "sources": list(self.sources),
            "status": self.status,
            "license": self.license,
            "evidence": list(self.evidence),
            "caution": self.caution,
            "links": [{"label": label, "url": url} for label, url in self.links],
            "checked_at": self.checked_at,
            # 외부 모델의 메모리는 받은 크기에서 **추정**한 값이다 — 화면이 「추정」이라고 적는다.
            "vram_measured": self.status == "verified",
            "agent_grade": agent_grade(self.ollama_tag),
            "memory_device": self.memory_device,
            "minimum_vram_gb": self.minimum_vram_gb,
            "good_at": self.good_at,
            "weak_at": self.weak_at,
            "vendor_claim": self.vendor_claim,
            "vendor_claim_links": [{"label": label, "url": url} for label, url in self.vendor_claim_links],
            "vendor_claim_checked": self.vendor_claim_checked,
            "license_open": is_open_license(self.license),
            "license_url": self.license_url,
            "family": self.family,
            "family_name": self.family_name,
            "quant": self.quant,
            "quant_label": self.quant_label,
            # 그림 읽기를 켜고 끌 수 있는 모델인가 — 그림 부속을 따로 붙이는 모델만(뗀 이름을 이 PC 에서 만들 수 있다).
            "pictures_optional": bool(self.projector_tag),
            "text_only_tag": TEXT_ONLY_PREFIX + self.key if self.projector_tag else "",
            "text_only_saves_gb": TEXT_ONLY_SAVES_GB if self.projector_tag else 0.0,
            "text_only_vram_gb": {str(ctx): gb for ctx, gb in sorted(self.text_only_vram_gb.items())},
        }


CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel(
        key="gemma4-26b-qat",
        name="Gemma 4 26B (QAT)",
        vendor="Google",
        ollama_tag="gemma4:26b-a4b-it-qat",
        download_gb=14.56,
        vram_gb={131072: 15.5},
        chain=(8, 10),
        chain_ctx=131072,
        roles=("chat", "vision"),
        vision=True,
        blurb="화면 읽기까지 한 모델로 됩니다. 그래픽카드 24GB 급에 맞습니다.",
        good_at="웹에서 찾아 문서로 정리하기(8/10) · 화면 읽기",
        sources=("git d375897c — 같은 밤 같은 10과제로 26B·9B 대조",),
        license="Apache 2.0",
        memory_device="RTX 3090 24GB",
    ),
    CatalogModel(
        key="qwen3.5-9b",
        name="Qwen 3.5 9B",
        vendor="Alibaba",
        ollama_tag="qwen3.5:9b",
        download_gb=6.14,
        vram_gb={131072: 8.9, 65536: 6.79, 32768: 6.15, 16384: 5.76},
        chain=(9, 10),
        chain_ctx=131072,
        roles=("chat",),
        blurb="문서 만들기에서 26B 와 동급으로 쟀습니다. 12GB 이상을 권하며 적용 때 이 PC에서 다시 잽니다.",
        good_at="웹에서 찾아 문서로 정리하기(9/10) · 브라우저 일",
        weak_at="처음 보는 코드 고치기 — 베타 실사용에서 망가뜨림(2026-10-01, 1판)",
        sources=("bench/browser_agents/results/multiturn_9b_2026-09-11.json", "git d375897c"),
        license="Apache 2.0",
        memory_device="RTX 3090 24GB", minimum_vram_gb=12.0,
    ),
    CatalogModel(
        key="qwen3.6-35b-a3b",
        name="Qwen 3.6 35B-A3B",
        vendor="Alibaba",
        ollama_tag="qwen3.6:35b-a3b",
        download_gb=23.0,
        # ★ 2026-09-20 이 PC 실측(3090 한 장, 다른 모델 내린 뒤): 128K 에서 21.3GB · 카드 안 92.5% ·
        #   생성 95.5토큰/초 · 5만1천 토큰 읽기 27.5초(1,869토큰/초) · 적재 13초. 도구 호출도 정확했다.
        #   두 장(3090+3060)에 나누면 100% 카드 안이지만, 모니터가 붙은 카드와 부딪혀 오히려 느렸다.
        vram_gb={131072: 21.3},
        # ★ 2026-09-20 실측: 사슬 벤치 10/10 (중앙 126초, 창작 0).
        #   같은 날 오전에 6/10 이 나왔는데 그건 모델이 아니라 **자리 다툼**이었다 —
        #   워치독이 젬마를 24시간 임대로 붙들어 3.6 이 한 번도 상주하지 못했고, 4판은
        #   시작조차 못 했다. 그걸 고치고 다시 재니 10/10 이다.
        chain=(10, 10),
        chain_ctx=131072,
        roles=("chat", "vision"),
        vision=True,
        blurb="MoE 라 35B 인데도 한 번에 3B 만 계산합니다. 128K 로 3090 한 장에 들어가는 것을 이 PC 에서 쟀습니다.",
        good_at="웹에서 찾아 문서로 정리하기(10/10)",
        sources=("https://ollama.com/library/qwen3.6/tags", "2026-09-20 이 PC 실측",
                 "bench/browser_agents/results/multiturn_qwen36_35ba3b_128k_20260920_after.json"),
        status="verified",
        license="Apache 2.0",
        memory_device="RTX 3090 24GB", minimum_vram_gb=22.0,
    ),
    # ── Qwen 3.8 27B 압축판 둘 (2026-10-08 이 PC 실측) ──────────────────────────────────────────────────────
    # 메모리는 **nvidia-smi 의 실제 사용량**이다(그림 부속을 붙인 상태 · MTP 켬). Ollama `/api/ps` 는 같은 모델을 128K 에서
    # 12.3GB 라고 보고한다 — 긴 창이 쓰는 몫이 빠진 값이라 쓰지 않았다(실제 18.9GB).
    # 코드 과제 = Aider 폴리글랏의 파이썬 과제 12개 · 창 64K · 판당 상한 600초 · 과제마다 한 판(`bench/coding/results_polyglot_1008/`).
    # 16GB 카드에서는 돌려 본 적이 없다 — 32K 창에서도 13.5~14.8GB 라 빠듯하다. 그래서 24GB 급에만 권한다(`minimum_vram_gb`).
    CatalogModel(
        key="qwen3.8-27b-swift",
        name="Swift 1.5 · Qwen 3.8 27B (3비트)",
        vendor="UkisAI",
        ollama_tag="hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf",
        download_gb=13.05,
        vram_gb={131072: 18.9, 65536: 16.1, 32768: 14.8},
        chain=None,
        chain_ctx=None,
        roles=("chat", "vision"),
        vision=True,
        blurb="Qwen 3.8 27B 를 손본 판입니다. 그래픽카드 24GB 급에서 128K 창까지 다 올라가는 것을 이 PC 에서 쟀습니다.",
        good_at="코드 과제 12개 중 12개(창 64K · 과제마다 한 판) · 웹 조사 두 판에서 답의 값 53개 중 52개가 읽은 글과 일치",
        sources=("bench/coding/results_polyglot_1008/swift_gsq_mtp_iq3s_64k.json",
                 "docs/고칠것_전체목록_2026-10-03.ko.md X-17 덧붙임 1~4"),
        status="verified",
        license="Swift Open License v1.0",
        license_url="https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF/blob/main/LICENSE",
        links=(("모델 카드", "https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF"),),
        checked_at="2026-10-08",
        memory_device="RTX 3090 24GB", minimum_vram_gb=22.0,
        family="swift-27b", family_name="Swift 1.5 · Qwen 3.8 27B", quant="IQ3_S", quant_label="3비트",
        # 이 저장소에는 그림 부속이 없다. 같은 제작사의 일반 양자화 저장소에 든 것을 따로 받아 붙인다(0.93GB · 2026-10-08 붙여서 그림 3/3 확인).
        projector_tag="hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GGUF:mmproj-Swift-1.5-Qwen3.8-27B-F16.gguf",
    ),
    # 같은 모델의 둘째 크기(2026-10-08 오후 실측). 같은 과제 12개를 다 통과했지만 걸음이 85 → 116, 시간 합이 1,856 → 2,459초,
    # 실패 걸음이 0 → 4 다(과제마다 한 판). 메모리는 그림 부속을 붙이고 nvidia-smi 로 쟀다 — 큰 크기보다 1.3~1.6GB 적다.
    # (10-08 에는 「추천 사다리에 넣지 않는다 — 16GB 카드에서 돌려 본 적이 없다」였다.)
    # ★ 2026-10-10 대표 결정: **16GB 급의 첫 추천으로 올린다.** 「저 정도는 괜찮다 · 사용자는 실제 체급을 더 좋아한다 · 대안은 카드로
    #   띄워 주면 된다」. 그날 이 설정(창 49,152 · 14.2GB)으로 조사 일 셋을 맡겨 원문과 칸마다 대조했다(각 1판): 사람인 15/15칸 ·
    #   다나와 12/12칸 · 교보 12/15칸 — 책 한 권의 쪽수·출간일이 다른 책 값이었고 숫자 문은 못 잡았다. 같은 교보 일을 운영 설정
    #   (IQ3_S · 128K)으로는 15/15칸. 9B 는 같은 날 같은 일로 안 쟀다. 잰 것은 아래 good_at · weak_at 에 그대로 적는다.
    #   **실제 16GB 카드에서는 아직 돌려 본 적이 없다** — 메모리는 3090 에 올려 잰 값이다. 안 들어가면 적용 단계가 창을 줄여 다시 재고,
    #   그래도 안 되면 화면이 닫을 프로그램과 9B 를 보여 준다(`model_setup.way_out`).
    #   `chain` 은 비워 둔다 — 그 칸은 정해진 사슬 벤치(10판)의 것이고 권한 판정이 같이 본다. 세 판을 거기 넣지 않는다.
    CatalogModel(
        key="qwen3.8-27b-swift-iq3xxs",
        name="Swift 1.5 · Qwen 3.8 27B (3비트 작게)",
        vendor="UkisAI",
        ollama_tag="hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf",
        download_gb=11.37,
        vram_gb={131072: 17.3, 65536: 14.6, 49152: 14.2, 32768: 13.5},
        chain=None,
        chain_ctx=None,
        roles=("chat", "vision"),
        vision=True,
        blurb="같은 모델을 더 작게 눌러 담은 크기입니다. 받는 크기와 메모리가 조금 줄어듭니다.",
        good_at="코드 과제 12개 중 12개(창 64K · 과제마다 한 판) · 조사 일 세 판 중 두 판은 모든 칸이 맞았습니다(창 48K)",
        weak_at=("조사 일 한 판에서 책 한 권의 쪽수와 출간일을 다른 책의 값으로 적었습니다(창 48K · 세 판 중 한 판) · "
                 "같은 코드 과제에서 3비트 크기보다 걸음이 많고(116 대 85) 시간이 1.3배 들었습니다"),
        sources=("bench/coding/results_polyglot_1008/swift_gsq_mtp_iq3xxs_64k.json",),
        status="verified",
        license="Swift Open License v1.0",
        license_url="https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF/blob/main/LICENSE",
        links=(("모델 카드", "https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF"),),
        checked_at="2026-10-08",
        memory_device="RTX 3090 24GB", minimum_vram_gb=16.0,
        family="swift-27b", family_name="Swift 1.5 · Qwen 3.8 27B", quant="IQ3_XXS", quant_label="3비트 작게",
        projector_tag="hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GGUF:mmproj-Swift-1.5-Qwen3.8-27B-F16.gguf",
        # 2026-10-12 RTX 3090 · nvidia-smi: 그림 부속 없이 48K 13,080MB · 64K 13,754MB (그림 있는 48K 는 14,216MB).
        # 같은 날 가격 조사 세 과제(각 1판 · 온전한 줄 /9): 글만 읽기 64K 8 · 48K 5 — 16GB 급에서 갈린 것은 창이었다(전수조사 §7-36).
        text_only_vram_gb={65536: 13.8, 49152: 13.1},
    ),
    # ★ 2026-10-26 대표 결정: 「16GB 기본은 Swift 27B(3비트 작게), 안 들어가면 Qwen3.6 2비트」. 16GB 카드에 다른 프로그램(3ds Max 등)이
    #   그래픽 메모리를 쥐어 Swift 의 글만 읽기 64K(13.8GB)가 안 들어갈 때의 다음 칸이다(9B 보다 위).
    #   2026-10-23 밤 이 PC(3090) 실측 · 글만 읽기 · 창 64K · 과제마다 한 판: 바깥 코드 과제 10/12(가운데 131초 · 9B 5/12) ·
    #   한국어 3/3(한 판에 한자 한 낱말) · 가격 조사 2/3 · 2/3(놓친 곳은 둘 다 봇 검사에 막힌 G마켓) · 그래픽 메모리 12.4GB ·
    #   모델 몫 12GB 로 흉내 냈을 때 88% 가 카드에 올라가고 초당 116토큰(9B 94~95). 기록 `D:\bench_tmp\sixteen_gb_1023\`.
    #   MoE 라 넘치는 몫이 CPU 로 가도 덜 느려진다. 그림 있는 값은 재지 않았다 — 아래 vram_gb 는 글만 읽기 값 + 부속 약 0.9GB 어림.
    CatalogModel(
        key="qwen3.6-35b-iq2m",
        name="Qwen 3.6 35B-A3B (2비트)",
        vendor="Alibaba · Unsloth 압축",
        ollama_tag="hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ2_M",
        download_gb=12.0,
        vram_gb={65536: 13.3},
        chain=None,
        chain_ctx=None,
        roles=("chat",),
        vision=True,
        blurb="35B 를 2비트로 눌러 담았습니다. 16GB 카드를 다른 프로그램과 나눠 쓸 때 9B 대신 올라가는 모델입니다.",
        good_at="코드 과제 12개 중 10개(창 64K · 과제마다 한 판 · 9B 는 5개) · 한국어 3/3 · 9B 보다 빠름(초당 116 대 94토큰)",
        weak_at="2비트라 Swift 27B 보다 코드 과제 두 개를 더 놓쳤습니다(10 대 12) · 글만 읽기로 쓰면 그림을 읽지 못합니다",
        sources=("D:/bench_tmp/sixteen_gb_1023 (code · korean · price · speed runs.jsonl · 2026-10-23 밤)",),
        status="verified",
        license="Apache 2.0",
        links=(("Hugging Face", "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF"),),
        checked_at="2026-10-23",
        memory_device="RTX 3090 24GB", minimum_vram_gb=14.0,
        family="qwen3.6-35b", family_name="Qwen 3.6 35B-A3B", quant="UD-IQ2_M", quant_label="2비트",
        # 그림 부속은 받을 때 따로 붙어 온다 — `projector_tag` 는 비운다(9B 3비트와 같은 길 · `eyes_of`).
        text_only_vram_gb={65536: 12.4},
    ),
    CatalogModel(
        key="qwen3.8-27b-gsq",
        name="Qwen 3.8 27B (압축 3비트)",
        vendor="Alibaba · ISTA-DASLab 압축",
        ollama_tag="hf.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf",
        download_gb=13.05,
        vram_gb={131072: 18.9, 65536: 16.1, 32768: 14.8},
        chain=None,
        chain_ctx=None,
        roles=("chat", "vision"),
        vision=True,
        blurb="Qwen 3.8 27B 를 3비트로 눌러 담은 판입니다. 화면 읽기까지 한 모델로 됩니다.",
        good_at="코드 과제 12개 중 11개(창 64K · 과제마다 한 판)",
        weak_at="같은 과제에서 두 판이 600초 상한에 걸렸습니다(한 판은 답을 맞히고도 못 끝냄)",
        sources=("bench/coding/results_polyglot_1008/gsq_mtp_iq3s_64k.json",),
        status="verified",
        license="Apache 2.0",
        links=(("모델 카드", "https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF"),),
        checked_at="2026-10-08",
        memory_device="RTX 3090 24GB", minimum_vram_gb=22.0,
    ),
    # ── 외부 추천 (온텔릭 미검증) — docs/모델_큐레이션_2026-09-15.ko.md ─────────────────
    # vram_gb 는 **추정**이다: Ollama 가 보고한 받는 크기 + 컨텍스트 32K 몫 1GB. 잰 값이 아니라서
    # 32K 한 칸만 두고, 화면은 「추정」이라고 적는다. 우리가 재면 status 를 verified 로 올리고 실측으로 바꾼다.
    # ★ 2026-10-14 대표 결정: 8GB 급의 첫 추천은 이 9B 3비트의 **글만 읽기**(「느려도 그게 맞다」).
    #   가격 조사 과제 7판(판마다 9칸 · 온전한 줄): 부산 노트북(RTX 5050 Laptop 8GB · 창 48K · 카드에 100%) 7 8 4 5 5 4 4 = 37/63,
    #   이 PC(3090 · 같은 조합) 5 4 6 4 6 4 8 = 37/63 — 같은 노트북의 공식 4B(4비트 · 창 78K) 3 3 4 4 3 3 4 = 24/63,
    #   이 PC 의 공식 9B(그림 있음 · 48K) 19/63 보다 높다. 왜 공식 9B 보다 높은지는 아직 못 갈랐다(그림 부속 · 파일의 말하는 틀 · 양자화).
    #   내주는 것: 과제 하나 가운데 447초(4B 278초) · 그림을 읽지 못한다. 창 64K 는 카드에 88% 만 올라가 34/63 · 520초 — 넘치면 손해다.
    #   메모리(부산 노트북 · Ollama 0.34.3 · 바깥 모니터가 꺼진 밤 · 카드에 다른 것 0.8GB): 그림 있음 32K 6.28 · 48K 7.02 · 64K 7.65GB
    #   (전부 다 안 올라감 — 88% · 78% · 73%) / 글만 읽기 32K 5.48 · 48K 6.03 · 64K 7.14GB. 낮에 모니터를 켜면 카드 자리가 줄어든다 —
    #   다 올라가는지는 적용 단계가 실제로 올려 보고, 안 되면 다음 칸(32K → 4B)으로 내려간다.
    CatalogModel(
        key="qwen3.5-9b-q3",
        name="Qwen 3.5 9B (3비트)",
        vendor="Alibaba · Unsloth 압축",
        ollama_tag="hf.co/unsloth/Qwen3.5-9B-GGUF:Q3_K_M",
        download_gb=5.6,
        vram_gb={65536: 7.65, 49152: 7.02, 32768: 6.28},
        chain=None,
        chain_ctx=None,
        roles=("chat",),
        vision=True,
        blurb="8GB 카드에서 그림 읽기를 끄면 창 48K 로 전부 올라갑니다. 4B 보다 느리지만 조사 일을 더 많이 해냈습니다.",
        good_at="웹에서 찾아 표로 정리하기 — 가격 조사 7판에서 온전한 줄 37/63(8GB 노트북 · 창 48K · 글만 읽기), 같은 노트북의 4B 는 24/63",
        weak_at="4B 보다 느립니다(과제 하나 가운데 447초 대 278초) · 글만 읽기로 쓰면 그림을 읽지 못합니다",
        sources=("부산 노트북 measure_kit 결과 run_9b_q3_text_48k(2026-10-14 03:38) · 9b_q3_text_64k_spill(07:12)",
                 "이 PC measure_kit 결과 night_1014/9b_unsloth_q3_text_48k(2026-10-14 06:42)"),
        status="verified",
        license="Apache 2.0",
        links=(("Hugging Face", "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF"),),
        checked_at="2026-10-14",
        memory_device="RTX 5050 Laptop 8GB", minimum_vram_gb=8.0,
        family="qwen3.5-9b", family_name="Qwen 3.5 9B", quant="Q3_K_M", quant_label="3비트",
        # 그림 부속은 받을 때 따로 붙어 온다(파일 둘) — 우리가 붙이지 않으니 `projector_tag` 는 비운다. 떼는 길은 `eyes_of`.
        text_only_vram_gb={65536: 7.14, 49152: 6.03, 32768: 5.48},
    ),
    # ★ 2026-10-14 밤 대표 결정(「6GB 마법사 4B 3비트로」): 6GB 급의 첫 추천은 이 4B 3비트의 **글만 읽기 · 창 48K**, 안 들어가면 32K.
    #   6GB 노트북(RTX 3050 Laptop 6GB · Ollama 0.35.0 · 바깥 모니터를 이 카드가 그림): 글만 읽기 32K 3,483MiB · 48K 4,011MiB —
    #   둘 다 카드에 전부(초당 약 40~46토큰). 그림 있는 공식 4B(4비트) 32K 는 34층 중 30층만 올라가(78.8%) 마법사가 **2B 로 내려갔고**,
    #   그 2B 는 가격 조사 첫 네 과제가 전부 0 이었다. 이 4B 3비트 48K 는 10/63(7판 · 메모리가 새던 고치기 전 판 · 실행기 2번 꺼짐) —
    #   약하지만 0 이 아니다. 고친 판으로 같은 조건을 다시 재는 중이다(10-14 밤).
    #   메모리 값은 MiB 를 GB(10억)로 옮겨 적었다(넉넉한 쪽). 그림 있는 칸은 **안 쟀다** — 글만 읽기 + 그림 부속 0.67GB 로 어림한 값이다.
    CatalogModel(
        key="qwen3.5-4b-q3",
        name="Qwen 3.5 4B (3비트)",
        vendor="Alibaba · Unsloth 압축",
        ollama_tag="hf.co/unsloth/Qwen3.5-4B-GGUF:UD-Q3_K_XL",
        download_gb=3.1,
        vram_gb={49152: 4.9, 32768: 4.3},
        chain=None,
        chain_ctx=None,
        roles=("chat",),
        vision=True,
        blurb="6GB 카드에서 그림 읽기를 끄면 창 48K 로 전부 올라갑니다. 2B 로 내려가는 것보다 조사 일을 해냅니다.",
        good_at="6GB 노트북에서 카드에 전부 올라가는 가장 큰 조합 — 가격 조사 7판 10/63(같은 노트북의 2B 는 첫 네 과제 0)",
        weak_at="큰 모델보다 많이 틀립니다(같은 과제 8GB 의 9B 3비트 37/63) · 글만 읽기로 쓰면 그림을 읽지 못합니다",
        sources=("6GB 노트북 measure_kit 결과 4b_q3_text_48k(2026-10-14 02:09)",),
        status="verified",
        license="Apache 2.0",
        links=(("Hugging Face", "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF"),),
        checked_at="2026-10-14",
        memory_device="RTX 3050 Laptop 6GB", minimum_vram_gb=6.0,
        family="qwen3.5-4b", family_name="Qwen 3.5 4B", quant="UD-Q3_K_XL", quant_label="3비트",
        text_only_vram_gb={49152: 4.21, 32768: 3.65},
    ),
    CatalogModel(
        key="qwen3.5-4b", name="Qwen 3.5 4B", vendor="Alibaba", ollama_tag="qwen3.5:4b",
        # ★ 2026-10-12 밤 큰 창 칸을 열었다 — 창을 키워도 가벼운 모델이라 8GB · 6GB 카드에서 재 볼 수 있게.
        #   3090 에서 잰 값: 32K 3.80 · 48K 4.39 · 64K 4.81GB. 32K 칸의 4.2 는 8GB 노트북에서 잰 것이라(같은 창인데 0.4GB 더)
        #   새 칸도 그만큼 얹어 적는다. 추천 사다리는 안 바꿨다(32K 한 칸 그대로) — 같은 날 가격 조사 세 과제의 온전한 줄이
        #   48K 7/9(1판) · 64K 3 · 4(2판) · 32K 7 · 4 · 5 · 3 · 2 · 3 이라 창을 키운다고 낫다고 말할 근거가 없다.
        download_gb=3.4, vram_gb={32768: 4.2, 49152: 4.8, 65536: 5.2}, chain=None, chain_ctx=None, roles=("chat",), vision=True,
        blurb="노트북 RTX 5050 8GB에서 32K·100% GPU·60.4 tok/s를 확인했습니다. 일 성공률은 아직 안 쟀습니다.",
        status="verified", license="Apache 2.0", memory_device="RTX 5050 Laptop 8GB",
        sources=("docs/인수인계_2026-09-19_새벽.ko.md §4 — 노트북 /api/ps 4,197,596,527 bytes",),
        evidence=("Hugging Face 최근 30일 다운로드 약 696만 · 좋아요 924",
                  "Ollama 공식: 도구 호출 · 이미지 · 생각 모드"),
        caution="평: Hugging Face 토론에 빈 생각 블록 템플릿 수정 제안(#14)",
        links=(("Ollama", "https://ollama.com/library/qwen3.5"), ("Hugging Face", "https://huggingface.co/Qwen/Qwen3.5-4B")),
        checked_at="2026-09-15",
    ),
    CatalogModel(
        key="qwen3.5-2b", name="Qwen 3.5 2B", vendor="Alibaba", ollama_tag="qwen3.5:2b",
        download_gb=2.7, vram_gb={32768: 3.7}, chain=None, chain_ctx=None, roles=("chat",), vision=True,
        blurb="4B도 그래픽카드에 전부 안 올라갈 때 32K를 유지하며 실제로 재볼 후보입니다.",
        status="external", license="Apache 2.0",
        evidence=("Qwen 3.5 작은 모델 사다리 — 적용 시 토큰 생성과 GPU 적재 비율을 검증",),
        caution="메모리는 추정이며 한국어 작업 성공률은 아직 안 쟀습니다.",
        links=(("Ollama", "https://ollama.com/library/qwen3.5:2b"),),
    ),
    CatalogModel(
        key="granite4.1-8b", name="Granite 4.1 8B", vendor="IBM", ollama_tag="granite4.1:8b",
        download_gb=5.3, vram_gb={32768: 6.3}, chain=None, chain_ctx=None, roles=("chat",),
        blurb="지원 언어에 한국어, 기능에 함수 호출을 공식으로 적은 가벼운 모델입니다.",
        status="external", license="Apache 2.0",
        evidence=("IBM 공식 문서: 지원 언어에 한국어 · 함수 호출 명시", "Hugging Face 최근 30일 다운로드 약 21만"),
        caution="이미지는 못 읽습니다",
        links=(("Ollama", "https://ollama.com/library/granite4.1"), ("Hugging Face", "https://huggingface.co/ibm-granite/granite-4.1-8b")),
        checked_at="2026-09-15",
    ),
    CatalogModel(
        key="gemma4-e4b-qat", name="Gemma 4 E4B (QAT)", vendor="Google", ollama_tag="gemma4:e4b-it-qat",
        download_gb=6.1, vram_gb={32768: 7.1}, chain=None, chain_ctx=None, roles=("chat", "vision"), vision=True,
        blurb="작은 카드에서 이미지·오디오까지 되는 구글 모델입니다.",
        status="external", license="Apache 2.0",
        evidence=("Hugging Face 최근 30일 다운로드 약 462만 · 좋아요 1,559", "구글 공식 QAT 버전"),
        caution="평: 여러 턴 도구 사용에서 이전 추론이 다시 들어가 반복한다는 제보(HF 토론 #37)",
        links=(("Ollama", "https://ollama.com/library/gemma4"), ("Hugging Face", "https://huggingface.co/google/gemma-4-E4B-it")),
        checked_at="2026-09-15",
    ),
    CatalogModel(
        key="gemma4-12b-qat", name="Gemma 4 12B (QAT)", vendor="Google", ollama_tag="gemma4:12b-it-qat",
        download_gb=7.2, vram_gb={32768: 8.2}, chain=None, chain_ctx=None, roles=("chat", "vision"), vision=True,
        blurb="12B 급에서 네이티브 함수 호출과 긴 컨텍스트를 가진 구글 모델입니다.",
        status="external", license="Apache 2.0",
        evidence=("Hugging Face 최근 30일 다운로드 약 296만 · 좋아요 1,560", "구글 공식 QAT GGUF 약 78만 다운로드"),
        caution="평: 긴 에이전트 프롬프트에서 생각 반복 제보(HF 토론 #38·#41) — Sonjari의 누출 방지로 막히는지 재는 중",
        links=(("Ollama", "https://ollama.com/library/gemma4"), ("Hugging Face", "https://huggingface.co/google/gemma-4-12B-it")),
        checked_at="2026-09-15",
    ),
    CatalogModel(
        key="gemma4-31b-qat", name="Gemma 4 31B (QAT)", vendor="Google", ollama_tag="gemma4:31b-it-qat",
        download_gb=19.0, vram_gb={32768: 20.0}, chain=None, chain_ctx=None, roles=("chat", "vision"), vision=True,
        blurb="26B(MoE)보다 느리지만 품질을 우선한 구글 모델입니다.",
        status="external", license="Apache 2.0",
        evidence=("Hugging Face 좋아요 3,829 — Gemma 4 가운데 가장 많음", "최근 30일 다운로드 약 882만"),
        caution="우리 26B 와 같은 과제로 비교한 적 없음",
        links=(("Ollama", "https://ollama.com/library/gemma4"), ("Hugging Face", "https://huggingface.co/google/gemma-4-31B-it")),
        checked_at="2026-09-15",
    ),
    # ★ 2026-10-01 밤 대표: 「Ornith 1.5 가 그렇게 좋다는데」. 자기 보고 벤치가 같은 체급 Qwen 을 크게 앞선다 — 우리 과제로는 아직
    #   안 쟀으니 외부 평가 칸에만 둔다(16GB 측정 10-02 아침에 9B·35B 2비트, 3090 에서 35B IQ4_XS 를 잰 뒤 올린다).
    #   크기는 bartowski GGUF 파일 + 화면 읽기 부속(0.9GB) 실측, 32K 메모리는 그보다 1GB 많게 잡은 추정.
    CatalogModel(
        key="ornith1.5-9b", name="Ornith 1.5 9B", vendor="Ornith", ollama_tag="hf.co/bartowski/Ornith-1.5-9B-GGUF:Q4_K_M",
        download_gb=6.8, vram_gb={32768: 7.8}, chain=None, chain_ctx=None, roles=("chat", "vision"), vision=True,
        blurb="Qwen 3.5 9B 구조를 강화학습으로 다시 키운 모델입니다. 같은 체급에서 코딩·조사 벤치가 크게 높다고 발표했습니다.",
        status="external", license="MIT",
        evidence=("제작사 발표(자기 보고): SWE-bench Verified 70.6 · BrowseComp 56.4 · MCP-Atlas 54.2 — Qwen 3.5 9B 는 53.2 · 41.5 · 46.8",
                  "Hugging Face 최근 30일 GGUF 다운로드 약 506만 · 좋아요 471"),
        caution="벤치는 전부 제작사가 잰 것입니다. 손자리 과제(한국 사이트 조사→문서)로는 아직 안 쟀습니다.",
        links=(("Hugging Face", "https://huggingface.co/ornith-ai/Ornith-1.5-9B"),
               ("GGUF", "https://huggingface.co/bartowski/Ornith-1.5-9B-GGUF")),
        checked_at="2026-10-01",
    ),
    CatalogModel(
        key="ornith1.5-35b-a3b", name="Ornith 1.5 35B-A3B", vendor="Ornith",
        ollama_tag="hf.co/bartowski/Ornith-1.5-35B-A3B-GGUF:IQ4_XS",
        # ★ 메모리는 2026-10-01 밤 이 PC(RTX 3090)에서 상한 재기로 **실측**(전부 100% GPU · 109~128 tok/s).
        #   처음엔 32K 한 칸만 추정으로 적어, 적용 장치가 128K 요청을 32K 로 깎았다(`apply_tag` 는 표의 가장 큰 칸까지만).
        download_gb=20.2,
        vram_gb={16384: 17.8, 32768: 18.0, 65536: 18.5, 131072: 19.3, 262144: 21.0},
        chain=None, chain_ctx=None, roles=("chat", "vision"), vision=True,
        blurb="MoE 라 35B 인데 한 번에 3B 만 계산합니다. 3090 에서 256K 까지 그래픽카드에 다 올라가는 것을 쟀습니다(117~128 tok/s).",
        status="external", license="MIT",
        evidence=("제작사 발표(자기 보고): SWE-bench Verified 79.0 · BrowseComp 67.6 · MCP-Atlas 70.2 — Qwen 3.6 35B 는 73.4 · 62.0 · 62.8",
                  "같은 표의 Claude Opus 4.8 대비 흔한 일 85~95% · 길고 어려운 일(DeepSWE·Frontier-Bench) 24~37%",
                  "Hugging Face 최근 30일 GGUF 다운로드 약 360만 · 좋아요 472"),
        caution="벤치는 전부 제작사가 잰 것입니다. 손자리 과제(조사→문서·코딩 사다리) 성적은 아직 안 쟀습니다 — 메모리만 쟀습니다.",
        memory_device="RTX 3090 24GB",
        links=(("Hugging Face", "https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B"),
               ("GGUF", "https://huggingface.co/bartowski/Ornith-1.5-35B-A3B-GGUF")),
        checked_at="2026-10-01",
    ),
)

#: 그래픽카드 메모리 등급(GB). 카드 전체 메모리로 고른다 — 「6GB 이하」「8GB 이하」….
TIERS: tuple[int, ...] = (6, 8, 12, 16, 24)

#: 등급마다 외부 추천 후보, 앞에서부터 들어가는 첫 모델을 고른다.
#: 검증 칸은 따로 두지 않는다 — 잰 모델 중 **실제로 들어가는 것**을 `setup_profile.recommend` 가 계산한다.
EXTERNAL_BY_TIER: dict[int, tuple[str, ...]] = {
    6: ("qwen3.5-4b",),
    8: ("gemma4-e4b-qat", "granite4.1-8b", "qwen3.5-4b"),
    12: ("gemma4-12b-qat", "gemma4-e4b-qat"),
    16: ("gemma4-12b-qat",),
    24: ("gemma4-31b-qat", "gemma4-12b-qat"),
}


def tier_for(vram_total_gb: float) -> int:
    """카드 전체 메모리 → 등급. 표기 오차(7.9·11.99GB 등)를 반 GB 까지 봐준다."""
    for tier in TIERS:
        if vram_total_gb <= tier + 0.5:
            return tier
    return TIERS[-1]


def by_key(key: str) -> CatalogModel | None:
    return next((model for model in CATALOG if model.key == key), None)


#: 같은 모델에서 **그림 부속만 뺀 이름**의 머리 (2026-10-12). 이 이름은 손자리가 이 PC 의 Ollama 에 만든다
#: (`SetupService.text_only_tag`) — 새로 받는 것 없이 이미 받은 모델 파일을 그대로 쓴다. 이름에 목록 키를 실어,
#: 이름만 보고 어느 모델인지 안다(능력 등급 · 「지금 쓰는 것」 표시가 원래 모델과 같은 칸을 본다).
#:
#: ★ 그날 잰 것(3090 에 올린 27B 「3비트 작게」 · nvidia-smi): 그림 있음 · 48K 14,216MB / 그림 없음 · 48K 13,080MB /
#:   그림 없음 · 64K 13,754MB. 부속을 떼면 1.1GB 쯤 비고, 그 자리에 창을 한 칸 넓혀도 원래보다 덜 쓴다.
TEXT_ONLY_PREFIX = "sonjari-text-"
#: 그림 부속을 떼면 덜 쓰는 그래픽카드 메모리(GB) — 위에 적은 그날의 잰 값(14,216 → 13,080MB). 화면이 「글만 읽기」를 골랐을 때
#: 창마다의 메모리에서 이만큼을 빼고 들어가는지 본다. 실제로 들어가는지는 적용할 때 올려 보고 잰다(`_measure_and_save`).
TEXT_ONLY_SAVES_GB = 1.1


def text_only_need(model: "CatalogModel", ctx: int) -> float | None:
    """「글만 읽기」로 이 창을 올리면 드는 메모리(GB). 잰 값이 있으면 그 값, 없으면 그림 있는 값에서 부속만큼 뺀다.
    그림 부속을 따로 붙이는 모델이 아니거나 그 창을 잰 적이 없으면 None."""
    # 잰 값이 있으면 그것이 먼저다 — 받을 때 부속이 따로 붙어 오는 모델(`projector_tag` 없음)도 잰 값으로 안다(2026-10-14).
    if ctx in model.text_only_vram_gb:
        return model.text_only_vram_gb[ctx]
    if not model.projector_tag:
        return None
    if ctx in model.vram_gb:
        return round(model.vram_gb[ctx] - TEXT_ONLY_SAVES_GB, 2)
    return None


def text_only_name(key: str) -> str:
    """목록 모델의 「글만 읽는」 이름. 그림 부속을 따로 붙이는 모델(`projector_tag`)에만 쓴다."""
    return TEXT_ONLY_PREFIX + str(key or "").strip()


def text_only_key(tag: str) -> str:
    """이 이름이 손자리가 만든 「글만 읽는」 이름이면 그 모델의 목록 키, 아니면 빈 글."""
    bare = str(tag or "").strip().lower().removesuffix(":latest")
    if not bare.startswith(TEXT_ONLY_PREFIX):
        return ""
    key = bare[len(TEXT_ONLY_PREFIX):]
    return key if by_key(key) is not None else ""


def is_text_only_name(tag: str) -> bool:
    """손자리가 만든 「글만 읽는」 이름인가 — 목록 모델의 것이든 목록 밖 모델의 것이든."""
    return str(tag or "").strip().lower().startswith(TEXT_ONLY_PREFIX)


def text_only_name_for_tag(tag: str) -> str:
    """목록 밖 모델(허깅페이스에서 고른 것 · 직접 받은 것)의 「글만 읽는」 이름 — 원래 이름에서 만든다.

    ★ 2026-10-13: 6GB 노트북에서 눈(그림 부속)을 단 4B 가 창 32K 로 다 못 올라갔다. Ollama 0.35 가 모델을 올릴 때
      「눈의 무게 + 1GiB」를 카드에 비워 두기 때문이다(`llm/llama_server.go` 의 `mmprojOffloadHeadroom`). 눈을 뺀 이름은
      그 여유가 1,024MiB 로 줄어, 같은 카드에 같은 모델이 창 48K 까지 전부 올라갔다. 그 길이 목록 모델에만 있었다.
    - 주인 이름을 싣는다 — 저장소 이름과 양자화가 같은 다른 사람의 파일과 한 이름을 두고 다투지 않게.
    - 이미 「글만 읽는」 이름이면 그대로 돌려준다.
    """
    bare = str(tag or "").strip().lower().removesuffix(":latest")
    if bare.startswith(TEXT_ONLY_PREFIX):
        return bare
    for head in ("hf.co/", "huggingface.co/"):
        bare = bare.removeprefix(head)
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9._]+", "-", bare)).strip("-.")
    # Ollama 이름은 81자까지 받는다(`model_setup.OLLAMA_TAG`) — 머리 13자를 빼고 남는 만큼만 싣는다.
    return TEXT_ONLY_PREFIX + slug[:64].rstrip("-.")


def by_tag(tag: str) -> CatalogModel | None:
    wanted = str(tag or "").strip().lower()
    found = next((model for model in CATALOG if model.ollama_tag.lower() == wanted), None)
    if found is None:
        key = text_only_key(wanted)
        found = by_key(key) if key else None
    return found


# ── 능력 등급 — 메모리 실측(`status`)과는 **다른 칸**이다 (2026-09-20) ──────────────
#
# 사장님 지시로 생겼다: "벤치에서 성능이 검증된 애들만 권한을 틀어 주는 게 어떤가.
# 4B 로 그렇게 해 버리면 진짜 큰일난다."
#
# ★ 맨 먼저 확인한 것: 화면의 「검증됨」은 **VRAM 을 쟀다**는 뜻이었다
#   (`public()["vram_measured"] = status == "verified"`). 4B 도 거기선 「검증됨」이다.
#   그 칸을 권한 기준으로 쓰면 **틀린 눈금으로 잠그는 것**이 된다. 그래서 능력은
#   `chain`(사슬 벤치 — 조사해서 파일까지 만든 판)으로만 판정한다. 지어내지 않는다.
#
# 지금 능력을 잰 모델은 둘뿐이다: Gemma 4 26B(8/10) · Qwen 3.5 9B(9/10).
# 나머지는 전부 「안 쟀음」이고, 그건 「나쁘다」가 아니라 **모른다**는 뜻이다.

#: 이 아래로 떨어지면 잰 것이라도 「약함」으로 본다. 8/10 을 살리는 자리 — 우리가 실제로
#: 위임해 본 판의 성적이 그 언저리다. 올릴 근거가 생기면 그때 올린다.
AGENT_PASS_RATE = 0.7


def agent_grade(tag: str) -> dict[str, Any]:
    """이 모델의 **능력 실측** 상태. 화면 문구와 권한 판정이 같은 곳을 본다.

    반환: `measured`(잰 적 있고 합격) · `chain`(성공/전체) · `label`(화면 한 줄) · `model`.
    """
    wanted = str(tag or "").strip()
    model = by_tag(wanted)
    if model is None or not model.chain:
        return {
            "model": wanted or "(모델 없음)",
            "measured": False,
            "chain": None,
            "rate": None,
            "label": "능력을 잰 적 없음",
            "detail": "Sonjari가 이 모델로 사슬 벤치를 돌린 적이 없습니다 — 나쁘다는 뜻이 아니라 모른다는 뜻입니다.",
        }
    ok, total = model.chain
    rate = ok / total if total else 0.0
    measured = rate >= AGENT_PASS_RATE
    return {
        "model": wanted,
        "measured": measured,
        "chain": {"ok": ok, "total": total, "ctx": model.chain_ctx},
        "rate": rate,
        "label": f"사슬 벤치 {ok}/{total} 실측" + ("" if measured else " · 합격선 미달"),
        "detail": (
            f"{model.name} — 조사해서 파일까지 만든 판 {ok}/{total}"
            + (f" (컨텍스트 {model.chain_ctx:,})" if model.chain_ctx else "")
        ),
    }
