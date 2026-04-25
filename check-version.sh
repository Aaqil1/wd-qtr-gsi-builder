#!/bin/bash
set -e

echo "===================================="
echo "Version Consistency Check: START"
echo "===================================="

WORKSPACE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$WORKSPACE"

TOML_VERSION=$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')
POM_VERSION=$(echo "$VERSION" | sed 's/-SNAPSHOT$//')

if [ -z "$TOML_VERSION" ]; then
    echo "ERROR: Could not extract version from pyproject.toml"
    exit 1
fi

if [ -z "$POM_VERSION" ]; then
    echo "ERROR: Could not get version from pom.xml (VERSION env var not set)"
    exit 1
fi

if [ "$TOML_VERSION" != "$POM_VERSION" ]; then
    echo "============================================================"
    echo "VERSION MISMATCH DETECTED!"
    echo "  pyproject.toml version: $TOML_VERSION"
    echo "  pom.xml version:        $POM_VERSION (from ${VERSION})"
    echo "  Please update both files to the same version."
    echo "============================================================"
    exit 1
fi

echo "Version check passed: $TOML_VERSION"
echo "===================================="
echo "Version Consistency Check: DONE"
echo "===================================="
