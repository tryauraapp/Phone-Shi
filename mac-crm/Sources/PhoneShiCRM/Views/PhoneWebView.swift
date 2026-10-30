import AppKit
import SwiftUI
import WebKit

/// Runs inside the VDS phone page and strips it down to the phone display:
/// the device list, modal chrome and control column are hidden and the two
/// stream canvases (video + touch) are scaled to fill the frame. The touch
/// layer keeps working because ws-scrcpy maps pointer events through the
/// canvas's on-screen rectangle. The canvas size is reported back to the app
/// so the frame can take the phone's exact aspect ratio.
private let cleanViewScript = """
(function () {
  if (window === window.top || window.__phoneShiClean) { return; }
  window.__phoneShiClean = true;
  const css = `
    html, body { margin: 0 !important; padding: 0 !important; background: #000 !important; overflow: hidden !important; }
    body > :not(dialog.connect-modal) { display: none !important; }
    dialog.connect-modal { position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important;
      max-width: none !important; max-height: none !important; margin: 0 !important; padding: 0 !important; border: 0 !important;
      background: #000 !important; box-shadow: none !important; border-radius: 0 !important; transform: none !important; animation: none !important; }
    dialog.connect-modal .modal-frame, dialog.connect-modal .modal-body, dialog.connect-modal .device-view {
      display: block !important; width: 100% !important; height: 100% !important; margin: 0 !important; padding: 0 !important;
      border: 0 !important; background: #000 !important; transform: none !important; animation: none !important; transition: none !important; }
    dialog.connect-modal .modal-header, dialog.connect-modal .control-buttons-list { display: none !important; }
    dialog.connect-modal .video { display: block !important; position: fixed !important; inset: 0 !important; width: 100vw !important;
      height: 100vh !important; margin: 0 !important; padding: 0 !important; background: #000 !important; transform: none !important; }
    dialog.connect-modal .video canvas { position: fixed !important; max-width: none !important; max-height: none !important;
      min-width: 0 !important; min-height: 0 !important; margin: 0 !important; transform: none !important; }
  `;
  let reported = '';
  function apply() {
    if (!document.getElementById('phone-shi-style')) {
      const style = document.createElement('style');
      style.id = 'phone-shi-style';
      style.textContent = css;
      document.head.appendChild(style);
    }
  }
  function videoSize(video, canvas) {
    const vw = parseFloat(video.style.getPropertyValue('--video-width'));
    const vh = parseFloat(video.style.getPropertyValue('--video-height'));
    if (vw > 0 && vh > 0) { return [vw, vh]; }
    if (canvas.width === 300 && canvas.height === 150) { return null; }
    return [canvas.width, canvas.height];
  }
  function fit() {
    const video = document.querySelector('dialog.connect-modal .video');
    if (!video) { return; }
    const layers = Array.from(video.querySelectorAll('canvas'));
    if (!layers.length) { return; }
    const size = videoSize(video, layers[0]);
    if (!size) { return; }
    const w = size[0], h = size[1];
    const W = document.documentElement.clientWidth, H = document.documentElement.clientHeight;
    const scale = Math.min(W / w, H / h);
    const cw = Math.floor(w * scale), ch = Math.floor(h * scale);
    const left = Math.floor((W - cw) / 2), top = Math.floor((H - ch) / 2);
    for (const layer of layers) {
      layer.style.setProperty('width', cw + 'px', 'important');
      layer.style.setProperty('height', ch + 'px', 'important');
      layer.style.setProperty('left', left + 'px', 'important');
      layer.style.setProperty('top', top + 'px', 'important');
    }
    const key = w + 'x' + h;
    if (key !== reported) {
      reported = key;
      try { window.webkit.messageHandlers.phoneShi.postMessage({ w: w, h: h }); } catch (e) {}
    }
  }
  apply(); fit();
  setInterval(function () { apply(); fit(); }, 400);
  window.addEventListener('resize', fit);
})();
"""

/// One WKWebView per open phone, kept alive while the phone stays open so that
/// moving it between the strip and a window never restarts the stream.
@MainActor
final class PhoneWebViews: NSObject, ObservableObject, WKScriptMessageHandler {
    static let shared = PhoneWebViews()
    static let defaultAspect: CGFloat = 1080.0 / 2340.0

    /// Stream width divided by height, reported by the page once it knows.
    @Published var aspects: [String: CGFloat] = [:]
    private var views: [String: WKWebView] = [:]

    func view(for serial: String, url: URL) -> WKWebView {
        if let existing = views[serial] { return existing }
        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.userContentController.addUserScript(
            WKUserScript(source: cleanViewScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false))
        configuration.userContentController.add(self, name: "phoneShi")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.setValue(false, forKey: "drawsBackground")
        view.allowsMagnification = false
        view.load(URLRequest(url: url))
        views[serial] = view
        return view
    }

    func aspect(for serial: String) -> CGFloat {
        aspects[serial] ?? Self.defaultAspect
    }

    func reload(serial: String) {
        views[serial]?.reload()
    }

    func close(serial: String) {
        guard let view = views[serial] else { return }
        view.stopLoading()
        view.loadHTMLString("", baseURL: nil)
        view.removeFromSuperview()
        views.removeValue(forKey: serial)
        aspects.removeValue(forKey: serial)
    }

