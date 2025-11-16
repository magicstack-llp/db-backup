# Database Backup Tool

A command-line tool for backing up MySQL databases to local storage or AWS S3.

## Quick start

1. Install

```bash
pip install database-backup

# upgrade
pip install --upgrade database-backup

```

2. Initialize storage configuration

```bash
# Interactive init (sets up storage/global settings)
db-backup init
```

3. Add a database connection

```bash
# Add your first database connection
db-backup add --name production --host 127.0.0.1 --user root
```

4. Run backup

```bash
db-backup backup --connection production --local   # store on filesystem
db-backup backup --connection production --s3        # store on S3
```

## Features

-   **Multiple database connections**: Manage multiple database connections with separate JSON storage.
-   Back up all MySQL databases, excluding system databases.
-   Store backups in a local directory or an AWS S3 bucket.
-   Create a separate folder for each database.
-   Timestamped backups for easy identification.
-   Automatic cleanup of old backups based on a retention policy.
-   Configuration via `.env` file (storage/global settings) and `connections.json` (database connections).
-   Command-line interface for easy operation.
-   Cron setup for automatic backups.

## Requirements

-   Python 3.10+
-   `mysql-connector-python`
-   `boto3`
-   `python-dotenv`
-   `click`
-   MySQL client tools (provides `mysqldump`)

    On macOS (Homebrew):

    ```bash
    brew install mysql-client
    # Typical binary path: /opt/homebrew/opt/mysql-client/bin/mysqldump (Apple Silicon)
    ```

    On Debian/Ubuntu:

    ```bash
    sudo apt-get update
    sudo apt-get install mysql-client
    # Typical binary path: /usr/bin/mysqldump
    ```

    On Red Hat/CentOS/Fedora:

    ```bash
    sudo dnf install mysql
    #    OR
    sudo dnf install @mysql

    # Typical binary path: /usr/bin/mysqldump
    ```

    On Arch/Manjaro:

    ```bash
    sudo pacman -Syu
    sudo pacman -S mysql
    # Typical binary path: /usr/bin/mysqldump
    ```

## Installation

From PyPI (recommended):

```bash
pip install database-backup
```

From source (optional):

```bash
git clone https://github.com/magicstack-llp/db-backup.git
cd db-backup
pip install -r requirements.txt
```

## Configuration

The tool uses two separate configuration files:

1. **`.env` file**: Stores storage and global settings (S3 credentials, backup directory, retention count, etc.)
   - Default location: `~/.config/database-backup/.env` (or `${XDG_CONFIG_HOME}/database-backup/.env`)
   - Override with `--config` or `DATABASE_BACKUP_CONFIG` env var

2. **`connections.json` file**: Stores database connection details (host, port, user, password, etc.)
   - Default location: `~/.config/database-backup/connections.json`
   - Managed via CLI commands: `add`, `remove`, `list`

### Storage Configuration (.env)

Example `.env` (storage/global settings only):

```env
BACKUP_DRIVER=local  # local, s3
BACKUP_DIR=/Users/<USER>/backups/databases
RETENTION_COUNT=5
S3_BUCKET=mybucket
S3_PATH=backups
AWS_ACCESS_KEY_ID=XXXXXXX
AWS_SECRET_ACCESS_KEY=YYYYYYY
```

### Connection Management

Database connections are stored separately in JSON format. Use these commands:

-   `db-backup add`: Add a new database connection
-   `db-backup remove`: Remove a database connection
-   `db-backup list`: List all database connections

Example `connections.json`:

```json
{
  "production": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "password",
    "mysqldump_path": "/opt/homebrew/opt/mysql-client/bin/mysqldump",
    "excluded_databases": ["db_1", "db_2"],
    "storage_driver": "local",
    "path": "/backups/production"
  },
  "staging": {
    "host": "192.168.1.100",
    "port": 3306,
    "user": "backup_user",
    "password": "secure_password",
    "mysqldump_path": "/usr/bin/mysqldump",
    "excluded_databases": [],
    "storage_driver": "s3",
    "s3_bucket": "my-backup-bucket",
    "path": "staging"
  }
}
```

