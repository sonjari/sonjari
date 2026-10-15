"""한·영 동등성 쌍 — **실제 요청에서** 골랐다 (2026-09-23 밤, 영어판 P1).

운영 DB 의 서로 다른 요청 1,181개를 계획 판정 모양(개수·사이트·행위·산출물·검증)과 붙는 스킬로 묶고, 묶음마다 골라 옮겼다.
이름·메일·경로는 일반화했다(나래→민지, 실제 메일→test@example.com, E:\\…→C:\\work\\…). 뜻은 그대로 둔다 — 영어 쪽이
「더 쉽게」 옮겨지면 동등성이 부풀어 보인다. 영어는 **사람이 실제로 칠 법한 말**로 옮겼다(번역투 금지).

한국어 판정 자체가 틀린 요청(예: 「제출…하지 말고 읽기만 해」가 폼 제출로 잡히는 것)은 **넣지 않았다** — 영어가 그 버그까지
따라가야 동등해지기 때문이다. 그런 것은 따로 고친다.
"""
from __future__ import annotations

#: (한국어, 영어)
PAIRS: list[tuple[str, str]] = [
    # ── 처음 10쌍(09-23 밤 첫 측정) ──
    ("사람인에서 여수 회계 공고 3개 찾아서 회사명·마감일을 엑셀로 정리해줘",
     "Find 3 accounting job posts in Yeosu on Saramin and put company names and deadlines in an Excel file"),
    ("다나와에서 무선 마우스 인기 상품 3개를 골라 상세 페이지를 열어 가격을 확인해줘",
     "Pick the top 3 wireless mice on Danawa, open each product page and check the price"),
    ("블로그 글 써서 임시저장만 해줘. 발행하지는 마.",
     "Write a blog post and only save it as a draft. Don't publish it."),
    ("내일 오후 3시에 팀 회의 일정 등록해줘",
     "Add a team meeting to my calendar tomorrow at 3pm"),
    ("이 폴더에 할 일 목록 웹페이지를 index.html로 만들고 미리보기로 보여 줘",
     "Make a to-do list web page as index.html in this folder and show it in the preview"),
    ("회의록.docx를 읽고 핵심 3개를 요약해서 워드로 만들어줘",
     "Read meeting-notes.docx and summarize the 3 key points into a Word document"),
    ("구글 드라이브에 이 보고서를 올려줘",
     "Upload this report to my Google Drive"),
    ("경쟁사 분석 보고서를 문서로 정리해줘",
     "Write a competitor analysis report as a document"),
    ("이력서 초안을 워드로 써줘",
     "Draft my resume as a Word document"),
    ("바탕화면에 memo.txt 만들고 '회의 10시'라고 적어줘",
     "Create memo.txt on the desktop and write 'meeting at 10'"),

    # ── 사이트 조사 · 개수 ──
    ("위시켓에서 AI 에이전트 관련 프로젝트 3개의 제목과 예산을 알려줘",
     "Tell me the titles and budgets of 3 AI agent projects on Wishket"),
    ("위시켓에서 AI 에이전트·자동화 관련 프로젝트 상위 5개의 제목과 예산을 알려줘",
     "Tell me the titles and budgets of the top 5 AI agent or automation projects on Wishket"),
    ("YES24 사이트에서 파이썬(Python) 프로그래밍 관련 책 2권을 검색해서 각 책의 제목, 쪽수, ISBN을 확인해줘.",
     "Search the YES24 site for 2 Python programming books and check the title, page count and ISBN of each."),
    ("사람인에서 여수 회계 채용 공고 3개를 찾아 회사와 마감일을 정리해줘",
     "Find 3 accounting job posts in Yeosu on Saramin and list the companies and deadlines"),
    ("사람인에서 여수 회계 채용 공고 3개의 제목과 회사명을 알려줘",
     "Tell me the titles and company names of 3 accounting job posts in Yeosu on Saramin"),
    ("크몽에서 'AI 자동화' 키워드로 검색했을 때 상위 5개 서비스의 제목과 가격을 알려줘.",
     "Search Kmong for 'AI automation' and tell me the titles and prices of the top 5 services."),
    ("쿠팡에서 무선마우스 3만원 이하로 평점 좋은 거 3개만 찾아서 이름·가격·평점 표로 정리해줘",
     "Find just 3 well-rated wireless mice under 30,000 won on Coupang and put the name, price and rating in a table"),
    ("apps.microsoft.com 에서 \"AI\" 를 검색해서, 검색 결과 목록에서 맨 위부터 나오는 앱 5개의 이름을 순서대로 알려줘. "
     "파일은 만들지 말고 이름 목록만 답으로 줘.",
     "Search apps.microsoft.com for \"AI\" and tell me the names of the first 5 apps in the results, in order. "
     "Don't make a file, just reply with the list of names."),
    ("AI 에이전트 프레임워크 2026년 최신 동향을 조사해줘. 자료는 3개 이상 직접 열어서 읽고, 각각 어디서 읽었는지 주소를 적어줘.",
     "Research the latest 2026 trends in AI agent frameworks. Open and read at least 3 sources yourself and note the address of each."),
    ("위시켓에서 AI 에이전트 관련 프로젝트 3개의 예상 기간과 지원자 수를 알려줘",
     "Tell me the expected duration and number of applicants for 3 AI agent projects on Wishket"),
    ("교보문고에서 '파이썬' 책을 검색해서 상위 3권의 제목과 가격을 알려줘.",
     "Search Kyobo for 'Python' books and tell me the titles and prices of the top 3."),
    ("다나와에서 무선마우스를 검색하고, 정렬을 '낮은가격순'으로 바꾼 다음 상위 3개 상품명과 가격을 알려줘.",
     "Search Danawa for wireless mice, change the sort to lowest price, then tell me the top 3 product names and prices."),
    ("YES24 웹사이트(www.yes24.com)에서 '클린 코드' 책을 검색해서 정확한 상세 페이지를 찾은 뒤, 그 책의 정확한 제목·쪽수·ISBN을 확인해줘. "
     "파일로 만들 필요는 없고 결과만 답해줘.",
     "Search the YES24 website (www.yes24.com) for the book 'Clean Code', find its exact product page, then confirm its exact title, "
     "page count and ISBN. No need to make a file, just answer with the result."),
    ("브라우저를 열어서 robometafit.com 첫 화면을 직접 보고, 어떤 문구와 메뉴가 있는지 확인한 그대로 알려줘",
     "Open robometafit.com in the browser, look at the front page yourself, and tell me exactly what wording and menus are on it"),
    ("지금 국내에서 로컬 AI 에이전트를 어떤 업체들이 만드는지 조사해서 알려줘",
     "Research which companies in Korea are building local AI agents and tell me"),
    ("네이버 뉴스에서 오늘 경제 분야 주요 기사 3개를 찾아서 제목·언론사·한 줄 요약·기사 주소를 표로 정리한 워드 문서로 만들어줘",
     "Find 3 major economy stories on Naver News today and make a Word document with a table of title, publisher, one-line summary and article address"),
    ("무신사에서 남성 반팔 티셔츠 인기 상품 3개를 조사해서 엑셀로 정리해줘. 브랜드·상품명·가격·상품 URL 을 넣어줘.",
     "Research the 3 most popular men's short-sleeve t-shirt products on Musinsa and put them in Excel with brand, product name, price and product URL."),
    ("다나와에서 무선 마우스 인기 상품 3개를 조사해서 CSV 파일로 정리해줘. 상품명·가격·제조사·상품 URL 을 넣어줘.",
     "Research the 3 most popular wireless mouse products on Danawa and save them as a CSV file with product name, price, maker and product URL."),
    ("위시켓에서 AI 에이전트 관련 프로젝트 3개를 조사해서 엑셀 파일로 정리해줘. 프로젝트명·예상기간·지원자수·공고 URL 을 표로 넣어줘.",
     "Research 3 AI agent projects on Wishket and put them in an Excel file with a table of project name, expected duration, applicants and post URL."),
    ("YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 마크다운 문서로 만들어줘. 상세페이지 URL 도 같이 넣어줘.",
     "Look up the page count and ISBN of 3 Python books on YES24 and make a Markdown document. Include each product page URL too."),
    ("교보문고와 YES24에서 '혼자 공부하는 파이썬' 책의 판매가와 쪽수를 각각 확인해서 비교하는 마크다운 문서로 만들어줘.",
     "Check the price and page count of the book 'Python for Self-Study' on both Kyobo and YES24 and make a Markdown document comparing them."),
    ("알라딘에서 데이터 분석 책 3권을 조사해서 워드 문서로 만들어줘. 저자·출판사·정가·상세페이지 URL 을 표로 넣어줘.",
     "Research 3 data analysis books on Aladin and make a Word document with a table of author, publisher, list price and product page URL."),
    ("사람인(saramin.co.kr)에서 여수 지역 회계 관련 채용 공고 2개를 찾아, 회사명과 마감일을 엑셀 파일(.xlsx)로 정리해 줘.",
     "Find 2 accounting job posts in the Yeosu area on Saramin (saramin.co.kr) and put the company names and deadlines in an Excel file (.xlsx)."),
    ("사람인에서 여수 회계 채용 공고 2개를 보고, 거기 지원할 이력서 초안을 문서로 만들어줘. 공고가 요구하는 자격을 반영해줘.",
     "Look at 2 accounting job posts in Yeosu on Saramin and draft a resume for applying to them as a document. Reflect the qualifications the posts ask for."),
    ("예스24(yes24.com)에서 책 「클린 코드」(로버트 마틴)를 검색해서 정가와 쪽수를 찾아, 그 내용을 워드 문서(.docx) 한 장으로 정리해 줘.",
     "Search yes24.com for the book \"Clean Code\" (Robert Martin), find the list price and page count, and put that on one page of a Word document (.docx)."),
    ("지금 열려 있는 로그인된 크롬으로 네이버(naver.com) 메인 페이지에 들어가서, 오늘 메인 화면에 노출된 헤드라인 기사 제목 3개를 찾아 "
     "마크다운(.md) 파일로 저장해 줘.",
     "Using the logged-in Chrome that's open, go to the naver.com main page, find 3 headline titles on today's front page "
     "and save them to a Markdown (.md) file."),
    ("잡코리아에서 오늘자 기준으로 지원 가능한 회계 공고를 찾아줘",
     "Find accounting job posts on JobKorea that are still open for applications as of today"),
    ("크몽에서 다른 사람들이 올린 API 연동 서비스 단가를 한번 알아봐줘",
     "Find out what other people on Kmong charge for API integration services"),

    # ── 파일 · 문서 ──
    ("다음 주 할 일 3개를 한글 문서로 만들어줘.",
     "Make a Hangul document with 3 to-dos for next week."),
    ("이번 작업 폴더에 loop.txt 파일을 만들고 첫 줄에 'workspace closed loop', 둘째 줄에 'created by jarvis'를 저장해줘.",
     "Create a loop.txt file in this work folder and save 'workspace closed loop' on the first line and 'created by jarvis' on the second."),
    ("학생 5명 점수로 엑셀 성적표 파일 만들어줘. 민지 92, 가람 88, 지훈 75, 서연 95, 민수 61. 평균이랑 등수도 넣어줘.",
     "Make an Excel grade sheet for 5 students: Minji 92, Garam 88, Jihoon 75, Seoyeon 95, Minsu 61. Include the average and rank too."),
    ("민지 92, 가람 88, 지훈 75의 이름·점수 표를 roundtrip.xlsx 엑셀 파일로 만들어 저장해줘.",
     "Save a name and score table of Minji 92, Garam 88, Jihoon 75 as the Excel file roundtrip.xlsx."),
    ("사무실 로컬 AI 비서의 장점 다섯 가지를 각각 설명이 있는 마크다운 목록으로 자세히 정리해라.",
     "Write up five advantages of a local AI assistant for the office as a detailed Markdown list with an explanation for each."),
    ("C:\\work\\docs\\architecture.md 를 읽고 핵심을 한글 문서로 만들어줘.",
     "Read C:\\work\\docs\\architecture.md and make a Hangul document of the key points."),
    ("C:\\work\\docs 폴더에 어떤 문서들이 있는지 알려줘.",
     "Tell me what documents are in the C:\\work\\docs folder."),
    ("C:\\work\\recipes 폴더 안에 파일이 몇 개 있고 이름이 뭔지 알려줘",
     "Tell me how many files are in the C:\\work\\recipes folder and what they're called"),
    ("C:\\work\\scope_probe 폴더에 memo.txt 파일을 만들고 '범위 확인'이라고 적어줘. 기존 테스트 파일은 절대 수정하지 마.",
     "Create a memo.txt file in the C:\\work\\scope_probe folder and write 'scope check' in it. Never modify the existing test files."),
    ("우리 학원 상세페이지 문구 좀 써줘. 중등부 수학 집중반이야.",
     "Write the copy for our academy's detail page. It's an intensive middle-school math class."),
    ("우리 학원 인스타 피드 글 만들어줘",
     "Make an Instagram feed post for our academy"),
    ("우리 학원 수강료 가격 책정 어떻게 해야 할지 조언해줘",
     "Advise me on how to price tuition for our academy"),
    ("구글 드라이브에서 이력서 찾아서 읽고, 지원 직무에 맞게 다듬은 수정본을 워드 파일로 만들어줘",
     "Find my resume in Google Drive, read it, and make a revised version tailored to the job as a Word file"),
    ("구글 드라이브에서 이력서 읽어서 한글 파일 하나에 본문을 전부 옮기고, 고칠 만한 곳마다 각주로 수정 제안을 달아줘",
     "Read my resume from Google Drive, copy the whole text into one Hangul file, and add a footnote with a suggested fix everywhere something could be improved"),
    ("구글 드라이브 들어가서 이력서 한번 검토하고 어디에 강점이 있는지 봐줘",
     "Go into Google Drive, review my resume and tell me where my strengths are"),

    # ── 코드 ──
    ("safe_divide(a, b)가 b=0이면 None을 반환하도록 고쳐줘. 기존 공개 테스트 파일은 수정하지 말고 그대로 실행해 검증해줘.",
     "Fix safe_divide(a, b) so it returns None when b=0. Don't modify the existing public test file; run it as-is to verify."),
    ("INSTRUCTIONS.md 를 읽고 beer_song.py 를 구현해줘. 테스트 파일은 수정하지 마. 테스트를 실행해 전부 통과시켜줘.",
     "Read INSTRUCTIONS.md and implement beer_song.py. Don't modify the test file. Run the tests and make them all pass."),
    ("현재 테스트가 대소문자 비교 때문에 실패한다. 먼저 실패를 재현하고 원인을 고친 뒤 같은 테스트를 다시 실행해 통과시켜줘. 테스트는 수정하지 마.",
     "The current test fails because of a case-sensitive comparison. Reproduce the failure first, fix the cause, then rerun the same test "
     "and make it pass. Don't modify the test."),
    ("test_calc.py 가 실패한다. 원인을 찾아 calc.py 를 고치고, python -m pytest -q 를 돌려 통과를 확인해. 테스트 파일은 고치지 마.",
     "test_calc.py is failing. Find the cause, fix calc.py, and run python -m pytest -q to confirm it passes. Don't touch the test file."),
    ("slugify가 공백 묶음을 한 하이픈으로 만들고 양끝 하이픈을 제거하게 고쳐줘. 기존 공개 테스트는 바꾸지 말고 타겟 테스트를 실행해 검증해줘.",
     "Fix slugify so runs of spaces become a single hyphen and hyphens at both ends are removed. Don't change the existing public tests; "
     "run the target test to verify."),
    ("alpha.py에 multiply(a, b)를 추가하고 test_alpha.py에 그 테스트를 추가해서 pytest를 실제로 통과시켜줘.",
     "Add multiply(a, b) to alpha.py, add a test for it to test_alpha.py, and actually get pytest to pass."),
    ("single_check.py 파일 하나를 만들어. 이 파일은 숫자 42만 출력해야 하고, 실제로 실행해서 출력이 42인지 검증해.",
     "Create one file, single_check.py. It should print only the number 42; actually run it and verify the output is 42."),
    ("1부터 1000까지 소수의 개수를 계산해 숫자 168만 출력하는 prime_count.py를 파일로 만들어 저장하고, 그 파일을 실제로 실행해서 검증해줘.",
     "Create prime_count.py as a file and save it; it counts the primes from 1 to 1000 and prints only 168. Then actually run that file to verify it."),
    ("index.html 하나를 만들어줘. 제목은 '별 관측', 버튼 하나(글자는 '관측 시작')와 그 아래 빈 문단이 있고, 버튼을 누르면 문단 글자가 "
     "'관측 중입니다'로 바뀌어야 해. 만든 뒤 미리보기로 열어서 화면을 확인해.",
     "Make one index.html. The title is 'Stargazing', with one button (labeled 'Start') and an empty paragraph below it; clicking the button "
     "should change the paragraph text to 'Observing'. After you make it, open it in the preview and check the screen."),
    ("이 저장소에서 다음 테스트가 실패한다고 하자: tests/test_sandbox.py 실패 출력: ImportError while importing test module "
     "무엇부터 확인해야 하는지 순서만 알려줘. 고치지는 말고 판단만. 짧게.",
     "Suppose this test fails in this repo: tests/test_sandbox.py, output: ImportError while importing test module. "
     "Just tell me the order of what to check first. Don't fix anything, only judge. Keep it short."),
    ("이 저장소에서 코드 모드 판이 자꾸 예산 안에 못 끝난다. 어디가 진짜 병목인지 근거를 대고 판단해줘. 고치지는 말고 판단만. 짧게.",
     "In this repo, code-mode runs keep failing to finish within budget. Judge where the real bottleneck is, with evidence. "
     "Don't fix anything, only judge. Keep it short."),
    ("이 폴더에서 로그인 버그 원인을 찾아서 고치고 테스트 돌려줘",
     "Find the cause of the login bug in this folder, fix it and run the tests"),

    # ── 계산 ──
    ("1부터 1000까지 소수가 몇 개인지 계산해서 숫자만 알려줘",
     "Calculate how many primes there are from 1 to 1000 and tell me only the number"),
    ("강사 A는 문제집 한 권을 검토하는 데 6시간, 강사 B는 9시간이 걸린다. 둘이 같이 하면 겹치는 부분을 확인하느라 전체 작업 효율이 10% 떨어진다. "
     "둘이 함께 한 권을 검토하는 데 몇 시간이 걸리는가? 숫자만 답해라.",
     "Instructor A takes 6 hours to review one workbook and instructor B takes 9 hours. Working together, overall efficiency drops 10% "
     "because they check the overlapping parts. How many hours does it take them to review one book together? Answer with the number only."),
    ("어떤 고등학생의 내신이 국어 3등급(4단위), 수학 2등급(4단위), 영어 4등급(3단위), 한국사 1등급(2단위)이다. 단위수를 가중치로 한 평균 등급을 "
     "소수 둘째 자리까지 구해라. 숫자만 답해라.",
     "A high-school student's grades are Korean 3 (4 credits), math 2 (4 credits), English 4 (3 credits) and Korean history 1 (2 credits). "
     "Compute the credit-weighted average grade to two decimal places. Answer with the number only."),

    # ── 블로그 · 메일 · 캘린더 · 드라이브 ──
    ("로보메타핏 블로그에 '상담 기록 정리 팁'이라는 제목으로 짧은 글 하나 써서 임시저장해줘. 발행하지 마.",
     "Write a short post titled 'Tips for organizing counseling notes' on the Robometafit blog and save it as a draft. Don't publish."),
    ("로보메타핏 블로그에 '학원 데이터 관리 3가지 원칙'이라는 제목으로 5문장 정도 짧은 글을 써서 임시저장까지 해줘. 절대 발행하지 말고 임시저장만 해.",
     "Write a short post of about 5 sentences titled '3 principles of academy data management' on the Robometafit blog and save it as a draft. "
     "Never publish it, only save the draft."),
    ("네이버 블로그에 '테스트 글' 이라는 제목으로 짧은 초안 하나 써서 임시저장까지 해줘",
     "Write a short draft titled 'Test post' on Naver Blog and save it as a draft"),
    ("로보메타핏 블로그에 '학원 상담 기록을 남겨야 하는 이유' 라는 제목으로 6문장 정도 글을 써서 발행까지 해줘.",
     "Write a post of about 6 sentences titled 'Why academies should keep counseling records' on the Robometafit blog and publish it."),
    ("지금 바로 test@example.com 에게 메일 하나 발송해줘. 제목은 [TEST], 본문은 '메일 발송 기능 테스트입니다.'",
     "Send an email to test@example.com right now. Subject [TEST], body 'This is an email sending test.'"),
    ("test@example.com 앞으로 메일 한 통 보내줘. 제목은 '발송 확인', 본문은 '점검용 메일입니다. 확인 후 삭제하셔도 됩니다.' 로.",
     "Send one email to test@example.com with the subject 'Delivery check' and the body 'This is a test email. Feel free to delete it.'"),
    ("내 구글 캘린더에 내일 오후 3시부터 4시까지 '테스트 일정'이라는 제목으로 일정 하나 등록해줘. 참석자는 아무도 넣지 마.",
     "Add an event titled 'Test event' to my Google Calendar tomorrow from 3pm to 4pm. Don't add any attendees."),
    ("내일 오후 3시에 '실행 점검' 일정을 30분짜리로 만들어줘.",
     "Create a 30-minute 'Run check' event tomorrow at 3pm."),
    ("방금 등록한 '테스트 일정'을 내일 오후 5시부터 6시로 옮겨줘.",
     "Move the 'Test event' I just added to tomorrow from 5pm to 6pm."),
    ("방금 등록한 일정을 내일 오후 6시로 옮겨줘",
     "Move the event I just added to 6pm tomorrow"),
    ("내일 오후 팀 회의 일정 취소해줘",
     "Cancel tomorrow afternoon's team meeting event"),
    ("이 문서를 구글 드라이브에 저장해줘",
     "Save this document to my Google Drive"),

    # ── 판단 · 전략 · 잡담 ──
    ("우리 서비스가 만드는 건 잘 되는데 파는 게 안 된다. 지금 진짜 병목이 어디인지 판단해줘. 짧게.",
     "Our service is good at building but bad at selling. Judge where the real bottleneck is right now. Keep it short."),
    ("출시 전에 마케팅 워밍업을 어떻게 하면 좋을지 분석해서 말해줘",
     "Analyze how we should warm up marketing before launch and tell me"),
    ("경쟁사별로 대표 제품을 찾아서 비교해줘",
     "Find each competitor's flagship product and compare them"),
    ("안녕 오늘 기분 어때",
     "hey, how are you today"),
    ("고마워 잘했어",
     "thanks, nice work"),
]
