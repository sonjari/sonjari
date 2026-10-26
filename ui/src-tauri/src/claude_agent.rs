//! 앱 안의 **Claude Agent** (2026-10-26 · ADR `docs/ADR_클로드API_앱통합_2026-10-26.ko.md` 고침 4 · 구현 1판).
//!
//! 모델 칸에서 「Claude Agent」를 고른 대화는 앤트로픽의 클로드 코드 CLI 가 일한다. 우리는 **중계만** 한다:
//! 띄우고 · 흐름(stream-json)을 「컴퓨터」 칸 걸음으로 바꾸고 · 영수증 숫자를 옮긴다. 클로드에게 우리 하네스(몰아가기)는 걸리지 않는다.
//!
//! 파일럿 시범판(`run_pilot_chat`)과 다른 점:
//! - **API 키만.** 키는 손자리 본체가 DPAPI 로 감싸 둔 것(`api_escalation.py` · `secrets/anthropic_api_key.bin`) 하나를 같이 쓴다.
//!   키가 없으면 시작하지 않는다 — 구독 로그인으로 떨어지는 길이 없다. 코워크는 `--bare`(OAuth · 키체인을 아예 안 읽음),
//!   코드 모드는 `-p` 에서 `ANTHROPIC_API_KEY` 가 늘 먼저 쓰인다(code.claude.com/docs/en/authentication 「Authentication precedence」).
//! - **손은 손자리 MCP.** Browser Use · MarkItDown 대신 `sonjari_task` 맡기기 문. 코워크는 그 셋만, 코드 모드는 클로드 코드 자체 도구 + 그 셋.
//! - **코드 모드는 사용자가 고른 코드 폴더가 작업 폴더**(대표 10-26 08:25) — 그 프로젝트의 `CLAUDE.md` · `.claude/` · 사용자 전역 설정을
//!   진짜 클로드 코드처럼 그대로 읽는다. 손자리 지침은 사용자 파일을 고치지 않고 `--append-system-prompt` 로 옆에 끼운다.
//! - 파일럿의 「전역 CLAUDE.md 를 프롬프트에 붙이기」 · 장기 기억은 **안 한다**(API 로 나가는 글이 늘고, 코드 모드는 클로드 코드가 스스로 읽는다).

use super::*;

pub(crate) const STREAM_EVENT: &str = "claude-agent-stream";
const KEY_FILE: &str = "secrets/anthropic_api_key.bin";
const MAX_TURNS: &str = "40";
const MAX_BUDGET_USD: &str = "3.00";
const RESULT_TEXT_LIMIT: usize = 20_000;

/// 맡기기 문 셋 — `claude_agent.py::TOOLS` 와 같은 값이어야 한다(시험이 둘을 맞춘다).
pub(crate) const SONJARI_TOOLS: [&str; 3] = [
    "mcp__sonjari__sonjari_task",
    "mcp__sonjari__sonjari_task_status",
    "mcp__sonjari__sonjari_guide",
];

/// 생각 글을 받는다 (2026-10-26). 새 모델(Opus 4.7 이후)은 API 기본이 「생각 글 빼기(omitted)」라, `-p` 판은 생각 칸이 **빈 글 + 서명**으로만 왔다
/// (대표 PC 13:52 판 기록: thinking 0자 · 서명 1,356자). 대화형 클로드 코드의 `showThinkingSummaries` 설정은 `-p` 에 안 먹는다 —
/// CLI 2.1.241 의 판정이 「직접 준 값 → 대화형이면 그 설정 → 아니면 비움」이다. 그래서 값을 직접 준다. 옛 CLI 가 이 칸을 모르면 빼고 다시 띄운다.
pub(crate) const THINKING_FLAG: [&str; 2] = ["--thinking-display", "summarized"];

/// 명령 걸음(Bash · PowerShell)의 출력을 화면에 실을 때 — 앞뒤를 남기고 가운데를 뺀다(줄 · 글자 둘 다).
const COMMAND_HEAD_LINES: usize = 60;
const COMMAND_TAIL_LINES: usize = 60;
const COMMAND_TEXT_LIMIT: usize = 16_000;

/// 코드 모드에서 미리 허락하는 클로드 코드 자체 도구. 파일 읽기 · 고치기만 — `Bash` 는 넣지 않는다.
/// 사용자가 자기 설정(`.claude/settings.json` · 전역)에서 허락해 둔 명령은 클로드 코드가 그대로 따른다.
const CODE_TOOLS: [&str; 6] = ["Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit"];

#[derive(Deserialize)]
pub(crate) struct AgentChatRequest {
    job_id: String,
    prompt: String,
    #[serde(default)]
    history: Vec<PilotHistoryMessage>,
    #[serde(default)]
    attachments: Vec<PilotAttachment>,
    /// `cowork` · `code`
    #[serde(default)]
    workspace_mode: String,
    #[serde(default)]
    code_workspace: String,
    #[serde(default)]
    resume_session_id: String,
    #[serde(default)]
    model: String,
    /// `ko` · `en` — 어느 지침 파일을 끼울지.
    #[serde(default)]
    lang: String,
    /// 손자리 권한 메뉴 값(`workspace` · `ask` · `reversible` · `read_only` · `bypass`) — 코드 모드에서 클로드 코드 권한 모드로 옮긴다.
    #[serde(default)]
    permission_mode: String,
    /// 입력창 생각 깊이 칩(`auto` · `fast` · `normal` · `deep`) — 클로드 코드 `--effort` 로 옮긴다.
    #[serde(default)]
    effort: String,
}

/// 손자리 권한 메뉴 → 클로드 코드 권한 모드 (2026-10-26 대표: 「Claude 를 고르면 클로드 앱 권한처럼」).
/// 코워크는 맡기기 문만 열어 두므로 이 값을 쓰지 않는다 — 손자리 안의 권한은 손자리가 따로 지킨다.
pub(crate) fn claude_permission(mode: &str) -> &'static str {
    match mode.trim() {
        "workspace" => "auto",
        "ask" => "manual",
        "read_only" => "plan",
        "bypass" => "bypassPermissions",
        _ => "acceptEdits",
    }
}

/// 생각 깊이 칩 → `--effort`. 칩 「자동」은 보통(medium) — 생각 글이 화면에 보이게(값이 없으면 생각을 거의 안 냈다).
pub(crate) fn claude_effort(choice: &str) -> &'static str {
    match choice.trim() {
        "fast" => "low",
        "deep" => "high",
        _ => "medium",
    }
}

