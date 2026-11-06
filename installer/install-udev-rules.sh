#!/bin/sh
# SolarScribe - install or remove the Linux camera udev rules and QHY firmware.
#
# The .deb and .rpm already do this through their maintainer scripts. This
# script is for the source tree and the portable tarball:
#   sudo installer/install-udev-rules.sh
#   sudo installer/install-udev-rules.sh --uninstall
#
# --root DIR is for CI and for a staged image; it prefixes every destination
# and skips udevadm, so the script can be exercised without root.
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

ROOT=""
UNINSTALL=0
NO_RELOAD=0
RULE_DIR="/etc/udev/rules.d"
FIRMWARE_DIR="/lib/firmware/qhy"

while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT=${2:?--root needs a directory}; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        --system) RULE_DIR="/usr/lib/udev/rules.d"; shift ;;
        --no-reload) NO_RELOAD=1; shift ;;
        --rules-dir) RULE_DIR=${2:?--rules-dir needs a path}; shift 2 ;;
        --firmware-dir) FIRMWARE_DIR=${2:?--firmware-dir needs a path}; shift 2 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ "$UNINSTALL" -eq 0 ] && [ -z "$ROOT" ] && [ "$(id -u)" -ne 0 ]; then
    echo "run as root, or use --root DIR to stage into an image" >&2
    exit 1
fi

rule_dst="${ROOT}${RULE_DIR}"
firmware_dst="${ROOT}${FIRMWARE_DIR}"
bundle="$here/vendor/bundle/linux/firmware/qhy"

if [ "$UNINSTALL" -eq 1 ]; then
    rm -f "$rule_dst/99-solarscribe-cameras.rules" \
          "$rule_dst/85-solarscribe-qhy.rules"
    # Remove only the firmware files this bundle installed, then the folder
    # only if it is empty: /lib/firmware/qhy may also belong to a distribution
    # libqhy package, and deleting the whole tree would break it.
    if [ -d "$bundle" ] && [ -d "$firmware_dst" ]; then
        (cd "$bundle" && find . -type f -print) | while IFS= read -r rel; do
            rm -f "$firmware_dst/${rel#./}"
        done
        rmdir "$firmware_dst" 2>/dev/null || true
    fi
    echo "removed SolarScribe udev rules and QHY firmware"
else
    install -d "$rule_dst"
    install -m 0644 "$here/udev/99-solarscribe-cameras.rules" \
        "$rule_dst/99-solarscribe-cameras.rules"
    echo "installed $rule_dst/99-solarscribe-cameras.rules"

    if [ -d "$bundle" ]; then
        install -d "$firmware_dst"
        cp -a "$bundle/." "$firmware_dst/"
        install -m 0644 "$here/udev/85-solarscribe-qhy.rules" \
            "$rule_dst/85-solarscribe-qhy.rules"
        echo "installed QHY firmware and $rule_dst/85-solarscribe-qhy.rules"
    else
        echo "no QHY firmware in the bundle: skipping the QHY loader rule"
        echo "  (the QHY SDK archive has no redistribution licence; see"
        echo "   installer/licenses/qhy.md)"
    fi
fi

if [ -z "$ROOT" ] && [ "$NO_RELOAD" -eq 0 ] && command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=usb
    echo "udev rules reloaded; unplug and replug the camera"
fi
