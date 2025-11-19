#!/bin/bash
# Build script for creating a single executable for the current platform

set -e

echo "Building db-backup executable for $(uname -s)..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install uv first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if PyInstaller is installed in the uv environment
if ! uv run pyinstaller --version &> /dev/null; then
    echo "PyInstaller is not installed. Installing build dependencies..."
    uv pip install -r requirements-build.txt
fi

# Install the package and all dependencies using uv
echo "Installing package dependencies with uv..."
uv sync

# Install the package itself in editable mode so db_backup imports work
echo "Installing package in editable mode..."
uv pip install -e .

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist

# Build the executable using uv run to ensure correct environment
echo "Building executable..."
uv run pyinstaller db-backup.spec --clean

# Check if build was successful
if [ -f "dist/db-backup" ] || [ -f "dist/db-backup.exe" ]; then
    echo ""
    echo "✓ Build successful!"
    echo "Executable location:"
    if [ -f "dist/db-backup" ]; then
        ls -lh dist/db-backup
        echo ""
        echo "To test the executable:"
        echo "  ./dist/db-backup --help"
    elif [ -f "dist/db-backup.exe" ]; then
        ls -lh dist/db-backup.exe
        echo ""
        echo "To test the executable:"
        echo "  dist\\db-backup.exe --help"
    fi
else
    echo "✗ Build failed - executable not found"
    exit 1
fi

