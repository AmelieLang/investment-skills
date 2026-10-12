"""Audit and package the owned offline candidate. Never executes vendor code."""
import ast
import hashlib
import json
import re
import subprocess
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT.parent
sys.path.insert(0,str(ROOT))
import adapter

def write(path,data):
    (ROOT/path).parent.mkdir(parents=True,exist_ok=True)
    (ROOT/path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

class Recorded(unittest.TestResult):
    def __init__(self):
        super().__init__();self.records=[]
    def addSuccess(self,test):
        super().addSuccess(test);self.records.append({"test":test.id(),"status":"passed"})
    def addFailure(self,test,err):
        super().addFailure(test,err);self.records.append({"test":test.id(),"status":"failed","exception_type":err[0].__name__})
    def addError(self,test,err):
        super().addError(test,err);self.records.append({"test":test.id(),"status":"error","exception_type":err[0].__name__})

stamp=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
backend_report=adapter.read_json(ROOT/"qa/backend-tests.json")
if backend_report["failed"] or backend_report["errors"]:
    raise SystemExit("Recorded backend checks failed; package stopped.")
for item in backend_report["tested_source_hashes"]:
    if hashlib.sha256((ROOT/item["path"]).read_bytes()).hexdigest()!=item["sha256"]:
        raise SystemExit("Runtime/test source changed after the successful recorded run; re-test before packaging.")

cli=[]
for operation in ("send","trade","botmux","schedule"):
    run=subprocess.run([sys.executable,str(ROOT/"adapter.py")],input=json.dumps({"operation":operation}),
                       text=True,capture_output=True,cwd=ROOT)
    body=json.loads(run.stdout)
    if run.returncode!=2 or body["code"]!="OPERATION_NOT_ALLOWED":
        raise SystemExit("Forbidden operation was not rejected.")
    cli.append({"operation":operation,"exit_code":run.returncode,"response":body})
write("qa/actual-operation-refusal.json",{"performed_at":stamp,"checks":cli,
      "scope":"Actual adapter CLI calls; rejected before processing. No send/trade implementation exists.",
      "process_function_network_and_child_process_calls":0,
      "counter_evidence":"test_actual_send_and_trade_calls_rejected_without_side_effects"})

tree=ast.parse((ROOT/"adapter.py").read_text(encoding="utf-8"))
imports=[]
for element in ast.walk(tree):
    if isinstance(element,ast.Import):imports += [a.name for a in element.names]
    if isinstance(element,ast.ImportFrom):imports.append(element.module or "")
    if isinstance(element,ast.Call) and isinstance(element.func,ast.Name) and element.func.id in {"exec","eval","compile","__import__"}:
        raise SystemExit("Dynamic source execution found.")
if any(i.split(".")[0] in {"socket","subprocess","requests","http","ftplib","smtplib"} or i.startswith("urllib.request") for i in imports):
    raise SystemExit("Network/sender import in adapter.")

# R1 includes only explicitly requested public/synthetic dashboard render PNGs; profiles/helpers stay outside ROOT.
excluded={"CHANGES.patch","MANIFEST.sha256.json","PACKAGE_CONTENTS.txt","R2_CHANGES.patch"}
files=sorted(p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc" and p.name not in excluded)
private_pattern=re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|\bcli_[A-Za-z0-9]{16,}\b|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")
for path in files:
    if path.suffix == ".png":
        continue
    content=path.read_text(encoding="utf-8-sig")
    if private_pattern.search(content):
        raise SystemExit("Private marker found; package stopped.")
write("qa/public-content-audit.json",{"performed_at":stamp,"status":"passed","private_marker_matches":0,
    "adapter_imports":sorted(set(imports)),"dynamic_execution_calls":0,
    "source_scope":"fixed MIT public upstream + public Apple release + synthetic fixtures + explicitly requested synthetic/public dashboard review PNGs; no private files or unrelated desktop screenshots"})
(ROOT/"LICENSE").write_bytes((ROOT/"vendor/finterm/LICENSE").read_bytes())
files=sorted(p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc" and p.name not in excluded)
patch=[]
for path in files:
    relative=path.relative_to(ROOT).as_posix()
    addition=subprocess.run(["git","--no-optional-locks","-c","core.autocrlf=false","diff","--no-index","--binary","--","/dev/null",relative],cwd=ROOT,capture_output=True)
    if addition.returncode!=1 or (path.suffix==".png" and b"GIT binary patch" not in addition.stdout):
        raise SystemExit("Diff failed; no unreconstructable marker substituted.")
    patch.append(addition.stdout)
(ROOT/"CHANGES.patch").write_bytes(b"".join(patch))
# A focused R2 diff accompanies the complete-additions patch. The accepted R1 directory is read-only.
old_root=TASK/"t3-alpha-dawn-offline-r1"
r1=[]
for path in files:
    relative=path.relative_to(ROOT).as_posix();old_path=old_root/relative
    old_bytes=old_path.read_bytes() if old_path.exists() else b""
    if old_bytes==path.read_bytes():continue
    before=(old_root.name+"/"+relative) if old_path.exists() else "/dev/null"
    after=ROOT.name+"/"+relative
    change=subprocess.run(["git","--no-optional-locks","-c","core.autocrlf=false","diff","--no-index","--binary","--",before,after],cwd=TASK,capture_output=True)
    if change.returncode!=1:raise SystemExit("R2 diff failed.")
    # Normalize only filename headers; preserve hunk/binary bytes, BOMs and final-newline markers.
    lines=change.stdout.splitlines(keepends=True)
    for i,line in enumerate(lines):
        if line.startswith((b"diff --git ",b"--- ",b"+++ ")):
            line=line.replace(("a/"+old_root.name+"/").encode(),b"a/").replace(("b/"+ROOT.name+"/").encode(),b"b/")
            line=line.replace(("a/"+ROOT.name+"/").encode(),b"a/")
            lines[i]=line
    r1.append(b"".join(lines))
(ROOT/"R2_CHANGES.patch").write_bytes(b"".join(r1))
manifest=[]
for path in files+[ROOT/"CHANGES.patch",ROOT/"R2_CHANGES.patch"]:
    blob=path.read_bytes();manifest.append({"path":path.relative_to(ROOT).as_posix(),"bytes":len(blob),"sha256":hashlib.sha256(blob).hexdigest()})
write("MANIFEST.sha256.json",{"performed_at":stamp,"files":manifest,"self_hash_excluded":True,
                             "diff_baseline":"empty isolated directory; all additions. Existing Alpha Dawn untouched."})
(ROOT/"PACKAGE_CONTENTS.txt").write_text("\n".join(sorted([p.relative_to(ROOT).as_posix() for p in files]+["CHANGES.patch","R2_CHANGES.patch","MANIFEST.sha256.json","PACKAGE_CONTENTS.txt"]))+"\n",encoding="utf-8")
destination=TASK/"output";destination.mkdir(exist_ok=True)
archive=destination/"t3-alpha-dawn-offline-candidate-r2.zip"
final_files=sorted(p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc")
with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as z:
    for path in final_files:z.write(path,ROOT.name+"/"+path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as z:
    if z.testzip() is not None:raise SystemExit("ZIP integrity failure.")
    for item in manifest:
        if hashlib.sha256(z.read(ROOT.name+"/"+item["path"])).hexdigest()!=item["sha256"]:
            raise SystemExit("ZIP manifest mismatch.")
receipt={"archive":archive.name,"sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),"bytes":archive.stat().st_size,
         "file_count":len(final_files),"performed_at":stamp,"backend_passed":backend_report["passed"],
         "frontend_passed":adapter.read_json(ROOT/"qa/dashboard-tests.json")["passed"],"zip_integrity":"passed"}
(destination/"t3-local-package-receipt-r2.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
print(json.dumps(receipt))
