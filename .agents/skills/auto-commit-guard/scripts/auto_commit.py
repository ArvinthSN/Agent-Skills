#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path
SECRET_PATTERNS = [
    __import__("re").compile(r'(?i)(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*["\']?([A-Za-z0-9_./+=:-]{8,})'),
    __import__("re").compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    __import__("re").compile(r'\bAKIA[0-9A-Z]{16}\b'),
]
def git(root,args,env=None):
    return subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,env=env)
def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path.cwd())
    p.add_argument("--message",required=True); p.add_argument("--dry-run",action="store_true")
    p.add_argument("--yes",action="store_true"); p.add_argument("paths",nargs="+"); a=p.parse_args()
    q=git(a.root.resolve(),["rev-parse","--show-toplevel"])
    if q.returncode: print("Not inside a Git repository.",file=sys.stderr); return 2
    root=Path(q.stdout.strip()).resolve(); paths=[]
    for raw in a.paths:
        candidate=(root/raw).resolve()
        try: rel=candidate.relative_to(root).as_posix()
        except ValueError: print(f"Refusing path outside repository: {raw}",file=sys.stderr); return 2
        if Path(rel).name in {".env",".env.local","secrets.json","credentials.json","id_rsa"}:
            print(f"Refusing sensitive filename: {rel}",file=sys.stderr); return 4
        if not candidate.exists() and git(root,["ls-files","--error-unmatch","--",rel]).returncode:
            print(f"Path not found: {rel}",file=sys.stderr); return 2
        if candidate.is_file():
            text=candidate.read_text(encoding="utf-8",errors="replace")
            if any(rx.search(line) for line in text.splitlines() for rx in SECRET_PATTERNS):
                print(f"Blocked: possible secret pattern in {rel}; inspect locally.",file=sys.stderr); return 4
        paths.append(rel)
    evidence_path=root/".agentguard"/"test-results.json"
    try: evidence=json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception: evidence={}
    head=git(root,["rev-parse","HEAD"]).stdout.strip()
    if evidence.get("status")!="passed" or evidence.get("commit")!=head:
        print("Blocked: passing test evidence for current HEAD is required.",file=sys.stderr); return 3
    for rel in paths:
        path=root/rel
        if path.exists() and path.stat().st_mtime>evidence.get("finished_epoch",0):
            print(f"Blocked: test evidence is stale for {rel}.",file=sys.stderr); return 3
    status=git(root,["status","--porcelain=v1","--",*paths])
    if status.returncode or not status.stdout.strip(): print("No selected changes or status unavailable.",file=sys.stderr); return 2
    print("Selected paths:\n  "+"\n  ".join(paths)); print("Commit message:",a.message)
    if a.dry_run: print("Dry run: no commit created."); return 0
    if not a.yes: print("Approval required; rerun with --yes after reviewing.",file=sys.stderr); return 5
    fd,tmp=tempfile.mkstemp(prefix="agentguard-index-"); os.close(fd); env=os.environ.copy(); env["GIT_INDEX_FILE"]=tmp
    try:
        r=git(root,["read-tree","HEAD"],env)
        if r.returncode: print(r.stderr,file=sys.stderr); return 6
        r=git(root,["add","--",*paths],env)
        if r.returncode: print(r.stderr,file=sys.stderr); return 6
        staged=git(root,["diff","--cached","--name-only"],env).stdout.strip()
        if not staged: print("No selected changes."); return 2
        r=git(root,["commit","-m",a.message],env)
        if r.returncode: print(r.stderr,file=sys.stderr); return 6
        print("Created commit:",git(root,["rev-parse","HEAD"]).stdout.strip()); return 0
    finally:
        try: os.unlink(tmp)
        except OSError: pass
if __name__=="__main__": raise SystemExit(main())
