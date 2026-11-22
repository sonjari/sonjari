// 손자리 맥 음성 도우미 (2026-11-16 · 맥판 음성)
//
// 하는 일 셋 — 결과는 늘 JSON 한 줄(표준 출력 또는 --result 파일):
//   probe                                   이 맥에서 한국어 받아쓰기를 기기 안에서 할 수 있나 · 마이크 허락 상태
//   record --out <wav> --stop-file <경로>     마이크를 녹음한다. stop 파일이 생기면(또는 --max-sec) 멈추고 파일을 닫는다
//   transcribe --in <wav> [--locale ko-KR]  소리 파일을 받아쓴다
//
// ★ 기기 안에서만 받아쓴다. 서버로 보내는 길은 코드에 없다.
//   macOS 26 이상: SpeechTranscriber(SpeechAnalyzer) — 모델은 이 맥에 설치된 것(AssetInventory)만 쓴다.
//                  설치 안 됐으면 내려받지 않고 아래 길로 간다(모델 받기도 사람이 정할 일).
//   그 아래 · 위가 안 될 때: SFSpeechRecognizer + requiresOnDeviceRecognition = true
//                  (애플 문서: 「true 면 소리를 네트워크로 보내지 않는다」). 기기 안 처리를 지원하지 않으면 실패로 끝낸다.
//
// ★ 왜 파이썬(pyobjc)이 아니라 이 도우미인가: SpeechTranscriber 는 Swift 전용 API 이고, 마이크 허락 창은
//   허락을 구하는 앱의 Info.plist 설명(NSMicrophoneUsageDescription)이 있어야 뜬다 — 백엔드의 파이썬 실행 파일엔 없다.
//   그래서 백엔드는 이 앱을 `open` 으로 띄워 허락의 주인이 「손자리 음성」이 되게 한다.
import AVFoundation
import CoreAudio
import Foundation
import Speech

// MARK: - 공통

func emit(_ object: [String: Any]) -> Never {
    let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data("{\"ok\":false}".utf8)
    let line = String(data: data, encoding: .utf8) ?? "{\"ok\":false}"
    if let path = argValue("--result") {
        try? (line + "\n").write(toFile: path, atomically: true, encoding: .utf8)
    }
    print(line)
    fflush(stdout)
    exit((object["ok"] as? Bool) == true ? 0 : 1)
}

func argValue(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: name), index + 1 < args.count else { return nil }
    return args[index + 1]
}

func waitAsync<T>(_ body: @escaping () async -> T) -> T {
    let semaphore = DispatchSemaphore(value: 0)
    var value: T?
    Task {
        value = await body()
        semaphore.signal()
    }
    semaphore.wait()
    return value!
}

func micStatus() -> String {
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized: return "authorized"
    case .denied: return "denied"
    case .restricted: return "restricted"
    case .notDetermined: return "not_determined"
    @unknown default: return "unknown"
    }
}

/// 기본 소리 입력 장치의 입력 채널 수(장치가 없으면 0).
///
/// ★ 2026-11-22 맥미니(본체 마이크 없음 · 모니터 · 헤드폰 · 스피커 모두 출력만): `inputNode.outputFormat` 은
///   0 이 아닌 형식을 돌려줘 아래 형식 검사를 지나쳤고, `installTap` 이 Objective-C 예외를 던져 도우미가
///   통째로 죽었다(SIGABRT · 결과 파일 없음 → 화면 「Load failed」). Swift 는 그 예외를 잡을 수 없으므로
///   연결하기 **전에** 실제 장치를 CoreAudio 로 센다.
func defaultInputChannels() -> Int {
    var device = AudioObjectID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice,
                                             mScope: kAudioObjectPropertyScopeGlobal,
                                             mElement: kAudioObjectPropertyElementMain)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device) == noErr,
          device != AudioObjectID(kAudioObjectUnknown) else { return 0 }
    address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
                                         mScope: kAudioDevicePropertyScopeInput,
                                         mElement: kAudioObjectPropertyElementMain)
    var bytes: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &bytes) == noErr, bytes > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(bytes), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &bytes, raw) == noErr else { return 0 }
    let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return list.reduce(0) { $0 + Int($1.mNumberChannels) }
}

let localeId = argValue("--locale") ?? "ko-KR"
let locale = Locale(identifier: localeId)

// MARK: - probe

