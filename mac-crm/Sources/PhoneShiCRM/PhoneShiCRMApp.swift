import SwiftUI

@main
struct PhoneShiCRMApp: App {
    @StateObject private var store = Store()

    var body: some Scene {
        WindowGroup("Phone Shi CRM") {
            ContentView()
                .environmentObject(store)
                .frame(minWidth: 960, minHeight: 600)
        }
        .defaultSize(width: 1280, height: 800)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Refresh from VDS") { Task { await store.refresh() } }
                    .keyboardShortcut("r", modifiers: .command)
            }
        }
        WindowGroup("Phone", id: "phone", for: String.self) { $serial in
            if let serial {
                PhoneWindowView(serial: serial)
                    .environmentObject(store)
            }
        }
        .defaultSize(width: 440, height: 860)
        Settings {
            SettingsView()
                .environmentObject(store)
        }
    }
}
