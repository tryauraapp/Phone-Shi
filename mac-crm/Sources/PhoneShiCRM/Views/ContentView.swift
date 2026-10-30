import SwiftUI

enum SidebarItem: String, CaseIterable, Identifiable {
    case dashboard = "Dashboard"
    case phones = "Phones"
    case creators = "Creators"
    case snap = "Snap Accounts"
    case apps = "Apps"
    case settings = "VDS Settings"

    var id: String { rawValue }
    var icon: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .phones: return "iphone"
        case .creators: return "person.2"
        case .snap: return "bolt.circle"
        case .apps: return "app.badge"
        case .settings: return "server.rack"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: Store
    @State private var section: SidebarItem? = .dashboard

    var body: some View {
        NavigationSplitView {
            List(SidebarItem.allCases, selection: $section) { item in
                Label(item.rawValue, systemImage: item.icon).tag(item)
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200)
            .safeAreaInset(edge: .bottom) { hostFooter }
        } detail: {
            Group {
                switch section ?? .dashboard {
                case .dashboard: DashboardView()
                case .phones: PhonesView()
                case .creators: CreatorsView()
                case .snap: SnapAccountsView()
                case .apps: AppsView()
                case .settings: SettingsView()
                }
            }
            .toolbar { toolbar }
        }
        .task {
            await store.refresh()
            while !Task.isCancelled {
                let seconds = store.hasRunningSetup ? 15 : max(15, store.settings.autoRefreshSeconds)
                try? await Task.sleep(for: .seconds(seconds))
                await store.refresh()
            }
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .status) {
            if let error = store.lastError {
                Label(error.split(separator: "\n").first.map(String.init) ?? error,
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .lineLimit(1)
                    .help(error)
            } else if let captured = store.inventory?.capturedAt {
                Text("Updated \(captured, style: .relative) ago")
                    .foregroundStyle(.secondary)
            }
        }
        ToolbarItem(placement: .primaryAction) {
            Button {
                Task { await store.refresh() }
            } label: {
                if store.isRefreshing {
                    ProgressView().controlSize(.small)
                } else {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
            .disabled(store.isRefreshing)
            .help("Refresh phones from the VDS (⌘R)")
        }
    }

    private var hostFooter: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let host = store.inventory?.host {
                Label(host.hostname, systemImage: "server.rack").font(.callout.bold())
                Text("Up \(host.uptime)").font(.caption).foregroundStyle(.secondary)
                Text("Load \(host.load)").font(.caption).foregroundStyle(.secondary)
                Text("RAM \(host.memUsedMB / 1024) / \(host.memTotalMB / 1024) GB · Disk \(host.diskUsedPercent)%")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                Label(store.settings.host, systemImage: "server.rack").font(.callout.bold())
                Text("Not connected yet").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.bar)
    }
}
