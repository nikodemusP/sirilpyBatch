import sys

import sirilpy as s # type: ignore

# Dependencies must be installed BEFORE importing sirilpyBatch, because importing it
# pulls in PyQt6 and PyYAML immediately.
s.ensure_installed("PyQt6", "numpy", "astropy", "pyyaml")

import sirilpyBatch as batch

if __name__ == "__main__":
    batch.execute(sys.argv)