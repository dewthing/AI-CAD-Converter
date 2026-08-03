# AI-CAD-Converter (PDF/Image -> DXF)

This repo contains a simple pipeline to convert PDF/PNG images to DXF via GitHub Actions.

How it works (overview):
- Read PDF or image (pdf2image / PIL)
- OCR to detect text boxes (pytesseract) 12 create DXF TEXT entities
- Mask text areas, binarize and trace bitmap 12 SVG (potrace)
- Convert SVG paths to DXF polylines (svgpathtools + ezdxf)
- Optimize preprocessing parameters by checking SSIM between original image and rendered SVG

Files:
- `main.py` - converter script
- `requirements.txt` - python packages
- `.github/workflows/convert.yml` - GitHub Actions workflow
- `inputs/` - put your input file(s) here (e.g. inputs/sample.pdf)

Usage on GitHub:
1. Add the files above to your repo and push.
2. Put the PDF/PNG you want to convert into `inputs/` (e.g. `inputs/sample.pdf`) and push.
3. The workflow triggers on pushes to `inputs/**` or via Manual Run (Actions -> Run workflow).
4. After the run completes, download the artifact `dxf-results` from the Actions run page.

Notes:
- Runner installs system tools: `poppler-utils`, `tesseract-ocr`, `potrace`.
- If output is not ideal, tweak parameters inside `main.py` (thresholds, blurs, turdsize).
- DXF contains TEXT entities created from OCR; font/kerning may require manual adjustment.
- To get DWG, convert DXF externally (e.g., ODA File Converter or AutoCAD).
