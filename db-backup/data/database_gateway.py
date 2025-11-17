
import os
import shutil
import mysql.connector
import subprocess
from typing import Optional

try:
    from ..domain.database import Database  # type: ignore
except Exception:
    try:
        from db_backup.domain.database import Database  # type: ignore
    except Exception:
        from domain.database import Database  # type: ignore

try:
    from ..data.ssh_tunnel import SSHTunnel  # type: ignore
except Exception:
    try:
        from db_backup.data.ssh_tunnel import SSHTunnel  # type: ignore
    except Exception:
        SSHTunnel = None  # type: ignore

class DatabaseGateway:
    def __init__(self, host, port, user, password, mysqldump_path: str | None = None, excluded_databases: list[str] | None = None,
                 ssh_host: Optional[str] = None, ssh_port: Optional[int] = None, ssh_user: Optional[str] = None,
                 ssh_key_path: Optional[str] = None, bastion_host: Optional[str] = None,
                 bastion_port: Optional[int] = None, bastion_user: Optional[str] = None,
                 bastion_key_path: Optional[str] = None):
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
        
        # SSH tunnel configuration
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port or 22
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path
        self.bastion_host = bastion_host
        self.bastion_port = bastion_port
        self.bastion_user = bastion_user
        self.bastion_key_path = bastion_key_path
        
        self.ssh_tunnel: Optional[SSHTunnel] = None
        self._effective_host = host
        self._effective_port = port

    def _ensure_ssh_tunnel(self):
        """Ensure SSH tunnel is established if SSH configuration is provided."""
        if self.ssh_host and self.ssh_user and self.ssh_key_path:
            if SSHTunnel is None:
                raise ImportError(
                    "SSH tunnel configuration detected but 'paramiko' is not installed.\n"
                    "This connection requires SSH tunneling. Please install paramiko:\n"
                    "  pip install paramiko\n"
                    "Or install all dependencies:\n"
                    "  pip install -e ."
                )
            if self.ssh_tunnel is None:
                try:
                    self.ssh_tunnel = SSHTunnel(
                        ssh_host=self.ssh_host,
                        ssh_port=self.ssh_port,
                        ssh_user=self.ssh_user,
                        ssh_key_path=self.ssh_key_path,
                        remote_host=self.host,
                        remote_port=self.port,
                        bastion_host=self.bastion_host,
                        bastion_port=self.bastion_port,
                        bastion_user=self.bastion_user,
                        bastion_key_path=self.bastion_key_path
                    )
                    local_port = self.ssh_tunnel.start()
                    self._effective_host = "127.0.0.1"
                    self._effective_port = local_port
                except ImportError as e:
                    raise ImportError(
                        f"SSH tunnel configuration detected but 'paramiko' is not installed.\n"
                        f"This connection requires SSH tunneling. Please install paramiko:\n"
                        f"  pip install paramiko\n"
                        f"Or install all dependencies:\n"
                        f"  pip install -e .\n"
                        f"Original error: {e}"
                    )
        else:
            self._effective_host = self.host
            self._effective_port = self.port
    
    def _cleanup_ssh_tunnel(self):
        """Clean up SSH tunnel if it exists."""
        if self.ssh_tunnel:
            try:
                self.ssh_tunnel.stop()
            except Exception:
                pass
            self.ssh_tunnel = None
        self._effective_host = self.host
        self._effective_port = self.port
    
    def list_databases(self):
        try:
            self._ensure_ssh_tunnel()
            connection = mysql.connector.connect(
                host=self._effective_host,
                port=self._effective_port,
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
            self._ensure_ssh_tunnel()
            
            # Resolve mysqldump absolute path if provided as command name
            mysqldump = self.mysqldump_path
            resolved = shutil.which(mysqldump) if not os.path.isabs(mysqldump) else mysqldump
            if not resolved or not os.path.exists(resolved):
                print(f"mysqldump not found. Set MYSQLDUMP_PATH in .env or ensure '{mysqldump}' is in PATH.")
                return False

            command = [
                resolved,
                f"--host={self._effective_host}",
                f"--port={self._effective_port}",
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
    
    def close(self):
        """Close SSH tunnel and cleanup resources."""
        self._cleanup_ssh_tunnel()
