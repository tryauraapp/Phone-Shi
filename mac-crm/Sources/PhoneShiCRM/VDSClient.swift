import Foundation

struct VDSError: LocalizedError {
    var message: String
    var errorDescription: String? { message }
}

/// Talks to the VDS over the system `ssh` binary. Every call is synchronous
/// and must run off the main thread.
struct VDSClient {
    var settings: ConnectionSettings

    private var target: String { "\(settings.user)@\(settings.host)" }

    private var baseArguments: [String] {
        let key = (settings.keyPath as NSString).expandingTildeInPath
        return [
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=12",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=15",
            "-i", key,
            target,
        ]
    }

    @discardableResult
    func run(_ remote: String, stdin: Data? = nil, timeout: TimeInterval = 90) throws -> Data {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
        process.arguments = baseArguments + [remote]

        let input = Pipe(), output = Pipe(), errors = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors

        var errorData = Data()
        let errorGroup = DispatchGroup()
        errorGroup.enter()
        DispatchQueue.global().async {
            errorData = errors.fileHandleForReading.readDataToEndOfFile()
            errorGroup.leave()
        }

        do {
            try process.run()
        } catch {
            throw VDSError(message: "Could not start ssh: \(error.localizedDescription)")
        }

        if let stdin {
            input.fileHandleForWriting.write(stdin)
        }
        try? input.fileHandleForWriting.close()

        let timer = DispatchWorkItem { if process.isRunning { process.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: timer)

        let result = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        timer.cancel()
        errorGroup.wait()

        guard process.terminationStatus == 0 else {
            let text = String(data: errorData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let reason = text.isEmpty ? "ssh exited with status \(process.terminationStatus)" : text
            throw VDSError(message: reason)
        }
        return result
    }

    func inventory() throws -> Inventory {
        let data = try run("PHONE_SHI_ADB='\(settings.adbPath)' python3 -",
                           stdin: Data(InventoryScript.source.utf8))
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        do {
            return try decoder.decode(Inventory.self, from: data)
        } catch {
            let preview = String(data: data.prefix(300), encoding: .utf8) ?? ""
            throw VDSError(message: "Inventory could not be read: \(error.localizedDescription)\n\(preview)")
        }
    }

    func setPower(_ control: PhoneControl, on: Bool) throws {
        let verb = on ? "start" : "stop"
        let name = shellQuote(control.name)
        switch control.kind {
        case "systemd":
            try run("systemctl \(verb) \(name)")
        case "docker":
            try run("docker \(verb) \(name)")
        default:
            throw VDSError(message: "This phone has no start/stop controller on the VDS.")
        }
    }

    func screenshot(serial: String) throws -> Data {
        let adb = shellQuote(settings.adbPath)
        let data = try run("\(adb) -s \(shellQuote(serial)) exec-out screencap -p", timeout: 40)
        guard data.starts(with: [0x89, 0x50, 0x4E, 0x47]) else {
            throw VDSError(message: "The phone did not return a screenshot.")
        }
        return data
    }

    func sendKey(serial: String, keycode: Int) throws {
        let adb = shellQuote(settings.adbPath)
        try run("\(adb) -s \(shellQuote(serial)) shell input keyevent \(keycode)", timeout: 20)
    }

    static let setupLogDirectory = "/opt/android-vm/setup-logs"

    /// Starts the standard phone setup as a tracked background unit on the VDS.
    func createPhone(name: String, port: Int, grpcPort: Int) throws {
        let log = "\(Self.setupLogDirectory)/\(name).log"
        let create = "python3 \(shellQuote(settings.setupScript)) create --name \(shellQuote(name)) --port \(port) " +
                     "--grpc-port \(grpcPort) --duck-apk \(shellQuote(settings.duckApk))"
        let inner = "mkdir -p \(shellQuote(Self.setupLogDirectory)); " +
                    "echo \(shellQuote("phone-shi setup: " + create)) > \(shellQuote(log)); " +
                    "\(create) >> \(shellQuote(log)) 2>&1; echo PHONE_SHI_EXIT=$? >> \(shellQuote(log))"
        try run("systemd-run --unit=\(shellQuote("phone-setup-" + name)) --collect --quiet /bin/sh -c \(shellQuote(inner))",
                timeout: 30)
    }

    /// Resumes a retained incomplete setup without wiping it.
    func resumeSetup(name: String, directory: String) throws {
        let log = "\(Self.setupLogDirectory)/\(name).log"
        let resume = "python3 \(shellQuote(settings.setupScript)) resume --metadata \(shellQuote(directory + "/phone.json")) " +
                     "--duck-apk \(shellQuote(settings.duckApk))"
        let inner = "mkdir -p \(shellQuote(Self.setupLogDirectory)); echo \(shellQuote("phone-shi setup: " + resume)) >> \(shellQuote(log)); " +
                    "\(resume) >> \(shellQuote(log)) 2>&1; echo PHONE_SHI_EXIT=$? >> \(shellQuote(log))"
        try run("systemd-run --unit=\(shellQuote("phone-setup-" + name)) --collect --quiet /bin/sh -c \(shellQuote(inner))",
                timeout: 30)
    }

    /// Re-verifies a finished phone against its saved profile. Synchronous; takes a minute or two.
    func verifyPhone(directory: String) throws -> String {
        let data = try run("python3 \(shellQuote(settings.setupScript)) verify --metadata \(shellQuote(directory + "/phone.json")) 2>&1",
                           timeout: 400)
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    func setupLog(name: String) throws -> String {
        let data = try run("tail -n 300 \(shellQuote("\(Self.setupLogDirectory)/\(name).log")) 2>/dev/null || " +
                           "journalctl -u \(shellQuote("phone-setup-" + name)) --no-pager -n 300 -o cat", timeout: 30)
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// The numbered stages of the standard setup, as printed by `plan`.
    func setupPlan() throws -> [String] {
        let data = try run("python3 \(shellQuote(settings.setupScript)) plan", timeout: 30)
        return (String(data: data, encoding: .utf8) ?? "").split(separator: "\n").map(String.init)
    }

    func testConnection() throws -> String {
        let data = try run("hostname && uptime -p", timeout: 20)
        return String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? "connected"
    }

    private func shellQuote(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}
