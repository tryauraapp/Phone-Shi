import AppKit
import Combine
import Foundation

/// A phone streamed natively: the bridge helper (Python, reusing the repo's
/// gRPC/WebRTC viewer) runs as a child process, writes raw RGB frames to a
/// pipe and takes touch/key input back as JSON lines.
final class NativePhoneSession: ObservableObject {
    let serial: String
    @Published private(set) var image: CGImage?
    @Published private(set) var deviceSize: CGSize?
    @Published private(set) var state = "starting"
    @Published private(set) var error: String?
    @Published private(set) var frameCount = 0
    @Published private(set) var mode = "webrtc"
    @Published private(set) var rtcDenied = false

    private var process: Process?
    private var input: FileHandle?
    private var stopped = false
    private var settings: ConnectionSettings?
    private let readQueue = DispatchQueue(label: "phone-bridge-reader", qos: .userInteractive)
    private var pendingImage: CGImage?
    private var publishScheduled = false

    init(serial: String) { self.serial = serial }

    var statusLabel: String {
        switch state {
        case "connecting": return mode == "webrtc" ? "Connecting…" : "Connecting (screenshots)…"
        case "connected": return mode == "webrtc" ? "WebRTC" : "Screenshots"
        case "failed": return "Native view failed"
        case "ended": return "Stream ended"
        default: return state.capitalized
        }
    }

    // MARK: Lifecycle

