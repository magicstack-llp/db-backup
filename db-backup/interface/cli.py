
import click
import os
import pathlib
import shutil
import subprocess
import sys
import datetime
import re
from dotenv import load_dotenv, dotenv_values

# Support running both as a package (relative imports) and as a script (absolute imports)
try:  # package context
    from ..data.database_gateway import DatabaseGateway  # type: ignore
    from ..data.storage_gateway import StorageGateway  # type: ignore
    from ..app.backup_use_case import BackupUseCase  # type: ignore
except Exception:  # script context
    from data.database_gateway import DatabaseGateway  # type: ignore
    from data.storage_gateway import StorageGateway  # type: ignore
    from app.backup_use_case import BackupUseCase  # type: ignore

def _default_config_path() -> str:
    # Follow XDG on Linux/macOS; fallback to ~/.config
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".config"
    return str(base / "database-backup" / ".env")


def _ensure_config_file(config_path: str) -> None:
    if os.path.exists(config_path):
        return

    click.echo(f"Config not found at {config_path} — let's create one.")
    # Ensure directory exists
    cfg_dir = os.path.dirname(config_path)
    if cfg_dir and not os.path.exists(cfg_dir):
        os.makedirs(cfg_dir, exist_ok=True)

    _init_config_interactive(config_path)


