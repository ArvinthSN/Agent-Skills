#!/usr/bin/env python3
"""Read-only Git change inventory with optional baseline and heuristic secret scan."""
import argparse, json, re, subprocess, sys
from pathlib import Path
SENSITIVE_NAMES = {".env", ".env.local", "secrets.json", "credentials.json", "id_rsa"}
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*["\']?([A-Za-z0-9_./+=:-]{8,})'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]
def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
def root_for(start):
    r=git(start.resolve(), "rev-parse", "--show-toplevel")
    if r.returncode: raise RuntimeError("Not inside a Git repository.")
    return Path(r.stdout.strip()).resolve()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--baseline", action="store_true", help="save current status as baseline")
    p.add_argument("--json", action="store_true", help="print JSON output")
    a=p.parse_args()
    try: root=root_for(a.root)
    except RuntimeError as e: print(str(e), file=sys.stderr); return 2
    status=git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode: print(status.stderr, file=sys.stderr); return 2
    rows=[]
    for line in status.stdout.splitlines():
        code, path = line[:2], line[3:].strip().strip('"')
        paths=[x.strip().strip('"') for x in path.split(" -> ")]
        rows.append({"status":code,"path":path,"sensitive_name":any(Path(x).name in SENSITIVE_NAMES for x in paths)})
    state_dir=root/".agentguard"; state_dir.mkdir(exist_ok=True)
    baseline_file=state_dir/"baseline.json"
    if a.baseline:
        head=git(root,"rev-parse","HEAD").stdout.strip()
        baseline_file.write_text(json.dumps({"head":head,"status":rows},indent=2)+"\n",encoding="utf-8")
        result={"baseline_captured":True,"repository":str(root),"changes":rows,"findings":[]}
    else:
        findings=[{"type":"sensitive-filename","path":r["path"]} for r in rows if r["sensitive_name"]]
        diff=git(root,"diff","--no-ext-diff","--unified=0")
        for line in diff.stdout.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                for pat in SECRET_PATTERNS:
                    if pat.search(line[1:]):
                        findings.append({"type":"possible-secret","text":"[redacted possible secret]"})
                        break
        result={"baseline_captured":False,"repository":str(root),"changes":rows,"findings":findings,
                "note":"Untracked file contents are not scanned by this helper; inspect them separately. Secret detection is heuristic."}
    print(json.dumps(result,indent=2) if a.json else json.dumps(result,indent=2))
    return 1 if result.get("findings") else 0
if __name__=="__main__": raise SystemExit(main())
