use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{HashMap, HashSet},
    env, fs,
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, PhysicalPosition, Position, Size, WebviewUrl, WebviewWindowBuilder,
};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

mod package;
mod tray_status;
mod webview_check;

// 빌드할 때 `JARVIS_DEFAULT_BACKEND_URL` 로 바꿀 수 있다 — 포장 시험판이 운영(8091)과 안 부딪히게.
// CSP(`tauri.*.conf.json`)의 connect-src 와 같은 포트여야 한다.
const DEFAULT_BACKEND_URL: &str = match option_env!("JARVIS_DEFAULT_BACKEND_URL") {
    Some(url) => url,
    None => "http://127.0.0.1:8091",
};

/// 앱이 켠 동봉 백엔드. 앱을 닫을 때 기억 복제본을 한 번 뜬 뒤 끈다.
#[derive(Default)]
struct BundledBackend(Mutex<Option<std::process::Child>>);
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Serialize)]
struct BackendBootstrap {
    base_url: String,
    control_token: String,
    mode: String,
}

fn default_token_path() -> PathBuf {
    if let Ok(executable) = env::current_exe() {
        if let Some(root) = executable.parent().and_then(Path::parent) {
            let beside_install = root.join("data").join("control.token");
            if beside_install.is_file() {
                return beside_install;
            }
        }
    }
    if let Some(local_app_data) = env::var_os("LOCALAPPDATA") {
        return package::runtime_dir(&PathBuf::from(local_app_data))
            .join("data")
            .join("control.token");
    }
    PathBuf::from("data").join("control.token")
}

