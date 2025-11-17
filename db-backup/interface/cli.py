
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
    # Validate input lines are not empty
    if not lines:
        raise click.ClickException("No cron lines to install")
    
    # Filter out any empty lines
    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        raise click.ClickException("No valid cron lines to install")
    
    # Read existing crontab
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = res.stdout if res.returncode == 0 else ""

    # Remove only comment markers (if any exist)
    existing = re.sub(r"(?s)# BEGIN db-backup.*?# END db-backup\s*", "", existing)
    
    # Clean up existing crontab - remove comment markers but keep all cron entries
    existing_lines = existing.split('\n') if existing else []
    filtered_existing = []
    for line in existing_lines:
        line_stripped = line.strip()
        # Skip only comment markers
        if (line_stripped.startswith('# BEGIN db-backup') or 
            line_stripped.startswith('# END db-backup') or
            line_stripped.startswith('# Generated on')):
            continue
        # Keep all other lines including existing db-backup cron entries
        filtered_existing.append(line)
    
    existing = '\n'.join(filtered_existing).rstrip()

    # Prepare new cron lines to append
    new_lines = []
    for line in lines:
        if line.strip():  # Only add non-empty lines
            new_lines.append(line)

    # Append new lines to existing crontab (don't replace)
    if existing:
        # Check for exact duplicates before appending
        existing_set = set(existing.split('\n'))
        lines_to_add = []
        for line in new_lines:
            if line not in existing_set:
                lines_to_add.append(line)
        
        if lines_to_add:
            new_cron = existing + "\n" + "\n".join(lines_to_add)
        else:
            new_cron = existing  # No new lines to add
    else:
        new_cron = "\n".join(new_lines) if new_lines else ""

    # Validate the final crontab before installing
    # Check that all non-comment lines have at least 5 fields
    for line_num, line in enumerate(new_cron.split('\n'), 1):
        line = line.strip()
        if line and not line.startswith('#'):
            parts = line.split()
            if len(parts) < 5:
                raise click.ClickException(
                    f"Invalid crontab line {line_num}: '{line}' (expected at least 5 fields)"
                )

    apply_res = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True)
    if apply_res.returncode != 0:
        err = apply_res.stderr.strip() or "failed to install crontab"
        # Show the problematic crontab for debugging
        click.echo(f"\nCrontab content that failed to install:")
        click.echo(new_cron)
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
    
    # Get schedule input with proper default handling
    schedule_input = click.prompt(
        "Enter a cron expression (5 fields) or times (24h HH:MM) comma-separated",
        default=default_schedule,
        show_default=True,
    )
    
    # Normalize the input - handle empty strings, whitespace, etc.
    if schedule_input:
        schedule_str = schedule_input.strip()
    else:
        schedule_str = default_schedule
    
    # If empty after stripping, use default
    if not schedule_str:
        schedule_str = default_schedule
        click.echo(f"Using default schedule: {default_schedule}")

    # Parse and validate the schedule
    cron_expr = None
    cron_pairs = []
    
    # Check if it's a cron expression (5 fields)
    if _is_cron_expression(schedule_str):
        cron_expr = schedule_str
    else:
        # Try to parse as time list (HH:MM format)
        times = [s.strip() for s in schedule_str.split(",") if s.strip()]
        if times:
            try:
                cron_pairs = _times_to_cron_entries(times)
            except (click.ClickException, ValueError) as e:
                click.echo(f"Warning: Invalid time format. Using default: {default_schedule}")
                cron_expr = default_schedule
        else:
            # Empty or invalid, use default
            cron_expr = default_schedule

    # Build the command
    exe = _resolve_executable()
    storage_flag = ""
    if storage_choice in ("local", "s3"):
        storage_flag = f" --{storage_choice}"
    cmd = f"{exe} backup --config \"{config_path}\" --connection {connection_name}{storage_flag}"

    # Generate cron lines - ensure we always have a valid expression
    cron_lines = []
    
    if cron_expr:
        # Use the cron expression directly
        if _is_cron_expression(cron_expr):
            cron_lines.append(f"{cron_expr} {cmd}")
        else:
            # Invalid, use default
            cron_lines.append(f"{default_schedule} {cmd}")
    elif cron_pairs:
        # Use time pairs to generate cron lines
        for m, h in cron_pairs:
            cron_lines.append(f"{m} {h} * * * {cmd}")
    else:
        # Fallback to default
        cron_lines.append(f"{default_schedule} {cmd}")
    
    # Final validation - ensure all lines are valid
    validated_lines = []
    for line in cron_lines:
        line = line.strip()
        if not line:
            continue
            
        # Split and validate: should have at least 6 parts (5 cron fields + command start)
        parts = line.split(None, 5)  # Split into max 6 parts
        if len(parts) >= 6:
            # Validate the first 5 parts are valid cron fields
            minute, hour, day, month, weekday = parts[0], parts[1], parts[2], parts[3], parts[4]
            # Basic validation - ensure they're not empty
            if all(field.strip() for field in [minute, hour, day, month, weekday]):
                validated_lines.append(line)
            else:
                click.echo(f"Warning: Invalid cron fields in line, using default")
                validated_lines.append(f"{default_schedule} {cmd}")
        else:
            click.echo(f"Warning: Invalid cron line format (expected 5 fields + command), using default")
            validated_lines.append(f"{default_schedule} {cmd}")
    
    # Ensure we have at least one valid line
    if not validated_lines:
        validated_lines = [f"{default_schedule} {cmd}"]
    
    # Debug: show what will be installed
    click.echo("\nCron entries to be installed:")
    for ln in validated_lines:
        click.echo(f"  {ln}")
    click.echo()
    
    _install_crontab(validated_lines)
    click.echo("✓ Cron entries installed successfully!")


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
    
    # Extract SSH configuration
    ssh_host = conn_data.get("ssh_host")
    ssh_port = conn_data.get("ssh_port")
    ssh_user = conn_data.get("ssh_user")
    ssh_key_path = conn_data.get("ssh_key_path")
    bastion_host = conn_data.get("bastion_host")
    bastion_port = conn_data.get("bastion_port")
    bastion_user = conn_data.get("bastion_user")
    bastion_key_path = conn_data.get("bastion_key_path")
    
    # Check if SSH is configured but paramiko is not available
    if ssh_host and ssh_user and ssh_key_path:
        try:
            import paramiko  # type: ignore
        except ImportError:
            click.echo("Error: This connection requires SSH tunneling, but 'paramiko' is not installed.", err=True)
            click.echo("", err=True)
            click.echo("To fix this, install paramiko:", err=True)
            click.echo("  pip install paramiko", err=True)
            click.echo("", err=True)
            click.echo("Or install all dependencies:", err=True)
            click.echo("  pip install -e .", err=True)
            return
    
    db_gateway = DatabaseGateway(
        mysql_host,
        mysql_port,
        mysql_user,
        mysql_password,
        mysqldump_path=effective_mysqldump,
        excluded_databases=excluded_list,
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key_path,
        bastion_host=bastion_host,
        bastion_port=bastion_port,
        bastion_user=bastion_user,
        bastion_key_path=bastion_key_path
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
        try:
            use_case.execute(retention_count, backup_dir=effective_backup_dir, compress=compress)
        finally:
            db_gateway.close()
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
        try:
            use_case.execute(retention_count, s3_bucket=effective_s3_bucket, s3_path=effective_s3_path, compress=compress)
        finally:
            db_gateway.close()
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
@click.option('--ssh-host', help='SSH hostname for tunnel (if database is behind SSH).')
@click.option('--ssh-port', type=int, default=22, help='SSH port (default: 22).')
@click.option('--ssh-user', help='SSH username for tunnel.')
@click.option('--ssh-key-path', help='Path to SSH private key file.')
@click.option('--bastion-host', help='Bastion host for double-hop SSH (optional).')
@click.option('--bastion-port', type=int, default=22, help='Bastion SSH port (default: 22).')
@click.option('--bastion-user', help='Bastion SSH username (optional, uses ssh-user if not provided).')
@click.option('--bastion-key-path', help='Bastion SSH key path (optional, uses ssh-key-path if not provided).')
def add(name, host, port, user, password, mysqldump_path, excluded, storage_driver, path, s3_bucket,
        ssh_host, ssh_port, ssh_user, ssh_key_path, bastion_host, bastion_port, bastion_user, bastion_key_path):
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
        
        # Handle SSH configuration
        if ssh_host is None and existing.get("ssh_host"):
            if not click.confirm("Keep existing SSH configuration?", default=True):
                ssh_host = click.prompt("SSH host (leave empty to disable)", default="", show_default=False)
                if not ssh_host.strip():
                    ssh_host = None
                else:
                    ssh_user = ssh_user or click.prompt("SSH user", default=existing.get("ssh_user", ""))
                    ssh_key_path = ssh_key_path or click.prompt("SSH key path", default=existing.get("ssh_key_path", ""))
                    if not ssh_key_path.strip():
                        ssh_key_path = None
            else:
                ssh_host = existing.get("ssh_host")
                ssh_port = existing.get("ssh_port") or 22
                ssh_user = existing.get("ssh_user")
                ssh_key_path = existing.get("ssh_key_path")
                bastion_host = existing.get("bastion_host")
                bastion_port = existing.get("bastion_port")
                bastion_user = existing.get("bastion_user")
                bastion_key_path = existing.get("bastion_key_path")
        elif ssh_host:
            if not ssh_user:
                ssh_user = click.prompt("SSH user", default=existing.get("ssh_user", ""))
            if not ssh_key_path:
                ssh_key_path = click.prompt("SSH key path", default=existing.get("ssh_key_path", ""))
                if not ssh_key_path.strip():
                    ssh_key_path = None
        
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
            s3_bucket=s3_bucket,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_key_path=ssh_key_path,
            bastion_host=bastion_host,
            bastion_port=bastion_port,
            bastion_user=bastion_user,
            bastion_key_path=bastion_key_path
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
    
    # Handle SSH configuration for new connections
    if ssh_host:
        if not ssh_user:
            ssh_user = click.prompt("SSH user")
        if not ssh_key_path:
            ssh_key_path = click.prompt("SSH key path")
            if not ssh_key_path.strip():
                ssh_key_path = None
        if bastion_host and not bastion_user:
            bastion_user = click.prompt("Bastion SSH user", default=ssh_user)
        if bastion_host and not bastion_key_path:
            bastion_key_path = click.prompt("Bastion SSH key path", default=ssh_key_path)
    elif click.confirm("Do you want to configure SSH tunnel for this connection?", default=False):
        ssh_host = click.prompt("SSH host")
        ssh_port = click.prompt("SSH port", default=22, type=int)
        ssh_user = click.prompt("SSH user")
        ssh_key_path = click.prompt("SSH key path")
        if click.confirm("Use bastion host (double-hop SSH)?", default=False):
            bastion_host = click.prompt("Bastion host")
            bastion_port = click.prompt("Bastion port", default=22, type=int)
            bastion_user = click.prompt("Bastion SSH user", default=ssh_user)
            bastion_key_path = click.prompt("Bastion SSH key path", default=ssh_key_path)
    
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
        s3_bucket=s3_bucket,
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key_path,
        bastion_host=bastion_host,
        bastion_port=bastion_port,
        bastion_user=bastion_user,
        bastion_key_path=bastion_key_path
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
