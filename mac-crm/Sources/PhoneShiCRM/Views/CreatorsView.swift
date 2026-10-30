import SwiftUI

struct CreatorsView: View {
    @EnvironmentObject private var store: Store
    @State private var selection: UUID?
    @State private var newName = ""

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                List(store.creators, selection: $selection) { creator in
                    VStack(alignment: .leading) {
                        Text(creator.name).bold()
                        Text("\(store.phones(for: creator).count) phones · \(store.snapAccounts(for: creator).count) Snap")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .tag(creator.id)
                }
                Divider()
                HStack {
                    TextField("New creator name", text: $newName)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(add)
                    Button("Add", action: add).disabled(newName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .padding(10)
            }
            .frame(minWidth: 220, idealWidth: 260, maxWidth: 320)

            Group {
                if let id = selection, let creator = store.creators.first(where: { $0.id == id }) {
                    CreatorDetailView(creator: creator)
                } else {
                    ContentUnavailableView("Select a creator", systemImage: "person.2",
                                           description: Text("Add a creator on the left, then assign phones to them."))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .navigationTitle("Creators")
    }

    private func add() {
        let name = newName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        selection = store.addCreator(named: name).id
        newName = ""
    }
}

struct CreatorDetailView: View {
    @EnvironmentObject private var store: Store
    let creator: Creator
    @State private var confirmDelete = false
    @State private var newSnap = ""

    private func addSnap() {
        let name = newSnap.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        store.addSnapAccount(username: name, creatorID: creator.id)
        newSnap = ""
    }

    private var binding: Binding<Creator> {
        Binding(get: { store.creators.first { $0.id == creator.id } ?? creator },
                set: { store.update($0) })
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Form {
                    TextField("Name", text: binding.name)
                    TextField("Instagram", text: binding.instagram, prompt: Text("@handle"))
                    TextField("TikTok", text: binding.tiktok, prompt: Text("@handle"))
                    TextField("OnlyFans", text: binding.onlyfans, prompt: Text("username"))
                    TextField("Notes", text: binding.notes, axis: .vertical).lineLimit(3...8)
                }
                .formStyle(.grouped)
                .scrollContentBackground(.hidden)

                GroupBox("Phones") {
                    let assigned = store.phones(for: creator)
                    if assigned.isEmpty {
                        Text("No phones assigned").foregroundStyle(.secondary)
                    }
                    ForEach(assigned) { row in
                        HStack {
                            Circle().fill(row.isOnline ? Color.green : Color.orange).frame(width: 8, height: 8)
                            Text(row.displayName).bold()
                            Text(row.modelLabel).foregroundStyle(.secondary)
                            Spacer()
                            Text((row.live?.packages ?? []).map(store.appName).joined(separator: ", "))
                                .foregroundStyle(.secondary).lineLimit(1)
                            Button("Unassign") {
                                var r = row.record; r.creatorID = nil; store.update(r)
                            }
                            .buttonStyle(.link)
                        }
                        .padding(.vertical, 2)
                    }
                    let free = store.rows.filter { $0.record.creatorID == nil }
                    if !free.isEmpty {
                        Menu("Assign a phone") {
                            ForEach(free) { row in
                                Button("\(row.displayName) · \(row.modelLabel)") {
                                    var r = row.record; r.creatorID = creator.id; store.update(r)
                                }
                            }
                        }
                        .frame(maxWidth: 200)
                    }
                }
                .padding(.horizontal)

                GroupBox("Snap accounts") {
                    let accounts = store.snapAccounts(for: creator)
                    if accounts.isEmpty {
                        Text("No Snap accounts assigned").foregroundStyle(.secondary)
                    }
                    ForEach(accounts) { account in
                        HStack {
                            Image(systemName: "bolt.circle.fill").foregroundStyle(.yellow)
                            Text(account.username).bold()
                            Text(account.status.label).foregroundStyle(.secondary)
                            if !account.phoneSerial.isEmpty {
                                Text("on \(store.rows.first { $0.serial == account.phoneSerial }?.displayName ?? account.phoneSerial)")
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("Unassign") {
                                var a = account; a.creatorID = nil; store.update(a)
                            }
                            .buttonStyle(.link)
                        }
                        .padding(.vertical, 2)
                    }
                    HStack {
                        let free = store.snapAccounts.filter { $0.creatorID == nil }
                        if !free.isEmpty {
                            Menu("Assign a Snap account") {
                                ForEach(free) { account in
                                    Button(account.username) {
                                        var a = account; a.creatorID = creator.id; store.update(a)
                                    }
                                }
                            }
                            .frame(maxWidth: 220)
                        }
                        TextField("New Snap username", text: $newSnap)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 220)
                            .onSubmit(addSnap)
                        Button("Add to creator", action: addSnap)
                            .disabled(newSnap.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                .padding(.horizontal)

                HStack {
                    Spacer()
                    Button("Delete creator", role: .destructive) { confirmDelete = true }
                }
                .padding(.horizontal)
            }
            .padding(.vertical)
        }
        .confirmationDialog("Delete \(creator.name)?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) { store.delete(creator) }
        } message: {
            Text("Their phones and Snap accounts stay in the CRM and become unassigned.")
        }
    }
}
