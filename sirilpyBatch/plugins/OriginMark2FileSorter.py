# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
import shutil
from pathlib import Path
from dataclasses import dataclass
from sirilpy import LogColor # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry 

Plugin_Config = """
Plugin:
    Key: sorter
    Title: Sort Files
"""

@dataclass
class sirilFolder:
    fileName: str
    targetDir: str
    master_name: str
    moved: int

# Base Configuration, how the files are sorted
dir_config = [
    sirilFolder(fileName="light", targetDir="lights", master_name="",            moved=0),
    sirilFolder(fileName="bias",  targetDir="biases", master_name="bias_master", moved=0),
    sirilFolder(fileName="dark",  targetDir="darks",  master_name="dark_master", moved=0),
    sirilFolder(fileName="flat",  targetDir="flats",  master_name="flat_master", moved=0)]

@BatchPluginRegistry.register(Plugin_Config)
class OriginMark2FileSorter(BatchPlugin):

    def process(self):
        # ── 1) Working-Directory ────────────────────────────────
        workdir = Path(self.get_siril_wd())
        self.context.siril.log(f"[INFO] Working Directory: {workdir}", LogColor.GREEN)

        # ── 2) sort files into lights/biases/darks/flats ──
        for sirilFolder in dir_config:
            sirilFolder.moved = 0
            (workdir / sirilFolder.targetDir).mkdir(exist_ok=True)
            self.context.siril.log(f"[OK]   Ordner: {sirilFolder.targetDir}/", LogColor.GREEN)
            for f in sorted(workdir.iterdir()):
                if not f.is_file():
                    continue

                n = f.name.lower()
                if not n.startswith(sirilFolder.fileName):
                    continue

                if f.suffix.lower() not in (".fits", ".fit"):
                    continue

                # Move the file to the target directory and rename it to lowercase
                shutil.move(str(f), str(workdir / sirilFolder.targetDir / f.name.lower()))
                self.context.siril.log(f"[OK]   {f.name}  →  {sirilFolder.targetDir}/", LogColor.GREEN)
                sirilFolder.moved += 1

        for sirilFolder in dir_config:
            self.context.siril.log(f"[INFO] {sirilFolder.fileName.capitalize()}-Frames: {sirilFolder.moved}", LogColor.GREEN)

        # ── 3) create process directories and cleanup ─────────────────────
        masters_dir = workdir / "masters"
        self.reset_dir(masters_dir)
        self.reset_dir(workdir / "process")

        # ── 4) build Master-Calidration ─────────────────────
        self.context.siril.log(f"[INFO] building the master calibration files...", LogColor.GREEN)

        for sirilFolder in dir_config:
            if sirilFolder.master_name == "":
                continue
            self.build_master(sirilFolder)

        self.context.siril.log(f"\n[FERTIG] master-files are located in masters/:", LogColor.GREEN)
        for f in sorted(masters_dir.glob("*.fits")):
            self.context.siril.log(f"         {f.name}", LogColor.GREEN)

    # List all FiTS files in a folder
    def fits_files(self, folder: Path):
        return sorted(list(folder.glob("*.fits")) + list(folder.glob("*.fit")))

    # Count the number of FiTS files in a folder
    def fits_in(self, folder: Path) -> int:
        return len(self.fits_files(folder))

    # Build a master calibration file from the files in targetDir/
    #   - 0 files  -> skipped
    #   - 1 file   -> simply copied & renamed (Origin already provides an internally stacked file, no re-stacking needed)
    #   - >1 files -> stacked into a real master
    def build_master(self, sirilFolder: sirilFolder):
        workdir = Path(self.get_siril_wd())
        masters_dir = workdir / "masters"
        src_dir = workdir / sirilFolder.targetDir
        files = self.fits_files(src_dir)
        n = len(files)
        target_name = sirilFolder.master_name

        if n == 0:
            print(f"[WARN] No {sirilFolder.fileName}-Frames in {sirilFolder.targetDir}/, skip master creation.")
            return None

        if n == 1:
            dst_file = masters_dir / f"{sirilFolder.master_name}.fits"
            shutil.copy(str(files[0]), str(dst_file))
            print(f"[OK]   Single file copied: {files[0].name} → masters/{sirilFolder.master_name}.fits")
            return dst_file

        # --- mehrere Subframes: in Siril konvertieren und stacken ---
        self.cmd(f'cd "{workdir}"')
        self.cmd(f"cd {sirilFolder.targetDir}")
        self.cmd(f"convert {sirilFolder.fileName} -out=../process")
        self.cmd("cd ../process")

        # Flat is a single file, but it needs to be calibrated with the bias before stacking. 
        # So we check if a bias master exists and use it for calibration.
        if sirilFolder.fileName == "flat":
            bias_cfg = next((c for c in dir_config if c.fileName == "bias"), None)
            master_bias = masters_dir / f"{bias_cfg.master_name}.fits" if bias_cfg and bias_cfg.master_name else None

            if master_bias and master_bias.exists():
                self.cmd(f"calibrate flat -bias=../masters/{bias_cfg.master_name}")
                self.cmd("stack pp_flat rej 3 3 -norm=mul")
                stacked_name = "pp_flat_stacked.fits"
            else:
                self.cmd("stack flat rej 3 3 -norm=mul")
                stacked_name = "flat_stacked.fits"
        else:
            self.cmd(f"stack {sirilFolder.fileName} rej 3 3 -nonorm")
            stacked_name = f"{sirilFolder.fileName}_stacked.fits"

        self.cmd(f'cd "{workdir}"')

        stacked_path = workdir / "process" / stacked_name
        dst_file = masters_dir / f"{sirilFolder.master_name}.fits"
        if stacked_path.exists():
            shutil.move(str(stacked_path), str(dst_file))
            print(f"[OK]   {n} {sirilFolder.fileName}-Frames gestackt → masters/{sirilFolder.master_name}.fits")
        else:
            print(f"[FEHLER] Erwartete Stack-Ausgabe nicht gefunden: {stacked_path}")
            return None

        return dst_file

    def reset_dir(self, path: Path):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(exist_ok=True)