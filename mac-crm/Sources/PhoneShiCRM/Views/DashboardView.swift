import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var store: Store

    private var rows: [PhoneRow] { store.rows }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                tiles
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())],
                          alignment: .leading, spacing: 16) {
                    CountTable(title: "Phones per model", rows: store.counts { $0.modelLabel })
                    CountTable(title: "Phones per app", rows: store.appStats.map {
                        CountRow(label: $0.name, count: $0.phoneCount)
                    })
                    CountTable(title: "Phones per creator", rows: store.counts {
                        store.creatorName($0.record.creatorID)
                    })
                    CountTable(title: "Phones per state", rows: store.counts { $0.stateLabel })
                    CountTable(title: "Phones per backend", rows: store.counts {
                        $0.live?.backendLabel ?? "Unknown"
                    })
                    CountTable(title: "Android versions", rows: store.counts {
                        $0.live.map { "Android \($0.androidVersion)" } ?? "Unknown"
                    })
                    CountTable(title: "Snap accounts per creator", rows: store.snapCounts {
                        store.creatorName($0.creatorID)
                    })
                    CountTable(title: "Snap accounts per status", rows: store.snapCounts { $0.status.label })
                }
            }
            .padding(20)
        }
        .navigationTitle("Dashboard")
    }

    private var tiles: some View {
        HStack(spacing: 12) {
            StatTile(title: "Phones", value: rows.count, icon: "iphone")
            StatTile(title: "Online", value: rows.filter(\.isOnline).count, icon: "bolt.fill", tint: .green)
            StatTile(title: "Stopped", value: rows.filter { !$0.isOnline && !($0.live?.isSettingUp ?? false) }.count,
                     icon: "powersleep", tint: .orange)
            StatTile(title: "Setting up", value: rows.filter { $0.live?.isSettingUp ?? false }.count,
                     icon: "gearshape.2", tint: .blue)
            StatTile(title: "Creators", value: store.creators.count, icon: "person.2")
            StatTile(title: "Snap accounts", value: store.snapAccounts.count, icon: "bolt.circle", tint: .yellow)
            StatTile(title: "Apps", value: store.appStats.count, icon: "app.badge")
            StatTile(title: "Unassigned", value: rows.filter { $0.record.creatorID == nil }.count,
                     icon: "questionmark.circle", tint: .secondary)
        }
    }
}

struct StatTile: View {
    let title: String
    let value: Int
    let icon: String
    var tint: Color = .accentColor

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(title, systemImage: icon).font(.caption).foregroundStyle(tint)
            Text("\(value)").font(.system(size: 28, weight: .semibold, design: .rounded))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }
}

struct CountTable: View {
    let title: String
    let rows: [CountRow]

    var body: some View {
        GroupBox(title) {
            if rows.isEmpty {
                Text("No data yet").foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
            } else {
                VStack(spacing: 0) {
                    ForEach(rows) { row in
                        HStack {
                            Text(row.label)
                            Spacer()
                            Text("\(row.count)").monospacedDigit().foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 5)
                        if row.id != rows.last?.id { Divider() }
                    }
                }
            }
        }
    }
}
