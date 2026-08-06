from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GEN3 = ROOT / ".cinder/selfhost-proof/cinder-gen3"
OUT = ROOT / "smoke_test.txt"
PROGRESS = Path("/tmp/cinder_gen3_smoke_progress.log")
MAX_BLOB = 8000
TIMEOUT_SEC = 60
EXPECTED_TARGETS = 36

STDIN = {
    "input.ci": "World\n",
    "fizzbuzz.ci": "15\n",
    "towers_of_hanoi.ci": "3\n",
}

_CLANG_GCC_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s+"
    r"(?P<severity>fatal error|error|warning|note):\s+(?P<message>.*)$"
)
_MSVC_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+)(?:,(?P<column>\d+))?\):\s+"
    r"(?P<severity>fatal error|error|warning)\s+(?:[A-Z]+\d+:\s+)?(?P<message>.*)$"
)
_STRUCTURAL_RE = re.compile(
    r"^(?:typedef\s+)?(?P<kind>struct|union|enum)\s+(?P<name>[A-Za-z_]\w*)\b"
)
_DEFINE_RE = re.compile(r"^#define\s+(?P<name>[A-Za-z_]\w*)\b")
_FUNCTION_RE = re.compile(
    r"^(?:[A-Za-z_][\w\s\*]*\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)$"
)
_SOURCE_COMMENT_RE = re.compile(r"/\*\s*Source:\s*(?P<source>.*?)\s*\*/")
_SKIP_CONTEXT_PREFIXES = (
    "if ",
    "for ",
    "while ",
    "switch ",
    "return ",
    "case ",
    "else",
    "do ",
)


@dataclass(frozen=True, slots=True)
class FirstCError:
    target: str
    generated_file: str
    generated_line: int | None
    source_feature: str
    cause_label: str
    message: str


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


def smoke_targets(root: Path = ROOT) -> list[Path]:
    targets = sorted(root.glob("examples/*.ci"))
    for name in ("class_project", "module_project"):
        targets.append(root / "examples" / name)
    return targets


def run_one(
    target: Path,
    tmp_path: Path,
    *,
    gen3: Path = GEN3,
    root: Path = ROOT,
    timeout: int = TIMEOUT_SEC,
) -> dict[str, Any]:
    rel = target.relative_to(root).as_posix()
    name = target.name
    out_bin = tmp_path / f"{name}.bin"
    build_dir = tmp_path / f"{name}-build"
    stdin_data = STDIN.get(name if target.is_file() else "", "")
    cmd = [str(gen3), "run", str(target), "-o", str(out_bin), "--build-dir", str(build_dir)]
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
        cwd=str(root),
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
        exit_code = proc.returncode if proc.returncode is not None else -1
    except subprocess.TimeoutExpired:
        timed_out = True
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
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
    first_c_error = extract_first_c_error(
        target_name=rel,
        target_path=target,
        build_dir=build_dir,
        stdout=stdout or "",
        stderr=stderr or "",
    )
    return {
        "rel": rel,
        "status": status,
        "kind": kind,
        "exit": exit_code,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "elapsed": elapsed,
        "timed_out": timed_out,
        "first_c_error": first_c_error,
    }


def extract_first_c_error(
    *,
    target_name: str,
    target_path: Path,
    build_dir: Path,
    stdout: str,
    stderr: str,
) -> FirstCError | None:
    for line in f"{stdout}\n{stderr}".splitlines():
        parsed = _parse_c_diagnostic(line)
        if parsed is None:
            continue
        severity = parsed["severity"].lower()
        if severity in {"warning", "note"}:
            continue
        generated_path = Path(parsed["file"])
        generated_line = int(parsed["line"])
        message = parsed["message"].strip()
        cause_label = cause_label_for(message)
        context = _generated_context(generated_path, generated_line)
        source_feature = source_feature_for(
            cause_label=cause_label,
            context=context,
            target_path=target_path,
            generated_path=generated_path,
            build_dir=build_dir,
        )
        return FirstCError(
            target=target_name,
            generated_file=normalize_generated_file(generated_path, build_dir),
            generated_line=generated_line,
            source_feature=source_feature,
            cause_label=cause_label,
            message=message,
        )
    return None