fn token_path() -> PathBuf {
    env::var_os("JARVIS_TOKEN_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(default_token_path)
}

#[tauri::command]
fn app_package_status() -> package::PackageStatus {
    package::status()
}

/// 자동 시작(StartupTask). `enable` 이 없으면 상태만 본다. 패키지가 아니면 `unpackaged`.
/// 켜기는 Windows 확인 창을 띄울 수 있어 비동기 명령으로 둔다(UI 스레드를 잡지 않게).
#[tauri::command]
async fn startup_task(enable: Option<bool>) -> package::StartupState {
    package::startup_task(enable)
}

/// 마법사를 끝냈다 — 작업 화면을 열고 마법사 창을 닫는다. `setup_state.json` 은 백엔드가 이미 썼다.
///
/// ★ 2026-09-15 F3 리허설에서 잡혔다: 첫 부탁을 눌러도 작업 화면이 **열리지 않았다**(두 판 연속, CDP 목록에도 없음).
///   동기 명령은 메인 스레드에서 돌고, Windows 에서 그 안에서 웹뷰 창을 만들면 교착한다(Tauri 문서의 경고).
///   창을 만들 수 있는 명령(finish_setup · open_setup · focus_workspace)은 async 로 둔다.
#[tauri::command]
async fn finish_setup(app: AppHandle, draft: Option<String>) -> Result<(), String> {
    open_workspace_with(&app, draft.as_deref())?;
    if let Some(window) = app.get_webview_window("setup") {
        let _ = window.close();
    }
    Ok(())
}

/// F2 · G1 — 백엔드에 못 닿을 때 화면의 「다시 시도」. 동봉 백엔드가 죽었으면 다시 켜고 40초까지 기다린다.
/// 사설·개발 설치(동봉 파이썬 없음)는 켤 것이 없어 지금 닿는지만 돌려준다.
#[tauri::command]
async fn retry_backend(app: AppHandle) -> bool {
    let base_url = env::var("JARVIS_URL").unwrap_or_else(|_| DEFAULT_BACKEND_URL.to_string());
    if package::backend_answers(&base_url) {
        return true;
    }
    if let Ok(mut slot) = app.state::<BundledBackend>().0.lock() {
        if let Some(child) = slot.as_mut() {
            if matches!(child.try_wait(), Ok(Some(_))) {
                *slot = None; // 죽은 자식은 버린다
            }
        }
        if slot.is_none() {
            *slot = package::start_bundled_backend(&base_url);
        }
    }
    let deadline = Instant::now() + Duration::from_secs(40);
    while Instant::now() < deadline {
        if package::backend_answers(&base_url) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

/// 동봉 백엔드가 죽으면 **스스로** 다시 켠다 (2026-09-24).
///
/// 노트북 포장본에서 백엔드가 음성 로딩 중 비정상 종료(0xc0000005)했는데 창은 살아 있고 아무도 다시 안 켜서,
/// 사용자에게는 「너무 느리다」로 보였다(실제로는 대답할 프로세스가 없었다). 「다시 시도」 단추(`retry_backend`)는
/// 화면이 백엔드를 못 찾았다고 알아챌 때만 뜬다. 그래서 3초마다 자식이 끝났는지 보고, 끝났으면 다시 켠다.
/// 같은 고장이 되풀이되면 무한히 되살리지 않는다 — 10분에 5번까지(그 뒤엔 「다시 시도」로 사람이 결정).
fn watch_bundled_backend(app: AppHandle, base_url: String) {
    std::thread::spawn(move || {
        let mut restarts: Vec<Instant> = Vec::new();
        loop {
            std::thread::sleep(Duration::from_secs(3));
            let state = app.state::<BundledBackend>();
            let Ok(mut slot) = state.0.lock() else { continue };
            let dead = match slot.as_mut() {
                Some(child) => matches!(child.try_wait(), Ok(Some(_))),
                None => !package::backend_answers(&base_url),
            };
            if !dead {
                continue;
            }
            restarts.retain(|at| at.elapsed() < Duration::from_secs(600));
            if restarts.len() >= 5 {
                *slot = None;
                continue;
            }
            restarts.push(Instant::now());
            *slot = package::start_bundled_backend(&base_url);
        }
    });
}

/// 설정 > 「첫 실행 다시 하기」. 백엔드가 파일을 옆으로 옮긴 뒤 부른다.
#[tauri::command]
async fn open_setup(app: AppHandle) -> Result<(), String> {
    open_setup_window(&app)
}

/// 창 제목 표시줄을 앱 바탕색에 맞춘다 (2026-09-15 제품 요청: 「제목 표시줄 색이 달라서 거슬린다」).
///
/// Windows 기본 어두운 제목 표시줄은 #202020 이라 앱 바탕(사이드바 `--surface-1` #0e0d0b)과 띠가 갈렸다.
/// Windows 11(22000+)의 DWM 제목 표시줄 색 지정으로 같은 흑연을 칠한다. Windows 10 은 이 속성을 모르고
/// 실패를 돌려주는데, 그러면 그냥 기본색으로 둔다(창은 멀쩡하다).
#[cfg(target_os = "windows")]
fn paint_title_bar(window: &tauri::WebviewWindow) {
    use windows_sys::Win32::Graphics::Dwm::{DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR};
    let Ok(hwnd) = window.hwnd() else { return };
    // COLORREF 는 0x00BBGGRR.
    let caption: u32 = 0x000B_0D0E; // #0e0d0b — tokens.css --surface-1
    let text: u32 = 0x00C8_D1D6; // #d6d1c8 — --text-2
    for (attribute, value) in [(DWMWA_CAPTION_COLOR, caption), (DWMWA_BORDER_COLOR, caption), (DWMWA_TEXT_COLOR, text)] {
        unsafe {
            DwmSetWindowAttribute(hwnd.0 as _, attribute as _, &value as *const u32 as *const _, std::mem::size_of::<u32>() as u32);
        }
    }
}

#[cfg(not(target_os = "windows"))]
fn paint_title_bar(_window: &tauri::WebviewWindow) {}

/// 앱 바탕과 같은 흑연 — 창이 뜨는 첫 순간(웹뷰가 그리기 전)에 파란 기가 비치지 않게.
const WINDOW_GROUND: tauri::webview::Color = tauri::webview::Color(14, 13, 11, 255);

fn open_setup_window(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("setup") {
        let _ = window.unminimize();
        window.show().map_err(|error| error.to_string())?;
        return window.set_focus().map_err(|error| error.to_string());
    }
    let window = WebviewWindowBuilder::new(app, "setup", WebviewUrl::App("index.html?mode=setup".into()))
        .title("Sonjari 시작하기")
        .inner_size(1180.0, 780.0)
        .min_inner_size(900.0, 640.0)
        .resizable(true)
        .decorations(true)
        .background_color(WINDOW_GROUND)
        .build()
        .map_err(|error| error.to_string())?;
    if let Some(icon) = app.default_window_icon() {
        let _ = window.set_icon(icon.clone());
    }
    paint_title_bar(&window);
    window.center().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

#[tauri::command]
fn backend_bootstrap() -> Result<BackendBootstrap, String> {
    if cfg!(feature = "pilot") {
        return Ok(BackendBootstrap {
            base_url: "pilot://local".into(),
            control_token: String::new(),
            mode: "pilot".into(),
        });
    }
    let base_url = env::var("JARVIS_URL").unwrap_or_else(|_| DEFAULT_BACKEND_URL.to_string());
    let token_path = token_path();
    let control_token = fs::read_to_string(&token_path)
        .map_err(|error| {
            // ★ 2026-10-01 베타 테스터 PC: 예전에 깐 위성이 같은 포트(8091)를 먼저 잡고 있었다. 동봉 본체는 「누가 이미 답한다」며
            //   안 켜졌고(package::start_bundled_backend), 화면은 「제어 토큰을 읽지 못했습니다 (os error 3)」만 띄웠다 —
            //   「다시 시도」로는 영영 안 풀리는데 이유를 몰랐다. 토큰이 없는데 그 포트에서 누가 답하면 그 사실을 말한다.
            //   (이 문구에는 「os error」를 넣지 않는다 — 화면이 「곧 생길 토큰」으로 알고 90초를 기다리지 않게.)
            if error.kind() == std::io::ErrorKind::NotFound && package::backend_answers(&base_url) {
                return package::port_taken_message(&base_url);
            }
            format!(
                "제어 토큰을 읽지 못했습니다 ({}): {error}",
                token_path.display()
            )
        })?
        .trim_start_matches('\u{feff}')
        .trim()
        .to_string();
    if control_token.is_empty() {
        return Err("제어 토큰 파일이 비어 있습니다.".into());
    }
    Ok(BackendBootstrap {
        base_url,
        control_token,
        mode: "server".into(),
    })
}

#[derive(Default)]
struct PilotState {
    children: Mutex<HashMap<String, u32>>,
}

#[derive(Default, Deserialize, Serialize)]
struct PilotConfig {
    api_key_file: String,
}

#[derive(Serialize)]
struct PilotAuthStatus {
    ready: bool,
    method: String,
    key_file_name: String,
    claude_found: bool,
    message: String,
}

#[derive(Deserialize)]
struct PilotHistoryMessage {
    role: String,
    content: String,
}

#[derive(Deserialize)]
struct PilotAttachment {
    name: String,
    mime_type: String,
    data_base64: String,
}

#[derive(Deserialize)]
struct PilotChatRequest {
    job_id: String,
    prompt: String,
    session_id: String,
    history: Vec<PilotHistoryMessage>,
    attachments: Vec<PilotAttachment>,
    workspace_mode: String,
    code_workspace: String,
    #[serde(default)]
    resume_session_id: String,
    #[serde(default)]
    model: String,
}

#[derive(Serialize)]
struct PilotChatResult {
    answer: String,
    cost_usd: Option<f64>,
    duration_ms: u128,
    session_id: String,
    model: String,
    thinking_tokens: u64,
    cache_read_tokens: u64,
    cache_creation_tokens: u64,
    outputs: Vec<PilotOutput>,
    trace: Vec<PilotToolStep>,
}

#[derive(Clone, Serialize)]
struct PilotStreamEvent {
    job_id: String,
    kind: String,
    delta: String,
    step: u32,
    tool: String,
    message: String,
    evidence: Value,
}

#[derive(Serialize)]
struct PilotToolStep {
    step: u32,
    tool: String,
    ok: bool,
    status: String,
    error: String,
    kind: String,
    title: String,
    at: f64,
    took_ms: u64,
    truncated: bool,
    arguments: Value,
    payload: Value,
}

#[derive(Serialize)]
struct PilotOutput {
    step: u32,
    tool: String,
    name: String,
    path: String,
    bytes: u64,
    kind: String,
    exists: bool,
    viewable: bool,
}

#[derive(Serialize)]
struct PilotOutputBytes {
    data_base64: String,
    mime_type: String,
}

#[derive(Serialize)]
struct PilotOutputPreview {
    name: String,
    path: String,
    format: String,
    text: String,
    readable: bool,
}

#[derive(Default, Deserialize, Serialize)]
struct PilotMemory {
    entries: Vec<PilotMemoryEntry>,
}

#[derive(Deserialize, Serialize)]
struct PilotMemoryEntry {
    at: u64,
    session_id: String,
    user: String,
    assistant: String,
}

enum ClaudeCommand {
    Node { cli: PathBuf },
    Native { exe: PathBuf },
}

fn pilot_data_dir() -> Result<PathBuf, String> {
    let root = env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA 환경 변수가 없습니다.")?;
    Ok(PathBuf::from(root).join("Alture").join("JarvisCliPilot"))
}

fn pilot_config_path() -> Result<PathBuf, String> {
    Ok(pilot_data_dir()?.join("pilot-config.json"))
}

fn read_pilot_config() -> PilotConfig {
    pilot_config_path()
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn write_pilot_config(config: &PilotConfig) -> Result<(), String> {
    let path = pilot_config_path()?;
    let parent = path.parent().ok_or("설정 폴더를 정하지 못했습니다.")?;
    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    let text = serde_json::to_string_pretty(config).map_err(|error| error.to_string())?;
    fs::write(path, text).map_err(|error| error.to_string())
}

fn read_api_key(path: &Path) -> Result<String, String> {
    let text = fs::read_to_string(path).map_err(|error| {
        format!(
            "API 키 파일을 읽지 못했습니다 ({}): {error}",
            path.display()
        )
    })?;
    let mut keys = Vec::new();
    for (start, _) in text.match_indices("sk-ant-") {
        let key: String = text[start..]
            .chars()
            .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_'))
            .collect();
        if key.len() >= 40 && !keys.contains(&key) {
            keys.push(key);
        }
    }
    match keys.len() {
        1 => Ok(keys.remove(0)),
        0 => Err("파일에서 Anthropic API 키를 찾지 못했습니다.".into()),
        _ => Err(
            "서로 다른 Anthropic API 키가 여러 개 있습니다. 키 하나만 든 파일을 선택해 주세요."
                .into(),
        ),
    }
}

fn find_claude() -> Option<ClaudeCommand> {
    if let Some(exe) = env::var_os("JARVIS_CLAUDE_EXE").map(PathBuf::from) {
        if exe.is_file() {
            return Some(ClaudeCommand::Native { exe });
        }
    }
    if let Some(appdata) = env::var_os("APPDATA") {
        let npm_root = PathBuf::from(appdata).join("npm");
        let native = npm_root
            .join("node_modules")
            .join("@anthropic-ai")
            .join("claude-code")
            .join("bin")
            .join("claude.exe");
        if native.is_file() {
            return Some(ClaudeCommand::Native { exe: native });
        }
        let cli = npm_root
            .join("node_modules")
            .join("@anthropic-ai")
            .join("claude-code")
            .join("cli.js");
        if cli.is_file() {
            return Some(ClaudeCommand::Node { cli });
        }
    }
    if let Some(profile) = env::var_os("USERPROFILE") {
        for relative in [
            r".local\bin\claude.exe",
            r"AppData\Local\Programs\claude\claude.exe",
        ] {
            let exe = PathBuf::from(&profile).join(relative);
            if exe.is_file() {
                return Some(ClaudeCommand::Native { exe });
            }
        }
    }
    None
}

fn claude_process(command: &ClaudeCommand) -> Command {
    let mut process = match command {
        ClaudeCommand::Node { cli } => {
            let mut process = Command::new("node.exe");
            process.arg(cli);
            process
        }
        ClaudeCommand::Native { exe } => Command::new(exe),
    };
    #[cfg(target_os = "windows")]
    process.creation_flags(CREATE_NO_WINDOW);
    process
}

fn oauth_ready(command: &ClaudeCommand) -> bool {
    let output = claude_process(command)
        .args(["auth", "status", "--json"])
        .stderr(Stdio::null())
        .output();
    output
        .ok()
        .and_then(|value| serde_json::from_slice::<Value>(&value.stdout).ok())
        .and_then(|value| value.get("loggedIn").and_then(Value::as_bool))
        .unwrap_or(false)
}

#[tauri::command]
fn pilot_auth_status() -> PilotAuthStatus {
    let claude = find_claude();
    let claude_found = claude.is_some();
    let config = read_pilot_config();
    if !config.api_key_file.is_empty() {
        let path = PathBuf::from(&config.api_key_file);
        if read_api_key(&path).is_ok() {
            return PilotAuthStatus {
                ready: claude_found,
                method: "api_key_file".into(),
                key_file_name: path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .unwrap_or("API 키 파일")
                    .into(),
                claude_found,
                message: if claude_found {
                    "API 키 파일이 안전하게 연결되었습니다."
                } else {
                    "Claude Code 설치가 필요합니다."
                }
                .into(),
            };
        }
    }
    let oauth = claude.as_ref().map(oauth_ready).unwrap_or(false);
    PilotAuthStatus {
        ready: oauth,
        method: if oauth { "oauth" } else { "none" }.into(),
        key_file_name: String::new(),
        claude_found,
        message: if oauth {
            "Claude Code OAuth 로그인을 사용합니다."
        } else if claude_found {
            "Anthropic API 키 파일을 연결해 주세요."
        } else {
            "Claude Code가 설치되지 않았습니다. 설치 결과 로그를 확인해 주세요."
        }
        .into(),
    }
}

#[tauri::command]
fn pilot_choose_api_key_file() -> Result<PilotAuthStatus, String> {
    let Some(path) = rfd::FileDialog::new()
        .set_title("Anthropic API 키 파일 선택")
        .add_filter("텍스트 파일", &["txt", "key"])
        .pick_file()
    else {
        return Err("선택을 취소했습니다.".into());
    };
    read_api_key(&path)?;
    write_pilot_config(&PilotConfig {
        api_key_file: path.to_string_lossy().into_owned(),
    })?;
    Ok(pilot_auth_status())
}

#[tauri::command]
fn pilot_clear_api_key() -> Result<PilotAuthStatus, String> {
    write_pilot_config(&PilotConfig::default())?;
    Ok(pilot_auth_status())
}

fn pilot_workspace() -> Result<PathBuf, String> {
    if let Some(path) = env::var_os("JARVIS_PILOT_WORKSPACE").map(PathBuf::from) {
        if path.is_dir() {
            return Ok(path);
        }
    }
    let beside_exe = env::current_exe()
        .map_err(|error| error.to_string())?
        .parent()
        .ok_or("실행 파일 폴더를 찾지 못했습니다.")?
        .join("workspace");
    if beside_exe.is_dir() {
        return Ok(beside_exe);
    }
    Err("손자리 공개 도구 작업공간을 찾지 못했습니다. 다시 설치해 주세요.".into())
}

fn safe_attachment_name(name: &str) -> String {
    Path::new(name)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .unwrap_or("attachment.bin")
        .replace(['\r', '\n'], "_")
}

fn redact_api_keys(value: &str) -> String {
    let mut result = String::with_capacity(value.len());
    let mut rest = value;
    while let Some(start) = rest.find("sk-ant-") {
        result.push_str(&rest[..start]);
        let secret = &rest[start..];
        let length = secret
            .chars()
            .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_'))
            .map(char::len_utf8)
            .sum::<usize>();
        result.push_str("[ANTHROPIC_API_KEY_REDACTED]");
        rest = &secret[length..];
    }
    result.push_str(rest);
    result
}

fn pilot_memory_path() -> Result<PathBuf, String> {
    Ok(pilot_data_dir()?.join("pilot-memory.json"))
}

fn read_pilot_memory() -> PilotMemory {
    pilot_memory_path()
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn memory_context(workspace: &Path) -> String {
    let mut result = String::new();
    if let Some(profile) = env::var_os("USERPROFILE") {
        let global = PathBuf::from(profile).join(".claude").join("CLAUDE.md");
        if let Ok(text) = fs::read_to_string(global) {
            result.push_str("기존 Claude Code 전역 CLAUDE.md 규칙:\n");
            result.push_str(&text.chars().take(120_000).collect::<String>());
            result.push_str("\n\n");
        }
    }
    let profile = workspace.join("MEMORY.md");
    if let Ok(text) = fs::read_to_string(profile) {
        result.push_str("사용자가 확인할 수 있는 장기기억:\n");
        result.push_str(&text.chars().take(12_000).collect::<String>());
        result.push_str("\n\n");
    }
    let memory = read_pilot_memory();
    if !memory.entries.is_empty() {
        result.push_str("다른 새 대화를 포함한 최근 로컬 연속기억:\n");
        for row in memory
            .entries
            .iter()
            .rev()
            .take(40)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
        {
            result.push_str("- 사용자: ");
            result.push_str(&row.user);
            result.push_str("\n  Sonjari: ");
            result.push_str(&row.assistant);
            result.push('\n');
        }
    }
    result
}

fn remember_exchange(request: &PilotChatRequest, answer: &str) -> Result<(), String> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let mut memory = read_pilot_memory();
    memory.entries.push(PilotMemoryEntry {
        at: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
        session_id: request.session_id.clone(),
        user: redact_api_keys(&request.prompt)
            .chars()
            .take(2_000)
            .collect(),
        assistant: redact_api_keys(answer).chars().take(3_000).collect(),
    });
    if memory.entries.len() > 40 {
        memory.entries.drain(0..memory.entries.len() - 40);
    }
    let path = pilot_memory_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let text = serde_json::to_string_pretty(&memory).map_err(|error| error.to_string())?;
    fs::write(path, text).map_err(|error| error.to_string())
}

fn prepare_prompt(
    request: &PilotChatRequest,
    attachment_paths: &[(String, String, PathBuf)],
    memory: &str,
) -> String {
    let mut text = String::from(
        "당신은 사용자 PC에서 실행되는 Sonjari 파일럿입니다. 작업공간의 CLAUDE.md를 최우선으로 지키세요.\n\n",
    );
    if !memory.trim().is_empty() {
        text.push_str(memory);
        text.push_str("\n\n");
    }
    if !request.history.is_empty() {
        text.push_str("최근 대화:\n");
        let mut used = 0usize;
        for row in &request.history {
            let content: String = row.content.chars().take(120_000).collect();
            used += content.chars().count();
            if used > 2_800_000 {
                break;
            }
            text.push_str(if row.role == "assistant" {
                "Sonjari: "
            } else {
                "사용자: "
            });
            text.push_str(&content);
            text.push('\n');
        }
        text.push('\n');
    }
    if !attachment_paths.is_empty() {
        text.push_str("첨부 파일(사용자가 이 작업을 위해 명시적으로 제공함):\n");
        for (name, mime, path) in attachment_paths {
            text.push_str(&format!("- {name} ({mime}): {}\n", path.display()));
        }
        text.push('\n');
    }
    if request.workspace_mode == "code" && !request.code_workspace.trim().is_empty() {
        text.push_str(&format!(
            "허용된 코드 작업 폴더: {}\n\n",
            request.code_workspace
        ));
    }
    text.push_str("현재 요청:\n");
    text.push_str(request.prompt.trim());
    text
}

fn output_snapshot(root: &Path) -> HashMap<PathBuf, (u64, u64)> {
    fn visit(dir: &Path, rows: &mut HashMap<PathBuf, (u64, u64)>) {
        let Ok(entries) = fs::read_dir(dir) else {
            return;
        };
        for entry in entries.flatten().take(2_000) {
            let path = entry.path();
            if path.is_dir() {
                visit(&path, rows);
            } else if let Ok(meta) = entry.metadata() {
                let modified = meta
                    .modified()
                    .ok()
                    .and_then(|value| value.duration_since(std::time::UNIX_EPOCH).ok())
                    .map(|value| value.as_secs())
                    .unwrap_or(0);
                rows.insert(path, (meta.len(), modified));
            }
        }
    }
    let mut rows = HashMap::new();
    visit(root, &mut rows);
    rows
}

fn changed_outputs(root: &Path, before: &HashMap<PathBuf, (u64, u64)>) -> Vec<PathBuf> {
    let allowed = [
        "docx", "xlsx", "pptx", "pdf", "png", "jpg", "jpeg", "txt", "md", "csv",
    ];
    let mut changed: Vec<_> = output_snapshot(root)
        .into_iter()
        .filter(|(path, stamp)| before.get(path) != Some(stamp))
        .filter(|(path, _)| {
            path.extension()
                .and_then(|value| value.to_str())
                .map(|value| allowed.contains(&value.to_ascii_lowercase().as_str()))
                .unwrap_or(false)
        })
        .collect();
    changed.sort_by(|left, right| right.1 .1.cmp(&left.1 .1));
    changed.into_iter().map(|(path, _)| path).collect()
}

/// 답 속 링크를 **기본 브라우저**로 연다 (2026-10-01 밤 베타 테스터: 「링크 눌러도 안 된다」).
/// 손자리 크롬 새 탭으로 열던 길은 무대 모드(크롬이 화면 밖)·크롬이 아직 안 뜬 때 아무것도 안 보였고,
/// 대신 부르던 `window.open` 은 데스크톱 앱 안에서 아무 일도 안 한다. 사람이 보려고 누른 링크라 늘 보이는 곳에 연다.
/// http·https 만 받는다 — 다른 스킴(file:·명령 줄)은 열지 않는다.
#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let url = url.trim().to_string();
    let lower = url.to_ascii_lowercase();
    if !(lower.starts_with("http://") || lower.starts_with("https://")) {
        return Err("http·https 주소만 엽니다".into());
    }
    if url.chars().any(|c| c.is_control() || c == '"' || c == ' ') {
        return Err("주소에 쓸 수 없는 글자가 있습니다".into());
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        Command::new("rundll32.exe")
            .args(["url.dll,FileProtocolHandler", &url])
            .creation_flags(0x0800_0000)
            .spawn()
            .map(|_| ())
            .map_err(|error| error.to_string())
    }
    #[cfg(not(target_os = "windows"))]
    {
        Command::new("xdg-open").arg(&url).spawn().map(|_| ()).map_err(|error| error.to_string())
    }
}

fn open_outputs(paths: &[PathBuf]) {
    for path in paths.iter().take(3) {
        #[cfg(target_os = "windows")]
        {
            let _ = Command::new("explorer.exe").arg(path).spawn();
        }
    }
}

fn output_kind(path: &Path) -> String {
    match path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "png" | "jpg" | "jpeg" | "gif" | "webp" => "image",
        _ => "file",
    }
    .into()
}

fn output_mime(path: &Path) -> String {
    match path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "pdf" => "application/pdf",
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt" | "md" | "csv" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
    .into()
}

fn validate_output_path(raw: &str) -> Result<PathBuf, String> {
    let root = pilot_workspace()?.join("outputs");
    let root = fs::canonicalize(&root).map_err(|_| "산출물 폴더가 아직 없습니다.".to_string())?;
    let candidate =
        fs::canonicalize(raw).map_err(|_| "산출물 파일을 찾지 못했습니다.".to_string())?;
    if !candidate.starts_with(&root) || !candidate.is_file() {
        return Err("Sonjari outputs 폴더 밖의 파일은 이 화면에서 열 수 없습니다.".into());
    }
    Ok(candidate)
}

fn document_python() -> Option<PathBuf> {
    let beside_exe = env::current_exe()
        .ok()?
        .parent()?
        .join("document-runtime")
        .join("Scripts")
        .join("python.exe");
    if beside_exe.is_file() {
        return Some(beside_exe);
    }

    let installed = pilot_data_dir()
        .ok()?
        .join("document-runtime")
        .join("Scripts")
        .join("python.exe");
    installed.is_file().then_some(installed)
}

#[tauri::command]
fn pilot_read_output(path: String) -> Result<PilotOutputBytes, String> {
    let path = validate_output_path(&path)?;
    let bytes = fs::read(&path).map_err(|error| error.to_string())?;
    if bytes.len() > 64 * 1024 * 1024 {
        return Err("64MB보다 큰 파일은 화면 안에서 열 수 없습니다.".into());
    }
    Ok(PilotOutputBytes {
        data_base64: BASE64.encode(bytes),
        mime_type: output_mime(&path),
    })
}

#[tauri::command]
fn pilot_preview_output(path: String) -> Result<PilotOutputPreview, String> {
    let path = validate_output_path(&path)?;
    let format = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("산출물")
        .to_string();
    let text = if matches!(format.as_str(), "txt" | "md" | "csv" | "json" | "log") {
        fs::read_to_string(&path).map_err(|error| error.to_string())?
    } else {
        let Some(python) = document_python() else {
            return Ok(PilotOutputPreview {
                name,
                path: path.to_string_lossy().into_owned(),
                format,
                text: "문서 미리보기 런타임이 설치되지 않았습니다. 파일은 기본 앱으로 열었습니다."
                    .into(),
                readable: false,
            });
        };
        let output = Command::new(python)
            .args(["-c", "from markitdown import MarkItDown; import sys; print(MarkItDown().convert(sys.argv[1]).text_content)"])
            .arg(&path)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdout(Stdio::piped()).stderr(Stdio::null())
            .output().map_err(|error| error.to_string())?;
        if !output.status.success() {
            return Ok(PilotOutputPreview {
                name,
                path: path.to_string_lossy().into_owned(),
                format,
                text: "문서 내용을 텍스트로 펼치지 못했습니다. 파일은 기본 앱으로 열었습니다."
                    .into(),
                readable: false,
            });
        }
        String::from_utf8_lossy(&output.stdout).into_owned()
    };
    Ok(PilotOutputPreview {
        name,
        path: path.to_string_lossy().into_owned(),
        format,
        text: text.chars().take(200_000).collect(),
        readable: true,
    })
}

fn tool_kind(name: &str, arguments: &Value) -> &'static str {
    let lower = name.to_ascii_lowercase();
    if lower.contains("browser") || lower.contains("webfetch") || lower.contains("websearch") {
        "page"
    } else if lower.contains("markitdown") {
        "document"
    } else if lower == "read" {
        let extension = arguments
            .get("file_path")
            .or_else(|| arguments.get("path"))
            .and_then(Value::as_str)
            .and_then(|path| Path::new(path).extension())
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if matches!(
            extension.as_str(),
            "md" | "txt" | "pdf" | "docx" | "xlsx" | "pptx"
        ) {
            "document"
        } else {
            "code"
        }
    } else if matches!(lower.as_str(), "write" | "edit" | "notebookedit") {
        "artifact"
    } else if matches!(lower.as_str(), "glob" | "grep") {
        "files"
    } else {
        "note"
    }
}

fn visible_tool_name(name: &str) -> String {
    name.trim_start_matches("mcp__")
        .replace("__", " · ")
        .replace('_', " ")
}

fn content_text(value: &Value) -> String {
    if let Some(text) = value.as_str() {
        return text.to_string();
    }
    value
        .as_array()
        .map(|rows| {
            rows.iter()
                .filter_map(|row| row.get("text").and_then(Value::as_str))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

fn tool_payload(name: &str, arguments: &Value, result_text: &str) -> Value {
    let lower = name.to_ascii_lowercase();
    if lower.contains("browser") {
        let parsed = serde_json::from_str::<Value>(result_text).ok();
        let url = parsed
            .as_ref()
            .and_then(|value| value.get("url"))
            .and_then(Value::as_str)
            .or_else(|| arguments.get("url").and_then(Value::as_str))
            .unwrap_or("");
        let title = parsed
            .as_ref()
            .and_then(|value| value.get("title"))
            .and_then(Value::as_str)
            .map(str::to_string)
            .unwrap_or_else(|| visible_tool_name(name));
        let elements = parsed
            .as_ref()
            .and_then(|value| value.get("interactive_elements"))
            .cloned()
            .unwrap_or(Value::Null);
        return serde_json::json!({
            "url": url,
            "title": title,
            "text": result_text,
            "elements_raw": elements,
        });
    }
    serde_json::json!({ "text": result_text })
}

fn parse_stream_output(stdout: &[u8]) -> Result<(Value, Vec<PilotToolStep>), String> {
    let text = String::from_utf8_lossy(stdout);
    let mut final_value = None;
    let mut trace = Vec::<PilotToolStep>::new();
    let mut by_id = HashMap::<String, usize>::new();
    let at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs_f64())
        .unwrap_or(0.0);

    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        match value.get("type").and_then(Value::as_str).unwrap_or("") {
            "assistant" => {
                let Some(content) = value
                    .get("message")
                    .and_then(|message| message.get("content"))
                    .and_then(Value::as_array)
                else {
                    continue;
                };
                for block in content {
                    if block.get("type").and_then(Value::as_str) != Some("tool_use") {
                        continue;
                    }
                    let id = block
                        .get("id")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    let name = block
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("tool")
                        .to_string();
                    let arguments = block
                        .get("input")
                        .cloned()
                        .unwrap_or_else(|| serde_json::json!({}));
                    let index = trace.len();
                    trace.push(PilotToolStep {
                        step: (index + 1) as u32,
                        tool: name.clone(),
                        ok: true,
                        status: "running".into(),
                        error: String::new(),
                        kind: tool_kind(&name, &arguments).into(),
                        title: visible_tool_name(&name),
                        at: at + index as f64 / 1_000.0,
                        took_ms: 0,
                        truncated: false,
                        arguments,
                        payload: serde_json::json!({ "text": "도구 실행 결과를 기다리는 중입니다." }),
                    });
                    if !id.is_empty() {
                        by_id.insert(id, index);
                    }
                }
            }
            "user" => {
                let Some(content) = value
                    .get("message")
                    .and_then(|message| message.get("content"))
                    .and_then(Value::as_array)
                else {
                    continue;
                };
                for block in content {
                    if block.get("type").and_then(Value::as_str) != Some("tool_result") {
                        continue;
                    }
                    let Some(index) = block
                        .get("tool_use_id")
                        .and_then(Value::as_str)
                        .and_then(|id| by_id.get(id))
                        .copied()
                    else {
                        continue;
                    };
                    let full_text = content_text(block.get("content").unwrap_or(&Value::Null));
                    let character_count = full_text.chars().count();
                    let result_text: String = full_text.chars().take(120_000).collect();
                    let failed = block
                        .get("is_error")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    let arguments = trace[index].arguments.clone();
                    let name = trace[index].tool.clone();
                    trace[index].ok = !failed;
                    trace[index].status = if failed { "failed" } else { "completed" }.into();
                    trace[index].error = if failed {
                        result_text.chars().take(2_000).collect()
                    } else {
                        String::new()
                    };
                    trace[index].truncated = character_count > 120_000;
                    trace[index].payload = tool_payload(&name, &arguments, &result_text);
                }
            }
            "result" => final_value = Some(value),
            _ => {}
        }
    }

    let final_value = final_value.ok_or("Claude의 최종 응답 행을 찾지 못했습니다.")?;
    Ok((final_value, trace))
}

fn selected_pilot_model(requested: &str) -> &'static str {
    match requested.trim() {
        "claude-haiku-4-5" => "claude-haiku-4-5",
        "claude-opus-5" => "claude-opus-5",
        _ => "claude-sonnet-5",
    }
}

fn valid_resume_session(value: &str) -> bool {
    let value = value.trim();
    (8..=80).contains(&value.len())
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || character == '-')
}

fn emit_pilot_stream_line(
    app: &AppHandle,
    job_id: &str,
    value: &Value,
    emitted_tools: &mut HashSet<String>,
    step: &mut u32,
    saw_thinking_delta: &mut bool,
) {
    if value.get("type").and_then(Value::as_str) == Some("stream_event") {
        let delta = value
            .get("event")
            .and_then(|event| event.get("delta"));
        if delta.and_then(|row| row.get("type")).and_then(Value::as_str)
            == Some("thinking_delta")
        {
            let thinking = delta
                .and_then(|row| row.get("thinking"))
                .and_then(Value::as_str)
                .unwrap_or("");
            if !thinking.is_empty() {
                *saw_thinking_delta = true;
                let _ = app.emit(
                    "pilot-stream",
                    PilotStreamEvent {
                        job_id: job_id.to_string(),
                        kind: "thinking".into(),
                        delta: thinking.to_string(),
                        step: 0,
                        tool: String::new(),
                        message: String::new(),
                        evidence: serde_json::json!({}),
                    },
                );
            }
        }
        return;
    }
    if value.get("type").and_then(Value::as_str) != Some("assistant") {
        return;
    }
    let Some(content) = value
        .get("message")
        .and_then(|message| message.get("content"))
        .and_then(Value::as_array)
    else {
        return;
    };
    for block in content {
        if block.get("type").and_then(Value::as_str) == Some("thinking") {
            if !*saw_thinking_delta {
                let thinking = block
                    .get("thinking")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if !thinking.is_empty() {
                    let _ = app.emit(
                        "pilot-stream",
                        PilotStreamEvent {
                            job_id: job_id.to_string(),
                            kind: "thinking".into(),
                            delta: thinking.to_string(),
                            step: 0,
                            tool: String::new(),
                            message: String::new(),
                            evidence: serde_json::json!({}),
                        },
                    );
                }
            }
            continue;
        }
        if block.get("type").and_then(Value::as_str) != Some("tool_use") {
            continue;
        }
        let id = block.get("id").and_then(Value::as_str).unwrap_or("");
        if !id.is_empty() && !emitted_tools.insert(id.to_string()) {
            continue;
        }
        *step += 1;
        let name = block
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("tool");
        let evidence = block
            .get("input")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        let _ = app.emit(
            "pilot-stream",
            PilotStreamEvent {
                job_id: job_id.to_string(),
                kind: "tool".into(),
                delta: String::new(),
                step: *step,
                tool: name.to_string(),
                message: format!("{} 실행 중", visible_tool_name(name)),
                evidence,
            },
        );
    }
}

fn usage_number(value: &Value, pointer: &str) -> u64 {
    value.pointer(pointer).and_then(Value::as_u64).unwrap_or(0)
}

fn run_pilot_chat(app: &AppHandle, request: PilotChatRequest) -> Result<PilotChatResult, String> {
    if request.prompt.trim().is_empty() {
        return Err("요청이 비어 있습니다.".into());
    }
    let claude =
        find_claude().ok_or("Claude Code를 찾지 못했습니다. 설치 결과 로그를 확인해 주세요.")?;
    let workspace = pilot_workspace()?;
    let output_root = workspace.join("outputs");
    let outputs_before = output_snapshot(&output_root);
    let config = read_pilot_config();
    let api_key = if config.api_key_file.is_empty() {
        None
    } else {
        Some(read_api_key(Path::new(&config.api_key_file))?)
    };
    if api_key.is_none() && !oauth_ready(&claude) {
        return Err("Anthropic API 키 파일을 연결하거나 Claude Code에 로그인해 주세요.".into());
    }

    let attach_root = pilot_data_dir()?
        .join("workspace")
        .join("attachments")
        .join(&request.job_id);
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
    let resume_session = request.resume_session_id.trim();
    let can_resume = valid_resume_session(resume_session);
    let memory = if can_resume {
        String::new()
    } else {
        memory_context(&workspace)
    };
    let prompt = prepare_prompt(&request, &attachment_paths, &memory);
    let settings = workspace.join(".claude").join("settings.json");
    let mcp = workspace.join(".mcp.json");
    if !settings.is_file() || !mcp.is_file() {
        return Err("손자리 도구 설정 파일이 없습니다. 설치를 복구해 주세요.".into());
    }

    let started = Instant::now();
    let model = selected_pilot_model(&request.model);
    let mut command = claude_process(&claude);
    command
        .current_dir(&workspace)
        .args([
            "-p",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--model",
            model,
            "--effort",
            "high",
            "--max-turns",
            "24",
            "--max-budget-usd",
            "3.00",
            "--permission-mode",
            "auto",
            "--allowedTools",
            "mcp__browser-use__browser_navigate",
            "mcp__browser-use__browser_get_state",
            "mcp__browser-use__browser_screenshot",
            "mcp__browser-use__browser_get_html",
            "mcp__browser-use__browser_click",
            "mcp__browser-use__browser_type",
            "mcp__browser-use__browser_scroll",
            "mcp__browser-use__browser_list_tabs",
            "mcp__browser-use__browser_list_sessions",
            "mcp__browser-use__browser_go_back",
            "mcp__browser-use__browser_switch_tab",
            "mcp__browser-use__browser_close_tab",
            "mcp__browser-use__browser_close_session",
            "mcp__browser-use__browser_close_all",
            "mcp__markitdown__convert_to_markdown",
        ])
        .arg("--mcp-config")
        .arg(&mcp)
        .arg("--strict-mcp-config")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("ANONYMIZED_TELEMETRY", "false")
        .env("BROWSER_USE_CLOUD_SYNC", "false")
        .env("BROWSER_USE_VERSION_CHECK", "false")
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8");
    if can_resume {
        command.arg("--resume").arg(resume_session);
    }
    if request.workspace_mode == "code" && !request.code_workspace.trim().is_empty() {
        let code_path = PathBuf::from(request.code_workspace.trim());
        if !code_path.is_dir() {
            return Err("선택한 Code 작업 폴더가 존재하지 않습니다.".into());
        }
        command.arg("--add-dir").arg(code_path);
    }
    if let Some(key) = api_key.as_ref() {
        command.env("ANTHROPIC_API_KEY", key);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("Claude Code를 시작하지 못했습니다: {error}"))?;
    let pid = child.id();
    app.state::<PilotState>()
        .children
        .lock()
        .map_err(|_| "작업 상태 잠금이 손상되었습니다.".to_string())?
        .insert(request.job_id.clone(), pid);
    if let Some(stdin) = child.stdin.as_mut() {
        stdin
            .write_all(prompt.as_bytes())
            .map_err(|error| error.to_string())?;
    }
    drop(child.stdin.take());
    let stdout = child
        .stdout
        .take()
        .ok_or("Claude Code stdout를 연결하지 못했습니다.")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Claude Code stderr를 연결하지 못했습니다.")?;
    let stderr_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut reader = BufReader::new(stderr);
        let _ = reader.read_to_end(&mut bytes);
        bytes
    });
    let mut stdout_bytes = Vec::new();
    let mut emitted_tools = HashSet::new();
    let mut live_step = 0u32;
    let mut saw_thinking_delta = false;
    for line in BufReader::new(stdout).lines() {
        let line = line.map_err(|error| error.to_string())?;
        stdout_bytes.extend_from_slice(line.as_bytes());
        stdout_bytes.push(b'\n');
        if let Ok(value) = serde_json::from_str::<Value>(&line) {
            emit_pilot_stream_line(
                app,
                &request.job_id,
                &value,
                &mut emitted_tools,
                &mut live_step,
                &mut saw_thinking_delta,
            );
        }
    }
    let status = child.wait().map_err(|error| error.to_string())?;
    let stderr_bytes = stderr_reader.join().unwrap_or_default();
    if let Ok(mut children) = app.state::<PilotState>().children.lock() {
        children.remove(&request.job_id);
    }
    if !status.success() {
        let stderr = String::from_utf8_lossy(&stderr_bytes);
        let short: String = stderr.chars().take(2_000).collect();
        return Err(format!(
            "Claude Code 작업이 실패했습니다 (exit={}). {}",
            status,
            short.trim()
        ));
    }
    let (value, trace) = parse_stream_output(&stdout_bytes)?;
    if value
        .get("is_error")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return Err(value
            .get("result")
            .and_then(Value::as_str)
            .unwrap_or("Claude Code가 오류를 반환했습니다.")
            .into());
    }
    let answer = value
        .get("result")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    if answer.is_empty() {
        return Err("Claude Code가 빈 응답을 반환했습니다.".into());
    }
    remember_exchange(&request, &answer)?;
    let changed = changed_outputs(&output_root, &outputs_before);
    open_outputs(&changed);
    let outputs = changed
        .iter()
        .map(|path| PilotOutput {
            step: 1,
            tool: "claude-code".into(),
            name: path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("산출물")
                .into(),
            path: path.to_string_lossy().into_owned(),
            bytes: fs::metadata(path).map(|value| value.len()).unwrap_or(0),
            kind: output_kind(path),
            exists: path.is_file(),
            viewable: true,
        })
        .collect();
    Ok(PilotChatResult {
        answer,
        cost_usd: value.get("total_cost_usd").and_then(Value::as_f64),
        duration_ms: started.elapsed().as_millis(),
        session_id: value
            .get("session_id")
            .and_then(Value::as_str)
            .unwrap_or(&request.session_id)
            .to_string(),
        model: model.to_string(),
        thinking_tokens: usage_number(&value, "/usage/output_tokens_details/thinking_tokens"),
        cache_read_tokens: usage_number(&value, "/usage/cache_read_input_tokens"),
        cache_creation_tokens: usage_number(&value, "/usage/cache_creation_input_tokens"),
        outputs,
        trace,
    })
}

