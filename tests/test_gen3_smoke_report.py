from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_smoke_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_gen3_smoke",
        ROOT / "scripts" / "run_gen3_smoke.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = load_smoke_runner()


def test_generics_expected_exit_is_success() -> None:
    assert smoke.EXPECTED_EXIT["generics.ci"] == 42
    assert smoke.classify(42, "40\n", "", False, 42) == "ok"
    assert smoke.classify(1, "", "", False, 42) == "gen3_runtime_nonzero"


def test_owned_expected_exit_is_success() -> None:
    assert smoke.EXPECTED_EXIT["owned.ci"] == 42
    assert smoke.classify(42, "drop 1\n", "", False, 42) == "ok"


def test_smoke_targets_cover_top_level_examples_and_projects() -> None:
    targets = smoke.smoke_targets(ROOT)
    assert len(targets) == smoke.EXPECTED_TARGETS == 39
    assert targets[:-2] == sorted((ROOT / "examples").glob("*.ci"))
    assert [target.name for target in targets[-2:]] == [
        "class_project",
        "module_project",
    ]
    assert ROOT / "examples" / "aggregate_ownership.ci" in targets
    assert ROOT / "examples" / "ownership_edge_cases.ci" in targets
    assert ROOT / "examples" / "funnel_hash.ci" in targets


def test_generic_list_assignment_is_an_expected_aggregate_error() -> None:
    message = (
        "assigning to 'CinderList_i32' (aka 'struct CinderList_i32') "
        "from incompatible type 'CinderList' (aka 'struct CinderList')"
    )
    assert smoke.cause_label_for(message) == "aggregate_expected_type"


