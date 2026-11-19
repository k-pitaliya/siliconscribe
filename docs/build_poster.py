"""Build the SiliconScribe EC486 poster (48 x 36 in) on the existing CHARUSAT template.

Keeps the template's layout (background, both logos) and the title text box; every other shape is rebuilt here
from plain shapes (boxes, arrows, bars), so it renders the same in PowerPoint, Keynote and Quick Look and stays editable.
All numbers come from docs_work/FACTS.md, backend/evaluation/summary.md and the live runs cited there.
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree
from PIL import ImageFont, Image

SRC, OUT, SHOTS = sys.argv[1], sys.argv[2], sys.argv[3]

# ---------------------------------------------------------------- palette (the template's theme colours + tints)
NAVY = RGBColor(0x18, 0x2B, 0x49); BLUE = RGBColor(0x25, 0x63, 0xEB); GREEN = RGBColor(0x15, 0x80, 0x3D)
RED = RGBColor(0xB9, 0x1C, 0x1C); SLATE = RGBColor(0x47, 0x55, 0x69); AMBER = RGBColor(0xB4, 0x53, 0x09)
TXT = RGBColor(0x0F, 0x17, 0x2A); WHITE = RGBColor(0xFF, 0xFF, 0xFF); BORDER = RGBColor(0xCB, 0xD5, 0xE1)
T_BLUE = RGBColor(0xDB, 0xEA, 0xFE); T_GREEN = RGBColor(0xDC, 0xFC, 0xE7); T_RED = RGBColor(0xFE, 0xE2, 0xE2)
T_AMBER = RGBColor(0xFE, 0xF3, 0xC7); T_GREY = RGBColor(0xF1, 0xF5, 0xF9); T_NAVY = RGBColor(0xE0, 0xE7, 0xF1)
GRID = RGBColor(0xE2, 0xE8, 0xF0); GREY = RGBColor(0x94, 0xA3, 0xB8)
FONT, MONO = "Times New Roman", "Courier New"
FONTDIR = "/System/Library/Fonts/Supplemental/"
_F = {False: FONTDIR + "Times New Roman.ttf", True: FONTDIR + "Times New Roman Bold.ttf"}
LINE = 1.17           # PowerPoint line height for Times New Roman at single spacing, as a multiple of the size

prs = Presentation(SRC)
slide = prs.slides[0]
tree = slide.shapes._spTree
for shp in list(slide.shapes)[1:]:        # keep shape 0: the red title + institution lines
    tree.remove(shp._element)

I = Inches
REPORT = []                               # text-fit report: (label, needed_in, available_in)


# ---------------------------------------------------------------- text measurement (real font metrics)
def _wrap_lines(text, size, bold, width_in):
    font = ImageFont.truetype(_F[bold], size * 10)
    maxw = width_in * 72 * 10 * 0.93     # renderers draw Times up to ~7% wider than these metrics
    lines = 0
    for hard in text.split("\n"):
        words, cur = hard.split(" "), ""
        n = 1
        for w in words:
            trial = (cur + " " + w).strip()
            if font.getlength(trial) <= maxw or not cur:
                cur = trial
            else:
                n += 1
                cur = w
        lines += n
    return lines


def _plain(runs):
    return "".join(t for t, _ in runs)


def parse(s, **base):
    """'**bold** text' -> [(text, style)] ; style keys: bold, color, size, font, italic."""
    out, bold = [], False
    for i, part in enumerate(s.split("**")):
        if part:
            st = dict(base)
            st["bold"] = bold or base.get("bold", False)
            out.append((part, st))
        bold = not bold
    return out


def fill_tf(tf, paras, size, color, align, anchor, label, w_in, h_in, inset, space_after, bold=False, font=FONT, line=1.0):
    tf.word_wrap = True
    tf.auto_size = None
    for side in ("left", "right"):
        setattr(tf, f"margin_{side}", I(inset))
    tf.margin_top = I(inset * 0.6); tf.margin_bottom = I(inset * 0.6)
    tf.vertical_anchor = anchor
    need = 0.0
    first = True
    for p_spec in paras:
        if isinstance(p_spec, str):
            p_spec = {"runs": parse(p_spec, bold=bold)}
        elif isinstance(p_spec, list):
            p_spec = {"runs": p_spec}
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = p_spec.get("align", align)
        psize = p_spec.get("size", size)
        p.space_after = Pt(p_spec.get("space_after", space_after))
        if line != 1.0:
            p.line_spacing = line
        for text, st in p_spec["runs"]:
            r = p.add_run(); r.text = text
            f = r.font; f.name = st.get("font", p_spec.get("font", font)); f.size = Pt(st.get("size", psize))
            f.bold = st.get("bold", False); f.italic = st.get("italic", p_spec.get("italic", False))
            f.color.rgb = st.get("color", p_spec.get("color", color))
        mostly_bold = sum(len(t) for t, st in p_spec["runs"] if st.get("bold")) > len(_plain(p_spec["runs"])) / 2
        n = _wrap_lines(_plain(p_spec["runs"]), psize, mostly_bold, w_in - 2 * inset - 0.02)
        need += n * psize * LINE * line / 72 + p_spec.get("space_after", space_after) / 72
    need += inset * 1.2
    REPORT.append((label, round(need, 2), round(h_in, 2)))


def text(x, y, w, h, paras, size=20, color=TXT, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, label="", inset=0.04,
         space_after=4, bold=False, font=FONT, line=1.0):
    s = slide.shapes.add_textbox(I(x), I(y), I(w), I(h))
    fill_tf(s.text_frame, paras, size, color, align, anchor, label or str(paras)[:40], w, h, inset, space_after, bold, font, line)
    return s


def box(x, y, w, h, fill=WHITE, line=BORDER, lw=1.25, shape=MSO_SHAPE.RECTANGLE, paras=None, size=16, color=TXT,
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, label="", inset=0.08, bold=False, radius=None, dash=False,
        space_after=0, font=FONT):
    s = slide.shapes.add_shape(shape, I(x), I(y), I(w), I(h))
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(lw)
        if dash:
            from pptx.enum.dml import MSO_LINE_DASH_STYLE
            s.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    s.shadow.inherit = False
    if paras:
        fill_tf(s.text_frame, paras, size, color, align, anchor, label or str(paras)[:40], w, h, inset, space_after, bold, font)
    return s


def arrow(x1, y1, x2, y2, color=SLATE, w=2.25, head=True, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, I(x1), I(y1), I(x2), I(y2))
    c.line.color.rgb = color; c.line.width = Pt(w)
    ln = c.line._get_or_add_ln()
    if dash:
        d = etree.SubElement(ln, qn("a:prstDash")); d.set("val", "dash")
    if head:
        t = etree.SubElement(ln, qn("a:tailEnd")); t.set("type", "triangle"); t.set("w", "med"); t.set("len", "med")
    return c


def card(x, y, w, h, title, body, head_fill=NAVY, body_fill=WHITE, title_size=15, body_size=14, head_h=0.46,
         label="", body_align=PP_ALIGN.CENTER, body_anchor=MSO_ANCHOR.MIDDLE, body_inset=0.09):
    """The earlier poster's block style: a coloured title strip over a tinted body."""
    box(x, y, w, h, fill=body_fill, line=head_fill, lw=1.5)
    box(x, y, w, head_h, fill=head_fill, line=head_fill, lw=1.5, paras=[title], size=title_size, color=WHITE, bold=True,
        label=(label or title) + " (title)", inset=0.06)
    box(x, y + head_h, w, h - head_h, fill=None, line=None, paras=body, size=body_size, align=body_align,
        anchor=body_anchor, label=(label or title) + " (body)", inset=body_inset)


