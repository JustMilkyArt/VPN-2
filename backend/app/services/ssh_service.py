"""
SSH Orchestration Service
Manages SSH connections and remote command execution on VPN servers.
"""
import io
import logging
import time
from typing import Optional, Tuple
import paramiko
from app.core.config import settings
from app.models.server import Server

logger = logging.getLogger(__name__)


class SSHClient:
    """Context manager for SSH connections."""

    def __init__(self, server: Server):
        self.server = server
        self.client: Optional[paramiko.SSHClient] = None

    def __enter__(self) -> "SSHClient":
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.server.ip,
            "port": self.server.ssh_port,
            "username": self.server.ssh_user,
            "timeout": settings.SSH_CONNECT_TIMEOUT,
            "banner_timeout": 30,
            "auth_timeout": 30,
        }

        if self.server.ssh_key:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.server.ssh_key))
            connect_kwargs["pkey"] = pkey
        elif self.server.ssh_password:
            connect_kwargs["password"] = self.server.ssh_password

        logger.info(f"Connecting to {self.server.ip}:{self.server.ssh_port} as {self.server.ssh_user}")
        self.client.connect(**connect_kwargs)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            self.client.close()
        return False

    def exec(self, command: str, timeout: int = None) -> Tuple[int, str, str]:
        """Execute command and return (exit_code, stdout, stderr)."""
        if not self.client:
            raise RuntimeError("SSH client not connected")
        
        timeout = timeout or settings.SSH_COMMAND_TIMEOUT
        logger.debug(f"Executing: {command[:100]}")
        
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        
        if exit_code != 0:
            logger.warning(f"Command exited with {exit_code}: {err[:200]}")
        
        return exit_code, out, err

    def upload_file(self, local_content: str, remote_path: str) -> None:
        """Upload string content as a file to remote server."""
        sftp = self.client.open_sftp()
        try:
            with sftp.open(remote_path, "w") as f:
                f.write(local_content)
        finally:
            sftp.close()

    def upload_script(self, script_content: str, remote_path: str) -> None:
        """Upload script and make it executable."""
        self.upload_file(script_content, remote_path)
        self.exec(f"chmod +x {remote_path}")


