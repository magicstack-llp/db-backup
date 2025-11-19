#!/usr/bin/env python
"""Entry point script for PyInstaller executable."""
import sys
import os

# When running as PyInstaller bundle, __file__ points to the executable
# We need to handle both development and bundled scenarios
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    base_path = sys._MEIPASS
else:
    # Running as script
    base_path = os.path.dirname(os.path.abspath(__file__))

# Add db-backup directory to path for imports
db_backup_path = os.path.join(base_path, 'db-backup')
if os.path.exists(db_backup_path):
    sys.path.insert(0, base_path)

# Import and run the CLI
# Try multiple import strategies to handle different scenarios
try:
    # Strategy 1: Try as installed package (db_backup)
    from db_backup.interface.cli import backup_cli
except ImportError:
    try:
        # Strategy 2: Import from db-backup directory directly
        sys.path.insert(0, db_backup_path)
        from interface.cli import backup_cli
    except ImportError:
        # Strategy 3: Try relative import from parent
        sys.path.insert(0, os.path.dirname(base_path))
        from db_backup.interface.cli import backup_cli

if __name__ == "__main__":
    backup_cli()