def panel(x, y, w, h, title):
    box(x, y, w, h, fill=WHITE, line=BORDER, lw=1.5)
    box(x, y, w, 0.09, fill=NAVY, line=None)                       # navy rule on top of every panel
    text(x + 0.25, y + 0.2, w - 0.5, 0.75, [title], size=29, color=NAVY, bold=True, label="panel: " + title)
    return x + 0.25, y + 0.98, w - 0.5                              # inner left, top, width


def picture(path, x, y, w, h=None, crop=None, border=True):
    im = Image.open(path)
    iw, ih = im.size
    if crop:  # (l, t, r, b) fractions
        l, t, r, b = crop
        iw2, ih2 = iw * (r - l), ih * (b - t)
    else:
        iw2, ih2 = iw, ih
    if h is None:
        h = w * ih2 / iw2
    pic = slide.shapes.add_picture(path, I(x), I(y), I(w), I(h))
    if crop:
        pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = crop[0], crop[1], 1 - crop[2], 1 - crop[3]
    if border:
        pic.line.color.rgb = BORDER; pic.line.width = Pt(1.25)
    return h


# ================================================================ geometry
COLX = [0.75, 12.58, 24.42, 36.25]
CW = 11.0
GAP = 0.4
TOP, BOTTOM = 8.2, 35.2

# ================================================================ COLUMN 1
x0 = COLX[0]
# ---- Abstract
y = TOP; h = 6.0
ix, iy, iw = panel(x0, y, CW, h, "Abstract")
text(ix, iy, iw, h - 1.05, [
    "Large language models (LLMs) can write Verilog, but they never run it: the output is plausible text, not verified "
    "hardware. **SiliconScribe** is a browser-based EDA playground that closes this loop with a real simulator. A "
    "plain-English prompt becomes a typed specification; the RTL and an independent self-checking testbench are "
    "generated from it; **Icarus Verilog 12** runs them, and failures return to the model as a structured diagnosis and "
    "a minimal patch until the design passes.",
    "Because a PASS is only as strong as its testbench, every PASS also reports how much it is worth: testbench "
    "strength by mutation, measured toggle coverage, a second-opinion testbench after a repair, an optional separate "
    "testbench model, and a pre-layout **timing and area** estimate on SkyWater 130 nm (Yosys + OpenSTA). In a live "
    "evaluation of 15 prompts with a free model, **14 completed and all 14 passed** (8 first attempt, 6 after repair); "
    "their testbenches caught **102 of 111** injected bugs, and hand-written reference testbenches confirmed all 14 "
    "designs correct.",
], size=20.5, space_after=8, label="abstract", align=PP_ALIGN.JUSTIFY)

# ---- Introduction & Problem Statement
y = y + h + GAP; h = 8.3
ix, iy, iw = panel(x0, y, CW, h, "Introduction & Problem Statement")
dy = iy
box(ix, dy, iw, 3.45, fill=T_GREY, line=BORDER)
text(ix + 0.15, dy + 0.08, iw - 0.3, 0.42, ["Open-loop LLM generation vs. the execution-grounded loop"], size=16, bold=True,
     color=NAVY, label="intro diagram title")
text(ix + 0.15, dy + 0.55, 4, 0.36, ["Raw LLM (open loop)"], size=14, bold=True, color=SLATE, label="row1")
bx = [ix + 0.2, ix + 2.75, ix + 5.3, ix + 7.85]; bw = 2.3
labels1 = [("Prompt", SLATE), ("LLM", SLATE), ("Verilog text", SLATE), ("Never executed?", RED)]
for (lab, col), xx in zip(labels1, bx):
    box(xx, dy + 0.95, bw, 0.62, fill=col, line=col, paras=[lab], size=15, color=WHITE, bold=True, label="r1 " + lab)
for xx in bx[:-1]:
    arrow(xx + bw, dy + 1.26, xx + bw + 0.25, dy + 1.26)