### Connection Management Commands

#### Add a connection

```bash
db-backup add --name production --host 127.0.0.1 --port 3306 --user root --password mypass
```

Or interactively:

```bash
db-backup add
```

Options:
-   `--name`: Connection name (required)
-   `--host`: MySQL server host (default: localhost)
-   `--port`: MySQL server port (default: 3306)
-   `--user`: MySQL username (default: root)
-   `--password`: MySQL password (will prompt if not provided)
-   `--mysqldump`: Path to mysqldump binary
-   `--excluded`: Comma-separated list of databases to exclude
-   `--storage-driver`: Preferred storage driver for this connection (local/s3)
-   `--path`: Storage path - backup directory for local storage or S3 path prefix (overrides .env)
-   `--s3-bucket`: Preferred S3 bucket for this connection (overrides .env)

#### Remove a connection

```bash
db-backup remove --name production
```

#### List connections

```bash
db-backup list
```

### Cron setup

You can set up cron jobs interactively:

```bash
db-backup cron
```

-   You can enter either:
    -   A full cron expression (5 fields), e.g. `0 3,15 * * *`
    -   Or a comma-separated list of 24h times, e.g. `03:00,15:00`
-   Default schedule: `0 3,15 * * *` (daily at 03:00 and 15:00)
-   You'll be prompted to select a connection and storage type
-   The CLI writes a managed block to your user crontab between `# BEGIN db-backup (managed)` and `# END db-backup (managed)`.
-   It will pass `--config ~/.config/database-backup/.env` by default (or whatever you provide with `--config`).

