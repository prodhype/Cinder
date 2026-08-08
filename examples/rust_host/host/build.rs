use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let build_dir = manifest_dir.join("../build");
    let lib_o = build_dir.join("lib.o");
    let runtime_o = build_dir.join("cinder_runtime.o");

    println!("cargo:rerun-if-changed={}", lib_o.display());
    println!("cargo:rerun-if-changed={}", runtime_o.display());
    println!("cargo:rustc-link-arg={}", lib_o.display());
    println!("cargo:rustc-link-arg={}", runtime_o.display());
}
