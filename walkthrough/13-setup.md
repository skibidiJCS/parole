# setup.py — building Parole.app

[setup.py](../setup.py) tells **py2app** how to wrap parole.py into a macOS `.app` bundle.
Run it with:

```bash
.venv/bin/python setup.py py2app -A
```

`-A` is "alias mode": instead of copying Python, MLX and torch into the app (several GB), the
app just points at this folder and `.venv`. Code changes apply on the next launch without
rebuilding, but the folder must stay where it is.

---

```python
from setuptools import setup     # the standard Python packaging tool; py2app plugs into it

setup(
    name="Parole",
    app=["parole.py"],           # the script the app runs
    options={
        "py2app": {
            "iconfile": "icon/Parole.icns",   # the icon (made by icon/make_icon.py)
            "plist": {                         # Info.plist: the app's metadata for macOS
                "CFBundleName": "Parole",            # short name
                "CFBundleDisplayName": "Parole",     # name shown in Finder
                "CFBundleIdentifier": "local.parole.dictation",  # unique ID; macOS ties
                                                     # permissions (mic, Accessibility) to it
                "CFBundleShortVersionString": "0.4", # version number
                "LSUIElement": True,                 # "agent" app: no Dock icon, no main window
                "NSMicrophoneUsageDescription": (    # text of macOS's microphone prompt;
                    "Parole records your voice ..."  # without it macOS refuses mic access
                ),
            },
        }
    },
)
```
The two strings inside `NSMicrophoneUsageDescription`'s parentheses are adjacent literals, so
Python joins them into one.
