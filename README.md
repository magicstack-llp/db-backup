# Database Backup Tool

A command-line tool for backing up MySQL databases to local storage or AWS S3.

## Features

-   Back up all MySQL databases, excluding system databases.
-   Store backups in a local directory or an AWS S3 bucket.
-   Create a separate folder for each database.
-   Timestamped backups for easy identification.
-   Automatic cleanup of old backups based on a retention policy.
-   Configuration via a `.env` file.
-   Command-line interface for easy operation.

## Requirements

-   Python 3.11+
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

1.  Clone the repository:

    ```bash
    git clone https://github.com/your-username/database-backup.git
    ```

2.  Install the required libraries:

    ```bash
    pip install -r requirements.txt
    ```

3.  Create a `.env` file in the project root and add the following configuration:

    ```env
    MYSQL_HOST=localhost
    MYSQL_PORT=3306
    MYSQL_USER=root
    MYSQL_PASSWORD=mysecretpassword
    BACKUP_DIR=./backups
    S3_BUCKET=mybucket
    S3_PATH=backups
    AWS_ACCESS_KEY_ID=XXXXXXX
    AWS_SECRET_ACCESS_KEY=YYYYYYY
    RETENTION_COUNT=5
    # Optional: set full path or command name for mysqldump
    MYSQLDUMP_PATH=/opt/homebrew/opt/mysql-client/bin/mysqldump
    BACKUP_DRIVER=local # local, s3
    EXCLUDED_DATABASES=db_1,db_2
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
BACKUP_DIR=/Users/<USER>/backups/databses
S3_BUCKET=mybucket
S3_PATH=backups
AWS_ACCESS_KEY_ID=XXXXXXX
AWS_SECRET_ACCESS_KEY=YYYYYYY
RETENTION_COUNT=5
MYSQLDUMP_PATH=/opt/homebrew/opt/mysql-client/bin/mysqldump
BACKUP_DRIVER=local # local, s3
EXCLUDED_DATABASES=db_1,db_2
```

## CLI usage

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

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue if you have any suggestions or feedback.

## License

This project is licensed under the MIT License.
