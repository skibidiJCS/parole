"""The live-preview bubble: a small floating panel showing words as you speak.

It's a borderless "non-activating" panel: it floats above other windows but
never takes keyboard focus, so the text still goes into the app you're
dictating into. Clicks pass through it.

It sits inside that app's window: right under the text cursor (or the text
field) when the app tells us where it is, else at the bottom of the window.
While it's visible we check the window's position 10 times a second
(via Accessibility, see ax.py), so it follows the window when you drag it.
AppKit rule: only call these methods on the main thread.
"""

import rumps
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSLineBreakByWordWrapping,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSTextField,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)

import ax

MAX_WIDTH, MIN_WIDTH, HEIGHT = 560, 220, 62
INSET = 12  # minimum distance from the window's edges
GAP = 8  # distance from the text cursor / field
MARGIN = 14  # text padding inside the bubble
FOLLOW_INTERVAL = 0.1  # seconds between position checks
TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}


def anchor_frame():
    """Where the text is being typed: the cursor, else a small text field."""
    field = ax.focused_element()
    if field is None:
        return None
    caret = ax.caret_frame(field)
    if caret is not None:
        return caret
    if ax.role(field) in TEXT_ROLES:
        frame = ax.frame(field)
        if frame and frame[3] <= 150:  # a one- or few-line box, not a whole document
            return frame
    return None


def bubble_frame():
    """(x, y, width) for the bubble, kept inside the focused window."""
    window = ax.focused_window()
    window = ax.frame(window) if window is not None else None
    if window is None:  # no window info: bottom of the screen, as a last resort
        screen = NSScreen.mainScreen().visibleFrame()
        return screen.origin.x + (screen.size.width - MAX_WIDTH) / 2, screen.origin.y + 90, MAX_WIDTH

    wx, wy, ww, wh = window
    width = max(MIN_WIDTH, min(MAX_WIDTH, ww - 2 * INSET))
    anchor = anchor_frame()
    if anchor is not None:
        x_anchor, y_anchor, w_anchor, h_anchor = anchor
        x = x_anchor + w_anchor / 2 - width / 2
        y = y_anchor - GAP - HEIGHT  # just below
        if y < wy + INSET:
            y = y_anchor + h_anchor + GAP  # no room below: just above
    else:
        x, y = wx + (ww - width) / 2, wy + INSET  # bottom of the window
    # Never stick out of the window.
    x = min(max(x, wx + INSET), wx + ww - INSET - width)
    y = min(max(y, wy + INSET), wy + wh - INSET - HEIGHT)
    return x, y, width


class Bubble:
    def __init__(self):
        self.panel = None
        self.label = None
        self.text = ""
        self.timer = rumps.Timer(lambda _: self._place(), FOLLOW_INTERVAL)

    def show(self, text):
        if self.panel is None:
            self._build()
        self.text = text
        visible = self.panel.isVisible()
        self._place()
        if not visible:
            self.panel.orderFrontRegardless()  # show without activating Parole
            self.timer.start()

    def hide(self):
        self.timer.stop()
        if self.panel is not None:
            self.panel.orderOut_(None)

    def _place(self):
        try:
            x, y, width = bubble_frame()
        except Exception:
            return  # an app answered something odd; keep the last position
        frame = self.panel.frame()
        if (frame.origin.x, frame.origin.y, frame.size.width) != (x, y, width):
            self.panel.setFrame_display_(NSMakeRect(x, y, width, HEIGHT), True)
        max_chars = int((width - 2 * MARGIN) / 7.5) * 2  # about two lines
        text = self.text
        if len(text) > max_chars:
            text = "…" + text[-max_chars:].split(" ", 1)[-1]  # older words scroll off the front
        self.label.setStringValue_(text)

    def _build(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, MAX_WIDTH, HEIGHT), style, NSBackingStoreBuffered, False
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        # Dark blurred background with rounded corners; it stretches with the panel.
        background = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, MAX_WIDTH, HEIGHT))
        background.setMaterial_(NSVisualEffectMaterialHUDWindow)
        background.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        background.setState_(NSVisualEffectStateActive)
        background.setWantsLayer_(True)
        background.layer().setCornerRadius_(16)
        background.layer().setMasksToBounds_(True)
        background.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        label = NSTextField.wrappingLabelWithString_("")
        label.setFrame_(NSMakeRect(MARGIN, 7, MAX_WIDTH - 2 * MARGIN, HEIGHT - 14))
        label.setFont_(NSFont.systemFontOfSize_(14))
        label.setTextColor_(NSColor.whiteColor())
        label.setMaximumNumberOfLines_(2)
        label.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        label.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        background.addSubview_(label)

        panel.setContentView_(background)
        self.panel, self.label = panel, label
