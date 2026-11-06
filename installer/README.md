# Installer

Packaging for Windows and Linux. Populated by the packaging agent (ADR-004,
ADR-017):

- **Windows 10/11 x64**: PyInstaller (`.spec`) + Inno Setup (`.iss`).
- **Linux**: `.deb` (Debian/Ubuntu) and `.rpm` (Fedora/RHEL).

Reuses NightScribe's `installer/` layout. The camera SDK binaries travel inside;
on Linux the `udev` rules and (QHY) firmware are included. Platform
prerequisites are detected and reported: the ASCOM Platform (.NET) on Windows
for the mount, and a running `indiserver` on Linux.

Distribution is via GitHub Releases; the Windows installer is not code-signed.