#[derive(Clone, Serialize, Default, Debug, PartialEq)]
pub(crate) struct AgentStreamEvent {
    job_id: String,
    /// thinking · text · tool · tool_done · delegated · delegation_status
    kind: String,
    delta: String,
    step: u32,
    tool: String,
    tool_use_id: String,
    message: String,
    ok: bool,
    evidence: Value,
    /// 맡기기 결과에서 꺼낸 손자리 판 번호(`delegated` · `delegation_status`).
    local_job_id: String,
    /// 맡긴 판의 검사 요약 — **센 숫자만**(글은 옮기지 않는다).
    summary: Value,
}

#[derive(Serialize)]
pub(crate) struct AgentDelegation {
    tool_use_id: String,
    local_job_id: String,
}

#[derive(Serialize)]
pub(crate) struct AgentChatResult {
    answer: String,
    /// stream-json `result.total_cost_usd` 그대로. 없으면 null — 지어내지 않는다.
    cost_usd: Option<f64>,
    duration_ms: u128,
    session_id: String,
    model: String,
    input_tokens: u64,
    output_tokens: u64,
    cache_read_tokens: u64,
    cache_creation_tokens: u64,
    num_turns: u64,
    trace: Vec<PilotToolStep>,
    delegations: Vec<AgentDelegation>,
}

#[derive(Serialize)]
pub(crate) struct AgentStatus {
    ready: bool,
    claude_found: bool,
    has_key: bool,
    /// none · ok · subscription_token · admin_key · unreadable — 키 **값**은 끝자리도 안 낸다.
    key_state: String,
    message: String,
}

// ── 키 ───────────────────────────────────────────────────────────────────────────

/// `api_escalation.key_shape` 과 같은 판정. 둘이 갈리면 시험이 잡는다.
pub(crate) fn key_shape(key: &str) -> &'static str {
    let key = key.trim();
    if !key.starts_with("sk-ant-") || key.chars().any(char::is_whitespace) {
        "not_a_key"
    } else if key.starts_with("sk-ant-oat") {
        "subscription_token"
    } else if key.starts_with("sk-ant-admin") {
        "admin_key"
    } else {
        "api_key"
    }
}

fn data_dir() -> PathBuf {
    package::data_dir_from_token(&token_path())
}

#[cfg(target_os = "windows")]
fn dpapi_unprotect(data: &[u8]) -> Result<Vec<u8>, String> {
    #[repr(C)]
    struct Blob {
        cb_data: u32,
        pb_data: *mut u8,
    }
    #[link(name = "crypt32")]
    extern "system" {
        fn CryptUnprotectData(
            data_in: *const Blob,
            description: *mut *mut u16,
            entropy: *const Blob,
            reserved: *const std::ffi::c_void,
            prompt: *const std::ffi::c_void,
            flags: u32,
            data_out: *mut Blob,
        ) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn LocalFree(memory: *mut std::ffi::c_void) -> *mut std::ffi::c_void;
    }
    let mut input = data.to_vec();
    let source = Blob { cb_data: input.len() as u32, pb_data: input.as_mut_ptr() };
    let mut output = Blob { cb_data: 0, pb_data: std::ptr::null_mut() };
    // 본체(`google_workspace.TokenVault`)가 엔트로피 없이 현재 사용자로 감쌌다 — 같은 사용자만 푼다.
    let ok = unsafe {
        CryptUnprotectData(&source, std::ptr::null_mut(), std::ptr::null(), std::ptr::null(), std::ptr::null(), 0, &mut output)
    };
    if ok == 0 || output.pb_data.is_null() {
        return Err("키 파일을 풀지 못했습니다(다른 사용자 계정에서 넣은 키일 수 있습니다).".into());
    }
    let bytes = unsafe { std::slice::from_raw_parts(output.pb_data, output.cb_data as usize).to_vec() };
    unsafe {
        LocalFree(output.pb_data.cast());
    }
    Ok(bytes)
}

#[cfg(not(target_os = "windows"))]
fn dpapi_unprotect(data: &[u8]) -> Result<Vec<u8>, String> {
    Ok(data.to_vec())
}

/// 키를 꺼낸다. 값은 이 프로세스 안에서 클로드 코드의 환경 변수로만 간다 — 화면(웹뷰) · 기록에는 안 간다.
fn read_agent_key(dir: &Path) -> Result<String, String> {
    let path = dir.join(KEY_FILE);
    let raw = fs::read(&path).map_err(|_| "no_key".to_string())?;
    let plain = dpapi_unprotect(&raw)?;
    let value: Value = serde_json::from_slice(&plain).map_err(|_| "키 파일 모양이 다릅니다.".to_string())?;
    let key = value.get("api_key").and_then(Value::as_str).unwrap_or("").trim().to_string();
    match key_shape(&key) {
        "api_key" => Ok(key),
        other => Err(other.to_string()),
    }
}

#[tauri::command]
pub(crate) fn claude_agent_status() -> AgentStatus {
    let claude_found = find_claude().is_some();
    let dir = data_dir();
    let (has_key, key_state) = if !dir.join(KEY_FILE).is_file() {
        (false, "none".to_string())
    } else {
        match read_agent_key(&dir) {
            Ok(_) => (true, "ok".to_string()),
            Err(code) if code == "subscription_token" || code == "admin_key" => (true, code),
            Err(_) => (true, "unreadable".to_string()),
        }
    };
    let ready = claude_found && key_state == "ok";
    let message = if !claude_found {
        "Claude Agent 를 돌릴 프로그램(앤트로픽 CLI)이 이 PC 에 없습니다."
    } else {
        match key_state.as_str() {
            "ok" => "API 키가 연결되어 있습니다.",
            "none" => "API 키를 넣어 주세요.",
            "subscription_token" => "구독 로그인 토큰은 쓸 수 없습니다. Claude Console 의 API 키를 넣어 주세요.",
            "admin_key" => "관리자 키는 쓸 수 없습니다. 일반 API 키를 넣어 주세요.",
            _ => "넣어 둔 키를 읽지 못했습니다. 다시 넣어 주세요.",
        }
    };
    AgentStatus { ready, claude_found, has_key, key_state, message: message.into() }
}

// ── 띄울 명령 ───────────────────────────────────────────────────────────────────────

pub(crate) struct LaunchPlan {
    pub cwd: PathBuf,
    pub args: Vec<String>,
}

