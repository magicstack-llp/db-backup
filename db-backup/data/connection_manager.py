
import json
import os
import pathlib
from typing import Optional, Dict, List


def _default_connections_path() -> str:
    """Get the default path for connections.json file."""
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".config"
    return str(base / "database-backup" / "connections.json")


class ConnectionManager:
    """Manages database connections stored in JSON format."""
    
    def __init__(self, connections_path: Optional[str] = None):
        self.connections_path = connections_path or _default_connections_path()
        self._ensure_connections_file()
    
    def _ensure_connections_file(self) -> None:
        """Ensure the connections.json file exists."""
        cfg_dir = os.path.dirname(self.connections_path)
        if cfg_dir and not os.path.exists(cfg_dir):
            os.makedirs(cfg_dir, exist_ok=True)
        
        if not os.path.exists(self.connections_path):
            # Create empty connections file
            with open(self.connections_path, 'w') as f:
                json.dump({}, f, indent=2)
    
    def _load_connections(self) -> Dict:
        """Load connections from JSON file."""
        try:
            with open(self.connections_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_connections(self, connections: Dict) -> None:
        """Save connections to JSON file."""
        with open(self.connections_path, 'w') as f:
            json.dump(connections, f, indent=2)
    
    def add_connection(self, name: str, host: str, port: int, user: str, 
                      password: str, mysqldump_path: Optional[str] = None,
                      excluded_databases: Optional[List[str]] = None,
                      storage_driver: Optional[str] = None,
                      path: Optional[str] = None,
                      s3_bucket: Optional[str] = None,
                      ssh_host: Optional[str] = None,
                      ssh_port: Optional[int] = None,
                      ssh_user: Optional[str] = None,
                      ssh_key_path: Optional[str] = None,
                      bastion_host: Optional[str] = None,
                      bastion_port: Optional[int] = None,
                      bastion_user: Optional[str] = None,
                      bastion_key_path: Optional[str] = None) -> bool:
        """Add a new connection."""
        connections = self._load_connections()
        
        if name in connections:
            return False  # Connection already exists
        
        connections[name] = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "mysqldump_path": mysqldump_path,
            "excluded_databases": excluded_databases or [],
            "storage_driver": storage_driver,
            "path": path,
            "s3_bucket": s3_bucket,
            "ssh_host": ssh_host,
            "ssh_port": ssh_port,
            "ssh_user": ssh_user,
            "ssh_key_path": ssh_key_path,
            "bastion_host": bastion_host,
            "bastion_port": bastion_port,
            "bastion_user": bastion_user,
            "bastion_key_path": bastion_key_path
        }
        
        self._save_connections(connections)
        return True
    
    def remove_connection(self, name: str) -> bool:
        """Remove a connection."""
        connections = self._load_connections()
        
        if name not in connections:
            return False
        
        del connections[name]
        self._save_connections(connections)
        return True
    
    def get_connection(self, name: str) -> Optional[Dict]:
        """Get a connection by name."""
        connections = self._load_connections()
        return connections.get(name)
    
    def list_connections(self) -> List[str]:
        """List all connection names."""
        connections = self._load_connections()
        return list(connections.keys())
    
    def get_all_connections(self) -> Dict:
        """Get all connections."""
        return self._load_connections()
    
    def update_connection(self, name: str, host: Optional[str] = None,
                          port: Optional[int] = None, user: Optional[str] = None,
                          password: Optional[str] = None,
                          mysqldump_path: Optional[str] = None,
                          excluded_databases: Optional[List[str]] = None,
                          storage_driver: Optional[str] = None,
                          path: Optional[str] = None,
                          s3_bucket: Optional[str] = None,
                          ssh_host: Optional[str] = None,
                          ssh_port: Optional[int] = None,
                          ssh_user: Optional[str] = None,
                          ssh_key_path: Optional[str] = None,
                          bastion_host: Optional[str] = None,
                          bastion_port: Optional[int] = None,
                          bastion_user: Optional[str] = None,
                          bastion_key_path: Optional[str] = None) -> bool:
        """Update an existing connection."""
        connections = self._load_connections()
        
        if name not in connections:
            return False
        
        conn = connections[name]
        if host is not None:
            conn["host"] = host
        if port is not None:
            conn["port"] = port
        if user is not None:
            conn["user"] = user
        if password is not None:
            conn["password"] = password
        if mysqldump_path is not None:
            conn["mysqldump_path"] = mysqldump_path
        if excluded_databases is not None:
            conn["excluded_databases"] = excluded_databases
        if storage_driver is not None:
            conn["storage_driver"] = storage_driver
        if path is not None:
            conn["path"] = path
        if s3_bucket is not None:
            conn["s3_bucket"] = s3_bucket
        if ssh_host is not None:
            conn["ssh_host"] = ssh_host
        if ssh_port is not None:
            conn["ssh_port"] = ssh_port
        if ssh_user is not None:
            conn["ssh_user"] = ssh_user
        if ssh_key_path is not None:
            conn["ssh_key_path"] = ssh_key_path
        if bastion_host is not None:
            conn["bastion_host"] = bastion_host
        if bastion_port is not None:
            conn["bastion_port"] = bastion_port
        if bastion_user is not None:
            conn["bastion_user"] = bastion_user
        if bastion_key_path is not None:
            conn["bastion_key_path"] = bastion_key_path
        
        self._save_connections(connections)
        return True

