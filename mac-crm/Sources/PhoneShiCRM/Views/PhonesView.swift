import SwiftUI

struct PhonesView: View {
    @EnvironmentObject private var store: Store
    @State private var selection: String?
    @State private var search = ""
    @State private var openSerials: [String] = []

    private var rows: [PhoneRow] {
        let all = store.rows
        guard !search.isEmpty else { return all }
        let needle = search.lowercased()
        return all.filter { row in
            [row.serial, row.record.nickname, row.modelLabel, store.creatorName(row.record.creatorID),
             (row.live?.packages ?? []).map(store.appName).joined(separator: " ")]
                .joined(separator: " ").lowercased().contains(needle)
        }
    }

    var body: some View {
        VSplitView {
            HStack(spacing: 0) {
                table
                if let serial = selection, let row = store.rows.first(where: { $0.serial == serial }) {
                    Divider()
                    PhoneDetailView(row: row, isOpen: openSerials.contains(serial),
                                    open: { open(serial) })
                        .frame(width: 340)
                        .background(.background)
                }
            }
            .frame(minHeight: 150, idealHeight: openSerials.isEmpty ? nil : 240,
                   maxHeight: openSerials.isEmpty ? .infinity : 400)
            if !openSerials.isEmpty {
                OpenPhonesStrip(openSerials: $openSerials)
                    .frame(minHeight: 400, idealHeight: 2000, maxHeight: .infinity)
                    .layoutPriority(1)
            }
        }
        .searchable(text: $search, placement: .toolbar, prompt: "Search phones")
        .navigationTitle("Phones")
    }

    private func open(_ serial: String) {
        if !openSerials.contains(serial) { openSerials.append(serial) }
    }

