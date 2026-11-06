############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - entry point module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Command-line entry point. The GUI is the default; a dry run and a device
diagnostic are the other modes (they land in cli/).
"""

import sys


def main(argv=None):
    # @args: argv - command line arguments (defaults to sys.argv[1:])
    # @return: process exit code
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--version", "-V"):
        from . import __version__
        print(__version__)
        return 0
    # The GUI is the default entry point. It lands in ui/app.py; the skeleton
    # only declares the contract, so the import stays lazy.
    from .ui.app import run
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
