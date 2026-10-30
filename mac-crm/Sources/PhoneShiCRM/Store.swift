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

    init() { load() }

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
