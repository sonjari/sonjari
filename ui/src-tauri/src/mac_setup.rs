//! 맥 첫 실행 준비 (2026-11-17 대표 「dmg 에는 손자리 앱만 · 로고만 누르면 깔리게」).
//!
//! 예전 dmg 는 앱 옆에 「손자리 설치.command」 · backend 폴더 · 안내 그림을 두었다. 대표가 새 계정 시험에서
//! 로고(앱)부터 눌렀다 — 손님도 그렇게 한다. 이제 본체 묶음은 앱 안(`Contents/Resources/backend`)에 실리고,
//! 앱이 켜질 때 본체가 안 깔려 있으면 그 안의 `install_mac.sh` 를 뒤에서 돌린다(터미널 창 없음).
//! 끝나면 dmg 에서 연 앱을 응용 프로그램 폴더로 복사한다(예전 .command 가 하던 일).
//!
//! 화면은 `backend_bootstrap` 이 돌려주는 「처음 준비하는 중」 문구를 보고 제한 시간 없이 기다린다(backend.ts).

/// dmg(/Volumes/…) 나 격리 사본(AppTranslocation)에서 켜진 앱인가. **순수 함수** — 윈도우에서도 시험한다.
pub fn from_disk_image(exe_path: &str) -> bool {
    exe_path.starts_with("/Volumes/") || exe_path.contains("/AppTranslocation/")
}

/// 떠 있는 옛 손자리를 먼저 끝낼까 (2026-11-22 대표 맥 · 설계_맥앱안업데이트 §3-7).
///
/// 옛 손자리가 떠 있으면 새 dmg 앱은 single-instance 플러그인이 **설치 전에** 옛 앱으로 넘겨 버려 아무것도 안 바뀌었다
/// (옛 창만 앞으로 · 굽기의 「켜 보기: 이미 떠 있는 손자리로 넘김」도 같은 현상). dmg 에서 켜졌고, 실린 판 표시가 있고,
/// 깔린 판과 다를 때만 — 같은 판을 다시 누른 사람의 창은 그대로 둔다.
pub fn should_replace_running(exe_path: &str, bundled_stamp: &str, installed_stamp: &str) -> bool {
    let bundled = bundled_stamp.trim();
    from_disk_image(exe_path) && !bundled.is_empty() && bundled != installed_stamp.trim()
}

/// `ps -axo pid=,command=` 한 줄들에서 끝낼 옛 손자리 화면 앱의 pid. **자기 자신만** 빼고,
/// 실행 파일 이름이 `alture-jarvis-hud` 인 `.app` 만(본체 파이썬 · 도우미는 건드리지 않는다). **순수 함수**.
///
/// ★ 2026-11-23: 처음엔 dmg(/Volumes) 안에서 도는 손자리도 뺐다. 그런데 0.4.50 은 응용 프로그램으로 다시 열기 고침 전이라
///   **옛 dmg 안에서 계속 도는 옛 손자리**가 있었고(대표 맥), 그걸 못 끝내면 새 dmg 가 또 넘겨진다. 새 판 확인은
///   `should_replace_running`(판 표시가 다를 때만)이 이미 하므로, 여기서는 자기만 빼면 된다.
pub fn old_hud_pids(ps_output: &str, me: u32) -> Vec<u32> {
    ps_output
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            let (pid, command) = line.split_once(char::is_whitespace)?;
            let pid: u32 = pid.trim().parse().ok()?;
            // 경로에 빈칸이 있을 수 있다(「Sonjari 2.app」) — 빈칸으로 자르지 않고 자리 글자로 본다.
            let exe = command.trim();
            let wanted = exe.contains(".app/Contents/MacOS/alture-jarvis-hud");
            (wanted && pid != me).then_some(pid)
        })
        .collect()
}

#[cfg(target_os = "macos")]
mod imp {
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::process::{Command, Stdio};
    use std::sync::Mutex;

    /// 화면이 「기다리면 풀린다」로 알아보는 표시 — backend.ts `backendPreparing` 과 같은 글자.
    pub const PREPARING_MARK: &str = "손자리를 처음 준비하는 중입니다";

