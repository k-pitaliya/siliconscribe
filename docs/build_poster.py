"""SiliconScribe EC486 poster, v3: narrative layout in the style the student chose (soft gradient background, rounded
white panels, purple sub-headings, light-blue result tiles, metrics table, dashed image frames, QR code to the repo).

Same CHARUSAT template (background, logos, title box). Numbers come from the verified fact sheet (docs_work/FACTS.md).
Usage: build_poster_v3.py <template.pptx> <out.pptx> <screenshots dir> <assets dir> <qr.png>
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.oxml.ns import qn
from lxml import etree
from PIL import ImageFont, Image

SRC, OUT, SHOTS, ASSETS, QR = sys.argv[1:6]

INK = RGBColor(0x11, 0x18, 0x27); BODY = RGBColor(0x1F, 0x29, 0x37); PURPLE = RGBColor(0x5B, 0x2C, 0x83)
DARKRED = RGBColor(0x9B, 0x1C, 0x1C); STEEL = RGBColor(0x2B, 0x5F, 0x8A); TEAL = RGBColor(0x2E, 0x6E, 0x8E)
TILE = RGBColor(0xDC, 0xEA, 0xF6); TILE_LINE = RGBColor(0xB9, 0xD0, 0xE6); WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PANEL_LINE = RGBColor(0xC9, 0xD6, 0xE3); DASH = RGBColor(0x7F, 0xA7, 0xC9); GREEN = RGBColor(0x15, 0x80, 0x3D)
AMBER = RGBColor(0xB4, 0x53, 0x09); RED = RGBColor(0xB9, 0x1C, 0x1C); NAVY = RGBColor(0x18, 0x2B, 0x49)
ROW_ALT = RGBColor(0xF3, 0xF7, 0xFB); SLATE = RGBColor(0x47, 0x55, 0x69)
T_BLUE = RGBColor(0xDB, 0xEA, 0xFE); T_GREEN = RGBColor(0xDC, 0xFC, 0xE7); T_RED = RGBColor(0xFE, 0xE2, 0xE2)
BLUE = RGBColor(0x25, 0x63, 0xEB)
FONT, MONO = "Times New Roman", "Courier New"
_F = {False: "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
      True: "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"}
I = Inches
REPORT = []

prs = Presentation(SRC)
slide = prs.slides[0]
tree = slide.shapes._spTree
title_shape = list(slide.shapes)[0]
for shp in list(slide.shapes)[1:]:
    tree.remove(shp._element)

# ---- title block recoloured like the reference: dark-red title, purple institution lines
for k, p in enumerate(title_shape.text_frame.paragraphs):
    for r in p.runs:
        r.font.color.rgb = DARKRED if k == 0 else PURPLE
        if k > 0:
            r.font.bold = True


def lines_needed(text, size, bold, width_in):
    f = ImageFont.truetype(_F[bold], int(size * 10)); maxw = width_in * 72 * 10 * 0.93; n = 0
    for hard in text.split("\n"):
        cur, k = "", 1
        for w in hard.split(" "):
            t = (cur + " " + w).strip()
            if f.getlength(t) <= maxw or not cur:
                cur = t
            else:
                k += 1; cur = w
        n += k
    return n


def parse(s, **base):
    out, bold = [], False
    for part in s.split("**"):
        if part:
            st = dict(base); st["bold"] = bold or base.get("bold", False); out.append((part, st))
        bold = not bold
    return out


def _bullet(p, indent_in):
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(int(I(indent_in)))); pPr.set("indent", str(-int(I(indent_in * 0.75))))
    for tag in ("a:buNone", "a:buChar", "a:buFont"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    f = etree.SubElement(pPr, qn("a:buFont")); f.set("typeface", "Arial")
    c = etree.SubElement(pPr, qn("a:buChar")); c.set("char", "•")


def fill(tf, paras, size, color, align, anchor, label, w, h, inset, space_after, bold=False, font=FONT):
    tf.word_wrap = True; tf.auto_size = None
    tf.margin_left = tf.margin_right = I(inset); tf.margin_top = tf.margin_bottom = I(inset * 0.5)
    tf.vertical_anchor = anchor
    need, first = 0.0, True
    for spec in paras:
        if isinstance(spec, str):
            spec = {"runs": parse(spec, bold=bold)}
        p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
        p.alignment = spec.get("align", align)
        ps = spec.get("size", size); sa = spec.get("space_after", space_after)
        p.space_after = Pt(sa)
        width = w - 2 * inset - 0.02
        if spec.get("bullet"):
            _bullet(p, 0.32); width -= 0.32
        for t, st in spec["runs"]:
            r = p.add_run(); r.text = t; fo = r.font
            fo.name = st.get("font", spec.get("font", font)); fo.size = Pt(st.get("size", ps)); fo.bold = st.get("bold", False)
            fo.italic = st.get("italic", spec.get("italic", False)); fo.color.rgb = st.get("color", spec.get("color", color))
        plain = "".join(t for t, _ in spec["runs"])
        b = sum(len(t) for t, st in spec["runs"] if st.get("bold")) > len(plain) / 2
        need += lines_needed(plain, ps, b, width) * ps * 1.17 / 72 + sa / 72
    need += inset
    REPORT.append((label, round(need, 2), round(h, 2)))


def text(x, y, w, h, paras, size=22, color=BODY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, label="", inset=0.04,
         space_after=6, bold=False, font=FONT):
    s = slide.shapes.add_textbox(I(x), I(y), I(w), I(h))
    fill(s.text_frame, paras, size, color, align, anchor, label or str(paras)[:40], w, h, inset, space_after, bold, font)
    return s


def shadow(shape):
    spPr = shape._element.spPr
    eff = etree.SubElement(spPr, qn("a:effectLst"))
    sh = etree.SubElement(eff, qn("a:outerShdw"))
    for k, v in {"blurRad": "88900", "dist": "25400", "dir": "5400000", "algn": "t", "rotWithShape": "0"}.items():
        sh.set(k, v)
    c = etree.SubElement(sh, qn("a:srgbClr")); c.set("val", "1F2937")
    a = etree.SubElement(c, qn("a:alpha")); a.set("val", "16000")


def box(x, y, w, h, fillc=WHITE, line=PANEL_LINE, lw=1.0, shape=MSO_SHAPE.RECTANGLE, paras=None, size=18, color=BODY,
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, label="", inset=0.1, bold=False, radius=None, dash=False,
        space_after=0, shade=False):
    s = slide.shapes.add_shape(shape, I(x), I(y), I(w), I(h))
    if radius is not None:
        s.adjustments[0] = radius
    if fillc is None: s.fill.background()
    else: s.fill.solid(); s.fill.fore_color.rgb = fillc
    if line is None: s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(lw)
        if dash: s.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    if shade: shadow(s)
    else: s.shadow.inherit = False
    if paras:
        fill(s.text_frame, paras, size, color, align, anchor, label or str(paras)[:40], w, h, inset, space_after, bold)
    return s


def arrow(x1, y1, x2, y2, color=SLATE, w=2.25, head=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, I(x1), I(y1), I(x2), I(y2))
    c.line.color.rgb = color; c.line.width = Pt(w)
    if head:
        t = etree.SubElement(c.line._get_or_add_ln(), qn("a:tailEnd")); t.set("type", "triangle"); t.set("w", "med"); t.set("len", "med")


def panel(x, y, w, h, title):
    box(x, y, w, h, fillc=WHITE, line=PANEL_LINE, lw=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.02, shade=True)
    text(x + 0.35, y + 0.2, w - 0.7, 0.85, [title], size=37, color=INK, bold=True, label="panel " + title)
    return x + 0.35, y + 1.15, w - 0.7


def sub(x, y, w, t):
    text(x, y, w, 0.62, [t], size=29, color=PURPLE, bold=True, label="sub " + t)
    return y + 0.68


def bullets(x, y, w, h, items, size=25, label="b", space_after=5, color=BODY):
    return text(x, y, w, h, [{"runs": parse(t), "bullet": True} for t in items], size=size, label=label,
                space_after=space_after, color=color)


LINE_H = lambda size: size * 1.17 / 72
CHIP = RGBColor(0xEF, 0xE9, 0xF7); CHIP_LINE = RGBColor(0xC9, 0xB8, 0xE3)


def para_h(t, size, w, bold=False):
    return lines_needed(t.replace("**", ""), size, bold, w - 0.1) * LINE_H(size) + 0.12


def steps(x, y, w, items, color=STEEL, size=23, gap=0.2, d=0.6, draw=True, label="steps"):
    """Numbered circle badges with text beside them (a stepper). Returns the height used."""
    yy = y; tw = w - d - 0.28
    for k, t in enumerate(items, 1):
        th = para_h(t, size, tw); h = max(d, th)
        if draw:
            box(x, yy, d, d, fillc=color, line=None, shape=MSO_SHAPE.OVAL, paras=[str(k)], size=size * 0.82,
                color=WHITE, bold=True, inset=0, label=f"{label} badge {k}")
            text(x + d + 0.28, yy + max(0.0, (d - LINE_H(size)) / 2 - 0.06), tw, th + 0.05, [t], size=size,
                 label=f"{label} {k}", inset=0.02, space_after=0)
        yy += h + gap
    return yy - y - gap


def kv_rows(x, y, w, rows, label_w=2.55, size=22, draw=True):
    """A two-column label / value table with soft row shading. Returns the height used."""
    yy = y
    for k, (lab, val) in enumerate(rows):
        h = max(para_h(val, size, w - label_w - 0.2), LINE_H(size) + 0.12) + 0.16
        if draw:
            box(x, yy, w, h, fillc=ROW_ALT if k % 2 == 0 else WHITE, line=None)
            box(x, yy, 0.07, h, fillc=PURPLE, line=None)
            text(x + 0.2, yy + 0.08, label_w - 0.2, h - 0.1, [lab], size=size, bold=True, color=PURPLE, label="kv " + lab, inset=0.02)
            text(x + label_w, yy + 0.08, w - label_w - 0.1, h - 0.1, [val], size=size, label="kv val " + lab, inset=0.02)
        yy += h
    return yy - y


def accent_cards(x, y, w, items, size=22, gap=0.22, draw=True):
    """Finding cards: a coloured side bar on a soft tint, bold lead phrase. items: (bar, tint, text)."""
    yy = y
    for k, (bar, tint, t) in enumerate(items):
        h = para_h(t, size, w - 0.45) + 0.22
        if draw:
            box(x, yy, w, h, fillc=tint, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
            box(x, yy, 0.13, h, fillc=bar, line=None)
            text(x + 0.32, yy + 0.1, w - 0.42, h - 0.12, [t], size=size, label=f"card {k}", inset=0.02, space_after=0)
        yy += h + gap
    return yy - y - gap


def chips(x, y, w, labels, size=20, gap=0.2, draw=True):
    """Rounded tag chips that wrap onto new rows. Returns the height used."""
    f = ImageFont.truetype(_F[True], int(size * 10)); ch = LINE_H(size) + 0.3
    cx, cy = x, y
    for lab in labels:
        cw = f.getlength(lab) / 720 + 0.55
        if cx + cw > x + w and cx > x:
            cx, cy = x, cy + ch + gap
        if draw:
            box(cx, cy, cw, ch, fillc=CHIP, line=CHIP_LINE, lw=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5,
                paras=[lab], size=size, bold=True, color=PURPLE, inset=0.05, label="chip " + lab)
        cx += cw + gap
    return cy + ch - y


def framed(path, x, y, w, h, caption, cap_h=0.7, crop=None):
    """Image centred in a dashed frame, italic caption under it (the reference poster's style)."""
    box(x, y, w, h, fillc=WHITE, line=DASH, lw=1.25, dash=True)
    im = Image.open(path); iw, ih = im.size
    if crop:
        l, t, r, b = crop; iw, ih = iw * (r - l), ih * (b - t)
    aw, ah = w - 0.3, h - 0.3 - cap_h
    sc = min(aw / iw, ah / ih); pw, ph = iw * sc, ih * sc
    pic = slide.shapes.add_picture(path, I(x + (w - pw) / 2), I(y + 0.15 + (ah - ph) / 2), I(pw), I(ph))
    if crop:
        pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = crop[0], crop[1], 1 - crop[2], 1 - crop[3]
    text(x + 0.15, y + h - cap_h - 0.08, w - 0.3, cap_h, [caption], size=19, color=TEAL, align=PP_ALIGN.CENTER,
         label="cap " + caption[:30], inset=0.02, space_after=0)
    for run in slide.shapes[-1].text_frame.paragraphs[0].runs:
        run.font.italic = True


# ---- soft gradient behind everything (light top, blue bottom), placed just above the template background
bgf = slide.background.fill
bgf.gradient(); bgf.gradient_angle = 90
st = bgf.gradient_stops
st[0].position, st[0].color.rgb = 0.0, RGBColor(0x5A, 0x8C, 0xBA)   # bottom
st[1].position, st[1].color.rgb = 1.0, RGBColor(0xEE, 0xF4, 0xFA)   # top

TOP, BOTTOM = 8.0, 35.25
XA, XB, XC = 0.8, 12.55, 24.3
WA = WB = 11.15
WC = 47.2 - XC

# =========================================================== column A: Abstract, Introduction
ix, iy, iw = panel(XA, TOP, WA, 9.75, "Abstract")
text(ix, iy - 0.05, iw, 7.75, [
    "Large language models can write Verilog, but they never run it, so the code is plausible text rather than "
    "verified hardware. **SiliconScribe** is a browser-based tool that closes this loop with a real simulator. A "
    "plain-English prompt becomes a typed specification; the RTL and an independent self-checking testbench are "
    "generated from it; Icarus Verilog 12 runs them, and failures return to the model as a structured diagnosis "
    "until the design passes.",
    "Every PASS also reports how much it is worth: testbench strength by mutation, measured toggle coverage, a "
    "second-opinion testbench, and a pre-layout timing and area estimate on SkyWater 130 nm whose netlist is "
    "formally proven equal to the RTL. In a live evaluation of 15 prompts, 14 completed and all 14 passed.",
    {"runs": [("Keywords: ", {"bold": True, "color": PURPLE}),
              ("LLM, RTL generation, Verilog, self-checking testbench, mutation testing, formal equivalence, "
               "static timing analysis, sky130", {"italic": True})]},
], size=25.5, space_after=10, label="abstract", align=PP_ALIGN.LEFT)

y = TOP + 9.75 + 0.45
ix, iy, iw = panel(XA, y, WA, BOTTOM - y, "Introduction")
_im = Image.open(f"{ASSETS}/diagram_open_vs_closed_loop.png")
frame_h = (iw - 0.3) * _im.size[1] / _im.size[0] + 0.3 + 0.7 + 0.1
BG_TEXT = ("Language models now write Verilog quickly, but they never compile or simulate it. In chip design, "
           "verification takes most of the effort, and a model told to \u201cmake it pass\u201d may weaken the "
           "testbench instead of fixing the design.")
PS_TEXT = ("Build a loop around any language model in which only a real simulator decides PASS or FAIL, failures are "
           "repaired from evidence, and every PASS states how much it can be trusted.")
OBJ = ["Testbench written from the specification only, never from the RTL",
       "The simulator as the only judge, with a guarded repair loop",
       "Measure each PASS: strength, coverage, second opinion",
       "Pre-layout timing and area on sky130, with a proven netlist",
       "Show the circuit as RTL-cell and gate-level schematics"]
h_bg, h_ps = para_h(BG_TEXT, 25.5, iw), para_h(PS_TEXT, 25.5, iw)
h_obj = steps(ix, 0, iw, OBJ, color=PURPLE, size=23, draw=False)
content = 3 * 0.68 + h_bg + h_ps + h_obj
gap = max(0.15, (BOTTOM - 0.3 - frame_h - (iy - 0.05) - content - 0.25) / 3)
yy = sub(ix, iy - 0.05, iw, "Background")
text(ix, yy, iw, h_bg + 0.15, [BG_TEXT], size=25.5, label="intro bg")
yy += h_bg + gap
yy = sub(ix, yy, iw, "Problem Statement")
text(ix, yy, iw, h_ps + 0.15, [PS_TEXT], size=25.5, label="problem")
yy += h_ps + gap
yy = sub(ix, yy, iw, "Objectives")
steps(ix, yy + 0.05, iw, OBJ, color=PURPLE, size=23, label="obj")
yy = BOTTOM - 0.3 - frame_h
framed(f"{ASSETS}/diagram_open_vs_closed_loop.png", ix, yy, iw, frame_h,
       "Open-loop generation versus the execution-grounded loop")

# =========================================================== column B: Methodology, Experimental Setup
MH = 12.6
ix, iy, iw = panel(XB, TOP, WB, MH, "Methodology")
mh = steps(ix, iy + 0.05, iw, [
    "Prompt to a typed JSON specification, which the user may review and edit",
    "RTL and testbench generated separately: the testbench never sees the RTL",
    "Sandbox and lint, then Icarus Verilog simulation with a timeout",
    "On FAIL: compiler fix, LLM diagnosis, minimal patch (up to 5 rounds); patches that delete checks are rejected",
    "On PASS: strength, toggle coverage, second opinion, timing, area and the netlist proof",
], color=STEEL, size=22.5, gap=0.17, d=0.58, label="method")
my = iy + 0.05 + mh + 0.15
text(ix, my, iw, 0.7, ["PASS  ⇔  Passed: N > 0  ∧  Failed: 0  ∧  clean exit"], size=23, color=PURPLE,
     align=PP_ALIGN.CENTER, font=MONO, bold=True, label="formula")
# compact flow diagram: row 1 generation -> simulation, row 2 repair loop (FAIL) and evidence (PASS)
dy = my + 0.85; dh = TOP + MH - 0.3 - dy
r1_pad = max(0.4, (dh - (0.95 + 0.95 + 2.1)) / 2)
box(ix, dy, iw, dh, fillc=WHITE, line=DASH, lw=1.25, dash=True)
bw, bh, gx = 1.78, 0.95, 0.27
labels = [("Prompt", SLATE), ("Spec", NAVY), ("RTL + TB", NAVY), ("Lint", NAVY), ("Icarus", BLUE)]
x0 = ix + (iw - (5 * bw + 4 * gx)) / 2; r1 = dy + r1_pad
for k, (lab, col) in enumerate(labels):
    xx = x0 + k * (bw + gx)
    box(xx, r1, bw, bh, fillc=col, line=col, paras=[lab], size=17, color=WHITE, bold=True, label="flow " + lab,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.12)
    if k < 4:
        arrow(xx + bw + 0.02, r1 + bh / 2, xx + bw + gx - 0.02, r1 + bh / 2)
r2 = r1 + bh + 0.95
rep_x = x0; rep_w = 2 * bw + gx + bw * 0.6; ev_x = x0 + 3 * (bw + gx) - 0.1; ev_w = x0 + 5 * bw + 4 * gx - ev_x
RB = min(2.1, dh - (r2 - dy) - 0.3)
box(rep_x, r2, rep_w, RB, fillc=T_RED, line=RED, lw=1.5, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06,
    paras=[{"runs": parse("**FAIL: repair**"), "color": RED, "size": 20}, "compiler fix, LLM diagnosis, minimal patch"],
    size=17.5, label="repair box", space_after=2)
box(ev_x, r2, ev_w, RB, fillc=T_GREEN, line=GREEN, lw=1.5,
    shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06,
    paras=[{"runs": parse("**PASS: evidence**"), "color": GREEN, "size": 20},
           "strength · coverage · 2nd opinion · timing · area · netlist proof"],
    size=17.5, label="evidence box", space_after=2)
icx = x0 + 4 * (bw + gx) + bw / 2
arrow(icx, r1 + bh, icx, r2 - 0.05, color=GREEN, w=2.75)                           # Icarus -> evidence (PASS)
text(icx + 0.08, r1 + bh + 0.22, 1.0, 0.45, ["PASS"], size=16, bold=True, color=GREEN, label="lbl pass", inset=0)
rtl_cx = x0 + 2 * (bw + gx) + bw / 2
arrow(rtl_cx, r2, rtl_cx, r1 + bh + 0.04, color=RED, w=2.75)                       # repair -> RTL + TB (patch)
text(rtl_cx + 0.08, r1 + bh + 0.22, 1.0, 0.45, ["patch"], size=16, bold=True, color=RED, label="lbl patch", inset=0)
arrow(icx - 0.55, r1 + bh, rep_x + rep_w + 0.02, r2 + 0.25, color=RED, w=2.75)     # Icarus -> repair (FAIL)
text(icx - 1.45, r1 + bh + 0.6, 1.0, 0.45, ["FAIL"], size=16, bold=True, color=RED, label="lbl fail", inset=0)

y = TOP + MH + 0.45
ix, iy, iw = panel(XB, y, WB, BOTTOM - y, "Experimental Setup")
kh = kv_rows(ix, iy + 0.0, iw, [
    ("EDA tools", "Icarus Verilog 12.0 \u00b7 Yosys 0.71 \u00b7 OpenSTA 3.2.0"),
    ("Library", "SkyWater sky130_fd_sc_hd, typical, 25\u00b0C, 1.8\u00a0V"),
    ("Software", "FastAPI \u00b7 React 18 + TypeScript \u00b7 SQLite"),
    ("Models", "OpenCode (DeepSeek V4.1 Flash, free), Cloudflare, NVIDIA NIM"),
    ("Evaluation", "15 prompts: 7 combinational, 6 sequential, 2 FSM"),
], label_w=2.5, size=21.5)
sy = iy + kh + 0.3
framed(f"{ASSETS}/diagram_architecture.png", ix, sy, iw, BOTTOM - 0.3 - sy,
       "Three-tier architecture: browser, backend, model router, EDA tools")

# =========================================================== column C/D: Test Results Discussion
RH = 19.6
ix, iy, iw = panel(XC, TOP, WC, RH, "Test Results Discussion")
lw_ = 10.9; rx = ix + lw_ + 0.45; rw = iw - lw_ - 0.45
kpis = [("14/14", "Live runs PASS"), ("102/111", "Injected bugs caught"), ("16/18", "Netlists proven"),
        ("27/27", "Mutation sweep")]
tw = (lw_ - 3 * 0.22) / 4
for k, (big, small) in enumerate(kpis):
    box(ix + k * (tw + 0.22), iy, tw, 1.95, fillc=TILE, line=TILE_LINE, lw=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
        radius=0.1, paras=[{"runs": parse(f"**{big}**"), "size": 46, "color": STEEL}, {"runs": parse(f"**{small}**"),
                                                                                      "size": 18.5, "color": BODY}],
        size=18.5, label="kpi " + big, space_after=0)
accent_cards(ix, iy + 2.25, lw_, [
    (GREEN, T_GREEN, "**Live evaluation:** 15 prompts, 14 completed; 8 passed first time and 6 after self-repair. "
                     "The 15th timed out and is reported as no result."),
    (STEEL, TILE, "**No false PASS:** hand-written reference testbenches confirmed all 14 designs."),
    (AMBER, RGBColor(0xFE, 0xF3, 0xC7), "**Models disagreed:** a separate testbench model failed a shift register "
                                        "(61/108). The app kept the FAIL; the testbench was at fault."),
    (PURPLE, CHIP, "**Second opinion:** after a repair rewrote a FIFO testbench, a fresh one agreed (3798/3798); "
                   "the original's 482 failures stayed as a warning."),
], size=23, gap=0.2)
text(rx, iy - 0.05, rw, 0.6, ["Verification metrics & evidence"], size=26, color=PURPLE, bold=True,
     align=PP_ALIGN.CENTER, label="table title")
rows = [("Metric", "Achieved", "Status"),
        ("Live evaluation (completed)", "14 / 14", "PASS"),
        ("Reference testbench check", "14 / 14 correct", "PASS"),
        ("Testbench strength", "102 / 111 (92%)", "PASS"),
        ("Toggle coverage", "100% on 13 of 14", "MEASURED"),
        ("Mutation sweep (built-in)", "27 / 27", "PASS"),
        ("Gate-level simulation", "19 / 19 match", "PASS"),
        ("Formal netlist = RTL", "16 / 18 proven", "PROVEN*"),
        ("Automated tests", "655 + 277", "PASS")]
cws = [rw * 0.46, rw * 0.30, rw * 0.24]; trh = 0.8; ty = iy + 0.72
for r, row in enumerate(rows):
    xx = rx
    for c, v in enumerate(row):
        hdr = r == 0
        col = WHITE if hdr else (GREEN if (c == 2 and v in ("PASS", "PROVEN*")) else (STEEL if c == 2 else BODY))
        box(xx, ty + r * trh, cws[c], trh, fillc=STEEL if hdr else (ROW_ALT if r % 2 == 0 else WHITE), line=PANEL_LINE,
            lw=0.75, paras=[v], size=21, bold=hdr or c == 2, color=col,
            align=PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER, label=f"t{r}{c}", inset=0.12)
        xx += cws[c]
text(rx, ty + len(rows) * trh + 0.05, rw, 0.5, ["* the 2 FSMs are not proven (state re-encoded by synthesis); 0 different"],
     size=18, color=SLATE, label="table note")
# evidence images
gy = iy + 8.6; gh = TOP + RH - 0.3 - gy
w1 = iw * 0.55; w2 = iw - w1 - 0.35
framed(f"{SHOTS}/s08_second_opinion.png", ix, gy, w1, gh * 0.47,
       "Live FIFO run: the original testbench still fails, so the PASS is shown as disputed")
framed(f"{ASSETS}/chart_live_evaluation.png", ix, gy + gh * 0.47 + 0.25, w1, gh * 0.53 - 0.25,
       "Testbench strength per design in the live evaluation", crop=(0, 0.215, 1, 1))
framed(f"{SHOTS}/schematic_counter_gate_full.png", ix + w1 + 0.35, gy, w2, gh,
       "Gate-level schematic of the built-in 4-bit counter (Schematic tab)")

# =========================================================== bottom row: Conclusion, Prepared By
by = TOP + RH + 0.45
CW = 13.9
ix, iy, iw = panel(XC, by, CW, BOTTOM - by, "Conclusion")
CONC = ("SiliconScribe closes the loop between a language model and a real simulator: only the simulator decides, "
        "and every PASS states how much it is worth. All 14 completed live runs passed and were confirmed by "
        "reference testbenches, and the sky130 netlist is formally proven equal to the RTL on 16 of 18 designs. "
        "The evidence is pre-layout and from simulation, on small designs run once each. Added after submission "
        "(24 Nov): a chat that answers questions from the run's waveform; every fix it proposes is re-simulated.")
FUT = ["Power from simulation activity", "Testbench hardening", "OpenROAD place and route", "SVA assertions",
       "Tiny Tapeout chip"]
h_c = para_h(CONC, 23, iw); h_f = chips(ix, 0, iw, FUT, size=20, draw=False)
g = max(0.2, (BOTTOM - 0.3 - (iy - 0.05) - h_c - 0.68 - h_f) / 2)
text(ix, iy - 0.05, iw, h_c + 0.15, [CONC], size=23, label="conclusion")
yy = sub(ix, iy - 0.05 + h_c + g, iw, "Future Work")
chips(ix, yy + 0.05, iw, FUT, size=20)

px = XC + CW + 0.4; pw_ = 47.2 - px
ix, iy, iw = panel(px, by, pw_, BOTTOM - by, "Prepared By:")
text(ix, iy - 0.1, iw, 2.55, [
    {"runs": parse("**Kushal Pitaliya (23EC105)**"), "size": 28, "color": INK},
    "B.Tech ECE, 7th Sem · EC486 Minor Project · AY 2026-27",
    {"runs": [("Guided By: ", {"bold": True, "color": PURPLE}), ("______________________", {})]},
    {"runs": [("HOD: ", {"bold": True, "color": PURPLE}), ("Dr. Upesh Patel, Dept. of EC Engg., CSPIT", {})]},
], size=21.5, label="prepared", space_after=5)
qs = BOTTOM - 0.3 - (iy + 2.55)
slide.shapes.add_picture(QR, I(ix), I(iy + 2.55), I(qs), I(qs))
text(ix + qs + 0.3, iy + 2.55, iw - qs - 0.3, qs, ["Scan for the complete source code, report and guide (GitHub repository)"],
     size=22, color=SLATE, anchor=MSO_ANCHOR.MIDDLE, label="qr text")

used = set(slide._element.xpath(".//@r:embed"))
for rId, rel in list(slide.part.rels.items()):
    if rel.reltype.endswith("/image") and rId not in used:
        slide.part.drop_rel(rId)
prs.save(OUT)
bad = [(l, n, a) for l, n, a in REPORT if n > a * 0.95 + 0.02]
import os
if os.environ.get("FITLOG"):
    for l, n, a in REPORT: print(f"FIT {l[:28]:28s} need {n:5.2f} have {a:5.2f} {n/a*100 if a else 0:5.0f}%")
print(f"saved {OUT}; text boxes {len(REPORT)}; overflowing {len(bad)}")
for l, n, a in bad:
    print(f"  OVERFLOW {l[:60]!r}: needs {n}, has {a}")
