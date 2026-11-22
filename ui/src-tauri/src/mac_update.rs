//! 맥 앱 꾸러미 통째 교체 (2026-11-16 · docs/설계_맥업데이트_2026-11-16.ko.md §2 ⑨⑩ · §6 위협 3).
//!
//! 서명 · 공증된 꾸러미는 안의 파일을 바꾸면 애플 서명이 깨진다 → 타우리 업데이터로 **통째로** 바꾼다.
//!
//! ## 누가 무엇을 확인하나
//! - **목록 서명 · seq · 판 맞춤**: 백엔드(`mac_update.py`) 한 곳. 화면 앱은 `/v1/update/check` 의 `app` 칸을 받는다
//!   (같은 기계 · 같은 사용자의 백엔드는 이미 화면 앱이 믿는 대상이다 — 제어 토큰으로 모든 도구를 부른다).
//! - **꾸러미 자체 서명**: 타우리 플러그인이 박아 둔 공개 열쇠(`src/alture_jarvis/update_pubkey.txt` → `include_str!`)로 늘 확인한다.
//! - **판 묶기**: latest.json 은 서명되지 않는다. 그것만 믿으면 「판 번호만 부풀린 옛 진짜 꾸러미」로 되돌릴 수 있다.
//!   지금 CLI(2.11.4)의 서명엔 판 번호가 없어 플러그인의 `requireSignedVersion` 도 못 쓴다(11-16 실측).
//!   그래서 비교 함수를 바꿔 끼워 **latest.json 의 판과 서명 문자열이 서명된 목록의 것과 같고, 지금보다 새것일 때만** 받는다.
//!
//! 윈도우는 스토어가 갱신한다 — 플러그인은 맥에만 싣고(Cargo.toml), 아래 두 명령은 맥이 아니면 바로 거절한다.

#![cfg_attr(not(target_os = "macos"), allow(dead_code))]

use serde::Deserialize;

/// 박아 둔 공개 열쇠(minisign 글). `#` 줄은 설명. 비어 있으면 앱 꾸러미 갱신은 꺼져 있다.
/// ★ 자리는 **한 곳**(대표 결정 11-16): 파이썬 묶음과 같은 `src/alture_jarvis/update_pubkey.txt` 를 빌드 때 그대로 굽는다.
///   두 벌로 두면 한쪽만 바뀐다. 빌드는 저장소 안에서만 돈다(build_app_package.ps1 · build_mac_dmg.sh — 화면 앱을 따로 복사하지 않음).
const PUBKEY_FILE: &str = include_str!("../../../src/alture_jarvis/update_pubkey.txt");