    enum State {
        Idle,
        Running,
        /// 이미 깔린 손님이 새 dmg 를 열었다 — 안에 실린 새 본체로 바꾸는 중(11-18).
        Updating,
        Failed(String),
        Done,
    }

    static STATE: Mutex<State> = Mutex::new(State::Idle);

    fn home() -> Option<PathBuf> {
        std::env::var_os("HOME").map(PathBuf::from)
    }

    /// 본체가 이미 깔려 있나 — 가상환경 파이썬과 로그인 자동 시작 등록이 둘 다 있어야 한다.
    fn installed(home: &Path) -> bool {
        home.join("Library/Application Support/Sonjari/app/.venv/bin/python").exists()
            && home.join("Library/LaunchAgents/com.sonjari.backend.plist").exists()
    }

    /// 판 표시 한 줄(굽기 · 커밋 · 시각). 없으면 빈 글.
    fn stamp(path: &Path) -> String {
        fs::read_to_string(path).map(|text| text.trim().to_string()).unwrap_or_default()
    }

    /// ★ 2026-11-18: 이미 깐 계정이 새 dmg 를 열어도 옛 본체로 돌았다(11-17 새 계정 시험 — 설치는 「처음」에만 돌았다).
    ///   dmg 안의 판 표시와 깔린 판 표시가 다르면 다시 깐다(install_mac.sh 는 덮어쓰기라 다시 돌려도 안전 · 설정 · 데이터는 그대로).
    ///   깔린 쪽에 표시가 없으면(이 고침 전에 깐 판) 한 번 다시 깐다. dmg 쪽에 표시가 없으면(개발 빌드) 건드리지 않는다.
    fn needs_update(home: &Path, payload: &Path) -> bool {
        let bundled = stamp(&payload.join("PAYLOAD_STAMP"));
        if bundled.is_empty() {
            return false;
        }
        bundled != stamp(&home.join("Library/Application Support/Sonjari/app/PAYLOAD_STAMP"))
    }

    fn contents_dir() -> Option<PathBuf> {
        // .../Sonjari.app/Contents/MacOS/alture-jarvis-hud → .../Sonjari.app/Contents
        std::env::current_exe().ok()?.parent()?.parent().map(Path::to_path_buf)
    }

    fn setup_log(home: &Path) -> PathBuf {
        home.join("Library/Logs/Sonjari/first_setup.log")
    }

    /// 켤 때 한 번 부른다. 깔려 있거나 앱 안에 본체 묶음이 없으면(개발 빌드) 아무것도 안 한다.
    pub fn start_if_needed() {
        let Some(home) = home() else { return };
        let Some(contents) = contents_dir() else { return };
        let payload = contents.join("Resources/backend");
        let script = payload.join("scripts/mac/install_mac.sh");
        if !script.exists() {
            return;
        }
        let updating = installed(&home);
        if updating && !needs_update(&home, &payload) {
            return;
        }
        {
            let mut state = STATE.lock().unwrap_or_else(|e| e.into_inner());
            if !matches!(*state, State::Idle) {
                return;
            }
            *state = if updating { State::Updating } else { State::Running };
        }
        let voice = contents.join("Helpers/SonjariVoice.app");
        // 11-18: 실행 도우미 — 허락 창이 「python3.12」 대신 「손자리」로 뜨게(native/mac/SonjariEngine).
        let engine = contents.join("Helpers/SonjariEngine.app");
        std::thread::spawn(move || {
            let log_path = setup_log(&home);
            let _ = fs::create_dir_all(log_path.parent().unwrap_or(&home));
            let log = fs::OpenOptions::new().create(true).append(true).open(&log_path).ok();
            let mut command = Command::new("/bin/bash");
            command.arg(&script).arg("--source").arg(&payload).env("SONJARI_VOICE_APP", &voice).env("SONJARI_ENGINE_APP", &engine).stdin(Stdio::null());
            match log.as_ref().and_then(|file| Some((file.try_clone().ok()?, file.try_clone().ok()?))) {
                Some((out, err)) => {
                    command.stdout(out).stderr(err);
                }
                None => {
                    command.stdout(Stdio::null()).stderr(Stdio::null());
                }
            }
            let outcome = command.status();
            let next = match outcome {
                Ok(status) if status.success() => {
                    copy_to_applications(&home);
                    State::Done
                }
                Ok(status) => State::Failed(format!("설치가 끝나지 못했습니다(종료 코드 {})", status.code().unwrap_or(-1))),
                Err(error) => State::Failed(format!("설치를 시작하지 못했습니다: {error}")),
            };
            *STATE.lock().unwrap_or_else(|e| e.into_inner()) = next;
        });
    }