Helpful: You can use a cron expression generator like [it-tools crontab generator](https://it-tools.tech/crontab-generator) to craft schedules.

## Usage

### Basic backup

```bash
# Backup using a specific connection
db-backup backup --connection production --local

# If only one connection exists, it will be used automatically
db-backup backup --local

# If multiple connections exist, you'll be prompted to select one
db-backup backup --local
```

### Backup options

-   `--connection NAME`: Specify which connection to use (required if multiple connections exist)
-   `--local`: Store backups locally
-   `--s3`: Store backups in S3
-   `--retention N`: Number of backups to retain (overrides .env)
-   `--backup-dir PATH`: Local backup directory (overrides .env)
-   `--mysqldump PATH`: Path to mysqldump binary (overrides connection setting)
-   `--compress/--no-compress`: Compress backups with gzip (default: compress)
-   `--config FILE`: Override .env config file path

### Examples

```bash
# Local backup with specific connection
db-backup backup --connection production --local

# S3 backup
db-backup backup --connection staging --s3

# Override retention count
db-backup backup --connection production --local --retention 10

# Custom backup directory
db-backup backup --connection production --local --backup-dir /custom/path
```

## Architecture

The database backup tool is built using a Clean Architecture approach, which separates the code into four layers:

-   Domain: Contains the core business logic and entities of the application.
-   Data: Contains the data access layer, which is responsible for interacting with the database and storage.
-   App: Contains the application logic, which orchestrates the backup process.
-   Interface: Contains the user interface, which is responsible for handling user input and displaying output.

This separation of concerns makes the application more modular, testable, and maintainable.

## Configuration Reference

### .env File (Storage/Global Settings)

All storage and global settings are read from your .env file unless overridden by CLI flags. Defaults are shown where applicable.

-   **BACKUP_DRIVER**: Where to store backups. One of: `local`, `s3`
    -   Example: `local`
    -   Note: You can also pass `--local` or `--s3` on the CLI.
-   **BACKUP_DIR**: Base directory for local backups (used when BACKUP_DRIVER=local or with --local).
    -   Example: `/Users/alex/backups/databases`
-   **S3_BUCKET**: S3 bucket name (used when BACKUP_DRIVER=s3 or with --s3).
    -   Example: `my-bucket`
-   **S3_PATH**: Prefix/path inside the bucket to store backups (folders are created per database).
    -   Example: `backups`
-   **AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY**: AWS credentials to access the bucket.
    -   Example: `AWS_ACCESS_KEY_ID=AKIA...` / `AWS_SECRET_ACCESS_KEY=...`
    -   Tip: If using instance/profile or environment credentials, these can be left empty; boto3 will try the default credential chain.
-   **RETENTION_COUNT**: Number of most recent backups to keep per database. Older ones are removed automatically.
    -   Default: `5`
    -   Example: `10`
-   **DATABASE_BACKUP_CONFIG**: Optional env var to point the CLI to a different .env file.
    -   Example: `/etc/database-backup/.env`

### connections.json (Database Connections)

Database connections are stored in JSON format. Each connection includes:

-   **host**: MySQL server host
    -   Example: `127.0.0.1`
-   **port**: MySQL server port
    -   Default: `3306`
-   **user**: MySQL username with privileges to dump all databases
    -   Example: `root`
-   **password**: Password for the MySQL user
    -   Example: `changeme`
-   **mysqldump_path**: Full path or command name to mysqldump (optional)
    -   Example (macOS/Homebrew on Apple Silicon): `/opt/homebrew/opt/mysql-client/bin/mysqldump`
    -   If not set, the tool tries to resolve mysqldump from PATH
-   **excluded_databases**: List of additional databases to skip (optional)
    -   Example: `["db_1", "db_2"]`
    -   Note: System DBs are always excluded: `mysql`, `information_schema`, `performance_schema`, `sys`
-   **storage_driver**: Preferred storage driver for this connection (optional)
    -   Values: `local` or `s3`
    -   If not set, uses CLI flag (`--local`/`--s3`) or falls back to `BACKUP_DRIVER` from .env
-   **path**: Storage path - backup directory for local storage or S3 path prefix (optional)
    -   For local storage: Example `/backups/production`
    -   For S3 storage: Example `production/backups`
    -   Priority: CLI `--backup-dir` (for local) > connection `path` > `.env` `BACKUP_DIR` or `S3_PATH`
-   **s3_bucket**: Preferred S3 bucket for this connection (optional)
    -   Example: `my-backup-bucket`
    -   Used when `storage_driver` is `s3`
    -   Priority: connection `s3_bucket` > `.env` `S3_BUCKET`

## Examples

### Connection Management

```bash
# Add a production database connection with local storage preference
db-backup add --name production --host db.example.com --user backup_user --password secure_pass \
  --storage-driver local --path /backups/production

# Add a staging connection with S3 storage preference
db-backup add --name staging --host staging.db.example.com --user backup_user --password secure_pass \
  --storage-driver s3 --s3-bucket my-backup-bucket --path staging

# Add a connection without storage preferences (will use .env or CLI flags)
db-backup add --name dev --host localhost --user root --password devpass

# List all connections (shows storage preferences)
db-backup list

# Remove a connection
db-backup remove --name dev
```

### Running Backups

```bash
# Backup using connection's preferred storage (if set)
db-backup backup --connection production

# Backup production database to local storage (overrides connection preference)
db-backup backup --connection production --local

# Backup staging database to S3 (overrides connection preference)
db-backup backup --connection staging --s3

# Backup with custom retention
db-backup backup --connection production --retention 10

# Backup with custom backup directory (overrides connection preference)
db-backup backup --connection production --local --backup-dir /custom/backup/path

# Backup with custom mysqldump path
db-backup backup --connection production --mysqldump /custom/path/mysqldump
```

## Upcoming Features

-   Web UI Mangement Server
-   Multiple connections with SQLite
-   Postgres Support
-   Mongodb Support
-   Remote Connection Support with SSH and bastion host
-   Independent Docker Container
-   Backup history and management
-   Restore Database MySQL, Postgres, MongoDB CLI and UI
-   Multiple compression
-   Multifile database backup
-   Exclude tables
-   Database Size Viewer

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue if you have any suggestions or feedback.

## License

This project is licensed under the MIT License.
