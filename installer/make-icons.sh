#!/bin/sh
# Regenerate the PNG/ICO icon set from installer/icons/solarscribe.svg.
# The generated files are committed so the Windows and Linux builds do not
# need rsvg-convert or Pillow; run this only when the SVG changes.
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
src="$here/icons/solarscribe.svg"
out="$here/icons"

for size in 16 32 48 64 128 256; do
    rsvg-convert -w "$size" -h "$size" -o "$out/solarscribe-${size}.png" "$src"
done

# make_ico.py builds the Windows .ico container from the PNGs with the
# standard library only; the committed .ico is what the Windows build reads.
python3 "$here/make_ico.py" "$out" 16 32 48 64 128 256
echo "icons written to $out"
