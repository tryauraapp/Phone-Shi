import SwiftUI
import WebKit

/// Runs inside the VDS phone page and strips it down to the phone display:
/// the device list, modal chrome and control column are hidden and the two
/// stream canvases (video + touch) are scaled to fill the frame. The touch
/// layer keeps working because ws-scrcpy maps pointer events through the
/// canvas's on-screen rectangle.
private let cleanViewScript = """
(function () {
  if (window === window.top || window.__phoneShiClean) { return; }
  window.__phoneShiClean = true;
  const css = `
    html, body { margin: 0 !important; padding: 0 !important; background: #000 !important; overflow: hidden !important; }
    body > :not(dialog.connect-modal) { display: none !important; }
    dialog.connect-modal { position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important;
      max-width: none !important; max-height: none !important; margin: 0 !important; padding: 0 !important; border: 0 !important;
      background: #000 !important; box-shadow: none !important; border-radius: 0 !important; }
    dialog.connect-modal .modal-frame, dialog.connect-modal .modal-body, dialog.connect-modal .device-view {
      width: 100% !important; height: 100% !important; margin: 0 !important; padding: 0 !important; border: 0 !important; background: #000 !important; }
    dialog.connect-modal .modal-header, dialog.connect-modal .control-buttons-list { display: none !important; }
    dialog.connect-modal .video { position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important;
      margin: 0 !important; background: #000 !important; }
    dialog.connect-modal .video canvas { position: fixed !important; }
  `;
  function apply() {
    if (!document.getElementById('phone-shi-style')) {
      const style = document.createElement('style');
      style.id = 'phone-shi-style';
      style.textContent = css;
      document.head.appendChild(style);
    }
  }
  function fit() {
    const video = document.querySelector('dialog.connect-modal .video');
    if (!video) { return; }
    const layers = Array.from(video.querySelectorAll('canvas'));
    if (!layers.length) { return; }
    const w = layers[0].width, h = layers[0].height;
    if (!w || !h) { return; }
    const W = document.documentElement.clientWidth, H = document.documentElement.clientHeight;
    const scale = Math.min(W / w, H / h);
    const cw = Math.floor(w * scale), ch = Math.floor(h * scale);
    const left = Math.floor((W - cw) / 2), top = Math.floor((H - ch) / 2);
    for (const layer of layers) {
      layer.style.width = cw + 'px'; layer.style.height = ch + 'px';
      layer.style.left = left + 'px'; layer.style.top = top + 'px';
    }
  }
  apply(); fit();
  setInterval(function () { apply(); fit(); }, 500);
  window.addEventListener('resize', fit);
})();
"""

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
        configuration.userContentController.addUserScript(
            WKUserScript(source: cleanViewScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false))
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.setValue(false, forKey: "drawsBackground")
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
                keyButton("arrow.backward", "Back", keycode: 4)
                keyButton("circle", "Home", keycode: 3)
                keyButton("square.on.square", "Recent apps", keycode: 187)
                keyButton("power", "Power / wake", keycode: 26)
                Divider().frame(height: 14)
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

    private func keyButton(_ symbol: String, _ help: String, keycode: Int) -> some View {
        Button {
            Task { await store.sendKey(serial: row.serial, keycode: keycode) }
        } label: { Image(systemName: symbol) }
            .help(help)
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