def compiler_error_lines(stdout: str, stderr: str) -> list[str]:
    errors: list[str] = []
    for line in f"{stdout}\n{stderr}".splitlines():
        parsed = _parse_c_diagnostic(line)
        if parsed is None:
            continue
        if parsed["severity"].lower() in {"error", "fatal error"}:
            errors.append(line)
    return errors


def _parse_c_diagnostic(line: str) -> dict[str, str] | None:
    for pattern in (_CLANG_GCC_DIAGNOSTIC, _MSVC_DIAGNOSTIC):
        match = pattern.match(line)
        if match is not None:
            return match.groupdict(default="")
    return None


def normalize_generated_file(path: Path, build_dir: Path) -> str:
    try:
        return path.resolve().relative_to(build_dir.resolve()).as_posix()
    except ValueError:
        parts = path.parts
        if "cinder_gen" in parts:
            index = parts.index("cinder_gen")
            return Path(*parts[index:]).as_posix()
        return path.as_posix()


def cause_label_for(message: str) -> str:
    lowered = message.lower()
    if "unknown type name" in lowered:
        if _looks_like_leaked_type_parameter(message):
            return "leaked_type_parameter"
        return "unknown_type"
    if "call to undeclared function" in lowered:
        if "super" in lowered:
            return "missing_super_lowering"
        if any(name in lowered for name in ("type_name", "type_info", "field", "method", "implements")):
            return "missing_reflection_builtin"
        if any(name in lowered for name in ("parse_", "to_string", "clone", "reserve", "append", "finish")):
            return "missing_builtin_or_method"
        return "undeclared_function"
    if "use of undeclared identifier" in lowered or "undeclared identifier" in lowered:
        if any(name in lowered for name in ("score", "original", "parsed", "value", "error")):
            return "missing_match_binding"
        if "owned" in lowered:
            return "owned_lowering"
        if "." in message:
            return "bad_qualified_constructor"
        return "undeclared_identifier"
    if "field has incomplete type" in lowered:
        return "incomplete_type"
    if "incompatible result type" in lowered:
        return "result_type_mismatch"
    if "indirection requires pointer operand" in lowered:
        return "owned_lowering"
    if "no member named" in lowered:
        if "owned" in lowered:
            return "owned_lowering"
        return "missing_member"
    if "initializer element is not a compile-time constant" in lowered:
        return "nonconstant_initializer"
    if "array initializer" in lowered or "initializing" in lowered:
        return "aggregate_expected_type"
    if "expected expression" in lowered:
        return "invalid_expression"
    return "c_error"


def _looks_like_leaked_type_parameter(message: str) -> bool:
    for quoted in re.findall(r"'([^']+)'", message):
        tail = quoted.split("__")[-1]
        if len(tail) == 1 and tail.isalpha() and tail.isupper():
            return True
    return bool(re.search(r"\bT\b", message))


def source_feature_for(
    *,
    cause_label: str,
    context: str | None,
    target_path: Path,
    generated_path: Path,
    build_dir: Path,
) -> str:
    feature = _feature_area_for(cause_label)
    if context:
        return f"{feature} at {context}"
    source_path = _infer_source_path(target_path, generated_path, build_dir)
    if source_path:
        return f"{feature} at {source_path}"
    return feature


def _feature_area_for(cause_label: str) -> str:
    return {
        "leaked_type_parameter": "user generics",
        "missing_super_lowering": "class and dyn lowering",
        "missing_reflection_builtin": "reflection builtins",
        "missing_match_binding": "match binding lowering",
        "bad_qualified_constructor": "enum and variant constructors",
        "aggregate_expected_type": "expected aggregate types",
        "owned_lowering": "Owned lowering",
        "missing_builtin_or_method": "String or builtin lowering",
        "result_type_mismatch": "Result lowering",
        "incomplete_type": "type definition ordering",
    }.get(cause_label, "generated C")


def _generated_context(path: Path, line_number: int) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    index = max(0, min(line_number - 1, len(lines) - 1))
    for text in reversed(lines[: index + 1]):
        context = _context_from_line(text.strip())
        if context is not None:
            return context
    return None


