#!/usr/bin/env python3
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
def normalize(value):
    value=re.sub(r'([A-Za-z]:)?[/\\][\w./\\ -]+','<PATH>',value)
    value=re.sub(r'\bline\s+\d+\b','line <N>',value,flags=re.I)
    return re.sub(r'\s+',' ',value).strip().lower()[:500]
def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path.cwd())
    p.add_argument("--task-id",required=True); p.add_argument("--command",required=True)
    p.add_argument("--error",required=True); p.add_argument("--hypothesis",required=True)
    p.add_argument("--approach",required=True); p.add_argument("--outcome",choices=["failed","passed"],default="failed")
    a=p.parse_args(); root=a.root.resolve()
    q=subprocess_run(["git","-C",str(root),"rev-parse","--show-toplevel"])
    if q.returncode: print("Not inside a Git repository.",file=sys.stderr); return 2
    path=Path(q.stdout.strip())/".agentguard"/"attempts.json"; path.parent.mkdir(parents=True,exist_ok=True)
    try: data=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version":1,"attempts":[]}
    except Exception as e: print(f"Corrupt attempt ledger: {e}",file=sys.stderr); return 2
    sig=normalize(a.error); entries=data.setdefault("attempts",[])
    repeats=sum(1 for x in entries if x.get("task_id")==a.task_id and x.get("signature")==sig and x.get("outcome")=="failed")
    entries.append({"task_id":a.task_id,"command":a.command,"signature":sig,"hypothesis":a.hypothesis,"approach":a.approach,"outcome":a.outcome,"timestamp":datetime.now(timezone.utc).isoformat()})
    tmp=path.with_suffix(".tmp"); tmp.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8"); tmp.replace(path)
    if a.outcome=="passed": print("continue"); return 0
    if repeats>=2: print("stop-and-escalate"); return 2
    if repeats>=1: print("change-approach"); return 1
    print("continue"); return 0
def subprocess_run(args):
    import subprocess
    return subprocess.run(args,capture_output=True,text=True)
if __name__=="__main__": raise SystemExit(main())