def _init_config_interactive(config_path: str) -> None:
    """Interactively create or update a .env config file at config_path."""
    # Load existing values (if any) to use as defaults
    existing = dotenv_values(config_path) if os.path.exists(config_path) else {}

    if os.path.exists(config_path):
        click.echo(f"Config exists at {config_path}.")
        if not click.confirm("Do you want to overwrite it?", default=False):
            click.echo("Aborted. Existing config left unchanged.")
            return

    # Ensure directory exists
    cfg_dir = os.path.dirname(config_path)
    if cfg_dir and not os.path.exists(cfg_dir):
        os.makedirs(cfg_dir, exist_ok=True)

    # Prompts with defaults from existing values when available
    mysql_host = click.prompt("MySQL host", default=existing.get("MYSQL_HOST", "localhost"))
    mysql_port = click.prompt("MySQL port", default=int(existing.get("MYSQL_PORT", 3306)), type=int)
    mysql_user = click.prompt("MySQL user", default=existing.get("MYSQL_USER", "root"))
    mysql_password = click.prompt("MySQL password", hide_input=True, default=existing.get("MYSQL_PASSWORD", ""))

    backup_driver = click.prompt(
        "Backup driver (local/s3)",
        type=click.Choice(["local", "s3"], case_sensitive=False),
        default=(existing.get("BACKUP_DRIVER", "local") or "local"),
    ).lower()

    backup_dir = None
    s3_bucket = None
    s3_path = None
    aws_access_key_id = None
    aws_secret_access_key = None

    if backup_driver == "local":
        backup_dir = click.prompt("Local backup directory", default=existing.get("BACKUP_DIR", "./backups"))
    else:
        s3_bucket = click.prompt("S3 bucket name", default=existing.get("S3_BUCKET", ""))
        s3_path = click.prompt("S3 base path", default=existing.get("S3_PATH", "backups"))
        aws_access_key_id = click.prompt("AWS Access Key ID", default=existing.get("AWS_ACCESS_KEY_ID", ""))
        aws_secret_access_key = click.prompt("AWS Secret Access Key", hide_input=True, default=existing.get("AWS_SECRET_ACCESS_KEY", ""))

    retention_default = int(existing.get("RETENTION_COUNT", 5)) if str(existing.get("RETENTION_COUNT", "")).strip() else 5
    retention_count = click.prompt("Retention count (how many backups to keep)", default=retention_default, type=int)

    # Suggest mysqldump path if found
    suggested_dump = existing.get("MYSQLDUMP_PATH") or shutil.which("mysqldump") or "/opt/homebrew/opt/mysql-client/bin/mysqldump"
    mysqldump_path = click.prompt("mysqldump path", default=suggested_dump)

    excluded_dbs = click.prompt(
        "Excluded databases (comma-separated, besides system DBs)",
        default=existing.get("EXCLUDED_DATABASES", ""),
    )

    # Write .env
    lines = [
        f"MYSQL_HOST={mysql_host}",
        f"MYSQL_PORT={mysql_port}",
        f"MYSQL_USER={mysql_user}",
        f"MYSQL_PASSWORD={mysql_password}",
        f"BACKUP_DRIVER={backup_driver}",
        f"RETENTION_COUNT={retention_count}",
        f"MYSQLDUMP_PATH={mysqldump_path}",
        f"EXCLUDED_DATABASES={excluded_dbs}",
    ]
    if backup_driver == "local":
        lines.append(f"BACKUP_DIR={backup_dir}")
    else:
        lines.extend([
            f"S3_BUCKET={s3_bucket}",
            f"S3_PATH={s3_path}",
            f"AWS_ACCESS_KEY_ID={aws_access_key_id}",
            f"AWS_SECRET_ACCESS_KEY={aws_secret_access_key}",
        ])

    with open(config_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    click.echo(f"Created config at {config_path}")


def _resolve_executable() -> str:
    """Find a robust way to run the CLI from cron.

    Prefer the installed console script `db-backup`; fallback to `python -m db_backup`.
    """
    exe = shutil.which("db-backup")
    if exe:
        return exe
    py = shutil.which("python") or sys.executable
    return f"{py} -m db_backup"


def _times_to_cron_entries(times: list[str]) -> list[tuple[int, int]]:
    entries: list[tuple[int, int]] = []
    for t in times:
        t = t.strip()
        if not t:
            continue
        if not re.match(r"^\d{2}:\d{2}$", t):
            raise click.ClickException(f"Invalid time format: '{t}'. Use HH:MM 24h, e.g. 03:00")
        hh, mm = t.split(":")
        h = int(hh)
        m = int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise click.ClickException(f"Time out of range: '{t}'")
        entries.append((m, h))
    return entries


def _install_crontab(lines: list[str]) -> None:
    """Install or update user's crontab with a managed db-backup block."""
    # Read existing crontab
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = res.stdout if res.returncode == 0 else ""

    # Remove existing managed block
    existing = re.sub(r"(?s)# BEGIN db-backup.*?# END db-backup\s*", "", existing)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    managed_block = [
        "# BEGIN db-backup (managed)",
        f"# Generated on {timestamp}",
        *lines,
        "# END db-backup (managed)",
        "",
    ]
    new_cron = existing.rstrip() + "\n" + "\n".join(managed_block)

    apply_res = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True)
    if apply_res.returncode != 0:
        err = apply_res.stderr.strip() or "failed to install crontab"
        raise click.ClickException(f"Unable to install crontab: {err}")


def _is_cron_expression(s: str) -> bool:
    # Basic 5-field crontab expression detection
    parts = s.strip().split()
    return len(parts) == 5


def _setup_cron_interactive(config_path: str) -> None:
    click.echo("Let's set up your cron schedule for db-backup.")
    # Ensure config exists so cron can use it
    _ensure_config_file(config_path)

    # Choose storage type
    storage_choice = click.prompt(
        "Storage to use (local/s3/config)",
        type=click.Choice(["local", "s3", "config"], case_sensitive=False),
        default="config",
    ).lower()

    # Schedule input: accept a full cron expression or comma-separated HH:MM list
    schedule_str = click.prompt(
        "Enter a cron expression (5 fields) or times (24h HH:MM) comma-separated",
        default="0 3,15 * * *",
    ).strip()

    cron_lines: list[str] = []
    if _is_cron_expression(schedule_str):
        cron_expr = schedule_str
    else:
        times = [s.strip() for s in schedule_str.split(",") if s.strip()]
        cron_pairs = _times_to_cron_entries(times)
        cron_expr = None  # use pairs instead

    exe = _resolve_executable()
    # Build command
    storage_flag = ""
    if storage_choice in ("local", "s3"):
        storage_flag = f" --{storage_choice}"
    cmd = f"{exe} --config \"{config_path}\"{storage_flag}"

    if cron_expr is not None:
        cron_lines = [f"{cron_expr} {cmd}"]
    else:
        cron_lines = [f"{m} {h} * * * {cmd}" for (m, h) in cron_pairs]
    _install_crontab(cron_lines)
    click.echo("Cron entries installed:")
    for ln in cron_lines:
        click.echo(f"  {ln}")