#[tauri::command]
async fn pilot_chat(app: AppHandle, request: PilotChatRequest) -> Result<PilotChatResult, String> {
    tauri::async_runtime::spawn_blocking(move || run_pilot_chat(&app, request))
        .await
        .map_err(|error| format!("손자리 작업 스레드가 중단되었습니다: {error}"))?
}

fn translate_thinking_locally(text: &str) -> Result<String, String> {
    let text: String = text.chars().take(8_000).collect();
    if text.trim().is_empty() {
        return Ok(String::new());
    }
    let prompt = format!(
        "You are a professional English (en) to Korean (ko-KR) translator. Your goal is to accurately convey the meaning and nuances of the original English text while adhering to Korean grammar, vocabulary, and cultural sensitivities.\nProduce only the Korean translation, without any additional explanations or commentary. Please translate the following English text into Korean:\n\n\n{}",
        text.trim()
    );
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_millis(650))
        .timeout_read(Duration::from_secs(45))
        .timeout_write(Duration::from_secs(5))
        .build();
    let response = agent
        .post("http://127.0.0.1:11434/api/generate")
        .send_json(serde_json::json!({
            "model": "translategemma:4b",
            "prompt": prompt,
            "stream": false,
            "keep_alive": "15m",
            "options": { "temperature": 0, "num_ctx": 8192 }
        }))
        .map_err(|error| format!("로컬 thinking 번역기를 사용할 수 없습니다: {error}"))?;
    let value: Value = response
        .into_json()
        .map_err(|error| format!("로컬 thinking 번역 응답을 읽지 못했습니다: {error}"))?;
    Ok(value
        .get("response")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string())
}

