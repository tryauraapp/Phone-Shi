import AppKit
import Combine
import SwiftUI

/// Draws bridge frames and turns mouse and keyboard into phone input.
final class PhoneCanvas: NSView {
    var session: NativePhoneSession? {
        didSet { subscribe() }
    }
    private var image: CGImage?
    private var cancellable: AnyCancellable?
    private var pressed = false

    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    private func subscribe() {
        cancellable = session?.$image.receive(on: DispatchQueue.main).sink { [weak self] image in
            self?.image = image
            self?.needsDisplay = true
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.setFillColor(NSColor.black.cgColor)
        context.fill(bounds)
        guard let image else { return }
        context.saveGState()
        // Flipped view: flip back so the image is not drawn upside down.
        context.translateBy(x: 0, y: bounds.height)
        context.scaleBy(x: 1, y: -1)
        context.interpolationQuality = .medium
        context.draw(image, in: bounds)
        context.restoreGState()
    }

    // MARK: Touch

    private func devicePoint(_ event: NSEvent) -> CGPoint? {
        guard let size = session?.deviceSize, bounds.width > 0, bounds.height > 0 else { return nil }
        let location = convert(event.locationInWindow, from: nil)
        let x = min(max(location.x / bounds.width, 0), 1) * size.width
        let y = min(max(location.y / bounds.height, 0), 1) * size.height
        return CGPoint(x: x, y: y)
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        guard let point = devicePoint(event) else { return }
        pressed = true
        session?.touch(x: point.x, y: point.y, down: true)
    }

    override func mouseDragged(with event: NSEvent) {
        guard pressed, let point = devicePoint(event) else { return }
        session?.touch(x: point.x, y: point.y, down: true)
    }

    override func mouseUp(with event: NSEvent) {
        guard let point = devicePoint(event) else { return }
        pressed = false
        session?.touch(x: point.x, y: point.y, down: false)
    }

    override func rightMouseDown(with event: NSEvent) {
        session?.key("GoBack")
    }

    override func scrollWheel(with event: NSEvent) {
        // A wheel tick becomes a short vertical swipe so lists scroll.
        guard let size = session?.deviceSize, let session, abs(event.scrollingDeltaY) > 0.5 else { return }
        let location = convert(event.locationInWindow, from: nil)
        let x = min(max(location.x / bounds.width, 0), 1) * size.width
        let y = min(max(location.y / bounds.height, 0), 1) * size.height
        let delta = min(max(event.scrollingDeltaY * 6, -400), 400)
        session.touch(x: x, y: y, down: true)
        session.touch(x: x, y: y + delta, down: true)
        session.touch(x: x, y: y + delta, down: false)
    }

    // MARK: Keyboard

    private static let specialKeys: [UInt16: String] = [
        36: "Enter", 76: "Enter", 51: "Backspace", 117: "Delete", 48: "Tab", 53: "GoBack",
        123: "ArrowLeft", 124: "ArrowRight", 125: "ArrowDown", 126: "ArrowUp",
        115: "Home", 119: "End",
    ]

    override func keyDown(with event: NSEvent) {
        guard let session else { return }
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if flags.contains(.command) {
            if event.charactersIgnoringModifiers == "v",
               let text = NSPasteboard.general.string(forType: .string), !text.isEmpty {
                session.text(text)
                return
            }
            super.keyDown(with: event)
            return
        }
        if let name = Self.specialKeys[event.keyCode] {
            session.key(name)
            return
        }
        if let characters = event.characters, !characters.isEmpty,
           characters.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) {
            session.text(characters)
            return
        }
        super.keyDown(with: event)
    }
}

struct NativePhoneView: NSViewRepresentable {
    @ObservedObject var session: NativePhoneSession

    func makeNSView(context: Context) -> PhoneCanvas {
        let canvas = PhoneCanvas(frame: .zero)
        canvas.session = session
        return canvas
    }

    func updateNSView(_ nsView: PhoneCanvas, context: Context) {
        if nsView.session !== session { nsView.session = session }
    }
}
