import Foundation

/// Friendly names for Android package ids. Users can override any entry in
/// the Apps tab; overrides are stored with the CRM data.
enum AppCatalog {
    static let known: [String: String] = [
        "com.tinder": "Tinder",
        "com.bumble.app": "Bumble",
        "com.pof.android": "Plenty of Fish",
        "co.hinge.app": "Hinge",
        "com.okcupid.okcupid": "OkCupid",
        "com.match.android.matchmobile": "Match",
        "com.eharmony": "eHarmony",
        "com.coffeemeetsbagel": "Coffee Meets Bagel",
        "co.feeld": "Feeld",
        "com.zoosk.zoosk": "Zoosk",
        "com.badoo.mobile": "Badoo",
        "com.hily.app": "Hily",
        "com.ftw_and_co.happn": "Happn",
        "com.facebook.katana": "Facebook",
        "com.instagram.android": "Instagram",
        "com.zhiliaoapp.musically": "TikTok",
        "com.snapchat.android": "Snapchat",
        "org.telegram.messenger": "Telegram",
        "com.whatsapp": "WhatsApp",
        "com.twitter.android": "X",
        "com.reddit.frontpage": "Reddit",
        "com.android.chrome": "Chrome",
        "com.google.android.apps.nexuslauncher": "Home screen",
        "com.android.vending": "Play Store",
        "com.eltavine.duckdetector": "Duck Detector",
        "dev.emulab.devicecheck": "Device Checker",
    ]

    static func name(for package: String, overrides: [String: String]) -> String {
        if let custom = overrides[package], !custom.isEmpty { return custom }
        if let name = known[package] { return name }
        return package.split(separator: ".").last.map(String.init)?.capitalized ?? package
    }
}
