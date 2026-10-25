# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
import sys

import sirilpy as s # type: ignore

# Dependencies must be installed BEFORE importing sirilpybatch, because importing it
# pulls in PyQt6 and PyYAML immediately.
s.ensure_installed("PyQt6", "numpy", "astropy", "pyyaml","sirilpybatch")

import sirilpybatch as batch

if __name__ == "__main__":
    batch.execute(sys.argv)