text(ix + 0.15, dy + 1.72, 5, 0.36, ["SiliconScribe (closed loop)"], size=14, bold=True, color=NAVY, label="row2")
bx2 = [ix + 0.2, ix + 2.2, ix + 4.2, ix + 6.2, ix + 8.2]; bw2 = 1.75
labels2 = [("Prompt", NAVY), ("Spec", NAVY), ("RTL + TB", NAVY), ("Icarus sim", BLUE), ("PASS", GREEN)]
for (lab, col), xx in zip(labels2, bx2):
    box(xx, dy + 2.1, bw2, 0.62, fill=col, line=col, paras=[lab], size=15, color=WHITE, bold=True, label="r2 " + lab)
for xx in bx2[:-1]:
    arrow(xx + bw2, dy + 2.41, xx + bw2 + 0.25, dy + 2.41)
# feedback: Icarus -> back to RTL+TB
fx1, fx2, fyb = bx2[3] + bw2 / 2, bx2[2] + bw2 / 2, dy + 3.05
arrow(fx1, dy + 2.72, fx1, fyb, color=RED, head=False)
arrow(fx1, fyb, fx2, fyb, color=RED, head=False)
arrow(fx2, fyb, fx2, dy + 2.74, color=RED)
text(fx2 + 0.1, fyb - 0.02, 2.0, 0.36, ["FAIL: diagnose + patch"], size=12.5, color=RED, bold=True, label="fb label",
     align=PP_ALIGN.CENTER)
text(ix, dy + 3.6, iw, h - 3.6 - 1.05, [
    "• **Verification gap:** an engineer must write both the design and the testbench that proves it; code "
    "generation alone solves neither.",
    "• **No execution awareness:** a model cannot observe a clock edge or a race; it produces plausible text, not "
    "evidence.",
    "• **Test evasion:** told to “make it pass”, a model may weaken the testbench or delete checks instead of "
    "fixing the design.",
    "• **Goal:** a trustworthy loop around any generator, where only the simulator decides PASS or FAIL and each PASS "
    "states how much it is worth.",
], size=21, space_after=7, label="intro bullets")

# ---- Experimental Setup & Implementation
y = y + h + GAP; h = 5.8
ix, iy, iw = panel(x0, y, CW, h, "Experimental Setup & Implementation")
rows = [
    ("Simulator", "Icarus Verilog 12.0 (iverilog -g2012, vvp)"),
    ("Synthesis", "Yosys 0.71: generic cells and sky130 mapping"),
    ("Static timing", "OpenSTA 3.2.0 (built from source)"),
    ("Cell library", "SkyWater sky130_fd_sc_hd, typical, 25°C, 1.8 V"),
    ("Backend", "Python 3.14, FastAPI, Pydantic, SQLite"),
    ("Frontend", "React 18, TypeScript, Vite, SVG waveform"),
    ("Evaluation model", "DeepSeek V4.1 Flash (free), OpenCode app"),
    ("Other sources", "Cloudflare Workers AI (40), NVIDIA NIM (15)"),
    ("Platform, tests", "Apple M4, macOS; 453 pytest + 222 Vitest"),
]
rh = 0.5
for k, (a, b) in enumerate(rows):
    yy = iy + k * rh
    fill = T_NAVY if k % 2 == 0 else WHITE
    box(ix, yy, 3.0, rh, fill=fill, line=BORDER, lw=0.75, paras=[a], size=16, bold=True, color=NAVY, align=PP_ALIGN.LEFT,
        label="setup k " + a, inset=0.1)
    box(ix + 3.0, yy, iw - 3.0, rh, fill=fill, line=BORDER, lw=0.75, paras=[b], size=16, align=PP_ALIGN.LEFT,
        label="setup v " + a, inset=0.1)

# ---- The tool in use (real screenshot)
y = y + h + GAP; h = BOTTOM - y
ix, iy, iw = panel(x0, y, CW, h, "Gate-Level Schematic View")
gh = (y + h - 0.25) - iy
_im = Image.open(f"{SHOTS}/schematic_counter_gate_full.png"); gw = gh * _im.size[0] / _im.size[1]
picture(f"{SHOTS}/schematic_counter_gate_full.png", ix, iy, gw, gh)
text(ix + gw + 0.3, iy, iw - gw - 0.3, gh, [
    "The **Schematic tab** draws every run as RTL cells and as gates, from its own Yosys netlist.",
    "Shown: the built-in 4-bit counter, four flip-flops with asynchronous reset and the next-state gates.",
    "The sky130 netlist behind the timing numbers is also **formally proven** equal to the RTL.",
], size=16, label="schematic caption", space_after=6)

# ================================================================ COLUMN 2
x0 = COLX[1]
# ---- System Architecture
y = TOP; h = 11.75
ix, iy, iw = panel(x0, y, CW, h, "System Architecture")
# tier 1: frontend
fy, fh = iy, 2.35
box(ix, fy, iw, fh, fill=T_BLUE, line=BLUE, lw=1.75)
box(ix, fy, iw, 0.5, fill=BLUE, line=BLUE, paras=["FRONTEND  ·  React 18 + TypeScript + Vite (in the browser)"],
    size=16, color=WHITE, bold=True, label="fe title")
chips = ["Prompt + model menu", "Spec review", "Run timeline (SSE)", "Results + evidence", "Test cases", "Waveform (VCD)",
         "Schematic", "Projects + themes"]
