
import os
import shutil
import mysql.connector
import subprocess

try:
    from ..domain.database import Database  # type: ignore
except Exception:
    from domain.database import Database  # type: ignore

class DatabaseGateway:
    def __init__(self, host, port, user, password, mysqldump_path: str | None = None, excluded_databases: list[str] | None = None):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        # Allow configuring mysqldump path via env/CLI; default to resolving from PATH
        self.mysqldump_path = mysqldump_path or os.getenv("MYSQLDUMP_PATH") or "mysqldump"
        # Exclusions: always include system DBs; extend with config-provided values
        system_excluded = {"information_schema", "performance_schema", "mysql", "sys"}
        extra = set((excluded_databases or []))
        self.excluded_databases = {db.strip() for db in (system_excluded | extra) if db and db.strip()}

    def list_databases(self):
        try:
            connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password
            )
            cursor = connection.cursor()
            cursor.execute("SHOW DATABASES")
            databases = [db[0] for db in cursor]
            cursor.close()
            connection.close()
            return [Database(db) for db in databases if db not in self.excluded_databases]
        except mysql.connector.Error as err:
            print(f"Error connecting to MySQL: {err}")
            return []

    def backup_database(self, db_name, backup_path):
        try:
            # Resolve mysqldump absolute path if provided as command name
            mysqldump = self.mysqldump_path
            resolved = shutil.which(mysqldump) if not os.path.isabs(mysqldump) else mysqldump
            if not resolved or not os.path.exists(resolved):
                print(f"mysqldump not found. Set MYSQLDUMP_PATH in .env or ensure '{mysqldump}' is in PATH.")
                return False

            command = [
                resolved,
                f"--host={self.host}",
                f"--port={self.port}",
                f"--user={self.user}",
                f"--password={self.password}",
                "--single-transaction",
                "--quick",
                "--skip-lock-tables",
                db_name,
                f"--result-file={backup_path}",
            ]

            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                # Clean up any partial/empty file
                try:
                    if os.path.exists(backup_path) and os.path.getsize(backup_path) == 0:
                        os.remove(backup_path)
                except Exception:
                    pass
                stderr = (result.stderr or "").strip()
                print(f"Error backing up database {db_name}: {stderr or 'mysqldump failed'}")
                return False

            # Verify file exists and is non-empty
            if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
                print(f"Backup file for database {db_name} is empty. Check mysqldump permissions and options.")
                return False

            return True
        except Exception as e:
            print(f"Error backing up database {db_name}: {e}")
            try:
                if os.path.exists(backup_path) and os.path.getsize(backup_path) == 0:
                    os.remove(backup_path)
            except Exception:
                pass
            return False
