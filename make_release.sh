#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <version>" >&2
  echo "Example: $0 0.6.0" >&2
  exit 2
fi

version=$1
if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must use MAJOR.MINOR.PATCH format (for example, 0.6.0)." >&2
  exit 2
fi

tag="v$version"

git tag -a "$tag" -m "Cinder $tag"
git push origin "$tag"
