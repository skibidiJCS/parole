"""Small helpers around the macOS Accessibility API ("AX").

AX lets an app with the Accessibility permission ask other apps about their
interface: which window and text field are focused, where they are, and
where the text cursor is. Parole uses it to place the live bubble inside the
app you're dictating into, and to look at the character before the cursor.

AX measures from the top-left of the main screen (y goes down); AppKit
measures from the bottom-left (y goes up). frame() and caret_frame() convert
to AppKit's (x, y, width, height).
"""

from AppKit import NSScreen, NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCopyParameterizedAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementSetMessagingTimeout,
    AXValueCreate,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXValueCFRangeType,
    kAXValueCGPointType,
    kAXValueCGRectType,
    kAXValueCGSizeType,
)

TIMEOUT = 0.05  # seconds; never let a slow app hold Parole up


def attribute(element, name):
    error, value = AXUIElementCopyAttributeValue(element, name, None)
    return value if error == kAXErrorSuccess else None


def parameterized(element, name, parameter):
    error, value = AXUIElementCopyParameterizedAttributeValue(element, name, parameter, None)
    return value if error == kAXErrorSuccess else None


def _frontmost_app():
    # Asking the frontmost app directly is more reliable than the
    # "system-wide" AX element, which sometimes refuses (-25204).
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    element = AXUIElementCreateApplication(app.processIdentifier())
    AXUIElementSetMessagingTimeout(element, TIMEOUT)
    return element


def focused_element():
    """The focused text field (or other control) in the frontmost app, or None."""
    app = _frontmost_app()
    return attribute(app, "AXFocusedUIElement") if app is not None else None


def focused_window():
    app = _frontmost_app()
    return attribute(app, "AXFocusedWindow") if app is not None else None


def selected_range(field):
    """(start, length) of the cursor/selection in a text field, or None."""
    value = attribute(field, "AXSelectedTextRange")
    if value is None:
        return None
    ok, text_range = AXValueGetValue(value, kAXValueCFRangeType, None)
    return tuple(text_range) if ok else None


def _to_appkit(x, y, width, height):
    top = NSScreen.screens()[0].frame().size.height  # the main screen sets the origin
    return (x, top - y - height, width, height)


def frame(element):
    """Where an element (window, text field) is on screen, or None."""
    position, size = attribute(element, "AXPosition"), attribute(element, "AXSize")
    if position is None or size is None:
        return None
    _, point = AXValueGetValue(position, kAXValueCGPointType, None)
    _, extent = AXValueGetValue(size, kAXValueCGSizeType, None)
    return _to_appkit(point.x, point.y, extent.width, extent.height)


def caret_frame(field):
    """Where the text cursor is drawn, or None if the app doesn't say."""
    text_range = selected_range(field)
    if text_range is None:
        return None
    start = text_range[0]
    # The cursor itself is an empty range; some apps only answer for the
    # character before it.
    for candidate in ((start, 0), (max(start - 1, 0), 1)):
        bounds = parameterized(field, "AXBoundsForRange", AXValueCreate(kAXValueCFRangeType, candidate))
        if bounds is None:
            continue
        _, rect = AXValueGetValue(bounds, kAXValueCGRectType, None)
        if rect.size.height > 0:
            return _to_appkit(rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)
    return None


def role(element):
    return attribute(element, "AXRole")
