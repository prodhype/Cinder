# Bootstrap seed provenance

The binaries in this directory are trusted bootstrap artifacts. They exist only
to compile the canonical compiler implementation in `compiler_selfhost/`.
Normal compiler development changes the Cinder sources, not these binaries.

## Source

- Source commit: `7df8c7e43d27c466f68f9c7e2de17e95a5c21526`
- Bootstrap date: 2026-08-16
- Producer: the Python 3.14 stage0 compiler at that commit
- Selected artifact: gen3 after an exact gen2/gen3 generated-C tree match
- Bootstrap command: `bash ./stage0.sh`

## darwin-arm64

- Path: `darwin-arm64/cinder`
- SHA-256: `55f8403cac59b2ac9f7758f6a6e9d9dec5b1cf8e053844186075bda84e8aafaa`
- Size: 794008 bytes
- Host: macOS 26.6.1 (25G76), arm64
- Python used by stage0: CPython 3.14.3
- C toolchain: Apple clang 17.0.0 (`clang-1700.0.13.3`)
- Minimum host OS: macOS 15.4
- Mach-O deployment target: `15.4.0` in `LC_BUILD_VERSION` (verified with
  `otool -l darwin-arm64/cinder`)

## linux-x86_64

- Path: `linux-x86_64/cinder`
- SHA-256: `c19e704bc7a9d5855deffc63fb1432901f6eeff64ddb9f30e9d99617bbb5e6ee`
- Size: 956160 bytes
- Build environment: `python:3.14-bookworm`
- Container image digest:
  `sha256:8771427e2ac3e39208c1632f17e8b09e464333d262844a03705cc5e0023c16e2`
- Host architecture inside the container: Linux x86_64
- Python used by stage0: CPython 3.14.7
- C toolchain: GCC 12.2.0 (`12.2.0-14+deb12u1`)
- Minimum host C library: glibc 2.34
- ELF version requirement: `GLIBC_2.34` (verified with
  `readelf --version-info linux-x86_64/cinder`)
- Container command:

  ```sh
  docker run --rm --platform linux/amd64 \
    -v "$PWD:/src" -w /src \
    python:3.14-bookworm \
    bash -lc 'python -m pip install -e . && bash ./stage0.sh'
  ```

## Verification

`bootstrap.sh` verifies the selected seed against `SHA256SUMS` before executing
it. On macOS ARM64 it requires macOS 15.4 or newer. On Linux x86_64 it requires
glibc 2.34 or newer and rejects unsupported C libraries before invoking the
dynamically linked seed. The seed then builds gen1, gen1 builds gen2, and the
generated C trees from those two builds must match exactly. Linked binaries are
not compared because system linkers may add nondeterministic metadata.

## Updating a seed

Update a seed only when an existing seed can no longer compile the canonical
compiler source. Build a fixed-point compiler on the target host from the
existing trusted seed, record the source commit and complete toolchain details,
replace only that host's binary, update its checksum above and in
`SHA256SUMS`, and run the complete bootstrap and native test suite on both seed
platforms.
