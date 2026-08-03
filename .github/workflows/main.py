#!/usr/bin/env python3
"""
Convert image/PDF -> DXF for GitHub Actions.
Usage: python main.py <input.pdf|input.png> <out_dir>
Requires system tools: poppler (pdftoppm), tesseract, potrace
"""
import sys
from pathlib import Path
import tempfile
import subprocess
from pdf2image import convert_from_path
from PIL import Image
import numpy as np
import cv2
import pytesseract
from skimage.metrics import structural_similarity as ssim
import cairosvg
from svgpathtools import svg2paths2
import ezdxf

def check_tool(name):
    from shutil import which
    return which(name) is not None

def load_input(path, dpi=300):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {path}")
    if path.suffix.lower() == ".pdf":
        pages = convert_from_path(str(path), dpi=dpi)
        return pages
    else:
        img = Image.open(path).convert("RGB")
        return [img]

def detect_text_boxes(img_pil, conf_thresh=50):
    data = pytesseract.image_to_data(img_pil, output_type=pytesseract.Output.DICT)
    boxes = []
    for i, txt in enumerate(data.get('text', [])):
        try:
            conf = float(data['conf'][i])
        except:
            conf = -1
        if txt and conf > conf_thresh:
            boxes.append({'x':data['left'][i],'y':data['top'][i],'w':data['width'][i],'h':data['height'][i],'text':txt})
    return boxes

def preprocess_for_tracing(img_pil, thresh=150, blur_radius=0, morph_iter=0):
    gray = np.array(img_pil.convert('L'))
    if blur_radius > 0:
        k = blur_radius*2+1
        gray = cv2.GaussianBlur(gray, (k,k), 0)
    _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)
    if morph_iter > 0:
        kernel = np.ones((3,3), np.uint8)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=morph_iter)
    return bw

def save_pbm(bw, out_path):
    im = Image.fromarray((bw>0).astype('uint8')*255)
    im = im.convert('1')
    im.save(out_path, format='PBM')

def call_potrace_to_svg(pbm_path, svg_out_path, turdsize=2, alphamax=1.0):
    cmd = ['potrace', str(pbm_path), '-s', '-o', str(svg_out_path), '--turdsize', str(turdsize), '--alphamax', str(alphamax)]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def render_svg_to_png(svg_text, png_out_path):
    cairosvg.svg2png(bytestring=svg_text.encode('utf8'), write_to=str(png_out_path))

def compute_ssim(img1_pil, img2_pil):
    a = np.array(img1_pil.convert('L'), dtype=np.float32)
    b = np.array(img2_pil.convert('L'), dtype=np.float32)
    if a.shape != b.shape:
        import cv2
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    try:
        return ssim(a, b, data_range=255)
    except Exception:
        return -1.0

def svg_to_dxf(svg_path, dxf_path, page_size):
    paths, attributes, svg_attr = svg2paths2(str(svg_path))
    doc = ezdxf.new('R2013')
    msp = doc.modelspace()
    width, height = page_size
    for p in paths:
        for sub in p.continuous_subpaths():
            length = max(sub.length(), 1e-6)
            n = max(int(length/2), 8)
            pts = []
            for t in np.linspace(0, 1, n):
                pt = sub.point(t)
                x, y = pt.real, pt.imag
                pts.append((x, height - y))
            if len(pts) >= 2:
                msp.add_lwpolyline(pts, close=False)
    doc.saveas(str(dxf_path))

def add_text_entities(dxf_path, boxes, page_size):
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:
        doc = ezdxf.new('R2013')
    msp = doc.modelspace()
    w, h = page_size
    for box in boxes:
        x = box['x']
        y = box['y']
        tx = x
        ty = h - y
        height_text = max(1.0, box['h'] * 0.75)
        try:
            msp.add_text(box['text'], dxfattribs={'height': height_text}).set_pos((tx, ty), align='LEFT')
        except Exception:
            continue
    doc.saveas(str(dxf_path))

def optimize_and_export(img_pil, out_dir, page_index=0):
    best = {'score': -1}
    thresholds = [120, 140, 160]
    blurs = [0,1]
    morphs = [0]
    turds = [1,2]
    boxes = detect_text_boxes(img_pil)
    for t in thresholds:
        for b in blurs:
            for m in morphs:
                for turd in turds:
                    bw = preprocess_for_tracing(img_pil, thresh=t, blur_radius=b, morph_iter=m)
                    mask = bw.copy()
                    for box in boxes:
                        x,y,w,h = box['x'],box['y'],box['w'],box['h']
                        y2 = min(mask.shape[0], y+h)
                        x2 = min(mask.shape[1], x+w)
                        mask[y:y2, x:x2] = 0
                    with tempfile.TemporaryDirectory() as tmp:
                        pbm = Path(tmp)/"tmp.pbm"
                        svg = Path(tmp)/"tmp.svg"
                        save_pbm(mask, pbm)
                        try:
                            call_potrace_to_svg(pbm, svg, turdsize=turd)
                        except subprocess.CalledProcessError:
                            continue
                        svg_text = svg.read_text()
                        png_tmp = Path(tmp)/"render.png"
                        try:
                            render_svg_to_png(svg_text, png_tmp)
                            rendered = Image.open(png_tmp).convert('RGB')
                        except Exception:
                            continue
                        score = compute_ssim(img_pil, rendered)
                        if score > best['score']:
                            best = {'score': score, 'svg_text': svg_text, 'boxes': boxes, 't':t,'b':b,'m':m,'turd':turd}
    if best['score'] < 0:
        raise RuntimeError("No successful trace")
    out_svg = Path(out_dir)/f'page_{page_index}.svg'
    out_svg.write_text(best['svg_text'])
    out_dxf = Path(out_dir)/f'page_{page_index}.dxf'
    svg_to_dxf(out_svg, out_dxf, img_pil.size)
    add_text_entities(out_dxf, best['boxes'], img_pil.size)
    return best['score'], out_dxf

def main():
    if len(sys.argv) < 3:
        print("Usage: python main.py <input.pdf|input.png> <out_dir>")
        sys.exit(2)
    if not check_tool('potrace'):
        print("Error: potrace not found in PATH")
        sys.exit(3)
    inp = sys.argv[1]
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = load_input(inp)
    results = []
    for i, page in enumerate(pages):
        print(f"[INFO] Processing page {i+1}/{len(pages)}")
        score, dxf = optimize_and_export(page, out_dir, page_index=i)
        print(f"[INFO] Page {i} -> SSIM={score:.4f} -> {dxf}")
        results.append((i, score, str(dxf)))
    print("Finished. Results:", results)

if __name__ == "__main__":
    main()
