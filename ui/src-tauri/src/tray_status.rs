//! 트레이 아이콘 = 상태 표시등 (2026-09-15, 로고 시안 A 「고리와 점」 확정).
//!
//! 앱 안의 표식(`ui/src/workspace/JarvisMark.tsx`)은 이미 색과 움직임으로 상태를 말한다. 창을 닫아도 남는
//! 트레이가 **같은 규칙**을 따르게 한다 — 사용자는 한 모양만 익히면 된다.
//!
//! | 상태 | 색 | 움직임 |
//! |---|---|---|
//! | working · routing · transcribing | 보라 | 고리가 돈다 |
//! | listening | 보라 | 숨쉬기 |
//! | waiting_approval · waiting_continuation | 호박 | 숨쉬기 — 사람이 눌러야 움직인다 |
//! | error | 빨강 | 멈춤 |
//! | 백엔드에 못 닿음 | 회색 | 멈춤 |
//! | 그 밖(idle·speaking·stopped) | 보라 | 멈춤 |
//!
//! 창이 닫혀 있어도 돌아야 하므로 화면(JS)이 아니라 여기서 백엔드 `/v1/state`(토큰 없음, 가벼움)를 읽는다.
//! 프레임은 `scripts/make_brand_icons.py` 가 만든 32×32 RGBA 원시 바이트다 — 이미지 해독 기능을 켜지 않는다.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;
use tauri::{image::Image, tray::TrayIcon, Runtime};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tone {
    Brand,
    Signal,
    Stop,
    Offline,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Motion {
    Still,
    Sweeping,
    Breathing,
}

/// JarvisMark.tsx 의 `tone`·`motion` 과 같은 규칙. `None` 은 백엔드에 못 닿음.
pub fn classify(state: Option<&str>) -> (Tone, Motion) {
    match state {
        None => (Tone::Offline, Motion::Still),
        Some("error") => (Tone::Stop, Motion::Still),
        Some("waiting_approval") | Some("waiting_continuation") => (Tone::Signal, Motion::Breathing),
        Some("working") | Some("routing") | Some("transcribing") => (Tone::Brand, Motion::Sweeping),
        Some("listening") => (Tone::Brand, Motion::Breathing),
        Some(_) => (Tone::Brand, Motion::Still),
    }
}

/// 트레이에 마우스를 올리면 보이는 말. 사람이 아는 말로.
pub fn label(state: Option<&str>) -> &'static str {
    match state {
        None => "연결 끊김",
        Some("idle") => "쉬는 중",
        Some("listening") => "듣는 중",
        Some("transcribing") => "받아 적는 중",
        Some("routing") => "할 일을 고르는 중",
        Some("working") => "일하는 중",
        Some("speaking") => "말하는 중",
        Some("waiting_approval") => "승인을 기다립니다",
        Some("waiting_continuation") => "계속할지 기다립니다",
        Some("error") => "멈췄습니다 — 확인이 필요합니다",
        Some("stopped") => "꺼져 있습니다",
        Some(_) => "",
    }
}

const BRAND: [&[u8]; 8] = [
    include_bytes!("../icons/tray/brand_0.rgba"),
    include_bytes!("../icons/tray/brand_1.rgba"),
    include_bytes!("../icons/tray/brand_2.rgba"),
    include_bytes!("../icons/tray/brand_3.rgba"),
    include_bytes!("../icons/tray/brand_4.rgba"),
    include_bytes!("../icons/tray/brand_5.rgba"),
    include_bytes!("../icons/tray/brand_6.rgba"),
    include_bytes!("../icons/tray/brand_7.rgba"),
];
const BRAND_DIM: &[u8] = include_bytes!("../icons/tray/brand_dim.rgba");
const SIGNAL_ON: &[u8] = include_bytes!("../icons/tray/signal_on.rgba");
const SIGNAL_DIM: &[u8] = include_bytes!("../icons/tray/signal_dim.rgba");
const STOP: &[u8] = include_bytes!("../icons/tray/stop.rgba");
const OFFLINE: &[u8] = include_bytes!("../icons/tray/offline.rgba");
const SIDE: u32 = 32;

/// 틱(150ms)마다 보여 줄 프레임. 한 바퀴 8 프레임 = 1.2초, 숨쉬기는 0.9초마다 밝기가 바뀐다.
pub fn frame(tone: Tone, motion: Motion, tick: u64) -> &'static [u8] {
    let breath_on = (tick / 6) % 2 == 0;
    match (tone, motion) {
        (Tone::Brand, Motion::Sweeping) => BRAND[(tick % 8) as usize],
        (Tone::Brand, Motion::Breathing) => {
            if breath_on {
                BRAND[0]
            } else {
                BRAND_DIM
            }
        }
        (Tone::Brand, Motion::Still) => BRAND[0],
        (Tone::Signal, _) => {
            if breath_on || motion == Motion::Still {
                SIGNAL_ON
            } else {
                SIGNAL_DIM
            }
        }
        (Tone::Stop, _) => STOP,
        (Tone::Offline, _) => OFFLINE,
    }
}

