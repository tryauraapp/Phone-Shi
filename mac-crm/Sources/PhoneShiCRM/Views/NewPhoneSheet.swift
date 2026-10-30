import SwiftUI

/// What the user fills in to create a phone with the standard VDS setup.
struct NewPhoneDraft {
    var name = ""
    var port = ""
    var grpcPort = ""
    var nickname = ""
    var creatorID: UUID?

    var portValue: Int? { Int(port.trimmingCharacters(in: .whitespaces)) }
    var grpcValue: Int? { Int(grpcPort.trimmingCharacters(in: .whitespaces)) }
    var validationError: String? {
        Store.validateSetup(name: name.trimmingCharacters(in: .whitespaces), port: portValue, grpcPort: grpcValue)
    }

    @MainActor static func suggested(from store: Store) -> NewPhoneDraft {
        var draft = NewPhoneDraft()
        let port = store.inventory?.nextPort ?? 5564
        draft.port = String(port)
        draft.grpcPort = String(store.inventory?.nextGrpcPort ?? (port + 3000))
        let existing = Set((store.inventory?.phones ?? []).compactMap { $0.setup?.name })
        var number = existing.count + 1
        while existing.contains(String(format: "Phone_%03d", number)) { number += 1 }
        draft.name = String(format: "Phone_%03d", number)
        return draft
    }
}

/// The fields shared by the New phone sheet and the Snap account sheet.
struct NewPhoneForm: View {
    @EnvironmentObject private var store: Store
    @Binding var draft: NewPhoneDraft
    var showCreator = true
    @State private var plan: [String] = []
    @State private var showPlan = false

    var body: some View {
        Group {
            TextField("Phone name", text: $draft.name, prompt: Text("Phone_001"))
            HStack {
                TextField("Emulator port", text: $draft.port, prompt: Text("5564"))
                TextField("gRPC port", text: $draft.grpcPort, prompt: Text("8564"))
            }
            TextField("Nickname in CRM", text: $draft.nickname, prompt: Text("Optional"))
            if showCreator {
                Picker("Creator", selection: $draft.creatorID) {
                    Text("Unassigned").tag(UUID?.none)
                    ForEach(store.creators) { Text($0.name).tag(UUID?.some($0.id)) }
                }
            }
            LabeledContent("Setup") {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Standard VPS phone setup (Android 17, Galaxy S25 identity)")
                    Text("Runs setup_vps_phone.py create on the VDS: fresh userdata, unique serial and IMEI, " +
                         "saved settings, Duck Detector, verified over two cold boots. Takes several minutes.")
                        .font(.caption).foregroundStyle(.secondary)
                    DisclosureGroup(isExpanded: $showPlan) {
                        if plan.isEmpty {
                            Text("Loading stages from the VDS…").font(.caption).foregroundStyle(.secondary)
                        } else {
                            VStack(alignment: .leading, spacing: 2) {
                                ForEach(plan.dropFirst(), id: \.self) { line in
                                    Text(line).font(.caption.monospaced())
                                }
                            }
                        }
                    } label: {
                        Text(plan.isEmpty ? "Stages" : "\(plan.count - 1) stages").font(.caption)
                    }
                }
            }
            if let error = draft.validationError {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange).font(.caption)
            }
        }
        .task { plan = await store.setupPlan() }
    }
}

struct NewPhoneSheet: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss
    @State private var draft: NewPhoneDraft
    @State private var creating = false
    var onCreated: ((String) -> Void)? = nil

    init(draft: NewPhoneDraft, onCreated: ((String) -> Void)? = nil) {
        _draft = State(initialValue: draft)
        self.onCreated = onCreated
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("New phone").font(.title2.bold()).padding()
            Form {
                NewPhoneForm(draft: $draft)
                Section {
                    Text("Duck APK: \(store.settings.duckApk)").font(.caption).foregroundStyle(.secondary)
                    Text("Script: \(store.settings.setupScript)").font(.caption).foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
            Divider()
            HStack {
                if let error = store.lastError, creating == false {
                    Text(error).font(.caption).foregroundStyle(.orange).lineLimit(2)
                }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button {
                    create()
                } label: {
                    if creating { ProgressView().controlSize(.small) } else { Text("Create phone") }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(draft.validationError != nil || creating)
            }
            .padding()
        }
        .frame(width: 560)
    }

    private func create() {
        guard let port = draft.portValue, let grpc = draft.grpcValue else { return }
        creating = true
        Task {
            let serial = await store.createPhone(name: draft.name.trimmingCharacters(in: .whitespaces),
                                                 port: port, grpcPort: grpc,
                                                 nickname: draft.nickname, creatorID: draft.creatorID)
            creating = false
            if let serial {
                onCreated?(serial)
                dismiss()
            }
        }
    }
}

/// Setup status, stages, log and recovery actions for a phone created on the VDS.
struct PhoneSetupSection: View {
    @EnvironmentObject private var store: Store
    let setup: PhoneSetup
    @State private var log = ""
    @State private var showLog = false
    @State private var busy = false
    @State private var verifyResult = ""

    var body: some View {
        GroupBox("Setup") {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    if setup.isRunning { ProgressView().controlSize(.small) }
                    Text(setup.statusLabel).bold()
                }
                Grid(alignment: .leading, verticalSpacing: 3) {
                    GridRow { Text("Name").foregroundStyle(.secondary); Text(setup.name) }
                    if setup.stepsTotal > 0 {
                        GridRow { Text("Stages").foregroundStyle(.secondary)
                                  Text("\(setup.stepsVerified) of \(setup.stepsTotal) verified") }
                    }
                    if !setup.duckScan.isEmpty {
                        GridRow { Text("Duck scan").foregroundStyle(.secondary); Text(setup.duckScan) }
                    }
                }
                .font(.callout)
                if !setup.logTail.isEmpty {
                    DisclosureGroup("Log", isExpanded: $showLog) {
                        ScrollView {
                            Text(log.isEmpty ? setup.logTail : log)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(height: 180)
                        .background(.quaternary.opacity(0.4))
                        Button("Reload log") { Task { log = await store.setupLog(setup) } }
                            .controlSize(.small)
                    }
                }
                HStack {
                    if setup.status == "failed" || setup.status == "incomplete" {
                        Button("Resume setup") { Task { busy = true; await store.resumeSetup(setup); busy = false } }
                            .disabled(busy)
                    }
                    if setup.automatedBaseComplete && !setup.isRunning {
                        Button("Verify phone") {
                            Task { busy = true; verifyResult = await store.verifyPhone(setup); busy = false }
                        }
                        .disabled(busy)
                    }
                    if busy { ProgressView().controlSize(.small) }
                }
                if !verifyResult.isEmpty {
                    Text(verifyResult).font(.caption).textSelection(.enabled)
                }
                if setup.status == "base-complete" {
                    Text("Stage 34 is interactive: open Duck on the phone, complete its checkpoint, export the report, " +
                         "then record it on the VDS with setup_vps_phone.py record-scan.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
