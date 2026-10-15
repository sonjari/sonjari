//! 스토어 패키지(MSIX)로 돌 때만 달라지는 것 (W1·W2, 2026-09-15).
//!
//! - **자동 시작**: 작업 스케줄러(`RoboMetaFit-*`) 대신 매니페스트의 `desktop:StartupTask`.
//!   Windows 는 앱이 스스로 켜지 못하게 막는다 — 사용자가 마법사에서 누른 순간 `RequestEnableAsync`
//!   가 확인 창을 띄우고, 사용자가 작업 관리자에서 끈 것(`DisabledByUser`)은 앱이 다시 못 켠다.
//! - **첫 실행 판정**: `data/setup_state.json` 이 없으면 작업 화면 대신 마법사 창을 연다.
//!
//! 패키지가 아니면(개발·사설 설치) 자동 시작은 `unpackaged` 를 돌려주고 기존 스크립트 경로를 쓴다.

use serde::Serialize;
use std::{
    env,
    path::{Path, PathBuf},
};

/// 매니페스트 `desktop:StartupTask TaskId` 와 같은 값이어야 한다(packaging/msix/AppxManifest).
pub const STARTUP_TASK_ID: &str = "OntelicStartup";
pub const SETUP_STATE_FILE: &str = "setup_state.json";

#[derive(Serialize, Clone)]
pub struct PackageStatus {
    pub packaged: bool,
    pub full_name: String,
}

#[cfg(target_os = "windows")]
pub fn package_full_name() -> String {
    use windows::Win32::Foundation::{APPMODEL_ERROR_NO_PACKAGE, ERROR_INSUFFICIENT_BUFFER};
    use windows::Win32::Storage::Packaging::Appx::GetCurrentPackageFullName;
    let mut length: u32 = 0;
    // SAFETY: 길이만 묻는 첫 호출은 버퍼 없이 부른다(문서화된 사용법).
    let code = unsafe { GetCurrentPackageFullName(&mut length, None) };
    if code == APPMODEL_ERROR_NO_PACKAGE || code != ERROR_INSUFFICIENT_BUFFER || length == 0 {
        return String::new();
    }
    let mut buffer = vec![0u16; length as usize];
    // SAFETY: 위에서 받은 길이만큼 버퍼를 잡았다.
    let code = unsafe { GetCurrentPackageFullName(&mut length, Some(windows::core::PWSTR(buffer.as_mut_ptr()))) };
    if code.0 != 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buffer[..(length as usize).saturating_sub(1)])
}

#[cfg(not(target_os = "windows"))]
pub fn package_full_name() -> String {
    String::new()
}

pub fn status() -> PackageStatus {
    let full_name = package_full_name();
    PackageStatus { packaged: !full_name.is_empty(), full_name }
}

#[derive(Serialize)]
pub struct StartupState {
    /// unpackaged · disabled · disabled_by_user · enabled · disabled_by_policy · enabled_by_policy · error
    pub state: String,
    pub detail: String,
}

fn state_name(value: i32) -> &'static str {
    match value {
        0 => "disabled",
        1 => "disabled_by_user",
        2 => "enabled",
        3 => "disabled_by_policy",
        4 => "enabled_by_policy",
        _ => "unknown",
    }
}

#[cfg(target_os = "windows")]
pub fn startup_task(enable: Option<bool>) -> StartupState {
    use windows::ApplicationModel::StartupTask;
    if !status().packaged {
        return StartupState { state: "unpackaged".into(), detail: String::new() };
    }
    let run = || -> windows::core::Result<i32> {
        let task = StartupTask::GetAsync(&windows::core::HSTRING::from(STARTUP_TASK_ID))?.get()?;
        match enable {
            Some(true) => Ok(task.RequestEnableAsync()?.get()?.0),
            Some(false) => {
                task.Disable()?;
                Ok(task.State()?.0)
            }
            None => Ok(task.State()?.0),
        }
    };
    match run() {
        Ok(value) => StartupState { state: state_name(value).into(), detail: String::new() },
        Err(error) => StartupState { state: "error".into(), detail: error.message().to_string() },
    }
}

#[cfg(not(target_os = "windows"))]
pub fn startup_task(_enable: Option<bool>) -> StartupState {
    StartupState { state: "unpackaged".into(), detail: String::new() }
}

/// 설치 파일에 같이 실린 파이썬 백엔드(`<exe 폴더>\backend\python\python.exe`). 개발·사설 설치에는 없다.
pub fn bundled_python() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    let python = exe.parent()?.join("backend").join("python").join("python.exe");
    python.is_file().then_some(python)
}

pub fn port_of(base_url: &str) -> Option<u16> {
    base_url.rsplit(':').next()?.trim_end_matches('/').parse().ok()
}

pub fn backend_answers(base_url: &str) -> bool {
    let Some(port) = port_of(base_url) else { return false };
    std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(400),
    )
    .is_ok()
}

/// 동봉 백엔드를 켠다. 이미 누가 그 포트에서 답하면(사설 설치·개발) 아무것도 안 한다.
/// 패키지 **안** 실행 파일의 자식이라 화면과 같은 파일 보기를 갖는다(MSIX 실측).
pub fn start_bundled_backend(base_url: &str) -> Option<std::process::Child> {
    let python = bundled_python()?;
    if backend_answers(base_url) {
        return None;
    }
    let mut command = bundled_backend_command(&python)?;
    command.stderr(start_log().unwrap_or_else(std::process::Stdio::null));
    if let Some(port) = port_of(base_url) {
        command.env("JARVIS_PORT", port.to_string());
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    command.spawn().ok()
}

fn bundled_backend_command(python: &Path) -> Option<std::process::Command> {
    let mut command = std::process::Command::new(python);
    command
        .args(["-m", "alture_jarvis"])
        .current_dir(python.parent()?.parent()?)
        .env("PYTHONIOENCODING", "utf-8")
        // 포장본의 기본값만 끈다. settings.json에서 사용자가 다시 켤 수 있다.
        .env("JARVIS_VOICE_ENABLED", "0")
        .env("JARVIS_TTS_ENABLED", "0")
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null());
    Some(command)
}

