// 손자리 실행 도우미(SonjariEngine.app) — 손자리 본체(파이썬)를 띄우고 기다리기만 한다 (2026-11-18).
//
// 왜: 맥은 허락 창(문서 폴더 · 로컬 네트워크 · 다른 앱 조작 …)을 「책임 프로세스」 이름으로 묻는다. 본체가 맨 파이썬이면
//   「python3.12 가 … 하려고 합니다」로 떠서 손님에게 낯설다(11-17 새 계정 시험). 서명된 이 앱이 파이썬을 **자식으로** 띄우면
//   책임자가 이 앱이 되어 「손자리」 이름과 Info.plist 의 이유 문장으로 묻는다(Qt 「responsible process」 · Apple 포럼 731504).
//   그래서 자식을 띄울 때 책임을 떼어 주지 않는다(disclaim 안 함) — 일부러 그대로 물려준다.
//
// 쓰는 법(LaunchAgent): SonjariEngine <파이썬> -m alture_jarvis
//   받은 인자를 그대로 자식에게 주고, 끄기 신호(TERM · INT · HUP)는 자식에게 넘기고, 자식의 끝남 코드로 끝난다.
import Foundation

let arguments = Array(CommandLine.arguments.dropFirst())
guard let program = arguments.first else {
    FileHandle.standardError.write("사용법: SonjariEngine <파이썬> [인자…]\n".data(using: .utf8)!)
    exit(64)
}

let child = Process()
child.executableURL = URL(fileURLWithPath: program)
child.arguments = Array(arguments.dropFirst())
child.environment = ProcessInfo.processInfo.environment
child.currentDirectoryURL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)

var sources: [DispatchSourceSignal] = []
for number in [SIGTERM, SIGINT, SIGHUP] {
    signal(number, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
    source.setEventHandler {
        if child.isRunning { kill(child.processIdentifier, number) }
    }
    source.resume()
    sources.append(source)
}

child.terminationHandler = { finished in
    let code: Int32 = finished.terminationReason == .uncaughtSignal ? 128 + finished.terminationStatus : finished.terminationStatus
    exit(code)
}

do {
    try child.run()
} catch {
    FileHandle.standardError.write("손자리 본체를 띄우지 못했습니다: \(program) — \(error)\n".data(using: .utf8)!)
    exit(70)
}
dispatchMain()
