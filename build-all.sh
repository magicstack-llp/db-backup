#!/bin/bash
# Build script for creating executables for multiple platforms
# Note: This script requires Docker or access to multiple platforms
# For true cross-platform builds, use GitHub Actions or similar CI/CD

set -e

echo "Building db-backup executables for multiple platforms..."
echo ""
echo "Note: This script provides instructions for cross-platform builds."
echo "For automated builds, consider using GitHub Actions."
echo ""

# Make build script executable
chmod +x build.sh

# Build for current platform
echo "Building for current platform: $(uname -s)..."
./build.sh

echo ""
echo "For cross-platform builds:"
echo ""
echo "1. Linux (x86_64):"
echo "   docker run --rm -v \$(pwd):/src -w /src python:3.11-slim bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.cargo/env && uv sync && uv pip install -r requirements-build.txt && uv run pyinstaller db-backup.spec --clean'"
echo ""
echo "2. Windows:"
echo "   Use Windows with uv installed, then run:"
echo "   uv sync"
echo "   uv pip install -r requirements-build.txt"
echo "   uv run pyinstaller db-backup.spec --clean"
echo ""
echo "3. macOS:"
echo "   On macOS, run:"
echo "   uv sync"
echo "   uv pip install -r requirements-build.txt"
echo "   uv run pyinstaller db-backup.spec --clean"
echo ""

