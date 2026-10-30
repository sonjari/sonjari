//! 윈도우 알림(오른쪽 아래 토스트) — 2026-10-27 그룹장 피드백(일을 던져 두고 다른 일을 하다 나중에 본다).
//!
//! ## 왜 `tauri-plugin-notification` 을 안 쓰나 (확인한 것)
//! 플러그인 2.3.3(소스를 직접 읽음)의 데스크톱 길은 **쏘고 잊는다** — 알림을 눌렀다는 신호가 앱에 안 온다(`on_action` 은 모바일만).
//! 「알림을 누르면 앱 창을 앞으로 + 그 대화로」를 못 한다. 또 설치된 앱의 앱 ID(AUMID)를 `tauri.conf` 의 identifier 로 못 박는데,
//! 스토어(MSIX) 앱의 진짜 AUMID 는 `패키지가문이름!App` 이라 어긋난다. 그래서 이미 쓰는 `windows` 크레이트(0.61)로 직접 한다 —
//! 새 의존성이 없고, 눌림을 받는다.
//!
//! ## 앱 ID
//! - **MSIX(스토어)**: `CreateToastNotifier()` 를 앱 ID 없이 부른다 — 패키지 신원이 곧 앱 ID 다(매니페스트 변경 없음).
//!   이 PC 에는 패키지판이 안 깔려 있어 **직접 확인하지 못했다**(짐작 — 윈도우 문서의 데스크톱 브리지 앱 방식).
//! - **패키지 아님(개발 · 사설 설치)**: 등록된 앱 ID 가 있어야 토스트가 뜬다. 이 PC 에서 `Sonjari` 같은 **미등록 ID 는 조용히 안 뜸**을
//!   직접 봤다(HKCU `AppUserModelId` 키만 만든 것도 안 뜸). 시작 메뉴 바로가기에 앱 ID 를 박는 것은 시작 메뉴를 건드리는 일이라
//!   하지 않고, 윈도우 PowerShell 의 앱 ID 를 빌린다(플러그인의 개발 모드와 같다) — 알림 위쪽에 「Windows PowerShell」 이 보인다.

//!
//! ## 모양(2026-10-27 대표 요청 — 손자리 디자인)
//! 토스트 XML 안에서만 꾸민다: 앱 아이콘(`appLogoOverride` · 네모 그대로, 원으로 자르지 않음) · 위쪽 큰 그림(`hero` 728x364, 종류별 셋 ·
//! `icons/notify/`) · 단추(「열기」 · 끝났을 때 산출물이 있으면 「결과 폴더」) · 출처 줄(`attribution`). 소리는 윈도우 기본 그대로다.
//! 따로 창을 그리는 방식(항상 위 작은 창)은 쓰지 않는다 — 알림 센터에 남아야 하고, 방해 금지 모드를 지켜야 하며, 3ds Max 같은 작업 위로
//! 튀어나오면 안 된다. **그림이 없거나 경로가 틀리면** 그 `<image>` 만 빼고 글만으로 띄운다(`resolve_art` 가 없으면 None).
//!
//! 그림 주소: MSIX 는 패키지 안 `Assets\…` → `ms-appx:///Assets/…`, 개발 · 사설 설치는 exe 옆 또는 소스 폴더의 `icons\…` → `file:///…`(한글 · 공백은 날것 그대로 — %인코딩하면 안 뜬다).

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

/// 알림을 누르면 부르는 것 — 인자는 누른 곳(`open` 본문 · 「열기」 · `folder` 「결과 폴더」). 토스트 스레드(COM 콜백)에서 불리니 `Send + Sync`.
pub type OnClick = Arc<dyn Fn(&str) + Send + Sync + 'static>;

/// 알림의 종류 — 위쪽 큰 그림이 이걸 따른다.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tone {
    Done,
    Waiting,
    Stuck,
}

impl Tone {
    pub fn parse(text: &str) -> Tone {
        match text {
            "waiting" => Tone::Waiting,
            "stuck" => Tone::Stuck,
            _ => Tone::Done,
        }
    }
    fn word(self) -> &'static str {
        match self {
            Tone::Done => "done",
            Tone::Waiting => "waiting",
            Tone::Stuck => "stuck",
        }
    }
}