def _context_from_line(text: str) -> str | None:
    if not text or text in {"{", "}"} or text.startswith("/*"):
        return None
    lowered = text.lower()
    if lowered.startswith(_SKIP_CONTEXT_PREFIXES):
        return None
    structural = _STRUCTURAL_RE.match(text)
    if structural is not None:
        return f"{structural.group('kind')} {_readable_c_symbol(structural.group('name'))}"
    define = _DEFINE_RE.match(text)
    if define is not None:
        return f"macro {_readable_c_symbol(define.group('name'))}"
    candidate = text[:-1].rstrip() if text.endswith("{") else text
    if candidate.endswith(";"):
        return None
    function = _FUNCTION_RE.match(candidate)
    if function is not None:
        return f"function {_readable_c_symbol(function.group('name'))}"
    return None


def _readable_c_symbol(name: str) -> str:
    if "__" in name:
        name = name.split("__", 1)[1]
    return name.replace("___", ".").replace("__", ".").strip("_") or name


def _infer_source_path(target_path: Path, generated_path: Path, build_dir: Path) -> str:
    source_comment = _source_comment(generated_path)
    if source_comment:
        return source_comment

    generated_file = normalize_generated_file(generated_path, build_dir)
    module_path = _module_path_from_generated(generated_file)
    if module_path is None:
        return _display_path(target_path)
    if target_path.suffix == ".ci":
        return _display_path(target_path)
    return _display_path(target_path / "src" / module_path)


def _source_comment(generated_path: Path) -> str:
    try:
        for line in generated_path.read_text(encoding="utf-8").splitlines()[:8]:
            match = _SOURCE_COMMENT_RE.search(line)
            if match is not None:
                return match.group("source")
    except OSError:
        return ""
    return ""


def _module_path_from_generated(generated_file: str) -> Path | None:
    prefix = "cinder_gen/"
    if not generated_file.startswith(prefix):
        return None
    module = generated_file[len(prefix) :]
    if module.endswith(".cinder.h"):
        module = module[: -len(".cinder.h")]
    elif module.endswith(".c"):
        module = module[:-2]
    else:
        return None
    return Path(module).with_suffix(".ci")


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _display_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_report(
    results: Sequence[dict[str, Any]],
    *,
    report_mode: str,
    gen3: Path = GEN3,
    root: Path = ROOT,
    timeout: int = TIMEOUT_SEC,
    now: str | None = None,
) -> str:
    ok_n = sum(1 for r in results if r["status"] == "OK")
    fail_n = sum(1 for r in results if r["status"] == "FAIL")
    timestamp = now or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# Gen3 example smoke test (gen3-only)")
    lines.append(f"# gen3:   {_display_relative(gen3, root)} run <src> -o <tmp> --build-dir <tmp>")
    lines.append(f"# date:   {timestamp}")
    lines.append(f"# cwd:    {root}")
    lines.append(
        f"# targets: {len(results)} (examples/*.ci + class_project + module_project; excludes large_project)"
    )
    lines.append(f"# per-target timeout: {timeout}s")
    lines.append(f"# report mode: {report_mode}")
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

    if report_mode in {"full", "both"}:
        _append_status(lines, results)
        lines.append("")

    if report_mode in {"first-error", "both"}:
        _append_first_c_errors(lines, results)
        lines.append("")

    if report_mode in {"full", "both"}:
        _append_ok(lines, results)
        lines.append("")
        _append_failures(lines, results, timeout=timeout)

    return "\n".join(lines).rstrip() + "\n"


def _append_status(lines: list[str], results: Sequence[dict[str, Any]]) -> None:
    lines.append("## Status by example")
    width = max((len(r["rel"]) for r in results), default=0)
    for r in results:
        lines.append(f"{r['rel']:<{width}}  {r['status']:<4}  {r['kind']}")


