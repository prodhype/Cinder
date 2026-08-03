from __future__ import annotations

import datetime as dt
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN3 = ROOT / ".cinder/selfhost-proof/cinder-gen3"
OUT = ROOT / "smoke_test.txt"
PROGRESS = Path("/tmp/cinder_gen3_smoke_progress.log")
MAX_BLOB = 8000
TIMEOUT_SEC = 60

assert GEN3.is_file(), f"missing {GEN3}"

targets: list[Path] = sorted(ROOT.glob("examples/*.ci"))
for name in ("class_project", "module_project"):
    targets.append(ROOT / "examples" / name)
assert len(targets) == 36, f"expected 36 targets, got {len(targets)}"

STDIN = {
    "input.ci": "World\n",
    "fizzbuzz.ci": "15\n",
    "towers_of_hanoi.ci": "3\n",
}


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with PROGRESS.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def classify(exit_code: int, stdout: str, stderr: str, timed_out: bool) -> str:
    if timed_out:
        return "gen3_timeout"
    if exit_code == 0:
        return "ok"
    blob = (stdout + "\n" + stderr).lower()
    if any(x in blob for x in ("toolchain", "undefined reference", "linker", "ld:", "collect2", "clang: error", "fatal error:")):
        return "gen3_toolchain_error"
    if "project" in blob and ("error" in blob or "failed" in blob):
        return "gen3_project_error"
    if re.search(r"\bE\s+\d+", stdout + stderr) or "checker" in blob or "type error" in blob:
        if any(x in blob for x in ("compiling", "linking", "ld:", "collect2")):
            return "gen3_toolchain_error"
        return "gen3_checker_error"
    if "error" in blob or "diagnostic" in blob:
        return "gen3_checker_error"
    return "gen3_runtime_nonzero"


def truncate(text: str, limit: int = MAX_BLOB) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]\n"


def run_one(target: Path, tmp_path: Path) -> dict:
    rel = target.relative_to(ROOT).as_posix()
    name = target.name
    out_bin = tmp_path / f"{name}.bin"
    build_dir = tmp_path / f"{name}-build"
    stdin_data = STDIN.get(name if target.is_file() else "", "")
    cmd = [str(GEN3), "run", str(target), "-o", str(out_bin), "--build-dir", str(build_dir)]
    timed_out = False
    stdout = ""
    stderr = ""
    exit_code = -1
    t0 = time.time()
    # New session so we can kill the whole process group on timeout
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=stdin_data, timeout=TIMEOUT_SEC)
        exit_code = proc.returncode if proc.returncode is not None else -1
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            leftover = proc.communicate(timeout=5)
            stdout = leftover[0] or ""
            stderr = leftover[1] or ""
        except Exception:
            stdout, stderr = "", ""
        exit_code = -9
    elapsed = time.time() - t0
    kind = classify(exit_code, stdout or "", stderr or "", timed_out)
    status = "OK" if (not timed_out and exit_code == 0) else "FAIL"
    return {
        "rel": rel,
        "status": status,
        "kind": kind,
        "exit": exit_code,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "elapsed": elapsed,
        "timed_out": timed_out,
    }


PROGRESS.write_text("", encoding="utf-8")
results = []
with tempfile.TemporaryDirectory(prefix="cinder-gen3-smoke.") as tmp:
    tmp_path = Path(tmp)
    for i, target in enumerate(targets, 1):
        rel = target.relative_to(ROOT).as_posix()
        log(f"[{i}/{len(targets)}] RUN {rel}")
        r = run_one(target, tmp_path)
        results.append(r)
        log(f"[{i}/{len(targets)}] -> {r['status']} {r['kind']} exit={r['exit']} {r['elapsed']:.1f}s")

ok_n = sum(1 for r in results if r["status"] == "OK")
fail_n = sum(1 for r in results if r["status"] == "FAIL")
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

lines: list[str] = []
lines.append("# Gen3 example smoke test (gen3-only)")
lines.append(f"# gen3:   {GEN3.relative_to(ROOT).as_posix()} run <src> -o <tmp> --build-dir <tmp>")
lines.append(f"# date:   {now}")
lines.append(f"# cwd:    {ROOT}")
lines.append(f"# targets: {len(results)} (examples/*.ci + class_project + module_project; excludes large_project)")
lines.append(f"# per-target timeout: {TIMEOUT_SEC}s")
lines.append("#")
lines.append("# Interactive stdin: input.ci=World, fizzbuzz.ci=15, towers_of_hanoi.ci=3")
lines.append("# Classification:")
lines.append("#   OK   - exit 0")
lines.append("#   FAIL - non-zero exit / compile / checker / toolchain / runtime / timeout")
lines.append("# kind values: ok | gen3_checker_error | gen3_toolchain_error |")
lines.append("#   gen3_project_error | gen3_runtime_nonzero | gen3_timeout")
lines.append("")
lines.append(f"Summary: {ok_n} ok, {fail_n} fail")
lines.append("")
lines.append("## Status by example")
width = max(len(r["rel"]) for r in results)
for r in results:
    lines.append(f"{r['rel']:<{width}}  {r['status']:<4}  {r['kind']}")
lines.append("")
lines.append("## OK")
oks = [r for r in results if r["status"] == "OK"]
if oks:
    for r in oks:
        lines.append(f"- {r['rel']}")
else:
    lines.append("- (none)")
lines.append("")
lines.append("## Failures")
fails = [r for r in results if r["status"] == "FAIL"]
if not fails:
    lines.append("(none)")
else:
    for r in fails:
        lines.append(f"### {r['rel']}")
        if r["timed_out"]:
            lines.append(f"gen3 exit=timeout after {TIMEOUT_SEC}s")
        else:
            lines.append(f"gen3 exit={r['exit']}")
        lines.append(f"kind: {r['kind']}")
        lines.append(f"elapsed: {r['elapsed']:.1f}s")
        lines.append("")
        lines.append("--- gen3 stdout ---")
        lines.append(truncate(r["stdout"]).rstrip("\n"))
        lines.append("--- gen3 stderr ---")
        lines.append(truncate(r["stderr"]).rstrip("\n"))
        lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
log(f"Wrote {OUT} ({ok_n} ok, {fail_n} fail)")