    /// dmg(/Volumes/…) 나 격리 사본(AppTranslocation)에서 연 앱이면 응용 프로그램 폴더로 복사한다.
    /// 관리자가 아니면 /Applications 에 못 쓴다 — 그때는 ~/Applications.
    fn copy_to_applications(home: &Path) {
        let Some(contents) = contents_dir() else { return };
        let Some(app) = contents.parent() else { return };
        let path = app.to_string_lossy();
        if !(path.starts_with("/Volumes/") || path.contains("/AppTranslocation/")) {
            return;
        }
        let system = Path::new("/Applications");
        let writable = fs::metadata(system).map(|m| !m.permissions().readonly()).unwrap_or(false)
            && Command::new("/bin/test").arg("-w").arg(system).status().map(|s| s.success()).unwrap_or(false);
        let dest_dir = if writable { system.to_path_buf() } else { home.join("Applications") };
        let _ = fs::create_dir_all(&dest_dir);
        let dest = dest_dir.join("Sonjari.app");
        let _ = fs::remove_dir_all(&dest);
        if Command::new("/usr/bin/ditto").arg(app).arg(&dest).status().map(|s| s.success()).unwrap_or(false) {
            let _ = Command::new("/usr/bin/xattr").args(["-dr", "com.apple.quarantine"]).arg(&dest).status();
            reopen_from_copy(&dest);
        }
    }

    /// single-instance 를 달기 **전에** 부른다 — dmg 에서 켜진 새 판이면 떠 있는 옛 손자리 화면 앱을 끝내고(최대 8초) 기다린다.
    /// 본체(launchd) · 도우미는 건드리지 않는다. 설치는 그 뒤 `start_if_needed` 가 평소대로 한다.
    pub fn replace_running_old() {
        let Some(home) = home() else { return };
        let Some(contents) = contents_dir() else { return };
        let exe = std::env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
        let bundled = stamp(&contents.join("Resources/backend/PAYLOAD_STAMP"));
        let installed = stamp(&home.join("Library/Application Support/Sonjari/app/PAYLOAD_STAMP"));
        if !super::should_replace_running(&exe, &bundled, &installed) {
            return;
        }
        let me = std::process::id();
        let list = || {
            Command::new("/bin/ps").args(["-axo", "pid=,command="]).output().ok()
                .map(|out| super::old_hud_pids(&String::from_utf8_lossy(&out.stdout), me))
                .unwrap_or_default()
        };
        let pids = list();
        if pids.is_empty() {
            return;
        }
        for pid in &pids {
            let _ = Command::new("/bin/kill").args(["-TERM", &pid.to_string()]).status();
        }
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(8);
        while std::time::Instant::now() < deadline && !list().is_empty() {
            std::thread::sleep(std::time::Duration::from_millis(200));
        }
    }

    /// dmg 에서 연 앱이 응용 프로그램으로 복사됐으면 1초 뒤 그 사본을 열고 자기는 끝낸다(11-22) — 그대로 두면 dmg 를 꺼낼 때 창이 닫힌다.
    fn reopen_from_copy(dest: &Path) {
        let script = format!("sleep 1; /usr/bin/open -n '{}'", dest.display().to_string().replace('\'', "'\\''"));
        if Command::new("/bin/sh").args(["-c", &script]).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().is_ok() {
            std::process::exit(0);
        }
    }

