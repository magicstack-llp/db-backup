
import click
import os
import pathlib
import shutil
from dotenv import load_dotenv

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

    # Prompts
    mysql_host = click.prompt("MySQL host", default="localhost")
    mysql_port = click.prompt("MySQL port", default=3306, type=int)
    mysql_user = click.prompt("MySQL user", default="root")
    mysql_password = click.prompt("MySQL password", hide_input=True, default="")

    backup_driver = click.prompt(
        "Backup driver (local/s3)",
        type=click.Choice(["local", "s3"], case_sensitive=False),
        default="local",
    ).lower()

    backup_dir = None
    s3_bucket = None
    s3_path = None
    aws_access_key_id = None
    aws_secret_access_key = None

    if backup_driver == "local":
        backup_dir = click.prompt("Local backup directory", default="./backups")
    else:
        s3_bucket = click.prompt("S3 bucket name")
        s3_path = click.prompt("S3 base path", default="backups")
        aws_access_key_id = click.prompt("AWS Access Key ID", default="")
        aws_secret_access_key = click.prompt("AWS Secret Access Key", hide_input=True, default="")

    retention_count = click.prompt("Retention count (how many backups to keep)", default=5, type=int)

    # Suggest mysqldump path if found
    suggested_dump = shutil.which("mysqldump") or "/opt/homebrew/opt/mysql-client/bin/mysqldump"
    mysqldump_path = click.prompt("mysqldump path", default=suggested_dump)

    excluded_dbs = click.prompt(
        "Excluded databases (comma-separated, besides system DBs)",
        default="",
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


@click.command()
@click.option('--config', default=None, help='Path to the .env file (defaults to ~/.config/database-backup/.env).')
@click.option('--retention', type=int, help='Number of backups to retain.')
@click.option('--local', 'storage_type', flag_value='local', help='Store backups locally.')
@click.option('--s3', 'storage_type', flag_value='s3', help='Store backups in S3.')
@click.option('--backup-dir', help='Local directory to store backups in.')
@click.option('--mysqldump', 'mysqldump_path', help='Path to mysqldump binary (overrides MYSQLDUMP_PATH).')
@click.option('--compress/--no-compress', default=True, show_default=True, help='Compress backups with gzip.')
def backup_cli(config, retention, storage_type, backup_dir, mysqldump_path, compress):
    # Resolve config path; env var DATABASE_BACKUP_CONFIG can override default
    if not config:
        config = os.getenv("DATABASE_BACKUP_CONFIG") or _default_config_path()
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
