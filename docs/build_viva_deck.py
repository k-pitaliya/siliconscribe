"""SiliconScribe viva deck (16:9, 20 slides) in the poster's design system.

Hand-built: real diagrams/charts cropped from the poster, real app screenshots, plain shapes for every
graphic element, speaker notes on every slide. Numbers come from the project's verified fact sheet.
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from PIL import ImageFont, Image

OUT, ASSETS, LOGO_L, LOGO_R = sys.argv[1:5]
NAVY = RGBColor(0x18, 0x2B, 0x49); BLUE = RGBColor(0x25, 0x63, 0xEB); GREEN = RGBColor(0x15, 0x80, 0x3D)
RED = RGBColor(0xB9, 0x1C, 0x1C); SLATE = RGBColor(0x47, 0x55, 0x69); AMBER = RGBColor(0xB4, 0x53, 0x09)
TXT = RGBColor(0x0F, 0x17, 0x2A); WHITE = RGBColor(0xFF, 0xFF, 0xFF); BORDER = RGBColor(0xCB, 0xD5, 0xE1)
T_BLUE = RGBColor(0xDB, 0xEA, 0xFE); T_GREEN = RGBColor(0xDC, 0xFC, 0xE7); T_RED = RGBColor(0xFE, 0xE2, 0xE2)
T_AMBER = RGBColor(0xFE, 0xF3, 0xC7); T_GREY = RGBColor(0xF1, 0xF5, 0xF9); T_NAVY = RGBColor(0xE0, 0xE7, 0xF1)
BG = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Times New Roman"
_F = {False: "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
      True: "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"}
I = Inches
W, H = 13.333, 7.5
REPORT = []

prs = Presentation()
prs.slide_width, prs.slide_height = I(W), I(H)
BLANK = prs.slide_layouts[6]


def lines_needed(text, size, bold, width_in):
    f = ImageFont.truetype(_F[bold], int(size * 10))
    maxw = width_in * 72 * 10 * 0.93
    n = 0
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


def fill(tf, paras, size, color, align, anchor, label, w, h, inset, space_after, bold=False):
    tf.word_wrap = True; tf.auto_size = None
    tf.margin_left = tf.margin_right = I(inset); tf.margin_top = tf.margin_bottom = I(inset * 0.6)
    tf.vertical_anchor = anchor
    need, first = 0.0, True
    for spec in paras:
        if isinstance(spec, str):
            spec = {"runs": parse(spec, bold=bold)}
        p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
        p.alignment = spec.get("align", align)
        ps = spec.get("size", size); sa = spec.get("space_after", space_after)
        p.space_after = Pt(sa)
        for t, st in spec["runs"]:
            r = p.add_run(); r.text = t; f = r.font
            f.name = FONT; f.size = Pt(st.get("size", ps)); f.bold = st.get("bold", False)
            f.italic = spec.get("italic", False); f.color.rgb = st.get("color", spec.get("color", color))
        plain = "".join(t for t, _ in spec["runs"])
        b = sum(len(t) for t, st in spec["runs"] if st.get("bold")) > len(plain) / 2
        need += lines_needed(plain, ps, b, w - 2 * inset - 0.02) * ps * 1.17 / 72 + sa / 72
    need += inset * 1.2
    REPORT.append((label, round(need, 2), round(h, 2)))


def text(s, x, y, w, h, paras, size=18, color=TXT, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, label="", inset=0.04,
         space_after=6, bold=False):
    b = s.shapes.add_textbox(I(x), I(y), I(w), I(h))
    fill(b.text_frame, paras, size, color, align, anchor, label or str(paras)[:40], w, h, inset, space_after, bold)
    return b


def box(s, x, y, w, h, fillc=WHITE, line=BORDER, lw=1.0, shape=MSO_SHAPE.RECTANGLE, paras=None, size=16, color=TXT,
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, label="", inset=0.1, bold=False, space_after=0):
    b = s.shapes.add_shape(shape, I(x), I(y), I(w), I(h))
    if fillc is None: b.fill.background()
    else: b.fill.solid(); b.fill.fore_color.rgb = fillc
    if line is None: b.line.fill.background()
    else: b.line.color.rgb = line; b.line.width = Pt(lw)
    b.shadow.inherit = False
    if paras:
        fill(b.text_frame, paras, size, color, align, anchor, label or str(paras)[:40], w, h, inset, space_after, bold)
    return b


def picture(s, path, x, y, w=None, h=None, border=True):
    iw, ih = Image.open(path).size
    if w and not h: h = w * ih / iw
    if h and not w: w = h * iw / ih
    p = s.shapes.add_picture(path, I(x), I(y), I(w), I(h))
    if border:
        p.line.color.rgb = BORDER; p.line.width = Pt(1)
    return w, h


def fit_picture(s, path, x, y, maxw, maxh, border=True, center=True):
    iw, ih = Image.open(path).size
    sc = min(maxw / iw, maxh / ih); w, h = iw * sc, ih * sc
    if center:
        x += (maxw - w) / 2; y += (maxh - h) / 2
    picture(s, path, x, y, w, h, border)
    return x, y, w, h


N = {"n": 0}


def slide(title, notes, kicker=None):
    s = prs.slides.add_slide(BLANK)
    N["n"] += 1
    s.background.fill.solid(); s.background.fill.fore_color.rgb = BG
    if title:
        if kicker:
            text(s, 0.6, 0.32, 9, 0.35, [kicker.upper()], size=12.5, color=BLUE, bold=True, label="kicker")
        text(s, 0.6, 0.55 if kicker else 0.42, 11.6, 0.75, [title], size=30, color=NAVY, bold=True, label="title " + title)
        box(s, 0.6, 1.3, 1.6, 0.06, fillc=NAVY, line=None)                 # short navy rule under the title
    # footer
    box(s, 0.6, 7.02, W - 1.2, 0.012, fillc=BORDER, line=None)
    text(s, 0.6, 7.05, 9, 0.32, ["SiliconScribe  ·  EC486 Minor Project  ·  Kushal Pitaliya (23EC105)  ·  CSPIT, CHARUSAT"],
         size=10.5, color=SLATE, label="footer")
    text(s, W - 1.6, 7.05, 1.0, 0.32, [str(N["n"])], size=10.5, color=SLATE, align=PP_ALIGN.RIGHT, label="page")
    s.notes_slide.notes_text_frame.text = notes
    return s


def bullets(s, x, y, w, h, items, size=19, label="bullets", space_after=10):
    paras = [{"runs": [("▪  ", {"color": BLUE, "bold": True})] + parse(t)} for t in items]
    return text(s, x, y, w, h, paras, size=size, label=label, space_after=space_after)


A = lambda n: f"{ASSETS}/{n}.png"

# 1 ---------------------------------------------------------------- title
s = prs.slides.add_slide(BLANK); N["n"] += 1
s.background.fill.solid(); s.background.fill.fore_color.rgb = BG
box(s, 0, 0, W, 0.18, fillc=NAVY, line=None)
picture(s, LOGO_L, 0.6, 0.55, h=1.35, border=False)
picture(s, LOGO_R, W - 0.6 - 1.35, 0.55, h=1.35, border=False)
text(s, 2.3, 0.62, W - 4.6, 0.4, ["V. T. Patel Department of Electronics & Communication Engineering"], size=15, color=SLATE,
     align=PP_ALIGN.CENTER, label="dept")
text(s, 2.3, 1.0, W - 4.6, 0.4, ["Chandubhai S. Patel Institute of Technology, CHARUSAT"], size=15, color=SLATE,
     align=PP_ALIGN.CENTER, label="inst")
text(s, 1.2, 2.2, W - 2.4, 1.1, ["SiliconScribe"], size=54, color=NAVY, bold=True, align=PP_ALIGN.CENTER, label="t1")
text(s, 1.4, 3.3, W - 2.8, 1.0, ["Execution-grounded RTL generation and autonomous diagnosis using large language models, "
                                  "with a real Verilog simulator in the loop"], size=21, color=TXT, align=PP_ALIGN.CENTER,
     label="t2")
box(s, W / 2 - 0.9, 4.42, 1.8, 0.05, fillc=RED, line=None)
text(s, 1.2, 4.7, W - 2.4, 0.45, ["**Kushal Pitaliya**  (Roll No. 23EC105)  ·  B.Tech ECE, 7th Semester"], size=19,
     align=PP_ALIGN.CENTER, label="name")
text(s, 1.2, 5.15, W - 2.4, 0.45, ["EC486 Minor Project  ·  Academic Year 2026-27"], size=17, color=SLATE,
     align=PP_ALIGN.CENTER, label="course")
text(s, 1.2, 5.75, W - 2.4, 0.8, ["Internal Guide: ______________________     Head of Department: Dr. Upesh Patel",
                                  "Viva: 25 November 2026"], size=15, color=SLATE, align=PP_ALIGN.CENTER, label="guide",
     space_after=4)
s.notes_slide.notes_text_frame.text = ("Good morning. My project is SiliconScribe: a tool that turns a plain-English description "
                                       "of a hardware block into Verilog and a testbench, runs them in a real simulator, and "
                                       "repairs failures until the design passes. The key idea: the simulator decides, not the AI.")

# 2 ---------------------------------------------------------------- problem
s = slide("LLMs write Verilog, but they never run it",
          "A language model produces text that looks like Verilog. It never compiles or simulates it, so it cannot know whether "
          "the design works. Worse, if you ask it to make a failing test pass, it may weaken the test instead of fixing the "
          "design. SiliconScribe closes this loop with a real simulator.", kicker="Problem")
fit_picture(s, A("diagram_open_vs_closed_loop"), 0.6, 1.75, 7.6, 2.75)
bullets(s, 8.55, 1.75, 4.2, 4.9, [
    "Generated code is **plausible text**, not verified hardware",
    "A model cannot observe a clock edge or a race condition",
    "Told to “make it pass”, a model may **weaken the testbench** instead of fixing the design",
    "Goal: a trustworthy loop where **only the simulator decides**"], size=18.5, label="problem bullets")
box(s, 0.6, 4.85, 7.6, 1.45, fillc=T_GREY, line=BORDER, paras=[
    {"runs": parse("**Verification gap:** someone must write the design and the testbench that proves it; "
                   "code generation alone solves neither."), "align": PP_ALIGN.LEFT}], size=15.5, anchor=MSO_ANCHOR.MIDDLE,
    label="gap box", inset=0.2)

# 3 ---------------------------------------------------------------- objectives
s = slide("Objectives", "Five objectives. One: only the simulator decides. Two: the testbench comes from the specification, never "
          "from the RTL, so the two cannot share the same mistake by copying. Three: failures are repaired with a structured "
          "diagnosis and guards against cheating. Four: every PASS reports how much it is worth. Five: an early timing and area "
          "estimate on a real cell library.", kicker="Aims")
objs = [("1", "Simulator as judge", "Only Icarus Verilog decides PASS or FAIL, never the model's own claim."),
        ("2", "Independent testbench", "Written from the specification only; the RTL is withheld."),
        ("3", "Guarded repair loop", "Compiler fix first, then an LLM diagnosis; patches that delete checks are rejected."),
        ("4", "Measured evidence", "Testbench strength, toggle coverage and a second opinion for every PASS."),
        ("5", "Early physical view", "Pre-layout timing and area on SkyWater 130 nm with Yosys and OpenSTA.")]
cw = (W - 1.2 - 4 * 0.25) / 5
for k, (n, t, d) in enumerate(objs):
    x = 0.6 + k * (cw + 0.25)
    box(s, x, 1.75, cw, 4.15, fillc=T_NAVY if k % 2 == 0 else T_GREY, line=BORDER)
    text(s, x + 0.2, 1.95, cw - 0.4, 0.9, [n], size=40, color=BLUE, bold=True, label="obj n")
    text(s, x + 0.2, 2.95, cw - 0.4, 0.9, [t], size=19, color=NAVY, bold=True, label="obj t " + t)
    text(s, x + 0.2, 3.88, cw - 0.4, 1.98, [d], size=16.5, label="obj d " + t)
if True:
    box(s, 0.6, 6.05, W - 1.2, 0.72, fillc=WHITE, line=BLUE, lw=1.25, paras=[{"runs": parse("**Scope:** small RTL blocks (under about 100 lines), free language models, a local single-user tool in the browser."), "align": PP_ALIGN.LEFT}], size=16.5, label="scope", inset=0.2)

# 4 ---------------------------------------------------------------- architecture
s = slide("System architecture", "Three tiers. The browser front end in React talks to a FastAPI backend over HTTP and Server-Sent "
          "Events, so each stage appears live. The backend routes model calls to OpenCode, Cloudflare Workers AI or NVIDIA NIM; "
          "API keys stay on the server. The EDA tools run as separate processes with time and resource limits.",
          kicker="Design")
fit_picture(s, A("diagram_architecture"), 6.45, 1.55, 6.3, 5.3)
bullets(s, 0.6, 1.75, 5.6, 5.0, [
    "**Frontend:** React 18 + TypeScript; prompt, model menu, spec review, live run timeline, results, waveform",
    "**Backend:** FastAPI; orchestrator with the repair loop and guards, sandbox policy, debugging agent, SQLite projects",
    "**Model router:** OpenCode (about 460 models), Cloudflare Workers AI, NVIDIA NIM; keys only in backend/.env",
    "**EDA tools:** Icarus Verilog 12.0, Yosys 0.71, OpenSTA 3.2.0 with the sky130 library"], size=17.5,
        label="arch bullets", space_after=12)

# 5 ---------------------------------------------------------------- pipeline
s = slide("Closed-loop pipeline", "The prompt becomes a typed specification. From it, one generator writes the RTL and another writes "
          "the testbench without seeing the RTL. After a sandbox check and lint, Icarus simulates. A FAIL goes to the repair loop: "
          "a deterministic compiler fix first, then an LLM diagnosis with root cause and fix location, then a minimal patch. A PASS "
          "goes to the evidence stage.", kicker="Method")
fit_picture(s, A("diagram_pipeline"), 0.6, 1.5, 5.0, 5.4)
bullets(s, 5.95, 1.75, 6.8, 2.9, [
    "Spec → RTL + **independent testbench** → sandbox + lint → **Icarus simulation**",
    "**FAIL:** compiler repair, then LLM diagnosis (symptom, root cause, fix location), minimal patch, up to 5 rounds",
    "**PASS:** evidence stage: original testbench re-run, second opinion, strength, toggle coverage, timing and area"],
        size=17.5, label="pipe bullets")
box(s, 5.95, 4.85, 6.8, 1.85, fillc=T_GREY, line=SLATE, paras=[
    {"runs": parse("**Verdict rules**"), "color": NAVY, "size": 17, "align": PP_ALIGN.LEFT},
    {"runs": parse("PASS needs a whole-line Passed: N with N > 0 and Failed: 0, no FAIL line and a clean exit. "
                   "Zero checks is never PASS; a watchdog that fires first gives ERROR."), "align": PP_ALIGN.LEFT}],
    size=15.5, anchor=MSO_ANCHOR.TOP, label="verdict box", inset=0.18, space_after=4)

# 6 ---------------------------------------------------------------- the app
s = slide("The application", "This is the real start screen. On the left: the prompt, the model menu with three sources, the option "
          "to let a different model write the testbench, and the option to review the specification first. The tabs show the "
          "design, results, every test case, the waveform and a schematic.", kicker="Demo")
x, y, w, h = fit_picture(s, A("screenshot_s01_welcome"), 0.6, 1.55, 8.4, 5.3, center=False)
bullets(s, 9.35, 1.75, 3.4, 5.0, [
    "Per-run **model choice** from three sources",
    "Optional **separate testbench model**",
    "Optional **specification review**",
    "**Ask about this run:** a chat that reads the waveform (new)",
    "Tabs: Design, Results, Test cases, Waveform, Schematic"], size=17, label="app bullets", space_after=12)

# 7 ---------------------------------------------------------------- verdict integrity and safety
s = slide("Verdict integrity and safety", "Four rules keep a PASS honest. The verdict comes from anchored summary lines, never from "
          "the model. Repairs cannot delete checks, and a loop that is going nowhere stops. Generated code runs in a sandbox: only "
          "allow-listed system tasks, no file or process access. A model that fails is reported, never silently replaced.",
          kicker="Integrity")
cards = [("PASS is earned", NAVY, T_NAVY, "Passed: N with N > 0 and Failed: 0, no FAIL line, clean exit. Zero checks is never "
          "PASS; an early watchdog gives ERROR."),
         ("No cheating repairs", RED, T_RED, "A patch that deletes checks is rejected. No-op and oscillating repairs stop the loop. "
          "A changed testbench is flagged and the original is re-run."),
         ("Sandboxed code", GREEN, T_GREEN, "Allow-listed system tasks only: no $system, file I/O or include. Scrubbed environment, "
          "CPU and file limits, at most 2 runs at once."),
         ("Honest failures", AMBER, T_AMBER, "A model the user chose that fails is reported in plain words, never swapped for the "
          "demo. Every result records which model wrote it.")]
cw2 = (W - 1.2 - 0.3) / 2; ch = 2.45
for k, (t, hc, bc, d) in enumerate(cards):
    x = 0.6 + (k % 2) * (cw2 + 0.3); y = 1.7 + (k // 2) * (ch + 0.25)
    box(s, x, y, cw2, ch, fillc=bc, line=hc, lw=1.5)
    box(s, x, y, 0.12, ch, fillc=hc, line=None)
    text(s, x + 0.35, y + 0.18, cw2 - 0.55, 0.5, [t], size=20, color=hc, bold=True, label="vi t " + t)
    text(s, x + 0.35, y + 0.75, cw2 - 0.55, ch - 0.85, [d], size=17, label="vi d " + t)

# 8 ---------------------------------------------------------------- trust features
s = slide("Four ways the tool checks the checker", "A PASS is only as strong as its testbench, so the tool checks the testbench in "
          "four ways, and each card shows a real live run. The strongest example is top-left: a separate model wrote a wrong "
          "testbench, and the app reported FAIL instead of rewriting the checks.", kicker="Trust")
fit_picture(s, A("diagram_trust_features"), 0.6, 1.55, 8.1, 5.35)
bullets(s, 9.0, 1.8, 3.75, 5.0, [
    "A PASS is **evidence, not proof**",
    "Separate testbench model: a failing check is reported, never rewritten away",
    "Second opinion after a repair rewrote the testbench",
    "Specification review before generation"], size=16.5, label="trust bullets", space_after=12)

# 9 ---------------------------------------------------------------- live: disagreement
s = slide("Live run: a separate testbench model disagrees", "Here a free OpenCode model wrote the design and an NVIDIA model wrote "
          "the testbench. The run failed, 61 of 108. The app named both models, said they disagree, and refused to apply the design "
          "model's rewrite of the testbench. I checked by hand: the testbench had two reset mistakes. Fixing only those two lines, "
          "the unchanged RTL passes 108 of 108.", kicker="Evidence")
fit_picture(s, A("screenshot_s17_independent_testbench_fail"), 0.6, 1.55, 8.4, 5.3, center=False)
box(s, 9.35, 1.7, 3.4, 1.25, fillc=T_RED, line=RED, paras=[{"runs": parse("**FAIL 61 / 108**"), "size": 26, "color": RED},
                                                          "models disagree"], size=15, label="kpi fail")
bullets(s, 9.35, 3.15, 3.4, 3.7, [
    "The app **refused to rewrite** the failing checks",
    "By hand: the testbench had **two reset bugs**",
    "RTL unchanged: **108 / 108** once they are fixed"], size=16.5, label="dis bullets", space_after=10)

# 10 --------------------------------------------------------------- live: second opinion
s = slide("Live run: second opinion after a repair", "A FIFO run passed after one repair, but that repair changed the testbench, which "
          "is suspicious. So the tool generated a fresh testbench from the same specification: it agrees, 3798 of 3798. But the "
          "original testbench still fails 482 checks, so the result is shown as PASS, disputed, until a person reviews the change.", kicker="Evidence")
fit_picture(s, A("screenshot_s06_results_pass"), 0.6, 1.55, 8.4, 5.3, center=False)
box(s, 9.35, 1.7, 3.4, 1.25, fillc=RGBColor(0xFD, 0xF1, 0xE6), line=AMBER, paras=[{"runs": parse("**PASS, disputed**"), "size": 24,
                                                               "color": AMBER}, "4134 / 4134 after one repair"], size=15, label="kpi pass")
bullets(s, 9.35, 3.15, 3.4, 3.7, [
    "The repair **changed the testbench**",
    "Fresh testbench agrees: **3798 / 3798**",
    "Original still fails **482** checks: shown as a warning"], size=16.5, label="so bullets", space_after=10)

# 11 --------------------------------------------------------------- timing stage
s = slide("Pre-layout timing and area", "After a PASS, Yosys maps the design to SkyWater 130 nanometre standard cells and OpenSTA times "
          "it. Where an honest number is impossible, for tri-states, latches, loops or derived clocks, it refuses with a reason. The "
          "mapped netlist was checked by simulation against the RTL on 19 designs. It is an estimate: one corner, no wires, not "
          "sign-off.", kicker="Physical view")
fit_picture(s, A("diagram_timing_flow"), 0.6, 1.6, 7.9, 5.25)
bullets(s, 8.85, 1.75, 3.9, 5.0, [
    "**Yosys 0.71** maps to sky130 cells; **OpenSTA 3.2.0** times the netlist",
    "Refuses tri-states, latches, loops and derived clocks",
    "Netlist **formally proven** equal to the RTL on **16 / 18** designs"], size=17, label="tim bullets", space_after=12)

# 11a -------------------------------------------------------------- schematic views
SHOTS = "/Users/kushalpitaliya/Kushal_Master/Projects/VLSI/ai-eda-playground/docs/screenshots/v2"
s = slide("See the gates: the Schematic tab", "New in the tool: every run can be drawn as RTL cells, adders, multiplexers and "
          "flip-flops, or as individual gates, straight from the Yosys netlist of that run. This is the built-in counter at "
          "gate level: four flip-flops with asynchronous reset and the gates that compute the next count.", kicker="New")
fit_picture(s, f"{SHOTS}/schematic_counter_gate_full.png", 0.6, 1.55, 7.2, 5.35)
bullets(s, 8.15, 1.75, 4.6, 5.0, [
    "Three views: **Block diagram**, **RTL cells**, **Gate level**",
    "Drawn from the **Yosys netlist of each run** with the open-source netlistsvg",
    "Gate level uses generic gates; designs over 400 cells are not drawn",
    "Shown: the built-in 4-bit counter (offline demo design)"], size=17.5, label="sch bullets", space_after=12)

# 11b -------------------------------------------------------------- formal proof and critical path
s = slide("A proven netlist and its critical path", "The timing numbers describe the sky130 netlist, so I prove that netlist is the "
          "design that was simulated. Yosys' SAT solver checks every input value for combinational designs; induction handles "
          "registers. Sixteen of eighteen designs are proven. The two state machines are honestly not proven, because synthesis "
          "re-encoded their states. A netlist I broke on purpose is caught. The table shows the ALU's slowest path: six majority "
          "cells, the ripple-carry chain.", kicker="New")
fit_picture(s, f"{SHOTS}/s20_timing_proof_critical_path.png", 0.6, 1.5, 5.6, 5.4)
box(s, 6.6, 1.65, 6.15, 1.3, fillc=T_GREEN, line=GREEN, lw=1.25,
    paras=[{"runs": parse("**16 / 18 proven**"), "size": 28, "color": GREEN}, "netlist = RTL (Yosys SAT / induction), 0 different"],
    size=15.5, label="proof kpi")
bullets(s, 6.6, 3.15, 6.15, 3.7, [
    "Combinational: **SAT over every input value**; sequential: **induction**",
    "2 FSMs **not proven** (state re-encoded), never shown as a pass; a sabotaged netlist is caught",
    "ALU critical path: **six maj3 cells** = the ripple-carry chain, 2.69 ns",
    "Proves netlist = RTL, not that the RTL is correct"], size=16.5, label="proof bullets", space_after=10)

# 11c -------------------------------------------------------------- debugging agent
s = slide("Ask about this run: an AI that reads the waveform", "New since the report was submitted: a chat panel. You ask a question "
          "about the code in the editor. The server simulates that code again, and the AI then uses eight tools on the real "
          "simulation: values at a time, a cycle-by-cycle table, what drives a signal, and testing a fix. It must query the "
          "waveform before it may answer. Here I hid a bug in the counter: it also counts when the low bit is one. The AI blamed "
          "line 13 and proposed a fix; the server re-simulated that fix: 57 of 57. Every time in the answer is a link: clicking "
          "30 nanoseconds opens the waveform at the failing hold check, where enable is 0 but count is already 2.",
          kicker="New · added 24 Nov, after submission")
fit_picture(s, A("screenshot_s23_ask_waveform_jump"), 0.6, 1.55, 8.4, 5.3, center=False)
bullets(s, 9.35, 1.7, 3.4, 5.2, [
    "Re-simulates the **code in the editor**",
    "**8 tools:** values at a time, cycle table, drivers, test a fix",
    "Must **query the waveform** before it answers",
    "Every fix is **re-simulated by the server**",
    "Times are links: **@30ns** moves the cursor"], size=16.5, label="agent bullets", space_after=10)

# 11d -------------------------------------------------------------- debugging agent: live results
s = slide("Debugging agent: live results", "Four real runs from today, one each, on small designs. First, the hidden enable bug: found "
          "from a cycle table, fix verified 57 of 57. Second, the most important: the counter was correct and the testbench was "
          "wrong, and the AI said so, because the check runs at the negedge before the third clock edge. Third, the honest one: "
          "for the SR latch that timed out, the fix passed 558 of 558, but the explanation blamed the wrong moment. So the fix is "
          "verified and the explanation is not. Fourth, DeepSeek answered correctly without looking at any evidence, which is why "
          "the agent now must query the waveform first.", kicker="Evidence")
rows = [("Case", "The AI's verdict", "Server check of its fix", "Time"),
        ("Hidden bug: enable || count[0]", "Design, line 13 (from a cycle table)", "PASS 57 / 57", "34–107 s"),
        ("Correct counter, wrong testbench", "Testbench: checks at the negedge, 560 ns", "PASS 57 / 57 (testbench fix)", "219 s"),
        ("SR latch that timed out", "Design: zero-delay loop (only partly right)", "PASS 558 / 558", "316 s"),
        ("Hidden bug, DeepSeek model", "Correct, but used no tools (now required)", "PASS 57 / 57", "49 s")]
cws = [3.55, 4.0, 3.05, W - 1.2 - 3.55 - 4.0 - 3.05]
for r, row in enumerate(rows):
    x = 0.6
    for c, v in enumerate(row):
        hdr = r == 0
        box(s, x, 1.6 + r * 0.74, cws[c], 0.74, fillc=NAVY if hdr else (T_GREY if r % 2 else WHITE), line=BORDER, lw=0.75,
            paras=[v], size=15.5, bold=hdr or c == 0, color=WHITE if hdr else (GREEN if c == 2 else TXT),
            align=PP_ALIGN.LEFT, label=f"ag {r}{c}", inset=0.12)
        x += cws[c]
box(s, 0.6, 5.5, 7.5, 1.3, fillc=T_AMBER, line=AMBER, lw=1.25, paras=[
    {"runs": parse("**The fix is verified; the explanation is not.** The SR-latch fix passed, but its explanation blamed the "
                   "wrong moment."), "align": PP_ALIGN.LEFT, "space_after": 4},
    {"runs": parse("One run each, small designs; NVIDIA NIM Nemotron Ultra unless stated."), "align": PP_ALIGN.LEFT,
     "size": 13, "color": SLATE}], size=15.5, label="agent takeaway", inset=0.18)
box(s, 8.4, 5.5, 4.35, 1.3, fillc=T_GREEN, line=GREEN, lw=1.25,
    paras=[{"runs": parse("**632 + 277**"), "size": 26, "color": GREEN}, "automated tests (41 + 10 new)"],
    size=15.5, label="agent kpi")

# 12 --------------------------------------------------------------- live evaluation
s = slide("Live evaluation: 15 prompts", "Fifteen prompts: seven combinational, six sequential and two state machines, with a free "
          "model, one run each. Fourteen completed and all fourteen passed: eight first time, six after repair. The fifteenth timed "
          "out three times and is reported as no result. The testbenches caught 102 of 111 injected bugs, and my own hand-written "
          "reference testbenches confirmed all fourteen designs correct.", kicker="Results")
fit_picture(s, A("chart_live_evaluation"), 0.6, 1.5, 7.4, 5.4)
kp = [("14 / 14", "completed runs PASS (8 first, 6 repaired)", GREEN, T_GREEN),
      ("102 / 111", "injected bugs caught (92%)", NAVY, T_NAVY),
      ("14 / 14", "confirmed by hand-written references", BLUE, T_BLUE)]
for k, (big, small, c, bc) in enumerate(kp):
    box(s, 8.4, 1.6 + k * 1.75, 4.35, 1.55, fillc=bc, line=c, lw=1.25,
        paras=[{"runs": parse(f"**{big}**"), "size": 30, "color": c}, small], size=15.5, label="ev kpi " + small)

# 13 --------------------------------------------------------------- timing, area, tools
s = slide("Timing, area, repair and tool checks", "Left: timing per design. Combinational designs get a longest path, never a clock "
          "rate. Area grows with flip-flops, the FIFO is largest. A seeded counter bug was found from the log alone and repaired "
          "from 1 of 20 to 20 of 20 checks. The tool itself has 632 backend and 277 frontend tests.", kicker="Results")
fit_picture(s, A("chart_timing_area_repair"), 0.6, 1.5, 6.6, 5.4)
bullets(s, 7.55, 1.75, 5.2, 5.0, [
    "Combinational designs report a **longest path**, never a clock rate",
    "Seeded counter bug: **1 / 20 → 20 / 20** checks after the live repair",
    "**632** backend + **277** frontend automated tests pass",
    "**27 / 27** injected bugs caught in the built-in designs",
    "**16 / 18** netlists formally proven equal to the RTL"], size=17.5, label="t13 bullets", space_after=11)

# 14 --------------------------------------------------------------- related work
s = slide("Comparison with related work", "Earlier work mostly builds better generators or benchmarks. AutoChip feeds compiler errors "
          "back. SiliconScribe's contribution is the loop around any generator: the simulator is the only judge, and each PASS comes "
          "with measured evidence.", kicker="Context")
rows = [("Work", "Focus", "What SiliconScribe adds"),
        ("VeriGen, ChipNeMo", "Better models for Verilog", "Any model plugs into the same verified loop"),
        ("VerilogEval", "Benchmark against golden answers", "Works without a golden answer: spec-derived testbench"),
        ("AutoChip", "Compiler and simulator feedback", "Structured diagnosis, anti-cheat guards, honest fallback"),
        ("Chip-Chat", "Human-led conversational design", "Automated loop; its chat answers from simulation evidence"),
        ("SiliconScribe", "Trustworthy loop + evidence", "Strength, coverage, second opinion, timing and area")]
cws = [2.6, 4.2, W - 1.2 - 2.6 - 4.2]
for r, row in enumerate(rows):
    x = 0.6
    for c, v in enumerate(row):
        hdr = r == 0; last = r == len(rows) - 1
        box(s, x, 1.7 + r * 0.78, cws[c], 0.78, fillc=NAVY if hdr else (T_BLUE if last else (T_GREY if r % 2 else WHITE)),
            line=BORDER, lw=0.75, paras=[v], size=16.5, bold=hdr or c == 0 or last, color=WHITE if hdr else TXT,
            align=PP_ALIGN.LEFT, label=f"rw {r}{c}", inset=0.14)
        x += cws[c]
text(s, 0.6, 6.5, W - 1.2, 0.45, ["The gap is not a better generator but a **trustworthy loop around any generator**."], size=17,
     color=NAVY, label="rw takeaway")

# 15 --------------------------------------------------------------- limitations and future
s = slide("Limitations and future work", "I want to be clear about the limits. The designs are small, each prompt was run once, mainly "
          "with one model; only toggle coverage is measured; timing is before layout. The next steps follow directly from these.",
          kicker="Honest limits")
cw2 = (W - 1.2 - 0.35) / 2
for k, (t, c, bc, items) in enumerate([
        ("Limitations", RED, T_RED, ["Small designs (under about 100 lines), one run each, mainly one model",
                                     "Only toggle coverage is measured; no assertions",
                                     "Timing is pre-layout on one corner; strength samples up to 12 mutants",
                                     "The agent's fixes are verified, its explanations are not",
                                     "The sandbox is defence in depth, not a jail"]),
        ("Future work", GREEN, T_GREEN, ["Power from the simulation's own activity",
                                         "Testbench hardening from the bugs it missed",
                                         "OpenROAD place and route for post-layout timing",
                                         "SVA assertions, and a Tiny Tapeout chip"])]):
    x = 0.6 + k * (cw2 + 0.35)
    box(s, x, 1.7, cw2, 4.6, fillc=bc, line=c, lw=1.5)
    box(s, x, 1.7, cw2, 0.62, fillc=c, line=c, paras=[t], size=20, color=WHITE, bold=True, label="lf " + t)
    bullets(s, x + 0.25, 2.55, cw2 - 0.5, 3.7, items, size=18.5, label="lf b " + t, space_after=11)

# 16 --------------------------------------------------------------- conclusion
s = slide(None, "To conclude: SiliconScribe lets a language model design hardware while the simulator stays the judge, and every PASS "
          "states how much it is worth. Thank you, I am happy to take questions or show a live run.")
box(s, 0, 0, W, 7.0, fillc=NAVY, line=None)
text(s, 1.0, 1.05, W - 2.0, 0.5, ["CONCLUSION"], size=15, color=RGBColor(0x93, 0xC5, 0xFD), bold=True, label="c kick")
text(s, 1.0, 1.55, W - 2.0, 1.9, ["Only the simulator decides, and every PASS states how much it is worth."], size=36,
     color=WHITE, bold=True, label="c main")
for k, (big, small) in enumerate([("14 / 14", "live runs PASS"), ("102 / 111", "bugs caught"), ("16 / 18", "netlists formally proven"),
                                  ("632 + 277", "automated tests")]):
    x = 1.0 + k * 2.88
    text(s, x, 3.75, 2.7, 0.75, [big], size=32, color=WHITE, bold=True, label="c big")
    text(s, x, 4.45, 2.7, 0.45, [small], size=15, color=RGBColor(0xCB, 0xD5, 0xE1), label="c small")
box(s, 1.0, 5.3, 2.2, 0.05, fillc=RED, line=None)
text(s, 1.0, 5.5, W - 2.0, 0.8, ["Thank you.  Questions?"], size=30, color=WHITE, bold=True, label="c thanks")

prs.save(OUT)
bad = [(l, n, a) for l, n, a in REPORT if n > a * 0.95 + 0.02]
print(f"saved {OUT}: {len(prs.slides)} slides; text boxes {len(REPORT)}; overflowing {len(bad)}")
for l, n, a in bad:
    print(f"  OVERFLOW {l[:60]!r}: needs {n}, has {a}")
