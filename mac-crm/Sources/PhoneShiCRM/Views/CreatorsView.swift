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
                        Text("\(store.phones(for: creator).count) phones")
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
            Text("Their phones stay in the CRM and become unassigned.")
        }
    }
}