@click.command()
@click.option('--config', default=None, help='Path to the .env file (defaults to ~/.config/database-backup/.env).')
@click.option('--retention', type=int, help='Number of backups to retain.')
@click.option('--local', 'storage_type', flag_value='local', help='Store backups locally.')
@click.option('--s3', 'storage_type', flag_value='s3', help='Store backups in S3.')
@click.option('--backup-dir', help='Local directory to store backups in.')
@click.option('--mysqldump', 'mysqldump_path', help='Path to mysqldump binary (overrides MYSQLDUMP_PATH).')
@click.option('--compress/--no-compress', default=True, show_default=True, help='Compress backups with gzip.')
@click.option('--cron', is_flag=True, help='Interactively set up crontab (default daily at 03:00 and 15:00).')
@click.option('--init', is_flag=True, help='Interactively create/update the config file and exit.')
def backup_cli(config, retention, storage_type, backup_dir, mysqldump_path, compress, cron, init):
    # Resolve config path; env var DATABASE_BACKUP_CONFIG can override default
    if not config:
        config = os.getenv("DATABASE_BACKUP_CONFIG") or _default_config_path()
    if init:
        _init_config_interactive(config)
        return
    if cron:
        _setup_cron_interactive(config)
        return
    _ensure_config_file(config)
    load_dotenv(dotenv_path=config)

    mysql_host = os.getenv("MYSQL_HOST")
    mysql_port_env = os.getenv("MYSQL_PORT")
    try:
        mysql_port = int(mysql_port_env) if mysql_port_env else 3306
    except ValueError:
        mysql_port = 3306
    mysql_user = os.getenv("MYSQL_USER")
    mysql_password = os.getenv("MYSQL_PASSWORD")
    retention_count = retention or int(os.getenv("RETENTION_COUNT", 5))

    effective_mysqldump = mysqldump_path or os.getenv("MYSQLDUMP_PATH")
    excluded_env = os.getenv("EXCLUDED_DATABASES", "")
    excluded_list = [x.strip() for x in excluded_env.split(",") if x.strip()] if excluded_env else []
    db_gateway = DatabaseGateway(
        mysql_host,
        mysql_port,
        mysql_user,
        mysql_password,
        mysqldump_path=effective_mysqldump,
        excluded_databases=excluded_list,
    )

    # Allow storage type to come from config if not provided as a flag
    if not storage_type:
        storage_type = (os.getenv("BACKUP_DRIVER") or "").lower() or None

    if storage_type == 'local':
        backup_dir = backup_dir or os.getenv("BACKUP_DIR")
        storage_gateway = StorageGateway(backup_dir=backup_dir)
        use_case = BackupUseCase(db_gateway, storage_gateway)
        use_case.execute(retention_count, backup_dir=backup_dir, compress=compress)
    elif storage_type == 's3':
        s3_bucket = os.getenv("S3_BUCKET")
        s3_path = os.getenv("S3_PATH")
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        storage_gateway = StorageGateway(
            s3_bucket=s3_bucket,
            s3_path=s3_path,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        use_case = BackupUseCase(db_gateway, storage_gateway)
        use_case.execute(retention_count, s3_bucket=s3_bucket, s3_path=s3_path, compress=compress)
    else:
        click.echo("Please specify a storage type: --local or --s3")
