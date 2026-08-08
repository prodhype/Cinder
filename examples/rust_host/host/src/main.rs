use std::io::{self, Write};
use std::process;
use std::ptr;
use std::time::Instant;

const ITERATIONS: i32 = 1_000_000_000;

extern "C" {
    fn cinder_vec3_field_count() -> i32;
    fn cinder_describe_vec3() -> i32;
    fn cinder_leibniz(iterations: i32) -> f64;
    fn fflush(stream: *mut std::ffi::c_void) -> i32;
}

fn rust_leibniz(iterations: i32) -> f64 {
    // Same series as cinder_leibniz / examples/leibniz_pi.ci.
    let mut pi = 1.0_f64;
    let rounds = iterations + 2;
    let mut i = 2_i32;
    while i < rounds {
        let x = -1.0 + 2.0 * f64::from(i & 1);
        pi += x / f64::from(2 * i - 1);
        i += 1;
    }
    pi * 4.0
}

fn time_call(label: &str, fn_: impl FnOnce() -> f64) -> (f64, f64) {
    let started = Instant::now();
    let value = fn_();
    let elapsed = started.elapsed().as_secs_f64();
    println!("{label}: π ≈ {value:.12}  ({:.1} ms)", elapsed * 1000.0);
    let _ = io::stdout().flush();
    (value, elapsed)
}

fn main() {
    // Flush libc stdout after each Cinder call so its prints interleave with Rust.
    unsafe {
        let count = cinder_vec3_field_count();
        fflush(ptr::null_mut());
        println!("field_count={count}");
        let _ = io::stdout().flush();

        let fingerprint = cinder_describe_vec3();
        fflush(ptr::null_mut());
        println!("schema_fingerprint={fingerprint}");
        let _ = io::stdout().flush();
    }

    println!("Leibniz π with {ITERATIONS} iterations");
    let _ = io::stdout().flush();

    let (rust_value, rust_elapsed) = time_call("rust", || rust_leibniz(ITERATIONS));
    let (ci_value, ci_elapsed) = time_call("cinder", || unsafe { cinder_leibniz(ITERATIONS) });

    if (rust_value - ci_value).abs() > 1e-9 {
        eprintln!("error: results diverged: rust={rust_value:?} cinder={ci_value:?}");
        process::exit(1);
    }
    if ci_elapsed <= 0.0 {
        eprintln!("error: cinder timing was non-positive");
        process::exit(1);
    }
    let speedup = rust_elapsed / ci_elapsed;
    println!("speedup: {speedup:.1}x (rust / cinder)");
}