    /// 준비가 도는 중이거나 실패했으면 화면에 보일 말. 없으면 None(평소 길).
    pub fn bootstrap_hint() -> Option<String> {
        let state = STATE.lock().unwrap_or_else(|e| e.into_inner());
        match &*state {
            State::Running => Some(format!("{PREPARING_MARK} — 부품을 받고 있어요. 처음 한 번만, 몇 분 걸립니다.")),
            // 화면이 기다리게 같은 표시를 앞에 둔다(backend.ts `backendPreparing`).
            State::Updating => Some(format!("{PREPARING_MARK} — 새 판으로 바꾸고 있어요. 잠깐이면 됩니다.")),
            State::Failed(reason) => {
                let log = home().map(|h| setup_log(&h).display().to_string()).unwrap_or_default();
                Some(format!("손자리를 준비하지 못했습니다: {reason}. 인터넷 연결을 확인한 뒤 앱을 다시 열어 주세요. (기록: {log})"))
            }
            State::Idle | State::Done => None,
        }
    }
}

#[cfg(target_os = "macos")]
pub use imp::{bootstrap_hint, replace_running_old, start_if_needed};

#[cfg(not(target_os = "macos"))]
pub fn start_if_needed() {}

#[cfg(not(target_os = "macos"))]
pub fn replace_running_old() {}

#[cfg(not(target_os = "macos"))]
pub fn bootstrap_hint() -> Option<String> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    const DMG: &str = "/Volumes/Sonjari/Sonjari.app/Contents/MacOS/alture-jarvis-hud";
    const INSTALLED: &str = "/Applications/Sonjari.app/Contents/MacOS/alture-jarvis-hud";

    #[test]
    fn a_newer_app_from_the_disk_image_replaces_the_running_one() {
        assert!(should_replace_running(DMG, "0.4.51 abc 2026", "0.4.50 def 2026"));
        assert!(should_replace_running("/private/var/folders/x/AppTranslocation/Y/d/Sonjari.app/Contents/MacOS/alture-jarvis-hud",
                                       "0.4.51 abc", "0.4.50 def"));
        // 깔린 쪽에 표시가 없으면(옛 설치) 바꾼다.
        assert!(should_replace_running(DMG, "0.4.51 abc", ""));
    }

    #[test]
    fn the_same_version_or_the_installed_app_leaves_the_window_alone() {
        assert!(!should_replace_running(DMG, "0.4.50 def 2026", "0.4.50 def 2026"));
        assert!(!should_replace_running(INSTALLED, "0.4.51 abc", "0.4.50 def"));
        assert!(!should_replace_running(DMG, "", "0.4.50 def")); // 개발 빌드(표시 없음)는 건드리지 않는다
    }

    #[test]
    fn only_old_hud_windows_are_picked_not_me_or_the_backend() {
        let ps = "  722 /Applications/Sonjari.app/Contents/MacOS/alture-jarvis-hud\n\
                  1801 /Applications/Sonjari 2.app/Contents/MacOS/alture-jarvis-hud --flag\n\
                  2332 /Volumes/Sonjari/Sonjari.app/Contents/MacOS/alture-jarvis-hud\n\
                  2435 /Users/a/Library/Application Support/Sonjari/app/.venv/bin/python -m alture_jarvis\n\
                  2431 /Users/a/Library/Application Support/Sonjari/app/engine/SonjariEngine.app/Contents/MacOS/SonjariEngine\n\
                  9999 /Applications/Sonjari.app/Contents/MacOS/alture-jarvis-hud\n\
                  garbage line\n";
        // 2332 = 옛 dmg 안에서 도는 옛 손자리(11-23 대표 맥 · 0.4.50) — 이것도 끝낸다. 9999 = 나.
        assert_eq!(old_hud_pids(ps, 9999), vec![722, 1801, 2332]);
        // 내가 dmg 안에서 도는 쪽이면 나만 빠진다.
        assert_eq!(old_hud_pids(ps, 2332), vec![722, 1801, 9999]);
    }
}