#[tauri::command]
async fn pilot_translate_thinking(text: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || translate_thinking_locally(&text))
        .await
        .map_err(|error| format!("로컬 thinking 번역 작업이 중단되었습니다: {error}"))?
}

#[tauri::command]
fn pilot_cancel(app: AppHandle, job_id: String) -> Result<bool, String> {
    let pid = app
        .state::<PilotState>()
        .children
        .lock()
        .map_err(|_| "작업 상태 잠금이 손상되었습니다.".to_string())?
        .get(&job_id)
        .copied();
    let Some(pid) = pid else {
        return Ok(false);
    };
    #[cfg(target_os = "windows")]
    {
        let status = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .status()
            .map_err(|error| error.to_string())?;
        return Ok(status.success());
    }
    #[cfg(not(target_os = "windows"))]
    Ok(false)
}

#[tauri::command]
fn pick_code_workspace(current_dir: Option<String>) -> Option<String> {
    let mut dialog = rfd::FileDialog::new().set_title("손자리 Code 프로젝트 폴더 선택");
    if let Some(current_dir) = current_dir.filter(|value| !value.trim().is_empty()) {
        let current_path = PathBuf::from(current_dir);
        if current_path.is_dir() {
            dialog = dialog.set_directory(current_path);
        }
    }
    dialog
        .pick_folder()
        .map(|path| path.to_string_lossy().into_owned())
}

