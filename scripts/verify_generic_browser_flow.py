"""End-to-end proof that the generic path handles what took two days on Naver.

The fixture below is not Naver. It is a page built to reproduce, on a site
nothing here has ever seen, the same five causes that stacked up on 2026-08-03~05:

  1. the content lives inside an iframe          -> snapshot must reach into it
  2. a dialog appears *late*, after the page settled -> a pre-flight check cannot catch it
  3. the dialog sits in the TOP document, not the iframe -> searching one frame finds nothing
  4. the dialog's buttons are wrapped in a row that matches the same selector
                                                  -> clicking the wrapper hits empty space
  5. the save button's real proof is a counter    -> "clicked" is not "saved"

Nothing in the code being exercised knows anything about this page. If this
passes, the machinery is not Naver-shaped.

Run:  set PYTHONPATH=...\\src && python scripts\\verify_generic_browser_flow.py
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _scratch import scratch_root
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import SiteRecipeTools


# Phase 2 drives the *same* page from a JSON recipe instead of Python. Written
# here rather than shipped in `recipes/` so a test fixture never shows up in the
# assistant's real tool listing.
FIXTURE_RECIPE = {
    "name": "fixture_editor",
    "description": "E2E 픽스처 — 레시피가 실제 브라우저를 모는지 증명하는 용도",
    "hosts": ["127.0.0.1"],
    "urls": {"editor": "{base}/"},
    "targets": {
        "title": ["input[placeholder='제목']"],
        "body": ["textarea"],
        "save": [".save_btn"],
    },
    "actions": {
        "save_draft": {
            "risk": "L2",
            "steps": [
                {"do": "open", "url_key": "editor"},
                {"_why": "늦게 뜨는 대화상자를 기다렸다 치운다", "do": "wait", "ms": 1400},
                {"do": "dismiss", "rounds": 2},
                {"do": "fill", "target": "title", "value": "{title}"},
                {"do": "fill", "target": "body", "value": "{body}"},
                {
                    "do": "click",
                    "target": "save",
                    "expect": {"kind": "number_increases", "selector": ".save_btn"},
                    "verify_timeout_ms": 6000,
                },
            ],
        }
    },
}


OUTER = """<!doctype html><html lang=ko><head><meta charset=utf-8><title>가상 편집기</title>
<style>
 body{font:15px 'Malgun Gothic',sans-serif;margin:0}
 header{padding:10px 16px;border-bottom:1px solid #ddd;background:#fafafa}
 iframe{width:100%;height:420px;border:0}
 /* The late dialog: top document, dim layer, buttons inside a wrapper row that
    matches the same permissive selector the buttons do. */
 #dim{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;z-index:9999}
 #dlg{position:fixed;left:50%;top:44%;transform:translate(-50%,-50%);background:#fff;
      padding:22px 26px;border-radius:8px;min-width:320px;text-align:center}
 .btnrow{display:flex;gap:36px;justify-content:center;margin-top:18px}
 .btnrow button{padding:8px 22px}
</style></head>
<body>
<header><button>알림</button><button>내 문서</button></header>
<iframe name="workFrame" src="/inner"></iframe>
<div id=dim><div id=dlg>
  <p>이전에 작성 중이던 내용이 있습니다. 불러올까요?</p>
  <div class="btnrow button_row"><button id=cancel>취소</button><button id=ok>불러오기</button></div>
</div></div>
<script>
  // Appears late, exactly like the draft-restore confirm did: the editor boots
  // clean, a pre-flight dismiss finds nothing, and only the next click meets it.
  setTimeout(() => { document.getElementById('dim').style.display = 'block'; }, 900);
  document.getElementById('cancel').onclick = () => {
    document.getElementById('dim').style.display = 'none';
  };
  document.getElementById('ok').onclick = () => { document.title = 'DRAFT RESTORED'; };
