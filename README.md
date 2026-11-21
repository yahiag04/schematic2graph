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

## Results (v1, `gemini-3.8-flash`, 25 projects, 362 components, 1358 GT edges)

| metric | value |
|---|---|
| component recall / precision | 0.97 / 1.00 |
| value accuracy (matched comps) | 0.93 |
| edge precision / recall / **F1** | 0.95 / 0.93 / **0.94** |
| edge F1 without power nets | 0.93 |

Edge recall by how the connection is drawn: wire 0.89 · net label 0.91 · power symbol 0.95;
by endpoint: 2–3-pin parts 0.91 · multi-pin parts (≥4 pins) 0.96. Per-project table: [results.md](results.md).
Zero hallucinated components; 13 of 25 schematics come out with perfect edge F1.

### Error analysis

Finding components is almost solved. The errors are in **small parts** and in **pin-to-net attribution**:

- **1-pin connectors/pads are the weak spot.** In `miniRGBii` the model skips all 9 output pads
  (`Conn_01x01`): it sees them as wire ends, not components (component recall 0.68, all misses). In `TP4056` five
  identical pads get swapped (J4↔J5, J2↔J5), and it returns the text next to each pad (`GND`, `OUT+`) as the value.
- **One wrong pin, many wrong edges.** In `lm386_amp` it puts C1 on GND instead of C2: one pin error gives
  7 missed + 7 fake edges (GND is a clique). Edge F1 penalises big nets quadratically: pin-level scoring is the next metric.
- **It "cleans up" the circuit.** In `ESP8266-IMU-Node` it connects U1↔U2 directly on SDA/SCL and skips the series
  resistors R8/R9: it reads the label name, not the topology.
- **Dense drawn wiring / unnamed nets** (`BoBoBaSs84` transistor bias, `tiny_sensor`): missed junctions, recall ~0.8.
- Drawn wires (0.89) and net labels (0.91) are the hardest. Power symbols are the easiest (0.95), and ICs are **easier**
  than 2-pin parts (0.96 vs 0.91), because pins are named and drawn far apart.

**Metric pitfall I found on the way.** Detecting power nets by name breaks when the two sides disagree. In
`tiny_sensor` the 3V3 rail is `Net-(D1-A)` in the netlist but `3V3` for the model, so the "no power" F1 dropped to 0.26
for a rail the model actually got right. Fix: drop a power edge from both sides if either side calls it power.

Limits: one run at temperature 0, small flat schematics only, ~2 min per schematic on the free tier.
