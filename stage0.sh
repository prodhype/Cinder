set -euo pipefail

ROOT="$(pwd)"
PROOF="$ROOT/.cinder/selfhost-proof"
PROJECT="$ROOT/compiler_selfhost"

rm -rf "$PROOF"
mkdir -p "$PROOF"

# Stage0 Python compiler builds the first native Cinder compiler.
python3.14 -m cinder build "$PROJECT" \
  -o "$PROOF/cinder-gen1" \
  --build-dir "$PROOF/gen1-build"

# Gen1 builds the Cinder compiler sources into gen2.
"$PROOF/cinder-gen1" build "$PROJECT" \
  -o "$PROOF/cinder-gen2" \
  --build-dir "$PROOF/gen2-build"

# Gen2 builds the same Cinder compiler sources into gen3.
"$PROOF/cinder-gen2" build "$PROJECT" \
  -o "$PROOF/cinder-gen3" \
  --build-dir "$PROOF/gen3-build"

# The generated C trees must be identical at the fixed point.
diff -ru \
  "$PROOF/gen2-build/cinder_gen" \
  "$PROOF/gen3-build/cinder_gen"

printf '%s\n' "fixed-point generated tree: PASS"
