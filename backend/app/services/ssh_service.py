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
            pkey = _load_private_key(self.server.ssh_key)
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
            pkey = _load_private_key(self.key)
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
    except paramiko.ssh_exception.NoValidConnectionsError as e:
        return False, f"Cannot connect to {server.ip}:{server.ssh_port} - {e}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


def speed_test(server: Server) -> Optional[float]:
    """Measure download speed in Mbit/s by running curl ON the VPN server via SSH.
    
    This measures the actual network throughput of the VPN server itself,
    not the admin server. Uses multiple CDN URLs, tries each in order.
    """
    # 10 MB file for more accurate measurement on fast servers
    test_urls = [
        "http://speedtest.tele2.net/10MB.zip",
        "http://speedtest.tele2.net/1MB.zip",
        "http://proof.ovh.net/files/10Mb.dat",
        "http://ipv4.download.thinkbroadband.com/10MB.zip",
    ]
    try:
        with SSHClient(server) as ssh:
            for url in test_urls:
                cmd = (
                    f"curl -o /dev/null -s --max-time 15 --connect-timeout 4 "
                    f"-w '%{{speed_download}}' '{url}'"
                )
                code, out, _ = ssh.exec(cmd, timeout=20)
                out = out.strip().strip("'")
                if code == 0 and out:
                    try:
                        bytes_per_sec = float(out)
                        mbit = round(bytes_per_sec * 8 / 1_000_000, 1)
                        if mbit > 0:
                            logger.info(f"Speed test for {server.ip}: {mbit} Mbit/s via {url}")
                            return mbit
                    except ValueError:
                        continue
    except Exception as e:
        logger.warning(f"Speed test failed for {server.ip}: {e}")
    return None


def ping_with_latency(server: Server) -> Tuple[bool, str, Optional[float]]:
    """Measure real ICMP latency via ping, confirm reachability via SSH.
    
    Two-step:
    1. ICMP ping from admin server → VPN server (real network latency, 20-80ms)
    2. Quick SSH connect to confirm server is alive and accepting connections
    """
    import subprocess, re

    # Step 1: ICMP ping — real latency
    icmp_latency = None
    try:
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "2", server.ip],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            # Parse "rtt min/avg/max/mdev = 12.3/14.5/16.7/1.8 ms"
            m = re.search(r'rtt [^=]+ = [\d.]+/([\d.]+)/', result.stdout)
            if m:
                icmp_latency = round(float(m.group(1)), 1)
    except Exception:
        pass

    # Step 2: SSH check — просто проверяем что сервер принимает соединения
    try:
        with SSHClient(server) as ssh:
            code, _, _ = ssh.exec("echo ok", timeout=10)
            if code == 0:
                return True, "Connection successful", icmp_latency
            return False, "SSH command failed", icmp_latency
    except paramiko.AuthenticationException:
        return False, "Authentication failed", icmp_latency
    except paramiko.ssh_exception.NoValidConnectionsError as e:
        return False, f"Cannot connect: {e}", icmp_latency
    except Exception as e:
        # Если ICMP ответил но SSH упал — сервер жив, но SSH проблема
        if icmp_latency is not None:
            return False, f"SSH error: {str(e)}", icmp_latency
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
    """Get basic server info (OS, CPU, RAM, disk, uptime)."""
    try:
        with SSHClient(server) as ssh:
            _, os_info, _ = ssh.exec("cat /etc/os-release | grep PRETTY_NAME | cut -d'\"' -f2")
            _, cpu, _     = ssh.exec("nproc")
            _, cpu_model, _ = ssh.exec("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2")
            _, mem, _     = ssh.exec("free -h | awk '/^Mem:/{print $3\"/\"$2}'")
            _, disk, _    = ssh.exec("df -h / | awk 'NR==2{print $3\"/\"$2}'")
            _, uptime, _  = ssh.exec("uptime -p")

            cpu_label = cpu.strip()
            if cpu_model.strip():
                cpu_label = f"{cpu_model.strip()} ({cpu.strip()} ядер)"

            return {
                "os":        os_info.strip(),
                "cpu_cores": cpu_label,
                "memory":    mem.strip(),
                "disk":      disk.strip(),
                "uptime":    uptime.strip(),
            }
    except Exception as e:
        logger.error(f"Failed to get server info for {server.ip}: {e}")
        return {}


def get_security_status(server: Server) -> dict:
    """Check real security status on server via SSH."""
    result = {
        "fail2ban":       False,
        "ufw":            False,
        "password_login": True,   # небезопасное значение по умолчанию
        "root_login":     True,
    }
    try:
        with SSHClient(server) as ssh:
            # Fail2Ban
            _, out, _ = ssh.exec("systemctl is-active fail2ban 2>/dev/null", timeout=5)
            result["fail2ban"] = out.strip() == "active"

            # UFW — запускаем через sudo (непривилегированный юзер не видит статус)
            _, out, _ = ssh.exec("sudo ufw status 2>/dev/null | head -1 || ufw status 2>/dev/null | head -1", timeout=8)
            result["ufw"] = "active" in out.lower()

            # PasswordAuthentication
            _, out, _ = ssh.exec(
                "grep -i '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null | tail -1",
                timeout=5
            )
            val = out.strip().split()[-1].lower() if out.strip() else "yes"
            result["password_login"] = val != "no"

            # PermitRootLogin
            _, out, _ = ssh.exec(
                "grep -i '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null | tail -1",
                timeout=5
            )
            val = out.strip().split()[-1].lower() if out.strip() else "yes"
            result["root_login"] = val not in ("no", "prohibit-password")

    except Exception as e:
        logger.warning(f"get_security_status failed for {server.ip}: {e}")
    return result


