"""Build the portable Windows executable.

The compatibility override only skips PyInstaller's overly broad metadata check
for an old conda pathlib distribution. Python still imports its standard-library
pathlib module, which is the implementation used by this project.
"""
from pathlib import Path

import PyInstaller.__main__
import PyInstaller.compat


def main() -> None:
    project = Path(__file__).resolve().parent
    PyInstaller.compat.check_requirements = lambda: None
    PyInstaller.__main__.run([
        str(project / "main.py"),
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name=公考求职日历",
        f"--distpath={project / 'dist'}",
        f"--workpath={project / 'build'}",
        f"--specpath={project}",
    ])


if __name__ == "__main__":
    main()
