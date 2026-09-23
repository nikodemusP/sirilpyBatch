# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional
from sirilpy import LogColor # type: ignore


# =============================================================================
# GraXpert
# =============================================================================

class GraXpert:

    # -------------------------------------------------------------------------
    # Constructor
    # -------------------------------------------------------------------------

    def __init__(
        self,
        sirl: Any,
        target: str,
        gpu: bool = True,
    ):
        self.siril = sirl
        self.gpu = gpu

        # Get the currently loaded image.
        filename = self.siril.get_image_filename()
        targetFileName = target

    # =========================================================================
    # DENOISING
    # =========================================================================

    def denoising(
        self,
        model: Optional[str] = None,
        strangth: float = None
    ):
        """
        Perform GraXpert denoising.

        The currently loaded Siril image is used automatically.
        """
        args = [
            
            "-cmd",
            "denoising",

            "-output",
            output_file,
        ]

        use_gpu = (
            self.gpu
            if gpu is None
            else gpu
        )

        args += [
            "-gpu",
            "true" if use_gpu else "false",
        ]

        if ai_version is not None:

            args += [
                "-ai_version",
                str(ai_version),
            ]

        args.append(self.filename)

        result = self._run(
            operation="denoising",
            args=args,
            output_file=output_file,
        )

        self._load_result(output_file)

        return result

    # =========================================================================
    # STELLAR DECONVOLUTION
    # =========================================================================

    def deconv_stellar(
        self,
        output: Optional[str] = None,
        strength: Optional[float] = None,
        gpu: Optional[bool] = None,
        **kwargs,
    ) -> GraXpertResult:
        """
        Stellar deconvolution.

        GraXpert 3.0.2 does not expose this operation through
        the CLI shown by:

            GraXpert --help

        This method is intentionally kept here so the public API
        remains stable when the deconvolution backend is added.
        """

        self.refresh_image()

        raise GraXpertDeconvolutionError(
            "GraXpert 3.0.2 does not expose stellar "
            "deconvolution through its CLI. "
            "The current CLI only supports "
            "'background-extraction' and 'denoising'."
        )

    # =========================================================================
    # OBJECT DECONVOLUTION
    # =========================================================================

    def deconv_obj(
        self,
        output: Optional[str] = None,
        strength: Optional[float] = None,
        gpu: Optional[bool] = None,
        **kwargs,
    ) -> GraXpertResult:
        """
        Object deconvolution.

        GraXpert 3.0.2 does not expose this operation through
        the CLI shown by:

            GraXpert --help
        """

        self.refresh_image()

        raise GraXpertDeconvolutionError(
            "GraXpert 3.0.2 does not expose object "
            "deconvolution through its CLI. "
            "The current CLI only supports "
            "'background-extraction' and 'denoising'."
        )

    # =========================================================================
    # VERSION
    # =========================================================================

    def version(self) -> str:
        """
        Return GraXpert version.
        """

        result = subprocess.run(
            [
                self.executable,
                "-v",
            ],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

        if result.returncode != 0:

            raise GraXpertExecutionError(
                result.stderr or result.stdout
            )

        return (
            result.stdout
            or result.stderr
        ).strip()

    # =========================================================================
    # INFO
    # =========================================================================

    def info(self) -> dict:
        """
        Return basic information about the GraXpert instance.
        """

        self.refresh_image()

        return {
            "executable": self.executable,
            "version": self.version(),
            "filename": self.filename,
            "gpu": self.gpu,
            "load_result": self.load_result,
        }


# =============================================================================
# Simple convenience functions
# =============================================================================

def background_extraction(
    **kwargs,
) -> GraXpertResult:
    """
    Convenience function.

    Example:

        from graxpert import background_extraction

        background_extraction(
            correction="Subtraction",
            smoothing=0.1,
        )
    """

    return GraXpert().background_extraction(
        **kwargs
    )


def denoising(
    **kwargs,
) -> GraXpertResult:
    """
    Convenience function.

    Example:

        from graxpert import denoising

        denoising()
    """

    return GraXpert().denoising(
        **kwargs
    )

