"""The live-preview bubble: a small floating panel showing words as you speak.

It's a borderless "non-activating" panel: it floats above every app (and
full-screen apps, on every Space) but never takes keyboard focus, so the
text still goes into the app you're dictating into. Clicks pass through it.
AppKit rule: only call show()/hide() on the main thread.
"""

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
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)

WIDTH, HEIGHT = 600, 66
MARGIN = 16
FROM_BOTTOM = 90  # points above the bottom of the screen (clear of the Dock)
MAX_CHARS = 120  # about two lines; older words scroll off the front


class Bubble:
    def __init__(self):
        self.panel = None
        self.label = None

    def show(self, text):
        if self.panel is None:
            self._build()
        if len(text) > MAX_CHARS:
            text = "…" + text[-MAX_CHARS:].split(" ", 1)[-1]  # cut at a word boundary
        self.label.setStringValue_(text)
        # Follow the screen you're working on (the one with the focused window).
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + (screen.size.width - WIDTH) / 2
        self.panel.setFrameOrigin_((x, screen.origin.y + FROM_BOTTOM))
        self.panel.orderFrontRegardless()  # show without activating Parole

    def hide(self):
        if self.panel is not None:
            self.panel.orderOut_(None)

    def _build(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, NSBackingStoreBuffered, False
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        # Dark blurred background with rounded corners.
        background = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
        background.setMaterial_(NSVisualEffectMaterialHUDWindow)
        background.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        background.setState_(NSVisualEffectStateActive)
        background.setWantsLayer_(True)
        background.layer().setCornerRadius_(18)
        background.layer().setMasksToBounds_(True)

        label = NSTextField.wrappingLabelWithString_("")
        label.setFrame_(NSMakeRect(MARGIN, 8, WIDTH - 2 * MARGIN, HEIGHT - 16))
        label.setFont_(NSFont.systemFontOfSize_(15))
        label.setTextColor_(NSColor.whiteColor())
        label.setMaximumNumberOfLines_(2)
        label.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        background.addSubview_(label)

        panel.setContentView_(background)
        self.panel, self.label = panel, label
