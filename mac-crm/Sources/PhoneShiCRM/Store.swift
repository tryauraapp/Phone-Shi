import AppKit
import Foundation

@MainActor
final class Store: ObservableObject {
    @Published var creators: [Creator] = []
    @Published var snapAccounts: [SnapAccount] = []
    @Published var phones: [String: PhoneRecord] = [:]
    @Published var appNames: [String: String] = [:]
    @Published var settings = ConnectionSettings()
    @Published var inventory: Inventory?
    @Published var isRefreshing = false
    @Published var lastError: String?
    @Published var busySerials: Set<String> = []

    private struct Document: Codable {
        var creators: [Creator]
        var phones: [String: PhoneRecord]
        var appNames: [String: String]
        var settings: ConnectionSettings
        var inventory: Inventory?
        var snapAccounts: [SnapAccount]?
    }

    private static var fileURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Phone Shi CRM", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("crm.json")
    }

    init() {
        load()
        PhoneWebViews.shared.pasteHandler = { [weak self] serial in
            Task { await self?.pasteClipboard(serial: serial) }
        }
    }

    // MARK: Persistence

    func load() {
        guard let data = try? Data(contentsOf: Self.fileURL) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let doc = try? decoder.decode(Document.self, from: data) else { return }
        creators = doc.creators
        phones = doc.phones
        appNames = doc.appNames
        settings = doc.settings
        inventory = doc.inventory
        snapAccounts = doc.snapAccounts ?? []
    }

    func save() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let doc = Document(creators: creators, phones: phones, appNames: appNames,
                           settings: settings, inventory: inventory, snapAccounts: snapAccounts)
        if let data = try? encoder.encode(doc) {
            try? data.write(to: Self.fileURL, options: .atomic)
        }
    }

    // MARK: Derived data

    var rows: [PhoneRow] {
        let live = Dictionary(uniqueKeysWithValues: (inventory?.phones ?? []).map { ($0.serial, $0) })
        let serials = Set(live.keys).union(phones.keys)
        return serials.sorted().map { serial in
            PhoneRow(serial: serial, live: live[serial], record: record(for: serial))
        }
    }

    func record(for serial: String) -> PhoneRecord {
        phones[serial] ?? PhoneRecord(serial: serial)
    }

    func update(_ record: PhoneRecord) {
        phones[record.serial] = record
        save()
    }

    func forget(serial: String) {
        phones.removeValue(forKey: serial)
        save()
    }

    func creator(_ id: UUID?) -> Creator? {
        guard let id else { return nil }
        return creators.first { $0.id == id }
    }

    func creatorName(_ id: UUID?) -> String {
        creator(id)?.name ?? "Unassigned"
    }

    func phones(for creator: Creator) -> [PhoneRow] {
        rows.filter { $0.record.creatorID == creator.id }
    }

    func appName(_ package: String) -> String {
        AppCatalog.name(for: package, overrides: appNames)
    }

    var appStats: [AppStat] {
        var serials: [String: [String]] = [:]
        for phone in inventory?.phones ?? [] {
            for package in phone.packages {
                serials[package, default: []].append(phone.serial)
            }
        }
        for record in phones.values where !record.primaryApp.isEmpty {
            if !(serials[record.primaryApp] ?? []).contains(record.serial) {
                serials[record.primaryApp, default: []].append(record.serial)
            }
        }
        return serials.map { AppStat(package: $0.key, name: appName($0.key), serials: $0.value.sorted()) }
            .sorted { ($1.phoneCount, $0.name) < ($0.phoneCount, $1.name) }
    }

    func counts(_ key: (PhoneRow) -> String) -> [CountRow] {
        var totals: [String: Int] = [:]
        for row in rows { totals[key(row), default: 0] += 1 }
        return totals.map { CountRow(label: $0.key, count: $0.value) }
            .sorted { ($1.count, $0.label) < ($0.count, $1.label) }
    }

    func addCreator(named name: String) -> Creator {
        let creator = Creator(name: name)
        creators.append(creator)
        save()
        return creator
    }

    func update(_ creator: Creator) {
        guard let index = creators.firstIndex(where: { $0.id == creator.id }) else { return }
        creators[index] = creator
        save()
    }

    func delete(_ creator: Creator) {
        creators.removeAll { $0.id == creator.id }
        for (serial, var record) in phones where record.creatorID == creator.id {
            record.creatorID = nil
            phones[serial] = record
        }
        for index in snapAccounts.indices where snapAccounts[index].creatorID == creator.id {
            snapAccounts[index].creatorID = nil
        }
        save()
    }

    // MARK: Snap accounts

    func snapAccounts(for creator: Creator) -> [SnapAccount] {
        snapAccounts.filter { $0.creatorID == creator.id }
    }

    func snapAccounts(onPhone serial: String) -> [SnapAccount] {
        snapAccounts.filter { $0.phoneSerial == serial }
    }

    @discardableResult
    func addSnapAccount(username: String, creatorID: UUID? = nil) -> SnapAccount {
        let account = SnapAccount(username: username, creatorID: creatorID)
        snapAccounts.append(account)
        save()
        return account
    }

    func update(_ account: SnapAccount) {
        guard let index = snapAccounts.firstIndex(where: { $0.id == account.id }) else { return }
        snapAccounts[index] = account
        save()
    }

    func delete(_ account: SnapAccount) {
        snapAccounts.removeAll { $0.id == account.id }
        save()
    }

    func snapCounts(_ key: (SnapAccount) -> String) -> [CountRow] {
        var totals: [String: Int] = [:]
        for account in snapAccounts { totals[key(account), default: 0] += 1 }
        return totals.map { CountRow(label: $0.key, count: $0.value) }
            .sorted { ($1.count, $0.label) < ($0.count, $1.label) }
    }

    // MARK: VDS actions

    private var client: VDSClient { VDSClient(settings: settings) }

    func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        let client = self.client
        do {
            let result = try await Task.detached(priority: .userInitiated) { try client.inventory() }.value
            inventory = result
            for phone in result.phones where phones[phone.serial] == nil {
                phones[phone.serial] = PhoneRecord(serial: phone.serial)
            }
            lastError = nil
            save()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func setPower(_ row: PhoneRow, on: Bool) async {
        guard let control = row.live?.control else {
            lastError = "\(row.serial) has no start/stop controller on the VDS."
            return
        }
        busySerials.insert(row.serial)
        defer { busySerials.remove(row.serial) }
        let client = self.client
        do {
            try await Task.detached { try client.setPower(control, on: on) }.value
            lastError = nil
            await refresh()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func screenshot(serial: String) async -> NSImage? {
        let client = self.client
        do {
            let data = try await Task.detached { try client.screenshot(serial: serial) }.value
            lastError = nil
            return NSImage(data: data)
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    func sendKey(serial: String, keycode: Int) async {
        let client = self.client
        do {
            try await Task.detached { try client.sendKey(serial: serial, keycode: keycode) }.value
        } catch {
            lastError = error.localizedDescription
        }
    }

    // MARK: Phone setup

    var hasRunningSetup: Bool {
        (inventory?.phones ?? []).contains { $0.setup?.isRunning == true }
    }

    nonisolated static func validateSetup(name: String, port: Int?, grpcPort: Int?) -> String? {
        guard name.range(of: #"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"#, options: .regularExpression) != nil else {
            return "Use a name of 1–64 letters, digits, dots, underscores or hyphens."
        }
        guard let port, (5554...5682).contains(port), port % 2 == 0 else {
            return "Choose an even emulator port between 5554 and 5682."
        }
        guard let grpcPort, (1024...65535).contains(grpcPort), grpcPort != port, grpcPort != port + 1 else {
            return "Choose a separate gRPC port between 1024 and 65535."
        }
        return nil
    }

    /// Starts the standard setup on the VDS and records the phone locally. Returns the new serial.
    func createPhone(name: String, port: Int, grpcPort: Int, nickname: String, creatorID: UUID?) async -> String? {
        let serial = "emulator-\(port)"
        let client = self.client
        do {
            try await Task.detached { try client.createPhone(name: name, port: port, grpcPort: grpcPort) }.value
        } catch {
            lastError = error.localizedDescription
            return nil
        }
        var record = phones[serial] ?? PhoneRecord(serial: serial)
        record.nickname = nickname.isEmpty ? name : nickname
        if let creatorID { record.creatorID = creatorID }
        if record.notes.isEmpty { record.notes = "Created from Phone Shi CRM as \(name)." }
        phones[serial] = record
        lastError = nil
        save()
        await refresh()
        return serial
    }

    func resumeSetup(_ setup: PhoneSetup) async {
        let client = self.client
        do {
            try await Task.detached { try client.resumeSetup(name: setup.name, directory: setup.directory) }.value
            lastError = nil
            await refresh()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func verifyPhone(_ setup: PhoneSetup) async -> String {
        let client = self.client
        do {
            let text = try await Task.detached { try client.verifyPhone(directory: setup.directory) }.value
            lastError = nil
            await refresh()
            return text
        } catch {
            lastError = error.localizedDescription
            return "Verification failed: \(error.localizedDescription)"
        }
    }

    func setupLog(_ setup: PhoneSetup) async -> String {
        let client = self.client
        do {
            return try await Task.detached { try client.setupLog(name: setup.name) }.value
        } catch {
            return error.localizedDescription
        }
    }

    func setupPlan() async -> [String] {
        let client = self.client
        return (try? await Task.detached { try client.setupPlan() }.value) ?? []
    }

    /// Pastes the Mac clipboard text into the phone: sets the device clipboard
    /// through the stream, then presses Android's Paste key.
    func pasteClipboard(serial: String) async {
        guard let text = NSPasteboard.general.string(forType: .string), !text.isEmpty else {
            lastError = "The Mac clipboard has no text to paste."
            return
        }
        if let session = NativePhoneSessions.shared.sessions[serial] {
            session.text(text)
            lastError = nil
            return
        }
        guard await PhoneWebViews.shared.pushClipboard(serial: serial, text: text) else {
            lastError = "Open the phone in the CRM first; the stream carries the clipboard to the phone."
            return
        }
        try? await Task.sleep(for: .milliseconds(400))
        await sendKey(serial: serial, keycode: 279)
        lastError = nil
    }

    /// Installs the repo's gRPC allowlist (stock plus the WebRTC service) into the
    /// phone's private emulator and restarts it so the native view can use WebRTC.
    func enableWebRTC(_ row: PhoneRow) async {
        guard let setup = row.live?.setup, let control = row.live?.control, control.kind == "systemd" else {
            lastError = "Only emulators created by the standard setup can be switched to WebRTC."
            return
        }
        let repo = (settings.repoPath as NSString).expandingTildeInPath
        guard let allowlist = try? Data(contentsOf: URL(fileURLWithPath: repo + "/vds_phone_view/emulator_access.json")) else {
            lastError = "vds_phone_view/emulator_access.json was not found in the repo."
            return
        }
        let client = self.client
        let avd = setup.name
        busySerials.insert(row.serial)
        defer { busySerials.remove(row.serial) }
        do {
            let path = "/opt/android-vm/avd/\(avd).avd/private-emulator/lib/emulator_access.json"
            try await Task.detached {
                try client.run("f='\(path)'; cp -n \"$f\" \"$f.stock\" 2>/dev/null; cat > \"$f\" && systemctl restart '\(control.name)'",
                               stdin: allowlist, timeout: 60)
            }.value
            NativePhoneSessions.shared.close(serial: row.serial)
            lastError = nil
            await refresh()
        } catch {
            lastError = error.localizedDescription
        }
    }

    func saveScreenshot(serial: String) async {
        guard let image = await screenshot(serial: serial),
              let tiff = image.tiffRepresentation,
              let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) else { return }
        let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask)[0]
        let url = desktop.appendingPathComponent("\(serial)-\(stamp).png")
        do {
            try png.write(to: url)
            lastError = nil
        } catch {
            lastError = "Could not save screenshot: \(error.localizedDescription)"
        }
    }

    func testConnection() async -> String {
        let client = self.client
        do {
            let text = try await Task.detached { try client.testConnection() }.value
            lastError = nil
            return "Connected: \(text.replacingOccurrences(of: "\n", with: ", "))"
        } catch {
            lastError = error.localizedDescription
            return "Failed: \(error.localizedDescription)"
        }
    }

    func openViewer(serial: String) {
        var base = settings.viewerBase
        while base.hasSuffix("/") { base.removeLast() }
        if let url = URL(string: "\(base)/go?udid=\(serial)") {
            NSWorkspace.shared.open(url)
        }
    }
}
