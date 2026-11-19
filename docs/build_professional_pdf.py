import os
import shutil
import pypdf
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#374151"))
        
        # Header (Pages 2+) - Simple clean academic line and text
        if self._pageNumber > 1:
            self.setStrokeColor(colors.HexColor("#9ca3af"))
            self.setLineWidth(0.5)
            self.line(40, 804, 555, 804)
            self.drawString(40, 809, "SiliconScribe: Autonomous EDA Playground")
            self.drawRightString(555, 809, "CHARUSAT • CSPIT • Department of ECE • EC486 Minor Project")
            
        # Footer (All pages)
        self.setStrokeColor(colors.HexColor("#9ca3af"))
        self.setLineWidth(0.5)
        self.line(40, 36, 555, 36)
        self.drawString(40, 24, "Kushal Pitaliya (23EC105) — Progress Report")
        self.drawRightString(555, 24, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()

def build_architecture_diagram():
    # Pure grayscale engineering block diagram
    d = Drawing(515, 126)
    
    # Outer frame: simple clean black outline
    d.add(Rect(0, 0, 515, 126, fillColor=colors.white, strokeColor=colors.HexColor('#4b5563'), strokeWidth=0.8, rx=2, ry=2))
    
    # Layer 1: Client Layer
    d.add(Rect(12, 88, 491, 28, fillColor=colors.HexColor('#f9fafb'), strokeColor=colors.HexColor('#111827'), strokeWidth=0.8, rx=2, ry=2))
    d.add(String(20, 104, "CLIENT LAYER (React 18 + TypeScript + Vite)", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor('#111827')))
    d.add(String(20, 94, "Prompt & Model Picker  •  CodeMirror 6 Editor (.v / .sv)  •  SVG Waveform Viewer  •  Agent Chat Stream", fontName="Helvetica", fontSize=7, fillColor=colors.HexColor('#374151')))
    
    # Arrow 1: Downward black arrow
    d.add(Line(257, 88, 257, 74, strokeColor=colors.HexColor('#111827'), strokeWidth=0.8))
    d.add(Polygon([255, 77, 259, 77, 257, 72], fillColor=colors.HexColor('#111827'), strokeColor=None))
    d.add(String(263, 78, "HTTP POST / SSE Stream", fontName="Helvetica-Oblique", fontSize=6.5, fillColor=colors.HexColor('#4b5563')))
    
    # Layer 2: Backend Pipeline
    d.add(Rect(12, 46, 491, 28, fillColor=colors.HexColor('#f9fafb'), strokeColor=colors.HexColor('#111827'), strokeWidth=0.8, rx=2, ry=2))
    d.add(String(20, 62, "BACKEND PIPELINE (FastAPI + Python)", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor('#111827')))
    d.add(String(20, 52, "Intent Parser  •  Verilog-2001 Generator  •  Linter  •  Autonomous Debugger (Hash Guard)  •  UVM 1.2 Export", fontName="Helvetica", fontSize=7, fillColor=colors.HexColor('#374151')))
    
    # Arrow 2: Downward black arrow
    d.add(Line(257, 46, 257, 32, strokeColor=colors.HexColor('#111827'), strokeWidth=0.8))
    d.add(Polygon([255, 35, 259, 35, 257, 30], fillColor=colors.HexColor('#111827'), strokeColor=None))
    d.add(String(263, 36, "Subprocess Execution", fontName="Helvetica-Oblique", fontSize=6.5, fillColor=colors.HexColor('#4b5563')))
    
    # Layer 3: EDA Toolchain
    d.add(Rect(12, 4, 491, 26, fillColor=colors.HexColor('#f9fafb'), strokeColor=colors.HexColor('#111827'), strokeWidth=0.8, rx=2, ry=2))
    d.add(String(20, 19, "LOCAL EDA TOOLCHAIN & PERSISTENCE", fontName="Helvetica-Bold", fontSize=8, fillColor=colors.HexColor('#111827')))
    d.add(String(20, 10, "Icarus Verilog (iverilog & vvp)  •  Yosys Open Synthesis Suite  •  SQLite Persistence (projects.db)", fontName="Helvetica", fontSize=7, fillColor=colors.HexColor('#374151')))
    
    return d

def generate_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=42,
        bottomMargin=45
    )
    
    # Clean professional grayscale palette
    COLOR_BLACK = colors.HexColor("#000000")
    COLOR_TEXT = colors.HexColor("#1f2937")
    COLOR_MUTED = colors.HexColor("#4b5563")
    BORDER_MED = colors.HexColor("#9ca3af")
    BORDER_LIGHT = colors.HexColor("#d1d5db")
    BG_LIGHT = colors.HexColor("#f9fafb")
    BG_HEAD = colors.HexColor("#f3f4f6")
    
    body = ParagraphStyle('ReportBody', fontName='Helvetica', fontSize=8.7, leading=12.2, textColor=COLOR_TEXT, alignment=4)
    body_italic = ParagraphStyle('ReportBodyItalic', fontName='Helvetica-Oblique', fontSize=8.7, leading=12.2, textColor=COLOR_TEXT, alignment=4)
    bullet = ParagraphStyle('ReportBullet', fontName='Helvetica', fontSize=8.7, leading=12, textColor=COLOR_TEXT, leftIndent=12, firstLineIndent=-8)
    
    title_univ = ParagraphStyle('UnivTitle', fontName='Helvetica-Bold', fontSize=10.5, leading=13.5, textColor=COLOR_BLACK, alignment=1)
    title_sub = ParagraphStyle('UnivSub', fontName='Helvetica', fontSize=8.5, leading=11, textColor=COLOR_MUTED, alignment=1)
    
    proj_title = ParagraphStyle('ProjTitle', fontName='Helvetica-Bold', fontSize=13, leading=16.5, textColor=COLOR_BLACK, alignment=1)
    
    h1 = ParagraphStyle('ReportH1', fontName='Helvetica-Bold', fontSize=10.5, leading=13.5, textColor=COLOR_BLACK, spaceBefore=8, spaceAfter=3, keepWithNext=True)
    h2 = ParagraphStyle('ReportH2', fontName='Helvetica-Bold', fontSize=9.2, leading=12, textColor=COLOR_BLACK, spaceBefore=5, spaceAfter=2, keepWithNext=True)
    
    table_cell = ParagraphStyle('TableCell', fontName='Helvetica', fontSize=7.8, leading=10, textColor=COLOR_TEXT)
    table_cell_bold = ParagraphStyle('TableCellBold', fontName='Helvetica-Bold', fontSize=7.8, leading=10, textColor=COLOR_BLACK)
    table_head = ParagraphStyle('TableHead', fontName='Helvetica-Bold', fontSize=8, leading=10.5, textColor=COLOR_BLACK)
    
    code_style = ParagraphStyle('CodeLine', fontName='Courier', fontSize=6.8, leading=9.2, textColor=COLOR_BLACK)
    code_bold = ParagraphStyle('CodeLineBold', fontName='Courier-Bold', fontSize=6.8, leading=9.2, textColor=COLOR_BLACK)
    code_comment = ParagraphStyle('CodeComment', fontName='Courier-Oblique', fontSize=6.8, leading=9.2, textColor=COLOR_MUTED)
    
    caption_style = ParagraphStyle('Caption', fontName='Helvetica-Oblique', fontSize=7.5, leading=9.5, textColor=COLOR_MUTED, alignment=1)

    story = []

    # ==================== PAGE 1: TITLE, ABSTRACT, 1. INTRODUCTION ====================
    story.append(Paragraph("CHAROTAR UNIVERSITY OF SCIENCE AND TECHNOLOGY (CHARUSAT)", title_univ))
    story.append(Paragraph("Chandubhai S. Patel Institute of Technology (CSPIT) • V. T. Patel Department of ECE", title_sub))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER_MED, spaceAfter=5, spaceBefore=2))
    
    meta_data = [
        [
            Paragraph("<b>Course:</b> EC486: Minor Project (Odd Sem 2026–27)", table_cell),
            Paragraph("<b>Student Name:</b> Kushal Pitaliya", table_cell),
            Paragraph("<b>Roll No:</b> 23EC105", table_cell_bold),
        ],
        [
            Paragraph("<b>Submission:</b> Progress Report", table_cell),
            Paragraph("<b>Program:</b> B.Tech. Electronics & Comm. Engg.", table_cell),
            Paragraph("<b>Date:</b> October 15, 2026", table_cell),
        ]
    ]
    t_meta = Table(meta_data, colWidths=[185, 200, 130])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 6))

    story.append(Paragraph("SiliconScribe: An AI-Assisted EDA Playground with Autonomous RTL Verification and Self-Correction", proj_title))
    story.append(Spacer(1, 3))
    story.append(HRFlowable(width="100%", thickness=1.0, color=COLOR_BLACK, spaceAfter=6, spaceBefore=2))

    # Academic IEEE-Style Abstract (bordered by thin horizontal rules, no bright colors)
    abstract_text = (
        "<b>Abstract</b>— In digital Integrated Circuit (IC) design, writing Register-Transfer Level (RTL) code and developing "
        "self-checking verification testbenches represent over 70% of engineering time. While Large Language Models (LLMs) can generate "
        "Verilog snippets from natural language, they frequently produce syntax errors, unsupported constructs, and functional timing bugs. "
        "Critically, generic AI operates in an open loop: it cannot compile, simulate, or debug its output. To solve this, I designed and built "
        "<b>SiliconScribe</b>, an execution-grounded browser-based Electronic Design Automation (EDA) playground. SiliconScribe translates English "
        "specifications into synthesizable Verilog-2001 RTL, generates self-checking testbenches, runs hardware simulation via Icarus Verilog, "
        "and executes an <b>autonomous closed-loop self-correction engine</b>. Simulation errors are automatically parsed and fed back to an AI "
        "debugger with normalized SHA-256 hashing and cycle-detection guards to prevent thrashing. The platform also includes a native SVG "
        "digital waveform viewer, multi-tier linting, Yosys synthesis metrics, and an industrial 16-file UVM 1.2 bundle export for QuestaSim. "
        "The project has been verified with 42 backend pytest cases and 36 frontend vitest tests."
    )
    
    t_abs = Table([[Paragraph(abstract_text, body)]], colWidths=[515])
    t_abs.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 0.6, BORDER_MED),
        ('LINEBELOW', (0, 0), (-1, -1), 0.6, BORDER_MED),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_abs)
    story.append(Spacer(1, 6))

    story.append(Paragraph("1. INTRODUCTION", h1))
    story.append(Paragraph("<b>1.1 Motivation & Problem Statement:</b> Modern digital semiconductor design requires rigorous specification and functional verification. However, applying generic AI coding models to digital hardware design presents major practical challenges:", body))
    story.append(Paragraph("• <b>Toolchain Incompatibility:</b> Generic LLMs frequently emit modern SystemVerilog constructs (e.g., <code>logic</code>, <code>always_ff</code>, interfaces, classes) that standard open-source tools like Icarus Verilog cannot compile.", bullet))
    story.append(Paragraph("• <b>No Hardware Execution Awareness:</b> Language models do not evaluate simulation cycles, race conditions, clock edges, propagation delays, or assertion mismatches.", bullet))
    story.append(Paragraph("• <b>Open-Loop Guessing:</b> When generated code fails compilation or assertions, human engineers must manually diagnose simulator transcripts and formulate debugging prompts.", bullet))
    story.append(Spacer(1, 3))
    story.append(Paragraph("<b>1.2 Project Scope & Objectives:</b> Developed as an individual software-based minor project for course <b>EC486</b>, the primary objective is to build an autonomous EDA environment that bridges the gap between natural language prompts and working hardware verification. Specific goals achieved include:", body))
    story.append(Paragraph("1. <b>Structured Intent Parsing:</b> Extracting module names, parameters, and directional port widths into a validated schema (<code>RTLDesignSpec</code>).", bullet))
    story.append(Paragraph("2. <b>Synthesizable Code Generation:</b> Producing standard Verilog-2001 RTL and self-checking testbenches with directed and randomized stimulus.", bullet))
    story.append(Paragraph("3. <b>Autonomous Closed-Loop Debugger:</b> Recursively diagnosing simulation errors and applying patches with oscillation detection guards.", bullet))
    story.append(Paragraph("4. <b>Interactive Visualization:</b> Implementing a native in-browser SVG digital waveform viewer and port-level block diagrams.", bullet))
    story.append(Paragraph("5. <b>Synthesis & UVM Integration:</b> Providing Yosys cell/area estimation and commercial 16-file UVM 1.2 bundle export for QuestaSim.", bullet))
    story.append(Paragraph("6. <b>Zero-Budget Resilience:</b> Maintaining full functionality offline via curated designs so demonstrations never fail without internet.", bullet))
    
    # Page 1 Break
    story.append(PageBreak())

    # ==================== PAGE 2: WORKING & ALGORITHM ====================
    story.append(Paragraph("2. WORKING (DESIGN, ARCHITECTURE, AND METHODOLOGY)", h1))
    story.append(Paragraph("<b>2.1 System Architecture:</b> The platform uses a modular three-tier architecture connecting a React frontend, a FastAPI Python orchestration backend, and containerized open-source EDA tools (Figure 1).", body))
    story.append(Spacer(1, 4))
    
    # Diagram and caption kept strictly together
    story.append(KeepTogether([
        build_architecture_diagram(),
        Spacer(1, 3),
        Paragraph("Figure 1: High-Level Three-Tier Architecture of SiliconScribe", caption_style)
    ]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("<b>2.2 Automated Pipeline Workflow:</b> When a prompt is submitted, the pipeline streams stages over Server-Sent Events (SSE):", body))
    story.append(Paragraph("• <b>Intent Parsing:</b> Extracts structural port maps (input/output/inout), bit widths, and constraints into a Pydantic schema.", bullet))
    story.append(Paragraph("• <b>RTL Generation:</b> Generates synthesizable Verilog-2001 using <code>reg</code>/<code>wire</code> and standard sensitivity lists (Icarus <code>-g2012</code> compatible).", bullet))
    story.append(Paragraph("• <b>Static Linting:</b> Non-blocking static analysis checking duplicate modules, <code>module/endmodule</code> mismatches, and syntax heuristics.", bullet))
    story.append(Paragraph("• <b>Testbench Generation:</b> Generates clock generators, DUT instantiation, randomized stimuli, self-checking comparisons (<code>===</code>), and auto-injects VCD dump commands (<code>$dumpfile</code>, <code>$dumpvars</code>).", bullet))
    story.append(Paragraph("• <b>Simulation Execution:</b> Invokes <code>iverilog</code> and runs the compiled binary via <code>vvp</code> under an isolated workspace with a 30s timeout.", bullet))
    story.append(Paragraph("• <b>Self-Correction Loop:</b> If simulation fails, the error log and code are routed to the debugger until passing or reaching max iterations.", bullet))
    story.append(Spacer(1, 5))

    # Algorithm Box kept strictly together (Classic LaTeX algorithm layout)
    algo_lines = [
        Paragraph("<b>Algorithm 1: Autonomous Closed-Loop Hardware Self-Correction Loop</b>", code_bold),
        Paragraph("<b>Input :</b> Natural language prompt, Target frequency, Max iterations <i>N</i> (default 5)", code_style),
        Paragraph("<b>Output:</b> Final verified RTL, Self-checking testbench, Waveforms, Pass/Fail verdict", code_style),
        Paragraph("------------------------------------------------------------------------------------------------------------------------", code_style),
        Paragraph("1:  Spec = ParseIntent(prompt) ;  RTL = GenerateRTL(Spec) ;  TB = GenerateTestbench(RTL, Spec)", code_style),
        Paragraph("2:  SeenHashes = { NormHash(RTL) }", code_style),
        Paragraph("3:  Status, Log, PassCount, FailCount = Simulate(RTL, TB)", code_style),
        Paragraph("4:  Iteration = 0", code_style),
        Paragraph("5:  <b>while</b> Status in ['FAIL', 'ERROR'] <b>and</b> Iteration &lt; N <b>do</b>", code_style),
        Paragraph("6:      Iteration = Iteration + 1", code_style),
        Paragraph("7:      Patch = LLM_FixDesign(RTL, TB, Log)        <font color='#4b5563'>// Request diagnostic patch from LLM</font>", code_style),
        Paragraph("8:      New_Hash = NormHash(Patch.rtl_code)", code_style),
        Paragraph("9:      <b>if</b> New_Hash == NormHash(RTL) <b>then</b> break        <font color='#4b5563'>// Guard 1: Terminate if model made no change</font>", code_style),
        Paragraph("10:     <b>if</b> New_Hash in SeenHashes <b>then</b> break           <font color='#4b5563'>// Guard 2: Terminate if model repeated prior code</font>", code_style),
        Paragraph("11:     SeenHashes.add(New_Hash)", code_style),
        Paragraph("12:     RTL = Patch.rtl_code ;  TB = Patch.testbench_code", code_style),
        Paragraph("13:     Status, Log, PassCount, FailCount = Simulate(RTL, TB)", code_style),
        Paragraph("14: <b>end while</b>", code_style),
        Paragraph("15: <b>return</b> RTL, TB, Status, Log, Waveform", code_style),
    ]
    t_algo = Table([[line] for line in algo_lines], colWidths=[515])
    t_algo.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.6, COLOR_BLACK),
        ('LINEABOVE', (0, 0), (-1, 0), 1.0, COLOR_BLACK),
        ('LINEBELOW', (0, -1), (-1, -1), 1.0, COLOR_BLACK),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))

    story.append(KeepTogether([
        Paragraph("<b>2.3 The Autonomous Closed-Loop Self-Correction Algorithm:</b>", h2),
        Paragraph("The core technical contribution is the autonomous debugging loop. Rather than open-loop prompting, simulation failures are fed back to the model with strict oscillation guards to prevent token thrashing:", body),
        Spacer(1, 3),
        t_algo,
        Spacer(1, 3),
        Paragraph("<b>Normalized Hash (NormHash):</b> To prevent false restarts caused by cosmetic whitespace or comments, <code>_norm_hash()</code> strips all single-line comments (<code>//.*</code>), multi-line comments (<code>/* ... */</code>), and whitespace before computing a SHA-256 digest. If <code>New_Hash</code> exists in <code>SeenHashes</code>, the loop aborts immediately.", body)
    ]))

    # Page 2 Break
    story.append(PageBreak())

    # ==================== PAGE 3: FEATURES & RESULTS ====================
    story.append(Paragraph("<b>2.4 Digital Waveform Parser & SVG Viewer:</b> The backend parser (<code>backend/vcd_parser.py</code>) converts VCD output into compact JSON structures, encoding buses into hexadecimal (<code>0x5</code>) while tracking 4-state unknown (<code>x</code>) and high-impedance (<code>z</code>) signals. It applies safety caps (max 40 signals, max 2000 transitions) to protect memory. The frontend SVG viewer renders responsive traces with zoom in/out, pan, and time-ruler markers.", body))
    story.append(Spacer(1, 3))
    story.append(Paragraph("<b>2.5 Industrial UVM 1.2 Export:</b> To connect with commercial verification, <code>backend/uvm_templates.py</code> exports a complete 16-file UVM testbench suite (interfaces with clocking blocks, sequence items, drivers, monitors, scoreboards, coverage subscriber with covergroups, testbench top, QuestaSim <code>Makefile</code>, and <code>filelist.f</code>) packaged as a downloadable base64 <code>.zip</code>.", body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("3. RESULTS AND DISCUSSION", h1))
    story.append(Paragraph("<b>3.1 Work Completed So Far (Milestone Status: 15/10/2026):</b>", h2))
    story.append(Paragraph("• Full pipeline operating end-to-end: prompt parsing &rarr; Verilog generation &rarr; Icarus simulation &rarr; auto-fix &rarr; waveform rendering.", bullet))
    story.append(Paragraph("• Autonomous self-correction engine proven on compile errors and testbench assertion failures.", bullet))
    story.append(Paragraph("• Multi-tier static linter (Verilator + Icarus + regex) and Yosys synthesis metrics integration.", bullet))
    story.append(Paragraph("• Browser UI with CodeMirror editor, SVG waveforms, project drawer, and 16-file UVM ZIP export.", bullet))
    story.append(Paragraph("• Offline resilience: 5 verified hardware designs running locally with zero API keys.", bullet))
    story.append(Spacer(1, 4))

    # Case Study Table (Classic IEEE academic styling)
    case_data = [
        [Paragraph("Stage / Attempt", table_head), Paragraph("Generated Verilog RTL Snippet", table_head), Paragraph("Simulation Verdict", table_head), Paragraph("Automated Action", table_head)],
        [
            Paragraph("<b>Attempt #0</b><br/>(Initial Gen)", table_cell),
            Paragraph("<code>count &lt;= count + 2'd2;</code><br/>(Bug: increments by 2 instead of 1)", table_cell),
            Paragraph("<b>FAIL</b><br/>0/20 Passed<br/>20/20 Failed", table_cell),
            Paragraph("Captured log: <i>'FAIL: expected=1 got=2'</i>. Routed code + log to AI debugger.", table_cell),
        ],
        [
            Paragraph("<b>Attempt #1</b><br/>(Autonomous Patch)", table_cell),
            Paragraph("<code>count &lt;= count + 1'b1;</code><br/>(Patched line 14 to correct increment)", table_cell),
            Paragraph("<b>PASS</b><br/>20/20 Passed<br/>0 Failed", table_cell),
            Paragraph("Simulation passed on re-run. Output summary: <i>'ALL TESTS PASSED'</i>. Loop terminated.", table_cell),
        ]
    ]
    t_case = Table(case_data, colWidths=[80, 165, 85, 185])
    t_case.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BG_HEAD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_MED),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ('LINEABOVE', (0, 0), (-1, 0), 1.0, COLOR_BLACK),
        ('LINEBELOW', (0, 0), (-1, 0), 0.75, COLOR_BLACK),
        ('LINEBELOW', (0, -1), (-1, -1), 1.0, COLOR_BLACK),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))

    story.append(KeepTogether([
        Paragraph("<b>3.2 Autonomous Self-Correction Case Study (Buggy 4-Bit Counter):</b>", h2),
        Paragraph("To evaluate the closed-loop debugger, a prompt requested a deliberately buggy counter: <i>'Design a 4-bit synchronous up-counter with async reset and enable, but make it buggy.'</i> Table 1 documents the autonomous resolution:", body),
        Spacer(1, 3),
        t_case,
        Spacer(1, 2),
        Paragraph("Table 1: Empirical Evaluation of Closed-Loop Self-Correction on Synchronous Counter", caption_style)
    ]))
    story.append(Spacer(1, 5))

    # Benchmark Designs Table (Classic IEEE academic styling)
    bench_data = [
        [Paragraph("Module", table_head), Paragraph("Functionality", table_head), Paragraph("Bit-Width", table_head), Paragraph("Logic Type", table_head), Paragraph("Vectors", table_head), Paragraph("Pass Rate", table_head)],
        [Paragraph("<b>counter</b>", table_cell), Paragraph("Synchronous up-counter with async reset & enable", table_cell), Paragraph("4-bit", table_cell), Paragraph("Sequential", table_cell), Paragraph("20", table_cell), Paragraph("<b>100% PASS</b>", table_cell)],
        [Paragraph("<b>alu_4bit</b>", table_cell), Paragraph("ALU: ADD, SUB, AND, OR, XOR with overflow", table_cell), Paragraph("4-bit", table_cell), Paragraph("Combinational", table_cell), Paragraph("120", table_cell), Paragraph("<b>100% PASS</b>", table_cell)],
        [Paragraph("<b>alu_8bit</b>", table_cell), Paragraph("ALU: ADD, SUB, AND, OR, XOR with 9-bit carry", table_cell), Paragraph("8-bit", table_cell), Paragraph("Combinational", table_cell), Paragraph("120", table_cell), Paragraph("<b>100% PASS</b>", table_cell)],
        [Paragraph("<b>full_adder</b>", table_cell), Paragraph("1-bit full adder with carry-in and carry-out", table_cell), Paragraph("1-bit", table_cell), Paragraph("Combinational", table_cell), Paragraph("8", table_cell), Paragraph("<b>100% PASS</b>", table_cell)],
        [Paragraph("<b>mux4to1</b>", table_cell), Paragraph("4-to-1 multiplexer with parameterizable bus width", table_cell), Paragraph("8-bit", table_cell), Paragraph("Combinational", table_cell), Paragraph("20", table_cell), Paragraph("<b>100% PASS</b>", table_cell)],
    ]
    t_bench = Table(bench_data, colWidths=[65, 190, 50, 75, 55, 80])
    t_bench.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BG_HEAD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_MED),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ('LINEABOVE', (0, 0), (-1, 0), 1.0, COLOR_BLACK),
        ('LINEBELOW', (0, 0), (-1, 0), 0.75, COLOR_BLACK),
        ('LINEBELOW', (0, -1), (-1, -1), 1.0, COLOR_BLACK),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))

    story.append(KeepTogether([
        Paragraph("<b>3.3 Offline Hardware Benchmark Suite:</b>", h2),
        Paragraph("Five pre-verified digital modules were benchmarked in offline mode to guarantee functionality without external API dependencies:", body),
        Spacer(1, 3),
        t_bench,
        Spacer(1, 2),
        Paragraph("Table 2: Verification Benchmarks for Curated Offline Hardware Modules", caption_style)
    ]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>3.4 Logic Synthesis Metrics (Yosys):</b> Gate-level synthesis through Yosys confirmed standard cell counts: <code>full_adder</code>: 2 cells (~10 &mu;m<sup>2</sup>), <code>counter</code>: 12 cells (~60 &mu;m<sup>2</sup>), <code>alu_4bit</code>: 22 cells (~110 &mu;m<sup>2</sup>).", body))
    story.append(Paragraph("<b>3.5 Test Suite Results:</b> The codebase is validated by <b>42 backend pytest cases</b> (23 passing offline, 19 simulator-integrated) and <b>36 frontend vitest unit tests</b> (passing in 843ms). The TypeScript frontend builds cleanly with zero errors.", body))

    # Page 3 Break
    story.append(PageBreak())

    # ==================== PAGE 4: LIMITATIONS, CONCLUSION, REFERENCES ====================
    story.append(Paragraph("4. LIMITATIONS", h1))
    story.append(Paragraph("1. <b>UVM Simulation Tool Dependency:</b> While the system exports complete UVM 1.2 testbenches, Icarus Verilog does not support SystemVerilog OOP classes. Simulating the UVM bundle requires commercial EDA simulators (QuestaSim / VCS).", bullet))
    story.append(Paragraph("2. <b>Schematic Display Level:</b> The in-browser schematic viewer currently renders a clean port-level block diagram. Gate-level netlist schematics directly from Yosys JSON require future integration with web netlist viewers like <code>netlistsvg</code>.", bullet))
    story.append(Paragraph("3. <b>Macro-Level Scope:</b> The tool is optimized for single-module designs or small digital blocks (&le; 1,000 lines of Verilog) rather than multi-million gate SoC architectures with complex bus protocols (e.g., AXI/AHB).", bullet))
    story.append(Spacer(1, 8))

    story.append(Paragraph("5. CONCLUSION AND FUTURE ROADMAP", h1))
    story.append(Paragraph("<b>5.1 Conclusion:</b> SiliconScribe successfully demonstrates that generative AI can transcend open-loop code guessing when combined with an execution engine. By integrating natural language parsing, synthesizable Verilog-2001 generation, Icarus Verilog simulation, and an autonomous self-correction loop with normalized hash guards, the platform reliably produces verified digital designs and standard verification artifacts.", body))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>5.2 Roadmap Toward Final Submission (Deadline: 06/11/2026):</b>", h2))
    story.append(Paragraph("1. <b>Gate-Level Schematic Rendering:</b> Integrate <code>netlistsvg</code> to visualize synthesized Yosys gate-level netlists directly in the browser.", bullet))
    story.append(Paragraph("2. <b>Hierarchical Multi-Module Design:</b> Expand intent parsing to support sub-module instantiation (e.g., combining adders and registers into multi-stage pipelines).", bullet))
    story.append(Paragraph("3. <b>Poster and Presentation Preparation:</b> Finalize the project poster, slide deck, and live software demo for the final evaluation.", bullet))
    story.append(Spacer(1, 8))

    story.append(Paragraph("6. REFERENCES", h1))
    refs = [
        "1. IEEE Standard for SystemVerilog—Unified Hardware Design, Specification, and Verification Language, <i>IEEE Std 1800-2017</i>, pp. 1–1315, 2017.",
        "2. Accellera Systems Initiative, <i>Universal Verification Methodology (UVM) 1.2 User's Guide</i>, Accellera Organization, 2015.",
        "3. S. Thakur et al., 'VeriGen: A Large Language Model for Verilog Code Generation,' <i>ACM TODAES</i>, vol. 29, no. 3, pp. 1–31, 2024.",
        "4. M. Liu et al., 'ChipNeMo: Domain-Adapted LLMs for Chip Design,' in <i>Proc. 61st ACM/IEEE Design Automation Conference (DAC)</i>, 2024, pp. 1–6.",
        "5. S. Williams, 'Icarus Verilog: An Open-Source Verilog Compiler and Simulator,' Available: http://iverilog.icarus.com/, 2026.",
        "6. C. Wolf, 'Yosys Open Synthesis Suite,' in <i>Proc. 21st International Workshop on Logic & Synthesis (IWLS)</i>, 2012.",
        "7. W. Snyder, 'Verilator: Fast Open-Source Verilog Simulator,' Veripool.org, 2024."
    ]
    for r in refs:
        story.append(Paragraph(r, ParagraphStyle('Ref', fontName='Helvetica', fontSize=8, leading=10.5, textColor=COLOR_TEXT, leftIndent=12, firstLineIndent=-12)))
        story.append(Spacer(1, 2))

    doc.build(story, canvasmaker=NumberedCanvas)
    
    reader = pypdf.PdfReader(output_path)
    print(f"Generated {output_path}: exactly {len(reader.pages)} pages, {os.path.getsize(output_path)} bytes")

if __name__ == "__main__":
    out_pdf = "docs/EC486_Minor_Project_Report.pdf"
    generate_pdf(out_pdf)
    
    root_pdf = "EC486_Minor_Project_Report.pdf"
    shutil.copy(out_pdf, root_pdf)
    print(f"Copied to root: {root_pdf}")

    artifact_dir = "/Users/kushalpitaliya/.gemini/antigravity/brain/dec5c233-339c-4701-af2a-fad175324425"
    if os.path.exists(artifact_dir):
        shutil.copy(out_pdf, os.path.join(artifact_dir, "EC486_Minor_Project_Report.pdf"))
        print(f"Copied to artifact dir: {artifact_dir}/EC486_Minor_Project_Report.pdf")
