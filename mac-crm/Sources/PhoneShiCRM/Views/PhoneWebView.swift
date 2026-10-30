import SwiftUI
import WebKit

/// One WKWebView per open phone, kept alive while the phone stays open so that
/// switching tabs or resizing never restarts the stream.
@MainActor
final class PhoneWebViews {
    static let shared = PhoneWebViews()
    private var views: [String: WKWebView] = [:]

    func view(for serial: String, url: URL) -> WKWebView {
        if let existing = views[serial] { return existing }
        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.preferences.isElementFullscreenEnabled = true
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.allowsMagnification = false
        view.load(URLRequest(url: url))
        views[serial] = view
        return view
    }

    func reload(serial: String) {
        views[serial]?.reload()
    }

    func close(serial: String) {
        views[serial]?.stopLoading()
        views[serial]?.loadHTMLString("", baseURL: nil)
        views.removeValue(forKey: serial)
    }
}

struct PhoneWebView: NSViewRepresentable {
    let serial: String
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        PhoneWebViews.shared.view(for: serial, url: url)
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}
}

/// A phone streamed from the VDS, with touch and keyboard passed through.
struct PhoneViewerCard: View {
    @EnvironmentObject private var store: Store
    let row: PhoneRow
    let onClose: () -> Void

    private var url: URL? {
        var base = store.settings.viewerBase
        while base.hasSuffix("/") { base.removeLast() }
        return URL(string: "\(base)/go?udid=\(row.serial)")
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Circle().fill(row.isOnline ? Color.green : Color.orange).frame(width: 8, height: 8)
                Text(row.displayName).font(.callout.bold()).lineLimit(1)
                Text(row.modelLabel).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                Button { PhoneWebViews.shared.reload(serial: row.serial) } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Reconnect the stream")
                Button { store.openViewer(serial: row.serial) } label: {
                    Image(systemName: "safari")
                }
                .help("Open this phone in your browser instead")
                Button { onClose() } label: { Image(systemName: "xmark") }
                    .help("Close this phone")
            }
            .buttonStyle(.borderless)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.bar)
            Divider()
            if let url {
                PhoneWebView(serial: row.serial, url: url)
            } else {
                ContentUnavailableView("Bad viewer URL", systemImage: "link.badge.plus",
                                       description: Text("Check the viewer base URL in VDS Settings."))
            }
        }
        .background(Color.black)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(.separator))
    }
}

/// The strip of open phones shown underneath the phone table.
struct OpenPhonesStrip: View {
    @EnvironmentObject private var store: Store
    @Binding var openSerials: [String]

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 12) {
                ForEach(openSerials, id: \.self) { serial in
                    if let row = store.rows.first(where: { $0.serial == serial }) {
                        PhoneViewerCard(row: row) { close(serial) }
                            .frame(width: 440)
                    }
                }
            }
            .padding(12)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.quaternary.opacity(0.3))
    }

    private func close(_ serial: String) {
        PhoneWebViews.shared.close(serial: serial)
        openSerials.removeAll { $0 == serial }
    }
}
