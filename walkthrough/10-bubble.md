# bubble.py — the live-preview bubble

[bubble.py](../bubble.py) draws the small dark floating panel that shows your words while
you speak. It is a **non-activating panel**: it floats above other windows but never takes
keyboard focus, so the paste still goes into your app. Clicks pass through it. It sits under
the text cursor (or the text field, or at the bottom of the window) and follows the window
when you drag it. All of its methods must run on the main thread.

---

## Lines 14–37: imports

`rumps` (for its Timer), many AppKit names (window, view, colour, font constants) and `ax`.
Each is explained where it's used below.

## Lines 39–44: constants

```python
MAX_WIDTH, MIN_WIDTH, HEIGHT = 560, 220, 62   # bubble size in points
INSET = 12            # keep at least 12 points from the window's edges
GAP = 8               # distance from the cursor / field
MARGIN = 14           # padding around the text inside the bubble
FOLLOW_INTERVAL = 0.1 # reposition 10 times a second
TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
```

## Lines 47–59: `anchor_frame`

```python
field = ax.focused_element()
if field is None:
    return None
caret = ax.caret_frame(field)
if caret is not None:
    return caret
if ax.role(field) in TEXT_ROLES:
    frame = ax.frame(field)
    if frame and frame[3] <= 150:
        return frame
return None
```
What to place the bubble next to: the text cursor if the app says where it is; otherwise the
text field itself, but only if it's small (`frame[3]` is the height, ≤ 150 points), because
placing it under a whole document would put it off-screen; otherwise nothing.

## Lines 62–84: `bubble_frame`

```python
window = ax.focused_window()
window = ax.frame(window) if window is not None else None
if window is None:
    screen = NSScreen.mainScreen().visibleFrame()
    return screen.origin.x + (screen.size.width - MAX_WIDTH) / 2, screen.origin.y + 90, MAX_WIDTH
```
Get the focused window's rectangle. Without it, centre the bubble horizontally near the
bottom of the screen (`visibleFrame` excludes the menu bar and Dock).

```python
wx, wy, ww, wh = window
width = max(MIN_WIDTH, min(MAX_WIDTH, ww - 2 * INSET))
```
Window x, y, width, height. Bubble width = window width minus the insets, limited to
220–560.

```python
anchor = anchor_frame()
if anchor is not None:
    x_anchor, y_anchor, w_anchor, h_anchor = anchor
    x = x_anchor + w_anchor / 2 - width / 2
    y = y_anchor - GAP - HEIGHT
    if y < wy + INSET:
        y = y_anchor + h_anchor + GAP
else:
    x, y = wx + (ww - width) / 2, wy + INSET
```
With an anchor: centre the bubble horizontally on it and put it just **below** (in AppKit, y
grows upwards, so "below" = smaller y: anchor bottom − gap − bubble height). If that falls
below the window, put it just above the anchor instead. Without an anchor: centred at the
bottom of the window.

```python
x = min(max(x, wx + INSET), wx + ww - INSET - width)
y = min(max(y, wy + INSET), wy + wh - INSET - HEIGHT)
return x, y, width
```
"Clamp": `max(value, low)` then `min(..., high)` keeps the value between `low` and `high`,
so the bubble never sticks out of the window.

## Lines 87–92: `Bubble.__init__`

```python
self.panel = None   # the NSPanel, built on first show
self.label = None   # the text field inside it
self.text = ""
self.timer = rumps.Timer(lambda _: self._place(), FOLLOW_INTERVAL)
```
A rumps timer runs on the main thread every 0.1 s once started; it passes itself as an
argument, which the lambda ignores (`_`).

## Lines 94–102: `show`

```python
if self.panel is None:
    self._build()
self.text = text
visible = self.panel.isVisible()
self._place()
if not visible:
    self.panel.orderFrontRegardless()
    self.timer.start()
```
Build the panel the first time. Store the text, position and update it. If it wasn't on
screen yet, bring it to the front **without** activating Parole (`orderFrontRegardless`) and
start following the window.

## Lines 104–107: `hide`

Stop the timer and remove the panel from the screen (`orderOut_(None)`; `None` is the
"sender" argument AppKit actions take).

## Lines 109–121: `_place`

```python
try:
    x, y, width = bubble_frame()
except Exception:
    return
```
If an app answers something odd, keep the previous position.

```python
frame = self.panel.frame()
if (frame.origin.x, frame.origin.y, frame.size.width) != (x, y, width):
    self.panel.setFrame_display_(NSMakeRect(x, y, width, HEIGHT), True)
```
Only move/resize when something changed (this runs 10 times a second). `NSMakeRect(x, y, w,
h)` builds a rectangle; `True` = redraw now.

```python
max_chars = int((width - 2 * MARGIN) / 7.5) * 2
text = self.text
if len(text) > max_chars:
    text = "…" + text[-max_chars:].split(" ", 1)[-1]
self.label.setStringValue_(text)
```
Estimate how many characters fit on two lines (≈ 7.5 points per character at 14 pt). If the
text is longer, keep its **end** (`text[-max_chars:]`), drop the partial first word
(`split(" ", 1)[-1]` = everything after the first space) and put "…" in front: older words
scroll off the start.

## Lines 123–157: `_build`

```python
style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
    NSMakeRect(0, 0, MAX_WIDTH, HEIGHT), style, NSBackingStoreBuffered, False
)
```
An `NSPanel` (a kind of window) with no title bar or border, which doesn't activate the app.
`NSBackingStoreBuffered` = normal double-buffered drawing; `False` = create it now.

```python
panel.setLevel_(NSStatusWindowLevel)     # float above normal windows
panel.setOpaque_(False)                  # allow transparency...
panel.setBackgroundColor_(NSColor.clearColor())   # ...with a clear window background
panel.setHasShadow_(True)
panel.setIgnoresMouseEvents_(True)       # clicks go through to the app underneath
panel.setCollectionBehavior_(
    NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
)                                        # show on every desktop, and over full-screen apps
```

```python
background = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, MAX_WIDTH, HEIGHT))
background.setMaterial_(NSVisualEffectMaterialHUDWindow)          # dark "HUD" look
background.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow) # blur what's behind
background.setState_(NSVisualEffectStateActive)                   # always blurred
background.setWantsLayer_(True)                                   # use a Core Animation layer...
background.layer().setCornerRadius_(16)                           # ...for rounded corners
background.layer().setMasksToBounds_(True)                        # clip to those corners
background.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)  # stretch with the panel
```
The blurred dark background.

```python
label = NSTextField.wrappingLabelWithString_("")
label.setFrame_(NSMakeRect(MARGIN, 7, MAX_WIDTH - 2 * MARGIN, HEIGHT - 14))
label.setFont_(NSFont.systemFontOfSize_(14))
label.setTextColor_(NSColor.whiteColor())
label.setMaximumNumberOfLines_(2)
label.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
label.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
background.addSubview_(label)
```
A non-editable, wrapping text label: inset by the margin, 14 pt white system font, at most two
lines wrapped at word boundaries, stretching with the panel. Put it inside the background.

```python
panel.setContentView_(background)
self.panel, self.label = panel, label
```
Make the background the panel's content and keep references to both.