/// `{"state":"working",...}` 에서 상태 한 낱말만. JSON 전체를 풀 필요가 없다.
pub fn parse_state(body: &str) -> Option<String> {
    let key = "\"state\"";
    let at = body.find(key)? + key.len();
    let rest = body[at..].trim_start().strip_prefix(':')?.trim_start().strip_prefix('"')?;
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

fn fetch_state(port: u16) -> Option<String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(400)).ok()?;
    stream.set_read_timeout(Some(Duration::from_millis(1500))).ok()?;
    stream
        .write_all(b"GET /v1/state HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .ok()?;
    let mut raw = String::new();
    stream.read_to_string(&mut raw).ok()?;
    let (head, body) = raw.split_once("\r\n\r\n")?;
    if !head.starts_with("HTTP/1.1 200") && !head.starts_with("HTTP/1.0 200") {
        return None;
    }
    parse_state(body)
}

/// 트레이를 상태 표시등으로 돌린다. 앱이 끝나면 스레드도 같이 끝난다(데몬처럼 둔다).
pub fn spawn<R: Runtime>(tray: TrayIcon<R>, port: u16, title: &'static str) {
    std::thread::Builder::new()
        .name("ontelic-tray-status".into())
        .spawn(move || {
            let mut tick: u64 = 0;
            let mut state: Option<String> = None;
            let mut shown: Option<*const u8> = None;
            let mut shown_label = String::new();
            loop {
                if tick % 10 == 0 {
                    // 1.5초마다 읽는다 — 상태는 사람이 보는 속도로만 바뀌면 된다.
                    state = fetch_state(port);
                }
                let (tone, motion) = classify(state.as_deref());
                let bytes = frame(tone, motion, tick);
                if shown != Some(bytes.as_ptr()) {
                    let _ = tray.set_icon(Some(Image::new_owned(bytes.to_vec(), SIDE, SIDE)));
                    shown = Some(bytes.as_ptr());
                }
                let words = label(state.as_deref());
                let tooltip = if words.is_empty() { title.to_string() } else { format!("{title} · {words}") };
                if tooltip != shown_label {
                    let _ = tray.set_tooltip(Some(tooltip.as_str()));
                    shown_label = tooltip;
                }
                tick = tick.wrapping_add(1);
                std::thread::sleep(Duration::from_millis(150));
            }
        })
        .ok();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn states_map_like_the_in_app_mark() {
        assert_eq!(classify(Some("working")), (Tone::Brand, Motion::Sweeping));
        assert_eq!(classify(Some("routing")), (Tone::Brand, Motion::Sweeping));
        assert_eq!(classify(Some("listening")), (Tone::Brand, Motion::Breathing));
        assert_eq!(classify(Some("waiting_approval")), (Tone::Signal, Motion::Breathing));
        assert_eq!(classify(Some("waiting_continuation")), (Tone::Signal, Motion::Breathing));
        assert_eq!(classify(Some("error")), (Tone::Stop, Motion::Still));
        assert_eq!(classify(Some("idle")), (Tone::Brand, Motion::Still));
        assert_eq!(classify(None), (Tone::Offline, Motion::Still));
    }

    #[test]
    fn frames_are_32px_rgba_and_the_ring_actually_turns() {
        for bytes in BRAND.iter().chain([BRAND_DIM, SIGNAL_ON, SIGNAL_DIM, STOP, OFFLINE].iter()) {
            assert_eq!(bytes.len(), (SIDE * SIDE * 4) as usize);
        }
        let seen: std::collections::HashSet<_> = (0..8).map(|t| frame(Tone::Brand, Motion::Sweeping, t).as_ptr()).collect();
        assert_eq!(seen.len(), 8);
        assert_ne!(frame(Tone::Signal, Motion::Breathing, 0).as_ptr(), frame(Tone::Signal, Motion::Breathing, 6).as_ptr());
        assert_eq!(frame(Tone::Stop, Motion::Still, 3).as_ptr(), frame(Tone::Stop, Motion::Still, 9).as_ptr());
    }

    #[test]
    fn state_is_read_without_a_json_parser() {
        assert_eq!(parse_state(r#"{"state":"working","changed_at":1}"#).as_deref(), Some("working"));
        assert_eq!(parse_state(r#"{ "state" : "waiting_approval" }"#).as_deref(), Some("waiting_approval"));
        assert_eq!(parse_state(r#"{"ok":true}"#), None);
    }
}