func probe() -> Never {
    // input_channels: 마이크 장치가 있는지(허락과 다른 질문). 없어도 받아쓰기 자체는 되므로 ok 는 바꾸지 않는다.
    let channels = defaultInputChannels()
    var result: [String: Any] = ["ok": true, "locale": localeId, "mic": micStatus(),
                                 "input_device": channels > 0, "input_channels": channels]
    let version = ProcessInfo.processInfo.operatingSystemVersion
    result["macos"] = "\(version.majorVersion).\(version.minorVersion)"
    if let recognizer = SFSpeechRecognizer(locale: locale) {
        result["sf_on_device"] = recognizer.supportsOnDeviceRecognition
    } else {
        result["sf_on_device"] = false
    }
    if #available(macOS 26.0, *) {
        let (supported, installed) = waitAsync { () async -> (Bool, Bool) in
            let match = await SpeechTranscriber.supportedLocale(equivalentTo: locale)
            let installedLocales = await SpeechTranscriber.installedLocales
            let wanted = match?.identifier(.bcp47) ?? localeId
            return (match != nil, installedLocales.contains { $0.identifier(.bcp47) == wanted })
        }
        result["transcriber_supported"] = supported
        result["transcriber_installed"] = installed
    } else {
        result["transcriber_supported"] = false
        result["transcriber_installed"] = false
    }
    let onDevice = (result["transcriber_installed"] as? Bool == true) || (result["sf_on_device"] as? Bool == true)
    result["on_device"] = onDevice
    if !onDevice {
        result["ok"] = false
        result["error"] = "on_device_unsupported"
    }
    emit(result)
}

// MARK: - transcribe

@available(macOS 26.0, *)
func transcribeWithAnalyzer(_ url: URL) async throws -> String {
    guard let match = await SpeechTranscriber.supportedLocale(equivalentTo: locale) else {
        throw NSError(domain: "sonjari", code: 1, userInfo: [NSLocalizedDescriptionKey: "transcriber_locale_unsupported"])
    }
    let installed = await SpeechTranscriber.installedLocales
    guard installed.contains(where: { $0.identifier(.bcp47) == match.identifier(.bcp47) }) else {
        throw NSError(domain: "sonjari", code: 2, userInfo: [NSLocalizedDescriptionKey: "transcriber_asset_not_installed"])
    }
    let transcriber = SpeechTranscriber(locale: match, transcriptionOptions: [], reportingOptions: [], attributeOptions: [])
    let file = try AVAudioFile(forReading: url)
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    async let text: String = transcriber.results.reduce("") { $0 + String($1.text.characters) }
    if let last = try await analyzer.analyzeSequence(from: file) {
        try await analyzer.finalizeAndFinish(through: last)
    } else {
        await analyzer.cancelAndFinishNow()
    }
    return try await text
}

func transcribeOnDeviceSF(_ url: URL) -> (String?, String?) {
    guard let recognizer = SFSpeechRecognizer(locale: locale) else { return (nil, "sf_locale_unsupported") }
    guard recognizer.supportsOnDeviceRecognition else { return (nil, "on_device_unsupported") }
    // 옛 API 는 음성 인식 허락이 있어야 돈다. 없으면 묻는다(허락 창은 사람이 누른다).
    if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
        let semaphore = DispatchSemaphore(value: 0)
        SFSpeechRecognizer.requestAuthorization { _ in semaphore.signal() }
        semaphore.wait()
    }
    guard SFSpeechRecognizer.authorizationStatus() == .authorized else { return (nil, "speech_permission_denied") }
    let request = SFSpeechURLRecognitionRequest(url: url)
    request.requiresOnDeviceRecognition = true  // ★ 서버로 보내지 않는다 — 이 줄이 빠지면 안 된다
    request.shouldReportPartialResults = false
    let semaphore = DispatchSemaphore(value: 0)
    var text: String?
    var failure: String?
    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result, result.isFinal {
            text = result.bestTranscription.formattedString
            semaphore.signal()
        } else if let error {
            failure = error.localizedDescription
            semaphore.signal()
        }
    }
    if semaphore.wait(timeout: .now() + 120) == .timedOut {
        task.cancel()
        return (nil, "timeout")
    }
    return (text, failure)
}

