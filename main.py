"""Entry point for running the backup CLI as a script.

Supports both:
- python main.py ... (when run from within the package folder)
- python -m database_backup ... (via __main__.py)
"""

try:
    # When executed as a module (python -m database_backup)
    from .interface.cli import backup_cli  # type: ignore
except Exception:
    # When executed directly as a script from inside the package folder
    from interface.cli import backup_cli  # type: ignore

if __name__ == "__main__":
    backup_cli()
