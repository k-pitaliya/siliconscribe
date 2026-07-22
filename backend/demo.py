"""Narrated CLI demo: drives the live SSE pipeline and pretty-prints each stage."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "r": "\033[31m",
     "y": "\033[33m", "c": "\033[36m", "m": "\033[35m", "x": "\033[0m"}

ICON = {"start": "▶", "intent": "🧠", "rtl": "📝", "testbench": "🧪",
        "explanation": "💡", "simulate": "⚙", "fixing": "🔧", "fix": "🩹",
        "done": "🏁", "error": "✖"}


def stream(prompt, max_iterations=3):
    body = json.dumps({"prompt": prompt, "max_iterations": max_iterations}).encode()
    req = urllib.request.Request(f"{BASE}/api/design/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    buf = ""
    final = None
    with urllib.request.urlopen(req) as resp:
        for raw in resp:
            buf += raw.decode()
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                line = next((l for l in frame.split("\n") if l.startswith("data:")), None)
                if not line:
                    continue
                e = json.loads(line[5:].strip())
                stage = e["stage"]
                icon = ICON.get(stage, "•")
                color = C["g"] if e.get("status") == "PASS" else C["r"] if e.get("status") in ("FAIL", "ERROR") else C["c"]
                it = f" [iter {e['iteration']}]" if e.get("iteration") is not None else ""
                print(f"  {icon} {color}{stage:11}{C['x']}{C['dim']}{it}{C['x']}  {e.get('message','')}")
                if stage == "done":
                    final = e["response"]
    return final


def banner(t):
    print(f"\n{C['b']}{C['m']}{'='*70}{C['x']}")
    print(f"{C['b']}{C['m']}  {t}{C['x']}")
    print(f"{C['b']}{C['m']}{'='*70}{C['x']}\n")


def show_code(label, code, n=14):
    print(f"\n{C['y']}── {label} ──{C['x']}")
    for ln in code.strip().splitlines()[:n]:
        print(f"  {C['dim']}│{C['x']} {ln}")


def render_wave(wf, width=48):
    print(f"\n{C['y']}── Waveform (parsed from VCD, {wf['end_time']} {wf['timescale']}) ──{C['x']}")
    end = max(wf["end_time"], 1)
    for s in wf["signals"][:8]:
        cells = []
        for i in range(width):
            t = i / width * end
            v = "x"
            for ch in s["wave"]:
                if ch["t"] <= t:
                    v = ch["v"]
                else:
                    break
            if s["width"] == 1:
                cells.append("▔" if v == "1" else "▁" if v == "0" else "▒")
            else:
                cells.append(v[0] if v not in ("x", "z") else "▒")
        name = (s["name"][:10]).ljust(11)
        print(f"  {C['c']}{name}{C['x']} {C['g']}{''.join(cells)}{C['x']}")


def show_schematic(sch):
    print(f"\n{C['y']}── Schematic: {sch['module_name']} ──{C['x']}")
    ins = [f"{p['name']}[{p['width']-1}:0]" if p['width'] > 1 else p['name'] for p in sch['inputs']]
    outs = [f"{p['name']}[{p['width']-1}:0]" if p['width'] > 1 else p['name'] for p in sch['outputs']]
    rows = max(len(ins), len(outs))
    print(f"  {' '*16}┌{'─'*(len(sch['module_name'])+4)}┐")
    for i in range(rows):
        li = ins[i] if i < len(ins) else ""
        ro = outs[i] if i < len(outs) else ""
        mid = f" {sch['module_name']} " if i == rows // 2 else " " * (len(sch['module_name']) + 2)
        print(f"  {C['c']}{li:>14}{C['x']} ─┤{mid}├─ {C['g']}{ro}{C['x']}")
    print(f"  {' '*16}└{'─'*(len(sch['module_name'])+4)}┘")


# ── DEMO 1: self-correction loop ──────────────────────────────────────────
banner("DEMO 1  —  Self-correction loop  (prompt: \"a buggy 4-bit counter\")")
final = stream("Design a buggy 4-bit counter")
print(f"\n  {C['b']}Result: {C['g'] if final['status']=='PASS' else C['r']}{final['status']}{C['x']}"
      f"  after {C['b']}{final['iterations']}{C['x']} self-correction iteration(s)")
print(f"\n{C['y']}── Iteration timeline ──{C['x']}")
for h in final["iteration_history"]:
    col = C["g"] if h["status"] == "PASS" else C["r"]
    print(f"  #{h['iteration']}  {col}{h['status']:6}{C['x']}  {h['pass_count']}/{h['pass_count']+h['fail_count']} pass"
          f"   {C['dim']}{h['fix_summary']}{C['x']}")
show_code(f"Final (fixed) RTL — {final['rtl_spec']['module_name']}", final["rtl_code"])

# ── DEMO 2: clean ALU with waveform + schematic ───────────────────────────
banner("DEMO 2  —  Full flow  (prompt: \"4-bit ALU with add sub and or xor\")")
final = stream("Design a 4-bit ALU with add sub and or xor and overflow detection")
r = final["result"]
print(f"\n  {C['b']}Result: {C['g']}{final['status']}{C['x']}  "
      f"{r['pass_count']}/{r['test_count']} tests   coverage: {r['coverage']['pass_rate']}%")
print(f"  {C['dim']}{final['explanation']}{C['x']}")
show_code(f"Generated RTL — {final['rtl_spec']['module_name']}", final["rtl_code"], 16)
render_wave(final["waveform"])
show_schematic(final["schematic"])
print()