func transcribe() -> Never {
    guard let input = argValue("--in") else { emit(["ok": false, "error": "missing_in"]) }
    let url = URL(fileURLWithPath: input)
    guard FileManager.default.fileExists(atPath: input) else { emit(["ok": false, "error": "input_missing"]) }
    let started = Date()
    var analyzerError = ""
    if #available(macOS 26.0, *) {
        let outcome = waitAsync { () async -> (String?, String) in
            do { return (try await transcribeWithAnalyzer(url), "") } catch { return (nil, error.localizedDescription) }
        }
        if let text = outcome.0 {
            emit(["ok": true, "text": text.trimmingCharacters(in: .whitespacesAndNewlines), "engine": "speech_transcriber",
                  "on_device": true, "locale": localeId, "ms": Int(Date().timeIntervalSince(started) * 1000)])
        }
        analyzerError = outcome.1
    }
    let (text, error) = transcribeOnDeviceSF(url)
    if let text {
        emit(["ok": true, "text": text, "engine": "sf_on_device", "on_device": true, "locale": localeId,
              "ms": Int(Date().timeIntervalSince(started) * 1000), "analyzer_error": analyzerError])
    }
    emit(["ok": false, "error": error ?? "transcribe_failed", "analyzer_error": analyzerError])
}

// MARK: - record

func requestMic() -> Bool {
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized: return true
    case .notDetermined:
        let semaphore = DispatchSemaphore(value: 0)
        var granted = false
        AVCaptureDevice.requestAccess(for: .audio) { ok in granted = ok; semaphore.signal() }
        semaphore.wait()
        return granted
    default: return false
    }
}

func record() -> Never {
    guard let out = argValue("--out"), let stopFile = argValue("--stop-file") else {
        emit(["ok": false, "error": "missing_out_or_stop_file"])
    }
    let maxSec = Double(argValue("--max-sec") ?? "") ?? 120
    // 장치부터 — 마이크가 없으면 허락 창을 띄울 까닭도 없다.
    guard defaultInputChannels() > 0 else { emit(["ok": false, "error": "no_input_device", "input_channels": 0]) }
    guard requestMic() else { emit(["ok": false, "error": "mic_permission_denied", "mic": micStatus()]) }
    let engine = AVAudioEngine()
    let input = engine.inputNode
    let hardware = input.inputFormat(forBus: 0)
    let format = input.outputFormat(forBus: 0)
    guard hardware.sampleRate > 0, hardware.channelCount > 0, format.sampleRate > 0, format.channelCount > 0 else {
        emit(["ok": false, "error": "no_input_device"])
    }
    let file: AVAudioFile
    do {
        // 받은 그대로(보통 float32) WAV 로 쓴다 — 받아쓰기는 파일 형식을 스스로 맞춘다.
        file = try AVAudioFile(forWriting: URL(fileURLWithPath: out), settings: format.settings,
                               commonFormat: format.commonFormat, interleaved: format.isInterleaved)
    } catch {
        emit(["ok": false, "error": "open_output_failed: \(error.localizedDescription)"])
    }
    var frames: AVAudioFramePosition = 0
    var writeError = ""
    input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
        do { try file.write(from: buffer); frames += AVAudioFramePosition(buffer.frameLength) } catch { writeError = error.localizedDescription }
    }
    do { try engine.start() } catch { emit(["ok": false, "error": "engine_start_failed: \(error.localizedDescription)"]) }
    // 녹음이 시작됐다는 표시 — 백엔드가 「듣는 중」을 확인한다.
    FileManager.default.createFile(atPath: out + ".started", contents: Data())
    let started = Date()
    var reason = "stop_file"
    while !FileManager.default.fileExists(atPath: stopFile) {
        if Date().timeIntervalSince(started) > maxSec { reason = "max_sec"; break }
        Thread.sleep(forTimeInterval: 0.05)
    }
    input.removeTap(onBus: 0)
    engine.stop()
    try? FileManager.default.removeItem(atPath: out + ".started")
    var result: [String: Any] = ["ok": writeError.isEmpty && frames > 0, "path": out, "frames": frames,
                                 "seconds": Double(frames) / format.sampleRate, "sample_rate": format.sampleRate,
                                 "channels": Int(format.channelCount), "stopped_by": reason]
    if !writeError.isEmpty { result["error"] = "write_failed: \(writeError)" } else if frames == 0 { result["error"] = "no_audio" }
    emit(result)
}

// MARK: - 시작

switch CommandLine.arguments.dropFirst().first ?? "" {
case "probe": probe()
case "transcribe": transcribe()
case "record": record()
default: emit(["ok": false, "error": "usage: probe | record --out W --stop-file S | transcribe --in W"])
}
