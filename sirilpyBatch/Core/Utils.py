# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
"""Utilities to scan a directory of FITS files and read frame type, exposure and ISO."""
import os
from typing import Callable, NamedTuple, Optional

FITS_EXTENSIONS = (".fit", ".fits", ".fts")
EXPOSURE_KEYS = ("EXPTIME", "EXPOSURE")
ISO_KEYS = ("ISOSPEED", "ISO")
FRAME_KEYS = ("IMAGETYP", "FRAMETYP", "FRAME")

# normalised frame type -> words that identify it in the header text (checked in this order)
_FRAME_WORDS = (
    ("bias", ("bias", "zero", "offset")),
    ("dark", ("dark",)),
    ("flat", ("flat",)),
    ("light", ("light", "science", "object")),
)


class FrameInfo(NamedTuple):
    """One scanned FITS file. Unpacks like a plain tuple: path, frame_type, exposure, iso."""
    path: str                    # full path of the file
    frame_type: Optional[str]    # 'light' | 'bias' | 'dark' | 'flat' | 'darkflat' | other text | None
    exposure: Optional[float]    # seconds
    iso: Optional[float]

    @property
    def name(self) -> str:
        """File name without directory."""
        return os.path.basename(self.path)


def read_fits_header(path: str) -> dict:
    """Minimal FITS primary-header reader (80-char cards in 2880-byte blocks)."""
    header = {}
    with open(path, "rb") as f:
        while True:
            block = f.read(2880)
            if len(block) < 2880:
                break
            for i in range(0, 2880, 80):
                card = block[i:i + 80].decode("ascii", errors="replace")
                keyword = card[:8].strip()
                if keyword == "END":
                    return header
                if card[8:10] != "= ":
                    continue
                raw = card[10:].strip()
                if raw.startswith("'"):
                    end = raw.find("'", 1)
                    value = raw[1:end] if end > 0 else raw[1:]
                else:
                    value = raw.split("/")[0].strip()
                header[keyword] = value.strip()
    return header


def header_number(header: dict, keys) -> Optional[float]:
    """First numeric header value among ``keys`` (rounded to 3 decimals), or None."""
    for key in keys:
        try:
            return round(float(header[key]), 3)
        except (KeyError, ValueError):
            continue
    return None


def frame_type(header: dict) -> Optional[str]:
    """Normalised frame type ('light', 'bias', 'dark', 'flat', 'darkflat') or None if absent."""
    for key in FRAME_KEYS:
        text = str(header.get(key, "")).lower()
        if not text:
            continue
        if "dark" in text and "flat" in text:
            return "darkflat"
        for name, words in _FRAME_WORDS:
            if any(word in text for word in words):
                return name
        return text  # unknown label, kept verbatim so it never equals a known type
    return None


def scanDirectory(
    path: str,
    extensions: tuple = FITS_EXTENSIONS,
    on_error: Optional[Callable[[str, Exception], None]] = None,
) -> list[FrameInfo]:
    """
    Read all FITS files directly inside ``path`` (not recursive), sorted by file name.

    Returns a list of ``FrameInfo(path, frame_type, exposure, iso)``. Files whose header
    can't be read are skipped and reported to ``on_error(path, exception)`` if given.
    A missing or invalid directory yields an empty list.
    """
    frames: list[FrameInfo] = []
    if not path or not os.path.isdir(path):
        return frames

    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if not (name.lower().endswith(extensions) and os.path.isfile(full)):
            continue
        try:
            header = read_fits_header(full)
        except OSError as exc:
            if on_error:
                on_error(full, exc)
            continue
        frames.append(FrameInfo(
            path=full,
            frame_type=frame_type(header),
            exposure=header_number(header, EXPOSURE_KEYS),
            iso=header_number(header, ISO_KEYS),
        ))
    return frames
