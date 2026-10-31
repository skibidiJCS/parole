"""Build Parole.app with py2app.

    .venv/bin/python setup.py py2app -A

-A ("alias mode") makes a small app that runs parole.py and the packages
straight from this folder and .venv instead of copying them (MLX and torch
would add several GB). Code changes apply on the next launch without
rebuilding, but this folder and .venv must stay where they are.
"""

from setuptools import setup

setup(
    name="Parole",
    app=["parole.py"],
    options={
        "py2app": {
            "plist": {
                "CFBundleName": "Parole",
                "CFBundleDisplayName": "Parole",
                "CFBundleIdentifier": "local.parole.dictation",
                "CFBundleShortVersionString": "0.4",
                "LSUIElement": True,  # menu bar only: no Dock icon, no main window
                # Shown by macOS when Parole first asks for the microphone.
                # Without it, macOS refuses microphone access to an app.
                "NSMicrophoneUsageDescription": (
                    "Parole records your voice while you hold Shift + Right Command "
                    "and transcribes it on this Mac. Audio is never saved."
                ),
            },
        }
    },
)
