"""Test setup: make this repo's custom_components/stiga importable.

pytest-homeassistant-custom-component puts its own `custom_components` test package on the
path, which would shadow ours, so our directory is added to that package's search path.
"""

import pathlib

import pytest_homeassistant_custom_component.testing_config.custom_components as _harness_package

_harness_package.__path__.append(str(pathlib.Path(__file__).parents[1] / "custom_components"))