/// 보낼 것. 그림 주소는 이미 풀어 둔 것(`resolve_art`) — 없으면 그 그림만 뺀다.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Toast {
    pub title: String,
    pub body: String,
    /// 제목 아래 작은 출처 줄(판 이름). 비면 안 넣는다.
    pub attribution: String,
    pub hero: Option<String>,
    pub logo: Option<String>,
    pub open_label: String,
    /// 있으면 「결과 폴더」 단추를 둔다(끝났고 산출물이 있을 때만).
    pub folder_label: Option<String>,
}

/// 토스트 XML 에 넣기 전에 특수문자를 막고 길이를 줄인다(토스트는 제목 1줄 · 본문 2줄쯤만 보인다).
pub fn clean(text: &str, max_chars: usize) -> String {
    let one_line = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let cut: String = one_line.chars().take(max_chars).collect();
    let cut = if one_line.chars().count() > max_chars { format!("{}…", cut.trim_end()) } else { cut };
    cut.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&apos;")
}

/// 그림 하나 — 주소를 못 풀었으면 줄 자체가 없다. `appLogoOverride` 에 `hint-crop` 을 안 주므로 네모 그대로 나온다.
fn image_line(placement: &str, src: &Option<String>) -> String {
    match src {
        Some(url) if !url.is_empty() => format!(r#"<image placement="{placement}" src="{}"/>"#, xml_attr(url)),
        _ => String::new(),
    }
}

pub fn toast_xml(toast: &Toast) -> String {
    let attribution = if toast.attribution.trim().is_empty() {
        String::new()
    } else {
        format!(r#"<text placement="attribution">{}</text>"#, clean(&toast.attribution, 40))
    };
    let open = if toast.open_label.trim().is_empty() { "Open" } else { toast.open_label.trim() };
    let mut actions = format!(r#"<action content="{}" arguments="open" activationType="foreground"/>"#, clean(open, 20));
    if let Some(label) = toast.folder_label.as_deref().filter(|label| !label.trim().is_empty()) {
        actions.push_str(&format!(r#"<action content="{}" arguments="folder" activationType="foreground"/>"#, clean(label, 20)));
    }
    // `<audio>` 는 넣지 않는다 — 소리는 윈도우 기본 그대로.
    format!(
        r#"<toast launch="open" activationType="foreground"><visual><binding template="ToastGeneric">{hero}{logo}<text>{title}</text><text>{body}</text>{attribution}</binding></visual><actions>{actions}</actions></toast>"#,
        hero = image_line("hero", &toast.hero),
        logo = image_line("appLogoOverride", &toast.logo),
        title = clean(&toast.title, 60),
        body = clean(&toast.body, 160),
    )
}

/// 파일 경로 → `file:///` 주소. **%인코딩을 하지 않는다** — 이 PC 에서 직접 봤다(2026-10-27): 날것의 한글 · 공백 경로(`file:///E:/내 작업/…`)는
/// 뜨고, 같은 경로를 %인코딩하면 그림이 안 뜬다(윈도우 토스트가 %를 풀지 않는다). XML 특수문자만 속성 값에서 막는다(`xml_attr`).
pub fn file_url(path: &Path) -> String {
    let text = path.to_string_lossy().replace('\\', "/");
    format!("file:///{}", text.strip_prefix("//?/").unwrap_or(&text))
}

/// XML 속성 값에 넣을 때 막을 글자만 막는다(공백은 건드리지 않는다 — 경로가 바뀐다).
fn xml_attr(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&apos;")
}

/// 그림 한 장의 주소를 푼다. 못 찾으면 None(→ 글만 띄운다).
/// - 패키지(MSIX): `<exe 폴더>/Assets/<packaged_rel>` 이 있으면 `ms-appx:///Assets/<packaged_rel>`.
/// - 패키지 아님: `<exe 폴더>/icons` · `<exe 폴더>/Assets` · `<exe 폴더>` · 소스의 `icons`(`manifest_dir`)에서 `dev_rel` 을 찾아 `file:///`.
pub fn resolve_art(
    packaged: bool,
    packaged_rel: &str,
    dev_rel: &str,
    exe_dir: Option<&Path>,
    manifest_dir: Option<&Path>,
    exists: &dyn Fn(&Path) -> bool,
) -> Option<String> {
    if packaged {
        let file = exe_dir?.join("Assets").join(packaged_rel);
        return exists(&file).then(|| format!("ms-appx:///Assets/{packaged_rel}"));
    }
    find_dev_file(dev_rel, exe_dir, manifest_dir, exists).map(|file| file_url(&file))
}

/// 패키지 아닌 판의 그림 파일 — `<exe 폴더>/icons` · `<exe 폴더>/Assets` · `<exe 폴더>` · 소스의 `icons`(`manifest_dir`) 순서로 처음 있는 것.
pub fn find_dev_file(dev_rel: &str, exe_dir: Option<&Path>, manifest_dir: Option<&Path>, exists: &dyn Fn(&Path) -> bool) -> Option<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Some(dir) = exe_dir {
        roots.extend([dir.join("icons"), dir.join("Assets"), dir.to_path_buf()]);
    }
    if let Some(dir) = manifest_dir {
        roots.push(dir.join("icons"));
    }
    roots.into_iter().map(|root| root.join(dev_rel)).find(|file| exists(file))
}

/// 종류 · 언어에 맞는 큰 그림 파일 이름.
pub fn hero_name(tone: Tone, english: bool) -> String {
    format!("notify/hero_{}_{}.png", tone.word(), if english { "en" } else { "ko" })
}

/// 실제 PC 에서 그림 둘의 주소를 푼다.
pub fn art_for(tone: Tone, english: bool) -> (Option<String>, Option<String>) {
    let packaged = crate::package::status().packaged;
    let exe_dir = std::env::current_exe().ok().and_then(|exe| exe.parent().map(Path::to_path_buf));
    let manifest = option_env!("CARGO_MANIFEST_DIR").map(PathBuf::from);
    let exists = |path: &Path| path.is_file();
    let hero_rel = hero_name(tone, english);
    let hero = resolve_art(packaged, &hero_rel, &hero_rel, exe_dir.as_deref(), manifest.as_deref(), &exists);
    // 앱 아이콘 — 패키지 안 것을 그대로(MSIX Assets 의 64px · 개발은 icons/64x64.png). 원으로 자르지 않는다.
    let logo = resolve_art(packaged, "Square44x44Logo.targetsize-64.png", "64x64.png", exe_dir.as_deref(), manifest.as_deref(), &exists);
    (hero, logo)
}

#[cfg(target_os = "windows")]
mod imp {
    use super::*;
    use windows::{
        core::{IInspectable, Interface, HSTRING},
        Data::Xml::Dom::XmlDocument,
        Foundation::TypedEventHandler,
        UI::Notifications::{ToastActivatedEventArgs, ToastNotification, ToastNotificationManager},
    };

    /// 패키지 아닐 때 빌려 쓰는 앱 ID — 윈도우 PowerShell 의 것(항상 등록돼 있다). 알림 머리줄에 「Windows PowerShell」 이 보인다.
    const BORROWED_AUMID: &str = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe";

    /// 패키지 아닐 때 쓰는 **손자리 이름 · 아이콘의 앱 ID**. HKCU `Software\Classes\AppUserModelId\<이 값>` 에 이름(DisplayName)과 아이콘(IconUri)을
    /// 적어 두면 알림 머리줄에 「Sonjari」 와 아이콘이 나온다(사용자 키 하나 — 시작 메뉴 · 시스템 설정은 안 건드린다. 지우려면 그 키를 지운다).
    /// ★ **꺼 둔다**(2026-10-27 이 PC 에서 직접 봄): 이 키만 만든 앱 ID 로 보낸 토스트는 배너가 안 뜨고 알림 센터에만 조용히 쌓였다.
    ///   시작 메뉴 바로가기에 앱 ID 를 박아야 배너가 뜬다 — 시작 메뉴를 건드리는 일이라 대표 결정을 받기 전에는 켜지 않는다.
    ///   그래서 패키지 아닌 판은 PowerShell 의 앱 ID 를 빌려 쓴다(머리줄에 「Windows PowerShell」). MSIX 는 이 길을 안 탄다.
    const BRANDED_AUMID: &str = "Sonjari.Desktop";
    const USE_BRANDED_AUMID: bool = false;

    /// 손자리 앱 ID 를 사용자 레지스트리에 한 번(프로세스당) 적는다. 성공하면 true.
    #[allow(dead_code)]
    fn register_branded() -> bool {
        static DONE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
        *DONE.get_or_init(|| {
            use std::os::windows::process::CommandExt;
            let key = format!(r"HKCU\Software\Classes\AppUserModelId\{BRANDED_AUMID}");
            let exe_dir = std::env::current_exe().ok().and_then(|exe| exe.parent().map(Path::to_path_buf));
            let manifest = option_env!("CARGO_MANIFEST_DIR").map(PathBuf::from);
            let icon = find_dev_file("128x128.png", exe_dir.as_deref(), manifest.as_deref(), &|path: &Path| path.is_file());
            let add = |name: &str, value: &str| -> bool {
                std::process::Command::new("reg")
                    .args(["add", &key, "/v", name, "/t", "REG_SZ", "/d", value, "/f"])
                    .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
                    .output()
                    .map(|out| out.status.success())
                    .unwrap_or(false)
            };
            let named = add("DisplayName", "Sonjari");
            if let Some(icon) = icon {
                add("IconUri", &icon.to_string_lossy());
                add("IconBackgroundColor", "FF141210");
            }
            named
        })
    }

    fn app_id() -> Option<HSTRING> {
        if crate::package::status().packaged {
            return None; // 패키지 신원이 곧 앱 ID(머리줄의 이름 · 아이콘은 매니페스트의 것)
        }
        #[allow(clippy::overly_complex_bool_expr)]
        if USE_BRANDED_AUMID && register_branded() {
            return Some(HSTRING::from(BRANDED_AUMID));
        }
        Some(HSTRING::from(BORROWED_AUMID))
    }

    /// 눌림 콜백을 받으려면 토스트 객체가 살아 있어야 한다 — 최근 것만 붙들어 둔다.
    static LIVE: Mutex<Vec<ToastNotification>> = Mutex::new(Vec::new());

    fn build(toast: &Toast, on_click: &OnClick) -> Result<ToastNotification, String> {
        let xml = XmlDocument::new().map_err(|e| e.message().to_string())?;
        xml.LoadXml(&HSTRING::from(toast_xml(toast))).map_err(|e| e.message().to_string())?;
        let notification = ToastNotification::CreateToastNotification(&xml).map_err(|e| e.message().to_string())?;
        let on_click = on_click.clone();
        let handler = TypedEventHandler::<ToastNotification, IInspectable>::new(move |_, args| {
            // 단추를 눌렀으면 그 단추의 arguments(`open` · `folder`), 본문을 눌렀으면 launch 값(`open`).
            let action = args
                .as_ref()
                .and_then(|inspectable| inspectable.cast::<ToastActivatedEventArgs>().ok())
                .and_then(|args| args.Arguments().ok())
                .map(|text| text.to_string())
                .unwrap_or_default();
            on_click(if action.is_empty() { "open" } else { action.as_str() });
            Ok(())
        });
        notification.Activated(&handler).map_err(|e| e.message().to_string())?;
        Ok(notification)
    }

    fn show_one(toast: &Toast, on_click: &OnClick) -> Result<(), String> {
        let notification = build(toast, on_click)?;
        let notifier = match app_id() {
            None => ToastNotificationManager::CreateToastNotifier(),
            Some(id) => ToastNotificationManager::CreateToastNotifierWithId(&id),
        }
        .map_err(|e| e.message().to_string())?;
        notifier.Show(&notification).map_err(|e| e.message().to_string())?;
        if let Ok(mut live) = LIVE.lock() {
            live.push(notification);
            if live.len() > 20 {
                live.remove(0);
            }
        }
        Ok(())
    }

    pub fn show(toast: &Toast, on_click: OnClick) -> Result<(), String> {
        // 그림 때문에 못 띄우는 일이 있으면(주소가 틀림 등) 그림을 빼고 글만으로 한 번 더 — 알림 자체를 잃지 않는다.
        match show_one(toast, &on_click) {
            Ok(()) => Ok(()),
            Err(first) if toast.hero.is_some() || toast.logo.is_some() => {
                show_one(&Toast { hero: None, logo: None, ..toast.clone() }, &on_click).map_err(|_| first)
            }
            Err(first) => Err(first),
        }
    }
}

#[cfg(target_os = "windows")]
pub fn show(toast: &Toast, on_click: OnClick) -> Result<(), String> {
    imp::show(toast, on_click)
}

#[cfg(not(target_os = "windows"))]
pub fn show(_toast: &Toast, _on_click: OnClick) -> Result<(), String> {
    Err("windows_only".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plain(title: &str, body: &str) -> Toast {
        Toast { title: title.into(), body: body.into(), open_label: "열기".into(), ..Toast::default() }
    }

    #[test]
    fn xml_escapes_and_stays_short() {
        let xml = toast_xml(&plain("a < b & \"c\"", &"x".repeat(400)));
        assert!(xml.contains("a &lt; b &amp; &quot;c&quot;"));
        assert!(xml.contains('…'));
        assert!(!xml.contains("a < b"));
        assert!(xml.len() < 1200);
    }

    #[test]
    fn newlines_become_spaces() {
        assert_eq!(clean("한 줄\n두 줄\t세 줄", 40), "한 줄 두 줄 세 줄");
    }

    #[test]
    fn a_toast_without_art_is_text_only_with_one_button() {
        let xml = toast_xml(&plain("제목", "본문"));
        assert!(!xml.contains("<image"), "그림이 없으면 image 줄 자체가 없다: {xml}");
        assert!(!xml.contains("attribution"));
        assert_eq!(xml.matches("<action ").count(), 1, "기다려요 · 그림 없음: 「열기」만");
        assert!(xml.contains(r#"content="열기" arguments="open""#));
        assert!(!xml.contains("<audio"), "소리는 윈도우 기본 그대로");
    }

    #[test]
    fn a_full_toast_has_hero_logo_attribution_and_two_buttons() {
        let toast = Toast {
            attribution: "손자리 · 코드".into(),
            hero: Some("ms-appx:///Assets/notify/hero_done_ko.png".into()),
            logo: Some("ms-appx:///Assets/Square44x44Logo.targetsize-64.png".into()),
            folder_label: Some("결과 폴더".into()),
            ..plain("제목", "본문")
        };
        let xml = toast_xml(&toast);
        assert!(xml.contains(r#"<image placement="hero" src="ms-appx:///Assets/notify/hero_done_ko.png"/>"#));
        assert!(xml.contains(r#"<image placement="appLogoOverride" src="ms-appx:///Assets/Square44x44Logo.targetsize-64.png"/>"#));
        assert!(!xml.contains("hint-crop"), "원으로 자르지 않는다");
        assert!(xml.contains(r#"<text placement="attribution">손자리 · 코드</text>"#));
        assert!(xml.contains(r#"content="결과 폴더" arguments="folder""#));
        assert_eq!(xml.matches("<action ").count(), 2);
        assert!(xml.find("hero").unwrap() < xml.find("<text>").unwrap(), "큰 그림은 제목보다 위");
    }

    #[test]
    fn file_urls_keep_hangul_and_spaces_raw() {
        // 날것의 한글 · 공백은 뜨고 %인코딩은 안 뜬다(이 PC 에서 직접 확인) — 그래서 인코딩하지 않는다.
        let url = file_url(Path::new(r"E:\내 작업\a b\hero.png"));
        assert_eq!(url, "file:///E:/내 작업/a b/hero.png");
        assert!(!url.contains('%') && !url.contains('\\'));
        assert_eq!(file_url(Path::new(r"\\?\C:\x\y.png")), "file:///C:/x/y.png");
        let toast = Toast { hero: Some(url), ..Toast::default() };
        assert!(toast_xml(&toast).contains(r#"src="file:///E:/내 작업/a b/hero.png""#));
        let tricky = Toast { hero: Some(r#"file:///E:/a&b/"x".png"#.into()), ..Toast::default() };
        assert!(toast_xml(&tricky).contains("a&amp;b/&quot;x&quot;.png"));
    }

    #[test]
    fn art_resolves_per_edition_and_is_none_when_missing() {
        let exe = PathBuf::from(r"C:\app");
        let manifest = PathBuf::from(r"E:\src-tauri");
        let rel = hero_name(Tone::Stuck, false);
        assert_eq!(rel, "notify/hero_stuck_ko.png");
        assert_eq!(hero_name(Tone::Waiting, true), "notify/hero_waiting_en.png");
        // MSIX: 패키지 안 Assets 에 있으면 ms-appx, 없으면 None(→ 글만)
        let present = |p: &Path| p == Path::new(r"C:\app\Assets\notify\hero_stuck_ko.png");
        assert_eq!(
            resolve_art(true, &rel, &rel, Some(&exe), Some(&manifest), &present).as_deref(),
            Some("ms-appx:///Assets/notify/hero_stuck_ko.png")
        );
        assert_eq!(resolve_art(true, &rel, &rel, Some(&exe), Some(&manifest), &|_: &Path| false), None);
        // 개발: 소스의 icons 에서 file:///
        let dev = |p: &Path| p == Path::new(r"E:\src-tauri\icons\notify\hero_stuck_ko.png");
        assert_eq!(
            resolve_art(false, &rel, &rel, Some(&exe), Some(&manifest), &dev).as_deref(),
            Some("file:///E:/src-tauri/icons/notify/hero_stuck_ko.png")
        );
        // 개발에서 exe 옆이 먼저
        let both = |p: &Path| p.ends_with("hero_stuck_ko.png");
        assert!(resolve_art(false, &rel, &rel, Some(&exe), Some(&manifest), &both).unwrap().starts_with("file:///C:/app/icons/"));
        assert_eq!(resolve_art(false, &rel, &rel, Some(&exe), Some(&manifest), &|_: &Path| false), None);
    }

    /// 화면에 띄우지 않고 윈도우 XML 해석기로만 확인한다 — 만든 토스트 XML 이 올바른 글이고 그림 · 단추 · 출처 줄이 제자리에 있는지.
    #[cfg(target_os = "windows")]
    #[test]
    fn windows_parses_the_toast_xml_without_showing_it() {
        use windows::{core::HSTRING, Data::Xml::Dom::XmlDocument};
        let toast = Toast {
            title: "3ds Max <폴더> & \"정리\"".into(),
            body: "끝났습니다 — 결과 12건".into(),
            attribution: "대화".into(),
            hero: Some("file:///E:/내 작업/a&b/hero_done_ko.png".into()),
            logo: Some("ms-appx:///Assets/Square44x44Logo.targetsize-64.png".into()),
            open_label: "열기".into(),
            folder_label: Some("결과 폴더".into()),
        };
        for variant in [toast.clone(), Toast { hero: None, logo: None, folder_label: None, attribution: String::new(), ..toast }] {
            let doc = XmlDocument::new().expect("xml");
            doc.LoadXml(&HSTRING::from(toast_xml(&variant))).expect("올바른 XML 이어야 한다");
            let text = doc.GetXml().unwrap().to_string();
            assert!(text.contains("<toast"));
            assert_eq!(text.contains("placement=\"hero\""), variant.hero.is_some());
            assert_eq!(text.contains("appLogoOverride"), variant.logo.is_some());
            assert_eq!(text.matches("<action ").count(), if variant.folder_label.is_some() { 2 } else { 1 });
        }
    }

    #[test]
    fn tone_parses_unknown_as_done() {
        assert_eq!(Tone::parse("waiting"), Tone::Waiting);
        assert_eq!(Tone::parse("stuck"), Tone::Stuck);
        assert_eq!(Tone::parse("finished"), Tone::Done);
    }

    /// 손으로 돌리는 시험: `NOTIFY_PROBE=done|waiting|stuck|missing cargo test show_a_real_toast -- --ignored --nocapture`
    /// — 이 PC 에서 진짜 토스트가 뜨는지 본다. `missing` 은 없는 그림 주소를 일부러 넣는다(그림이 없어도 글만으로 뜨는지).
    #[test]
    #[ignore]
    fn show_a_real_toast() {
        let probe = std::env::var("NOTIFY_PROBE").unwrap_or_else(|_| "done".into());
        let english = std::env::var("NOTIFY_LANG").map(|v| v == "en").unwrap_or(false);
        let tone = Tone::parse(&probe);
        let (hero, logo) = art_for(tone, english);
        let (title, body) = match probe.as_str() {
            "waiting" => ("3ds Max 폴더 정리", "승인이 필요합니다 — 바탕화면에 쓰기"),
            "stuck" => ("3ds Max 폴더 정리", "모델이 첫 글자를 300초 동안 내놓지 못했습니다 — 그래픽카드를 쓰는 다른 프로그램을 닫고 「이어서 해줘」라고 보내 주세요"),
            _ => ("3ds Max 폴더 정리", "끝났습니다 — 결과 12건을 엑셀로 만들었습니다."),
        };
        let mut toast = Toast {
            title: title.into(),
            body: body.into(),
            attribution: "손자리 · 대화".into(),
            hero,
            logo,
            open_label: "열기".into(),
            folder_label: (probe == "done").then(|| "결과 폴더".to_string()),
        };
        if probe == "missing" {
            toast.hero = Some("file:///Z:/nowhere/hero.png".into());
            toast.logo = Some("file:///Z:/nowhere/logo.png".into());
        }
        println!("hero={:?}\nlogo={:?}", toast.hero, toast.logo);
        show(&toast, Arc::new(|action| println!("CLICKED {action}"))).expect("toast");
        std::thread::sleep(std::time::Duration::from_secs(12));
    }
}
