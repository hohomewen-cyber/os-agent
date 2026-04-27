import json
import re
from typing import Dict, List, Optional, Tuple
from openai import OpenAI
from config import QWEN_API_BASE, QWEN_API_KEY, QWEN_MODEL
# 这个还是基于我的os实验报告做的提取模板，自己的时间不够还没有来的即进行完善，后面会进行改良的
class DocumentParser:
    CMD_KEYWORDS = {
        "mkdir", "cd", "ls", "cat", "vim", "touch", "rm", "cp", "mv",
        "gcc", "g++", "make", "./", "yum", "apt", "dnf",
        "ps", "pidof", "kill", "killall", "top", "jobs", "bg", "fg", "df", "free", "uptime", "pgrep",
        "who", "whoami", "w", "clear", "uname", "man", "last", "echo",
        "shutdown", "halt", "reboot", "poweroff", "history", "alias", "unalias",
        "wget", "curl", "ping", "netstat", "ss", "systemctl",
        "gdb", "strace", "find", "grep", "useradd", "userdel", "passwd",
    }

    _client: Optional[OpenAI] = None
    _last_diagnostics: Dict = {"engine": "none", "messages": []}

    @classmethod
    def _get_client(cls) -> Optional[OpenAI]:
        if not QWEN_API_KEY:
            return None
        if cls._client is None:
            cls._client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_API_BASE)
        return cls._client

    @classmethod
    def parse_file(cls, content: str) -> Tuple[List[Dict], List[Dict]]:
        cls._last_diagnostics = {"engine": "rules_fallback", "messages": []}
        ai_commands, ai_codes = cls._extract_with_ai(content)
        regex_commands, regex_codes = cls._extract_with_rules(content)

        commands = cls._merge_commands(ai_commands, regex_commands)
        c_codes = cls._merge_codes(ai_codes, regex_codes)
        if ai_commands or ai_codes:
            cls._last_diagnostics["engine"] = "ai_primary+rules_fallback"
            cls._last_diagnostics["messages"].append("已启用 AI 主抽取，并使用规则作为兜底补全。")
        else:
            cls._last_diagnostics["messages"].append("AI 未返回有效结构，已自动回退为规则解析。")
        cls._last_diagnostics["messages"].append(f"共识别命令 {len(commands)} 条，代码 {len(c_codes)} 段。")
        return commands, c_codes

    @classmethod
    def get_last_diagnostics(cls) -> Dict:
        return cls._last_diagnostics

    @classmethod
    def _extract_with_ai(cls, content: str) -> Tuple[List[Dict], List[Dict]]:
        client = cls._get_client()
        if client is None:
            cls._last_diagnostics["messages"].append("未检测到 QWEN_API_KEY，跳过大模型文档抽取。")
            return [], []

        commands: List[Dict] = []
        c_codes: List[Dict] = []
        normalized_content = cls._normalize_document_text(content)
        lines = normalized_content.splitlines()

        chunk_size = 80
        overlap = 12
        for start in range(0, len(lines), chunk_size):
            chunk_lines = lines[start:start + chunk_size]
            if start != 0:
                chunk_lines = lines[max(0, start - overlap):start + chunk_size]
            chunk_text = "\n".join(chunk_lines)
            if not chunk_text.strip():
                continue

            prompt = f"""你是 Linux 文档解析专家。下面的文本可能来自实验报告、课件、博客、作业、扫描转录、Markdown、TXT 或 PDF 提取文本。
请优先通过语义理解提取两类内容：
1. 可直接在 Linux Shell 中执行的命令
2. C 语言代码片段

输出严格 JSON：
{{
  "commands": [
    {{
      "command": "命令原文",
      "source": "ai_extract",
      "evidence": "原文片段",
      "reason": "为什么判断它是命令"
    }}
  ],
  "c_codes": [
    {{
      "name": "代码名称",
      "code": "完整代码",
      "evidence": "原文片段"
    }}
  ]
}}

要求：
1. 只提取文本中真实出现、或能从上下文明确还原的命令，不要臆造。
2. 识别跨行断裂命令、Markdown 代码块、终端转录、编号步骤、带提示符的命令。
3. 忽略纯说明文字、命令执行结果、自然语言描述中的模糊建议。
4. C 代码要尽量恢复完整，保留 include、main、函数定义和注释。
5. 如果是 shell 提示符如 `$ ls -l`、`root@host# ps aux`，只返回真正命令部分。
6. 没有内容时返回空数组。

文本如下：
{chunk_text}"""

            try:
                response = client.chat.completions.create(
                    model=QWEN_MODEL,
                    messages=[
                        {"role": "system", "content": "你是严谨的实验报告内容抽取器，只返回 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=1800,
                )
                raw = response.choices[0].message.content.strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                payload = json.loads(match.group(0) if match else raw)
            except Exception as exc:
                cls._last_diagnostics["messages"].append(f"第 {start + 1} 行附近 AI 抽取失败: {exc}")
                continue

            for item in payload.get("commands", []):
                command = cls._sanitize_extracted_command(cls._clean_ai_command(item.get("command") or ""))
                if not command:
                    continue
                commands.append(
                    {
                        "command": command,
                        "line": cls._find_line_number(content, item.get("evidence") or command),
                        "source": "AI识别",
                        "risk": cls._get_risk_level(command),
                        "raw_text": (item.get("evidence") or command)[:120],
                    }
                )

            for item in payload.get("c_codes", []):
                code = cls._clean_code_block(item.get("code") or "")
                if not code:
                    continue
                c_codes.append(
                    {
                        "code": code,
                        "line": cls._find_line_number(content, item.get("evidence") or code.splitlines()[0]),
                        "name": (item.get("name") or "AI提取代码").strip(),
                        "raw_text": (item.get("evidence") or code)[:200],
                    }
                )

        return commands, c_codes

    @staticmethod
    def _normalize_document_text(content: str) -> str:
        text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @staticmethod
    def _clean_ai_command(command: str) -> str:
        cmd = (command or "").strip()
        cmd = re.sub(r"^(?:[A-Za-z0-9_.-]+@[\w.-]+[:#]\s*|\$+\s*|#\s+)", "", cmd)
        cmd = cmd.strip().strip("`")
        if "\n" in cmd:
            cmd = " ".join(part.strip() for part in cmd.splitlines() if part.strip())
        return cmd

    @staticmethod
    def _clean_code_block(code: str) -> str:
        cleaned = (code or "").strip()
        cleaned = re.sub(r"^```c?\s*", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _sanitize_extracted_command(command: str) -> str:
        cmd = (command or "").strip().rstrip("。；;，,")
        cmd = re.sub(r"\s+(?:创建|删除|查看|进入|编译|运行|安装|执行|用于|用来).*$", "", cmd)
        cmd = re.sub(r"\s+\?+$", "", cmd)
        return cmd.strip()

    @classmethod
    def _extract_with_rules(cls, content: str) -> Tuple[List[Dict], List[Dict]]:
        commands = []
        c_codes = []
        lines = content.split("\n")
        in_c_code = False
        c_code_lines = []
        c_code_name = ""

        for i, line in enumerate(lines, 1):
            original_line = line
            line = line.strip()

            if not line:
                if in_c_code:
                    c_code_lines.append("")
                continue

            if (
                line.startswith("#include")
                or line.startswith("int main")
                or (line.startswith("main()") and "{" in line)
                or (not in_c_code and "fork()" in line and "{" in line)
            ):
                in_c_code = True
                c_code_lines = [original_line]
                for j in range(max(0, i - 10), i):
                    prev_line = lines[j].strip()
                    match = re.search(r"(例\d+)", prev_line)
                    if match:
                        c_code_name = match.group(1)
                        break
                    if "fork" in prev_line.lower():
                        c_code_name = "fork示例"
                    if "getpid" in prev_line.lower():
                        c_code_name = "getpid示例"
                continue

            if in_c_code:
                looks_like_command = (
                    line
                    and not line.startswith("//")
                    and line.split()[0] in cls.CMD_KEYWORDS
                    and not line.startswith("#include")
                    and not line.startswith("int main")
                    and "fork" not in line
                )
                if looks_like_command:
                    in_c_code = False
                    code_content = "\n".join(c_code_lines)
                    if code_content and ("#include" in code_content or "main" in code_content):
                        c_codes.append(
                            {
                                "code": code_content,
                                "line": i,
                                "name": c_code_name or f"代码片段_{i}",
                                "raw_text": code_content[:200],
                            }
                        )
                    c_code_lines = []
                    c_code_name = ""
                else:
                    c_code_lines.append(original_line)
                    continue

            cmd = cls._extract_command_from_line(line)
            if not cmd:
                cmd = cls._parse_natural_language(line)

            if not cmd:
                continue
            cmd = cls._sanitize_extracted_command(cmd)
            if len(cmd) < 2 or len(cmd) > 300:
                continue
            if cmd.startswith("#") or cmd.startswith("//"):
                continue
            if cmd in ["例如", "比如", "说明"]:
                continue

            commands.append(
                {
                    "command": cmd,
                    "line": i,
                    "source": "规则识别",
                    "risk": cls._get_risk_level(cmd),
                    "raw_text": line[:120],
                }
            )

        if in_c_code and c_code_lines:
            code_content = "\n".join(c_code_lines)
            if code_content and ("#include" in code_content or "main" in code_content):
                c_codes.append(
                    {
                        "code": code_content,
                        "line": len(lines),
                        "name": c_code_name or "代码片段",
                        "raw_text": code_content[:200],
                    }
                )

        return commands, c_codes

    @classmethod
    def _extract_command_from_line(cls, line: str) -> Optional[str]:
        match = re.search(r"\[.*\]#\s*(.+?)(?:\s*//|$)", line)
        if match:
            return match.group(1).strip()

        if line.startswith("$ "):
            return line[2:].split("//")[0].strip()

        if line.startswith("# ") and not line.startswith("#include"):
            return line[2:].split("//")[0].strip()

        inline_match = re.search(
            r"((?:sudo\s+)?(?:mkdir|cd|ls|cat|touch|rm|cp|mv|gcc|g\+\+|make|ps|kill|top|who|uname|wget|curl|ping|ss|netstat|systemctl|find|grep|useradd|userdel|passwd|df|free|uptime|pgrep)\b[^。；;\n]*)",
            line,
            re.IGNORECASE,
        )
        if inline_match:
            return inline_match.group(1).strip().rstrip("。；;")

        words = line.split()
        if words and words[0] in cls.CMD_KEYWORDS:
            if "[" in line and "]" in line and "=" not in line:
                return None
            return line.split("//")[0].strip()

        return None

    @staticmethod
    def _parse_natural_language(line: str) -> Optional[str]:
        line_lower = line.lower()
        intent_map = [
            (r"查看.*?进程", "ps aux"),
            (r"查看.*?服务.*?pid", "pidof"),
            (r"终止.*?进程", "kill"),
            (r"结束.*?进程", "kill"),
            (r"实时.*?监控", "top -bn1 | head -20"),
            (r"查看.*?登录.*?用户", "who -uH"),
            (r"查看.*?当前.*?用户", "whoami"),
            (r"新建.*?文件", "touch new_file"),
            (r"创建.*?目录", "mkdir -p new_dir"),
            (r"进入.*?目录", "cd target_dir"),
            (r"查看.*?文件.*?内容", "cat file"),
            (r"列出.*?文件", "ls -la"),
            (r"编译.*?c.*?程序", "gcc -o program program.c"),
            (r"运行.*?程序", "./program"),
            (r"安装.*?gcc", "apt install -y gcc"),
            (r"清除.*?屏幕", "clear"),
            (r"查看.*?系统.*?信息", "uname -a"),
            (r"查看.*?历史.*?命令", "history"),
        ]

        for pattern, template in intent_map:
            if re.search(pattern, line_lower):
                return template
        return None

    @classmethod
    def _merge_commands(cls, primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
        seen = set()
        merged = []
        for item in primary + secondary:
            command = item["command"].strip()
            if command in seen:
                continue
            seen.add(command)
            merged.append(item)
        return merged

    @classmethod
    def _merge_codes(cls, primary: List[Dict], secondary: List[Dict]) -> List[Dict]:
        seen = set()
        merged = []
        for item in primary + secondary:
            key = item["code"][:120]
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    @staticmethod
    def _find_line_number(content: str, snippet: str) -> int:
        if not snippet:
            return 1
        index = content.find(snippet[:80])
        if index < 0:
            return 1
        return content[:index].count("\n") + 1

    @staticmethod
    def _get_risk_level(command: str) -> str:
        try:
            from executor import executor

            risk_level, _, _ = executor.check_command_safety(command)
            return risk_level
        except Exception:
            cmd_lower = command.lower()
            if any(keyword in cmd_lower for keyword in ["shutdown", "reboot", "rm -rf /"]):
                return "high"
            if any(keyword in cmd_lower for keyword in ["kill", "passwd", "chmod", "rm "]):
                return "medium"
            return "low"
