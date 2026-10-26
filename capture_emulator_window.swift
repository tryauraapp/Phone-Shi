import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

let idOnly = CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--window-id"
guard CommandLine.arguments.count == 3 else {
    fail("Usage: bash capture_emulator_window.sh AVD_NAME OUTPUT.png\n       bash capture_emulator_window.sh --window-id AVD_NAME")
}
let avd = CommandLine.arguments[idOnly ? 2 : 1]
guard !avd.isEmpty else { fail("AVD name must not be empty.") }
func qemuPid(forAvd avd: String) -> Int32? {
    let ps = Process()
    let pipe = Pipe()
    ps.executableURL = URL(fileURLWithPath: "/bin/ps")
    ps.arguments = ["-axo", "pid=,command="]
    ps.standardOutput = pipe
    ps.standardError = FileHandle.nullDevice
    guard (try? ps.run()) != nil else { return nil }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    ps.waitUntilExit()
    guard let text = String(data: data, encoding: .utf8) else { return nil }
    for rawLine in text.split(separator: "\n") {
        let line = rawLine.trimmingCharacters(in: .whitespaces)
        guard line.contains("qemu-system") &&
              (line.contains("-avd \(avd) ") || line.hasSuffix("-avd \(avd)") || line.contains("@\(avd)")) else {
            continue
        }
        let parts = line.split(maxSplits: 1, whereSeparator: { $0.isWhitespace })
        if let first = parts.first, let pid = Int32(first) {
            return pid
        }
    }
    return nil
}

func findAdbExecutable() -> String {
    let candidates = [
        ProcessInfo.processInfo.environment["ADB"],
        "\(NSHomeDirectory())/Library/Android/sdk/platform-tools/adb",
        "/opt/homebrew/bin/adb",
        "/usr/local/bin/adb"
    ].compactMap { $0 }
    for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
        return path
    }
    return "adb"
}

func captureViaEmulatorConsole(avd: String, outputPath: String) -> Bool {
    let adb = findAdbExecutable()
    let devicesTask = Process()
    let pipe = Pipe()
    devicesTask.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    devicesTask.arguments = [adb, "devices"]
    devicesTask.standardOutput = pipe
    devicesTask.standardError = FileHandle.nullDevice
    guard (try? devicesTask.run()) != nil else { return false }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    devicesTask.waitUntilExit()
    guard let text = String(data: data, encoding: .utf8) else { return false }
    for line in text.split(separator: "\n") {
        let parts = line.split(whereSeparator: { $0.isWhitespace })
        guard parts.count >= 2, parts[1] == "device", parts[0].hasPrefix("emulator-") else { continue }
        let serial = String(parts[0])
        let nameTask = Process()
        let namePipe = Pipe()
        nameTask.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        nameTask.arguments = [adb, "-s", serial, "emu", "avd", "name"]
        nameTask.standardOutput = namePipe
        nameTask.standardError = FileHandle.nullDevice
        guard (try? nameTask.run()) != nil else { continue }
        let nameData = namePipe.fileHandleForReading.readDataToEndOfFile()
        nameTask.waitUntilExit()
        let foundAvd = (String(data: nameData, encoding: .utf8) ?? "")
            .split(whereSeparator: { $0.isNewline })
            .first
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) } ?? ""
        guard foundAvd == avd else { continue }
        let shotTask = Process()
        shotTask.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        shotTask.arguments = [adb, "-s", serial, "emu", "screenrecord", "screenshot", outputPath]
        shotTask.standardOutput = FileHandle.nullDevice
        shotTask.standardError = FileHandle.nullDevice
        guard (try? shotTask.run()) != nil else { return false }
        shotTask.waitUntilExit()
        return shotTask.terminationStatus == 0 && FileManager.default.fileExists(atPath: outputPath)
    }
    return false
}

let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
var matches = windows.filter { window in
    let owner = window[kCGWindowOwnerName as String] as? String ?? ""
    let title = window[kCGWindowName as String] as? String ?? ""
    // Match the complete AVD name in the normal Android Emulator window title.
    return owner.lowercased().contains("qemu") &&
        title.contains(" - " + avd + ":") &&
        (window[kCGWindowLayer as String] as? Int) == 0
}
if matches.isEmpty, let targetPid = qemuPid(forAvd: avd) {
    matches = windows.filter { window in
        guard (window[kCGWindowOwnerPID as String] as? Int32) == targetPid,
              (window[kCGWindowLayer as String] as? Int) == 0,
              let bounds = window[kCGWindowBounds as String] as? [String: Any],
              let width = bounds["Width"] as? Double,
              let height = bounds["Height"] as? Double else {
            return false
        }
        return width > 150 && height > width
    }
}
guard matches.count == 1, let window = matches.first,
      let number = window[kCGWindowNumber as String] as? UInt32 else {
    fail("Expected one visible emulator window for \(avd); found \(matches.count). Show its window and allow macOS Screen Recording access.")
}
if idOnly {
    print(number)
    exit(0)
}
let output = URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL
guard !FileManager.default.fileExists(atPath: output.path) else {
    fail("Output already exists; choose another filename.")
}
try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
task.arguments = ["-x", "-o", "-l", String(number), output.path]
task.standardError = FileHandle.nullDevice
try task.run()
task.waitUntilExit()
if task.terminationStatus != 0 || !FileManager.default.fileExists(atPath: output.path) {
    guard captureViaEmulatorConsole(avd: avd, outputPath: output.path) else {
        fail("Window capture failed; no desktop capture fallback was used.")
    }
}
print(output.path)
