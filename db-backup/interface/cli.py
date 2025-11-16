
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
    from ..data.connection_manager import ConnectionManager  # type: ignore
except Exception:  # script context
    from data.database_gateway import DatabaseGateway  # type: ignore
    from data.storage_gateway import StorageGateway  # type: ignore
    from app.backup_use_case import BackupUseCase  # type: ignore
    from data.connection_manager import ConnectionManager  # type: ignore

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
    """Interactively create or update a .env config file at config_path (storage/global settings only)."""
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

    click.echo("Setting up storage and global configuration...")
    click.echo("(Database connections are managed separately with --add command)")

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

    # Write .env (only storage/global settings)
    lines = [
        f"BACKUP_DRIVER={backup_driver}",
        f"RETENTION_COUNT={retention_count}",
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
    click.echo("Use 'db-backup --add' to add database connections.")


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

    # Check for connections
    conn_manager = ConnectionManager()
    connections = conn_manager.list_connections()
    
    connection_name = None
    if connections:
        if len(connections) == 1:
            connection_name = connections[0]
            click.echo(f"Using connection: {connection_name}")
        else:
            click.echo("Available connections:")
            for i, conn in enumerate(connections, 1):
                click.echo(f"  {i}. {conn}")
            choice = click.prompt("Select connection for cron", type=int)
            if 1 <= choice <= len(connections):
                connection_name = connections[choice - 1]
            else:
                click.echo("Invalid selection.")
                return
    else:
        click.echo("No connections found. Please add a connection first with 'db-backup --add'")
        return

    # Choose storage type
    storage_choice = click.prompt(
        "Storage to use (local/s3/config)",
        type=click.Choice(["local", "s3", "config"], case_sensitive=False),
        default="config",
    ).lower()

    # Schedule input: accept a full cron expression or comma-separated HH:MM list
    default_schedule = "0 3,15 * * *"
    try:
        schedule_input = click.prompt(
            "Enter a cron expression (5 fields) or times (24h HH:MM) comma-separated",
            default=default_schedule,
            show_default=True,
        )
    except (KeyboardInterrupt, EOFError):
        schedule_input = default_schedule
    
    # Handle empty input - ensure we always have a valid schedule
    schedule_str = schedule_input.strip() if schedule_input and schedule_input.strip() else default_schedule
    if not schedule_str or len(schedule_str.split()) == 0:
        schedule_str = default_schedule
        click.echo(f"Using default schedule: {default_schedule}")

    cron_lines: list[str] = []
    cron_expr = None
    cron_pairs = []
    
    # Validate and parse the schedule
    if _is_cron_expression(schedule_str):
        cron_expr = schedule_str
    else:
        times = [s.strip() for s in schedule_str.split(",") if s.strip()]
        if not times:
            # If no valid times, use default
            cron_expr = default_schedule
        else:
            try:
                cron_pairs = _times_to_cron_entries(times)
                if not cron_pairs:
                    # If parsing failed, use default
                    cron_expr = default_schedule
            except (click.ClickException, ValueError) as e:
                # If parsing failed, use default
                click.echo(f"Warning: Invalid schedule format. Using default: {default_schedule}")
                cron_expr = default_schedule

    exe = _resolve_executable()
    # Build command
    storage_flag = ""
    if storage_choice in ("local", "s3"):
        storage_flag = f" --{storage_choice}"
    cmd = f"{exe} backup --config \"{config_path}\" --connection {connection_name}{storage_flag}"

    # Ensure we have a valid cron expression
    if cron_expr is not None and cron_expr.strip():
        # Validate it's a proper cron expression
        if _is_cron_expression(cron_expr):
            cron_lines = [f"{cron_expr} {cmd}"]
        else:
            # Invalid format, use default
            cron_expr = default_schedule
            cron_lines = [f"{cron_expr} {cmd}"]
    elif cron_pairs:
        cron_lines = [f"{m} {h} * * * {cmd}" for (m, h) in cron_pairs]
    else:
        # Fallback to default if everything else fails
        cron_expr = default_schedule
        cron_lines = [f"{cron_expr} {cmd}"]
    
    # Final validation - ensure we have valid cron lines
    if not cron_lines or not all(ln.strip() for ln in cron_lines):
        click.echo("Error: No valid cron schedule provided. Using default: 0 3,15 * * *")
        cron_lines = [f"{default_schedule} {cmd}"]
    
    # Validate each cron line has proper format (5 fields + command)
    validated_lines = []
    for line in cron_lines:
        parts = line.split()
        if len(parts) >= 6:  # 5 cron fields + command (which may have spaces)
            validated_lines.append(line)
        else:
            click.echo(f"Warning: Invalid cron line format, using default: {line}")
            validated_lines.append(f"{default_schedule} {cmd}")
    
    if not validated_lines:
        validated_lines = [f"{default_schedule} {cmd}"]
    
    _install_crontab(validated_lines)
    click.echo("Cron entries installed:")
    for ln in validated_lines:
        click.echo(f"  {ln}")


@click.group()
@click.pass_context
def cli(ctx):
    """Database backup tool with multiple connection support."""
    ctx.ensure_object(dict)


@cli.command()
@click.option('--config', default=None, help='Path to the .env file (defaults to ~/.config/database-backup/.env).')
@click.option('--connection', 'connection_name', help='Name of the connection to use for backup.')
@click.option('--retention', type=int, help='Number of backups to retain.')
@click.option('--local', 'storage_type', flag_value='local', help='Store backups locally.')
@click.option('--s3', 'storage_type', flag_value='s3', help='Store backups in S3.')
@click.option('--backup-dir', help='Local directory to store backups in.')
@click.option('--mysqldump', 'mysqldump_path', help='Path to mysqldump binary.')
@click.option('--compress/--no-compress', default=True, show_default=True, help='Compress backups with gzip.')
def backup(config, connection_name, retention, storage_type, backup_dir, mysqldump_path, compress):
    """Run backup for a database connection."""
    # Resolve config path; env var DATABASE_BACKUP_CONFIG can override default
    if not config:
        config = os.getenv("DATABASE_BACKUP_CONFIG") or _default_config_path()
    
    _ensure_config_file(config)
    load_dotenv(dotenv_path=config)

    # Load connection from JSON
    conn_manager = ConnectionManager()
    
    if not connection_name:
        # If no connection specified, list available and prompt
        connections = conn_manager.list_connections()
        if not connections:
            click.echo("No connections found. Use 'db-backup --add' to add a connection.")
            return
        if len(connections) == 1:
            connection_name = connections[0]
            click.echo(f"Using connection: {connection_name}")
        else:
            click.echo("Available connections:")
            for i, conn in enumerate(connections, 1):
                click.echo(f"  {i}. {conn}")
            choice = click.prompt("Select connection", type=int)
            if 1 <= choice <= len(connections):
                connection_name = connections[choice - 1]
            else:
                click.echo("Invalid selection.")
                return
    
    conn_data = conn_manager.get_connection(connection_name)
    if not conn_data:
        click.echo(f"Connection '{connection_name}' not found. Use 'db-backup --list' to see available connections.")
        return

    mysql_host = conn_data["host"]
    mysql_port = conn_data.get("port", 3306)
    mysql_user = conn_data["user"]
    mysql_password = conn_data["password"]
    retention_count = retention or int(os.getenv("RETENTION_COUNT", 5))

    effective_mysqldump = mysqldump_path or conn_data.get("mysqldump_path") or os.getenv("MYSQLDUMP_PATH")
    excluded_list = conn_data.get("excluded_databases", [])
    
    db_gateway = DatabaseGateway(
        mysql_host,
        mysql_port,
        mysql_user,
        mysql_password,
        mysqldump_path=effective_mysqldump,
        excluded_databases=excluded_list,
    )

    # Determine storage type with priority: CLI flag > connection setting > .env
    if not storage_type:
        # Check connection-specific storage driver
        storage_type = conn_data.get("storage_driver")
        if storage_type:
            storage_type = storage_type.lower()
        else:
            # Fall back to .env
            storage_type = (os.getenv("BACKUP_DRIVER") or "").lower() or None

    if storage_type == 'local':
        # Priority: CLI flag > connection path (with backward compat) > .env
        # Support backward compatibility: check old backup_dir field first
        connection_path = conn_data.get("path") or conn_data.get("backup_dir")
        effective_backup_dir = backup_dir or connection_path or os.getenv("BACKUP_DIR")
        if not effective_backup_dir:
            click.echo("Please specify --backup-dir, set path in connection, or set BACKUP_DIR in .env")
            return
        storage_gateway = StorageGateway(backup_dir=effective_backup_dir)
        use_case = BackupUseCase(db_gateway, storage_gateway)
        use_case.execute(retention_count, backup_dir=effective_backup_dir, compress=compress)
    elif storage_type == 's3':
        # Priority: connection setting > .env
        effective_s3_bucket = conn_data.get("s3_bucket") or os.getenv("S3_BUCKET")
        # Support backward compatibility: check old s3_path field first
        connection_path = conn_data.get("path") or conn_data.get("s3_path")
        effective_s3_path = connection_path or os.getenv("S3_PATH")
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        if not effective_s3_bucket:
            click.echo("Please set s3_bucket in connection, set S3_BUCKET in .env, or use --s3 with proper configuration")
            return
        storage_gateway = StorageGateway(
            s3_bucket=effective_s3_bucket,
            s3_path=effective_s3_path,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )
        use_case = BackupUseCase(db_gateway, storage_gateway)
        use_case.execute(retention_count, s3_bucket=effective_s3_bucket, s3_path=effective_s3_path, compress=compress)
    else:
        click.echo("Please specify a storage type: --local or --s3, set storage_driver in connection, or set BACKUP_DRIVER in .env")


@cli.command()
@click.option('--name', prompt='Connection name', help='Name for this connection.')
@click.option('--host', prompt='MySQL host', default='localhost', help='MySQL server host.')
@click.option('--port', prompt='MySQL port', default=3306, type=int, help='MySQL server port.')
@click.option('--user', prompt='MySQL user', default='root', help='MySQL username.')
@click.option('--password', prompt='MySQL password', hide_input=True, help='MySQL password.')
@click.option('--mysqldump', 'mysqldump_path', help='Path to mysqldump binary.')
@click.option('--excluded', help='Comma-separated list of databases to exclude (besides system DBs).')
@click.option('--storage-driver', type=click.Choice(['local', 's3'], case_sensitive=False), help='Preferred storage driver for this connection (local/s3).')
@click.option('--path', help='Storage path: backup directory for local storage or S3 path prefix (overrides .env).')
@click.option('--s3-bucket', help='Preferred S3 bucket for this connection (overrides .env).')
def add(name, host, port, user, password, mysqldump_path, excluded, storage_driver, path, s3_bucket):
    """Add a new database connection."""
    conn_manager = ConnectionManager()
    
    existing = conn_manager.get_connection(name)
    if existing:
        if not click.confirm(f"Connection '{name}' already exists. Overwrite?", default=False):
            click.echo("Aborted.")
            return
        # Use update instead
        excluded_list = []
        if excluded:
            excluded_list = [x.strip() for x in excluded.split(",") if x.strip()]
        
        if not mysqldump_path:
            mysqldump_path = existing.get("mysqldump_path") or shutil.which("mysqldump") or "/opt/homebrew/opt/mysql-client/bin/mysqldump"
            if not click.confirm(f"Use mysqldump at '{mysqldump_path}'?", default=True):
                mysqldump_path = click.prompt("mysqldump path", default=mysqldump_path)
        
        # Interactive prompts for storage settings if not provided
        if storage_driver is None:
            existing_driver = existing.get("storage_driver")
            if existing_driver:
                if click.confirm(f"Keep existing storage driver '{existing_driver}'?", default=True):
                    storage_driver = existing_driver
                else:
                    storage_driver = click.prompt(
                        "Storage driver",
                        type=click.Choice(['local', 's3'], case_sensitive=False),
                        default=existing_driver or 'local'
                    ).lower()
            else:
                if click.confirm("Do you want to set a preferred storage driver for this connection?", default=False):
                    storage_driver = click.prompt(
                        "Storage driver",
                        type=click.Choice(['local', 's3'], case_sensitive=False),
                        default='local'
                    ).lower()
                else:
                    # Preserve None if user doesn't want to set it
                    storage_driver = None
        
        # Use effective storage_driver for path prompts (use existing if storage_driver is None)
        effective_driver = storage_driver or existing.get("storage_driver")
        
        if path is None:
            # Support backward compatibility: check old fields first
            existing_path = existing.get("path") or existing.get("backup_dir") or existing.get("s3_path")
            if existing_path:
                if not click.confirm(f"Keep existing path '{existing_path}'?", default=True):
                    if effective_driver:
                        if effective_driver == 'local':
                            path = click.prompt("Backup directory path", default=existing_path)
                        else:
                            path = click.prompt("S3 path prefix", default=existing_path)
                    else:
                        path = click.prompt("Storage path", default=existing_path)
                else:
                    path = existing_path
            elif effective_driver:
                # Only prompt if storage_driver is set
                if effective_driver == 'local':
                    path = click.prompt(
                        "Backup directory path",
                        default="",
                        show_default=False
                    )
                    if not path.strip():
                        path = None
                elif effective_driver == 's3':
                    path = click.prompt(
                        "S3 path prefix",
                        default="",
                        show_default=False
                    )
                    if not path.strip():
                        path = None
        
        if s3_bucket is None:
            existing_bucket = existing.get("s3_bucket")
            if existing_bucket:
                if not click.confirm(f"Keep existing S3 bucket '{existing_bucket}'?", default=True):
                    s3_bucket = click.prompt("S3 bucket name", default=existing_bucket)
                else:
                    s3_bucket = existing_bucket
            elif effective_driver == 's3':
                s3_bucket = click.prompt(
                    "S3 bucket name",
                    default="",
                    show_default=False
                )
                if not s3_bucket.strip():
                    s3_bucket = None
        
        success = conn_manager.update_connection(
            name=name,
            host=host,
            port=port,
            user=user,
            password=password,
            mysqldump_path=mysqldump_path,
            excluded_databases=excluded_list,
            storage_driver=storage_driver,
            path=path,
            s3_bucket=s3_bucket
        )
        if success:
            click.echo(f"Connection '{name}' updated successfully.")
        else:
            click.echo(f"Failed to update connection '{name}'.")
        return
    
    excluded_list = []
    if excluded:
        excluded_list = [x.strip() for x in excluded.split(",") if x.strip()]
    
    # Suggest mysqldump path if not provided
    if not mysqldump_path:
        mysqldump_path = shutil.which("mysqldump") or "/opt/homebrew/opt/mysql-client/bin/mysqldump"
        if not click.confirm(f"Use mysqldump at '{mysqldump_path}'?", default=True):
            mysqldump_path = click.prompt("mysqldump path", default=mysqldump_path)
    
    # Interactive prompts for storage settings if not provided
    if storage_driver is None:
        if click.confirm("Do you want to set a preferred storage driver for this connection?", default=False):
            storage_driver = click.prompt(
                "Storage driver",
                type=click.Choice(['local', 's3'], case_sensitive=False),
                default='local'
            ).lower()
    
    if storage_driver:
        if storage_driver == 'local':
            if path is None:
                path = click.prompt(
                    "Backup directory path",
                    default="",
                    show_default=False
                )
                if not path.strip():
                    path = None
            if s3_bucket:
                s3_bucket = None  # Clear s3_bucket if local storage
        elif storage_driver == 's3':
            if s3_bucket is None:
                s3_bucket = click.prompt(
                    "S3 bucket name",
                    default="",
                    show_default=False
                )
                if not s3_bucket.strip():
                    s3_bucket = None
            if path is None:
                path = click.prompt(
                    "S3 path prefix",
                    default="",
                    show_default=False
                )
                if not path.strip():
                    path = None
    
    success = conn_manager.add_connection(
        name=name,
        host=host,
        port=port,
        user=user,
        password=password,
        mysqldump_path=mysqldump_path,
        excluded_databases=excluded_list,
        storage_driver=storage_driver,
        path=path,
        s3_bucket=s3_bucket
    )
    
    if success:
        click.echo(f"Connection '{name}' added successfully.")
    else:
        click.echo(f"Connection '{name}' already exists. Use --remove first or update it.")


@cli.command()
@click.option('--name', prompt='Connection name', help='Name of the connection to remove.')
def remove(name):
    """Remove a database connection."""
    conn_manager = ConnectionManager()
    
    if not conn_manager.get_connection(name):
        click.echo(f"Connection '{name}' not found.")
        return
    
    if click.confirm(f"Are you sure you want to remove connection '{name}'?", default=False):
        if conn_manager.remove_connection(name):
            click.echo(f"Connection '{name}' removed successfully.")
        else:
            click.echo(f"Failed to remove connection '{name}'.")
    else:
        click.echo("Aborted.")


@cli.command(name='list')
def list_connections():
    """List all database connections."""
    conn_manager = ConnectionManager()
    connections = conn_manager.list_connections()
    
    if not connections:
        click.echo("No connections found. Use 'db-backup add' to add a connection.")
        return
    
    click.echo("Available connections:")
    for conn_name in connections:
        conn_data = conn_manager.get_connection(conn_name)
        storage_info = ""
        if conn_data.get("storage_driver"):
            storage_info = f" [storage: {conn_data['storage_driver']}"
            # Support backward compatibility: check old fields first
            connection_path = conn_data.get("path") or conn_data.get("backup_dir") or conn_data.get("s3_path")
            if connection_path:
                storage_info += f", path: {connection_path}"
            if conn_data['storage_driver'] == 's3' and conn_data.get("s3_bucket"):
                storage_info += f", bucket: {conn_data['s3_bucket']}"
            storage_info += "]"
        click.echo(f"  {conn_name}: {conn_data['user']}@{conn_data['host']}:{conn_data['port']}{storage_info}")


@cli.command()
@click.option('--config', default=None, help='Path to the .env file (defaults to ~/.config/database-backup/.env).')
def init(config):
    """Interactively create/update the config file (storage/global settings only)."""
    if not config:
        config = os.getenv("DATABASE_BACKUP_CONFIG") or _default_config_path()
    _init_config_interactive(config)


@cli.command()
@click.option('--config', default=None, help='Path to the .env file (defaults to ~/.config/database-backup/.env).')
def cron(config):
    """Interactively set up crontab (default daily at 03:00 and 15:00)."""
    if not config:
        config = os.getenv("DATABASE_BACKUP_CONFIG") or _default_config_path()
    _setup_cron_interactive(config)


# For backward compatibility, make backup_cli point to the group
backup_cli = cli
