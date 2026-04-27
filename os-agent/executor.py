import json
import re
import shlex
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import paramiko
except ImportError:
    paramiko = None

from config import (
    HIGH_RISK_PATTERNS,
    LOW_RISK_PATTERNS,
    MEDIUM_RISK_PATTERNS,
    SSH_HOST,
    SSH_PASSWORD,
    SSH_PORT,
    SSH_USER,
)


@dataclass
class CommandExecutionResult:
    command: str
    display_command: str
    executed_command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    success: bool = True
    blocked: bool = False
    risk_level: str = "low"
    risk_reason: str = ""
    precheck_ok: bool = True
    precheck_message: str = ""
    verification_ok: bool = True
    verification_message: str = ""
    status: str = "success"
    env_snapshot: Dict = field(default_factory=dict)

    def combined_output(self) -> str:
        parts = []
        seen = set()

        def append_part(value: str):
            text = (value or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            parts.append(text)

        if self.stdout.strip():
            append_part(self.stdout.strip())
        if self.stderr.strip():
            append_part(f"[STDERR]\n{self.stderr.strip()}")
        if self.precheck_message and not self.precheck_ok:
            append_part(self.precheck_message.strip())
        if self.verification_message and not self.verification_ok:
            append_part(self.verification_message.strip())
        combined = "\n".join(part for part in parts if part).strip()
        return combined or "(命令执行成功，无输出)"


class SafeExecutor:
    def __init__(self, hostname, username, password, port=22):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.client = None
        self.env_info_updated_at = 0.0
        self.system_snapshot: Dict = {}
        self.system_snapshot_updated_at = 0.0
        self.env_info: Dict = {
            "os_type": "unknown",
            "distribution": "unknown",
            "package_manager": "unknown",
            "current_user": username,
            "is_root": False,
            "sudo_available": False,
            "hostname": hostname,
        }
        self._connect()
        self.refresh_env_info(force=True)

    def _connect(self):
        if paramiko is None:
            self.client = None
            return
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.hostname,
                username=self.username,
                password=self.password,
                port=self.port,
                timeout=10,
            )
        except Exception:
            self.client = None

    def ensure_connection(self):
        try:
            if self.client is None:
                self._connect()
                return
            transport = self.client.get_transport()
            if transport is None or not transport.is_active():
                self._connect()
        except Exception:
            self._connect()

    def _matches(self, patterns, command: str):
        for pattern, reason in patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return reason
        return None

    def check_command_safety(self, command):
        cmd = (command or "").strip()
        if not cmd:
            return "low", False, "空命令"

        low_reason = self._matches(LOW_RISK_PATTERNS, cmd)
        if low_reason:
            return "low", False, low_reason

        high_reason = self._matches(HIGH_RISK_PATTERNS, cmd)
        if high_reason:
            return "high", False, high_reason

        medium_reason = self._matches(MEDIUM_RISK_PATTERNS, cmd)
        if medium_reason:
            return "medium", False, medium_reason

        return "low", False, "命令安全"

    def _run_command(self, command: str, timeout: int = 30):
        self.ensure_connection()
        if self.client is None:
            return "", "❌ SSH 连接未建立，无法执行命令。", 255

        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8", errors="ignore")
        error = stderr.read().decode("utf-8", errors="ignore")
        return self._strip_ansi(output), self._strip_ansi(error), exit_code

    @staticmethod
    def _strip_ansi(text: str) -> str:
        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_escape.sub("", text or "").strip()

    def _supports_sudo_password(self, command: str) -> bool:
        cmd = (command or "").strip()
        if not cmd.startswith("sudo "):
            return False
        return bool(self.password)

    def _wrap_command_for_execution(self, command: str) -> str:
        command = (command or "").strip()
        if self._supports_sudo_password(command):
            password = shlex.quote(self.password)
            return f"printf '%s\\n' {password} | sudo -S -p '' {command[5:]}"
        return command

    def mask_sensitive_command(self, command: str) -> str:
        if self._supports_sudo_password(command):
            return command.strip()
        return (command or "").strip()

    def refresh_env_info(self, force: bool = False, ttl: int = 30):
        now = time.time()
        if not force and self.env_info_updated_at and now - self.env_info_updated_at < ttl:
            return self.env_info
        if self.client is None:
            return self.env_info

        os_stdout, _, _ = self._run_command("uname -s")
        distro_stdout, _, _ = self._run_command(
            "bash -lc 'if [ -f /etc/os-release ]; then . /etc/os-release && echo \"${PRETTY_NAME:-$NAME}\"; else uname -sr; fi'"
        )
        pkg_stdout, _, _ = self._run_command(
            "bash -lc 'for pm in apt dnf yum zypper pacman apk; do command -v \"$pm\" >/dev/null 2>&1 && echo \"$pm\" && break; done'"
        )
        user_stdout, _, _ = self._run_command("whoami")
        uid_stdout, _, _ = self._run_command("id -u")
        sudo_stdout, _, _ = self._run_command("bash -lc 'command -v sudo >/dev/null 2>&1 && echo yes || echo no'")
        host_stdout, _, _ = self._run_command("hostname")

        self.env_info = {
            "os_type": os_stdout or "unknown",
            "distribution": distro_stdout or "unknown",
            "package_manager": pkg_stdout or "unknown",
            "current_user": user_stdout or self.username,
            "is_root": (uid_stdout or "").strip() == "0",
            "sudo_available": (sudo_stdout or "").strip() == "yes",
            "hostname": host_stdout or self.hostname,
        }
        self.env_info_updated_at = now
        return self.env_info

    def get_system_snapshot(self, force: bool = False, ttl: int = 8) -> Dict:
        now = time.time()
        if not force and self.system_snapshot_updated_at and now - self.system_snapshot_updated_at < ttl:
            return self.system_snapshot
        if self.client is None:
            return self.system_snapshot

        stdout, _, _ = self._run_command(
            "bash -lc '"
            "HOST=$(hostname 2>/dev/null); "
            "UP=$(uptime -p 2>/dev/null | sed \"s/^up //\"); "
            "MEM=$(free -h 2>/dev/null | awk \"NR==2 {print \\$3\\\"/\\\"\\$2}\"); "
            "DISK=$(df -h / 2>/dev/null | awk \"NR==2 {print \\$3\\\"/\\\"\\$2\\\" (\\\" \\$5 \\\")\\\"}\"); "
            "printf \"HOST=%s\nUP=%s\nMEM=%s\nDISK=%s\n\" \"$HOST\" \"$UP\" \"$MEM\" \"$DISK\""
            "'"
        )
        snapshot = {}
        for line in (stdout or "").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            snapshot[key] = value.strip()
        self.system_snapshot = snapshot
        self.system_snapshot_updated_at = now
        return snapshot

    def invalidate_caches(self, command: str = ""):
        cmd = (command or "").strip().lower()
        if any(token in cmd for token in ["useradd", "userdel", "usermod", "apt ", "yum ", "dnf ", "systemctl", "hostnamectl", "su ", "sudo "]):
            self.env_info_updated_at = 0.0
        if any(token in cmd for token in ["rm ", "touch ", "mv ", "cp ", "systemctl", "apt ", "yum ", "dnf ", "useradd", "userdel", "chmod", "chown"]):
            self.system_snapshot_updated_at = 0.0

    def _run_exists_check(self, probe_command: str) -> bool:
        stdout, stderr, exit_code = self._run_command(probe_command, timeout=15)
        return exit_code == 0 and not stderr.strip() and stdout.strip() == "EXISTS"

    def _extract_target(self, command: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, command)
        if not match:
            return None
        return (match.group(1) or "").strip()

    def _precheck(self, command: str) -> (bool, str):
        cmd = (command or "").strip()

        rm_match = re.search(r"^(?:sudo\s+)?rm\b(?:\s+-[^\s]+)*\s+(.+)$", cmd)
        if rm_match:
            target = rm_match.group(1).strip()
            exists = self._run_exists_check(f"bash -lc \"[ -e {shlex.quote(target)} ] && echo EXISTS\"")
            if not exists:
                return False, f"❌ 删除前检查失败：目标不存在 -> {target}"

        chmod_match = re.search(r"^(?:sudo\s+)?chmod\b(?:\s+-[^\s]+)*\s+\S+\s+(.+)$", cmd)
        if chmod_match:
            target = chmod_match.group(1).strip()
            exists = self._run_exists_check(f"bash -lc \"[ -e {shlex.quote(target)} ] && echo EXISTS\"")
            if not exists:
                return False, f"❌ 修改权限前检查失败：目标不存在 -> {target}"

        chown_match = re.search(r"^(?:sudo\s+)?chown\b(?:\s+-[^\s]+)*\s+\S+\s+(.+)$", cmd)
        if chown_match:
            target = chown_match.group(1).strip()
            exists = self._run_exists_check(f"bash -lc \"[ -e {shlex.quote(target)} ] && echo EXISTS\"")
            if not exists:
                return False, f"❌ 修改属主前检查失败：目标不存在 -> {target}"

        kill_match = re.search(r"^(?:sudo\s+)?kill(?:all)?\b.*?\s+([A-Za-z0-9_.-]+)$", cmd)
        if kill_match:
            target = kill_match.group(1).strip()
            if "killall" in cmd:
                exists = self._run_exists_check(f"bash -lc \"pgrep -x {shlex.quote(target)} >/dev/null 2>&1 && echo EXISTS\"")
            else:
                exists = self._run_exists_check(f"bash -lc \"kill -0 {shlex.quote(target)} >/dev/null 2>&1 && echo EXISTS\"")
            if not exists:
                return False, f"❌ 结束进程前检查失败：进程不存在 -> {target}"

        pkill_match = re.search(r"^(?:sudo\s+)?pkill\b.*?\s+([A-Za-z0-9_.-]+)$", cmd)
        if pkill_match:
            target = pkill_match.group(1).strip()
            exists = self._run_exists_check(f"bash -lc \"pgrep -f {shlex.quote(target)} >/dev/null 2>&1 && echo EXISTS\"")
            if not exists:
                return False, f"❌ 结束进程前检查失败：未找到匹配进程 -> {target}"

        userdel_match = re.search(r"^(?:sudo\s+)?userdel\b(?:\s+-[^\s]+)*\s+([A-Za-z_][A-Za-z0-9_-]*)$", cmd)
        if userdel_match:
            username = userdel_match.group(1)
            exists = self._run_exists_check(f"bash -lc \"id {shlex.quote(username)} >/dev/null 2>&1 && echo EXISTS\"")
            if not exists:
                return False, f"❌ 删除用户前检查失败：用户不存在 -> {username}"

        return True, ""

    def _post_verify(self, command: str, result: CommandExecutionResult) -> (bool, str):
        cmd = (command or "").strip()

        install_match = re.search(r"^(?:sudo\s+)?(?:apt(?:-get)?|yum|dnf)\s+install\b.*?\s+([A-Za-z0-9+_.:-]+)$", cmd)
        if install_match:
            package = install_match.group(1)
            pkg_manager = self.env_info.get("package_manager", "")
            if pkg_manager == "apt":
                check = f"bash -lc \"dpkg -s {shlex.quote(package)} >/dev/null 2>&1 && echo EXISTS\""
            elif pkg_manager in {"yum", "dnf"}:
                check = f"bash -lc \"rpm -q {shlex.quote(package)} >/dev/null 2>&1 && echo EXISTS\""
            else:
                check = ""
            if check and not self._run_exists_check(check):
                return False, f"❌ 安装后验证失败：未检测到软件包已安装 -> {package}"

        rm_match = re.search(r"^(?:sudo\s+)?rm\b(?:\s+-[^\s]+)*\s+(.+)$", cmd)
        if rm_match:
            target = rm_match.group(1).strip()
            if self._run_exists_check(f"bash -lc \"[ -e {shlex.quote(target)} ] && echo EXISTS\""):
                return False, f"❌ 删除后验证失败：目标仍存在 -> {target}"

        useradd_match = re.search(r"^(?:sudo\s+)?useradd\b.*?\s+([A-Za-z_][A-Za-z0-9_-]*)$", cmd)
        if useradd_match:
            username = useradd_match.group(1)
            if not self._run_exists_check(f"bash -lc \"id {shlex.quote(username)} >/dev/null 2>&1 && echo EXISTS\""):
                return False, f"❌ 创建用户后验证失败：未检测到用户 -> {username}"

        userdel_match = re.search(r"^(?:sudo\s+)?userdel\b(?:\s+-[^\s]+)*\s+([A-Za-z_][A-Za-z0-9_-]*)$", cmd)
        if userdel_match:
            username = userdel_match.group(1)
            if self._run_exists_check(f"bash -lc \"id {shlex.quote(username)} >/dev/null 2>&1 && echo EXISTS\""):
                return False, f"❌ 删除用户后验证失败：用户仍存在 -> {username}"

        service_match = re.search(r"^(?:sudo\s+)?systemctl\s+(start|stop|restart|enable|disable)\s+([A-Za-z0-9_.@-]+)", cmd)
        if service_match:
            action = service_match.group(1)
            service = service_match.group(2)
            if action in {"start", "restart"}:
                active = self._run_exists_check(f"bash -lc \"systemctl is-active {shlex.quote(service)} >/dev/null 2>&1 && echo EXISTS\"")
                if not active:
                    return False, f"❌ 服务状态验证失败：{service} 未处于 active 状态"
            elif action == "stop":
                inactive = self._run_exists_check(f"bash -lc \"systemctl is-active {shlex.quote(service)} >/dev/null 2>&1 || echo EXISTS\"")
                if not inactive:
                    return False, f"❌ 服务状态验证失败：{service} 仍处于 active 状态"
            elif action == "enable":
                enabled = self._run_exists_check(f"bash -lc \"systemctl is-enabled {shlex.quote(service)} >/dev/null 2>&1 && echo EXISTS\"")
                if not enabled:
                    return False, f"❌ 服务状态验证失败：{service} 未启用"
            elif action == "disable":
                disabled = self._run_exists_check(f"bash -lc \"systemctl is-enabled {shlex.quote(service)} >/dev/null 2>&1 || echo EXISTS\"")
                if not disabled:
                    return False, f"❌ 服务状态验证失败：{service} 仍处于启用状态"

        return True, ""

    def execute_with_details(self, command, skip_confirmation=False):
        self.ensure_connection()
        if self.client is None:
            return CommandExecutionResult(
                command=command or "",
                display_command=command or "",
                executed_command=command or "",
                stderr="❌ SSH 连接未建立，无法执行命令。",
                exit_code=255,
                success=False,
                status="error",
                env_snapshot=dict(self.env_info),
            )

        risk_level, _, reason = self.check_command_safety(command)
        display_command = self.mask_sensitive_command(command)
        if risk_level == "high":
            return CommandExecutionResult(
                command=command,
                display_command=display_command,
                executed_command=command,
                stderr=f"❌ 操作被拒绝: {reason}",
                exit_code=126,
                success=False,
                blocked=True,
                risk_level=risk_level,
                risk_reason=reason,
                status="blocked",
                env_snapshot=dict(self.env_info),
            )

        precheck_ok, precheck_message = self._precheck(command)
        if not precheck_ok:
            return CommandExecutionResult(
                command=command,
                display_command=display_command,
                executed_command=command,
                stderr="",
                exit_code=1,
                success=False,
                risk_level=risk_level,
                risk_reason=reason,
                precheck_ok=False,
                precheck_message=precheck_message,
                status="precheck_failed",
                env_snapshot=dict(self.env_info),
            )

        executed_command = self._wrap_command_for_execution(command)
        stdout, stderr, exit_code = self._run_command(executed_command)
        success = exit_code == 0

        result = CommandExecutionResult(
            command=command,
            display_command=display_command,
            executed_command=executed_command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            success=success,
            risk_level=risk_level,
            risk_reason=reason,
            env_snapshot=dict(self.env_info),
        )

        if success:
            verification_ok, verification_message = self._post_verify(command, result)
            result.verification_ok = verification_ok
            result.verification_message = verification_message
            if not verification_ok:
                result.success = False
                result.status = "verification_failed"
                result.exit_code = 1
        else:
            result.status = "error"

        self.invalidate_caches(command)
        self.refresh_env_info()
        result.env_snapshot = dict(self.env_info)
        return result

    def execute(self, command, skip_confirmation=False):
        result = self.execute_with_details(command, skip_confirmation=skip_confirmation)
        return result.combined_output()

    def export_env_info(self) -> str:
        return json.dumps(self.env_info, ensure_ascii=False)

    def close(self):
        if self.client:
            self.client.close()


executor = SafeExecutor(
    hostname=SSH_HOST,
    username=SSH_USER,
    password=SSH_PASSWORD,
    port=SSH_PORT,
)