/// 브라우저 무대에서 페이지가 파일을 달라고 할 때(2026-09-26) — 크롬의 파일 창은 화면 밖 창에 떠서 안 보이므로
/// 온텔릭이 자기 파일 창을 연다. 고른 경로만 돌려주고, 무대가 그대로 그 입력칸에 넣는다(`/v1/browser/live/files`).
/// ★ async — 파일 창이 닫힐 때까지 기다리는 동안 창의 메인 스레드를 붙들면 안 된다.
#[tauri::command]
async fn pick_upload_files(multiple: bool) -> Vec<String> {
    let dialog = rfd::FileDialog::new().set_title("웹페이지에 올릴 파일 고르기");
    let picked = if multiple {
        dialog.pick_files().unwrap_or_default()
    } else {
        dialog.pick_file().into_iter().collect()
    };
    picked.into_iter().map(|path| path.to_string_lossy().into_owned()).collect()
}

fn mode_size(mode: &str) -> (u32, u32) {
    match mode {
        "panel" => (492, 672),
        "approval" => (492, 442),
        "continuation" => (492, 482),
        // 사람이 화면에서 직접 처리해야 하는 상황 안내. 고를 것이 없어 승인창보다 낮다.
        "attention" => (492, 414),
        _ => (104, 104),
    }
}

