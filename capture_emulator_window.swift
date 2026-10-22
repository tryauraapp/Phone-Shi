import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

guard CommandLine.arguments.count == 3 else {
    fail("Usage: bash capture_emulator_window.sh AVD_NAME OUTPUT.png")
}
let avd = CommandLine.arguments[1]
let output = URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL
guard !avd.isEmpty else { fail("AVD name must not be empty.") }
guard !FileManager.default.fileExists(atPath: output.path) else {
    fail("Output already exists; choose another filename.")
}
let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let matches = windows.filter { window in
    let owner = window[kCGWindowOwnerName as String] as? String ?? ""
    let title = window[kCGWindowName as String] as? String ?? ""
    // Match the complete AVD name in the normal Android Emulator window title.
    return owner.lowercased().contains("qemu") &&
        title.contains(" - " + avd + ":") &&
        (window[kCGWindowLayer as String] as? Int) == 0
}
guard matches.count == 1, let window = matches.first,
      let number = window[kCGWindowNumber as String] as? UInt32 else {
    fail("Expected one visible emulator window for \(avd); found \(matches.count). Show its window and allow macOS Screen Recording access.")
}
try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
task.arguments = ["-x", "-o", "-l", String(number), output.path]
try task.run()
task.waitUntilExit()
guard task.terminationStatus == 0, FileManager.default.fileExists(atPath: output.path) else {
    fail("Window capture failed; no desktop capture fallback was used.")
}
print(output.path)
