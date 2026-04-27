import os

# ==================== Qwen 模型 API 配置 ====================
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus-2025-07-28")
QWEN_ASR_MODEL = os.getenv("QWEN_ASR_MODEL", "qwen3-asr-flash")

# ==================== SSH 连接配置 ====================
SSH_HOST = os.getenv("SSH_HOST", "192.168.220.128")
SSH_USER = os.getenv("SSH_USER", "u")
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "12345678")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))

# ==================== 安全配置 ====================
LOW_RISK_PATTERNS = [
    (r"\bsudo\s+useradd\b", "普通用户创建操作"),
    (r"\bsudo\s+userdel\b", "普通用户删除操作"),
    (r"\bsudo\s+groupadd\b", "普通用户组创建操作"),
    (r"\bsudo\s+groupdel\b", "普通用户组删除操作"),
]

HIGH_RISK_PATTERNS = [
    (r"\bsudo\s+rm\s+-rf\s+/\s*$", "尝试删除根目录"),
    (r"\brm\s+-rf\s+/\s*$", "尝试删除根目录"),
    (r"\brm\s+-rf\s+/\*", "尝试清空根目录"),
    (r"\brm\s+-rf\s+/(boot|etc|usr|var|root)(?:\s|$)", "尝试删除系统核心目录"),
    (r"\bmkfs(?:\.\w+)?\b", "磁盘格式化操作"),
    (r"\bdd\s+.*\bof=/dev/", "直接写块设备"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "疑似 fork bomb"),
    (r"\b(chmod|chown)\s+-R\s+777\s+/\b", "大范围修改系统根目录权限"),
    (r"\bshutdown\b", "系统关机操作"),
    (r"\breboot\b", "系统重启操作"),
    (r"\bhalt\b", "系统停机操作"),
    (r"\bpoweroff\b", "系统断电操作"),
    (r"\bcurl\b.*\|\s*(bash|sh)\b", "远程脚本直连执行"),
    (r"\bwget\b.*\|\s*(bash|sh)\b", "远程脚本直连执行"),
]

MEDIUM_RISK_PATTERNS = [
    (r"\bpasswd\b", "密码修改操作"),
    (r"\bchmod\b", "权限修改操作"),
    (r"\bchown\b", "属主修改操作"),
    (r"\brm\b(?!\s+-rf\s+/)", "文件删除操作"),
    (r"\bsystemctl\s+(stop|restart|disable|mask)\b", "服务管理操作"),
    (r"\bkill(all)?\b", "进程终止操作"),
    (r"\bpkill\b", "进程终止操作"),
    (r"\bapt\s+(remove|purge)\b", "软件卸载操作"),
    (r"\byum\s+remove\b", "软件卸载操作"),
    (r"\bdnf\s+remove\b", "软件卸载操作"),
    (r"\bpip\s+uninstall\b", "Python 包卸载操作"),
    (r"\busermod\b", "用户属性修改操作"),
    (r"\bdd\b", "原始数据写入操作"),
]

# 兼容旧代码，好像没有啥用
HIGH_RISK_COMMANDS = [pattern for pattern, _ in HIGH_RISK_PATTERNS]
WARNING_COMMANDS = [pattern for pattern, _ in MEDIUM_RISK_PATTERNS]
INTERACTIVE_COMMANDS = []
DANGEROUS_COMMANDS = HIGH_RISK_COMMANDS
