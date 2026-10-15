//! WebView2 가 없는 PC 에서 하얀 창 + 영어 오류 대신 한국어 안내를 띄운다 (2026-09-29, 인수인계 「베타 전 필수」).
//!
//! ★ 판정은 **레지스트리가 아니라 파일**로 한다. 샌드박스 실측(09-29): 레지스트리엔 WebView2 「있음」인데
//!   `msedgewebview2.exe` 가 없었고, 앱은 하얀 창으로 떴다. 있다고 적힌 것과 실제로 있는 것은 다르다.
//!
//! 못 찾아도 앱을 막지 않는다 — 「취소」를 누르면 그냥 띄운다. 우리가 모르는 설치 자리가 있을 수 있고,
//! 그때 앱을 잠그는 것이 하얀 창보다 나쁘다.

use std::path::{Path, PathBuf};

/// 마이크로소프트 공식 Evergreen 부트스트래퍼 내려받기 주소.
pub const WEBVIEW2_DOWNLOAD_URL: &str = "https://go.microsoft.com/fwlink/p/?LinkId=2124703";

/// `<root>\Microsoft\EdgeWebView\Application\<버전>\msedgewebview2.exe` 가 하나라도 있으면 참.
pub fn runtime_present_under(roots: &[PathBuf]) -> bool {
    roots.iter().any(|root| {
        let app = root.join("Microsoft").join("EdgeWebView").join("Application");
        let Ok(entries) = std::fs::read_dir(&app) else { return false };
        entries
            .flatten()
            .any(|entry| entry.path().join("msedgewebview2.exe").is_file())
    })
}

/// 고정판 런타임을 가리키는 환경변수(`WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`)가 실제 파일을 가리키는가.
fn fixed_runtime_present(folder: Option<&Path>) -> bool {
    folder.map(|dir| dir.join("msedgewebview2.exe").is_file()).unwrap_or(false)
}

fn install_roots() -> Vec<PathBuf> {
    ["ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"]
        .iter()
        .filter_map(|name| std::env::var_os(name).map(PathBuf::from))
        .collect()
}

pub fn runtime_present() -> bool {
    let fixed = std::env::var_os("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER").map(PathBuf::from);
    fixed_runtime_present(fixed.as_deref()) || runtime_present_under(&install_roots())
}

/// 없으면 안내 창을 띄운다. `true` 면 앱을 띄우지 말고 끝낸다(사람이 설치하러 갔다).
#[cfg(windows)]
pub fn guide_if_missing(app_name: &str) -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, IDOK, MB_ICONINFORMATION, MB_OKCANCEL, MB_SETFOREGROUND,
    };
    if runtime_present() {
        return false;
    }
    let text = format!(
        "{app_name} 화면을 그리려면 Microsoft Edge WebView2 런타임이 필요한데, 이 PC 에서 찾지 못했습니다.\n\n\
         [확인]을 누르면 마이크로소프트 공식 설치 파일을 내려받습니다. 설치한 뒤 {app_name} 를 다시 실행해 주세요.\n\
         [취소]를 누르면 그대로 열어 봅니다.\n\n\
         {app_name} needs the Microsoft Edge WebView2 Runtime, which was not found on this PC.\n\
         OK downloads the official installer from Microsoft. Cancel tries to open anyway."
    );
    let title = format!("{app_name} — WebView2");
    let wide = |s: &str| s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>();
    let (text_w, title_w) = (wide(&text), wide(&title));
    let answer = unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text_w.as_ptr(),
            title_w.as_ptr(),
            MB_OKCANCEL | MB_ICONINFORMATION | MB_SETFOREGROUND,
        )
    };
    if answer == IDOK {
        let _ = std::process::Command::new("explorer").arg(WEBVIEW2_DOWNLOAD_URL).spawn();
        return true;
    }
    false
}

#[cfg(not(windows))]
pub fn guide_if_missing(_app_name: &str) -> bool {
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("sonjari_wv2_{tag}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn finds_the_runtime_only_when_the_exe_file_is_really_there() {
        let root = temp_root("present");
        let version = root.join("Microsoft").join("EdgeWebView").join("Application").join("129.0.2792.65");
        std::fs::create_dir_all(&version).unwrap();
        // ★ 샌드박스 모양: 버전 폴더(=레지스트리가 「있다」고 말하는 자리)는 있는데 실행 파일이 없다.
        assert!(!runtime_present_under(&[root.clone()]), "폴더만 있고 파일이 없는데 있다고 봤다");
        std::fs::write(version.join("msedgewebview2.exe"), b"").unwrap();
        assert!(runtime_present_under(&[root.clone()]));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn an_empty_pc_is_missing() {
        let root = temp_root("empty");
        assert!(!runtime_present_under(&[root.clone()]));
        assert!(!fixed_runtime_present(Some(&root)));
        let _ = std::fs::remove_dir_all(&root);
    }
}
