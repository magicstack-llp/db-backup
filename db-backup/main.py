"""Entry point for running the backup CLI as a script.

Supports both:
"""

try:
    # When executed as a module (python -m db_backup)
    from .interface.cli import backup_cli  # type: ignore
except Exception:
    # When executed directly as a script from inside the package folder
    from interface.cli import backup_cli  # type: ignore

if __name__ == "__main__":
    backup_cli()