    func start(settings: ConnectionSettings, mode: String = "webrtc") {
        self.settings = settings
        stopped = false
        self.mode = mode
        error = nil
        state = "connecting"
        let repo = (settings.repoPath as NSString).expandingTildeInPath
        let python = repo + "/.local/grpc-viewer-venv/bin/python"
        let helper = repo + "/mac-crm/Helper/phone_bridge.py"
        guard FileManager.default.isExecutableFile(atPath: python), FileManager.default.fileExists(atPath: helper) else {
            fail("Native viewer environment is missing. Run mac-crm/build_app.sh once to create .local/grpc-viewer-venv.")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [helper, "--serial", serial, "--host", settings.host, "--user", settings.user,
                             "--key", (settings.keyPath as NSString).expandingTildeInPath,
                             "--mode", mode, "--width", mode == "webrtc" ? "0" : "720"]
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        process.standardInput = stdin
        process.standardOutput = stdout
        process.standardError = stderr
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.processEnded() }
        }
        do {
            try process.run()
        } catch {
            fail("Could not start the phone bridge: \(error.localizedDescription)")
            return
        }
        self.process = process
        input = stdin.fileHandleForWriting
        readQueue.async { [weak self] in self?.readLoop(stdout.fileHandleForReading) }
        DispatchQueue.global(qos: .utility).async { [weak self] in self?.stderrLoop(stderr.fileHandleForReading) }
    }

    func restart() {
        guard let settings else { return }
        stop()
        start(settings: settings, mode: rtcDenied ? "screenshot" : "webrtc")
    }

    func stop() {
        stopped = true
        send(["type": "quit"])
        let process = self.process
        self.process = nil
        input = nil
        DispatchQueue.global().asyncAfter(deadline: .now() + 1) {
            if let process, process.isRunning { process.terminate() }
        }
    }

    private func fail(_ message: String) {
        error = message
        state = "failed"
    }

    private func processEnded() {
        guard !stopped else { return }
        if rtcDenied, mode == "webrtc", let settings {
            // The emulator refused the WebRTC service: fall back to screenshot frames.
            start(settings: settings, mode: "screenshot")
            return
        }
        if state != "failed" { state = "ended" }
    }

    // MARK: Input

    func touch(x: CGFloat, y: CGFloat, down: Bool) {
        send(["type": "touch", "x": Int(x.rounded()), "y": Int(y.rounded()), "down": down])
    }

    func key(_ name: String) {
        send(["type": "key", "key": name])
    }

    func text(_ text: String) {
        send(["type": "text", "text": text])
    }

    func refresh() {
        send(["type": "refresh"])
    }

    private func send(_ message: [String: Any]) {
        guard let input, let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        try? input.write(contentsOf: data + Data([0x0A]))
    }

    // MARK: Output

    private func stderrLoop(_ handle: FileHandle) {
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { return }
            let text = String(decoding: chunk, as: UTF8.self)
            if text.contains("not on the allowlist") {
                DispatchQueue.main.async { self.rtcDenied = true }
            }
            if text.contains("WebRTC connected") || text.contains("WebRTC completed") {
                DispatchQueue.main.async { if self.state == "connecting" { self.state = "connected" } }
            }
        }
    }

    private func readLoop(_ handle: FileHandle) {
        var buffer = Data()
        var offset = 0
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { return }
            buffer.append(chunk)
            while let consumed = parseMessage(buffer, at: offset) {
                offset += consumed
            }
            if offset > 0 {
                buffer.removeSubrange(0..<offset)
                offset = 0
            }
        }
    }

    /// Parses one bridge message at `offset`; returns its byte length or nil if incomplete.
    private func parseMessage(_ buffer: Data, at offset: Int) -> Int? {
        let available = buffer.count - offset
        guard available >= 8 else { return nil }
        let base = buffer.startIndex + offset
        guard buffer[base] == 0x50, buffer[base + 1] == 0x53, buffer[base + 2] == 0x46, buffer[base + 3] == 0x31 else {
            DispatchQueue.main.async { self.fail("Bridge protocol error") }
            return nil
        }
        let headerLength = Int(buffer[base + 4]) << 24 | Int(buffer[base + 5]) << 16 | Int(buffer[base + 6]) << 8 | Int(buffer[base + 7])
        guard available >= 8 + headerLength else { return nil }
        let headerData = buffer.subdata(in: (base + 8)..<(base + 8 + headerLength))
        guard let header = try? JSONSerialization.jsonObject(with: headerData) as? [String: Any],
              let type = header["type"] as? String else { return 8 + headerLength }
        var payloadLength = 0
        if type == "frame", let w = header["w"] as? Int, let h = header["h"] as? Int {
            payloadLength = w * h * 3
            guard available >= 8 + headerLength + payloadLength else { return nil }
            let start = base + 8 + headerLength
            let payload = buffer.subdata(in: start..<(start + payloadLength))
            if let image = Self.makeImage(width: w, height: h, rgb: payload) {
                publish(image)
            }
        } else {
            handle(header)
        }
        return 8 + headerLength + payloadLength
    }

    private static func makeImage(width: Int, height: Int, rgb: Data) -> CGImage? {
        guard let provider = CGDataProvider(data: rgb as CFData) else { return nil }
        return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 24, bytesPerRow: width * 3,
                       space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent)
    }

    private func publish(_ image: CGImage) {
        DispatchQueue.main.async {
            self.image = image
            self.frameCount += 1
            if self.state == "connecting" { self.state = "connected" }
        }
    }

    private func handle(_ header: [String: Any]) {
        DispatchQueue.main.async {
            switch header["type"] as? String {
            case "info":
                if let w = header["deviceWidth"] as? Int, let h = header["deviceHeight"] as? Int {
                    self.deviceSize = CGSize(width: w, height: h)
                }
            case "state":
                if let state = header["state"] as? String, state == "failed" || state == "closed" {
                    if !self.rtcDenied { self.error = "WebRTC \(state)" }
                }
            case "error":
                if let message = header["message"] as? String, !self.stopped, !self.rtcDenied {
                    if message != "stream ended" { self.error = message }
                }
            default:
                break
            }
        }
    }
}

/// One native session per open phone.
@MainActor
final class NativePhoneSessions: ObservableObject {
    static let shared = NativePhoneSessions()
    @Published private(set) var sessions: [String: NativePhoneSession] = [:]

    func session(for serial: String, settings: ConnectionSettings) -> NativePhoneSession {
        if let existing = sessions[serial] { return existing }
        let session = NativePhoneSession(serial: serial)
        session.start(settings: settings)
        sessions[serial] = session
        return session
    }

    func close(serial: String) {
        sessions[serial]?.stop()
        sessions.removeValue(forKey: serial)
    }
}
