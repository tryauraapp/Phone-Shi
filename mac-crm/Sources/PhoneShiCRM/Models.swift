import Foundation

// MARK: - Records kept on the Mac

struct Creator: Identifiable, Codable, Hashable {
    var id = UUID()
    var name: String
    var instagram = ""
    var tiktok = ""
    var onlyfans = ""
    var notes = ""
    var createdAt = Date()
}

enum PhoneStatus: String, Codable, CaseIterable, Identifiable {
    case active, paused, retired
    var id: String { rawValue }
    var label: String { rawValue.capitalized }
}

struct PhoneRecord: Identifiable, Codable, Hashable {
    var id: String { serial }
    var serial: String
    var nickname = ""
    var creatorID: UUID?
    var status: PhoneStatus = .active
    var primaryApp = ""
    var notes = ""
    var firstSeen = Date()
}

enum SnapStatus: String, Codable, CaseIterable, Identifiable {
    case warming, active, locked, banned
    var id: String { rawValue }
    var label: String { rawValue.capitalized }
}

struct SnapAccount: Identifiable, Codable, Hashable {
    var id = UUID()
    var username: String
    var displayName = ""
    var email = ""
    var phoneNumber = ""
    var status: SnapStatus = .warming
    var creatorID: UUID?
    var phoneSerial = ""
    var notes = ""
    var createdAt = Date()
}

struct ConnectionSettings: Codable, Hashable {
    var host = "13.140.66.200"
    var user = "root"
    var keyPath = "~/.ssh/id_ed25519"
    var adbPath = "/opt/android-vm/sdk/platform-tools/adb"
    var viewerBase = "https://13.140.66.200"
    var autoRefreshSeconds = 60
}

// MARK: - Live inventory from the VDS

struct PhoneControl: Codable, Hashable {
    var kind: String
    var name: String
    var detail: String
    var active: Bool
    var serial: String
}

struct LivePhone: Codable, Hashable, Identifiable {
    var id: String { serial }
    var serial: String
    var state: String
    var manufacturer: String
    var model: String
    var product: String
    var androidVersion: String
    var sdk: String
    var bootCompleted: Bool
    var foregroundPackage: String
    var packages: [String]
    var control: PhoneControl?

    var isOnline: Bool { state == "device" }

    var modelLabel: String {
        if model.isEmpty { return "Unknown" }
        if model.hasPrefix("SM-S93") { return "Galaxy S25" }
        if model.hasPrefix("sdk_gphone") { return "Google emulator" }
        return model
    }

    var backendLabel: String {
        switch control?.kind {
        case "docker": return "Redroid container"
        case "systemd": return "Android emulator"
        default: return "Unmanaged"
        }
    }
}

struct HostInfo: Codable, Hashable {
    var hostname: String
    var uptime: String
    var load: String
    var memTotalMB: Int
    var memUsedMB: Int
    var diskUsedPercent: Int
    var cpuCount: Int
}

struct Inventory: Codable, Hashable {
    var capturedAt: Date
    var host: HostInfo
    var phones: [LivePhone]
    var controllers: [PhoneControl]
}

// MARK: - Combined row shown in the UI

struct PhoneRow: Identifiable, Hashable {
    let serial: String
    let live: LivePhone?
    let record: PhoneRecord
    var id: String { serial }

    var displayName: String { record.nickname.isEmpty ? serial : record.nickname }
    var modelLabel: String { live?.modelLabel ?? "Unknown" }
    var stateLabel: String {
        guard let live else { return "Not seen" }
        if live.state == "offline" { return "Stopped" }
        if live.state != "device" { return live.state.capitalized }
        return live.bootCompleted ? "Online" : "Booting"
    }
    var isOnline: Bool { live?.isOnline ?? false }
}

struct AppStat: Identifiable, Hashable {
    var id: String { package }
    let package: String
    let name: String
    let serials: [String]
    var phoneCount: Int { serials.count }
}

struct CountRow: Identifiable, Hashable {
    let label: String
    let count: Int
    var id: String { label }
}
