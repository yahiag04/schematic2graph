"""Schematic-to-Graph: KiCad netlist / VLM prediction -> component graph, and metrics vs ground truth.

Usage: python s2g.py eval data/      (expects data/<project>/netlist.xml and pred.json)
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from itertools import combinations
from pathlib import Path

import networkx as nx

# shortcut: power nets detected by name; upgrade by reading power-symbol pintypes from the netlist
POWER = re.compile(r"(.*GND.*|[+-].*|V(CC|DD|SS|EE|BUS|BAT|IN|SYS|CORE|REF)\w*|\d+V\w*)", re.I)
KINDS = ("wire", "label", "power")  # how a GT net is realised on the drawing, easiest evidence first


def norm_ref(ref):
    ref = ref.strip().upper()
    m = re.fullmatch(r"([A-Z]+\d+)[A-Z]", ref)  # unit suffix: U1A -> U1
    return m.group(1) if m else ref


def norm_value(v):
    return re.sub(r"\s|[Ωω]|ohms?", "", v.lower()).replace("µ", "u").replace("μ", "u")


def net_kind(name):
    n = name.lstrip("/")
    if POWER.fullmatch(n):
        return "power"
    if not n or name.startswith(("Net-(", "unconnected-")):
        return "wire"
    return "label"


def load_gt(path):
    """KiCad XML netlist -> components {ref: value}, nets [(name, {refs})], pins per ref."""
    root = ET.parse(path).getroot()
    comps = {norm_ref(c.get("ref")): c.findtext("value", "") for c in root.iter("comp")}
    nets, pins = [], Counter()
    for net in root.iter("net"):
        refs = [norm_ref(n.get("ref")) for n in net.iter("node")]
        pins.update(refs)
        nets.append((net.get("name", ""), set(refs)))
    return comps, nets, pins


def load_pred(path):
    d = json.loads(Path(path).read_text())
    comps = {norm_ref(c["ref"]): c.get("value", "") for c in d["components"] if not c["ref"].startswith("#")}
    nets = [(n.get("name", ""), {norm_ref(p["ref"]) for p in n["pins"] if not p["ref"].startswith("#")}) for n in d["nets"]]
    return comps, nets


def graph(comps, nets, skip_power=False):
    """Nodes = components, edge = two components on the same net (edge attr: list of nets)."""
    g = nx.Graph()
    g.add_nodes_from(comps)
    for name, refs in nets:
        if skip_power and net_kind(name) == "power":
            continue
        for a, b in combinations(sorted(refs), 2):
            if g.has_edge(a, b):
                g[a][b]["nets"].append(name)
            else:
                g.add_edge(a, b, nets=[name])
    return g


def edges(g):
    return {frozenset(e) for e in g.edges}


def evaluate(gt_comps, gt_nets, gt_pins, pr_comps, pr_nets):
    """Raw counts (so projects can be micro-averaged)."""
    gt_g, pr_g = graph(gt_comps, gt_nets), graph(pr_comps, pr_nets)
    gt_e, pr_e = edges(gt_g), edges(pr_g)
    gt_np, pr_np = edges(graph(gt_comps, gt_nets, True)), edges(graph(pr_comps, pr_nets, True))
    matched = gt_comps.keys() & pr_comps.keys()
    r = {
        "comp": [len(matched), len(gt_comps), len(pr_comps)],
        "value": [sum(norm_value(gt_comps[k]) == norm_value(pr_comps[k]) for k in matched), len(matched)],
        "edge": [len(gt_e & pr_e), len(gt_e), len(pr_e)],
        "edge_nopower": [len(gt_np & pr_np), len(gt_np), len(pr_np)],
    }
    # error analysis: recall of GT edges by how the connection is drawn and by endpoint pin count
    for e in gt_e:
        kind = min((net_kind(n) for n in gt_g.edges[tuple(e)]["nets"]), key=KINDS.index)
        multipin = "multipin" if max(gt_pins[x] for x in e) >= 4 else "2-3pin"
        for cat in (f"via_{kind}", multipin):
            hit_total = r.setdefault(cat, [0, 0])
            hit_total[0] += e in pr_e
            hit_total[1] += 1
    missed = sorted(gt_comps.keys() - pr_comps.keys())
    r["missed_comps"], r["hallucinated_comps"] = missed, sorted(pr_comps.keys() - gt_comps.keys())
    return r


def prf(tp, n_gt, n_pred):
    p, rec = tp / n_pred if n_pred else 0.0, tp / n_gt if n_gt else 0.0
    return p, rec, 2 * p * rec / (p + rec) if p + rec else 0.0


def main(data_dir):
    rows, total = [], {}
    for d in sorted(Path(data_dir).iterdir()):
        if not (d / "netlist.xml").exists() or not (d / "pred.json").exists():
            continue
        gt = load_gt(d / "netlist.xml")
        if len(gt[0]) < 3:  # templates / empty sheets
            continue
        r = evaluate(*gt, *load_pred(d / "pred.json"))
        rows.append((d.name, r))
        for k, v in r.items():
            if not k.endswith("_comps"):
                total[k] = [a + b for a, b in zip(total.get(k, [0] * len(v)), v)]

    out = ["| project | comps | comp R | edge P | edge R | edge F1 | F1 no-power |", "|---|---|---|---|---|---|---|"]
    for name, r in rows + [("**MICRO TOTAL**", total)]:
        _, cr, _ = prf(*r["comp"])
        ep, er, ef = prf(*r["edge"])
        out.append(f"| {name} | {r['comp'][1]} | {cr:.2f} | {ep:.2f} | {er:.2f} | {ef:.2f} | {prf(*r['edge_nopower'])[2]:.2f} |")
    out += ["", f"Projects: {len(rows)}. Value accuracy on matched components: "
            f"{total['value'][0] / max(total['value'][1], 1):.2f}", "",
            "Edge recall by category (error analysis):", "", "| category | recall | GT edges |", "|---|---|---|"]
    for cat in ("via_wire", "via_label", "via_power", "2-3pin", "multipin"):
        if cat in total:
            hit, n = total[cat]
            out.append(f"| {cat} | {hit / n:.2f} | {n} |")
    text = "\n".join(out)
    print(text)
    Path("results.md").write_text(text + "\n")
    Path("results.json").write_text(json.dumps({n: r for n, r in rows} | {"_total": total}, indent=1))


if __name__ == "__main__":
    main(sys.argv[2] if len(sys.argv) > 2 else "data")