/// 앱 데이터 자리 — `src/alture_jarvis/brand.py::runtime_dir` 와 같은 규칙.
/// 새 설치는 `%LOCALAPPDATA%\Sonjari`. 이미 `AltureJarvis`·`Ontelic` 를 쓰던 PC 는 그 자리를 계속 쓴다(2026-09-29 이름 2단계).
pub const RUNTIME_DIR_NAME: &str = "Sonjari";
pub const LEGACY_RUNTIME_DIR_NAME: &str = "AltureJarvis";
/// 이어 쓸 옛 자리 — 먼저 있는 것을 쓴다(brand.py `LEGACY_RUNTIME_DIR_NAMES` 와 같은 순서).
pub const LEGACY_RUNTIME_DIR_NAMES: [&str; 2] = [LEGACY_RUNTIME_DIR_NAME, "Ontelic"];

pub fn runtime_dir(local_app_data: &Path) -> PathBuf {
    LEGACY_RUNTIME_DIR_NAMES
        .iter()
        .map(|name| local_app_data.join(name))
        .find(|legacy| legacy.is_dir())
        .unwrap_or_else(|| local_app_data.join(RUNTIME_DIR_NAME))
}

/// 동봉 백엔드 시작 로그 — `<앱 데이터>\logs\backend_start.log`(백엔드 기본 런타임 자리와 같다).
fn start_log() -> Option<std::process::Stdio> {
    let dir = runtime_dir(&PathBuf::from(env::var_os("LOCALAPPDATA")?)).join("logs");
    std::fs::create_dir_all(&dir).ok()?;
    let file = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("backend_start.log")).ok()?;
    Some(std::process::Stdio::from(file))
}

/// 백엔드 데이터 폴더. 토큰 파일이 사는 곳과 같다 — 둘을 따로 추측하면 갈린다.
pub fn data_dir_from_token(token_path: &Path) -> PathBuf {
    token_path.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("data"))
}

/// 첫 실행인가. `JARVIS_FORCE_SETUP=1` 이면 무조건 마법사(시험·「첫 실행 다시 하기」용).
pub fn needs_setup(data_dir: &Path) -> bool {
    if env::var("JARVIS_FORCE_SETUP").map(|v| v == "1").unwrap_or(false) {
        return true;
    }
    if env::var("JARVIS_SKIP_SETUP").map(|v| v == "1").unwrap_or(false) {
        return false;
    }
    !data_dir.join(SETUP_STATE_FILE).is_file()
}

/// 토큰은 없는데 그 포트에서 **다른 무언가가** 답할 때 사람에게 할 말 (2026-10-01 베타 테스터 PC — 예전에 깐 위성이 8091 을 잡고 있었다).
/// 동봉 본체는 「이미 누가 답한다」며 안 켜지므로(`start_bundled_backend`) 「다시 시도」로는 안 풀린다 — 무엇을 끄면 되는지 말한다.
/// 「os error」를 넣지 않는다: 화면은 그 말이 있으면 「곧 생길 토큰」으로 알고 기다린다(backend.ts `tokenNotYetWritten`).
pub fn port_taken_message(base_url: &str) -> String {
    let port = port_of(base_url).map(|p| p.to_string()).unwrap_or_else(|| base_url.to_string());
    format!(
        "다른 프로그램이 이미 {port} 포트를 쓰고 있어 Sonjari 본체를 켜지 않았습니다. 예전에 깐 Sonjari(위성 포함)나 \
         다른 프로그램이 켜져 있는지 확인해 그것을 끈 뒤 Sonjari 를 다시 열어 주세요. \
         (명령 프롬프트에서 netstat -ano | findstr :{port} 로 그 프로그램 번호를 볼 수 있습니다.)"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_taken_port_is_named_and_does_not_look_like_a_missing_file() {
        let message = port_taken_message("http://127.0.0.1:8091");
        assert!(message.contains("8091"));
        assert!(!message.contains("os error"), "화면이 90초를 헛기다리면 안 된다");
    }

    #[test]
    fn packaged_voice_defaults_are_disabled_in_the_child_command() {
        let command = bundled_backend_command(Path::new("C:/app/backend/python/python.exe")).unwrap();
        let configured: std::collections::HashMap<_, _> = command.get_envs().collect();
        for key in ["JARVIS_VOICE_ENABLED", "JARVIS_TTS_ENABLED"] {
            assert_eq!(configured.get(std::ffi::OsStr::new(key)).copied().flatten(), Some(std::ffi::OsStr::new("0")));
        }
        assert_eq!(command.get_args().collect::<Vec<_>>(), vec![std::ffi::OsStr::new("-m"), std::ffi::OsStr::new("alture_jarvis")]);
    }

    #[test]
    fn a_missing_setup_state_opens_the_wizard() {
        let dir = env::temp_dir().join(format!("jarvis-setup-state-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        assert!(needs_setup(&dir));
        std::fs::write(dir.join(SETUP_STATE_FILE), "{}").unwrap();
        assert!(!needs_setup(&dir));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_normal_process_is_not_packaged() {
        assert!(!status().packaged);
        assert_eq!(startup_task(None).state, "unpackaged");
    }
}
