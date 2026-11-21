"""Pick small, flat KiCad projects from GitHub: exactly one .kicad_sch, 5-120 KB. Writes projects.txt."""
import json, subprocess, sys

def gh(path):
    return json.loads(subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout)

want = int(sys.argv[1]) if len(sys.argv) > 1 else 30
out, seen = [], set()
for q in ["topic:kicad size:<3000", "topic:kicad-project size:<3000", "kicad pcb in:description size:<3000"]:
    for page in (1, 2, 3):
        for r in gh(f"search/repositories?q={q.replace(' ', '+')}&sort=stars&per_page=50&page={page}")["items"]:
            name = r["full_name"]
            if name in seen or len(out) >= want:
                continue
            seen.add(name)
            try:
                sha = gh(f"repos/{name}/commits/{r['default_branch']}")["sha"]
                tree = gh(f"repos/{name}/git/trees/{sha}?recursive=1")
            except subprocess.CalledProcessError:
                continue
            sch = [t for t in tree["tree"] if t["path"].endswith(".kicad_sch")]
            if len(sch) == 1 and 5_000 < sch[0]["size"] < 120_000:
                out.append(f"{name} {sha} {sch[0]['path']}")
                print(out[-1], flush=True)
open("projects.txt", "w").write("\n".join(out) + "\n")