/// 띄울 인자(순수 함수 — 시험이 모드별로 센다). 지침 글은 파일에서 읽어 `--append-system-prompt` 로 넘긴다.
pub(crate) fn launch_plan(
    mode: &str,
    model: &str,
    permission: &str,
    effort: &str,
    agent_root: &Path,
    code_workspace: &str,
    instructions: &str,
    resume: Option<&str>,
    thinking_flag: bool,
) -> Result<LaunchPlan, String> {
    let mcp = agent_root.join("mcp.json");
    let code = mode == "code";
    let mut args: Vec<String> = [
        "-p", "--output-format", "stream-json", "--include-partial-messages", "--verbose",
        "--model", model, "--max-turns", MAX_TURNS, "--max-budget-usd", MAX_BUDGET_USD,
        "--effort", claude_effort(effort),
    ]
    .iter()
    .map(|value| value.to_string())
    .collect();
    if thinking_flag {
        args.extend(THINKING_FLAG.iter().map(|value| value.to_string()));
    }
    let cwd = if code {
        let folder = PathBuf::from(code_workspace.trim());
        if code_workspace.trim().is_empty() || !folder.is_dir() {
            return Err("코드 모드에서는 먼저 코드 폴더를 골라 주세요.".into());
        }
        // 진짜 클로드 코드처럼: 그 폴더의 CLAUDE.md · .claude/ · 사용자 전역 설정 · 사용자 자신의 MCP 를 같이 읽는다.
        // 그래서 `--bare` · `--strict-mcp-config` 를 쓰지 않는다. 손자리 MCP 는 옆에 하나 더 얹을 뿐이다.
        args.push("--mcp-config".into());
        args.push(mcp.to_string_lossy().into_owned());
        args.push("--permission-mode".into());
        args.push(claude_permission(permission).into());
        args.push("--allowedTools".into());
        args.extend(CODE_TOOLS.iter().map(|tool| tool.to_string()));
        args.extend(SONJARI_TOOLS.iter().map(|tool| tool.to_string()));
        folder
    } else {
        // 코워크: 전용 빈 폴더 · 손자리 맡기기 문만. `--bare` 는 훅 · CLAUDE.md 자동 읽기 · OAuth 를 끄고 키만 쓴다.
        args.push("--bare".into());
        args.push("--tools".into());
        args.push(String::new());
        args.push("--mcp-config".into());
        args.push(mcp.to_string_lossy().into_owned());
        args.push("--strict-mcp-config".into());
        args.push("--permission-mode".into());
        args.push("dontAsk".into());
        args.push("--allowedTools".into());
        args.extend(SONJARI_TOOLS.iter().map(|tool| tool.to_string()));
        agent_root.join("workspace")
    };
    if !instructions.trim().is_empty() {
        args.push("--append-system-prompt".into());
        args.push(instructions.to_string());
    }
    if let Some(session) = resume {
        args.push("--resume".into());
        args.push(session.to_string());
    }
    Ok(LaunchPlan { cwd, args })
}

fn agent_prompt(request: &AgentChatRequest, attachments: &[(String, String, PathBuf)]) -> String {
    let mut text = String::new();
    if !request.history.is_empty() {
        text.push_str("앞선 대화:\n");
        let mut used = 0usize;
        for row in request.history.iter().rev().take(40).collect::<Vec<_>>().into_iter().rev() {
            let content: String = row.content.chars().take(8_000).collect();
            used += content.chars().count();
            if used > 120_000 {
                break;
            }
            text.push_str(if row.role == "assistant" { "답: " } else { "사용자: " });
            text.push_str(&content);
            text.push('\n');
        }
        text.push('\n');
    }
    if !attachments.is_empty() {
        text.push_str("사용자가 이 일에 붙인 파일(이 PC 경로):\n");
        for (name, mime, path) in attachments {
            text.push_str(&format!("- {name} ({mime}): {}\n", path.display()));
        }
        text.push('\n');
    }
    text.push_str(request.prompt.trim());
    text
}

// ── 흐름 → 화면 사건 ─────────────────────────────────────────────────────────────────

#[derive(Default)]
pub(crate) struct StreamTracker {
    /// tool_use id → (도구 이름, 걸음 번호, 인자) — 인자는 끝난 걸음의 화면 본문(`agent_tool_payload`)을 만들 때 쓴다.
    tools: HashMap<String, (String, u32, Value)>,
    step: u32,
    saw_thinking_delta: bool,
    pub delegations: Vec<(String, String)>,
}

fn is_tool(name: &str, tail: &str) -> bool {
    name == format!("mcp__sonjari__{tail}") || name.ends_with(&format!("__{tail}"))
}

