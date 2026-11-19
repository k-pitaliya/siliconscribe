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
content = 3 * 0.68 + 3.05 + 1.7 + 2.95
gap = max(0.0, (BOTTOM - 0.3 - frame_h - (iy - 0.05) - content) / 3)
yy = sub(ix, iy - 0.05, iw, "Background")
bullets(ix, yy, iw, 3.0, [
    "Language models now write Verilog quickly, but they never compile or simulate it.",
    "In chip design, verification takes most of the effort: someone has to prove the design works.",
    "Told to “make it pass”, a model may weaken the testbench instead of fixing the design.",
], label="intro bg")
yy += 3.05 + gap
yy = sub(ix, yy, iw, "Problem Statement")
text(ix, yy, iw, 1.65, ["Build a loop around any language model in which only a real simulator decides PASS or FAIL, "
                        "failures are repaired from evidence, and every PASS states how much it can be trusted."],
     size=25.5, label="problem")
yy += 1.7 + gap
yy = sub(ix, yy, iw, "Objectives")
bullets(ix, yy, iw, 2.85, [
    "Testbench written from the specification only, never from the RTL",
    "The simulator as the only judge, with a guarded repair loop",
    "Measure each PASS: strength, coverage, second opinion",
    "Pre-layout timing and area on sky130, with a proven netlist",
    "Show the circuit: RTL-cell and gate-level schematics",
], label="objectives", space_after=4)
yy = BOTTOM - 0.3 - frame_h
framed(f"{ASSETS}/diagram_open_vs_closed_loop.png", ix, yy, iw, frame_h,
       "Open-loop generation versus the execution-grounded loop")

# =========================================================== column B: Methodology, Experimental Setup
MH = 12.6
ix, iy, iw = panel(XB, TOP, WB, MH, "Methodology")
bullets(ix, iy - 0.05, iw, 4.6, [
    "Prompt → typed JSON specification (the user may review and edit it)",
    "RTL and testbench generated separately: the testbench never sees the RTL",
    "Sandbox and lint, then Icarus Verilog simulation with a timeout",
    "FAIL → compiler fix, then an LLM diagnosis and a minimal patch (up to 5 rounds); a patch that deletes checks is rejected",
    "PASS → evidence: strength, toggle coverage, second opinion, timing, area, netlist proof",
], label="method bullets", space_after=5)
my = iy + 4.6
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
bullets(ix, iy - 0.05, iw, 4.25, [
    "**Tools:** Icarus Verilog 12.0, Yosys 0.71, OpenSTA 3.2.0, SkyWater sky130_fd_sc_hd (typical, 25°C, 1.8 V)",
    "**Software:** FastAPI backend, React 18 + TypeScript frontend, SQLite",
    "**Models:** OpenCode (evaluation: DeepSeek V4.1 Flash, free), Cloudflare Workers AI, NVIDIA NIM; keys stay on the server",
    "**Evaluation:** 15 prompts (7 combinational, 6 sequential, 2 FSM), one run each",
], size=25, label="setup bullets", space_after=8)
sy = iy + 4.3
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
bullets(ix, iy + 2.25, lw_, 6.1, [
    "15 prompts, 14 completed: **8 passed first time, 6 after self-repair**; the 15th timed out and is reported as no result",
    "Hand-written reference testbenches confirmed all 14 designs: **no false PASS**",
    "A separate testbench model disagreed on a shift register (FAIL 61/108): the app refused to rewrite the checks; "
    "the testbench was at fault",
    "After a repair rewrote a FIFO testbench, a fresh **second opinion agreed** (3798/3798) and the original's 482 "
    "failures were shown as a warning",
], size=25, label="results bullets", space_after=9)
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
        ("Automated tests", "453 + 222", "PASS")]
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
       "Live FIFO run: PASS after one repair, second opinion agrees, warning kept")
framed(f"{ASSETS}/chart_live_evaluation.png", ix, gy + gh * 0.47 + 0.25, w1, gh * 0.53 - 0.25,
       "Testbench strength per design in the live evaluation", crop=(0, 0.215, 1, 1))
framed(f"{SHOTS}/schematic_counter_gate_full.png", ix + w1 + 0.35, gy, w2, gh,
       "Gate-level schematic of the built-in 4-bit counter (Schematic tab)")

# =========================================================== bottom row: Conclusion, Prepared By
by = TOP + RH + 0.45
CW = 13.9
ix, iy, iw = panel(XC, by, CW, BOTTOM - by, "Conclusion")
bullets(ix, iy - 0.05, iw, 2.75, [
    "A closed loop where only the simulator decides, and every PASS states how much it is worth",
    "14 of 14 completed live runs passed and were confirmed by reference testbenches",
    "The sky130 netlist is formally proven equal to the RTL on 16 of 18 designs",
    "Evidence is pre-layout and from simulation: small designs, one run each",
], size=25, label="conclusion", space_after=7)
yy = sub(ix, iy + 2.7 + max(0.3, (BOTTOM - 0.3 - (iy + 2.7) - 0.68 - 1.15) / 2), iw, "Future Work")
bullets(ix, yy, iw, BOTTOM - 0.3 - yy, [
    "Power from simulation activity; testbench hardening from missed bugs",
    "OpenROAD place and route, SVA assertions, and a Tiny Tapeout chip",
], size=25, label="future", space_after=5)

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
