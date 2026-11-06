############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - smoke test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""The first green test: the package imports and its layers are importable.

It is the seed of the safety net (strict TDD). Real tests come with each layer.
"""


def test_package_imports():
    import solarscribe
    assert solarscribe.__version__


def test_layers_import():
    # The layer packages exist and import cleanly on their own.
    from solarscribe import capture, cli, config, devices, shg, ui  # noqa: F401
