from __future__ import annotations

"""Windows GUI entry point for the Ability Draft command builder.

This file is intentionally tiny:
- it reads the project VERSION file, if present;
- it passes that version string into the Tkinter UI;
- it does not contain app logic itself.

Keeping the launcher minimal makes it easier to audit and replace later.
"""

from pathlib import Path

from ad_ui.app import main


def read_version() -> str:
    """Read the optional VERSION file from the project root.

    Returns an empty string if the file is missing or unreadable.
    The UI already knows how to handle an empty version by simply
    not appending anything extra to the window title.
    """
    version_path = Path(__file__).resolve().parent / "VERSION"
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


if __name__ == "__main__":
    # Launch the GUI and pass in the version string for display in the title bar.
    main(version=read_version())