def apply_security_setting(server: Server, setting: str, enabled: bool) -> Tuple[bool, str]:
    """Apply a single security setting on the server via SSH."""
    try:
        with SSHClient(server) as ssh:

            if setting == "fail2ban":
                if enabled:
                    cmds = [
                        "apt-get install -y fail2ban -qq",
                        "systemctl enable fail2ban",
                        "systemctl start fail2ban",
                    ]
                else:
                    cmds = ["systemctl stop fail2ban", "systemctl disable fail2ban"]
                for cmd in cmds:
                    code, _, err = ssh.exec(cmd, timeout=60)
                    if code != 0:
                        return False, f"Command failed: {cmd}: {err}"
                return True, "fail2ban " + ("enabled" if enabled else "disabled")

            elif setting == "ufw":
                if enabled:
                    # Разрешаем нужные порты перед включением чтобы не потерять SSH
                    ssh_port = server.ssh_port or 22
                    cmds = [
                        "apt-get install -y ufw -qq",
                        f"ufw allow {ssh_port}/tcp",
                        "ufw allow 80/tcp",
                        "ufw allow 443/tcp",
                        "ufw allow 51820/udp",
                        "ufw allow 51821/udp",
                        "DEBIAN_FRONTEND=noninteractive sudo ufw --force enable",
                    ]
                else:
                    cmds = ["DEBIAN_FRONTEND=noninteractive sudo ufw --force disable"]
                for cmd in cmds:
                    code, _, err = ssh.exec(cmd, timeout=60)
                    if code != 0:
                        return False, f"Command failed: {cmd}: {err}"
                return True, "ufw " + ("enabled" if enabled else "disabled")

            elif setting == "password_login":
                val = "yes" if enabled else "no"
                cmds = [
                    f"sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication {val}/' /etc/ssh/sshd_config",
                    f"grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication {val}' >> /etc/ssh/sshd_config",
                    "systemctl reload sshd || systemctl reload ssh",
                ]
                for cmd in cmds:
                    ssh.exec(cmd, timeout=10)
                return True, f"PasswordAuthentication set to {val}"

            elif setting == "root_login":
                val = "yes" if enabled else "no"
                cmds = [
                    f"sed -i 's/^#*PermitRootLogin.*/PermitRootLogin {val}/' /etc/ssh/sshd_config",
                    f"grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin {val}' >> /etc/ssh/sshd_config",
                    "systemctl reload sshd || systemctl reload ssh",
                ]
                for cmd in cmds:
                    ssh.exec(cmd, timeout=10)
                return True, f"PermitRootLogin set to {val}"

            else:
                return False, f"Unknown setting: {setting}"

    except Exception as e:
        return False, str(e)


def harden_server(server: Server) -> Tuple[bool, str]:
    """Run basic hardening on a freshly added server:
    - Install & enable Fail2Ban
    - Install & configure UFW with required ports
    """
    try:
        with SSHClient(server) as ssh:
            logger.info(f"Starting hardening for {server.ip}")
            ssh_port = server.ssh_port or 22

            steps = [
                ("update",       "apt-get update -qq"),
                ("fail2ban",     "apt-get install -y fail2ban -qq"),
                ("f2b-start",    "systemctl enable fail2ban && systemctl start fail2ban"),
                ("ufw-inst",     "apt-get install -y ufw -qq"),
                ("ufw-ssh",      f"ufw allow {ssh_port}/tcp"),
                ("ufw-80",       "ufw allow 80/tcp"),
                ("ufw-443",      "ufw allow 443/tcp"),
                ("ufw-wg1",      "ufw allow 51820/udp"),
                ("ufw-wg2",      "ufw allow 51821/udp"),
                ("ufw-on",       "echo 'y' | ufw enable"),
                # Запрет root-логина через SSH
                ("no-root",      "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config && "
                                 "grep -q '^PermitRootLogin' /etc/ssh/sshd_config || "
                                 "echo 'PermitRootLogin no' >> /etc/ssh/sshd_config"),
                ("sshd-reload",  "systemctl reload sshd || systemctl reload ssh"),
            ]

            for name, cmd in steps:
                code, _, err = ssh.exec(cmd, timeout=120)
                if code != 0:
                    logger.warning(f"Harden step '{name}' failed for {server.ip}: {err}")
                else:
                    logger.info(f"Harden step '{name}' OK for {server.ip}")

            return True, "Hardening completed"
    except Exception as e:
        logger.error(f"Hardening failed for {server.ip}: {e}")
        return False, str(e)
