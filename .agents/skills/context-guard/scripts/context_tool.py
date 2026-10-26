#!/usr/bin/env python3
import argparse, re, subprocess, sys
from pathlib import Path
TEMPLATE = """# Project Context

## Project facts
## Architecture decisions (with rationale)
## Conventions
## Current task
## Completed work
## Remaining work
## Known bugs
## Failed approaches
## Validation evidence
Last verified against commit: <hash or unknown>
"""
SECRET = re.compile(r'(?i)(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*["\']?([A-Za-z0-9_./+=:-]{8,})')
def main():
    p=argparse.ArgumentParser(); p.add_argument("command",choices=["init","check","scan-secrets"])
    p.add_argument("--root",type=Path,default=Path.cwd()); a=p.parse_args()
    q=subprocess.run(["git","-C",str(a.root.resolve()),"rev-parse","--show-toplevel"],capture_output=True,text=True)
    if q.returncode: print("Not inside a Git repository.",file=sys.stderr); return 2
    root=Path(q.stdout.strip()).resolve(); path=root/".agentguard"/"context.md"
    if a.command=="init":
        if path.exists(): print(f"Context already exists: {path}"); return 1
        head=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(TEMPLATE.replace("<hash or unknown>",head.stdout.strip() if head.returncode==0 else "unknown"),encoding="utf-8")
        print(f"Created {path}"); return 0
    if not path.exists(): print("Context file is missing."); return 1
    content=path.read_text(encoding="utf-8")
    if a.command=="scan-secrets":
        found=[]
        for n,line in enumerate(content.splitlines(),1):
            if SECRET.search(line): found.append(n)
        for n in found: print(f"Possible secret pattern at line {n}; content omitted.")
        print("No common patterns detected." if not found else "Remove possible secrets before continuing.")
        return 2 if found else 0
    recorded=next((x.split(":",1)[1].strip() for x in content.splitlines() if x.lower().startswith("last verified against commit:")),"unknown")
    current=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    print("Context commit marker matches HEAD." if recorded==current else f"Context may be stale: recorded={recorded}, current={current}")
    return 0 if recorded==current else 1
if __name__=="__main__": raise SystemExit(main())
