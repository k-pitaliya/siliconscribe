"""Generate the function index appendix (function_index.tex) straight from the code.

Every backend function/method is listed with its file and a one-line purpose:
the first line of its docstring when it has one, otherwise the hand-written
description below. Run from docs/guide/:  python3 gen_function_index.py
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

# Descriptions for functions that have no docstring (written from reading the code).
DESC = {
    "equivalence._script": "Build the Yosys proof script: RTL (gold) vs sky130 netlist (gate); SAT on a miter, or induction for registers.",
    "cov_metrics.compute_coverage": "Summarise what the testbench exercised: vectors run, passed, failed, pass rate, any COV: bins and any printed toggle/branch/line coverage figures.",
    "db._db_path": "Return the path of projects.db inside the workspace.",
    "db._ensure_table": "Create the projects table (and add missing columns to older databases) plus an index on created_at.",
    "db.count_projects": "Return how many projects are stored.",
    "db.delete_project": "Delete one project by id; True if a row was removed.",
    "llm_service._extract_json": "Pull the JSON object out of a model reply (fenced or surrounded by prose) and parse it, tolerating raw newlines inside strings.",
    "llm_service._section": "Return the text between <tag> and </tag> in a model reply, or None.",
    "llm_service._parse_diagnosis": "Turn the <diagnosis> block (symptom / root_cause / fix_location / confidence lines) into a dict.",
    "llm_service.OpenAIProvider.__init__": "Create the OpenAI-compatible client with timeout and token budget from the environment, and read the per-stage model overrides.",
    "llm_service.OpenAIProvider._chat": "Send one chat request: pick the model (request override > stage model > default), disable hidden reasoning unless asked, map provider failures to LLM_UPSTREAM errors, reject truncated or empty answers.",
    "llm_service.OpenAIProvider.parse_intent": "Ask the model to turn the prompt into JSON and validate it as an RTLDesignSpec (temperature 0.3).",
    "llm_service.OpenAIProvider.generate_rtl": "Ask the model for Verilog from the specification (temperature 0.2) and extract the module.",
    "llm_service.OpenAIProvider.generate_testbench": "Ask the model for a self-checking testbench from the specification only; the RTL body is deliberately withheld.",
    "llm_service.OpenAIProvider.explain_design": "Ask for a 2-3 sentence explanation of the RTL (cheaper model unless the user chose one).",
    "llm_service.OpenAIProvider.fix_design": "Send spec, RTL, testbench and the last 4000 characters of the simulator log to the debugger prompt and parse its diagnosis and patch.",
    "llm_service.OfflineProvider.__init__": "Start with no matched design.",
    "llm_service.OfflineProvider.parse_intent": "Match the prompt to a curated design by keyword and return that design's specification.",
    "llm_service.OfflineProvider.generate_rtl": "Return the curated RTL (or its buggy variant for the self-correction demo).",
    "llm_service.OfflineProvider.generate_testbench": "Return the curated testbench for the matched design.",
    "llm_service.OfflineProvider.explain_design": "Return the curated explanation, prefixed with an [Offline demo] note when the prompt was not an exact match.",
    "llm_service.OfflineProvider.fix_design": "Scripted fix: swap in the known-correct RTL. Reports fix_type offline_scripted and NO diagnosis, because none was produced.",
    "llm_service._placeholder": "True if an environment value is empty or a 'your_...' placeholder.",
    "llm_service._is_offline_env": "True if OFFLINE_MODE is set to 1/true/yes/on.",
    "llm_service.get_provider": "Return the active provider (always offline when OFFLINE_MODE is set).",
    "llm_service.is_offline": "True when the app is running on the offline provider.",
    "llm_service.current_model": "Name of the configured live model, or None offline.",
    "llm_service.parse_intent": "Module-level wrapper: forwards to the active provider.",
    "llm_service.generate_rtl": "Module-level wrapper: forwards to the active provider.",
    "llm_service.generate_testbench": "Module-level wrapper: forwards to the active provider.",
    "llm_service.explain_design": "Module-level wrapper: forwards to the active provider.",
    "llm_service.fix_design": "Module-level wrapper: forwards to the active provider.",
    "main._get_client_ip": "Find the caller's IP for rate limiting: the socket address, or the last X-Forwarded-For entry only when TRUST_PROXY_HEADERS says a trusted proxy is in front.",
    "main._check_rate_limit": "Thread-safe wrapper: take the lock and apply the rate limit.",
    "main._check_rate_limit_locked": "Sliding-window limiter: at most 20 requests per 60 s per IP, otherwise HTTP 429.",
    "main._startup_gc": "On server start, delete workspace folders older than 24 h.",
    "main._new_design_id": "Return a fresh full UUID (hex) used as the design and project id.",
    "main.root": "GET / : name, provider, offline flag and simulator availability.",
    "models.SimulationRequest.validate_design_id": "Reject design ids that are not 1-32 characters of letters, digits, _ or -.",
    "models.SynthesisRequest.validate_module_name": "Reject module names that are not legal Verilog identifiers.",
    "models.UVMExportRequest.validate_module_override": "Reject an override module name that is not a legal identifier.",
    "offline_designs._marker": "Return the '// [offline:key]' comment used to recognise a curated design later.",
    "offline_designs.match_design": "Pick a curated design key from prompt keywords (8-bit ALU, ALU, counter, adder, mux); default counter.",
    "offline_designs.is_buggy_request": "True if the prompt asks for a buggy design (drives the self-correction demo).",
    "offline_designs.get_design": "Return the spec, RTL, testbench and explanation for a design key.",
    "offline_designs.design_key_from_rtl": "Read the [offline:key] marker back out of RTL text.",
    "openroad.check_openroad_available": "True if the openroad binary is on PATH (the flow itself is a stub).",
    "orchestrator._tb_check_count": "Count places where a testbench can fail (fail_count updates, $error/$fatal, assert).",
    "orchestrator._sim_message": "Human-readable one-line summary of a simulation result.",
    "orchestrator._final_message": "Human-readable final verdict (passes first time / after N iterations / could not pass).",
    "schematic.build_schematic": "Group the specification's ports into inputs, outputs and inouts for the port-level diagram.",
    "simulator.IcarusSimulator.__init__": "Resolve and create the workspace folder.",
    "simulator.IcarusSimulator.available": "True if both iverilog and vvp are on PATH.",
    "simulator.IcarusSimulator._design_dir": "Validate the design id and return its folder, refusing any path that escapes the workspace.",
    "simulator.IcarusSimulator.write_files": "Size-check and sandbox-check the code, then write design.sv and testbench.sv (adding a VCD dump if missing).",
    "simulator.IcarusSimulator.compile": "Run iverilog -g2012 -Wall with a 30 s timeout and a scrubbed environment.",
    "simulator.IcarusSimulator.run": "Run vvp with a clamped timeout (1-120 s) and an output-size cap; TIMEOUT on overrun.",
    "simulator.IcarusSimulator.parse_results": "Read the transcript and decide PASS / FAIL / ERROR from Passed:/Failed: counts, errors and ALL TESTS PASSED.",
    "simulator.IcarusSimulator.simulate": "Full path: validate id, sandbox scan, write, compile, run, parse.",
    "tools.mutation_sweep.main": "Inject each of the 27 known bugs into the built-in RTL, simulate with the built-in testbench, and print which were caught.",
    "uvm_templates._is_sequential": "True if the spec has a clock-like port (so the bundle drives a clock).",
    "uvm_templates._detect_clk_rst": "Find the clock and reset port names, if any.",
    "uvm_templates._sanitize_mod": "Make the module name a safe identifier for file and class names.",
    "uvm_templates._inputs": "Input ports of the spec.",
    "uvm_templates._outputs": "Output ports of the spec.",
    "uvm_templates._inouts": "Inout ports of the spec.",
    "uvm_templates._non_clk_rst_inputs": "Inputs other than clock and reset (the ones a sequence randomises).",
    "uvm_templates._width_decl": "SystemVerilog width declaration such as [3:0] (empty for 1 bit).",
    "uvm_templates._is_op_like": "True if a port looks like an opcode/select input.",
    "uvm_templates._find_op_port": "Find the opcode-like input, if any.",
    "uvm_templates._is_alu_like": "True if the design looks like an ALU (so the scoreboard uses an ALU model).",
    "uvm_templates._max_val": "Largest value for a given width.",
    "uvm_templates._port_type_decl": "Declaration type and width for a port in the interface.",
    "uvm_templates._find_port": "First port whose name matches one of a list.",
    "uvm_templates._gen_sequencer": "Generate the UVM sequencer class.",
    "uvm_templates._gen_driver": "Generate the UVM driver that applies items to the interface.",
    "uvm_templates._gen_monitor": "Generate the UVM monitor that samples the interface.",
    "uvm_templates._gen_agent": "Generate the agent wrapping sequencer, driver and monitor.",
    "uvm_templates._gen_scoreboard": "Generate the scoreboard that checks DUT outputs.",
    "uvm_templates._gen_coverage": "Generate the functional coverage collector.",
    "uvm_templates._gen_env": "Generate the environment class.",
    "uvm_templates._gen_test": "Generate the UVM test class.",
    "uvm_templates._gen_pkg": "Generate the package that includes all classes.",
    "uvm_templates._gen_tb_top": "Generate the top module that instantiates the DUT and interface.",
    "uvm_templates._gen_makefile": "Generate a Makefile for a commercial simulator (Questa style).",
    "uvm_templates._gen_filelist": "Generate the compile file list.",
    "vcd_parser.parse_vcd": "Read a VCD file (max 8 MB) and return up to 40 signals with up to 2000 value changes each, buses as hex, with truncation flags.",
    "synthesis.YosysSynthesizer.__init__": "Remember the workspace used for synthesis work folders.",
    "uvm_templates._gen_seq_item": "Generate the sequence item (one transaction).",
    "main._trust_proxy_headers": "True only when the deployment says it runs behind a trusted proxy (TRUST_PROXY_HEADERS); decides whether forwarded-for headers are believed for rate limiting.",
    "orchestrator._strip_comments_and_strings": "Blank out comments and string literals so counting checks and finding the design instance cannot be fooled by text inside them.",
    "llm_service.OpenCodeAppProvider.__init__": "Remember the OpenCode model, agent and timeout; no API key is needed because the local app's own login is used.",
    "llm_service.OpenCodeAppProvider._chat": "Run the OpenCode app in an empty temporary folder with a read-only agent and return the model's text, or raise a typed upstream error.",
    "simulator._policy_violations": "Combine the sandbox policy and the RTL-integrity rules for one design and testbench pair.",
    "simulator._finish_time_ns": "Read the final simulation time from the $finish message and convert it to nanoseconds.",
    "checks._category": "Normalise a test-type name to a short slug and fold types beyond the cap into 'other'.",
    "checks._clip": "Shorten a field to a maximum length so one verbose line cannot bloat the response.",
    "vcd_parser._role": "Classify a waveform signal (clock, reset, input, output, internal, testbench, task local, parameter) from its name, scope and the design's port list.",
    "orchestrator._second_opinion_message": "One-line timeline message for the second opinion: agrees, disagrees, or unavailable with the reason.",
    "llm_service.CloudflareProvider.__init__": "OpenAI-compatible client for one Cloudflare account (account-scoped base URL, Bearer token); no per-stage routing.",
    "llm_service.CloudflareProvider._extra_body": "Send a reasoning effort only to the gpt-oss models; every other Workers AI model gets a plain request.",
    "llm_service.NimProvider.__init__": "OpenAI-compatible client for the NVIDIA NIM hosted API; no per-stage routing.",
    "llm_service.NimProvider._extra_body": "No extra request fields: NIM is strict about unknown fields.",
    "llm_service.NimProvider._chat": "Remove the nim/ prefix from the model id, then send the chat request like any OpenAI-compatible provider.",
    "llm_service._nim_provider": "Return the NIM provider for the current key (rebuilt only if the key or address changes), or raise ModelNotAvailable when NVIDIA_NIM_API_KEY is not set.",
    "llm_service._cloudflare_provider": "Return the Cloudflare provider for the current credentials, or raise ModelNotAvailable when they are not set.",
    "models.RunRequest._user_spec_is_bounded": "Validate a user-confirmed specification with check_user_spec (plain identifiers, bounded sizes).",
    "model_catalog.is_valid_model_id": "True if a model id matches the safe pattern (no leading dash, no spaces or shell characters, at most 100 characters).",
    "model_catalog.is_cloudflare_id": "True for Cloudflare Workers AI ids (@cf/... or @hf/...).",
    "model_catalog.is_nim_id": "True for NVIDIA NIM menu ids (nim/...).",
    "model_catalog._get_cache": "Return a cached catalogue entry if it has not expired (and refresh was not asked for).",
    "model_catalog._put_cache": "Store a catalogue entry with its expiry time.",
    "model_catalog.clear_cache": "Forget every cached catalogue (used by tests).",
    "model_catalog._api_base": "Cloudflare API base URL (CLOUDFLARE_API_BASE, default the public v4 API).",
    "model_catalog.cloudflare_base_url": "The account-scoped OpenAI-compatible base URL for Workers AI.",
    "model_catalog._cloudflare_entry": "Build one Model-menu entry for a Workers AI model.",
    "model_catalog.static_cloudflare_models": "Suggested Workers AI models, used only when the live catalogue cannot be read.",
    "model_catalog._urlopen": "Open an HTTPS request with the certifi certificate bundle (some Python builds have none).",
    'model_catalog._search_cloudflare': "Read up to 5 pages of Cloudflare's model search and keep the text-generation models.",
    "model_catalog._nim_entry": "Build one Model-menu entry for a NIM model (id prefixed nim/).",
    "model_catalog.static_nim_models": "The NIM models that answered quickly in a live test, used when the live list cannot be read.",
    'model_catalog._search_nim': "Read NVIDIA's /models list with the key and keep the chat models.",
    "mutation._matching_paren": "Index of the parenthesis that closes the one at a given position, or -1.",
    "mutation._line_of": "Line number (1-based) of a character offset in the code.",
    'mutation.apply_mutant': "Return the code with one mutant's replacement applied.",
    "timing._env": "Scrubbed environment for Yosys and OpenSTA, plus HOME (the shims and the WebAssembly cache live there).",
    "timing._run": "Run a tool in the work folder with a time limit, no input and the scrubbed environment.",
    "timing._map_with_yosys": "Run Yosys: read, apply parameter overrides, proc and tribuf, flatten and synthesize, map to sky130 cells, write statistics and the netlist.",
    "timing._constraints": "OpenSTA constraints: one clock per clock port at the target period (asynchronous groups for several clocks) or a virtual clock for combinational designs, zero I/O delays.",
    "timing.timing_message": "One-line timeline message: meets or misses the target with slack, fmax and area, or the reason timing is not available.",
    "tools.verify_mapping.declared_modules": "Names of all modules declared in an RTL file.",
    'tools.verify_mapping.liberty_areas': "Read every sky130 cell's area from the liberty file.",
    "tools.verify_mapping.netlist_totals": "Recompute area and cell count from the written netlist and the liberty areas.",
    'tools.verify_mapping.verdict': "Read the Passed/Failed numbers from a simulation's output.",
    "tools.verify_mapping.simulate": "Compile and run a set of Verilog files with Icarus and return the Passed/Failed numbers (or the problem).",
    "tools.verify_mapping.collect": "List the designs to check: every saved evaluation design with its testbench plus the built-in designs.",
    "tools.verify_mapping.main": "Run the three checks on every design and print OK, REFUSED (with reason) or FAIL; non-zero exit on any failure.",
    "tools.preflight.record": "Store and print one OK / WARN / FAIL line.",
    "tools.preflight.run": "Run a command with a time limit and return its exit code and output.",
    "tools.preflight.http_ok": "True if a local URL answers with HTTP 2xx.",
    "tools.preflight.check_simulator": "Check Icarus Verilog is on the PATH and is version 12.",
    "tools.preflight.check_yosys": "Check Yosys is installed and report its version.",
    "tools.preflight.check_timing": "Check OpenSTA and the sky130 library are present for the timing stage.",
    "tools.preflight.check_offline_pipeline": "Run the offline demo pipeline once to prove the offline rung of the fallback ladder works.",
    'tools.preflight.check_live_config': "Check the live set-up: LLM_PROVIDER, the opencode command, and that the chosen model is in the app's list.",
    "tools.preflight.check_live_call": "With --live, make one tiny model call and report how long it took.",
    "tools.preflight.check_servers": "Check whether the backend (port 8000) and frontend (port 5173) are already running.",
    "tools.preflight.check_storage": "Count saved projects in projects.db with a read-only connection.",
    "tools.preflight.check_evidence": "Check that recorded live results exist in evaluation/results.jsonl (the saved-results rung).",
    "tools.preflight.main": "Run every check and print which rungs of the fallback ladder (live, offline, saved) are ready.",
    "tools.evaluate_live.load_done": "Read the finished records from results.jsonl (the last record for each prompt id wins).",
    "tools.evaluate_live.run_one": "Run one evaluation prompt through the real pipeline in a temporary workspace and build its record.",
    "tools.evaluate_live.summarise": "Build summary.md: first-attempt passes, passes after repair, failures, strength, toggle and timing per prompt.",
    "tools.evaluate_live.main": "Command line: run missing prompts (or --only, --redo), rebuild the summary, or backfill/retime saved designs without a model call.",
    "evaluation.independent.run.main": "Simulate every saved evaluation design against its hand-written reference testbench and report mismatches.",
    "evaluation.independent.strength.run_mutant": "Simulate one mutant against a reference testbench: killed, survived or invalid.",
    "evaluation.independent.strength.sweep": "Run every mutant of one saved design against its reference (in parallel) and count the outcomes.",
    "evaluation.independent.strength.main": "Print, for each reference, how many injected bugs it caught and which survived.",
}

FILES = ["main.py", "orchestrator.py", "llm_service.py", "simulator.py", "models.py",
         "linter.py", "cov_metrics.py", "checks.py", "vcd_parser.py", "schematic.py", "synthesis.py",
         "db.py", "offline_designs.py", "cleanup.py", "openroad.py", "uvm_templates.py",
         "model_catalog.py", "mutation.py", "timing.py", "equivalence.py",
         "tools/mutation_sweep.py", "tools/verify_mapping.py", "tools/preflight.py", "tools/evaluate_live.py",
         "evaluation/independent/run.py", "evaluation/independent/strength.py"]


def tex(s: str) -> str:
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}",
           "<": r"\textless{}", ">": r"\textgreater{}", "\u2192": r"$\rightarrow$"}
    return "".join(rep.get(c, c) for c in s)


def first_line(doc):
    return (doc or "").strip().split("\n")[0].strip()


rows = []
missing = []
for rel in FILES:
    path = BACKEND / rel
    mod = rel[:-3].replace("/", ".")
    tree = ast.parse(path.read_text())
    for node in tree.body:
        items = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    items.append((f"{node.name}.{m.name}", m))
        for name, fn in items:
            key = f"{mod}.{name}"
            d = first_line(ast.get_docstring(fn)) or DESC.get(key, "")
            if not d:
                missing.append(key)
            rows.append((rel, name, d))

out = [r"\begin{longtable}{@{}p{2.8cm}>{\raggedright\arraybackslash}p{4.6cm}p{7.9cm}@{}}",
       r"\toprule \textbf{File} & \textbf{Function} & \textbf{What it does} \\ \midrule \endhead",
       r"\bottomrule \endfoot"]
last = None
for rel, name, d in rows:
    f = ("\\nolinkurl{" + rel + "}") if rel != last else ""
    last = rel
    out.append(rf"{{\small {f}}} & \texttt{{\small {tex(name).replace(chr(46), chr(46) + chr(92) + "allowbreak ").replace(chr(92)+chr(95), chr(92)+chr(95)+chr(92)+"allowbreak{}")}}} & {tex(d)} \\")
out.append(r"\end{longtable}")
(pathlib.Path(__file__).parent / "function_index.tex").write_text("\n".join(out) + "\n")
print(f"{len(rows)} functions written; missing descriptions: {missing}")
