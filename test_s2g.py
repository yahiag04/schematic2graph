import json
from s2g import evaluate, load_gt, load_pred, net_kind, prf

NETLIST = """<export version="E"><components>
<comp ref="R1"><value>10k</value></comp><comp ref="C1"><value>100nF</value></comp>
<comp ref="U1"><value>LM7805</value></comp><comp ref="D1"><value>LED</value></comp>
</components><nets>
<net code="1" name="GND"><node ref="C1" pin="2"/><node ref="U1" pin="2"/><node ref="D1" pin="1"/></net>
<net code="2" name="/VSENSE"><node ref="R1" pin="1"/><node ref="U1" pin="3"/></net>
<net code="3" name="Net-(D1-A)"><node ref="R1" pin="2"/><node ref="D1" pin="2"/></net>
<net code="4" name="unconnected-(U1-Pad4)"><node ref="U1" pin="4"/></net>
<net code="5" name="+5V"><node ref="C1" pin="1"/><node ref="U1" pin="1"/></net>
</nets></export>"""

PRED = {"components": [{"ref": "R1", "value": "10 kΩ"}, {"ref": "C1", "value": "100nF"},
                       {"ref": "U1A", "value": "LM7805"}, {"ref": "R9", "value": "1k"}, {"ref": "#PWR01", "value": "GND"}],
        "nets": [{"name": "GND", "pins": [{"ref": "C1", "pin": "2"}, {"ref": "U1A", "pin": "2"}, {"ref": "#PWR01", "pin": "1"}]},
                 {"name": "", "pins": [{"ref": "R1", "pin": "1"}, {"ref": "U1", "pin": "3"}, {"ref": "R9", "pin": "1"}]}]}


def test_end_to_end(tmp_path):
    (tmp_path / "n.xml").write_text(NETLIST)
    (tmp_path / "p.json").write_text(json.dumps(PRED))
    r = evaluate(*load_gt(tmp_path / "n.xml"), *load_pred(tmp_path / "p.json"))
    assert r["comp"] == [3, 4, 3 + 1]          # D1 missed, R9 hallucinated, U1A->U1, #PWR dropped
    assert r["value"] == [3, 3]                # "10 kΩ" == "10k"
    # GT edges: GND clique {C1,U1,D1}=3, R1-U1, R1-D1, C1-U1 already counted -> 5; pred: C1-U1, R1-U1, R1-R9, U1-R9
    assert r["edge"] == [2, 5, 4]
    assert r["edge_nopower"] == [1, 2, 3]      # only R1-U1 (label) and R1-D1 (wire) are signal edges in GT
    assert r["via_label"] == [1, 1] and r["via_wire"] == [0, 1] and r["via_power"] == [1, 3]
    assert r["multipin"] == [2, 3]             # edges touching U1 (4 pins): C1, D1, R1
    assert r["missed_comps"] == ["D1"] and r["hallucinated_comps"] == ["R9"]


def test_helpers():
    assert [net_kind(n) for n in ("GND", "+3V3", "/VBUS", "/SDA", "Net-(R1-Pad1)", "")] == \
        ["power", "power", "power", "label", "wire", "wire"]
    assert prf(2, 4, 2) == (1.0, 0.5, 2 / 3)