def test_extract_first_c_error_skips_warnings_and_normalizes_path(tmp_path: Path) -> None:
    build_dir = tmp_path / "generics.ci-build"
    generated = build_dir / "cinder_gen" / "generics.cinder.h"
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "\n".join(
            [
                "typedef struct cinder_generics_generics__Box cinder_generics_generics__Box;",
                "struct cinder_generics_generics__Box {",
                "    cinder_generics_generics__T value;",
                "};",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    stderr = "\n".join(
        [
            f"{generated}:1:1: warning: '__auto_type' is a GNU extension [-Wgnu-auto-type]",
            (
                f"{generated}:3:5: error: unknown type name "
                "'cinder_generics_generics__T'; did you mean 'cinder_generics_generics__Box'?"
            ),
        ]
    )

    first = smoke.extract_first_c_error(
        target_name="examples/generics.ci",
        target_path=ROOT / "examples" / "generics.ci",
        build_dir=build_dir,
        stdout="",
        stderr=stderr,
    )

    assert first is not None
    assert first.target == "examples/generics.ci"
    assert first.generated_file == "cinder_gen/generics.cinder.h"
    assert first.generated_line == 3
    assert first.cause_label == "leaked_type_parameter"
    assert first.source_feature == "user generics at struct Box"


def test_extract_first_c_error_accepts_msvc_diagnostics(tmp_path: Path) -> None:
    build_dir = tmp_path / "expressive_match.ci-build"
    generated = build_dir / "cinder_gen" / "expressive_match.c"
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "\n".join(
            [
                "int main(void)",
                "{",
                "    return score;",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    first = smoke.extract_first_c_error(
        target_name="examples/expressive_match.ci",
        target_path=ROOT / "examples" / "expressive_match.ci",
        build_dir=build_dir,
        stdout="",
        stderr=f"{generated}(3,12): error C2065: 'score': undeclared identifier",
    )

    assert first is not None
    assert first.generated_file == "cinder_gen/expressive_match.c"
    assert first.generated_line == 3
    assert first.cause_label == "missing_match_binding"
    assert first.source_feature == "match binding lowering at function main"


def test_compiler_error_lines_excludes_warnings_and_notes(tmp_path: Path) -> None:
    generated = tmp_path / "cinder_gen" / "owned.c"
    generated.parent.mkdir(parents=True)
    warning = f"{generated}:8:5: warning: '__auto_type' is a GNU extension [-Wgnu-auto-type]"
    note = f"{generated}:4:12: note: expanded from macro 'Owned'"
    error = f"{generated}:16:31: error: use of undeclared identifier 'cinder_owned_owned__Owned'"
    fatal = f"{generated}:17:1: fatal error: generated include loop"

    assert smoke.compiler_error_lines("", "\n".join([warning, note, error, fatal])) == [
        error,
        fatal,
    ]


def test_render_both_mode_filters_warning_and_note_lines(tmp_path: Path) -> None:
    generated = tmp_path / "strings.ci-build" / "cinder_gen" / "strings.c"
    generated.parent.mkdir(parents=True)
    warning = f"{generated}:70:5: warning: '__auto_type' is a GNU extension [-Wgnu-auto-type]"
    note = f"{generated}:66:12: note: expanded from macro 'append'"
    error = f"{generated}:70:13: error: call to undeclared function 'reserve'"
    result = {
        "rel": "examples/strings.ci",
        "status": "FAIL",
        "kind": "gen3_toolchain_error",
        "exit": 2,
        "stdout": "",
        "stderr": "\n".join([warning, note, error]),
        "elapsed": 0.2,
        "timed_out": False,
        "first_c_error": smoke.FirstCError(
            target="examples/strings.ci",
            generated_file="cinder_gen/strings.c",
            generated_line=70,
            source_feature="String or builtin lowering at function main",
            cause_label="missing_builtin_or_method",
            message="call to undeclared function 'reserve'",
        ),
    }

    report = smoke.render_report(
        [result],
        report_mode="both",
        gen3=ROOT / ".cinder" / "selfhost-proof" / "cinder-gen3",
        now="2026-08-06 00:00:00 UTC",
    )

    assert "--- gen3 errors ---" in report
    assert "--- gen3 stderr ---" not in report
    assert "--- gen3 stdout ---" not in report
    assert error in report
    assert warning not in report
    assert note not in report


def test_render_first_error_mode_omits_verbose_failure_blobs() -> None:
    result = {
        "rel": "examples/classes.ci",
        "status": "FAIL",
        "kind": "gen3_toolchain_error",
        "exit": 2,
        "stdout": "",
        "stderr": "many diagnostics",
        "elapsed": 0.2,
        "timed_out": False,
        "first_c_error": smoke.FirstCError(
            target="examples/classes.ci",
            generated_file="cinder_gen/classes.c",
            generated_line=16,
            source_feature="class and dyn lowering at function Circle.__init__",
            cause_label="missing_super_lowering",
            message="call to undeclared function 'cinder_classes_classes__super'",
        ),
    }

    report = smoke.render_report(
        [result],
        report_mode="first-error",
        gen3=ROOT / ".cinder" / "selfhost-proof" / "cinder-gen3",
        now="2026-08-06 00:00:00 UTC",
    )

    assert "## First non-warning C errors" in report
    assert "examples/classes.ci: cinder_gen/classes.c:16 [missing_super_lowering]" in report
    assert "class and dyn lowering at function Circle.__init__" in report
    assert "--- gen3 stderr ---" not in report
    assert "## Status by example" not in report


def test_render_reports_missing_first_c_error_for_non_toolchain_failures() -> None:
    result = {
        "rel": "examples/input.ci",
        "status": "FAIL",
        "kind": "gen3_timeout",
        "exit": -9,
        "stdout": "",
        "stderr": "",
        "elapsed": 60.0,
        "timed_out": True,
        "first_c_error": None,
    }

    report = smoke.render_report(
        [result],
        report_mode="first-error",
        gen3=ROOT / ".cinder" / "selfhost-proof" / "cinder-gen3",
        now="2026-08-06 00:00:00 UTC",
    )

    assert "- examples/input.ci: no non-warning C error found (kind: gen3_timeout)" in report


def test_render_runtime_signal_and_raw_stderr() -> None:
    stderr = "libsystem_malloc: BUG IN CLIENT OF LIBMALLOC: not an allocated block"
    result = {
        "rel": "examples/aggregate_ownership.ci",
        "status": "FAIL",
        "kind": "gen3_runtime_nonzero",
        "exit": 133,
        "stdout": "",
        "stderr": stderr,
        "elapsed": 0.8,
        "timed_out": False,
        "first_c_error": None,
    }

    report = smoke.render_report(
        [result],
        report_mode="full",
        gen3=ROOT / ".cinder" / "selfhost-proof" / "cinder-gen3",
        now="2026-08-08 00:00:00 UTC",
    )

    assert "gen3 exit=133" in report
    assert "signal: SIGTRAP" in report
    assert stderr in report