pub fn pubkey() -> String {
    PUBKEY_FILE
        .lines()
        .filter(|line| !line.trim().is_empty() && !line.trim_start().starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n")
}

/// 백엔드 `/v1/update/check` 응답의 `app` 칸.
#[derive(Debug, Default, Deserialize)]
#[allow(dead_code)]
pub struct BackendApp {
    #[serde(default)]
    pub available: bool,
    #[serde(default)]
    pub ready: bool,
    #[serde(default)]
    pub version: String,
    #[serde(default)]
    pub signature: String,
    #[serde(default)]
    pub latest_json: String,
    #[serde(default)]
    pub reason: String,
}

/// latest.json 의 판 · 서명이 서명된 목록(백엔드가 확인한 값)에 묶여 있는가. **순수 함수** — 윈도우에서도 시험한다.
///
/// - `newer`: 플러그인이 준 판이 지금 판보다 새것인가(비교 함수를 바꿔 끼우면 플러그인의 기본 「더 새것만」이 빠진다 — 여기서 다시 건다).
/// - `announced`: latest.json 의 판. `want_version` 과 같아야 한다(앞의 `v` 는 무시).
/// - `signatures`: latest.json 이 이 꾸러미에 준 서명 문자열들. 하나라도 `want_signature` 와 같아야 한다.
pub fn bound_to_manifest(
    newer: bool,
    announced: &str,
    signatures: &[&str],
    want_version: &str,
    want_signature: &str,
) -> bool {
    let want_signature = want_signature.trim();
    newer
        && !want_version.trim().is_empty()
        && !want_signature.is_empty()
        && announced.trim().trim_start_matches('v') == want_version.trim().trim_start_matches('v')
        && signatures.iter().any(|sig| sig.trim() == want_signature)
}

#[cfg(target_os = "macos")]
mod mac {
    use super::{bound_to_manifest, pubkey, BackendApp};
    use serde_json::{json, Value};
    use tauri::AppHandle;
    use tauri_plugin_updater::{RemoteReleaseInner, UpdaterExt};

    fn backend_app() -> Result<BackendApp, String> {
        let boot = crate::backend_bootstrap()?;
        let response: Value = ureq::AgentBuilder::new()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .post(&format!("{}/v1/update/check", boot.base_url))
            .set("X-JARVIS-TOKEN", &boot.control_token)
            .set("Content-Type", "application/json")
            .send_string("{}")
            .map_err(|error| format!("백엔드에 못 닿았습니다: {error}"))?
            .into_json()
            .map_err(|error| format!("백엔드 응답을 못 읽었습니다: {error}"))?;
        if response.get("kind").and_then(Value::as_str) != Some("mac") {
            return Err("백엔드가 맥 업데이트 응답을 주지 않았습니다".into());
        }
        if let Some(reason) = response.get("reason").and_then(Value::as_str) {
            if response.get("ok").and_then(Value::as_bool) == Some(false) || response.get("enabled").and_then(Value::as_bool) == Some(false) {
                return Err(reason.to_string());
            }
        }
        serde_json::from_value(response.get("app").cloned().unwrap_or(Value::Null))
            .map_err(|error| format!("백엔드 응답의 앱 칸을 못 읽었습니다: {error}"))
    }

    async fn bound_update(app: &AppHandle) -> Result<Option<tauri_plugin_updater::Update>, String> {
        let key = pubkey();
        if key.is_empty() {
            return Err("서명 열쇠가 아직 정해지지 않았습니다(update_pubkey.txt)".into());
        }
        let want = tauri::async_runtime::spawn_blocking(backend_app)
            .await
            .map_err(|error| error.to_string())??;
        if !want.available || !want.ready {
            return Err(if want.reason.is_empty() { "받을 앱 꾸러미가 없습니다".into() } else { want.reason });
        }
        let endpoint = tauri::Url::parse(&want.latest_json).map_err(|error| format!("latest.json 주소가 이상합니다: {error}"))?;
        let (want_version, want_signature) = (want.version.clone(), want.signature.clone());
        app.updater_builder()
            .pubkey(key)
            .endpoints(vec![endpoint])
            .map_err(|error| error.to_string())?
            .version_comparator(move |current, release| {
                let signatures: Vec<&str> = match &release.data {
                    RemoteReleaseInner::Dynamic(platform) => vec![platform.signature.as_str()],
                    RemoteReleaseInner::Static { platforms } => platforms.values().map(|p| p.signature.as_str()).collect(),
                };
                bound_to_manifest(
                    release.version > current,
                    &release.version.to_string(),
                    &signatures,
                    &want_version,
                    &want_signature,
                )
            })
            .build()
            .map_err(|error| error.to_string())?
            .check()
            .await
            .map_err(|error| error.to_string())
    }

    pub async fn check(app: AppHandle) -> Result<Value, String> {
        match bound_update(&app).await? {
            Some(update) => Ok(json!({"available": true, "version": update.version, "current": update.current_version})),
            None => Ok(json!({"available": false, "reason": "latest.json 이 서명된 목록과 맞지 않거나 새 판이 아닙니다"})),
        }
    }

    pub async fn install(app: AppHandle) -> Result<Value, String> {
        let Some(update) = bound_update(&app).await? else {
            return Err("받을 앱 꾸러미가 없습니다".into());
        };
        // 꾸러미 서명은 플러그인이 받으면서 확인한다 — 틀리면 여기서 오류로 끝나고 아무것도 안 바뀐다.
        update
            .download_and_install(|_, _| {}, || {})
            .await
            .map_err(|error| format!("꾸러미를 바꾸지 못했습니다: {error}"))?;
        app.restart();
    }
}

/// 맥 앱 꾸러미에 받을 것이 있나(서명된 목록에 묶인 것만). 바꾸지 않는다.
#[tauri::command]
pub async fn app_update_check(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    #[cfg(target_os = "macos")]
    {
        mac::check(app).await
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("맥에서만 씁니다 — 윈도우는 스토어가 갱신합니다".into())
    }
}

/// 맥 앱 꾸러미를 받아 통째로 바꾸고 다시 켠다.
#[tauri::command]
pub async fn app_update_install(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    #[cfg(target_os = "macos")]
    {
        mac::install(app).await
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("맥에서만 씁니다 — 윈도우는 스토어가 갱신합니다".into())
    }
}

/// 맥이면 업데이트 플러그인을 단다. 다른 OS 는 받은 그대로.
pub fn with_updater<R: tauri::Runtime>(builder: tauri::Builder<R>) -> tauri::Builder<R> {
    #[cfg(target_os = "macos")]
    {
        builder.plugin(tauri_plugin_updater::Builder::new().pubkey(pubkey()).build())
    }
    #[cfg(not(target_os = "macos"))]
    {
        builder
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SIG: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZQ==";

    #[test]
    fn a_bound_newer_release_passes() {
        assert!(bound_to_manifest(true, "0.4.1", &[SIG], "0.4.1", SIG));
        assert!(bound_to_manifest(true, "v0.4.1", &["other", SIG], "0.4.1", SIG));
    }

    #[test]
    fn an_inflated_version_with_an_old_signature_is_refused() {
        // 위협 3: latest.json 이 판 번호만 부풀리고 옛 꾸러미의 (진짜) 서명을 붙였다.
        assert!(!bound_to_manifest(true, "9.9.9", &["old-signature"], "0.4.1", SIG));
        assert!(!bound_to_manifest(true, "0.4.1", &["old-signature"], "0.4.1", SIG));
        assert!(!bound_to_manifest(true, "9.9.9", &[SIG], "0.4.1", SIG));
    }

    #[test]
    fn not_newer_is_refused_even_when_bound() {
        assert!(!bound_to_manifest(false, "0.4.1", &[SIG], "0.4.1", SIG));
    }

    #[test]
    fn empty_wants_are_refused() {
        assert!(!bound_to_manifest(true, "", &[""], "", ""));
        assert!(!bound_to_manifest(true, "0.4.1", &[""], "0.4.1", ""));
    }

    #[test]
    fn the_baked_key_is_the_founders_key() {
        // 대표가 만든 열쇠(11-16 · 키 id 601B24A83ED65B82). 자리는 파이썬과 같은 파일 하나 — 파이썬 시험이 키 id 를 풀어 본다.
        let key = pubkey();
        assert!(!key.is_empty() && !key.contains('#') && !key.contains('\n'));
        use base64::Engine;
        let text = String::from_utf8(base64::engine::general_purpose::STANDARD.decode(key.trim()).unwrap()).unwrap();
        assert!(text.contains("minisign public key: 601B24A83ED65B82"));
    }
}
