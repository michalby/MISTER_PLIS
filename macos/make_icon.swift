// Renders the app icon: the favicon's drop on a dark rounded tile, as a macOS .iconset.
//   swiftc make_icon.swift -o make_icon && ./make_icon favicon.svg AppIcon.iconset
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let drop = NSImage(contentsOfFile: args[1]) else {
    FileHandle.standardError.write(Data("usage: make_icon <favicon.svg> <out.iconset>\n".utf8))
    exit(1)
}
let out = URL(fileURLWithPath: args[2])
try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func render(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: px, height: px)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = CGFloat(px) / 1024  // drawn on Apple's 1024 grid: an 824 tile with ~185 corners

    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
    shadow.shadowOffset = NSSize(width: 0, height: -10 * s)
    shadow.shadowBlurRadius = 22 * s
    NSGraphicsContext.saveGraphicsState()
    shadow.set()
    let tile = NSBezierPath(roundedRect: NSRect(x: 100 * s, y: 100 * s, width: 824 * s, height: 824 * s),
                            xRadius: 185 * s, yRadius: 185 * s)
    NSColor(srgbRed: 0.10, green: 0.09, blue: 0.20, alpha: 1).setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(starting: NSColor(srgbRed: 0.20, green: 0.17, blue: 0.38, alpha: 1),
               ending: NSColor(srgbRed: 0.07, green: 0.07, blue: 0.16, alpha: 1))!.draw(in: tile, angle: -90)

    // The drop fills 29 of the SVG's 32 units in height; make it 580 px tall, centred.
    let unit = 580 * s / 29
    let side = 32 * unit
    drop.draw(in: NSRect(x: 512 * s - side / 2, y: 512 * s - side / 2, width: side, height: side))

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    try render(base).write(to: out.appendingPathComponent("icon_\(base)x\(base).png"))
    try render(base * 2).write(to: out.appendingPathComponent("icon_\(base)x\(base)@2x.png"))
}