#[cfg(target_os = "windows")]
fn primary_work_area() -> Option<(i32, i32, i32, i32)> {
    use std::ffi::c_void;
    use windows_sys::Win32::{
        Foundation::RECT,
        UI::WindowsAndMessaging::{SystemParametersInfoW, SPI_GETWORKAREA},
    };

    let mut area = RECT {
        left: 0,
        top: 0,
        right: 0,
        bottom: 0,
    };
    let ok = unsafe {
        SystemParametersInfoW(
            SPI_GETWORKAREA,
            0,
            (&mut area as *mut RECT).cast::<c_void>(),
            0,
        )
    };
    (ok != 0).then_some((area.left, area.top, area.right, area.bottom))
}

#[cfg(not(target_os = "windows"))]
fn primary_work_area() -> Option<(i32, i32, i32, i32)> {
    None
}

fn place_bottom_right(app: &AppHandle, mode: &str) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or("손자리 창을 찾지 못했습니다.")?;
    window
        .set_always_on_top(true)
        .map_err(|error| error.to_string())?;
    let (width, height) = mode_size(mode);
    window
        .set_size(Size::Logical(tauri::LogicalSize::new(
            width as f64,
            height as f64,
        )))
        .map_err(|error| error.to_string())?;

    if let Some(monitor) = window
        .current_monitor()
        .map_err(|error| error.to_string())?
    {
        let scale = monitor.scale_factor();
        let margin = (18.0 * scale).round() as i32;
        let window_width = (width as f64 * scale).round() as i32;
        let window_height = (height as f64 * scale).round() as i32;
        let origin = monitor.position();
        let size = monitor.size();
        let monitor_bounds = (
            origin.x,
            origin.y,
            origin.x + size.width as i32,
            origin.y + size.height as i32,
        );
        let (left, top, right, bottom) = primary_work_area().unwrap_or(monitor_bounds);
        let x = right - window_width - margin;
        let y = bottom - window_height - margin;
        let x = x.max(left + margin);
        let y = y.max(top + margin);
        window
            .set_position(Position::Physical(PhysicalPosition::new(x, y)))
            .map_err(|error| error.to_string())?;
    }
    window.show().map_err(|error| error.to_string())?;
    Ok(())
}

fn resize_preserving_bottom_right(app: &AppHandle, mode: &str) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or("손자리 창을 찾지 못했습니다.")?;
    window
        .set_always_on_top(true)
        .map_err(|error| error.to_string())?;
    let previous_position = window.outer_position().ok();
    let previous_size = window.outer_size().ok();
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?;
    let (width, height) = mode_size(mode);
    window
        .set_size(Size::Logical(tauri::LogicalSize::new(
            width as f64,
            height as f64,
        )))
        .map_err(|error| error.to_string())?;

    if let (Some(position), Some(size), Some(monitor)) = (previous_position, previous_size, monitor)
    {
        let scale = monitor.scale_factor();
        let new_width = (width as f64 * scale).round() as i32;
        let new_height = (height as f64 * scale).round() as i32;
        let origin = monitor.position();
        let monitor_size = monitor.size();
        let monitor_bounds = (
            origin.x,
            origin.y,
            origin.x + monitor_size.width as i32,
            origin.y + monitor_size.height as i32,
        );
        let work_area = primary_work_area()
            .filter(|area| {
                area.0 >= monitor_bounds.0
                    && area.1 >= monitor_bounds.1
                    && area.2 <= monitor_bounds.2
                    && area.3 <= monitor_bounds.3
            })
            .unwrap_or(monitor_bounds);
        let anchor_x = position.x + size.width as i32;
        let anchor_y = position.y + size.height as i32;
        let max_x = (work_area.2 - new_width).max(work_area.0);
        let max_y = (work_area.3 - new_height).max(work_area.1);
        let x = (anchor_x - new_width).clamp(work_area.0, max_x);
        let y = (anchor_y - new_height).clamp(work_area.1, max_y);
        window
            .set_position(Position::Physical(PhysicalPosition::new(x, y)))
            .map_err(|error| error.to_string())?;
    }
    window.show().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn set_hud_mode(app: AppHandle, mode: String) -> Result<(), String> {
    resize_preserving_bottom_right(&app, &mode)
}

