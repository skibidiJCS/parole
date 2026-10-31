"""Draw Parole's app icon and build icon/Parole.icns.

    .venv/bin/python icon/make_icon.py

Drawn with AppKit (no extra packages): a sunset-gradient rounded square with
soft light bubbles, and a white speech bubble holding a sound wave.
"""

import os
import subprocess
import tempfile

from AppKit import (
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceOver,
    NSDeviceRGBColorSpace,
    NSGradient,
    NSGraphicsContext,
    NSMakePoint,
    NSMakeRect,
    NSPNGFileType,
    NSShadow,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024


def rgb(hex_color, alpha=1.0):
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return NSColor.colorWithDeviceRed_green_blue_alpha_(r, g, b, alpha)


def sunset():
    return NSGradient.alloc().initWithColors_([rgb("3A1C71"), rgb("D76D77"), rgb("FFAF7B")])


def draw():
    # The macOS icon grid: an 824 px rounded square centred on a 1024 canvas.
    tile_rect = NSMakeRect(100, 100, 824, 824)
    tile = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(tile_rect, 185, 185)

    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(rgb("000000", 0.35))
    shadow.setShadowOffset_((0, -12))
    shadow.setShadowBlurRadius_(28)
    NSGraphicsContext.saveGraphicsState()
    shadow.set()
    rgb("3A1C71").setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()

    NSGraphicsContext.saveGraphicsState()
    tile.addClip()
    sunset().drawInBezierPath_angle_(tile, -55)
    # Soft light bubbles for depth.
    for x, y, d, a in [(560, 600, 520, 0.10), (120, 160, 380, 0.08), (690, 180, 240, 0.07), (230, 690, 150, 0.09)]:
        rgb("FFFFFF", a).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, d, d)).fill()
    NSGraphicsContext.restoreGraphicsState()

    # Speech bubble: a rounded rectangle plus a little tail at the bottom left.
    bubble = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(232, 330, 560, 400), 170, 170)
    tail = NSBezierPath.bezierPath()
    tail.moveToPoint_(NSMakePoint(330, 360))
    tail.curveToPoint_controlPoint1_controlPoint2_(NSMakePoint(262, 248), NSMakePoint(330, 300), NSMakePoint(300, 262))
    tail.curveToPoint_controlPoint1_controlPoint2_(NSMakePoint(450, 340), NSMakePoint(350, 250), NSMakePoint(410, 290))
    tail.closePath()
    bubble.appendBezierPath_(tail)

    NSGraphicsContext.saveGraphicsState()
    glow = NSShadow.alloc().init()
    glow.setShadowColor_(rgb("2A0E55", 0.35))
    glow.setShadowOffset_((0, -10))
    glow.setShadowBlurRadius_(30)
    glow.set()
    rgb("FFFFFF", 0.97).setFill()
    bubble.fill()
    NSGraphicsContext.restoreGraphicsState()

    # Sound wave: rounded bars painted with the same sunset gradient.
    heights = [110, 210, 290, 190, 250, 130, 70]
    bar_width, gap = 42, 22
    total = len(heights) * bar_width + (len(heights) - 1) * gap
    x = 512 - total / 2
    bars = NSBezierPath.bezierPath()
    for h in heights:
        bars.appendBezierPath_(
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, 530 - h / 2, bar_width, h), bar_width / 2, bar_width / 2
            )
        )
        x += bar_width + gap
    sunset().drawInBezierPath_angle_(bars, -55)


def render(path):
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, SIZE, SIZE, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)
    context.setCompositingOperation_(NSCompositingOperationSourceOver)
    draw()
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(path, True)


def build_icns(png, icns):
    # iconutil wants an .iconset folder with every standard size.
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "Parole.iconset")
        os.mkdir(iconset)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                px = str(size * scale)
                subprocess.run(["sips", "-z", px, px, png, "--out", os.path.join(iconset, name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)


if __name__ == "__main__":
    png = os.path.join(HERE, "Parole.png")
    render(png)
    build_icns(png, os.path.join(HERE, "Parole.icns"))
    print("wrote", png, "and Parole.icns")