class SSHService:
    """
    Simple SSH service for admin-server operations (domain setup, certbot, nginx).
    Uses password or key authentication.
    """

    def __init__(self, host: str, user: str, password: str = None, port: int = 22, key: str = None):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.key = key
        self._client: Optional[paramiko.SSHClient] = None

    def connect(self):
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.user,
            "timeout": settings.SSH_CONNECT_TIMEOUT,
            "banner_timeout": 30,
            "auth_timeout": 30,
        }
        if self.key:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.key))
            connect_kwargs["pkey"] = pkey
        elif self.password:
            connect_kwargs["password"] = self.password
        self._client.connect(**connect_kwargs)
        logger.info(f"SSHService connected to {self.host}:{self.port}")

    def run(self, command: str, timeout: int = 120) -> str:
        """Execute command, return combined stdout+stderr output."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        combined = (out + err).strip()
        if exit_code != 0:
            logger.warning(f"SSHService command returned {exit_code}: {combined[:300]}")
        return combined

    def upload_text(self, content: str, remote_path: str):
        """Upload text content to remote file via SFTP."""
        sftp = self._client.open_sftp()
        try:
            with sftp.open(remote_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()

    def close(self):
        if self._client:
            self._client.close()
            self._client = None


def test_connection(server: Server) -> Tuple[bool, str]:
    """Test SSH connection to a server. Returns (success, message)."""
    try:
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec("echo 'ping'", timeout=10)
            if code == 0:
                return True, "Connection successful"
            return False, f"Command failed: {err}"
    except paramiko.AuthenticationException:
        return False, "Authentication failed - check SSH key or password"
    except paramiko.NoValidConnectionsError as e:
        return False, f"Cannot connect to {server.ip}:{server.ssh_port} - {e}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


def ping_with_latency(server: Server) -> Tuple[bool, str, Optional[float]]:
    """Test SSH connection and measure latency in ms. Returns (success, message, latency_ms)."""
    try:
        start = time.time()
        with SSHClient(server) as ssh:
            code, out, err = ssh.exec("echo 'ping'", timeout=10)
            elapsed = (time.time() - start) * 1000  # ms
            if code == 0:
                return True, "Connection successful", round(elapsed, 1)
            return False, f"Command failed: {err}", None
    except paramiko.AuthenticationException:
        return False, "Authentication failed", None
    except paramiko.NoValidConnectionsError as e:
        return False, f"Cannot connect: {e}", None
    except Exception as e:
        return False, f"Connection error: {str(e)}", None


def reboot_server(server: Server) -> Tuple[bool, str]:
    """Send reboot command to server via SSH."""
    try:
        with SSHClient(server) as ssh:
            # nohup reboot so SSH doesn't wait for exit
            ssh.exec("nohup reboot &>/dev/null & sleep 1", timeout=15)
            return True, "Reboot command sent. Server will be back in ~30-60 seconds."
    except Exception as e:
        # Connection may drop immediately after reboot — that's OK
        if "Connection reset" in str(e) or "No existing session" in str(e) or "EOF" in str(e):
            return True, "Reboot command sent. Server will be back in ~30-60 seconds."
        return False, f"Error: {str(e)}"


def change_ssh_password(server: Server, new_password: str) -> Tuple[bool, str]:
    """Change SSH user password on remote server."""
    try:
        with SSHClient(server) as ssh:
            # Use chpasswd — works without interactive prompt
            cmd = f"echo '{server.ssh_user}:{new_password}' | chpasswd"
            code, out, err = ssh.exec(cmd, timeout=15)
            if code == 0:
                return True, f"Password changed for user {server.ssh_user}"
            return False, f"Failed to change password: {err}"
    except Exception as e:
        return False, f"SSH error: {str(e)}"


def add_ssh_key(server: Server, public_key: str) -> Tuple[bool, str]:
    """Add SSH public key to authorized_keys on remote server."""
    try:
        with SSHClient(server) as ssh:
            cmd = f"""
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo '{public_key.strip()}' >> ~/.ssh/authorized_keys
sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo 'done'
"""
            code, out, err = ssh.exec(cmd, timeout=15)
            if code == 0 and "done" in out:
                return True, "SSH public key added to authorized_keys"
            return False, f"Failed: {err}"
    except Exception as e:
        return False, f"SSH error: {str(e)}"


def uninstall_stack(server: Server, services: list) -> Tuple[bool, str]:
    """Uninstall specified VPN services from server."""
    results = []
    try:
        with SSHClient(server) as ssh:
            if "xray" in services:
                ssh.exec("systemctl stop xray; systemctl disable xray; rm -rf /usr/local/bin/xray /usr/local/etc/xray /etc/systemd/system/xray.service; systemctl daemon-reload", timeout=30)
                results.append("xray removed")
            if "naiveproxy" in services:
                ssh.exec("systemctl stop caddy-naive; systemctl disable caddy-naive; rm -rf /usr/local/bin/caddy /etc/caddy-naive /etc/systemd/system/caddy-naive.service; systemctl daemon-reload", timeout=30)
                results.append("naiveproxy removed")
            if "awg" in services:
                ssh.exec("systemctl stop awg-quick@wg0 || systemctl stop wg-quick@wg0; apt-get remove -y amneziawg wireguard 2>/dev/null; rm -rf /etc/amnezia /etc/wireguard", timeout=60)
                results.append("amneziawg removed")
            if "warp" in services:
                ssh.exec("warp-cli --accept-tos disconnect; systemctl stop warp-svc; apt-get remove -y cloudflare-warp 2>/dev/null", timeout=30)
                results.append("warp removed")
        return True, ", ".join(results) if results else "Nothing to uninstall"
    except Exception as e:
        return False, f"SSH error: {str(e)}"


def get_server_info(server: Server) -> dict:
    """Get basic server info (CPU, RAM, uptime)."""
    try:
        with SSHClient(server) as ssh:
            _, uptime, _ = ssh.exec("uptime -p")
            _, cpu, _ = ssh.exec("nproc")
            _, mem, _ = ssh.exec("free -m | awk '/^Mem:/{print $2\"/\"$3}'")
            _, os_info, _ = ssh.exec("cat /etc/os-release | grep PRETTY_NAME | cut -d'\"' -f2")
            
            return {
                "uptime": uptime.strip(),
                "cpu_cores": cpu.strip(),
                "memory": mem.strip(),
                "os": os_info.strip(),
            }
    except Exception as e:
        logger.error(f"Failed to get server info for {server.ip}: {e}")
        return {}