cw4 = (iw - 0.3 - 3 * 0.15) / 4
for k, c in enumerate(chips):
    cx = ix + 0.15 + (k % 4) * (cw4 + 0.15); cy = fy + 0.68 + (k // 4) * 0.8
    box(cx, cy, cw4, 0.64, fill=WHITE, line=BLUE, lw=1, paras=[c], size=15.5, label="fe chip " + c, inset=0.05)
# arrow 1
a1y = fy + fh
arrow(ix + iw / 2, a1y, ix + iw / 2, a1y + 0.62, color=NAVY, w=2.75)
arrow(ix + iw / 2 - 0.25, a1y + 0.62, ix + iw / 2 - 0.25, a1y, color=NAVY, w=2.75)
text(ix + iw / 2 + 0.12, a1y + 0.1, 5.05, 0.45, ["HTTP JSON + Server-Sent Events · localhost only (CORS)"], size=13.5,
     color=SLATE, label="arrow1 label")
# tier 2: backend
by, bh = a1y + 0.68, 2.55
box(ix, by, iw, bh, fill=T_NAVY, line=NAVY, lw=1.75)
box(ix, by, iw, 0.5, fill=NAVY, line=NAVY, paras=["BACKEND  ·  FastAPI + Pydantic (Python 3.14)"], size=16,
    color=WHITE, bold=True, label="be title")
chips = ["API routes + rate limit", "Orchestrator: repair loop + guards", "Sandbox policy (allow-list)",
         "Evidence checks after PASS", "SQLite projects", "UVM export (16 files)"]
cw3 = (iw - 0.3 - 2 * 0.15) / 3
for k, c in enumerate(chips):
    cx = ix + 0.15 + (k % 3) * (cw3 + 0.15); cy = by + 0.66 + (k // 3) * 0.9
    box(cx, cy, cw3, 0.74, fill=WHITE, line=NAVY, lw=1, paras=[c], size=15.5, label="be chip " + c, inset=0.05)
# arrows to tier 3
t3y = by + bh + 0.7
lx, rx = ix + 2.55, ix + iw - 2.55
arrow(lx, by + bh, lx, t3y, color=NAVY, w=2.75)
arrow(rx, by + bh, rx, t3y, color=NAVY, w=2.75)
text(lx + 0.12, by + bh + 0.12, 2.6, 0.45, ["prompts and replies"], size=13.5, color=SLATE, label="a2 label")
text(rx + 0.12, by + bh + 0.12, 2.5, 0.45, ["subprocess + limits"], size=13.5, color=SLATE, label="a3 label")
# tier 3: model router + EDA tools
t3h = iy + (h - 1.05) - t3y
w3 = (iw - 0.3) / 2
box(ix, t3y, w3, t3h, fill=T_AMBER, line=AMBER, lw=1.75)
box(ix, t3y, w3, 0.5, fill=AMBER, line=AMBER, paras=["MODEL ROUTER"], size=16, color=WHITE, bold=True, label="mr title")
rows = ["**OpenCode app:** about 460 models, free first; Copilot auto", "**Cloudflare Workers AI:** live catalogue",
        "**NVIDIA NIM:** live catalogue", "**Offline demo:** always labelled as such"]
for k, r in enumerate(rows):
    box(ix + 0.12, t3y + 0.62 + k * 0.7, w3 - 0.24, 0.6, fill=WHITE, line=AMBER, lw=1, paras=[r], size=14.5,
        align=PP_ALIGN.LEFT, label="mr " + r[:20], inset=0.08)
text(ix + 0.1, t3y + 0.62 + 4 * 0.7 - 0.02, w3 - 0.2, 0.4, ["Keys only in backend/.env, never in the page"], size=13,
     color=AMBER, bold=True, align=PP_ALIGN.CENTER, label="mr keys")
ex = ix + w3 + 0.3
box(ex, t3y, w3, t3h, fill=T_GREEN, line=GREEN, lw=1.75)
box(ex, t3y, w3, 0.5, fill=GREEN, line=GREEN, paras=["EDA TOOLS"], size=16, color=WHITE, bold=True, label="eda title")
rows = ["**Icarus Verilog 12.0:** compile, simulate, VCD", "**Yosys 0.71:** synthesis + sky130 mapping",
        "**OpenSTA 3.2.0:** setup timing, slack", "**sky130 liberty:** tt corner, 25°C, 1.8 V"]
for k, r in enumerate(rows):
    box(ex + 0.12, t3y + 0.62 + k * 0.7, w3 - 0.24, 0.6, fill=WHITE, line=GREEN, lw=1, paras=[r], size=14.5,
        align=PP_ALIGN.LEFT, label="eda " + r[:20], inset=0.08)
text(ex + 0.1, t3y + 0.62 + 4 * 0.7 - 0.02, w3 - 0.2, 0.4, ["Every tool runs in an isolated work folder"], size=13,
     color=GREEN, bold=True, align=PP_ALIGN.CENTER, label="eda note")

# ---- Methodology & Closed-Loop Pipeline (flowchart)
y = y + h + GAP; h = BOTTOM - y
ix, iy, iw = panel(x0, y, CW, h, "Methodology & Closed-Loop Pipeline")
mx, mw = ix, 5.35                    # main column
rx0, rw = ix + 6.25, iw - 6.25       # right column
cxm = mx + mw / 2
yy = iy
steps = []


def step(yy, hh, title, body, fill=T_NAVY, line=NAVY, head=NAVY):
    card(mx, yy, mw, hh, title, [body], head_fill=head, body_fill=fill, title_size=15, body_size=15.5, head_h=0.44,
         label="step " + title)
    return yy + hh


e = step(yy, 1.05, "1  PROMPT", "plain-English description of the block")
arrow(cxm, e, cxm, e + 0.3); yy = e + 0.3
e = step(yy, 1.32, "2  SPECIFICATION PARSER", "typed JSON: ports, widths, reset, behaviour; optional user review and edit")
arrow(cxm, e, cxm, e + 0.3); yy = e + 0.3
hw = (mw - 0.2) / 2
card(mx, yy, hw, 1.62, "3a  RTL GENERATOR", ["Verilog-2001, Icarus-safe, from the spec"], title_size=14.5, body_size=15,
     head_h=0.44, label="3a")
card(mx + hw + 0.2, yy, hw, 1.62, "3b  TESTBENCH GEN.", ["spec only, RTL withheld; optional separate model"],
     head_fill=BLUE, body_fill=T_BLUE, title_size=14.5, body_size=15, head_h=0.44, label="3b")
e = yy + 1.62
arrow(cxm, e, cxm, e + 0.3); yy = e + 0.3
e = step(yy, 1.05, "4  SANDBOX + LINT", "allow-listed system tasks; no file or process access")
arrow(cxm, e, cxm, e + 0.3); yy = e + 0.3
sim_y = yy
e = step(yy, 1.05, "5  SIMULATE (ICARUS 12)", "iverilog -g2012, vvp with timeout, VCD", fill=T_BLUE, line=BLUE, head=BLUE)
arrow(cxm, e, cxm, e + 0.25); yy = e + 0.25
dh, dw = 1.3, 3.2
dmd = box(cxm - dw / 2, yy, dw, dh, fill=T_AMBER, line=AMBER, lw=1.75, shape=MSO_SHAPE.DIAMOND, paras=["Verdict?"], size=16,
          bold=True, color=TXT, label="diamond")
d_mid = yy + dh / 2
e = yy + dh
arrow(cxm, e, cxm, e + 0.38, color=GREEN, w=2.75)
text(cxm + 0.1, e + 0.0, 1.0, 0.36, ["PASS"], size=14, bold=True, color=GREEN, label="pass label")
yy = e + 0.38
ev_h = 2.55
card(mx, yy, mw, ev_h, "6  EVIDENCE FOR EACH PASS", [
    "original testbench re-run, if repair changed it",
    "second opinion: a fresh testbench",
    "strength: up to 12 injected bugs",
    "toggle coverage from the VCD",
    "timing, area + netlist proof (sky130)"],
     head_fill=GREEN, body_fill=T_GREEN, title_size=15, body_size=15.5, head_h=0.44, label="evidence")
e = yy + ev_h
arrow(cxm, e, cxm, e + 0.3); yy = e + 0.3
step(yy, BOTTOM - 0.25 - yy, "7  RESULTS", "results, test cases, waveform, schematic; saved to SQLite; UVM export")
# right column: repair loop, aligned with the simulate/verdict rows
rp_y, rp_h = sim_y - 1.6, 5.15
box(rx0, rp_y, rw, rp_h, fill=T_RED, line=RED, lw=1.75)
box(rx0, rp_y, rw, 0.5, fill=RED, line=RED, paras=["REPAIR LOOP (≤ 5 rounds)"], size=15, color=WHITE, bold=True,
    label="repair title")
text(rx0 + 0.08, rp_y + 0.55, rw - 0.16, rp_h - 0.6, [
    "**1.** Compiler repair first (wire→reg, disable→return)",
    "**2.** LLM diagnosis: symptom, root cause, fix location, confidence",
    "**3.** Minimal patch to the RTL or the testbench",
    "**Guards:** a patch that deletes checks is rejected; no-op and oscillating repairs stop the loop; a separately "
    "written testbench is never rewritten to hide a FAIL",
], size=18, space_after=8, label="repair body", inset=0.08)
# arrows: diamond -> repair (FAIL), repair -> simulate (re-simulate)
arrow(cxm + dw / 2, d_mid, rx0, d_mid, color=RED, w=2.75)
text(cxm + dw / 2 + 0.02, d_mid - 0.42, 1.6, 0.38, ["FAIL / ERROR"], size=13.5, bold=True, color=RED, label="fail lbl",
     align=PP_ALIGN.CENTER)
sy_mid = sim_y + 0.52
arrow(rx0, sy_mid, mx + mw, sy_mid, color=RED, w=2.75)
text(mx + mw + 0.02, sy_mid - 0.4, rx0 - mx - mw - 0.04, 0.38, ["re-run"], size=13.5, bold=True, color=RED, label="rerun lbl",
     align=PP_ALIGN.CENTER)
# right column: verdict rules
vr_y = rp_y + rp_h + 0.3
box(rx0, vr_y, rw, BOTTOM - 0.25 - vr_y, fill=T_GREY, line=SLATE, lw=1.5, paras=[
    {"runs": parse("**Verdict rules**"), "size": 17, "color": NAVY},
    "PASS only with a whole-line Passed: N (N > 0) and Failed: 0, no FAIL or ERROR line and a clean exit.",
    "Zero checks is never PASS; a watchdog that fires first gives ERROR.",
    {"runs": parse("**Only the simulator decides, never the model.**"), "color": NAVY},
], size=16, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, label="verdict rules", space_after=6, inset=0.12)

# ================================================================ COLUMN 3
x0 = COLX[2]
# ---- Verification & Trust Features
y = TOP; h = 9.55
ix, iy, iw = panel(x0, y, CW, h, "Verification & Trust Features")
text(ix, iy - 0.08, iw, 0.78, ["A PASS is evidence, not proof: it is only as strong as the testbench. Four mechanisms "
                               "check the checker, each shown here with a real live run."], size=17.5, color=SLATE,
     label="trust intro")
cw2 = (iw - 0.25) / 2; chh = (y + h - 0.28 - (iy + 0.8) - 0.2) / 2
cards = [
    ("SEPARATE TESTBENCH MODEL", BLUE, T_BLUE,
     "A second model, even another provider, writes the testbench. A failing check is reported, never rewritten away.",
     "**Live:** shift register FAIL 61/108, models disagree. By hand: the testbench had two reset bugs; the RTL passes "
     "108/108 once they are fixed."),
    ("SECOND OPINION", GREEN, T_GREEN,
     "If a repair rewrote the testbench, a fresh one is generated from the same spec and run on the final design.",
     "**Live:** FIFO PASS 4134/4134; fresh testbench agrees 3798/3798; the original still fails 482 checks, shown as a "
     "warning."),
    ("SPECIFICATION REVIEW", AMBER, T_AMBER,
     "The parsed spec (ports, behaviour, constraints) is shown first; the user edits it and the run uses exactly that spec.",
     "**Live:** up/down counter PASS 8672/8672; a hand-written reference model found 0 mismatches in 40,027 cycles."),
    ("STRENGTH + TOGGLE COVERAGE", NAVY, T_NAVY,
     "Up to 12 one-token bugs are injected into each passing design; toggle coverage is read from the simulator's VCD.",
     "**Evaluation:** 102 of 111 injected bugs caught (92%); toggle coverage 100% on 13 of 14 designs."),
]
for k, (t, hc, bc, d, live) in enumerate(cards):
    cx = ix + (k % 2) * (cw2 + 0.25); cy = iy + 0.8 + (k // 2) * (chh + 0.2)
    card(cx, cy, cw2, chh, t, [d, {"runs": parse(live), "color": hc}], head_fill=hc, body_fill=bc, title_size=17,
         body_size=19.5, head_h=0.55, body_align=PP_ALIGN.LEFT, body_anchor=MSO_ANCHOR.TOP, label="trust " + t,
         body_inset=0.16)

# ---- Timing & Area Stage
y = y + h + GAP; h = 7.05
ix, iy, iw = panel(x0, y, CW, h, "Timing & Area Stage (Pre-Layout)")
nb = 5; gw = 0.36; fw = (iw - (nb - 1) * gw) / nb; fh2 = 2.85
flow = [
    ("RTL", SLATE, T_GREY, ["design that", "passed", "simulation"]),
    ("YOSYS 0.71", NAVY, T_NAVY, ["flatten,", "keep tri-states,", "map to sky130"]),
    ("CHECKS", RED, T_RED, ["refuse", "tri-states,", "latches, loops,", "derived clocks"]),
    ("OPENSTA 3.2", BLUE, T_BLUE, ["clocks from", "the netlist,", "timed at target"]),
    ("REPORT", GREEN, T_GREEN, ["slack,", "period or path,", "area, cells"]),
]
for k, (t, hc, bc, d) in enumerate(flow):
    fx = ix + k * (fw + gw)
    card(fx, iy, fw, fh2, t, [{"runs": parse(ln), "space_after": 0} for ln in d], head_fill=hc, body_fill=bc, title_size=15, body_size=15, head_h=0.5,
         label="flow " + t, body_inset=0.2)
    if k < nb - 1:
        arrow(fx + fw + 0.04, iy + fh2 / 2 + 0.25, fx + fw + gw - 0.04, iy + fh2 / 2 + 0.25, color=NAVY, w=2.5)
ty = iy + fh2 + 0.22
exs = [("4-bit counter", "11 cells, 150.1 µm²; min period 0.727 ns; meets 100 MHz, +9.27 ns"),
       ("8-bit ALU (no clock)", "109 cells, 636.9 µm²; longest path 2.69 ns"),
       ("FIFO 8 × 4", "120 cells, 1830.5 µm²; min period 1.845 ns")]
ew = (iw - 0.4) / 3
for k, (a, b) in enumerate(exs):
    box(ix + k * (ew + 0.2), ty, ew, 1.3, fill=WHITE, line=BORDER, paras=[{"runs": parse(f"**{a}**"), "color": NAVY}, b],
        size=16, label="tex " + a, inset=0.08)
text(ix, ty + 1.42, iw, h - (ty - y) - 1.5, [
    "**Proven:** Yosys' SAT solver proves the netlist equals the RTL on **16 of 18** designs (the 2 FSMs: not proven, "
    "state re-encoded; 0 different). Gate-level simulation matches on 19 of 19.",
    {"runs": parse("Estimate only: one typical corner, no wire delay, ideal clock, setup only, no power. Not sign-off."),
     "color": AMBER, "italic": True},
], size=17, space_after=3, label="timing checked")

# ---- Test Results: Live Evaluation
y = y + h + GAP; h = BOTTOM - y
ix, iy, iw = panel(x0, y, CW, h, "Test Results: Live Evaluation")
text(ix, iy - 0.1, iw, 0.45, ["15 prompts (7 combinational, 6 sequential, 2 FSM) · DeepSeek V4.1 Flash (free) · one run each"],
     size=15.5, color=SLATE, label="eval sub")
# outcome bar
oy = iy + 0.45; oh = 0.66
segs = [(8, GREEN, "8 PASS first attempt"), (6, BLUE, "6 PASS after repair"), (1, GREY, "1 no result")]
cx = ix
for n, col, lab in segs:
    sw = iw * n / 15
    box(cx, oy, sw, oh, fill=col, line=WHITE, lw=1.5, paras=[lab if n > 1 else "1"], size=15, color=WHITE, bold=True,
        label="seg " + lab, inset=0.03)
    cx += sw
text(ix, oy + oh + 0.02, iw, 0.36, ["the 15th (4-bit counter) timed out three times: reported as no result, not as a pass"],
     size=13, color=SLATE, label="seg note", align=PP_ALIGN.RIGHT)
# strength chart
chy = oy + oh + 0.45
text(ix, chy, iw, 0.42, ["Testbench strength per design (injected bugs caught of those run)"], size=15.5, bold=True,
     color=NAVY, label="strength title")
data = [("c1 priority encoder", 10, 12), ("c2 binary to Gray", 1, 1), ("c3 ripple adder", 12, 12), ("c4 4:1 mux", 6, 6),
        ("c5 3:8 decoder", 12, 12), ("c6 comparator", 3, 3), ("c7 4-bit ALU", 9, 12), ("s2 up/down counter", 9, 9),
        ("s3 universal shift reg.", 5, 5), ("s4 SIPO shift reg.", 3, 3), ("s5 clock divide-by-4", 7, 7),
        ("s6 FIFO 8 × 4", 12, 12), ("f1 1011 detector", 6, 6), ("f2 traffic light", 7, 11)]
lab_w = 3.05; val_w = 0.85; plot_w = iw - lab_w - val_w
row_h = (BOTTOM - 1.15 - (chy + 0.45)) / len(data)
gy0 = chy + 0.47
for g in range(0, 13, 3):    # grid lines at 0, 3, 6, 9, 12
    gx = ix + lab_w + plot_w * g / 12
    arrow(gx, gy0 - 0.05, gx, gy0 + row_h * len(data), color=GRID, w=1, head=False)
    text(gx - 0.3, gy0 + row_h * len(data) - 0.02, 0.6, 0.3, [str(g)], size=11, color=SLATE, align=PP_ALIGN.CENTER,
         label="gx" + str(g), inset=0)
for k, (name, c, t) in enumerate(data):
    ry = gy0 + k * row_h
    text(ix, ry, lab_w - 0.08, row_h, [name], size=14, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE,
         label="lab " + name, inset=0.02)
    bh2 = row_h * 0.68; byy = ry + (row_h - bh2) / 2
    box(ix + lab_w, byy, plot_w * c / 12, bh2, fill=GREEN, line=None)
    if t > c:
        box(ix + lab_w + plot_w * c / 12, byy, plot_w * (t - c) / 12, bh2, fill=RED, line=None)
    text(ix + lab_w + plot_w * t / 12 + 0.06, ry, val_w + 1.0, row_h, [f"{c}/{t}"], size=14, bold=True,
         color=GREEN if c == t else RED, anchor=MSO_ANCHOR.MIDDLE, label="val " + name, inset=0.0)
# legend + totals
ly = BOTTOM - 0.85
box(ix, ly + 0.12, 0.3, 0.24, fill=GREEN, line=None); text(ix + 0.36, ly + 0.02, 1.4, 0.4, ["caught"], size=13, label="lg1")
box(ix + 1.5, ly + 0.12, 0.3, 0.24, fill=RED, line=None); text(ix + 1.86, ly + 0.02, 1.4, 0.4, ["not caught"], size=13, label="lg2")
text(ix + 3.4, ly - 0.04, iw - 3.4, 0.55, ["**102 / 111 caught (92%)** · 14/14 confirmed by references · median 360 s"],
     size=14.5, color=NAVY, align=PP_ALIGN.RIGHT, label="totals")

# ================================================================ COLUMN 4
x0 = COLX[3]
# ---- Test Results: Timing, Repair & Tool Checks
y = TOP; h = 12.85
ix, iy, iw = panel(x0, y, CW, h, "Test Results: Timing, Repair & Tool Checks")
names = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "s2", "s3", "s4", "s5", "s6", "f1", "f2"]
tvals = [0.36, 0.12, 1.48, 0.63, 0.18, 0.44, 1.22, 2.00, 0.75, 0.49, 0.64, 1.84, 0.74, 1.25]
avals = [58.806, 26.275, 110.106, 205.197, 77.574, 95.091, 336.573, 490.47, 212.704, 210.202, 62.56, 1830.51, 163.907, 466.698]


def vbars(top, height, title, vals, vmax, ticks, fmt, colors, unit, note=None):
    text(ix, top, iw, 0.42, [title], size=15.5, bold=True, color=NAVY, label="chart " + title[:20])
    py0 = top + 0.5; ph = height - 0.5 - 0.42
    ax_w = 0.62; pw = iw - ax_w
    for tv in ticks:
        gy = py0 + ph * (1 - tv / vmax)
        arrow(ix + ax_w, gy, ix + iw, gy, color=GRID, w=1, head=False)
        text(ix, gy - 0.16, ax_w - 0.06, 0.32, [fmt(tv)], size=11, color=SLATE, align=PP_ALIGN.RIGHT, label="tick", inset=0)
    n = len(vals); slot = pw / n; bw3 = slot * 0.64
    for k, v in enumerate(vals):
        bx3 = ix + ax_w + k * slot + (slot - bw3) / 2
        bh3 = ph * min(v, vmax) / vmax
        box(bx3, py0 + ph - bh3, bw3, bh3, fill=colors[k], line=None)
        text(bx3 - 0.25, py0 + ph - bh3 - 0.3, bw3 + 0.5, 0.3, [fmt(v, True)], size=12, color=TXT,
             align=PP_ALIGN.CENTER, label="bv", inset=0)
        text(bx3 - 0.2, py0 + ph + 0.03, bw3 + 0.4, 0.32, [names[k]], size=13.5, bold=True, color=SLATE,
             align=PP_ALIGN.CENTER, label="bn", inset=0)
    arrow(ix + ax_w, py0 + ph, ix + iw, py0 + ph, color=SLATE, w=1.25, head=False)
    return py0 + ph + 0.4


cols_t = [BLUE] * 7 + [NAVY] * 7
e = vbars(iy - 0.05, 3.85, "Pre-layout timing per design (ns, sky130 typical corner)", tvals, 2.2, [0, 0.5, 1.0, 1.5, 2.0],
          lambda v, lab=False: (f"{v:.2f}" if lab else f"{v:.1f}"), cols_t, "ns")
box(ix + 0.7, e - 0.02, 0.3, 0.22, fill=BLUE, line=None)
text(ix + 1.06, e - 0.11, 4.2, 0.38, ["longest input-to-output path (no clock)"], size=12.5, label="tl1")
box(ix + 5.6, e - 0.02, 0.3, 0.22, fill=NAVY, line=None)
text(ix + 5.96, e - 0.11, 4.4, 0.38, ["minimum clock period (clocked)"], size=12.5, label="tl2")
e2 = vbars(e + 0.35, 3.55, "Mapped cell area per design (µm², sky130_fd_sc_hd)", avals, 2000,
           [0, 500, 1000, 1500, 2000], lambda v, lab=False: (f"{v:.0f}"), [GREEN] * 14, "um2")
# seeded repair
sy = e2 - 0.05
text(ix, sy, iw, 0.42, ["Live fault repair: seeded counter bug (count + 2′d2)"], size=15.5, bold=True, color=NAVY,
     label="seed title")
rows = [("Before fix", 1, 19), ("After LLM fix", 20, 0)]
for k, (lab, p_, f_) in enumerate(rows):
    ry = sy + 0.5 + k * 0.55
    text(ix, ry, 2.0, 0.46, [lab], size=14, bold=True, anchor=MSO_ANCHOR.MIDDLE, label="seed " + lab, inset=0.02)
    pw2 = iw - 2.1 - 1.9
    box(ix + 2.1, ry + 0.06, pw2 * p_ / 20, 0.36, fill=GREEN, line=None)
    if f_:
        box(ix + 2.1 + pw2 * p_ / 20, ry + 0.06, pw2 * f_ / 20, 0.36, fill=RED, line=None)
    text(ix + 2.1 + pw2 + 0.1, ry, 1.85, 0.46, [f"{p_} pass / {f_} fail"], size=13.5, bold=True,
         color=GREEN if not f_ else RED, anchor=MSO_ANCHOR.MIDDLE, label="seedv " + lab, inset=0.02)
text(ix, sy + 1.62, iw, 0.4, ["Diagnosis from the simulator log alone: root cause at counter.v line 10, patched to count + 1′b1."],
     size=13, color=SLATE, label="seed note")
# KPI tiles
ky = sy + 2.12
kpis = [("453 + 222", "automated tests pass"), ("27 / 27", "injected bugs caught (built-in designs)"),
        ("16 / 18", "netlists formally proven equal to RTL"), ("0", "accessibility violations (axe-core)")]
kw = (iw - 3 * 0.18) / 4
kh = (y + h - 0.25) - ky
for k, (big, small) in enumerate(kpis):
    box(ix + k * (kw + 0.18), ky, kw, kh, fill=T_NAVY, line=NAVY, lw=1.25,
        paras=[{"runs": parse(f"**{big}**"), "size": 28, "color": NAVY}, small], size=14.5, label="kpi " + big, inset=0.06)

# ---- Conclusion & Comparative Summary
y = y + h + GAP; h = 7.85
ix, iy, iw = panel(x0, y, CW, h, "Conclusion & Comparative Summary")
rows = [("Metric", "Target", "Measured result"),
        ("Live evaluation (15 prompts)", "PASS decided by simulator", "14/14 PASS (8 first, 6 repaired)"),
        ("Reference check", "No false PASS", "14/14 designs correct"),
        ("Testbench strength", "Catch injected bugs", "102/111 caught (92%)"),
        ("Live fault repair", "Correct root cause", "1/20 to 20/20 checks"),
        ("Mutation sweep (built-in)", "Testbench must fail bugs", "27/27 caught"),
        ("Netlist vs RTL", "Formal proof", "16/18 proven, 0 different"),
        ("Automated tests", "All passing", "453 backend + 222 frontend")]
cws = [3.55, 3.05, iw - 3.55 - 3.05]; trh = 0.6
for r, row in enumerate(rows):
    xx = ix
    for c, val in enumerate(row):
        hdr = r == 0
        box(xx, iy + r * trh, cws[c], trh, fill=NAVY if hdr else (T_GREY if r % 2 == 0 else WHITE), line=BORDER, lw=0.75,
            paras=[val], size=15.5, bold=hdr or c == 0, color=WHITE if hdr else (GREEN if c == 2 else TXT),
            align=PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER, label=f"tbl {r}{c}", inset=0.08)
        xx += cws[c]
ty2 = iy + len(rows) * trh + 0.15
text(ix, ty2, iw, (y + h - 0.2) - ty2, [
    "**Key takeaway:** a PASS is evidence, not proof, so SiliconScribe also shows how much each PASS is worth and lets "
    "a separate model write the testbench.",
    "**Limits:** small designs, one run each, mainly one model, toggle coverage only, timing before layout. "
    "**Next:** power from simulation activity, testbench hardening by mutation, OpenROAD layout, SVA, a Tiny Tapeout chip.",
], size=17.5, space_after=5, label="takeaway")

# ---- Prepared By / Guided By (wording kept from the earlier poster)
y = y + h + GAP; h = 2.55
ix, iy, iw = panel(x0, y, CW, h, "Prepared By:")
text(ix, iy - 0.1, iw, h - 0.95, ["Kushal Pitaliya (Roll No.: 23EC105) | B.Tech ECE, 7th Sem, CSPIT, CHARUSAT",
                                 "Course: EC486 Minor Project | Academic Year 2026-27"], size=19, space_after=2,
     label="prepared")
y = y + h + GAP; h = BOTTOM - y
ix, iy, iw = panel(x0, y, CW, h, "Guided By:")
text(ix, iy - 0.1, iw, h - 0.95, ["Internal Guide: ______________________________",
                                 "Dept. of EC Engineering, CSPIT, CHARUSAT",
                                 "Dr. Upesh Patel (Head of Department)",
                                 "Associate Professor & HOD, Dept. of EC Engineering, CSPIT, CHARUSAT"], size=17,
     space_after=1, label="guided")

# ---------------------------------------------------------------- drop image parts the deleted pictures used
used = set(slide._element.xpath(".//@r:embed"))
for rId, rel in list(slide.part.rels.items()):
    if rel.reltype.endswith("/image") and rId not in used:
        slide.part.drop_rel(rId)

prs.save(OUT)

bad = [(l, n, a) for l, n, a in REPORT if n > a * 0.95 + 0.02]
print(f"saved {OUT}; text boxes checked: {len(REPORT)}; overflowing: {len(bad)}")
for l, n, a in bad:
    print(f"  OVERFLOW {l[:60]!r}: needs {n} in, has {a} in")
