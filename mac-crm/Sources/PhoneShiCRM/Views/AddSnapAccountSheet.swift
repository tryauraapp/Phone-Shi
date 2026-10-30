import SwiftUI

struct AddSnapAccountSheet: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss
    @State private var username = ""
    @State private var creatorID: UUID?
    @State private var phoneSerial = ""
    @State private var createPhone = false
    @State private var draft: NewPhoneDraft
    @State private var working = false

    init(creatorID: UUID? = nil, draft: NewPhoneDraft) {
        _creatorID = State(initialValue: creatorID)
        _draft = State(initialValue: draft)
    }

    private var canSubmit: Bool {
        !username.trimmingCharacters(in: .whitespaces).isEmpty &&
            (!createPhone || draft.validationError == nil) && !working
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("New Snap account").font(.title2.bold()).padding()
            Form {
                Section("Account") {
                    TextField("Snap username", text: $username)
                    Picker("Creator", selection: $creatorID) {
                        Text("Unassigned").tag(UUID?.none)
                        ForEach(store.creators) { Text($0.name).tag(UUID?.some($0.id)) }
                    }
                }
                Section("Phone") {
                    Toggle("Create a new phone for this account", isOn: $createPhone)
                    if createPhone {
                        NewPhoneForm(draft: $draft, showCreator: false)
                    } else {
                        Picker("Existing phone", selection: $phoneSerial) {
                            Text("None").tag("")
                            ForEach(store.rows) { Text("\($0.displayName) · \($0.modelLabel)").tag($0.serial) }
                        }
                    }
                }
            }
            .formStyle(.grouped)
            Divider()
            HStack {
                if let error = store.lastError, !working {
                    Text(error).font(.caption).foregroundStyle(.orange).lineLimit(2)
                }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button {
                    submit()
                } label: {
                    if working { ProgressView().controlSize(.small) }
                    else { Text(createPhone ? "Add account and create phone" : "Add account") }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!canSubmit)
            }
            .padding()
        }
        .frame(width: 560)
    }

    private func submit() {
        let name = username.trimmingCharacters(in: .whitespaces)
        working = true
        Task {
            var serial = phoneSerial
            if createPhone, let port = draft.portValue, let grpc = draft.grpcValue {
                let nickname = draft.nickname.isEmpty ? name : draft.nickname
                guard let created = await store.createPhone(name: draft.name.trimmingCharacters(in: .whitespaces),
                                                            port: port, grpcPort: grpc,
                                                            nickname: nickname, creatorID: creatorID) else {
                    working = false
                    return
                }
                serial = created
            }
            var account = store.addSnapAccount(username: name, creatorID: creatorID)
            account.phoneSerial = serial
            store.update(account)
            working = false
            dismiss()
        }
    }
}