</script>
</body></html>"""

INNER = """<!doctype html><html lang=ko><head><meta charset=utf-8><title>내부</title>
<style>
 body{font:15px 'Malgun Gothic',sans-serif;margin:0}
 .toolbar{display:flex;gap:8px;padding:9px 14px;background:#f1f5f9;border-bottom:1px solid #ddd}
 main{padding:20px}
 input,textarea{padding:8px;border:1px solid #bbb;border-radius:5px;width:70%}
</style></head>
<body>
<div class=toolbar>
  <button>굵게</button><button>사진</button>
  <button class="save_btn" id=save>저장 3</button>
</div>
<main><input placeholder="제목"><br><br><textarea placeholder="본문을 입력하세요" rows=8></textarea></main>
<script>
  let n = 3;
  document.getElementById('save').onclick = () => {
    // The proof arrives after a beat, as a real save does.
    setTimeout(() => { n += 1; document.getElementById('save').textContent = '저장 ' + n; }, 500);
  };
</script>
</body></html>"""


FORM = """<!doctype html><html lang=ko><head><meta charset=utf-8><title>신청 양식</title>
<style>
 body{font:15px 'Malgun Gothic',sans-serif;margin:0;padding:24px}
 label{display:block;margin:12px 0 4px}
 input,select,textarea{padding:7px;border:1px solid #bbb;border-radius:5px;width:320px}
 #done{margin-top:16px;color:#0a7}
</style></head>
<body>
<h1>상담 신청</h1>
<form id=f onsubmit="return false">
  <label>이름<input id=name placeholder="이름"></label>
  <label>연락처<input id=phone placeholder="연락처"></label>
  <label>학년<select id=grade>
    <option value="">선택</option><option value="m3">중3</option><option value="h3">고3</option>
  </select></label>
  <label>첨부<input id=file type=file></label>
  <button id=submit type=button>신청하기</button>
  <button id=danger type=button>결제하기</button>
</form>
<p id=done></p>
<script>
  document.getElementById('submit').onclick = () => {
    // 되돌릴 수 없는 동작 앞의 확인창 — 브라우저가 직접 띄우는 것이라 DOM 에 없다.
    if (!confirm('제출하시겠습니까?')) return;
    const pick = (id) => document.getElementById(id).value;
    const f = document.getElementById('file').files;
    // getElementById 로 집는다. `name` 은 window.name(브라우저 내장 문자열)과
    // 부딪혀 입력칸을 안 가리킨다 — 실제로 여기서 undefined 가 나왔다.
    document.getElementById('done').textContent =
      '접수완료 ' + pick('name') + '/' + pick('phone') + '/' + pick('grade') +
      '/' + (f.length ? f[0].name : '첨부없음');
  };
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body = FORM if self.path == "/form" else INNER if self.path == "/inner" else OUTER
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    report: dict[str, object] = {}

    with scratch_root("jarvis-generic-") as root:
        config = JarvisConfig(
            runtime_root=root,
            data_dir=root / "data",
            output_dir=root / "outputs",
            browser_enabled=True,
            browser_headless=True,
            # Off: the save button's text is the evidence, and read-only mode
            # blocks anything whose label looks like 저장.
            browser_read_only=False,
            browser_visual_overlay=False,
            browser_profile_dir=root / "profile",
            browser_download_dir=root / "downloads",
            browser_evidence_dir=root / "evidence",
        )
        config.prepare()
        worker = BrowserWorker(config)
        try:
            worker.execute("browser_open", {"url": base})
            worker.execute("browser_wait", {"milliseconds": 1400})  # let the dialog arrive

            # (1) the snapshot reaches into the iframe
            snapshot = worker.execute("browser_snapshot", {})
            frames = {item["frame"] for item in snapshot["elements"]}
            names = [item["name"] for item in snapshot["elements"]]
            report["frames_seen"] = sorted(frames)
            report["element_count"] = snapshot["element_count"]
            if "workFrame" not in frames:
                raise RuntimeError("iframe_elements_missing")

            # (2) the text read is not empty just because content is embedded
            text = worker.execute("browser_read", {})["text"]
            if "본문을 입력하세요" not in text and "저장" not in text:
                raise RuntimeError("iframe_text_missing")

            save = next(item for item in snapshot["elements"] if item["name"].startswith("저장"))

            # (3+4+5) click the save button while a late dialog covers the page,
            # and require the counter to prove it landed.
            result = worker.execute(
                "browser_click",
                {
                    "ref": save["ref"],
                    "expect": {"kind": "number_increases", "selector": ".save_btn"},
                    "verify_timeout_ms": 6000,
                },
            )
            report["verified"] = result.get("verified")
            report["evidence"] = result.get("verification", {}).get("evidence")
            if not result.get("verified"):
                raise RuntimeError(f"save_not_verified:{result.get('verification')}")

            # The dialog must have been answered with 취소 -- never 불러오기,
            # whose handler renames the document.
            title = worker.execute("browser_read", {"max_chars": 600})["title"]
            report["title_after"] = title
            if "DRAFT RESTORED" in title:
                raise RuntimeError("positive_button_was_pressed")

            # ---- phase 2: the same flow, driven by a JSON recipe -----------
            # Nothing site-specific left in Python. If this passes, adding a new
            # site is a reviewed data file.
            recipe_dir = root / "recipes"
            recipe_dir.mkdir(parents=True, exist_ok=True)
            (recipe_dir / "fixture_editor.json").write_text(
                json.dumps(FIXTURE_RECIPE, ensure_ascii=False), encoding="utf-8"
            )
            config.site_recipe_dir = recipe_dir
            tools = SiteRecipeTools(config, worker)
            recipe_result = tools.run(
                {
                    "site": "fixture_editor",
                    "action": "save_draft",
                    "params": {
                        "base": base,
                        "title": "레시피가 넣은 제목",
                        "body": "레시피가 넣은 본문",
                    },
                }
            )
            report["recipe_status"] = recipe_result["status"]
            report["recipe_evidence"] = [
                step.get("evidence") for step in recipe_result["steps"] if step.get("evidence")
            ]
            if recipe_result["status"] != "done":
                raise RuntimeError(f"recipe_failed:{recipe_result}")

            # ---- phase 3: 폼 4종을 실제 브라우저에서 ------------------------
            worker.execute("browser_open", {"url": base + "/form"})
            worker.execute("browser_wait", {"milliseconds": 300})
            snapshot = worker.execute("browser_snapshot", {})
            by_name = {item["name"]: item["ref"] for item in snapshot["elements"]}
            fields = {item.get("type"): item["ref"] for item in snapshot["elements"]}

            name_ref = by_name.get("이름") or fields.get("text")
            phone_ref = next(
                (i["ref"] for i in snapshot["elements"] if i["name"] == "연락처"), ""
            )
            worker.execute("browser_fill_form", {"fields": [
                {"ref": name_ref, "value": "박가람"},
                {"ref": phone_ref, "value": "010-0000-0000"},
            ]})

            select_ref = next(
                (i["ref"] for i in snapshot["elements"] if i["tag"] == "select"), ""
            )
            worker.execute("browser_select_option", {"ref": select_ref, "label": "고3"})

            upload_dir = root / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            sample = upload_dir / "성적표.txt"
            sample.write_text("점수 90", encoding="utf-8")
            config.browser_upload_allowed_roots = (str(upload_dir),)
            file_ref = next(
                (i["ref"] for i in snapshot["elements"] if i.get("type") == "file"), ""
            )
            worker.execute("browser_file_upload", {"ref": file_ref, "paths": [str(sample)]})

            submit_ref = next(
                (i["ref"] for i in snapshot["elements"] if i["name"] == "신청하기"), ""
            )
            # 순서가 중요하다: 허가를 **먼저** 두고 누른다. 확인창이 떠 있는 동안엔
            # 그 창을 띄운 클릭이 브라우저 스레드를 쥐고 있어서, 뒤에 답하려 하면
            # 교착에 빠진다(이 스크립트가 실제로 그렇게 멈춰서 설계를 되돌렸다).
            worker.execute("browser_handle_dialog", {"accept": True})
            clicked = worker.execute("browser_click", {"ref": submit_ref})
            report["form_dialog"] = clicked.get("dialog_answered", {})
            worker.execute("browser_wait", {"milliseconds": 500})
            done = worker.execute("browser_read", {"max_chars": 2000})["text"]
            report["form_result"] = next(
                (line for line in done.splitlines() if "접수완료" in line), "(접수 문구 없음)"
            )
            if "박가람" not in report["form_result"] or "성적표.txt" not in report["form_result"]:
                raise RuntimeError(f"form_flow_incomplete:{report['form_result']}")

            # 읽기 전용을 껐어도 되돌릴 수 없는 버튼은 여전히 막혀야 한다. 폼이 열렸다고
            # 결제까지 열리면 이 분리는 아무 의미가 없다.
            danger_ref = next(
                (i["ref"] for i in snapshot["elements"] if i["name"] == "결제하기"), ""
            )
            try:
                worker.execute("browser_click", {"ref": danger_ref})
                report["irreversible_blocked"] = False
            except Exception as exc:
                report["irreversible_blocked"] = "irreversible_click_needs_approval" in str(exc)
            if not report["irreversible_blocked"]:
                raise RuntimeError("결제 버튼이 승인 없이 눌렸다 — 위험 분리가 동작하지 않는다")

            report["ok"] = True
        except Exception as exc:
            report["ok"] = False
            report["error"] = str(exc)[:400]
            report["last_failure"] = worker.status().get("last_failure", {})
        finally:
            worker.stop()
            server.shutdown()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
