# SiliconScribe UI redesign: design plan

Inputs: the ui-ux-pro-max design-system query ("developer tool, hardware verification, data-dense"),
the frontend-design skill, Anthropic's *Prompting for frontend aesthetics* cookbook, and `wireframes.html`.

## Direction: "lab instrument"
A calm, neutral workspace you can leave open all day, with the two "instrument screens" (code editor and
waveform) kept dark in both themes, like a scope display on a bench. Minimal by restraint, not by
removing information: data-dense where engineers need data (tables, waveforms), quiet everywhere else.

What we remove (the "AI template" tells): glassmorphism and backdrop blur, gradient text, glowing
indigo/purple buttons, chat bubbles for a system log, one radius on everything, decorative entrance
animations, the generic Outfit font, CDN-loaded icon fonts.

## Tokens
- **Colour (5 named values):** *Bench* `#F6F7F8` (light page) / `#17191C` (dark page), *Panel* `#FFFFFF` / `#1F2226`,
  *Ink* `#1C2024` / `#E7E9EC`, *Scope* `#0D1014` (code and waveform screens, both themes), and one accent:
  **CH1 yellow** `#F2C230`, the colour of channel 1 on a bench oscilloscope, used only for the primary action,
  focus ring, active tab marker and the cursor in the waveform (dark text on it; a darker `#7A5C00` when the accent
  must be text on white). Semantic colours stay separate and always come with an icon or word:
  pass `#1E7F45`, fail `#C2362F`, warning `#B45309` (orange, so it never reads as the yellow accent).
  All text pairs verified at 4.5:1 (axe-core, both themes).
- **Type:** IBM Plex Sans for UI, IBM Plex Mono for code, numbers and signal names (engineering heritage,
  not a default font; self-hosted so the demo works offline). Weights 400 / 500 / 600. Scale 12 / 13 / 14 / 16 / 20 / 28.
  Tabular figures for every number.
- **Shape:** 1 px borders, radius 6 px (controls) and 8 px (cards), no shadows except floating layers (menus, drawer).
- **Spacing:** 4 px grid (4, 8, 12, 16, 24, 32).
- **Motion:** two durations (120 ms, 200 ms), ease-out in, faster out. Used only for cause-and-effect:
  tab content cross-fade, timeline step completion, menu open. `prefers-reduced-motion` turns all of it off.

## Layout
Top bar (48 px): wordmark, live/offline status, Projects, Export UVM, Re-run, theme switch.
Sidebar (320 px): prompt, Generate (the only primary button), examples, model and clock target, then the
run timeline (one row per pipeline event, time per row, the current row live) and the design explanation.
Workspace: tabs **Design · Results · Test cases · Waveform · Schematic**, each full height. Generate switches to
Design; a finished run switches to Results. No Expand button needed.

## Behaviour
- Theme: follows the system, with a light / dark / system switch remembered per browser.
- Keyboard: Cmd/Ctrl+Enter generates, arrow keys move between tabs, `[` `]` jump between failures in the waveform.
- Empty states teach the flow; errors say what happened and what to do.

## Quality gates (must pass before the redesign is done)
1. All existing behaviour tests pass (updated only where structure changed).
2. axe-core: zero violations in light and dark, passing and failing run, every tab.
3. Production build; main bundle not larger than today.
4. Real-browser screenshots of every wireframe state, compared against the wireframes.

## Review against the brief (frontend-design calibration), and what changed
| Draft choice | Why it read as a default | Revised to |
|---|---|---|
| Copper accent `#B4541F` / `#E08A52` | Too close to the warm-clay / terracotta accent that generated designs cluster around | CH1 yellow from bench oscilloscopes: grounded in the engineer's own instruments, rare in web products |
| ALL-CAPS labels above sidebar sections ("DESCRIBE THE HARDWARE") | Tracked-out eyebrow labels are template chrome | Sentence-case field labels only where a control needs one ("Describe the block") |
| Verdict strip written as "57 / 57 checks · 0 repairs · 7 of 8 …" | Meta strings joined with middle dots are a tell | Separate stat blocks, each a number with a plain label underneath |
| Monospace for every small label | A tell when it is decoration | Mono only where the content is code-like: source, signal names, values, times |
| Identical cards for every result | The SaaS card kit | Hierarchy by weight: one verdict band, then two quiet sections, log folded away |

Where the boldness goes: the verdict band (PASS or FAIL set large in Plex Sans 600, with the stat blocks) and the
single CH1-yellow accent. Everything else is quiet and disciplined.
