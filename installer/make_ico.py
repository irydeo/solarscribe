############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - Icon container builder module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Build installer/icons/solarscribe.ico from the already rendered PNGs.

The Windows installer needs one .ico file; Inno Setup does not read a PNG.
The PNGs themselves are produced by make-icons.sh with rsvg-convert, and the
result is committed so neither the Windows CI nor the Linux package build
needs an SVG renderer.

The container is written by hand because Pillow's ICO writer only stores one
frame when the frames come from separate files; the Windows shell and the
installer both pick a size from the directory, so every size must be there.
The entries carry PNG payloads (Vista and later), which is what rsvg-convert
already produced.
"""

import struct
import sys
from pathlib import Path


def build_ico(pngs, ico):
    # @args: pngs - [(size, Path)], ico - destination Path
    # @return: None
    blobs = [(size, path.read_bytes()) for size, path in pngs]
    # ICONDIR: reserved=0, type=1 (icon), count. Then one 16-byte directory
    # entry per image: width, height, palette, reserved, planes, bpp, length,
    # offset. A width or height of 0 means 256 in the ICO format.
    out = bytearray(struct.pack("<HHH", 0, 1, len(blobs)))
    offset = 6 + 16 * len(blobs)
    for size, data in blobs:
        out += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        )
        offset += len(data)
    for _size, data in blobs:
        out += data
    ico.write_bytes(out)


def main(argv=None):
    # @args: argv - [icon_dir, size...] (defaults to the sibling icons dir)
    # @return: process exit code
    args = list(sys.argv[1:] if argv is None else argv)
    out = Path(args[0]) if args else Path(__file__).resolve().parent / "icons"
    sizes = [int(s) for s in args[1:]] or [16, 32, 48, 64, 128, 256]

    pngs = []
    for size in sizes:
        png = out / f"solarscribe-{size}.png"
        if not png.is_file():
            print(f"missing {png}", file=sys.stderr)
            return 1
        pngs.append((size, png))
    ico = out / "solarscribe.ico"
    build_ico(pngs, ico)
    print(f"wrote {ico} ({len(pngs)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
