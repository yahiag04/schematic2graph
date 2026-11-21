# Schematic-to-Graph

Extract circuit topology from a schematic **PDF** with a VLM and score it against the **real netlist** exported by KiCad.

```
projects.txt ──(GitHub Actions, kicad/kicad:10.0)──► schematic.pdf + netlist.xml (ground truth)
schematic.pdf ──(Gemini, JSON-schema constrained)──► pred.json
netlist.xml + pred.json ──(networkx)──► component recall, edge P/R/F1, error analysis
```

- **Data**: 25 small open-source KiCad projects from GitHub (flat: one `.kicad_sch`), pinned to a commit
  (`find_projects.py` → `projects.txt`).
- **Ground truth**: `kicad-cli sch export netlist --format kicadxml`, turned into a graph:
  nodes = components, edge = two components sharing a net.
- **Extraction**: `extract.py` sends the PDF to Gemini with a JSON Schema (components + nets with pins);
  output validated with `jsonschema` before use.
- **Metrics** (`s2g.py`): component recall, value accuracy, edge P/R/F1 — also **without power nets**
  (GND/VCC become cliques that dominate the edge count) — and edge recall split by
  *how the connection is drawn* (wire / net label / power symbol) and *multi-pin parts* (≥4 pins, ICs/connectors).

## Run

```bash
gh workflow run export && gh run watch          # PDFs + netlists via kicad-cli
gh run download -n data -D data
set -a; . ./.env; set +a                         # GEMINI_API_KEY=...
SSL_CERT_FILE=$(python3 -m certifi) python extract.py data   # certifi: python.org builds ship no CA bundle
python s2g.py eval data                          # -> results.md, results.json
python -m pytest -q
```

## Results (v1, `gemini-3.8-flash`, 10 of 25 projects, 136 components, 385 GT edges)

| metric | value |
|---|---|
| component recall / precision | 1.00 / 1.00 |
| value accuracy (matched comps) | 0.95 |
| edge precision / recall / **F1** | 0.96 / 0.91 / **0.94** |
| edge F1 without power nets | 0.92 |

Edge recall by how the connection is drawn: wire 0.92 · net label 0.95 · power symbol 0.90;
by endpoint: 2–3-pin parts 0.91 · multi-pin parts (≥4 pins) 0.92. Per-project table: [results.md](results.md).

### Error analysis

Finding components is solved here; the errors are **in pin-to-net attribution**:

- **One wrong pin, many wrong edges.** In `lm386_amp` the model put C1 on GND instead of C2: one pin error
  gives 7 missed + 7 fake edges, because GND is a clique. Edge F1 penalises big nets quadratically, so the next
  metric to add is net-level or pin-level scoring.
- **Look-alike parts get swapped.** `TP4056` has five identical 1-pin connectors (`Conn_01x01`). The model mixed up
  J4/J5 and J2/J5, so every edge landed on the wrong connector. It also returned the label text next to each pad
  (`GND`, `OUT+`) as the value: that explains 5 of the 7 value "errors".
- **Labels that look like power.** In `sega-gun` a lowercase local label `gnd` (not a power symbol) loses J2: 8 edges.
- **Dense drawn wiring** (transistor bias network in `BoBoBaSs84`, unnamed nets): it misses junctions, recall 0.83.
- Surprisingly, net labels (0.95) are **not** harder than drawn wires (0.92), and ICs/connectors are not worse than
  2-pin parts. The weak spot is ambiguity (identical parts, crowded nodes), not the number of pins.

Limits: 10 projects (≈2 min per schematic on the free tier), one run at temperature 0, small flat schematics only.
