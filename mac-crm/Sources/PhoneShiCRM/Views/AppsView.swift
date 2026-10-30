import SwiftUI

struct AppsView: View {
    @EnvironmentObject private var store: Store

    var body: some View {
        Table(store.appStats) {
            TableColumn("App") { stat in
                TextField("", text: Binding(
                    get: { store.appNames[stat.package] ?? AppCatalog.known[stat.package] ?? "" },
                    set: { store.appNames[stat.package] = $0; store.save() }),
                    prompt: Text(stat.name))
                .textFieldStyle(.plain)
            }
            TableColumn("Package") { stat in
                Text(stat.package).font(.callout.monospaced()).foregroundStyle(.secondary)
            }
            TableColumn("Phones") { stat in
                Text("\(stat.phoneCount)").monospacedDigit()
            }
            .width(70)
            TableColumn("Installed on") { stat in
                Text(stat.serials.map { serial in
                    store.rows.first { $0.serial == serial }?.displayName ?? serial
                }.joined(separator: ", "))
                .lineLimit(1)
            }
        }
        .navigationTitle("Apps")
        .overlay {
            if store.appStats.isEmpty {
                ContentUnavailableView("No apps seen yet", systemImage: "app.badge",
                                       description: Text("Apps appear here once a phone inventory has been loaded from the VDS."))
            }
        }
    }
}
