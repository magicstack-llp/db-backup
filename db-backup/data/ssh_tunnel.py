
import os
import socket
import threading
from typing import Optional
from contextlib import contextmanager

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore


class SSHTunnel:
    """Manages SSH tunnels for database connections."""
    
    def __init__(self, ssh_host: str, ssh_port: int, ssh_user: str, ssh_key_path: str,
                 remote_host: str, remote_port: int,
                 bastion_host: Optional[str] = None, bastion_port: Optional[int] = None,
                 bastion_user: Optional[str] = None, bastion_key_path: Optional[str] = None):
        """
        Initialize SSH tunnel.
        
        Args:
            ssh_host: SSH server hostname (target server, or intermediate if bastion is used)
            ssh_port: SSH server port
            ssh_user: SSH username
            ssh_key_path: Path to SSH private key file
            remote_host: Target database hostname (behind SSH)
            remote_port: Target database port
            bastion_host: Optional bastion host (if using double hop)
            bastion_port: Optional bastion port (default: 22)
            bastion_user: Optional bastion username
            bastion_key_path: Optional bastion key path
        """
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.bastion_host = bastion_host
        self.bastion_port = bastion_port or 22
        self.bastion_user = bastion_user
        self.bastion_key_path = bastion_key_path
        
        self.local_port = None
        self.tunnel_thread = None
        self.bastion_client = None
        self.target_client = None
        self._stop_event = threading.Event()
        self._server_socket = None
    
    def _find_free_port(self) -> int:
        """Find a free local port for the tunnel."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            return s.getsockname()[1]
    
    def _load_ssh_key(self, key_path: str):
        """Load SSH private key from file (supports RSA, ECDSA, Ed25519)."""
        if paramiko is None:
            raise ImportError("paramiko is required for SSH tunnel support. Install it with: pip install paramiko")
        
        # Expand ~ to home directory
        expanded_path = os.path.expanduser(key_path)
        if not os.path.exists(expanded_path):
            raise ValueError(f"SSH key file not found: {expanded_path}")
        
        try:
            # Try different key types (DSSKey is deprecated/removed in newer paramiko versions)
            key_classes = [paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key]
            # Only try DSSKey if it exists (for older paramiko versions)
            if hasattr(paramiko, 'DSSKey'):
                key_classes.append(paramiko.DSSKey)
            
            for key_class in key_classes:
                try:
                    return key_class.from_private_key_file(expanded_path)
                except paramiko.ssh_exception.SSHException:
                    continue
            raise ValueError(f"Unsupported key type in {expanded_path}. Supported types: RSA, ECDSA, Ed25519")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to load SSH key from {expanded_path}: {e}")
    
    def _create_ssh_client(self, host: str, port: int, user: str, key_path: str):  # type: ignore
        """Create and configure SSH client."""
        if paramiko is None:
            raise ImportError("paramiko is required for SSH tunnel support. Install it with: pip install paramiko")
        client = paramiko.SSHClient()  # type: ignore
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # type: ignore
        
        try:
            key = self._load_ssh_key(key_path)
            client.connect(
                hostname=host,
                port=port,
                username=user,
                pkey=key,
                timeout=30,
                allow_agent=False,
                look_for_keys=False
            )
            return client
        except Exception as e:
            client.close()
            raise ConnectionError(f"Failed to connect to {host}:{port}: {e}")
    
    def _forward_tunnel(self, local_port: int, remote_host: str, remote_port: int, ssh_client):
        """Forward local port to remote host through SSH."""
        try:
            transport = ssh_client.get_transport()
            if not transport:
                raise ConnectionError("SSH transport not available")
            
            # Create server socket
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(('127.0.0.1', local_port))
            self._server_socket.listen(5)
            self._server_socket.settimeout(1.0)
            
            while not self._stop_event.is_set():
                try:
                    client_socket, _ = self._server_socket.accept()
                except socket.timeout:
                    continue
                except Exception:
                    if not self._stop_event.is_set():
                        break
                    continue
                
                # Create channel through SSH
                try:
                    channel = transport.open_channel(
                        'direct-tcpip',
                        (remote_host, remote_port),
                        client_socket.getpeername()
                    )
                except Exception as e:
                    client_socket.close()
                    if not self._stop_event.is_set():
                        print(f"Failed to open SSH channel: {e}")
                    continue
                
                # Forward data between sockets
                def forward_data(src, dst, name):
                    try:
                        while not self._stop_event.is_set():
                            data = src.recv(4096)
                            if not data:
                                break
                            dst.send(data)
                    except Exception:
                        pass
                    finally:
                        try:
                            src.close()
                        except Exception:
                            pass
                        try:
                            dst.close()
                        except Exception:
                            pass
                
                # Start forwarding in both directions
                threading.Thread(
                    target=forward_data,
                    args=(client_socket, channel, "client->channel"),
                    daemon=True
                ).start()
                threading.Thread(
                    target=forward_data,
                    args=(channel, client_socket, "channel->client"),
                    daemon=True
                ).start()
                
        except Exception as e:
            if not self._stop_event.is_set():
                print(f"Tunnel forwarding error: {e}")
        finally:
            if self._server_socket:
                try:
                    self._server_socket.close()
                except Exception:
                    pass
                self._server_socket = None
    
    def start(self) -> int:
        """Start the SSH tunnel and return local port."""
        if paramiko is None:
            raise ImportError("paramiko is required for SSH tunnel support. Install it with: pip install paramiko")
        if self.local_port is not None:
            return self.local_port
        
        self.local_port = self._find_free_port()
        
        if self.bastion_host:
            # Double hop: connect through bastion to target
            try:
                # Step 1: Connect to bastion
                self.bastion_client = self._create_ssh_client(
                    self.bastion_host,
                    self.bastion_port,
                    self.bastion_user or self.ssh_user,
                    self.bastion_key_path or self.ssh_key_path
                )
                
                # Step 2: Create channel through bastion to target SSH server
                bastion_transport = self.bastion_client.get_transport()
                if not bastion_transport:
                    raise ConnectionError("Bastion transport not available")
                
                target_channel = bastion_transport.open_channel(
                    'direct-tcpip',
                    (self.ssh_host, self.ssh_port),
                    (self.bastion_host, self.bastion_port)
                )
                
                # Step 3: Create SSH transport over the channel
                target_transport = paramiko.Transport(target_channel)
                target_transport.start_client()
                
                # Step 4: Authenticate to target
                key = self._load_ssh_key(self.ssh_key_path)
                target_transport.auth_publickey(self.ssh_user, key)
                
                # Step 5: Create SSH client wrapper
                self.target_client = paramiko.SSHClient()
                self.target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.target_client._transport = target_transport
                
                # Step 6: Start forwarding through target connection
                self._stop_event.clear()
                self.tunnel_thread = threading.Thread(
                    target=self._forward_tunnel,
                    args=(self.local_port, self.remote_host, self.remote_port, self.target_client),
                    daemon=True
                )
                self.tunnel_thread.start()
                
            except Exception as e:
                self.stop()
                raise ConnectionError(f"Failed to establish bastion tunnel: {e}")
        else:
            # Simple SSH tunnel: direct connection
            try:
                self.target_client = self._create_ssh_client(
                    self.ssh_host,
                    self.ssh_port,
                    self.ssh_user,
                    self.ssh_key_path
                )
                
                self._stop_event.clear()
                self.tunnel_thread = threading.Thread(
                    target=self._forward_tunnel,
                    args=(self.local_port, self.remote_host, self.remote_port, self.target_client),
                    daemon=True
                )
                self.tunnel_thread.start()
                
            except Exception as e:
                self.stop()
                raise ConnectionError(f"Failed to establish SSH tunnel: {e}")
        
        # Wait a moment to ensure tunnel is ready
        import time
        time.sleep(0.5)
        
        return self.local_port
    
    def stop(self):
        """Stop the SSH tunnel."""
        self._stop_event.set()
        
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
        
        if self.target_client:
            try:
                self.target_client.close()
            except Exception:
                pass
            self.target_client = None
        
        if self.bastion_client:
            try:
                self.bastion_client.close()
            except Exception:
                pass
            self.bastion_client = None
        
        if self.tunnel_thread:
            self.tunnel_thread.join(timeout=2.0)
            self.tunnel_thread = None
        
        self.local_port = None
    
    @contextmanager
    def tunnel(self):
        """Context manager for SSH tunnel."""
        port = self.start()
        try:
            yield port
        finally:
            self.stop()

