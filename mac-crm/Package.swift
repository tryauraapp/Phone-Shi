// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "PhoneShiCRM",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "PhoneShiCRM",
            path: "Sources/PhoneShiCRM"
        )
    ]
)
