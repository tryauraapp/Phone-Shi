import SwiftUI

struct SnapAccountsView: View {
    @EnvironmentObject private var store: Store
    @State private var selection: UUID?
    @State private var newUsername = ""
    @State private var search = ""

    private var accounts: [SnapAccount] {
        let all = store.snapAccounts.sorted { $0.username.lowercased() < $1.username.lowercased() }
        guard !search.isEmpty else { return all }
        let needle = search.lowercased()
        return all.filter { account in
            [account.username, account.displayName, account.email, account.phoneNumber,
             store.creatorName(account.creatorID), account.phoneSerial, account.status.label]
                .joined(separator: " ").lowercased().contains(needle)
        }
    }

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                table
                Divider()
                HStack {
                    TextField("New Snap username", text: $newUsername)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(add)
                    Button("Add", action: add)
                        .disabled(newUsername.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .padding(10)
            }
            if let id = selection, let account = store.snapAccounts.first(where: { $0.id == id }) {
                Divider()
                SnapAccountDetailView(account: account)
                    .frame(width: 340)
                    .background(.background)
            }
        }
        .searchable(text: $search, placement: .toolbar, prompt: "Search Snap accounts")
        .navigationTitle("Snap Accounts")
        .overlay {
            if store.snapAccounts.isEmpty {
                ContentUnavailableView("No Snap accounts yet", systemImage: "bolt.circle",
                                       description: Text("Add a username below, then assign it to a creator and a phone."))
            }
        }
    }

    private var table: some View {
        Table(accounts, selection: $selection) {
            TableColumn("Username") { account in
                VStack(alignment: .leading) {
                    Text(account.username).bold()
                    if !account.displayName.isEmpty {
                        Text(account.displayName).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .width(min: 140, ideal: 180)
            TableColumn("Status") { account in
                Picker("", selection: Binding(
                    get: { account.status },
                    set: { var a = account; a.status = $0; store.update(a) })) {
                    ForEach(SnapStatus.allCases) { Text($0.label).tag($0) }
                }
                .labelsHidden()
            }
            .width(110)
            TableColumn("Creator") { account in
                Picker("", selection: Binding<UUID?>(
                    get: { account.creatorID },
                    set: { var a = account; a.creatorID = $0; store.update(a) })) {
                    Text("Unassigned").tag(UUID?.none)
                    ForEach(store.creators) { Text($0.name).tag(UUID?.some($0.id)) }
                }
                .labelsHidden()
            }
            .width(160)
            TableColumn("Phone") { account in
                Picker("", selection: Binding(
                    get: { account.phoneSerial },
                    set: { var a = account; a.phoneSerial = $0; store.update(a) })) {
                    Text("None").tag("")
                    ForEach(store.rows) { Text($0.displayName).tag($0.serial) }
                }
                .labelsHidden()
            }
            .width(160)
            TableColumn("Email") { account in
                Text(account.email.isEmpty ? "—" : account.email).foregroundStyle(.secondary)
            }
            TableColumn("Phone number") { account in
                Text(account.phoneNumber.isEmpty ? "—" : account.phoneNumber).foregroundStyle(.secondary)
            }
            .width(130)
            TableColumn("Added") { account in
                Text(account.createdAt, style: .date).foregroundStyle(.secondary)
            }
            .width(100)
        }
    }

    private func add() {
        let name = newUsername.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        selection = store.addSnapAccount(username: name).id
        newUsername = ""
    }
}

struct SnapAccountDetailView: View {
    @EnvironmentObject private var store: Store
    let account: SnapAccount
    @State private var confirmDelete = false

    private var binding: Binding<SnapAccount> {
        Binding(get: { store.snapAccounts.first { $0.id == account.id } ?? account },
                set: { store.update($0) })
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Image(systemName: "bolt.circle.fill").foregroundStyle(.yellow).font(.title2)
                    Text(account.username).font(.title2.bold())
                }
                GroupBox("Account") {
                    Form {
                        TextField("Username", text: binding.username)
                        TextField("Display name", text: binding.displayName)
                        TextField("Email", text: binding.email)
                        TextField("Phone number", text: binding.phoneNumber)
                        Picker("Status", selection: binding.status) {
                            ForEach(SnapStatus.allCases) { Text($0.label).tag($0) }
                        }
                        TextField("Notes", text: binding.notes, axis: .vertical).lineLimit(3...8)
                    }
                    .formStyle(.columns)
                }
                GroupBox("Assignment") {
                    Form {
                        Picker("Creator", selection: binding.creatorID) {
                            Text("Unassigned").tag(UUID?.none)
                            ForEach(store.creators) { Text($0.name).tag(UUID?.some($0.id)) }
                        }
                        Picker("Phone", selection: binding.phoneSerial) {
                            Text("None").tag("")
                            ForEach(store.rows) { Text("\($0.displayName) · \($0.modelLabel)").tag($0.serial) }
                        }
                    }
                    .formStyle(.columns)
                }
                HStack {
                    Spacer()
                    Button("Delete account", role: .destructive) { confirmDelete = true }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .confirmationDialog("Delete \(account.username)?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) { store.delete(account) }
        }
    }
}