/// 맡기기 결과 글(JSON)에서 판 번호.
fn local_job_of(text: &str) -> String {
    serde_json::from_str::<Value>(text.trim())
        .ok()
        .and_then(|value| value.get("job_id").and_then(Value::as_str).map(str::to_string))
        .filter(|id| !id.is_empty() && id.len() <= 80 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'))
        .unwrap_or_default()
}

/// 맡긴 판 결과에서 **센 숫자만** 꺼낸다 — 글(답 · 출처 주소)은 화면 요약에 안 싣는다(그건 클로드가 받아 판단한다).
pub(crate) fn delegation_summary(text: &str) -> Value {
    let Ok(value) = serde_json::from_str::<Value>(text.trim()) else {
        return Value::Null;
    };
    let count = |key: &str| value.get(key).and_then(Value::as_array).map(|rows| rows.len()).unwrap_or(0);
    let needs = value.get("needs").and_then(Value::as_array);
    let needs_total = needs.map(|rows| rows.len()).unwrap_or(0);
    let needs_met = needs
        .map(|rows| rows.iter().filter(|row| row.get("met").and_then(Value::as_bool) == Some(true)).count())
        .unwrap_or(0);
    serde_json::json!({
        "status": value.get("status").and_then(Value::as_str).unwrap_or(""),
        "steps": value.get("steps").and_then(Value::as_u64).unwrap_or(0),
        "files": count("files"),
        "sources": count("sources"),
        "unsupported_numbers": count("unsupported_numbers"),
        "needs_total": needs_total,
        "needs_met": needs_met,
    })
}

pub(crate) fn stream_events(job_id: &str, value: &Value, tracker: &mut StreamTracker) -> Vec<AgentStreamEvent> {
    let base = || AgentStreamEvent { job_id: job_id.to_string(), evidence: serde_json::json!({}), summary: Value::Null, ..Default::default() };
    let mut out = Vec::new();
    match value.get("type").and_then(Value::as_str).unwrap_or("") {
        "stream_event" => {
            let delta = value.get("event").and_then(|event| event.get("delta"));
            match delta.and_then(|row| row.get("type")).and_then(Value::as_str) {
                Some("thinking_delta") => {
                    let text = delta.and_then(|row| row.get("thinking")).and_then(Value::as_str).unwrap_or("");
                    if !text.is_empty() {
                        tracker.saw_thinking_delta = true;
                        out.push(AgentStreamEvent { kind: "thinking".into(), delta: text.into(), ..base() });
                    }
                }
                Some("text_delta") => {
                    let text = delta.and_then(|row| row.get("text")).and_then(Value::as_str).unwrap_or("");
                    if !text.is_empty() {
                        out.push(AgentStreamEvent { kind: "text".into(), delta: text.into(), ..base() });
                    }
                }
                _ => {}
            }
        }
        "assistant" => {
            let blocks = value.pointer("/message/content").and_then(Value::as_array).cloned().unwrap_or_default();
            for block in blocks {
                match block.get("type").and_then(Value::as_str) {
                    Some("thinking") if !tracker.saw_thinking_delta => {
                        let text = block.get("thinking").and_then(Value::as_str).unwrap_or("");
                        if !text.is_empty() {
                            out.push(AgentStreamEvent { kind: "thinking".into(), delta: text.into(), ..base() });
                        }
                    }
                    Some("tool_use") => {
                        let id = block.get("id").and_then(Value::as_str).unwrap_or("").to_string();
                        if !id.is_empty() && tracker.tools.contains_key(&id) {
                            continue;
                        }
                        tracker.step += 1;
                        let name = block.get("name").and_then(Value::as_str).unwrap_or("tool").to_string();
                        let input = block.get("input").cloned().unwrap_or_else(|| serde_json::json!({}));
                        if !id.is_empty() {
                            tracker.tools.insert(id.clone(), (name.clone(), tracker.step, input));
                        }
                        out.push(AgentStreamEvent {
                            kind: "tool".into(),
                            step: tracker.step,
                            tool: name.clone(),
                            tool_use_id: id,
                            message: format!("{} 실행 중", visible_tool_name(&name)),
                            ok: true,
                            evidence: block.get("input").cloned().unwrap_or_else(|| serde_json::json!({})),
                            ..base()
                        });
                    }
                    _ => {}
                }
            }
        }
        "user" => {
            let blocks = value.pointer("/message/content").and_then(Value::as_array).cloned().unwrap_or_default();
            for block in blocks {
                if block.get("type").and_then(Value::as_str) != Some("tool_result") {
                    continue;
                }
                let id = block.get("tool_use_id").and_then(Value::as_str).unwrap_or("").to_string();
                let Some((name, step, input)) = tracker.tools.get(&id).cloned() else {
                    continue;
                };
                let failed = block.get("is_error").and_then(Value::as_bool).unwrap_or(false);
                let text = content_text(block.get("content").unwrap_or(&Value::Null));
                let shown = redact_api_keys(&text.chars().take(RESULT_TEXT_LIMIT).collect::<String>());
                // ★ 끝난 걸음의 화면 본문을 **여기서 한 번** 만든다(2026-10-26 대표: 「Bash 를 열면 줄 번호 1 만」).
                //   예전에는 화면이 걸음 결과 글만 받아 붙였고, 명령 글은 끝난 판의 기록(`run_claude_agent`)에만 있었다 — 도는 동안과 끝난 뒤가 달랐다.
                out.push(AgentStreamEvent {
                    kind: "tool_done".into(),
                    step,
                    tool: name.clone(),
                    tool_use_id: id.clone(),
                    ok: !failed,
                    evidence: agent_tool_payload(&name, &input, &shown),
                    message: shown,
                    ..base()
                });
                if failed {
                    continue;
                }
                if is_tool(&name, "sonjari_task") {
                    let local = local_job_of(&text);
                    if !local.is_empty() {
                        tracker.delegations.push((id.clone(), local.clone()));
                        out.push(AgentStreamEvent { kind: "delegated".into(), step, tool: name.clone(), tool_use_id: id.clone(), ok: true, local_job_id: local, ..base() });
                    }
                } else if is_tool(&name, "sonjari_task_status") {
                    let summary = delegation_summary(&text);
                    let local = local_job_of(&text);
                    if !summary.is_null() {
                        out.push(AgentStreamEvent { kind: "delegation_status".into(), step, tool: name, tool_use_id: id, ok: true, local_job_id: local, summary, ..base() });
                    }
                }
            }
        }
        _ => {}
    }
    out
}

/// 끝난 판의 `result` 줄 → 영수증 숫자. **있는 값만** — 없으면 0 · null.
pub(crate) fn result_numbers(value: &Value) -> (Option<f64>, u64, u64, u64, u64, u64) {
    (
        value.get("total_cost_usd").and_then(Value::as_f64),
        usage_number(value, "/usage/input_tokens"),
        usage_number(value, "/usage/output_tokens"),
        usage_number(value, "/usage/cache_read_input_tokens"),
        usage_number(value, "/usage/cache_creation_input_tokens"),
        value.get("num_turns").and_then(Value::as_u64).unwrap_or(0),
    )
}

/// 코드 모드의 「바뀐 줄」 — 화면의 EditReplay 가 받는 꼴(`edit_preview`). 시작 줄은 **끝난 뒤 파일에서 바꾼 글을 찾아** 적고,
/// 못 찾으면 0(화면이 번호를 안 그린다) — 줄 번호를 지어내지 않는다.
pub(crate) fn edit_preview(name: &str, arguments: &Value) -> Option<Value> {
    let path = arguments.get("file_path").and_then(Value::as_str)?;
    let (old, new) = match name {
        "Edit" => (
            arguments.get("old_string").and_then(Value::as_str).unwrap_or(""),
            arguments.get("new_string").and_then(Value::as_str).unwrap_or(""),
        ),
        "Write" => ("", arguments.get("content").and_then(Value::as_str).unwrap_or("")),
        _ => return None,
    };
    let lines = |text: &str| text.lines().take(200).map(str::to_string).collect::<Vec<_>>();
    let start_line = if name == "Write" {
        1
    } else if new.is_empty() {
        0
    } else {
        fs::metadata(path)
            .ok()
            .filter(|meta| meta.len() <= 2 * 1024 * 1024)
            .and_then(|_| fs::read_to_string(path).ok())
            .and_then(|text| text.find(new).map(|at| text[..at].matches('\n').count() + 1))
            .unwrap_or(0)
    };
    Some(serde_json::json!({
        "start_line": start_line,
        "removed": lines(old),
        "added": lines(new),
        "truncated": old.lines().count() > 200 || new.lines().count() > 200,
        "added_count": new.lines().count(),
    }))
}

/// 명령 걸음(Bash · PowerShell)의 화면 본문 — `$ 명령` 한 줄 + 출력(앞뒤만 · 키 가림). 명령이 없으면 None.
///
/// 「진짜 돌렸다」의 화면 증거다(2026-10-26 대표: pytest 를 돌렸는데 걸음을 열면 비어 있었다). 출력은 클로드 코드가 준 글 그대로 —
/// 종료 코드는 흐름에 없어서 적지 않는다(지어내지 않는다). 실패(승인 필요 등)도 같은 모양으로 보인다.
pub(crate) fn command_payload(name: &str, arguments: &Value, result_text: &str) -> Option<Value> {
    if !matches!(name, "Bash" | "PowerShell") {
        return None;
    }
    let command = redact_api_keys(arguments.get("command").and_then(Value::as_str).unwrap_or("").trim());
    if command.is_empty() {
        return None;
    }
    let output = redact_api_keys(&result_text.replace("\r\n", "\n").replace('\r', "\n"));
    let lines: Vec<&str> = output.trim_end().lines().collect();
    let mut clipped = false;
    let mut body = if lines.len() > COMMAND_HEAD_LINES + COMMAND_TAIL_LINES {
        clipped = true;
        let skipped = lines.len() - COMMAND_HEAD_LINES - COMMAND_TAIL_LINES;
        let mut kept = lines[..COMMAND_HEAD_LINES].join("\n");
        kept.push_str(&format!("\n… 가운데 {skipped}줄 생략 …\n"));
        kept.push_str(&lines[lines.len() - COMMAND_TAIL_LINES..].join("\n"));
        kept
    } else {
        lines.join("\n")
    };
    let chars = body.chars().count();
    if chars > COMMAND_TEXT_LIMIT {
        clipped = true;
        let half = COMMAND_TEXT_LIMIT / 2;
        let head: String = body.chars().take(half).collect();
        let tail: String = body.chars().skip(chars - half).collect();
        body = format!("{head}\n… 가운데 {}자 생략 …\n{tail}", chars - COMMAND_TEXT_LIMIT);
    }
    let prompt = if name == "PowerShell" { "PS>" } else { "$" };
    let text = if body.is_empty() { format!("{prompt} {command}") } else { format!("{prompt} {command}\n{body}") };
    Some(serde_json::json!({
        "command": command,
        "text": text,
        "language": if name == "PowerShell" { "powershell" } else { "bash" },
        "output_lines": lines.len(),
        "clipped": clipped,
    }))
}

/// 이 PC 의 CLI 가 `--thinking-display` 를 모르고 바로 끝났나 — 흐름이 한 줄도 없고 그 칸 이름이 오류에 있을 때만.
/// (2.1.241 은 안다: 모르는 값을 주면 「Allowed choices are summarized, omitted」 — 이 PC 에서 키 없이 띄워 확인.)
pub(crate) fn thinking_flag_rejected(stdout: &[u8], stderr: &[u8]) -> bool {
    let quiet = !String::from_utf8_lossy(stdout).lines().any(|line| line.trim_start().starts_with('{'));
    let error = String::from_utf8_lossy(stderr).to_ascii_lowercase();
    quiet && error.contains("thinking-display") && (error.contains("unknown option") || error.contains("unknown argument"))
}

fn agent_tool_payload(name: &str, arguments: &Value, result_text: &str) -> Value {
    if let Some(payload) = command_payload(name, arguments, result_text) {
        return payload;
    }
    if let Some(preview) = edit_preview(name, arguments) {
        return serde_json::json!({
            "path": arguments.get("file_path").and_then(Value::as_str).unwrap_or(""),
            "edit_preview": preview,
            "text": result_text,
        });
    }
    tool_payload(name, arguments, result_text)
}

fn run_claude_agent(app: &AppHandle, request: AgentChatRequest) -> Result<AgentChatResult, String> {
    if request.prompt.trim().is_empty() {
        return Err("요청이 비어 있습니다.".into());
    }
    let claude = find_claude().ok_or("Claude Agent 를 돌릴 프로그램(앤트로픽 CLI)을 찾지 못했습니다.")?;
    let dir = data_dir();
    let key = read_agent_key(&dir).map_err(|code| match code.as_str() {
        "no_key" => "API 키가 없습니다. 모델 칸의 「키 넣기」로 넣어 주세요.".to_string(),
        "subscription_token" => "구독 로그인 토큰은 쓸 수 없습니다. Claude Console 의 API 키를 넣어 주세요.".to_string(),
        "admin_key" => "관리자 키는 쓸 수 없습니다. 일반 API 키를 넣어 주세요.".to_string(),
        other => other.to_string(),
    })?;
    let root = dir.join("claude_agent");
    let mode = if request.workspace_mode == "code" { "code" } else { "cowork" };
    let lang = if request.lang.starts_with("en") { "en" } else { "ko" };
    let instructions = fs::read_to_string(root.join(format!("instructions_{mode}.{lang}.md")))
        .map_err(|_| "손자리 지침 파일이 없습니다. 앱을 다시 켜 주세요.".to_string())?;
    if !root.join("mcp.json").is_file() {
        return Err("손자리 연결 파일이 없습니다. 앱을 다시 켜 주세요.".into());
    }
    let model = selected_pilot_model(&request.model);
    let resume = request.resume_session_id.trim();
    let resume = valid_resume_session(resume).then_some(resume);
    let plan = launch_plan(mode, model, &request.permission_mode, &request.effort, &root, &request.code_workspace, &instructions, resume, true)?;
    fs::create_dir_all(&plan.cwd).map_err(|error| error.to_string())?;

    let attach_root = root.join("attachments").join(&request.job_id);
    let mut attachment_paths = Vec::new();
    let mut total_bytes = 0usize;
    for attachment in &request.attachments {
        let bytes = BASE64
            .decode(&attachment.data_base64)
            .map_err(|_| format!("첨부 파일을 해독하지 못했습니다: {}", attachment.name))?;
        total_bytes += bytes.len();
        if bytes.len() > 25 * 1024 * 1024 || total_bytes > 60 * 1024 * 1024 {
            return Err("첨부 파일은 개별 25MB, 합계 60MB까지 사용할 수 있습니다.".into());
        }
        fs::create_dir_all(&attach_root).map_err(|error| error.to_string())?;
        let name = safe_attachment_name(&attachment.name);
        let path = attach_root.join(&name);
        fs::write(&path, bytes).map_err(|error| error.to_string())?;
        attachment_paths.push((name, attachment.mime_type.clone(), path));
    }
    let prompt = agent_prompt(&request, &attachment_paths);

    let started = Instant::now();
    let mut plan = plan;
    let mut thinking_flag = true;
    let (status, stdout_bytes, stderr_bytes, tracker) = loop {
        let mut command = claude_process(&claude);
        command
            .current_dir(&plan.cwd)
            .args(&plan.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            // 키 말고 다른 자격이 먼저 쓰이지 않게(문서의 순서: 클라우드 · AUTH_TOKEN 이 API 키보다 앞) — 이 프로세스 환경에서 뺀다.
            .env_remove("ANTHROPIC_AUTH_TOKEN")
            .env_remove("CLAUDE_CODE_OAUTH_TOKEN")
            .env_remove("CLAUDE_CODE_USE_BEDROCK")
            .env_remove("CLAUDE_CODE_USE_VERTEX")
            .env_remove("CLAUDE_CODE_USE_FOUNDRY")
            .env("ANTHROPIC_API_KEY", &key)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8");

        let mut child = command.spawn().map_err(|error| format!("Claude Agent 를 시작하지 못했습니다: {error}"))?;
        app.state::<PilotState>()
            .children
            .lock()
            .map_err(|_| "작업 상태 잠금이 손상되었습니다.".to_string())?
            .insert(request.job_id.clone(), child.id());
        if let Some(stdin) = child.stdin.as_mut() {
            // 옛 CLI 가 인자에서 바로 끝나면 입력 관이 먼저 닫혀 있다 — 그때는 아래 「칸을 모름」 판정으로 간다.
            let _ = stdin.write_all(prompt.as_bytes());
        }
        drop(child.stdin.take());
        let stdout = child.stdout.take().ok_or("stdout 를 연결하지 못했습니다.")?;
        let stderr = child.stderr.take().ok_or("stderr 를 연결하지 못했습니다.")?;
        let stderr_reader = std::thread::spawn(move || {
            let mut bytes = Vec::new();
            let _ = BufReader::new(stderr).read_to_end(&mut bytes);
            bytes
        });
        let mut stdout_bytes = Vec::new();
        let mut tracker = StreamTracker::default();
        for line in BufReader::new(stdout).lines() {
            let line = line.map_err(|error| error.to_string())?;
            stdout_bytes.extend_from_slice(line.as_bytes());
            stdout_bytes.push(b'\n');
            if let Ok(value) = serde_json::from_str::<Value>(&line) {
                for event in stream_events(&request.job_id, &value, &mut tracker) {
                    let _ = app.emit(STREAM_EVENT, event);
                }
            }
        }
        let status = child.wait().map_err(|error| error.to_string())?;
        let stderr_bytes = stderr_reader.join().unwrap_or_default();
        if let Ok(mut children) = app.state::<PilotState>().children.lock() {
            children.remove(&request.job_id);
        }
        if thinking_flag && !status.success() && thinking_flag_rejected(&stdout_bytes, &stderr_bytes) {
            // 이 PC 의 CLI 가 생각 글 칸(`--thinking-display`)을 모른다 — 그 칸만 빼고 한 번 더 띄운다(생각 글 없이 일은 한다).
            thinking_flag = false;
            plan = launch_plan(mode, model, &request.permission_mode, &request.effort, &root, &request.code_workspace, &instructions, resume, false)?;
            continue;
        }
        break (status, stdout_bytes, stderr_bytes, tracker);
    };
    drop(key);
    let parsed = parse_stream_output(&stdout_bytes);
    if !status.success() && parsed.is_err() {
        let stderr = redact_api_keys(&String::from_utf8_lossy(&stderr_bytes));
        let short: String = stderr.chars().take(2_000).collect();
        return Err(format!("Claude Agent 작업이 실패했습니다 (exit={status}). {}", short.trim()));
    }
    let (value, mut trace) = parsed?;
    for step in trace.iter_mut() {
        let text = step.payload.get("text").and_then(Value::as_str).unwrap_or("").to_string();
        step.payload = agent_tool_payload(&step.tool, &step.arguments, &redact_api_keys(&text));
    }
    if value.get("is_error").and_then(Value::as_bool).unwrap_or(false) {
        return Err(redact_api_keys(value.get("result").and_then(Value::as_str).unwrap_or("Claude Agent 가 오류를 돌려줬습니다.")));
    }
    let answer = value.get("result").and_then(Value::as_str).unwrap_or("").trim().to_string();
    if answer.is_empty() {
        return Err("Claude Agent 가 빈 답을 돌려줬습니다.".into());
    }
    let (cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, num_turns) = result_numbers(&value);
    Ok(AgentChatResult {
        answer,
        cost_usd,
        duration_ms: started.elapsed().as_millis(),
        session_id: value.get("session_id").and_then(Value::as_str).unwrap_or("").to_string(),
        model: model.to_string(),
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_creation_tokens,
        num_turns,
        trace,
        delegations: tracker
            .delegations
            .into_iter()
            .map(|(tool_use_id, local_job_id)| AgentDelegation { tool_use_id, local_job_id })
            .collect(),
    })
}

#[tauri::command]
pub(crate) async fn claude_agent_chat(app: AppHandle, request: AgentChatRequest) -> Result<AgentChatResult, String> {
    let result = tauri::async_runtime::spawn_blocking(move || run_claude_agent(&app, request))
        .await
        .map_err(|error| format!("Claude Agent 작업 스레드가 중단되었습니다: {error}"))
        .and_then(|inner| inner);
    if let Err(error) = &result {
        log_agent_error(error);
    }
    result
}

/// 실패 문장을 파일에도 남긴다(키 가림) — 화면이 오류를 못 띄웠을 때 원인을 볼 자리 (2026-10-26 첫 판: 오류가 화면에서 삼켜졌다).
fn log_agent_error(error: &str) {
    use std::io::Write as _;
    let path = data_dir().join("claude_agent").join("errors.log");
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or(0);
    let line: String = redact_api_keys(error).chars().take(4_000).collect();
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{stamp}\t{}", line.replace('\n', " "));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = include_str!("testdata/claude_agent_stream.jsonl");

    fn replay() -> (Vec<AgentStreamEvent>, StreamTracker) {
        let mut tracker = StreamTracker::default();
        let mut events = Vec::new();
        for line in SAMPLE.lines().filter(|line| !line.trim().is_empty()) {
            let value: Value = serde_json::from_str(line).expect("sample line is JSON");
            events.extend(stream_events("job-1", &value, &mut tracker));
        }
        (events, tracker)
    }

    #[test]
    fn sample_stream_becomes_steps_and_hand_off() {
        let (events, tracker) = replay();
        let tools: Vec<_> = events.iter().filter(|event| event.kind == "tool").map(|event| (event.step, event.tool.as_str())).collect();
        assert_eq!(tools, vec![
            (1, "mcp__sonjari__sonjari_guide"),
            (2, "mcp__sonjari__sonjari_task"),
            (3, "mcp__sonjari__sonjari_task_status"),
            (4, "mcp__sonjari__sonjari_task_status"),
        ]);
        let delegated: Vec<_> = events.iter().filter(|event| event.kind == "delegated").collect();
        assert_eq!(delegated.len(), 1);
        assert_eq!(delegated[0].local_job_id, "a1b2c3d4e5f6");
        assert_eq!(tracker.delegations, vec![("toolu_02".to_string(), "a1b2c3d4e5f6".to_string())]);
        let last = events.iter().filter(|event| event.kind == "delegation_status").last().expect("status summary");
        assert_eq!(last.summary["status"], "done");
        assert_eq!(last.summary["sources"], 5);
        assert_eq!(last.summary["files"], 1);
        assert_eq!(last.summary["unsupported_numbers"], 0);
        assert_eq!(last.summary["needs_met"], 2);
        assert_eq!(last.summary["needs_total"], 2);
        // 글(답 · 주소)은 요약에 실리지 않는다.
        assert!(!last.summary.to_string().contains("http"));
        assert!(events.iter().any(|event| event.kind == "thinking"));
        assert!(events.iter().any(|event| event.kind == "text"));
    }

    #[test]
    fn same_tool_use_is_not_counted_twice() {
        let (events, _) = replay();
        let ids: Vec<_> = events.iter().filter(|event| event.kind == "tool").map(|event| event.tool_use_id.clone()).collect();
        let mut unique = ids.clone();
        unique.dedup();
        assert_eq!(ids, unique);
    }

    #[test]
    fn receipt_numbers_come_only_from_result_line() {
        let (value, trace) = parse_stream_output(SAMPLE.as_bytes()).expect("result line");
        let (cost, input, output, cache_read, _, turns) = result_numbers(&value);
        assert_eq!(cost, Some(0.0412));
        assert_eq!((input, output, cache_read, turns), (6100, 900, 2048, 5));
        assert_eq!(trace.len(), 4);
        let missing = serde_json::json!({"type": "result", "result": "ok"});
        assert_eq!(result_numbers(&missing).0, None);
    }

    #[test]
    fn permission_menu_and_effort_chip_map_to_claude_code() {
        assert_eq!(claude_permission("bypass"), "bypassPermissions");
        assert_eq!(claude_permission("workspace"), "auto");
        assert_eq!(claude_permission("ask"), "manual");
        assert_eq!(claude_permission("reversible"), "acceptEdits");
        assert_eq!(claude_permission("read_only"), "plan");
        assert_eq!(claude_permission(""), "acceptEdits");
        assert_eq!((claude_effort("fast"), claude_effort("auto"), claude_effort("deep")), ("low", "medium", "high"));
        let root = std::env::temp_dir().join("sonjari-agent-test");
        let folder = std::env::temp_dir();
        let plan = launch_plan("code", "claude-sonnet-5-5", "bypass", "deep", &root, &folder.to_string_lossy(), "지침", None, true).unwrap();
        let args = plan.args.join(" | ");
        assert!(args.contains("--permission-mode | bypassPermissions"));
        assert!(args.contains("--effort | high"));
        // 코워크는 권한 메뉴와 상관없이 맡기기 문만 — dontAsk 그대로.
        let cowork = launch_plan("cowork", "claude-sonnet-5-5", "bypass", "", &root, "", "지침", None, true).unwrap();
        assert!(cowork.args.join(" | ").contains("--permission-mode | dontAsk"));
    }

    #[test]
    fn cowork_plan_is_bare_and_only_delegation_tools() {
        let root = std::env::temp_dir().join("sonjari-agent-test");
        let plan = launch_plan("cowork", "claude-sonnet-5-5", "bypass", "auto", &root, "", "지침", None, true).unwrap();
        let args = plan.args.join(" | ");
        assert!(plan.args.contains(&"--bare".to_string()));
        assert!(plan.args.contains(&"--strict-mcp-config".to_string()));
        assert!(args.contains("--permission-mode | dontAsk"));
        let at = plan.args.iter().position(|arg| arg == "--tools").unwrap();
        assert_eq!(plan.args[at + 1], "");
        for tool in SONJARI_TOOLS {
            assert!(plan.args.contains(&tool.to_string()));
        }
        assert!(!plan.args.iter().any(|arg| arg == "Edit" || arg == "Bash"));
        assert_eq!(plan.cwd, root.join("workspace"));
        assert!(args.contains("--append-system-prompt | 지침"));
    }

    #[test]
    fn code_plan_runs_in_users_folder_and_reads_their_setup() {
        let root = std::env::temp_dir().join("sonjari-agent-test");
        let folder = std::env::temp_dir();
        let plan = launch_plan("code", "claude-opus-5-5", "", "", &root, &folder.to_string_lossy(), "지침", Some("abcdef12-3456"), true).unwrap();
        assert_eq!(plan.cwd, folder);
        assert!(!plan.args.contains(&"--bare".to_string()));
        assert!(!plan.args.contains(&"--strict-mcp-config".to_string()));
        assert!(plan.args.contains(&"Edit".to_string()));
        assert!(!plan.args.contains(&"Bash".to_string()));
        assert!(plan.args.contains(&"mcp__sonjari__sonjari_task".to_string()));
        assert!(plan.args.join(" ").contains("--resume abcdef12-3456"));
        assert!(launch_plan("code", "claude-opus-5-5", "", "", &root, "", "지침", None, true).is_err());
    }

    #[test]
    fn edit_preview_finds_the_real_line_or_says_zero() {
        let dir = std::env::temp_dir().join(format!("sonjari-edit-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let file = dir.join("a.py");
        fs::write(&file, "one\ntwo\nthree = 3\nfour\n").unwrap();
        let args = serde_json::json!({"file_path": file.to_string_lossy(), "old_string": "three", "new_string": "three = 3"});
        let preview = edit_preview("Edit", &args).unwrap();
        assert_eq!(preview["start_line"], 3);
        assert_eq!(preview["added"], serde_json::json!(["three = 3"]));
        let missing = serde_json::json!({"file_path": file.to_string_lossy(), "old_string": "x", "new_string": "not in file"});
        assert_eq!(edit_preview("Edit", &missing).unwrap()["start_line"], 0);
        assert!(edit_preview("Read", &args).is_none());
        let _ = fs::remove_dir_all(dir);
    }

    const CODE_SAMPLE: &str = include_str!("testdata/claude_agent_code_stream.jsonl");

    fn replay_code() -> Vec<AgentStreamEvent> {
        let mut tracker = StreamTracker::default();
        let mut events = Vec::new();
        for line in CODE_SAMPLE.lines().filter(|line| !line.trim().is_empty()) {
            let value: Value = serde_json::from_str(line).expect("sample line is JSON");
            events.extend(stream_events("job-c", &value, &mut tracker));
        }
        events
    }

    /// 대표 PC 10-26 13:59 판(클로드 코드 기록 `31deb38a…`)의 모양 그대로 — pytest 를 돌린 걸음을 열면 명령과 출력이 보여야 한다.
    #[test]
    fn command_steps_carry_command_and_output() {
        let events = replay_code();
        let done: Vec<_> = events.iter().filter(|event| event.kind == "tool_done").collect();
        assert_eq!(done.iter().map(|event| event.tool.as_str()).collect::<Vec<_>>(), vec!["Edit", "Bash", "PowerShell", "Bash"]);
        let bash = done[3];
        assert!(bash.ok);
        assert_eq!(bash.evidence["command"], "python -m pytest -q test_price.py");
        let text = bash.evidence["text"].as_str().unwrap();
        assert!(text.starts_with("$ python -m pytest -q test_price.py\n"), "{text}");
        assert!(text.ends_with("2 passed in 0.01s"), "{text}");
        assert!(!text.contains('\r'));
        // 실패한 명령(승인 필요)도 명령 · 까닭이 같은 모양으로 남는다.
        let denied = done[1];
        assert!(!denied.ok);
        assert!(denied.evidence["text"].as_str().unwrap().contains("requires approval"));
        assert!(done[2].evidence["text"].as_str().unwrap().starts_with("PS> python -m pytest"));
        // 고친 걸음은 지금처럼 「바뀐 줄」 꼴.
        assert!(done[0].evidence.get("edit_preview").is_some());
        // 끝난 판의 기록(parse_stream_output → agent_tool_payload)도 같은 본문.
        let (_, trace) = parse_stream_output(CODE_SAMPLE.as_bytes()).unwrap();
        let last = trace.last().unwrap();
        let payload = agent_tool_payload(&last.tool, &last.arguments, last.payload["text"].as_str().unwrap());
        assert_eq!(payload["text"], bash.evidence["text"]);
    }

    #[test]
    fn long_command_output_keeps_head_and_tail_and_hides_keys() {
        let output: String = (1..=500).map(|n| format!("line {n}\n")).collect::<String>() + concat!("sk-ant-", "api03-SECRETSECRETSECRETSECRETSECRET");
        let payload = command_payload("Bash", &serde_json::json!({"command": concat!("echo sk-ant-", "api03-ABCDEFABCDEFABCDEFABCDEF")}), &output).unwrap();
        let text = payload["text"].as_str().unwrap();
        assert!(text.contains("line 1\n") && text.contains("line 60\n") && !text.contains("line 61\n"));
        assert!(text.contains("가운데 381줄 생략"), "{text}");
        assert!(text.contains("line 500"));
        assert!(!text.contains("SECRET") && !text.contains("ABCDEF"));
        assert_eq!(payload["clipped"], true);
        assert!(command_payload("Bash", &serde_json::json!({}), "x").is_none());
        assert!(command_payload("Read", &serde_json::json!({"command": "x"}), "x").is_none());
    }

    /// 생각 글 — 칸 없이 띄우면 새 모델은 빈 생각(서명만)이 온다(대표 PC 13:52 판 기록). 칸을 주고, 빈 생각은 화면에 안 싣는다.
    #[test]
    fn thinking_is_requested_and_redacted_blocks_are_skipped() {
        let root = std::env::temp_dir().join("sonjari-agent-test");
        let folder = std::env::temp_dir();
        let plan = launch_plan("code", "claude-sonnet-5-5", "", "", &root, &folder.to_string_lossy(), "지침", None, true).unwrap();
        assert!(plan.args.join(" ").contains("--thinking-display summarized"));
        let cowork = launch_plan("cowork", "claude-sonnet-5-5", "", "", &root, "", "지침", None, true).unwrap();
        assert!(cowork.args.join(" ").contains("--thinking-display summarized"));
        let old_cli = launch_plan("code", "claude-sonnet-5-5", "", "", &root, &folder.to_string_lossy(), "지침", None, false).unwrap();
        assert!(!old_cli.args.iter().any(|arg| arg == "--thinking-display"));
        let thinking: Vec<_> = replay_code().into_iter().filter(|event| event.kind == "thinking").map(|event| event.delta).collect();
        assert_eq!(thinking.concat(), "The test expects quantity to be multiplied and the threshold to be inclusive. I'll fix both, then run pytest.");
        assert!(thinking.iter().all(|delta| !delta.is_empty()));
    }

    #[test]
    fn old_cli_without_thinking_flag_is_detected_only_when_it_said_so() {
        assert!(thinking_flag_rejected(b"", b"error: unknown option '--thinking-display'"));
        assert!(!thinking_flag_rejected(b"{\"type\":\"system\"}\n", b"error: unknown option '--thinking-display'"));
        assert!(!thinking_flag_rejected(b"", b"Not logged in"));
    }

    #[test]
    fn key_shapes_match_python() {
        assert_eq!(key_shape(&format!("sk-ant-api03-{}", "x".repeat(40))), "api_key");
        assert_eq!(key_shape(&format!("sk-ant-oat01-{}", "x".repeat(40))), "subscription_token");
        assert_eq!(key_shape(&format!("sk-ant-admin01-{}", "x".repeat(40))), "admin_key");
        assert_eq!(key_shape("hunter2"), "not_a_key");
    }

    #[test]
    fn tool_names_match_python_module() {
        let python = include_str!("../../../src/alture_jarvis/claude_agent.py");
        assert!(python.contains("mcp__{MCP_SERVER_NAME}__{tool['name']}"));
        for tool in SONJARI_TOOLS {
            assert!(tool.starts_with("mcp__sonjari__sonjari_"));
        }
    }

    #[test]
    fn key_never_leaks_into_tool_done_text() {
        let line = serde_json::json!({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": concat!("found sk-ant-", "api03-SECRETSECRETSECRETSECRETSECRETSECRETSECRET")}
        ]}});
        let mut tracker = StreamTracker::default();
        tracker.tools.insert("t1".into(), ("mcp__sonjari__sonjari_guide".into(), 1, serde_json::json!({})));
        let events = stream_events("j", &line, &mut tracker);
        assert!(!events[0].message.contains("SECRET"));
    }
}
