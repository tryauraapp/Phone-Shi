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
    private var keyMonitor: Any?
    /// Called with the serial when Cmd+V is pressed while that phone's view has focus.
    var pasteHandler: ((String) -> Void)?

    private override init() {
        super.init()
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command,
                  event.charactersIgnoringModifiers == "v",
                  let serial = self.focusedSerial() else { return event }
            self.pasteHandler?(serial)
            return nil
        }
    }

    /// The serial of the phone whose web view currently has keyboard focus, if any.
    func focusedSerial() -> String? {
        guard let responder = NSApp.keyWindow?.firstResponder as? NSView else { return nil }
        var view: NSView? = responder
        while let current = view {
            if let web = current as? WKWebView, let serial = views.first(where: { $0.value === web })?.key {
                return serial
            }
            view = current.superview
        }
        return nil
    }

    /// Hands text to ws-scrcpy's "push host clipboard to device" action inside the
    /// stream page, with the browser clipboard read replaced by the given text.
    func pushClipboard(serial: String, text: String) async -> Bool {
        guard let view = views[serial] else { return false }
        let encoded = (try? JSONSerialization.data(withJSONObject: [text])).flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
        let script = """
        (function () {
          const text = \(encoded)[0];
          const frame = document.getElementById('app');
          const w = frame && frame.contentWindow, d = frame && frame.contentDocument;
          if (!w || !d) { return 'no-frame'; }
          const button = d.querySelector('button[title="push host clipboard to device"]');
          if (!button) { return 'no-button'; }
          const clipboard = w.navigator.clipboard;
          if (!clipboard) { return 'no-clipboard'; }
          Object.defineProperty(clipboard, 'readText', { value: () => Promise.resolve(text), configurable: true });
          button.click();
          return 'sent';
        })();
        """
        let result = try? await view.evaluateJavaScript(script)
        return (result as? String) == "sent"
    }

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
    @ObservedObject private var nativeSessions = NativePhoneSessions.shared
    @State private var useBrowser = false
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

    private var nativeEligible: Bool {
        store.settings.nativeViewer && row.live?.control?.kind == "systemd" && row.isOnline
    }

    private var usingNative: Bool { nativeEligible && !useBrowser }

    private var aspect: CGFloat {
        if usingNative, let size = nativeSessions.sessions[row.serial]?.deviceSize, size.height > 0 {
            return size.width / size.height
        }
        return webViews.aspect(for: row.serial)
    }

    var body: some View {
        let phoneHeight = max(120, height - headerHeight)
        let phoneWidth = (phoneHeight * aspect).rounded()
        VStack(spacing: 0) {
            header
                .frame(height: headerHeight)
            HStack(spacing: 0) {
                Group {
                    if usingNative {
                        NativePhoneStage(session: nativeSessions.session(for: row.serial, settings: store.settings),
                                         row: row, switchToBrowser: { useBrowser = true })
                    } else if let url {
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
            if usingNative, let session = nativeSessions.sessions[row.serial] {
                NativeStatusText(session: session)
            } else {
                Text("Browser").font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            if nativeEligible {
                Button { useBrowser.toggle() } label: {
                    Image(systemName: useBrowser ? "bolt" : "globe")
                }
                .help(useBrowser ? "Switch back to the native stream" : "Switch to the browser stream")
            }
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
            tool("doc.on.clipboard", "Paste the Mac clipboard into the phone (⌘V)") { await store.pasteClipboard(serial: row.serial) }
            tool("camera", "Save a screenshot to the Desktop") { await store.saveScreenshot(serial: row.serial) }
            tool("arrow.clockwise", "Reconnect the stream") {
                if usingNative { nativeSessions.sessions[row.serial]?.restart() } else { webViews.reload(serial: row.serial) }
            }
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
        NativePhoneSessions.shared.close(serial: serial)
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
        .onDisappear {
            PhoneWebViews.shared.close(serial: serial)
            NativePhoneSessions.shared.close(serial: serial)
        }
    }
}


/// The native canvas with status overlays: connecting, failed (with a browser
/// fallback) and the one-click WebRTC enablement when the phone only allows
/// screenshot frames.
struct NativePhoneStage: View {
    @EnvironmentObject private var store: Store
    @ObservedObject var session: NativePhoneSession
    let row: PhoneRow
    var switchToBrowser: () -> Void

    var body: some View {
        ZStack {
            NativePhoneView(session: session)
            if session.state == "connecting" && session.image == nil {
                VStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(session.statusLabel).font(.caption).foregroundStyle(.white)
                }
            }
            if session.state == "failed" || session.state == "ended" {
                VStack(spacing: 10) {
                    Text(session.error ?? session.statusLabel)
                        .font(.caption).multilineTextAlignment(.center).foregroundStyle(.white)
                        .padding(.horizontal)
                    HStack {
                        Button("Retry") { session.restart() }
                        Button("Use browser") { switchToBrowser() }
                    }
                    .controlSize(.small)
                }
                .padding()
                .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 8))
            }
            if session.rtcDenied && session.mode == "screenshot" && session.state == "connected" {
                VStack {
                    Spacer()
                    HStack(spacing: 6) {
                        Text("Screenshot frames: WebRTC is not enabled on this phone.")
                            .font(.caption2).foregroundStyle(.white)
                        Button("Enable WebRTC (restarts phone)") { Task { await store.enableWebRTC(row) } }
                            .controlSize(.mini)
                            .disabled(store.busySerials.contains(row.serial))
                    }
                    .padding(6)
                    .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 6))
                    .padding(6)
                }
            }
        }
    }
}

private struct NativeStatusText: View {
    @ObservedObject var session: NativePhoneSession
    var body: some View {
        Text(session.statusLabel).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
    }
}