    private var table: some View {
        Table(rows, selection: $selection) {
            TableColumn("Status") { row in
                HStack(spacing: 6) {
                    Circle().fill(row.isOnline ? Color.green : Color.orange).frame(width: 8, height: 8)
                    Text(row.stateLabel)
                }
            }
            .width(90)
            TableColumn("Phone") { row in
                VStack(alignment: .leading) {
                    Text(row.displayName).bold()
                    if !row.record.nickname.isEmpty {
                        Text(row.serial).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            TableColumn("Model") { row in
                VStack(alignment: .leading) {
                    Text(row.modelLabel)
                    if let live = row.live, !live.androidVersion.isEmpty {
                        Text("Android \(live.androidVersion) · \(live.backendLabel)")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            TableColumn("Creator") { row in
                CreatorPicker(store: store, serial: row.serial)
            }
            .width(160)
            TableColumn("Apps") { row in
                Text((row.live?.packages ?? []).map(store.appName).joined(separator: ", "))
                    .lineLimit(1)
            }
            TableColumn("On screen") { row in
                Text(row.live?.foregroundPackage.isEmpty == false
                     ? store.appName(row.live!.foregroundPackage) : "—")
                    .foregroundStyle(.secondary)
            }
            .width(120)
            TableColumn("Use") { row in
                Picker("", selection: Binding(
                    get: { row.record.status },
                    set: { var r = row.record; r.status = $0; store.update(r) })) {
                    ForEach(PhoneStatus.allCases) { Text($0.label).tag($0) }
                }
                .labelsHidden()
            }
            .width(100)
            TableColumn("") { row in
                Button(openSerials.contains(row.serial) ? "Opened" : "Open") { open(row.serial) }
                    .disabled(!row.isOnline || openSerials.contains(row.serial))
                    .controlSize(.small)
            }
            .width(70)
        }
    }
}

struct CreatorPicker: View {
    @ObservedObject var store: Store
    let serial: String

    var body: some View {
        Picker("", selection: Binding<UUID?>(
            get: { store.record(for: serial).creatorID },
            set: { var r = store.record(for: serial); r.creatorID = $0; store.update(r) })) {
            Text("Unassigned").tag(UUID?.none)
            ForEach(store.creators) { Text($0.name).tag(UUID?.some($0.id)) }
        }
        .labelsHidden()
    }
}

struct PhoneDetailView: View {
    @EnvironmentObject private var store: Store
    let row: PhoneRow
    var isOpen = false
    var open: () -> Void = {}
    @State private var screenshot: NSImage?
    @State private var loadingScreenshot = false

    private var record: Binding<PhoneRecord> {
        Binding(get: { store.record(for: row.serial) }, set: { store.update($0) })
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text(row.displayName).font(.title2.bold())
                Text(row.serial).font(.caption.monospaced()).foregroundStyle(.secondary)

                actions

                GroupBox("Record") {
                    Form {
                        TextField("Nickname", text: record.nickname)
                        Picker("Creator", selection: record.creatorID) {
                            Text("Unassigned").tag(UUID?.none)
                            ForEach(store.creators) { Text($0.name).tag(UUID?.some($0.id)) }
                        }
                        Picker("Use", selection: record.status) {
                            ForEach(PhoneStatus.allCases) { Text($0.label).tag($0) }
                        }
                        Picker("Primary app", selection: record.primaryApp) {
                            Text("None").tag("")
                            ForEach(primaryAppChoices, id: \.self) { Text(store.appName($0)).tag($0) }
                        }
                        TextField("Notes", text: record.notes, axis: .vertical).lineLimit(3...6)
                    }
                    .formStyle(.columns)
                }

                if let live = row.live {
                    GroupBox("Live") {
                        Grid(alignment: .leading, verticalSpacing: 4) {
                            info("State", row.stateLabel)
                            info("Model", "\(live.manufacturer) \(live.model)".trimmingCharacters(in: .whitespaces))
                            info("Android", live.androidVersion.isEmpty ? "—" : "\(live.androidVersion) (SDK \(live.sdk))")
                            info("Backend", live.backendLabel)
                            info("Controller", live.control?.name ?? "none")
                            info("On screen", live.foregroundPackage.isEmpty ? "—" : store.appName(live.foregroundPackage))
                        }
                        .font(.callout)
                    }
                    GroupBox("Installed apps") {
                        if live.packages.isEmpty {
                            Text("No third-party apps").foregroundStyle(.secondary)
                        } else {
                            VStack(alignment: .leading, spacing: 3) {
                                ForEach(live.packages, id: \.self) { package in
                                    HStack {
                                        Text(store.appName(package))
                                        Spacer()
                                        Text(package).font(.caption.monospaced()).foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    }
                } else {
                    GroupBox("Live") {
                        Text("This phone was not in the last VDS inventory.").foregroundStyle(.secondary)
                        Button("Forget this phone", role: .destructive) { store.forget(serial: row.serial) }
                    }
                }

                if let screenshot {
                    GroupBox("Screen") {
                        Image(nsImage: screenshot).resizable().aspectRatio(contentMode: .fit)
                            .frame(maxHeight: 520)
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .onChange(of: row.serial) { screenshot = nil }
    }

    private var primaryAppChoices: [String] {
        var all = Set(row.live?.packages ?? [])
        if !row.record.primaryApp.isEmpty { all.insert(row.record.primaryApp) }
        return all.sorted()
    }

    private var actions: some View {
        HStack(spacing: 8) {
            let busy = store.busySerials.contains(row.serial)
            Button(action: open) {
                Label(isOpen ? "Opened" : "Open", systemImage: "rectangle.on.rectangle")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!row.isOnline || isOpen)
            .help("Open and control this phone underneath the table")
            Button {
                store.openViewer(serial: row.serial)
            } label: { Image(systemName: "safari") }
                .disabled(!row.isOnline)
                .help("Open in your browser instead")
            Button {
                loadingScreenshot = true
                Task { screenshot = await store.screenshot(serial: row.serial); loadingScreenshot = false }
            } label: {
                if loadingScreenshot { ProgressView().controlSize(.small) } else { Label("Screen", systemImage: "camera") }
            }
            .disabled(!row.isOnline || loadingScreenshot)
            Spacer()
            if row.isOnline {
                Button(role: .destructive) {
                    Task { await store.setPower(row, on: false) }
                } label: { Label("Stop", systemImage: "stop.fill") }
                    .disabled(busy || row.live?.control == nil)
            } else {
                Button {
                    Task { await store.setPower(row, on: true) }
                } label: { Label("Start", systemImage: "play.fill") }
                    .disabled(busy || row.live?.control == nil)
            }
            if busy { ProgressView().controlSize(.small) }
        }
    }

    private func info(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary).gridColumnAlignment(.trailing)
            Text(value).textSelection(.enabled)
        }
    }
}
