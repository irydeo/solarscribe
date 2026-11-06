############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - PyInstaller launcher module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Entry script for the frozen build.

PyInstaller runs its entry script as __main__, not as a package module, so a
relative import inside solarscribe/__main__.py would fail with "attempted
relative import with no known parent package". This two-line launcher gives
PyInstaller an absolute import and the rest of the app behaves exactly as it
does from `python -m solarscribe`.
"""

import sys

from solarscribe.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
