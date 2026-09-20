# Celestron Origin 2 → Siril Astrophotography Workflow

*Best-of-breed tools for stunning results — from stacked FITS to a finished image.*
based on the workflow created by Manoj Jayadevan

![Workflow Overview](images/workflow-overview.jpg)

> Work with 32-bit linear FITS for maximum quality throughout the linear stage.

## Table of Contents

- [Stage 1: Linear Processing](#stage-1-linear-processing)
- [Output at End of Linear Stage](#output-at-end-of-linear-stage)
- [Key Rules for Linear Processing](#key-rules-for-linear-processing)
- [Stage 2: Non-Linear Processing](#stage-2-non-linear-processing)
- [Tools at a Glance](#tools-at-a-glance)
- [Target-Specific Tips](#target-specific-tips)
- [General Tips for Success](#general-tips-for-success)
- [File Naming & Versioning](#file-naming--versioning)

---

## Stage 1: Linear Processing

*Preserve data — do all core corrections before stretching.*

| # | Step | Tool | Notes |
|---|------|------|-------|
| 1 | **Load Stacked FITS** | Siril | Use the stacked FITS from your Origin 2 (not the TIFF/JPEG). <br>Image will look dark — this is normal. <br>Use screen stretch only for viewing (no histogram stretch). |
| 2 | **Crop** | Siril | Remove stacking/edge artifacts. Keep as much of the field as possible. Don't crop aggressively. |
| 3 | **Gradient Removal** | GraXpert (recommended), VeraLux Nox, or Siril BE | Remove light pollution and background gradients. Use AI (GraXpert) or model-based (Nox). Be conservative for large faint nebulosity. |
| 4 | **Deconvolution** | RC Astro BlurXTerminator or GraXpert Deconvolution | Run while image is linear. Start with conservative settings. Corrects PSF and recovers detail. Do **NOT** run NoiseX first. |
| 5 | **Plate Solve** | Siril (Astrometry) | Identify the field. Usually automatic for Origin FITS (verify). Required for photometric color calibration. |
| 6 | **Color Calibration** | Siril (PCC / SPCC) | Use Photometric Color Calibration for natural color. Requires successful plate solve. Adjust if needed. Works well for broadband and narrowband (with care). |
| 7 | **Noise Reduction** | RC Astro NoiseXTerminator, VeraLux Silentium, or GraXpert Denoise | Run while still linear (can also run later). Use moderate settings. Preserve real detail. You can do a light second pass later if needed. |
| 8 | **Star Removal** | RC Astro StarXTerminator, StarNet++, or SyQon | Create separate starless and star images. Run **before** heavy stretching. Gives independent control of stars and DSO. |

### Output at End of Linear Stage

- ✅ Cropped image
- ✅ Gradient removed
- ✅ Deconvolved (BlurX)
- ✅ Color calibrated
- ✅ Noise reduced
- ✅ Starless and star images

**Now you're ready to stretch and enhance!**

### Key Rules for Linear Processing

1. Keep the image linear through step 8 (star removal).
2. Do **NOT** run NoiseX before BlurX.
3. Do **NOT** stretch before star separation.
4. Use GraXpert or VeraLux Nox for gradient removal (not both aggressively).
5. Be conservative to avoid removing real faint signal.
6. Use Photometric Color Calibration for accurate color.
7. Save intermediate versions.

---

## Stage 2: Non-Linear Processing

*Stretch, enhance, and recombine — now transform the data and bring out the beauty.*

| # | Step | Tool | Notes |
|---|------|------|-------|
| 9 | **Stretch Starless** | VeraLux HyperMetric (or Siril GHS / Asinh) | Use HyperMetric Stretch (recommended) or GHS. Bring out faint structures. Keep background dark gray (not pure black). |
| 10 | **Enhance Starless** | VeraLux Revela | Increase local contrast and detail. Use masks to protect bright regions. Adjust background and fine structure. |
| 11 | **Color Enhancement** | VeraLux Vectra | Refine color balance and saturation. Preserve natural color. Great for both broadband and narrowband. Finish with Siril curves if needed. |
| 12 | **Process Stars** | Siril or VeraLux | Stretch stars gently (keep them small). Use VeraLux StarComposer (optional) for star reduction and reconstruction. Avoid bloated stars. |
| 13 | **Recombine** | Siril (Pixel Math) or VeraLux StarComposer | Combine processed starless and stars images. Use StarComposer for advanced star control. Fine-tune star size and intensity. |
| 14 | **Final Noise Reduction** *(Optional)* | NoiseX or Silentium | Apply a very light pass if needed. Helps smooth background after stretching. Don't overdo it. |
| 15 | **Final Touches** | Siril or Photoshop | Final curves, color, and contrast. Subtle local adjustments. Crop, rotate, and frame. Export as TIFF (16-bit) for Photoshop. Add labels if desired. |

---

## Tools at a Glance

| Task | Recommended | Alternatives | Notes |
|------|-------------|---------------|-------|
| Gradient Removal | GraXpert AI | VeraLux Nox, Siril BE | Excellent for light pollution gradients |
| Deconvolution | BlurXTerminator | GraXpert Deconv | Run before NoiseX |
| Noise Reduction | NoiseXTerminator | VeraLux Silentium, GraXpert | Works in linear or non-linear |
| Star Removal | StarXTerminator | StarNet++, SyQon | Run before heavy stretching |
| Stretching | VeraLux HyperMetric | Siril GHS / Asinh | Preserves color relationships |
| Detail Enhancement | VeraLux Revela | Siril, Cosmic Clarity | Brings out fine structure |
| Color Enhancement | VeraLux Vectra | Siril curves | Advanced, natural color control |
| Star Recomposition | VeraLux StarComposer | Siril Pixel Math | Controls star size and appearance |

---

## Target-Specific Tips

### Galaxies (M31, M81, etc.)
- Use broadband workflow.
- Be careful with aggressive gradient removal.
- Stretch gently to preserve color and halos.

### Nebulae (North America, Veil, etc.)
- May require narrower-band filter (e.g. Origin nebula filter).
- Be conservative with background extraction.
- Use VeraLux tools for color and detail.
- Consider separate processing for narrowband.

### Clusters & Star Fields
- Light gradient removal is usually sufficient.
- Minimal deconvolution and NR.
- Gentle stretching to keep stars natural.

---

## General Tips for Success

- ✅ Always start from the best possible data (more integration time).
- ✅ Don't try to make the background pure black.
- ✅ Avoid over-processing — keep a natural look.
- ✅ Use masks to protect bright areas and stars.
- ✅ Experiment with different tools — each image is unique.
- ✅ Save different versions during the process.
- ✅ Most images are 90% finished in Siril — use Photoshop for final aesthetic work.

---

## File Naming & Versioning

Use clear names and keep intermediate files:

```
M31_linear.fits
M31_starless_stretched.fit
M31_stars_stretched.fit
M31_final.tif
```

---

## Directory Structure

```
.
├── README.md
└── images/
    └── workflow-overview.jpg   # Full infographic reference
```

---

*It all starts with a curious mind.*
**Celestron Origin 2 | Siril | GraXpert | RC Astro | VeraLux | Your Universe**