#[tauri::command]
fn start_hud_drag(app: AppHandle) -> Result<(), String> {
    app.get_webview_window("main")
        .ok_or("손자리 창을 찾지 못했습니다.")?
        .start_dragging()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn hide_hud(app: AppHandle) -> Result<(), String> {
    app.get_webview_window("main")
        .ok_or("손자리 창을 찾지 못했습니다.")?
        .hide()
        .map_err(|error| error.to_string())
}

fn open_workspace(app: &AppHandle) -> Result<(), String> {
    open_workspace_with(app, None)
}

fn open_workspace_with(app: &AppHandle, draft: Option<&str>) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("workspace") {
        if let Some(icon) = app.default_window_icon() {
            let _ = window.set_icon(icon.clone());
        }
        window.unminimize().map_err(|error| error.to_string())?;
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
        return Ok(());
    }
    let window_title = if cfg!(feature = "pilot") {
        "Sonjari 파일럿"
    } else {
        "Sonjari"
    };
    let window = WebviewWindowBuilder::new(
        app,
        "workspace",
        WebviewUrl::App(workspace_url(draft).into()),
    )
    .title(window_title)
    .inner_size(1320.0, 840.0)
    // 작업 화면을 옆에 좁게 띄워 두고 쓸 수 있게(인수인계 H2-C, 2026-09-16) — 좁으면 사이드바는 아이콘만, 컴퓨터 칸은 눌렀을 때 덮는다.
    .min_inner_size(420.0, 560.0)
    .resizable(true)
    .decorations(true)
    .transparent(false)
    .background_color(WINDOW_GROUND)
    // ★ 파일 드롭을 **웹뷰가 받게** 한다 (2026-08-23).
    //
    // Tauri 는 기본으로 드래그·드롭을 네이티브에서 가로채고 웹뷰에는 HTML5
    // drop 이벤트를 안 준다. 그래서 작성칸에 파일을 끌어다 놔도 아무 일이
    // 없었다 — 첨부하는 길이 📎 버튼 하나뿐이었다.
    //
    // 끄면 웹뷰가 그대로 받고, 붙여넣기와 **같은 함수**로 흘려보낼 수 있다
    // (`clipboardFiles.filesFromTransfer`). 두 입구가 한 규칙을 쓴다.
    .disable_drag_drop_handler()
    .build()
    .map_err(|error| error.to_string())?;
    if let Some(icon) = app.default_window_icon() {
        let _ = window.set_icon(icon.clone());
    }
    paint_title_bar(&window);
    window.center().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

/// 앱이 켠 백엔드만 끈다. 끄기 전에 기억 복제본을 뜨게 한다 — 강제 종료는 백엔드의 종료 백업을 건너뛴다.
fn stop_bundled_backend(app: &AppHandle) {
    let child = app.state::<BundledBackend>().0.lock().ok().and_then(|mut slot| slot.take());
    let Some(mut child) = child else { return };
    if let Ok(token) = fs::read_to_string(token_path()) {
        let base_url = env::var("JARVIS_URL").unwrap_or_else(|_| DEFAULT_BACKEND_URL.to_string());
        let _ = ureq::AgentBuilder::new()
            .timeout(Duration::from_secs(25))
            .build()
            .post(&format!("{base_url}/v1/backup/now"))
            .set("X-JARVIS-TOKEN", token.trim_start_matches('\u{feff}').trim())
            .set("Content-Type", "application/json")
            .send_string("{}");
    }
    let _ = child.kill();
    let _ = child.wait();
}

/// 마법사의 첫 부탁 칩을 작업 화면 작성칸에 채워 연다. 퍼센트 인코딩은 UTF-8 바이트 단위.
fn workspace_url(draft: Option<&str>) -> String {
    match draft.filter(|text| !text.trim().is_empty()) {
        None => "index.html?mode=workspace".to_string(),
        Some(text) => {
            let encoded: String = text
                .bytes()
                .map(|byte| match byte {
                    b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => (byte as char).to_string(),
                    _ => format!("%{byte:02X}"),
                })
                .collect();
            format!("index.html?mode=workspace&draft={encoded}")
        }
    }
}

/// 사용자가 결정해야 하는 것이 생겼을 때 창을 앞으로 가져온다.
/// 승인은 놓치면 작업이 아무 말 없이 멈춰 있고 5분 뒤 만료된다.
/// ★ 화면이 부르는 명령은 async 로 감싼다 — 창이 없으면 새로 만들기 때문(아래 finish_setup 주석).
#[tauri::command]
async fn focus_workspace(app: AppHandle) -> Result<(), String> {
    focus_workspace_window(app)
}

fn focus_workspace_window(app: AppHandle) -> Result<(), String> {
    // ★ 2026-09-16 밤, 노트북 첫 설치에서 잡혔다: 마법사가 떠 있는데 **작업 화면 창이 두 개 더** 떠서 마법사를 가렸다
    //   (사용자: 「설치 마법사도 없고 갑자기 앱만 뜬다」). 첫 실행 판정은 `setup()` 한 자리에만 있었고, 두 번째 실행
    //   (시작 메뉴·설치 창의 「실행」)·트레이 클릭·트레이 메뉴는 전부 여기로 와서 판정 없이 작업 화면을 만들었다.
    //   첫 실행을 안 끝냈으면 어느 문으로 들어와도 마법사를 앞으로 가져온다.
    if !cfg!(feature = "pilot")
        && app.get_webview_window("workspace").is_none()
        && package::needs_setup(&package::data_dir_from_token(&token_path()))
    {
        return open_setup_window(&app);
    }
    if let Some(window) = app.get_webview_window("workspace") {
        let _ = window.unminimize();
        let _ = window.show();
        window.set_focus().map_err(|error| error.to_string())?;
        return Ok(());
    }
    open_workspace(&app)
}

/// 브라우저 무대 작은 창 (2026-09-24). 바깥 AI(Claude·Codex 가 MCP 로)가 맡긴 일이 브라우저를 쓰는 동안,
/// 화면 오른쪽 아래에 온텔릭 크롬 화면을 작게 띄운다. 크롬 창을 띄우지 않고도 「보인다」.
///
/// ★ **포커스를 절대 가져가지 않는다.** 사람은 Claude 쪽에서 계속 일하는 중이다 — `focused(false)` 로 활성화 없이
///   띄우고(`SW_SHOWNOACTIVATE`), 뒤에서 `show()`·`set_focus()` 를 부르지 않는다(부르면 그 순간 앞창을 뺏는다).
#[tauri::command]
async fn open_stage_mini(app: AppHandle) -> Result<(), String> {
    if app.get_webview_window("stage-mini").is_some() {
        return Ok(());
    }
    let (width, height) = (460.0_f64, 320.0_f64);
    // 뜨기 **전의** 앞창 — 작은 창이 사람 클릭 없이 앞창을 가져가면 여기로 돌려준다.
    #[cfg(target_os = "windows")]
    let previous_foreground = unsafe { windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow() } as isize;
    let mut builder = WebviewWindowBuilder::new(&app, "stage-mini", WebviewUrl::App("index.html?mode=mini".into()))
        .title("Sonjari · 브라우저")
        .inner_size(width, height)
        .min_inner_size(320.0, 220.0)
        .resizable(true)
        .decorations(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .background_color(WINDOW_GROUND);
    if let Ok(Some(monitor)) = app.primary_monitor() {
        let scale = monitor.scale_factor();
        let origin = monitor.position();
        let size = monitor.size();
        // 작업 표시줄(아래 약 48px)을 피해 오른쪽 아래 — 논리 좌표로 준다.
        let x = origin.x as f64 / scale + size.width as f64 / scale - width - 24.0;
        let y = origin.y as f64 / scale + size.height as f64 / scale - height - 96.0;
        builder = builder.position(x.max(0.0), y.max(0.0));
    }
    let window = builder.build().map_err(|error| error.to_string())?;
    if let Some(icon) = app.default_window_icon() {
        let _ = window.set_icon(icon.clone());
    }
    paint_title_bar(&window);
    #[cfg(target_os = "windows")]
    guard_stage_mini_focus(&window, previous_foreground);
    Ok(())
}

/// ★ 2026-09-26 부산 노트북: `focused(false)` 인데도 작은 창이 **한 판에 한 번** 앞창을 가져갔다(웹뷰가 뜨며 초점을 쥔다).
/// 3초 동안 지켜보다가 사람 클릭 없이 작은 창이 앞창이 되면 원래 창에 돌려준다. 이 순간엔 우리 프로세스가 앞창이라 윈도우가
/// 돌려주기를 막지 않는다(백엔드 파이썬 감시기가 크롬에 대해 실패하는 이유 — 앞창 권한 — 가 여기엔 없다).
#[cfg(target_os = "windows")]
fn guard_stage_mini_focus(window: &tauri::WebviewWindow, previous: isize) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, IsWindow, SetForegroundWindow};
    let Ok(mini) = window.hwnd() else { return };
    let mini = mini.0 as isize;
    if previous == 0 || previous == mini {
        return;
    }
    std::thread::spawn(move || {
        for _ in 0..30 {
            std::thread::sleep(std::time::Duration::from_millis(100));
            let clicking = unsafe { GetAsyncKeyState(0x01) } as u16 & 0x8000 != 0;
            if clicking {
                return; // 사람이 누르는 중 — 사람의 선택이다
            }
            let foreground = unsafe { GetForegroundWindow() } as isize;
            if foreground == mini && unsafe { IsWindow(previous as _) } != 0 {
                unsafe { SetForegroundWindow(previous as _) };
                return;
            }
        }
    });
}

