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
GEMINI_API_KEY=... python extract.py data
python s2g.py eval data                          # -> results.md, results.json
python -m pytest -q
```

## Results

See [results.md](results.md).
