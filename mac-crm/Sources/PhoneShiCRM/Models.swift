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
    var setupScript = "/opt/android-vm/standard-setup/setup_vps_phone.py"
    var duckApk = "/opt/android-vm-staging/duck-detector-original.apk"

    init() {}

    // Older saved files may lack newer keys; keep their values and fill defaults.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = ConnectionSettings()
        host = try c.decodeIfPresent(String.self, forKey: .host) ?? d.host
        user = try c.decodeIfPresent(String.self, forKey: .user) ?? d.user
        keyPath = try c.decodeIfPresent(String.self, forKey: .keyPath) ?? d.keyPath
        adbPath = try c.decodeIfPresent(String.self, forKey: .adbPath) ?? d.adbPath
        viewerBase = try c.decodeIfPresent(String.self, forKey: .viewerBase) ?? d.viewerBase
        autoRefreshSeconds = try c.decodeIfPresent(Int.self, forKey: .autoRefreshSeconds) ?? d.autoRefreshSeconds
        setupScript = try c.decodeIfPresent(String.self, forKey: .setupScript) ?? d.setupScript
        duckApk = try c.decodeIfPresent(String.self, forKey: .duckApk) ?? d.duckApk
    }
}

/// State of a phone created by setup_vps_phone.py on the VDS.
struct PhoneSetup: Codable, Hashable {
    var name: String
    var directory: String
    var port: Int?
    var grpcPort: Int?
    var status: String
    var automatedBaseComplete: Bool
    var fullSetupComplete: Bool
    var duckScan: String
    var stepsVerified: Int
    var stepsTotal: Int
    var logTail: String
    var unitActive: String

    var isRunning: Bool { status == "running" }
    var statusLabel: String {
        switch status {
        case "running": return "Setting up"
        case "complete": return "Setup complete"
        case "base-complete": return "Base setup done · Duck review pending"
        case "failed": return "Setup failed"
        default: return "Setup incomplete"
        }
    }
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
    var setup: PhoneSetup?

    var isOnline: Bool { state == "device" }
    var isSettingUp: Bool { state == "setting-up" || setup?.isRunning == true }

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
    var nextPort: Int?
    var nextGrpcPort: Int?
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
        if live.isSettingUp { return "Setting up" }
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
