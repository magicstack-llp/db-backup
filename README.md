# Database Backup Tool

A command-line tool for backing up MySQL databases to local storage or AWS S3.

## Quick start

1. Install

```bash
pip install database-backup
```

1. See options

```bash
db-backup --help
```

1. Create/edit config

```bash
nano ~/.config/database-backup/.env
```

1. Run

```bash
db-backup --local   # store on filesystem
db-backup --s3      # store on S3
```

## Features

-   Back up all MySQL databases, excluding system databases.
-   Store backups in a local directory or an AWS S3 bucket.
-   Create a separate folder for each database.
-   Timestamped backups for easy identification.
-   Automatic cleanup of old backups based on a retention policy.
-   Configuration via a `.env` file.
-   Command-line interface for easy operation.

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

By default, the CLI loads config from:

-   macOS/Linux: `~/.config/database-backup/.env` (or `${XDG_CONFIG_HOME}/database-backup/.env`)

Override with `--config` or `DATABASE_BACKUP_CONFIG` env.

Example `.env`:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=password
BACKUP_DIR=/Users/<USER>/backups/databases
## CLI usage
S3_BUCKET=mybucket
S3_PATH=backups
AWS_ACCESS_KEY_ID=XXXXXXX
AWS_SECRET_ACCESS_KEY=YYYYYYY
RETENTION_COUNT=5
MYSQLDUMP_PATH=/opt/homebrew/opt/mysql-client/bin/mysqldump
BACKUP_DRIVER=local # local, s3
EXCLUDED_DATABASES=db_1,db_2
```

After installation as a package, use the short command:

```bash
db-backup --local
# or
database-backup --s3
```

Options:

-   `--compress/--no-compress` (default: `--compress`): gzip the dump and keep `.gz`.
-   `--mysqldump PATH`: override mysqldump path.
-   `--config FILE`: override config file path.

You can still run the module directly:

```bash
python -m db_backup --local
```

## Usage

Preferred: run as a module from the project root (this works reliably regardless of relative imports):

```bash
python -m db_backup --config .env --local
```

Or run the script directly (works after the import fallback fix):

```bash
python db_backup/main.py --config .env --local
```

You can override `mysqldump` path via CLI:

```bash
python -m db_backup --config .env --local --mysqldump /opt/homebrew/opt/mysql-client/bin/mysqldump
```

To store your backups in an S3 bucket:

```bash
python -m db_backup --config .env --s3
```

You can also override the retention count and backup directory using the command-line options:

```bash
python -m db_backup --config .env --retention 10 --local --backup-dir /path/to/backups
```

## Architecture

The database backup tool is built using a Clean Architecture approach, which separates the code into four layers:

-   Domain: Contains the core business logic and entities of the application.
-   Data: Contains the data access layer, which is responsible for interacting with the database and storage.
-   App: Contains the application logic, which orchestrates the backup process.
-   Interface: Contains the user interface, which is responsible for handling user input and displaying output.

This separation of concerns makes the application more modular, testable, and maintainable.

## Environment variables reference

All configuration is read from your .env file unless overridden by CLI flags. Defaults are shown where applicable.

-   MYSQL_HOST: MySQL server host.

    -   Example: 127.0.0.1

-   MYSQL_PORT: MySQL port. Default: 3306

    -   Example: 3306

-   MYSQL_USER: MySQL username with privileges to dump all databases.

    -   Example: root

-   MYSQL_PASSWORD: Password for MYSQL_USER.

    -   Example: changeme

-   BACKUP_DRIVER: Where to store backups. One of: local, s3

    -   Example: local
    -   Note: You can also pass --local or --s3 on the CLI.

-   BACKUP_DIR: Base directory for local backups (used when BACKUP_DRIVER=local or with --local).

    -   Example: /Users/alex/backups/databases

-   S3_BUCKET: S3 bucket name (used when BACKUP_DRIVER=s3 or with --s3).

    -   Example: my-bucket

-   S3_PATH: Prefix/path inside the bucket to store backups (folders are created per database).

    -   Example: backups

-   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY: AWS credentials to access the bucket.

    -   Example: AWS_ACCESS_KEY_ID=AKIA... / AWS_SECRET_ACCESS_KEY=...
    -   Tip: If using instance/profile or environment credentials, these can be left empty; boto3 will try the default credential chain.

-   RETENTION_COUNT: Number of most recent backups to keep per database. Older ones are removed automatically.

    -   Default: 5
    -   Example: 10

-   MYSQLDUMP_PATH: Full path or command name to mysqldump. If not set, the tool tries to resolve mysqldump from PATH.

    -   Example (macOS/Homebrew on Apple Silicon): /opt/homebrew/opt/mysql-client/bin/mysqldump

-   EXCLUDED_DATABASES: Comma-separated list of additional databases to skip. System DBs are always excluded: mysql, information_schema, performance_schema, sys.

    -   Example: db_1,db_2

-   DATABASE_BACKUP_CONFIG: Optional env var to point the CLI to a different .env file.
    -   Example: /etc/database-backup/.env

## Examples

-   Local backup with custom mysqldump and retention:

```bash
db-backup --local --mysqldump /opt/homebrew/opt/mysql-client/bin/mysqldump --retention 10
```

-   S3 backup using settings from .env:

```bash
db-backup --s3
```

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue if you have any suggestions or feedback.

## License

This project is licensed under the MIT License.
