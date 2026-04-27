import json
import re
from typing import Dict, List

from openai import OpenAI

from config import QWEN_API_BASE, QWEN_API_KEY, QWEN_MODEL

try:
    from colorama import Fore, Style, init

    init(autoreset=True)
except ImportError:
    class Fore:
        CYAN = GREEN = YELLOW = RED = BLUE = MAGENTA = WHITE = ""

    class Style:
        RESET_ALL = ""

# 因为我使用的ubuntn，只能基于我电脑上的基础配置进行编码了，小组其他人没有装置虚拟机，因此环境感知能力我一直在进行加强，如果有足够的时间
class OSAgent:
    def __init__(self):
        self.client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_API_BASE)
        self.model = QWEN_MODEL
        self.conversation_history: List[Dict[str, str]] = []
        self.env_info: Dict[str, str] = {}
        self.base_system_prompt = """你是一个专业的 Linux 服务器管理智能代理。

你正在通过 SSH 代理操作 Linux 服务器，必须把用户自然语言转成可执行命令计划，并保持行为可解释、可审计。

核心要求：
1. 优先理解上下文，用户可能会用“那个文件”“继续运行”“再删掉它”这样的表达。
2. 输出必须是严格 JSON，不要输出 Markdown，不要输出解释性前缀。
3. 尽量给出可直接执行的 Linux 命令；避免分页器、TTY 依赖和纯交互式工具。
4. 如果任务需要多步，必须返回 steps。
5. 风险只做初步判断，最终以执行器规则为准。
6. 用和用户相同的语言写 explanation 和 summary。
7. 用户创建或删除普通账号属于 low；密码修改、权限修改、删除文件、停止服务属于 medium；破坏系统核心目录或系统可用性的属于 high。
8. 创建用户优先使用非交互式 `useradd -m -s /bin/bash 用户名`，删除用户优先使用 `userdel`，不要优先生成 `adduser` 这类更依赖交互环境的命令。
9. 生成命令时必须结合当前环境信息，优先使用当前系统存在的包管理器和当前权限模型。

输出格式：
{
  "is_complex": false,
  "command": "命令",
  "explanation": "说明",
  "risk_level": "low/medium/high",
  "response_language": "zh/en"
}

或者：
{
  "is_complex": true,
  "explanation": "任务概述",
  "response_language": "zh/en",
  "steps": [
    {
      "step": 1,
      "command": "命令",
      "explanation": "说明",
      "risk_level": "low/medium/high"
    }
  ]
}"""

    def _compose_system_prompt(self) -> str:
        if not self.env_info:
            return self.base_system_prompt
        env_lines = [
            "当前环境信息：",
            f"- 操作系统类型: {self.env_info.get('os_type', 'unknown')}",
            f"- 发行版: {self.env_info.get('distribution', 'unknown')}",
            f"- 包管理器: {self.env_info.get('package_manager', 'unknown')}",
            f"- 当前用户: {self.env_info.get('current_user', 'unknown')}",
            f"- 是否 root: {self.env_info.get('is_root', False)}",
            f"- 是否可用 sudo: {self.env_info.get('sudo_available', False)}",
        ]
        return self.base_system_prompt + "\n\n" + "\n".join(env_lines)

    def set_env_info(self, env_info: Dict):
        self.env_info = env_info or {}

    def _infer_language(self, text: str) -> str:
        if re.search(r"[\u4e00-\u9fff]", text):
            return "zh"
        return "en"

    def resolve_language(self, user_input: str, preferred_language: str = "auto") -> str:
        if preferred_language in {"zh", "en"}:
            return preferred_language
        return self._infer_language(user_input)

    def _history_messages(self, limit: int = 8) -> List[Dict[str, str]]:
        if not self.conversation_history:
            return []
        return self.conversation_history[-limit:]

    def _extract_json(self, content: str) -> Dict:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        payload = match.group(0) if match else content
        return json.loads(payload)

    def remember_turn(self, user_input: str, command_summary: str, output_summary: str = ""):
        self.conversation_history.append({"role": "user", "content": user_input})
        assistant_text = f"执行计划: {command_summary}"
        if output_summary:
            assistant_text += f"\n结果摘要: {output_summary[:300]}"
        self.conversation_history.append({"role": "assistant", "content": assistant_text})
        self.conversation_history = self.conversation_history[-20:]

    def clear_memory(self):
        self.conversation_history = []

    def get_command_from_qwen(self, user_input: str, preferred_language: str = "auto") -> Dict:
        language = self.resolve_language(user_input, preferred_language)
        user_prompt = f"""用户输入：{user_input}

请基于对话历史和当前输入，返回严格 JSON。

附加要求：
1. 需要利用上下文补全代词、省略对象和连续动作。
2. 如果是代码/编程相关需求，可以返回多步命令。
3. response_language 使用 "{language}"。
4. 如果用户提到语言切换、英文回答、中文回答等，请在 explanation 中顺应该语言。
5. 创建文件可使用 heredoc；执行状态查询时优先只读命令。
6. 普通用户的创建、删除属于 low，不要抬高到 medium/high。"""

        messages = [{"role": "system", "content": self._compose_system_prompt()}]
        messages.extend(self._history_messages())
        messages.append({"role": "user", "content": user_prompt})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=1000,
            )
            result = self._extract_json(response.choices[0].message.content.strip())
            return self._normalize_parse_result(result, user_input)
        except Exception:
            return self._fallback_parse(user_input, preferred_language=preferred_language)

    def _normalize_parse_result(self, result: Dict, user_input: str) -> Dict:
        language = result.get("response_language") or self._infer_language(user_input)
        if result.get("is_complex"):
            steps = []
            for index, step in enumerate(result.get("steps", []), start=1):
                normalized_command = self._normalize_command(step.get("command", "").strip(), user_input)
                steps.append(
                    {
                        "step": step.get("step", index),
                        "command": normalized_command,
                        "explanation": step.get("explanation", "").strip(),
                        "risk_level": step.get("risk_level", step.get("risk", "low")).strip().lower(),
                    }
                )
            return {
                "is_complex": True,
                "explanation": result.get("explanation", "").strip(),
                "response_language": language,
                "steps": steps,
            }

        return {
            "is_complex": False,
            "command": self._normalize_command(result.get("command", "").strip(), user_input),
            "explanation": result.get("explanation", "").strip(),
            "risk_level": result.get("risk_level", "low").strip().lower(),
            "response_language": language,
        }

    def _normalize_command(self, command: str, user_input: str) -> str:
        cmd = (command or "").strip()
        if not cmd:
            return ""

        adduser_match = re.search(r"^(sudo\s+)?adduser\b.*?\s+([A-Za-z_][A-Za-z0-9_-]*)$", cmd)
        if adduser_match:
            prefix = "sudo " if adduser_match.group(1) else ""
            username = adduser_match.group(2)
            return f"{prefix}useradd -m -s /bin/bash {username}"

        deluser_match = re.search(r"^(sudo\s+)?deluser\b.*?\s+([A-Za-z_][A-Za-z0-9_-]*)$", cmd)
        if deluser_match:
            prefix = "sudo " if deluser_match.group(1) else ""
            username = deluser_match.group(2)
            remove_home = "--remove-home" in cmd or "-r" in cmd
            option = " -r" if remove_home else ""
            return f"{prefix}userdel{option} {username}"

        if any(keyword in user_input.lower() for keyword in ["install", "安装"]):
            package_manager = self.env_info.get("package_manager", "")
            if package_manager in {"yum", "dnf"} and re.search(r"\bapt(?:-get)?\s+install\b", cmd):
                return re.sub(r"\bapt(?:-get)?\s+install\b", f"{package_manager} install", cmd)
            if package_manager == "apt" and re.search(r"\byum\s+install\b|\bdnf\s+install\b", cmd):
                return re.sub(r"\b(?:yum|dnf)\s+install\b", "apt install", cmd)

        return cmd

    def _fallback_parse(self, user_input: str, preferred_language: str = "auto") -> Dict:
        text = user_input.lower()
        language = self.resolve_language(user_input, preferred_language)

        if "磁盘" in text or "space" in text or "disk" in text:
            return {"is_complex": False, "command": "df -h", "explanation": "查看磁盘使用情况", "risk_level": "low", "response_language": language}
        if "内存" in text or "memory" in text:
            return {"is_complex": False, "command": "free -h", "explanation": "查看内存使用情况", "risk_level": "low", "response_language": language}
        if "端口" in text or "port" in text:
            return {"is_complex": False, "command": "ss -tlnp", "explanation": "查看当前监听端口", "risk_level": "low", "response_language": language}
        if "创建用户" in text or "add user" in text:
            match = re.search(r"(?:创建|添加).*?(?:用户|账号)[：:\s]*(\w+)", text)
            username = match.group(1) if match else "newuser"
            return {"is_complex": False, "command": f"sudo useradd -m -s /bin/bash {username}", "explanation": f"创建用户 {username}", "risk_level": "low", "response_language": language}
        return {
            "is_complex": False,
            "command": f"echo 'Unable to understand request: {user_input}'",
            "explanation": "未识别的指令，请重新描述。",
            "risk_level": "low",
            "response_language": language,
        }

    def get_feedback_from_qwen(
        self,
        command: str,
        result: str,
        is_dangerous: bool = False,
        needs_warning: bool = False,
        risk_reason: str = "",
        language: str = "zh",
    ) -> str:
        fast_feedback = self._fast_feedback(
            command=command,
            result=result,
            is_dangerous=is_dangerous,
            needs_warning=needs_warning,
            risk_reason=risk_reason,
            language=language,
        )
        if fast_feedback:
            return fast_feedback

        if is_dangerous:
            prompt = f"""请用{language}简明说明这条命令为什么被拦截，并给出更安全的替代建议。
命令: {command}
原因: {risk_reason}
输出不超过80字。"""
        elif needs_warning:
            prompt = f"""请用{language}简明概括这条敏感命令的执行结果，并提醒用户注意影响范围。
命令: {command}
结果: {result[:300]}
输出不超过80字。"""
        elif "❌" in result or "error" in result.lower() or "failed" in result.lower():
            prompt = f"""请用{language}解释这条命令失败的主要原因，并给一个排查方向。
命令: {command}
结果: {result[:300]}
输出不超过90字。"""
        else:
            prompt = f"""请用{language}概括这条命令执行后的关键信息。
命令: {command}
结果: {result[:300]}
输出不超过80字。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是操作系统智能代理的反馈解释器。回答简洁、准确、自然。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=180,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            if is_dangerous:
                return f"该操作已被拦截：{risk_reason}"
            if "❌" in result or "error" in result.lower():
                return "命令执行失败，请查看输出并检查参数、权限或目标对象是否存在。"
            return "命令已执行，详细结果见输出。"

    def _fast_feedback(
        self,
        command: str,
        result: str,
        is_dangerous: bool = False,
        needs_warning: bool = False,
        risk_reason: str = "",
        language: str = "zh",
    ) -> str:
        result_lower = (result or "").lower()
        command = (command or "").strip()
        if language == "en":
            if is_dangerous:
                return f"Blocked for safety: {risk_reason or 'high-risk command'}."
            if "前检查失败" in result or "验证失败" in result:
                return "The command was stopped by a state check or failed post-verification."
            if "ssh 连接未建立" in result_lower:
                return "SSH is not connected, so the command could not run."
            if "[stderr]" in result_lower and "not found" in result_lower and "userdel" in command:
                return "The command completed, but cleanup reported a non-critical missing mail spool."
            if "❌" in result or "error" in result_lower or "failed" in result_lower:
                return "The command failed. Check permissions, parameters, or target state."
            if needs_warning:
                return "The command completed. Please review the output because it changes system state."
            return "The command completed successfully."

        if is_dangerous:
            return f"已按安全策略拦截：{risk_reason or '高风险命令'}。"
        if "前检查失败" in result or "验证失败" in result:
            return "命令已被状态检查拦下，或执行后验证未通过。"
        if "ssh 连接未建立" in result_lower:
            return "SSH 连接未建立，命令未执行。"
        if "[stderr]" in result_lower and "未找到" in result and "userdel" in command:
            return "命令已完成，附带的清理步骤提示未找到信件池，不影响用户删除结果。"
        if "❌" in result or "error" in result_lower or "failed" in result_lower:
            return "命令执行失败，请检查权限、参数或目标状态。"
        if needs_warning:
            return "命令已完成，但它会修改系统状态，建议核对结果输出。"
        return "命令执行成功。"

    def parse_complex_task(self, user_input: str, preferred_language: str = "auto") -> Dict:
        result = self.get_command_from_qwen(user_input, preferred_language=preferred_language)
        if result.get("is_complex"):
            return result
        return {
            "is_complex": False,
            "explanation": result.get("explanation", ""),
            "response_language": result.get("response_language", self._infer_language(user_input)),
            "steps": [
                {
                    "step": 1,
                    "command": result.get("command", ""),
                    "explanation": result.get("explanation", ""),
                    "risk_level": result.get("risk_level", "low"),
                }
            ],
        }

    def process_user_input(self, user_input: str):
        print(Fore.CYAN + f"\n🧠 正在理解: '{user_input}'")
        parsed = self.get_command_from_qwen(user_input)
        print(Fore.GREEN + f"💡 计划执行: {json.dumps(parsed, ensure_ascii=False)}")
        return parsed

    def process_complex_task(self, user_input: str):
        print(Fore.CYAN + f"\n🔍 正在分析任务: '{user_input}'")
        task_plan = self.parse_complex_task(user_input)
        print(Fore.GREEN + json.dumps(task_plan, ensure_ascii=False, indent=2))
        return task_plan

    def run_loop(self):
        print(Fore.GREEN + "🤖 操作系统智能代理已启动 (输入 'exit' 退出)")
        while True:
            user_input = input("\n请输入指令: ").strip()
            if user_input.lower() in ["exit", "quit", "退出"]:
                print(Fore.GREEN + "👋 再见！")
                break
            if user_input:
                self.process_complex_task(user_input)


if __name__ == "__main__":
    OSAgent().run_loop()