def _append_first_c_errors(lines: list[str], results: Sequence[dict[str, Any]]) -> None:
    lines.append("## First non-warning C errors")
    fails = [r for r in results if r["status"] == "FAIL"]
    if not fails:
        lines.append("(none)")
        return
    for r in fails:
        first_c_error = r.get("first_c_error")
        if not isinstance(first_c_error, FirstCError):
            lines.append(f"- {r['rel']}: no non-warning C error found (kind: {r['kind']})")
            continue
        location = first_c_error.generated_file
        if first_c_error.generated_line is not None:
            location = f"{location}:{first_c_error.generated_line}"
        lines.append(
            f"- {first_c_error.target}: {location} [{first_c_error.cause_label}] "
            f"{first_c_error.source_feature} - {_shorten(first_c_error.message)}"
        )


def _append_ok(lines: list[str], results: Sequence[dict[str, Any]]) -> None:
    lines.append("## OK")
    oks = [r for r in results if r["status"] == "OK"]
    if oks:
        for r in oks:
            lines.append(f"- {r['rel']}")
    else:
        lines.append("- (none)")


def _append_failures(
    lines: list[str],
    results: Sequence[dict[str, Any]],
    *,
    timeout: int,
) -> None:
    lines.append("## Failures")
    fails = [r for r in results if r["status"] == "FAIL"]
    if not fails:
        lines.append("(none)")
        return
    for r in fails:
        lines.append(f"### {r['rel']}")
        if r["timed_out"]:
            lines.append(f"gen3 exit=timeout after {timeout}s")
        else:
            lines.append(f"gen3 exit={r['exit']}")
        lines.append(f"kind: {r['kind']}")
        first_c_error = r.get("first_c_error")
        if isinstance(first_c_error, FirstCError):
            location = first_c_error.generated_file
            if first_c_error.generated_line is not None:
                location = f"{location}:{first_c_error.generated_line}"
            lines.append(f"first C error: {location} [{first_c_error.cause_label}]")
            lines.append(f"source feature: {first_c_error.source_feature}")
            lines.append(f"message: {_shorten(first_c_error.message)}")
        lines.append(f"elapsed: {r['elapsed']:.1f}s")
        lines.append("")
        stdout = str(r["stdout"]).strip()
        if stdout:
            lines.append("--- gen3 stdout ---")
            lines.append(truncate(stdout).rstrip("\n"))
        lines.append("--- gen3 errors ---")
        errors = compiler_error_lines(str(r["stdout"]), str(r["stderr"]))
        if errors:
            lines.append(truncate("\n".join(errors)).rstrip("\n"))
        else:
            lines.append(f"(no parsed C errors; kind: {r['kind']})")
        lines.append("")


def _shorten(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 4].rstrip() + " ..."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the gen3 example smoke suite.")
    parser.add_argument(
        "--report-mode",
        choices=("full", "first-error", "both"),
        default="both",
        help="choose verbose output, compact first-error output, or both",
    )
    parser.add_argument("-o", "--output", type=Path, default=OUT)
    parser.add_argument("--gen3", type=Path, default=GEN3)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    gen3 = arguments.gen3.expanduser().resolve()
    if not gen3.is_file():
        parser.error(f"missing gen3 binary: {gen3}")
    targets = smoke_targets(ROOT)
    if len(targets) != EXPECTED_TARGETS:
        parser.error(f"expected {EXPECTED_TARGETS} targets, got {len(targets)}")

    PROGRESS.write_text("", encoding="utf-8")
    results = []
    with tempfile.TemporaryDirectory(prefix="cinder-gen3-smoke.") as tmp:
        tmp_path = Path(tmp)
        for i, target in enumerate(targets, 1):
            rel = target.relative_to(ROOT).as_posix()
            log(f"[{i}/{len(targets)}] RUN {rel}")
            r = run_one(target, tmp_path, gen3=gen3, timeout=arguments.timeout)
            results.append(r)
            log(
                f"[{i}/{len(targets)}] -> {r['status']} {r['kind']} "
                f"exit={r['exit']} {r['elapsed']:.1f}s"
            )

    report = render_report(
        results,
        report_mode=arguments.report_mode,
        gen3=gen3,
        timeout=arguments.timeout,
    )
    arguments.output.write_text(report, encoding="utf-8")
    ok_n = sum(1 for r in results if r["status"] == "OK")
    fail_n = sum(1 for r in results if r["status"] == "FAIL")
    log(f"Wrote {arguments.output} ({ok_n} ok, {fail_n} fail)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
