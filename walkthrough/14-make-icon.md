# icon/make_icon.py — drawing the app icon

[icon/make_icon.py](../icon/make_icon.py) draws Parole's icon with AppKit (no extra packages)
— a sunset-gradient rounded square with soft light circles and a white speech bubble holding a
sound wave — and saves it as `icon/Parole.png` and `icon/Parole.icns`. Run once with
`.venv/bin/python icon/make_icon.py`; the app doesn't use this file at runtime.

---

## Lines 9–28: imports and constants

```python
import os, subprocess, tempfile
from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSCompositingOperationSourceOver,
                    NSDeviceRGBColorSpace, NSGradient, NSGraphicsContext, NSMakePoint,
                    NSMakeRect, NSPNGFileType, NSShadow)

HERE = os.path.dirname(os.path.abspath(__file__))   # the folder this script is in (icon/)
SIZE = 1024                                          # draw at 1024 × 1024 pixels
```
`__file__` is the path of the current script. `NSBezierPath` = a vector shape; `NSGradient` =
a colour gradient; `NSShadow` = a drop shadow; `NSGraphicsContext` = "where drawing goes".

## Lines 31–33: `rgb`

```python
r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
return NSColor.colorWithDeviceRed_green_blue_alpha_(r, g, b, alpha)
```
Turn `"D76D77"` into a colour: take characters 0–1, 2–3, 4–5, parse each as hexadecimal
(`int("D7", 16)` = 215) and divide by 255 to get 0–1. `alpha` is opacity.

## Lines 36–37: `sunset`

A gradient through three colours: deep purple `3A1C71`, pink `D76D77`, peach `FFAF7B`.

## Lines 40–96: `draw`

Coordinates are in pixels with (0, 0) at the **bottom-left**.

**The tile (lines 42–53)**
```python
tile_rect = NSMakeRect(100, 100, 824, 824)
tile = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(tile_rect, 185, 185)
```
An 824-pixel rounded square centred on the 1024 canvas (Apple's icon grid), corner radius 185.

```python
shadow = NSShadow.alloc().init()
shadow.setShadowColor_(rgb("000000", 0.35))   # 35 % black
shadow.setShadowOffset_((0, -12))             # 12 px downward
shadow.setShadowBlurRadius_(28)
NSGraphicsContext.saveGraphicsState()
shadow.set()
rgb("3A1C71").setFill()
tile.fill()
NSGraphicsContext.restoreGraphicsState()
```
`saveGraphicsState` / `restoreGraphicsState` bracket temporary drawing settings: here the
shadow applies only to this fill. The tile is filled in solid purple, casting a shadow.

**Gradient and light circles (lines 55–62)**
```python
NSGraphicsContext.saveGraphicsState()
tile.addClip()                                   # from now on, only draw inside the tile
sunset().drawInBezierPath_angle_(tile, -55)      # gradient across the tile at -55°
for x, y, d, a in [(560, 600, 520, 0.10), ...]:
    rgb("FFFFFF", a).setFill()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, d, d)).fill()
NSGraphicsContext.restoreGraphicsState()         # remove the clip
```
Paint the gradient over the purple tile, then four faint white circles (position `x, y`,
diameter `d`, opacity `a`), clipped to the tile's shape.

**Speech bubble (lines 65–81)**
```python
bubble = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(232, 330, 560, 400), 170, 170)
tail = NSBezierPath.bezierPath()
tail.moveToPoint_(NSMakePoint(330, 360))
tail.curveToPoint_controlPoint1_controlPoint2_(NSMakePoint(262, 248), NSMakePoint(330, 300), NSMakePoint(300, 262))
tail.curveToPoint_controlPoint1_controlPoint2_(NSMakePoint(450, 340), NSMakePoint(350, 250), NSMakePoint(410, 290))
tail.closePath()
bubble.appendBezierPath_(tail)
```
A rounded rectangle plus a tail: start inside the bubble's bottom-left, curve down to the
tail's tip at (262, 248), curve back up to (450, 340), close. Each `curveTo` is a cubic Bézier
curve: the end point, then two "control points" that pull the curve's shape. The tail is added
to the bubble so they're filled as one shape.

```python
NSGraphicsContext.saveGraphicsState()
glow = NSShadow.alloc().init()
glow.setShadowColor_(rgb("2A0E55", 0.35)); glow.setShadowOffset_((0, -10)); glow.setShadowBlurRadius_(30)
glow.set()
rgb("FFFFFF", 0.97).setFill()
bubble.fill()
NSGraphicsContext.restoreGraphicsState()
```
Fill the bubble in nearly opaque white with a soft purple shadow.

**Sound wave (lines 84–96)**
```python
heights = [110, 210, 290, 190, 250, 130, 70]
bar_width, gap = 42, 22
total = len(heights) * bar_width + (len(heights) - 1) * gap
x = 512 - total / 2
```
Seven bars; `total` is the width of all bars plus the gaps between them, so starting at
`512 - total / 2` centres the group horizontally (512 = middle of 1024).

```python
bars = NSBezierPath.bezierPath()
for h in heights:
    bars.appendBezierPath_(
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, 530 - h / 2, bar_width, h), bar_width / 2, bar_width / 2
        )
    )
    x += bar_width + gap
sunset().drawInBezierPath_angle_(bars, -55)
```
Each bar is a rounded rectangle centred vertically on y = 530 (from `530 - h/2` to
`530 + h/2`) with fully rounded ends (radius = half the width). All bars go into one path,
which is then painted with the same sunset gradient.

## Lines 99–110: `render`

```python
rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, SIZE, SIZE, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
)
```
An empty bitmap in memory: let AppKit allocate the pixels (`None`), 1024 × 1024, 8 bits per
channel, 4 channels (RGBA), with alpha, not planar (channels interleaved), RGB colour space,
and `0, 0` = "compute bytes per row / bits per pixel yourself". (The very long name is the
Objective-C method name with one `_` per argument.)

```python
context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(context)
context.setCompositingOperation_(NSCompositingOperationSourceOver)
draw()
context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()
```
Make the bitmap the current drawing destination, use normal "paint over" blending, draw,
make sure everything is written, and restore the previous context.

```python
rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(path, True)
```
Encode as PNG and write it. `atomically=True` writes to a temporary file first and then
renames it, so a half-written file never appears.

## Lines 113–124: `build_icns`

```python
with tempfile.TemporaryDirectory() as tmp:
    iconset = os.path.join(tmp, "Parole.iconset")
    os.mkdir(iconset)
```
A temporary folder, deleted automatically when the `with` block ends. Inside, a folder ending
in `.iconset`, which is what Apple's `iconutil` expects.

```python
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            px = str(size * scale)
            subprocess.run(["sips", "-z", px, px, png, "--out", os.path.join(iconset, name)],
                           check=True, capture_output=True)
```
For each standard size at normal and Retina (`@2x`) resolution, e.g. `icon_32x32@2x.png` at
64 px: `sips -z height width` (a macOS command-line image tool) resizes the PNG.
`check=True` raises an error if the command fails; `capture_output=True` hides its output.

```python
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
```
Convert the `.iconset` folder into a single `.icns` file.

## Lines 127–131: entry point

```python
if __name__ == "__main__":
    png = os.path.join(HERE, "Parole.png")
    render(png)
    build_icns(png, os.path.join(HERE, "Parole.icns"))
    print("wrote", png, "and Parole.icns")
```
Draw the PNG next to this script, build the `.icns` from it, and report.
