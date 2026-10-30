import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: Store
    @State private var testResult = ""
    @State private var testing = false

    private var settings: Binding<ConnectionSettings> {
        Binding(get: { store.settings }, set: { store.settings = $0; store.save() })
    }

    var body: some View {
        Form {
            Section("VDS connection") {
                TextField("Host", text: settings.host)
                TextField("SSH user", text: settings.user)
                TextField("SSH key", text: settings.keyPath)
                TextField("adb path on VDS", text: settings.adbPath)
            }
            Section("Phone setup") {
                TextField("Setup script on VDS", text: settings.setupScript)
                TextField("Duck APK on VDS", text: settings.duckApk)
                Text("New phones run `setup_vps_phone.py create` with these paths as root over SSH.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Phone viewer") {
                TextField("Viewer base URL", text: settings.viewerBase)
                Text("Open viewer launches <base>/go?udid=<serial> in your browser.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Refresh") {
                Stepper("Auto-refresh every \(settings.wrappedValue.autoRefreshSeconds) s",
                        value: settings.autoRefreshSeconds, in: 15...600, step: 15)
            }
            Section {
                HStack {
                    Button("Test connection") {
                        testing = true
                        Task { testResult = await store.testConnection(); testing = false }
                    }
                    .disabled(testing)
                    if testing { ProgressView().controlSize(.small) }
                    Text(testResult).foregroundStyle(.secondary).textSelection(.enabled)
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("VDS Settings")
        .frame(minWidth: 520)
    }
}