    nonisolated func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let w = body["w"] as? Double, let h = body["h"] as? Double, w > 0, h > 0 else { return }
        let sender = message.webView
        Task { @MainActor in
            guard let serial = self.views.first(where: { $0.value === sender })?.key else { return }
            self.aspects[serial] = CGFloat(w / h)
        }
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

/// A phone streamed from the VDS: the screen fills a phone-shaped frame with
/// a vertical toolbar beside it, like a cloud-phone client.
struct PhoneViewerCard: View {
    @EnvironmentObject private var store: Store
    @ObservedObject private var webViews = PhoneWebViews.shared
    let row: PhoneRow
    let height: CGFloat
    var onClose: () -> Void
    var onPopOut: (() -> Void)? = nil

    private let headerHeight: CGFloat = 30
    private let toolbarWidth: CGFloat = 44

    private var url: URL? {
        var base = store.settings.viewerBase
        while base.hasSuffix("/") { base.removeLast() }
        return URL(string: "\(base)/go?udid=\(row.serial)")
    }

    var body: some View {
        let phoneHeight = max(120, height - headerHeight)
        let phoneWidth = (phoneHeight * webViews.aspect(for: row.serial)).rounded()
        VStack(spacing: 0) {
            header
                .frame(height: headerHeight)
            HStack(spacing: 0) {
                Group {
                    if let url {
                        PhoneWebView(serial: row.serial, url: url)
                    } else {
                        Text("Check the viewer base URL in VDS Settings.")
                            .foregroundStyle(.secondary).padding()
                    }
                }
                .frame(width: phoneWidth, height: phoneHeight)
                .background(Color.black)
                toolbar
                    .frame(width: toolbarWidth, height: phoneHeight)
            }
        }
        .frame(width: phoneWidth + toolbarWidth, height: height)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(.separator))
    }

    private var header: some View {
        HStack(spacing: 8) {
            Circle().fill(row.isOnline ? Color.green : Color.orange).frame(width: 8, height: 8)
            Text(row.displayName).font(.callout.bold()).lineLimit(1)
            Text(row.modelLabel).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            Spacer()
            if let onPopOut {
                Button(action: onPopOut) { Image(systemName: "macwindow.on.rectangle") }
                    .help("Open this phone in its own window")
            }
            Button(action: onClose) { Image(systemName: "xmark") }
                .help("Close this phone")
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 10)
        .background(.bar)
    }

    private var toolbar: some View {
        VStack(spacing: 14) {
            tool("arrow.backward", "Back") { await store.sendKey(serial: row.serial, keycode: 4) }
            tool("circle", "Home") { await store.sendKey(serial: row.serial, keycode: 3) }
            tool("square.on.square", "Recent apps") { await store.sendKey(serial: row.serial, keycode: 187) }
            Divider().frame(width: 20)
            tool("speaker.wave.2", "Volume up") { await store.sendKey(serial: row.serial, keycode: 24) }
            tool("speaker.wave.1", "Volume down") { await store.sendKey(serial: row.serial, keycode: 25) }
            tool("power", "Power / wake") { await store.sendKey(serial: row.serial, keycode: 26) }
            Divider().frame(width: 20)
            tool("camera", "Save a screenshot to the Desktop") { await store.saveScreenshot(serial: row.serial) }
            tool("arrow.clockwise", "Reconnect the stream") { webViews.reload(serial: row.serial) }
            tool("safari", "Open in your browser") { store.openViewer(serial: row.serial) }
            Spacer()
        }
        .padding(.top, 10)
        .buttonStyle(.borderless)
        .background(.quaternary.opacity(0.4))
    }

    private func tool(_ symbol: String, _ help: String, action: @escaping () async -> Void) -> some View {
        Button { Task { await action() } } label: {
            Image(systemName: symbol).font(.system(size: 15)).frame(width: 28, height: 24)
        }
        .help(help)
    }
}

/// The strip of open phones shown underneath the phone table.
struct OpenPhonesStrip: View {
    @EnvironmentObject private var store: Store
    @Environment(\.openWindow) private var openWindow
    @Binding var openSerials: [String]

    var body: some View {
        GeometryReader { geo in
            ScrollView(.horizontal) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(openSerials, id: \.self) { serial in
                        if let row = store.rows.first(where: { $0.serial == serial }) {
                            PhoneViewerCard(row: row, height: geo.size.height - 24,
                                            onClose: { close(serial) },
                                            onPopOut: { popOut(serial) })
                        }
                    }
                }
                .padding(12)
            }
        }
        .background(.quaternary.opacity(0.3))
    }

    private func close(_ serial: String) {
        PhoneWebViews.shared.close(serial: serial)
        openSerials.removeAll { $0 == serial }
    }

    private func popOut(_ serial: String) {
        openSerials.removeAll { $0 == serial }
        openWindow(id: "phone", value: serial)
    }
}

/// A phone in its own window.
struct PhoneWindowView: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss
    let serial: String

    var body: some View {
        GeometryReader { geo in
            if let row = store.rows.first(where: { $0.serial == serial }) {
                PhoneViewerCard(row: row, height: geo.size.height, onClose: { dismiss() })
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ContentUnavailableView("Phone not found", systemImage: "iphone.slash")
            }
        }
        .background(Color.black)
        .navigationTitle(store.rows.first { $0.serial == serial }?.displayName ?? serial)
        .onDisappear { PhoneWebViews.shared.close(serial: serial) }
    }
}
