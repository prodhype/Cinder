use std::io::{self, Write};
use std::ptr;

extern "C" {
    fn cinder_vec3_field_count() -> i32;
    fn cinder_describe_vec3() -> i32;
    fn fflush(stream: *mut std::ffi::c_void) -> i32;
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
}
