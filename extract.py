"""Schematic PDF -> structured JSON (components + nets) with Gemini, validated against SCHEMA.

Usage: GEMINI_API_KEY=... python extract.py data/ [--model gemini-3.8-flash] [--force]
Writes data/<project>/pred.json (or pred.error.txt on failure).
"""
import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema

SCHEMA = {
    "type": "object",
    "properties": {
        "components": {"type": "array", "items": {"type": "object", "properties": {
            "ref": {"type": "string", "description": "reference designator, e.g. R1, C3, U2"},
            "value": {"type": "string", "description": "value or part number, e.g. 10k, 100nF, LM7805"},
            "kind": {"type": "string", "description": "resistor, capacitor, IC, connector, diode, ..."},
        }, "required": ["ref", "value"]}},
        "nets": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "description": "net label or power symbol text (GND, +3V3, SDA); empty string if unnamed"},
            "pins": {"type": "array", "items": {"type": "object", "properties": {
                "ref": {"type": "string"},
                "pin": {"type": "string", "description": "pin number or name"},
            }, "required": ["ref", "pin"]}},
        }, "required": ["name", "pins"]}},
    },
    "required": ["components", "nets"],
}

PROMPT = """You are reading an electronic schematic (exported from KiCad).
Extract the circuit netlist:
1. components: every real component with its reference designator and value. Do NOT list power symbols,
   PWR_FLAG, net labels or no-connect markers as components.
2. nets: every electrical net with ALL component pins on it. Rules:
   - pins joined by wires (including through junction dots) are on the same net;
   - net labels / global labels with the same text are the SAME net even if not wired together;
   - every power symbol with the same name (GND, +5V, +3V3, ...) is the same net;
   - each net appears once; multi-unit parts (U1A, U1B) use the base reference (U1).
Be exhaustive: include nets that connect only two pins."""


def call_gemini(pdf, model, key, retries=5):
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf).decode()}},
            {"text": PROMPT},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseJsonSchema": SCHEMA},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                out = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503) or attempt == retries - 1:
                raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:500]}") from None
            time.sleep(30 * (attempt + 1))  # free-tier rate limit
    parts = out["candidates"][0]["content"]["parts"]
    return json.loads("".join(p["text"] for p in parts if "text" in p and not p.get("thought")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", default="data")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    key = os.environ["GEMINI_API_KEY"]
    for d in sorted(p for p in Path(a.data).iterdir() if (p / "schematic.pdf").exists()):
        if (d / "pred.json").exists() and not a.force:
            continue
        t = time.time()
        try:
            pred = call_gemini((d / "schematic.pdf").read_bytes(), a.model, key)
            jsonschema.validate(pred, SCHEMA)  # trust boundary: model output
        except Exception as e:  # one bad project must not stop the batch
            (d / "pred.error.txt").write_text(repr(e))
            print(f"FAIL {d.name}: {e!r}"[:300])
            continue
        (d / "pred.json").write_text(json.dumps(pred, indent=1))
        print(f"ok   {d.name}: {len(pred['components'])} comps, {len(pred['nets'])} nets, {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