/// ★ 콜드스타트 크롬의 앞창 줄다리기 (2026-09-26).
///
/// 화면 밖 크롬도 처음 뜰 때 앞창(키보드)을 몇 초 쥔다 — 노트북 실측 2.7~7.2초, 그 사이 친 글자는 안 보이는
/// 크롬으로 간다. 백엔드 감시(0.1초)가 돌려줘도 크롬이 다시 쥔다(138번 주고받음). 시작 플래그는 크롬이 자기를 다시
/// 띄워 손자에게 안 간다. 남은 문은 `LockSetForegroundWindow` 인데 **앞에 있는 프로세스만** 걸 수 있다 — 백엔드는
/// 못 걸고 온텔릭 창은 건다. 사람이 메시지를 보낸 순간은 온텔릭이 앞이다. 잠금은 사람이 다른 창을 누르거나 Alt 를
/// 누르면 윈도우가 스스로 푼다 — 사람의 전환은 막지 않는다. 앞이 아니면 아무것도 안 한다.
static FOREGROUND_HOLD: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

#[cfg(target_os = "windows")]
fn we_are_foreground() -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(GetForegroundWindow(), &mut pid) };
    pid == std::process::id()
}

#[tauri::command]
fn hold_foreground(ms: u64) -> bool {
    #[cfg(target_os = "windows")]
    {
        use std::sync::atomic::Ordering;
        use windows_sys::Win32::UI::WindowsAndMessaging::{LockSetForegroundWindow, LSFW_LOCK, LSFW_UNLOCK};
        if !we_are_foreground() {
            return false;
        }
        if unsafe { LockSetForegroundWindow(LSFW_LOCK) } == 0 {
            return false;
        }
        let generation = FOREGROUND_HOLD.fetch_add(1, Ordering::SeqCst) + 1;
        let ms = ms.clamp(1_000, 30_000);
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(ms));
            // 그 사이 새로 잡았으면 그쪽 타이머가 푼다.
            if FOREGROUND_HOLD.load(Ordering::SeqCst) == generation {
                unsafe { LockSetForegroundWindow(LSFW_UNLOCK) };
            }
        });
        true
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = ms;
        false
    }
}

/// 사람이 「크롬 창 보기」를 누를 때 — 잠가 둔 채면 크롬이 앞으로 못 온다.
#[tauri::command]
fn release_foreground() {
    #[cfg(target_os = "windows")]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{LockSetForegroundWindow, LSFW_UNLOCK};
        FOREGROUND_HOLD.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        unsafe { LockSetForegroundWindow(LSFW_UNLOCK) };
    }
}

#[tauri::command]
fn close_stage_mini(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("stage-mini") {
        window.close().map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn minimize_workspace(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("workspace") {
        window.minimize().map_err(|error| error.to_string())?;
    }
    place_bottom_right(&app, "panel")?;
    Ok(())
}

pub fn run() {
    // WebView2 가 없으면 하얀 창 대신 한국어 안내(2026-09-29). 사람이 설치하러 가면 여기서 끝낸다.
    if webview_check::guide_if_missing("손자리") {
        return;
    }
    tauri::Builder::default()
        .manage(PilotState::default())
        .manage(BundledBackend::default())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // 두 번째로 실행하면(작업 표시줄에서 다시 누르거나 스크립트로 띄우거나)
            // 창을 하나 더 만들지 말고 있는 창을 앞으로 가져온다. 인자는 더 이상
            // 보지 않는다 — 창이 하나뿐이라 갈래가 없다.
            // ★ 2026-09-20: 「두 번째 실행 뒤 창이 160×28 로 최소화된다」는 시험 결과는 **사람의 클릭**이었다
            //   (최소화 순간 GetLastInputInfo 가 16~31ms — 시험 창이 쓰던 크롬 위로 떠서 사람이 내렸다. 대조군
            //   WinForms 창도 똑같이 내려갔다). 그걸 고치려고 넣었던 「0.75초 뒤 최소화면 다시 복원」은 사람이
            //   내린 창을 도로 띄워서 되돌렸다. 창 상태 시험은 입력 기록(GetLastInputInfo)을 같이 남길 것.
            let _ = focus_workspace_window(app.clone());
        }))
        .setup(|app| {
            // 설치 파일에 실린 백엔드가 있으면 켠다(W1-7). 사설·개발 설치는 작업 스케줄러가 켜 두므로 건너뛴다.
            if !cfg!(feature = "pilot") {
                let base_url = env::var("JARVIS_URL").unwrap_or_else(|_| DEFAULT_BACKEND_URL.to_string());
                if let Some(child) = package::start_bundled_backend(&base_url) {
                    if let Ok(mut slot) = app.state::<BundledBackend>().0.lock() {
                        *slot = Some(child);
                    }
                    let deadline = Instant::now() + Duration::from_secs(40);
                    while Instant::now() < deadline && !package::backend_answers(&base_url) {
                        std::thread::sleep(Duration::from_millis(300));
                    }
                    watch_bundled_backend(app.handle().clone(), base_url.clone());
                }
            }
            // 메뉴에서 "음성 HUD 보기"를 뺐다. 오브 창 자체가 없어졌기 때문이다 —
            // 마이크는 전체화면 작성창 안에 있고 F9 는 창과 무관하게 동작한다.
            let workspace = MenuItemBuilder::with_id("workspace", "손자리 열기").build(app)?;
            // W3: 설정은 작업 화면 안의 겹 화면이다. 창을 앞으로 가져온 뒤 화면에 열라고 알린다.
            let settings = MenuItemBuilder::with_id("settings", "설정").build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "종료").build(app)?;
            let menu = MenuBuilder::new(app).items(&[&workspace, &settings, &quit]).build()?;
            let tray_title = if cfg!(feature = "pilot") {
                "Sonjari 파일럿"
            } else {
                "Sonjari"
            };
            let mut tray = TrayIconBuilder::with_id("jarvis")
                .tooltip(tray_title)
                .menu(&menu)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "workspace" => {
                        let _ = focus_workspace_window(app.clone());
                    }
                    "settings" => {
                        let _ = focus_workspace_window(app.clone());
                        let _ = app.emit_to("workspace", "open-settings", ());
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let _ = focus_workspace_window(tray.app_handle().clone());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            let tray = tray.build(app)?;
            // 트레이 = 상태 표시등(로고 A). 창을 닫아도 색·움직임으로 상태를 말한다 — tray_status.rs.
            if !cfg!(feature = "pilot") {
                let base_url = env::var("JARVIS_URL").unwrap_or_else(|_| DEFAULT_BACKEND_URL.to_string());
                if let Some(port) = package::port_of(&base_url) {
                    tray_status::spawn(tray, port, tray_title);
                }
            }
            // ★ 2026-08-06 사용자 결정: 창 하나로 합친다.
            //
            // `tauri.conf.json` 의 `windows` 가 **비어 있는 것이 맞다.** 예전에는
            // 거기에 104x104 투명 오브 창이 있었다. 그걸 `visible: false` 로만 두는
            // 것으로는 안 됐다 — 창은 안 보여도 그 안의 React 는 계속 돌고,
            // `useJarvis` 가 `set_hud_mode` 를 불러 **스스로를 다시 띄웠다**(실측:
            // 숨긴 뒤에도 오브가 화면에 그대로 있었고 웹뷰가 코어 33%를 계속 썼다).
            // 그래서 창 자체를 만들지 않는다.
            //
            // 작은 오브 팝업은 없앤다. 오늘 나온 문제가 전부 그것 때문이었다 —
            // 말한 답이 구석 팝업으로 새고, 기억이 둘로 갈라지고(office-main 94개
            // 대 jarvis-* 14개), 가만히 있는데도 코어 절반을 태웠다(투명+항상 위
            // 창의 backdrop-filter). 승인·계속진행 카드는 전체화면으로 옮겼다.
            //
            // 트레이 아이콘은 남는다 — 창을 닫아도 자비스를 다시 부를 길은 있어야 한다.
            // ★ 첫 실행 판정 (W2). 마법사는 `?mode=setup` 으로만 열렸고 앱 어디서도 여는 길이
            //   없었다. 백엔드 데이터 폴더(토큰 파일 옆)에 `setup_state.json` 이 없으면 마법사부터.
            if !cfg!(feature = "pilot") && package::needs_setup(&package::data_dir_from_token(&token_path())) {
                open_setup_window(app.handle()).map_err(std::io::Error::other)?;
            } else {
                open_workspace(app.handle()).map_err(std::io::Error::other)?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_bootstrap,
            app_package_status,
            startup_task,
            retry_backend,
            finish_setup,
            open_setup,
            set_hud_mode,
            start_hud_drag,
            hide_hud,
            minimize_workspace,
            focus_workspace,
            open_stage_mini,
            close_stage_mini,
            open_external_url,
            hold_foreground,
            release_foreground,
            pick_upload_files,
            pick_code_workspace,
            pilot_auth_status,
            pilot_choose_api_key_file,
            pilot_clear_api_key,
            pilot_chat,
            pilot_translate_thinking,
            pilot_cancel,
            pilot_read_output,
            pilot_preview_output
        ])
        .build(tauri::generate_context!())
        .expect("Sonjari HUD failed to start")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                stop_bundled_backend(app);
            }
        });
}
