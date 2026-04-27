import streamlit as st
import datetime
import hashlib
import json
import os
import re
import time
from streamlit.components.v1 import html
from config import QWEN_MODEL
from modules.audit_store import AuditLogStore, build_audit_entry
from modules.c_executor import c_executor
from modules.document_parser import DocumentParser
# from modules.windows_terminal import terminal as win_terminal
from executor import executor
from agent import OSAgent
from voice_input import transcribe_audio_bytes
st.set_page_config(
    page_title="🤖 操作系统智能代理",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
section[data-testid="stSidebar"] {
    background: #f8fafc;
    border-right: 1px solid #e2e8f0;
}
section[data-testid="stSidebar"] .stMarkdown {
    color: #1e293b;
}
section[data-testid="stSidebar"] h3 {
    color: #334155 !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    margin-top: 20px !important;
}
section[data-testid="stSidebar"] [data-testid="stMetricValue"] {
    color: #2563eb !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
    color: #64748b !important;
    font-size: 12px !important;
}

.risk-high {
    background: #fee2e2;
    color: #dc2626;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 12px;
    display: inline-block;
}
.risk-medium {
    background: #fef3c7;
    color: #d97706;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 12px;
    display: inline-block;
}
.risk-low {
    background: #d1fae5;
    color: #059669;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 12px;
    display: inline-block;
}

.stSuccess {
    background: #f0fdf4 !important;
    border: 1px solid #bbf7d0 !important;
    border-radius: 8px !important;
}
.stWarning {
    background: #fefce8 !important;
    border: 1px solid #fef08a !important;
    border-radius: 8px !important;
}
.stError {
    background: #fef2f2 !important;
    border: 1px solid #fecaca !important;
    border-radius: 8px !important;
}
.stInfo {
    background: #eff6ff !important;
    border: 1px solid #bfdbfe !important;
    border-radius: 8px !important;
}

.main-title {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
</style>
""", unsafe_allow_html=True)
st.markdown("""
<h1 style='margin-bottom: 0;'>
    <span class='main-title'>
        🤖 操作系统智能代理
    </span>
</h1>
<p style='color: #64748b; margin-top: 0; font-size: 16px;'>
    用自然语言管理 Linux 服务器 — AI 实时操控终端
</p>
""", unsafe_allow_html=True)
AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "data", "audit_log.json")
audit_store = AuditLogStore(AUDIT_LOG_PATH)
if "agent" not in st.session_state:
    st.session_state.agent = OSAgent()
    st.session_state.messages = []
    st.session_state.terminal_ready = False
    st.session_state.complex_mode = False
    st.session_state.query_history = []
    st.session_state.pending_task = None
    st.session_state.pending_complex_task = None
    st.session_state.confirmation_request = None
    st.session_state.audit_log = audit_store.load()
    st.session_state.voice_transcript = ""
    st.session_state.voice_transcript_hash = ""
    st.session_state.voice_transcript_error = ""
    st.session_state.doc_parse_cache = {}
agent = st.session_state.agent
st.session_state.setdefault("doc_parse_cache", {})
agent.set_env_info(executor.refresh_env_info())
c_executor.ssh_executor = executor
INTERACTIVE_COMMANDS = [
    "passwd", "vim", "vi", "nano", "emacs", "gedit",
    "top", "htop", "less", "more", "man", "info",
    "sudo su", "su -", "su ", "bash", "sh", "zsh", "fish",
    "mysql", "psql", "sqlite3", "mongo", "redis-cli",
    "python", "python3", "node", "irb", "ghci", "gdb",
    "ssh ", "telnet", "ftp", "sftp",
    "watch ", "tail -f",
]


def is_interactive_command(command):
    cmd_lower = command.lower().strip()
    for interactive in INTERACTIVE_COMMANDS:
        if interactive in cmd_lower:
            return True, interactive
    return False, None


def is_programming_task(user_input, command):
    programming_keywords = [
        "写代码", "编写代码", "生成代码", "c语言", "c程序", "c代码",
        "python程序", "java程序", "cpp程序", "hello world", "程序", "代码",
        "打印", "输出", "函数", "main", "include", "printf",
        "cout", "system.out", "console.log", "print("
    ]

    user_lower = user_input.lower()
    cmd_lower = command.lower()

    for kw in programming_keywords:
        if kw in user_lower:
            return True

    if any(editor in cmd_lower for editor in ["vim", "vi", "nano", "emacs", "gedit"]) and any(
        marker in user_lower for marker in ["代码", "程序", "c语言", "python", "java", "cpp"]
    ):
        return True

    return False

def generate_c_code_with_ai(user_input):
    """调用AI生成C代码"""
    prompt = f"""用户需求：{user_input}
请生成一个完整的C语言程序。
要求：
1. 代码必须完整，包含main函数和必要的头文件
2. 不能使用交互式输入（如scanf、getchar等），测试数据必须硬编码在代码中
3. 程序功能要完全符合用户需求
4. 只输出纯C代码，不要任何解释
请直接输出C代码："""
    try:
        response = agent.client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的C语言程序员，只输出代码，不输出任何解释。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1000
        )
        code = response.choices[0].message.content.strip()
        code = re.sub(r'^```c?\s*\n', '', code)
        code = re.sub(r'\n```\s*$', '', code)
        return code
    except Exception as e:
        return f"#include <stdio.h>\n\nint main() {{\n    printf(\"代码生成失败: {e}\\n\");\n    return 1;\n}}"
def generate_programming_commands_with_ai(user_input):
    """调用AI生成编程任务的完整命令序列"""
    code = generate_c_code_with_ai(user_input)
    # 生成文件名
    prompt = f"""用户需求：{user_input}
请为这个C程序生成一个合适的文件名（只包含字母数字下划线，以.c结尾）。
只输出文件名，不要任何解释。"""
    try:
        response = agent.client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的程序员，只输出文件名。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=50
        )
        filename = response.choices[0].message.content.strip()
        if not filename.endswith('.c'):
            filename += '.c'
    except:
        filename = "program.c"
    # 构建命令序列
    commands = []
    # 创建文件
    commands.append(f"cat > {filename} << 'EOF'\n{code}\nEOF")
    # 编译
    output_file = filename.replace('.c', '')
    commands.append(f"gcc {filename} -o {output_file}")
    # 运行
    commands.append(f"./{output_file}")
    return commands, filename, "c", code
def get_alternative_suggestion(command, user_input=""):
    cmd_lower = command.lower().strip()

    if is_programming_task(user_input, command):
        return "💡 **编程任务处理:** 将使用AI生成代码，然后编译运行。"

    if "passwd" in cmd_lower:
        return "💡 **替代方案:** 使用 `echo '用户名:新密码' | sudo chpasswd` 可非交互式修改密码"

    if any(e in cmd_lower for e in ["vim", "vi", "nano", "emacs"]):
        return "💡 **替代方案:** 使用 `echo '内容' >> 文件` 追加内容，或 `cat > 文件 << EOF` 写入多行内容"

    if "top" in cmd_lower or "htop" in cmd_lower:
        return "💡 **替代方案:** 使用 `ps aux` 查看进程列表，或 `top -bn1` 获取一次性快照"

    if "less" in cmd_lower or "more" in cmd_lower:
        return "💡 **替代方案:** 使用 `cat 文件名` 直接显示全部内容"

    if "su" in cmd_lower:
        return "💡 **替代方案:** 在需要的命令前直接加 `sudo`，无需切换用户"

    if any(db in cmd_lower for db in ["mysql", "psql", "sqlite3", "mongo"]):
        return "💡 **替代方案:** 使用 `echo 'SQL语句' | mysql 数据库名` 执行单条查询"

    if "watch" in cmd_lower or "tail -f" in cmd_lower:
        return "💡 **替代方案:** 该命令会持续运行，建议在终端中手动执行"

    return "💡 **提示:** 交互式命令不适合远程自动执行，建议在终端中手动操作"
def get_risk_level_from_executor(command):
    """使用 executor 的统一风险判断"""
    try:
        risk_level, is_interactive, reason = executor.check_command_safety(command)
        # 转换为显示用的中文
        if risk_level == "high":
            return "高", reason
        elif risk_level == "medium":
            return "中", reason
        else:
            return "低", reason
    except Exception as e:
        # 降级：简单判断
        cmd_lower = command.lower()
        if any(h in cmd_lower for h in ["rm -rf /", "mkfs", "dd if=", "shutdown", "reboot"]):
            return "高", "高危操作"
        elif any(m in cmd_lower for m in ["rm ", "userdel", "kill", "chmod"]):
            return "中", "中风险操作"
        return "低", "低风险操作"
# ==================== 历史记录管理 ====================
def check_duplicate(query):
    query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()
    for item in st.session_state.query_history:
        if item["hash"] == query_hash:
            return True, item
    return False, None

def add_to_history(query, command, explanation, risk, output=None, status="success"):
    st.session_state.query_history.append({
        "hash": hashlib.md5(query.lower().strip().encode()).hexdigest(),
        "query": query[:40] + "..." if len(query) > 40 else query,
        "full_query": query,
        "command": command,
        "explanation": explanation,
        "risk": risk,
        "output": output,
        "status": status,
        "time": datetime.datetime.now().strftime("%H:%M")
    })


def add_audit_log(stage, detail, status="info"):
    st.session_state.audit_log = audit_store.append(build_audit_entry(stage, detail, status))


def clear_audit_log():
    audit_store.clear()
    st.session_state.audit_log = []


def export_audit_log_text():
    return audit_store.export_text()


def result_has_failed(result):
    return not result.success


def result_status(result):
    return "error" if result_has_failed(result) else "success"


def execute_single_command(command, explanation=""):
    result = executor.execute_with_details(command)
    agent.set_env_info(result.env_snapshot)
    if st.session_state.get("terminal_ready"):
        win_terminal.render_execution(result.display_command, result.combined_output())
    return result


def execute_programming_task(commands, filename, lang, code):
    """执行编程任务（多步骤）"""
    results = []

    # 第一步：创建文件（用printf方式，更安全）
    st.info(f"📝 创建源文件 `{filename}`...")

    # 转义代码中的特殊字符
    escaped_code = code.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')

    # 构建创建文件的命令
    create_cmd = f'printf "%s\\n" "{escaped_code}" > {filename}'

    # SSH执行创建文件
    output1 = executor.execute(f"cat > {filename} << 'EOF'\n{code}\nEOF")
    if st.session_state.get("terminal_ready"):
        win_terminal.render_execution(f"cat > {filename} << 'EOF' ... EOF", output1)
    results.append(output1)

    if output1 and ("error" in output1.lower() or "❌" in output1):
        st.error(f"创建文件失败:\n{output1}")
        return False, results

    # 第二步：编译
    st.info(f"🔨 编译 `{filename}`...")
    output_file = filename.replace('.c', '').replace('.cpp', '')
    compile_cmd = f"gcc {filename} -o {output_file}"

    output2 = executor.execute(compile_cmd)
    if st.session_state.get("terminal_ready"):
        win_terminal.render_execution(compile_cmd, output2)
    results.append(output2)

    if output2 and ("error" in output2.lower() or "❌" in output2):
        st.error(f"编译失败:\n{output2}")

        # 尝试用AI修复
        st.warning("🤖 正在尝试用AI修复编译错误...")
        fix_prompt = f"""以下C代码编译失败：
代码：
{code}

编译错误：
{output2}

请修正代码，只输出修正后的完整C代码，不要任何解释。"""

        try:
            response = agent.client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个专业的C语言程序员，只输出修正后的代码。"},
                    {"role": "user", "content": fix_prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            fixed_code = response.choices[0].message.content.strip()
            fixed_code = re.sub(r'^```c?\s*\n', '', fixed_code)
            fixed_code = re.sub(r'\n```\s*$', '', fixed_code)

            st.info("📝 重新创建修复后的文件...")
            output_retry = executor.execute(f"cat > {filename} << 'EOF'\n{fixed_code}\nEOF")
            output2 = executor.execute(compile_cmd)

            if output2 and ("error" in output2.lower() or "❌" in output2):
                st.error(f"修复后仍编译失败:\n{output2}")
                return False, results
        except:
            return False, results

    # 第三步：运行
    st.info(f"🚀 运行程序...")
    run_cmd = f"./{output_file}"

    output3 = executor.execute(run_cmd)
    if st.session_state.get("terminal_ready"):
        win_terminal.render_execution(run_cmd, output3)
    results.append(output3)

    if output3:
        st.code(output3, language="bash")

    return True, results

# ==================== 侧边栏 ====================
with st.sidebar:
    st.markdown("### 📊 系统状态")

    try:
        env_info = executor.refresh_env_info()
        agent.set_env_info(env_info)
        system_snapshot = executor.get_system_snapshot()
        hostname = system_snapshot.get("HOST", "").strip()
        uptime = system_snapshot.get("UP", "").strip()
        memory_raw = system_snapshot.get("MEM", "").strip()
        disk_raw = system_snapshot.get("DISK", "").strip()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("🖥️ 主机", hostname[:12] if hostname else "未知")
            st.metric("⏱️ 运行", uptime or "未知")
        with col2:
            mem_display = memory_raw if memory_raw and "command" not in memory_raw else "--"
            disk_display = disk_raw if disk_raw and "command" not in disk_raw else "--"
            st.metric("📊 内存", mem_display)
            st.metric("💾 磁盘", disk_display)
    except:
        st.warning("⚠️ 连接失败")

    st.divider()
    st.markdown("### 🌍 环境感知")
    st.caption(f"系统: {executor.env_info.get('distribution', 'unknown')}")
    st.caption(f"包管理器: {executor.env_info.get('package_manager', 'unknown')}")
    st.caption(f"当前用户: {executor.env_info.get('current_user', 'unknown')}")
    st.caption(f"权限: {'root' if executor.env_info.get('is_root') else '普通用户'}")

    st.divider()

    st.markdown("### 🖥️ 终端")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 检测", use_container_width=True):
            if win_terminal.find_terminal():
                st.session_state.terminal_ready = True
                st.toast("✅ 终端已就绪", icon="✅")
            else:
                st.session_state.terminal_ready = False
                st.toast("❌ 未找到", icon="❌")
    with col2:
        complex_mode = st.toggle("📋 复杂", value=st.session_state.complex_mode)
        st.session_state.complex_mode = complex_mode

    if st.session_state.get("terminal_ready"):
        st.success("✅ 终端就绪")
    else:
        st.info("点击检测终端")

    st.divider()
    st.markdown("### 📜 审计日志")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 清空", use_container_width=True):
            clear_audit_log()
            st.rerun()
    with col2:
        st.download_button(
            "📤 导出",
            data=export_audit_log_text(),
            file_name=f"audit_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            use_container_width=True,
        )
    if st.session_state.audit_log:
        for item in reversed(st.session_state.audit_log[-8:]):
            status_icon = "⚠️" if item["status"] == "warning" else ("❌" if item["status"] == "error" else "✅")
            st.caption(f"{item['time']} {status_icon} {item['stage']} | {item['detail'][:42]}")
    else:
        st.caption("暂无审计日志")

    st.divider()
    st.divider()
    # ========== 新增：文档上传（支持 PDF/TXT/MD） ==========
    st.markdown("### 📄 上传实验报告")

    uploaded_file = st.file_uploader(
        "选择文件 (.txt / .md / .pdf)",
        type=["txt", "md", "pdf"],
        key="report_uploader"
    )

    if uploaded_file is not None:
        # 显示文件名
        st.info(f"📄 文件: {uploaded_file.name}")
        file_bytes = uploaded_file.getvalue()
        file_hash = hashlib.md5(file_bytes).hexdigest()

        # 根据文件类型读取内容
        content = ""
        file_type = uploaded_file.type

        try:
            if file_type == "application/pdf":
                try:
                    import io
                    import pdfplumber

                    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                        for page in pdf.pages:
                            content += (page.extract_text() or "") + "\n"
                    st.success("✅ PDF 解析成功")
                except Exception as e:
                    try:
                        import io
                        from pypdf import PdfReader

                        reader = PdfReader(io.BytesIO(file_bytes))
                        for page in reader.pages:
                            content += (page.extract_text() or "") + "\n"
                        st.success("✅ PDF 解析成功（pypdf 兜底）")
                    except Exception as fallback_error:
                        st.error(f"❌ PDF 解析失败: {e} | 兜底失败: {fallback_error}")
                        content = ""
            else:
                # TXT / MD 直接读取
                content = file_bytes.decode("utf-8")
                st.success("✅ 文件读取成功")
        except Exception as e:
            st.error(f"❌ 文件读取失败: {e}")
            content = ""

        if content:
            cached_parse = st.session_state.doc_parse_cache.get(file_hash)
            if cached_parse:
                commands = cached_parse["commands"]
                c_codes = cached_parse["c_codes"]
                diagnostics = cached_parse["diagnostics"]
            else:
                with st.spinner("解析中..."):
                    commands, c_codes = DocumentParser.parse_file(content)
                    diagnostics = DocumentParser.get_last_diagnostics()
                st.session_state.doc_parse_cache[file_hash] = {
                    "commands": commands,
                    "c_codes": c_codes,
                    "diagnostics": diagnostics,
                }

            low = [c for c in commands if c["risk"] == "low"]
            medium = [c for c in commands if c["risk"] == "medium"]
            high = [c for c in commands if c["risk"] == "high"]

            st.success(f"✅ 识别完成")
            st.write(f"🔒 低风险: {len(low)} | ⚠️ 中风险: {len(medium)} | 🚫 高风险: {len(high)}")
            st.write(f"📝 C代码: {len(c_codes)} 段")
            if not commands and not c_codes:
                st.warning("⚠️ 当前文档未识别出可执行命令或代码，请检查文档内容是否为实验步骤、命令记录或代码片段。")
            st.caption(f"解析引擎: {diagnostics.get('engine', 'unknown')}")
            if diagnostics.get("messages"):
                with st.expander("📋 解析诊断", expanded=False):
                    for message in diagnostics["messages"]:
                        st.write(f"- {message}")

            st.session_state.doc_commands = commands
            st.session_state.doc_c_codes = c_codes
            add_audit_log("文档解析", f"{uploaded_file.name} | 命令 {len(commands)} 条 | 代码 {len(c_codes)} 段")

            if st.button("📋 开始执行", type="primary", use_container_width=True):
                st.session_state.show_doc_executor = True
                st.rerun()
        else:
            st.warning("⚠️ 文件内容为空或解析失败")

    st.divider()
    st.markdown("### 🕘 历史记录")
    if st.session_state.query_history:
        for item in reversed(st.session_state.query_history[-8:]):
            risk_icon = "🔴" if item["risk"] == "高" else ("🟡" if item["risk"] == "中" else "🟢")
            status_icon = "✅" if item.get("status") == "success" else "❌"

            with st.container():
                st.markdown(f"""
                <div style='padding:8px 12px;margin:4px 0;background:white;border-radius:8px;border:1px solid #e2e8f0;'>
                    <div style='display:flex;align-items:center;gap:6px;'>
                        <span style='font-size:10px;color:#94a3b8;'>{item['time']}</span>
                        <span>{risk_icon}</span>
                        <span>{status_icon}</span>
                    </div>
                    <div style='font-size:13px;color:#1e293b;margin-top:4px;'>{item['query']}</div>
                    <div style='font-size:11px;color:#64748b;margin-top:2px;'><code>{item['command'][:25]}</code></div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.caption("暂无历史记录")

# ==================== 显示历史消息 ====================
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["content"])
        else:
            if msg.get("command"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**📝 计划执行:** `{msg['command']}`")
                with col2:
                    risk = msg.get("risk", "低")
                    if risk == "高":
                        st.markdown('<span class="risk-high">⚠️ 高风险</span>', unsafe_allow_html=True)
                    elif risk == "中":
                        st.markdown('<span class="risk-medium">⚡ 中风险</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="risk-low">✅ 低风险</span>', unsafe_allow_html=True)
                st.caption(f"📋 {msg.get('explanation', '')}")

            if msg.get("output"):
                with st.expander("📋 查看结果", expanded=False):
                    st.code(msg["output"], language="bash")

            if msg.get("feedback"):
                if msg.get("status") == "blocked":
                    st.error(f"💬 {msg['feedback']}")
                elif msg.get("status") == "pending_confirmation":
                    st.warning(f"💬 {msg['feedback']}")
                elif msg.get("status") == "skipped":
                    st.info(f"💬 {msg['feedback']}")
                elif msg.get("status") == "error":
                    st.warning(f"💬 {msg['feedback']}")
                elif msg.get("status") == "cancelled":
                    st.info(f"💬 {msg['feedback']}")
                else:
                    st.success(f"💬 {msg['feedback']}")
# ==================== 文档批量执行模式 ====================

if st.session_state.get("show_doc_executor", False):
    commands = st.session_state.get("doc_commands", [])
    c_codes = st.session_state.get("doc_c_codes", [])

    st.markdown("## 📋 实验报告命令执行")

    # 显示C代码
    if c_codes:
        st.markdown("### 📝 C代码片段")
        for i, code_info in enumerate(c_codes):
            with st.expander(f"{code_info['name']} (行 {code_info['line']})", expanded=False):
                st.code(code_info["code"], language="c")
                col1, col2 = st.columns(2)
                with col1:
                    # 添加复选框，用于批量执行
                    st.checkbox("加入批量执行", key=f"select_c_{i}")
                with col2:
                    # 单独编译运行按钮
                    if st.button(f"▶️ 单独运行", key=f"run_c_{i}"):
                        result = c_executor.execute(code_info["code"])
                        if result["success"]:
                            st.success("✅ 执行成功")
                            st.code(result["output"])
                        else:
                            st.error(f"❌ 执行失败: {result['error']}")

    # 显示命令
    if commands:
        st.markdown("### 💻 Linux命令")

        # 按风险分组显示
        low_risk_cmds = [c for c in commands if c["risk"] == "low"]
        medium_risk_cmds = [c for c in commands if c["risk"] == "medium"]
        high_risk_cmds = [c for c in commands if c["risk"] == "high"]

        # 低风险（默认选中）
        if low_risk_cmds:
            st.markdown("#### 🔒 低风险命令（自动执行）")
            for i, cmd_info in enumerate(low_risk_cmds):
                col1, col2 = st.columns([1, 10])
                with col1:
                    selected = st.checkbox("", value=True, key=f"low_{i}")
                with col2:
                    st.markdown(f"`{cmd_info['command']}`")
                    st.caption(f"行 {cmd_info['line']}")

        # 中风险（默认不选中）
        if medium_risk_cmds:
            st.markdown("#### ⚠️ 中风险命令（建议手动执行）")
            for i, cmd_info in enumerate(medium_risk_cmds):
                col1, col2 = st.columns([1, 10])
                with col1:
                    selected = st.checkbox("", value=False, key=f"medium_{i}")
                with col2:
                    st.markdown(f"`{cmd_info['command']}`")
                    st.caption(f"行 {cmd_info['line']} - ⚠️ 可能影响系统状态")

        # 高风险（不可选中）
        if high_risk_cmds:
            st.markdown("#### 🚫 高风险命令（已拦截）")
            for cmd_info in high_risk_cmds:
                st.error(f"`{cmd_info['command']}` - 行 {cmd_info['line']} - 已拦截，请手动执行")

        # 执行按钮
        # 执行按钮
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 执行选中的命令", type="primary", use_container_width=True):
                # 收集选中的命令
                selected_commands = []
                # 低风险（全部选中）
                for cmd_info in low_risk_cmds:
                    selected_commands.append(cmd_info["command"])
                # 中风险（用户勾选的）
                for i, cmd_info in enumerate(medium_risk_cmds):
                    if st.session_state.get(f"medium_{i}", False):
                        selected_commands.append(cmd_info["command"])

                # 收集选中的C代码（用户点击了"编译运行"按钮的）
                selected_c_codes = []
                for i, code_info in enumerate(c_codes):
                    if st.session_state.get(f"select_c_{i}", False):
                        selected_c_codes.append(code_info)

                st.session_state.batch_commands = selected_commands
                st.session_state.batch_c_codes = selected_c_codes
                st.session_state.batch_executing = True
                st.rerun()
        with col2:
            if st.button("❌ 关闭", use_container_width=True):
                st.session_state.show_doc_executor = False
                st.session_state.doc_mode = False
                st.rerun()

    st.divider()
# ==================== 批量执行中 ====================
if st.session_state.get("batch_executing", False):
    import subprocess
    import time
    import hashlib

    commands_to_execute = st.session_state.get("batch_commands", [])
    c_codes_to_execute = st.session_state.get("batch_c_codes", [])

    # 初始化控制变量
    if "execution_pause" not in st.session_state:
        st.session_state.execution_pause = False
    if "execution_stop" not in st.session_state:
        st.session_state.execution_stop = False
    if "execution_skip" not in st.session_state:
        st.session_state.execution_skip = False

    st.markdown("## 🚀 正在批量执行...")

    # 控制按钮
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("⏸️ 暂停", key="pause_btn"):
            st.session_state.execution_pause = True
            st.rerun()
    with col2:
        if st.button("▶️ 继续", key="resume_btn"):
            st.session_state.execution_pause = False
            st.rerun()
    with col3:
        if st.button("⏭️ 跳过当前", key="skip_btn"):
            st.session_state.execution_skip = True
    with col4:
        if st.button("⏹️ 停止", key="stop_btn"):
            st.session_state.execution_stop = True
            st.warning("⏹️ 用户停止执行")

    results = []
    total = len(commands_to_execute) + len(c_codes_to_execute)
    current = 0
    progress_bar = st.progress(0)
    status_text = st.empty()
    current_cmd_text = st.empty()

    # 记录已执行的命令（去重）
    executed_commands = set()

    # ========== 执行C代码 ==========
    for code_info in c_codes_to_execute:
        if st.session_state.execution_stop:
            st.warning("⏹️ 执行已停止")
            break

        while st.session_state.execution_pause:
            time.sleep(0.5)
            if st.session_state.execution_stop:
                break

        if st.session_state.execution_skip:
            st.session_state.execution_skip = False
            st.info(f"⏭️ 跳过C代码: {code_info.get('name', 'C程序')}")
            continue

        current += 1
        progress_bar.progress(current / total)
        status_text.text(f"正在执行C代码 [{current}/{total}]")
        current_cmd_text.info(f"📝 {code_info.get('name', 'C程序')}")

        # 使用c_executor执行
        try:
            result = c_executor.execute(code_info["code"])

            if result["success"]:
                st.success(f"✅ {code_info.get('name', 'C程序')}")
                if result["output"]:
                    with st.expander("📋 查看输出"):
                        st.code(result["output"])
            else:
                st.error(f"❌ {code_info.get('name', 'C程序')}: {result['error']}")

            results.append({
                "type": "C",
                "name": code_info.get("name", "C程序"),
                "success": result["success"],
                "output": result["output"] if result["success"] else result["error"]
            })
        except ImportError:
            st.error("❌ C 代码执行模块未找到，请检查 modules/c_executor.py")
            results.append({
                "type": "C",
                "name": code_info.get("name", "C程序"),
                "success": False,
                "output": "C 代码执行模块未找到"
            })

    # ========== 执行Linux命令 ==========
    for i, command in enumerate(commands_to_execute):
        if st.session_state.execution_stop:
            st.warning("⏹️ 执行已停止")
            break

        while st.session_state.execution_pause:
            time.sleep(0.5)
            if st.session_state.execution_stop:
                break

        if st.session_state.execution_skip:
            st.session_state.execution_skip = False
            st.info(f"⏭️ 跳过命令: {command}")
            results.append({
                "type": "cmd",
                "command": command,
                "success": None,
                "output": "用户跳过",
                "skipped": True
            })
            continue

        # 去重检查
        cmd_hash = hashlib.md5(command.encode()).hexdigest()
        if cmd_hash in executed_commands:
            st.info(f"⏭️ 跳过重复命令: `{command}`")
            results.append({
                "type": "cmd",
                "command": command,
                "success": None,
                "output": "已跳过（重复命令）",
                "skipped": True
            })
            continue

        current += 1
        progress_bar.progress(current / total)
        status_text.text(f"正在执行命令 [{current}/{total}]")
        current_cmd_text.code(f"$ {command}")

        try:
            result = execute_single_command(command)
            output = result.combined_output()
            success = not result_has_failed(result)

            # 截取输出显示
            display_output = output[:500] + ("..." if len(output) > 500 else "")

            if success:
                st.success(f"✅ `{command}`")
                if display_output:
                    with st.expander("📋 查看输出"):
                        st.code(display_output)
            else:
                st.error(f"❌ `{command}`")
                st.code(display_output)

            results.append({
                "type": "cmd",
                "command": command,
                "success": success,
                "output": output[:2000],
                "skipped": False
            })
            executed_commands.add(cmd_hash)

        except subprocess.TimeoutExpired:
            st.error(f"⏰ 超时: `{command}`")
            results.append({
                "type": "cmd",
                "command": command,
                "success": False,
                "output": "执行超时（30秒）",
                "skipped": False
            })
        except Exception as e:
            st.error(f"❌ `{command}` 执行异常: {e}")
            results.append({
                "type": "cmd",
                "command": command,
                "success": False,
                "output": str(e),
                "skipped": False
            })

    # 显示最终结果
    st.markdown("## ✅ 执行完成")

    cmd_success = sum(1 for r in results if r["type"] == "cmd" and r.get("success") is True)
    cmd_fail = sum(1 for r in results if r["type"] == "cmd" and r.get("success") is False)
    cmd_skip = sum(1 for r in results if r["type"] == "cmd" and r.get("skipped", False))
    c_success = sum(1 for r in results if r["type"] == "C" and r.get("success") is True)
    c_fail = sum(1 for r in results if r["type"] == "C" and r.get("success") is False)

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("✅ 命令成功", cmd_success)
    with col2:
        st.metric("❌ 命令失败", cmd_fail)
    with col3:
        st.metric("⏭️ 命令跳过", cmd_skip)
    with col4:
        st.metric("✅ C成功", c_success)
    with col5:
        st.metric("❌ C失败", c_fail)

    # 详细结果
    with st.expander("📋 查看详细结果", expanded=False):
        for r in results:
            if r["type"] == "cmd":
                if r.get("success") is True:
                    st.success(f"✅ `{r['command']}`")
                elif r.get("success") is False:
                    st.error(f"❌ `{r['command']}`")
                    st.code(r["output"][:300], language="bash")
                else:
                    st.info(f"⏭️ `{r['command']}` - {r['output']}")
            else:
                if r["success"]:
                    st.success(f"✅ {r['name']}")
                else:
                    st.error(f"❌ {r['name']}: {r['output']}")

    # 重置状态
    if st.button("返回"):
        st.session_state.batch_executing = False
        st.session_state.batch_commands = []
        st.session_state.batch_c_codes = []
        st.session_state.show_doc_executor = False
        st.session_state.execution_pause = False
        st.session_state.execution_stop = False
        st.session_state.execution_skip = False
        st.rerun()

    st.stop()
# ==================== 用户输入处理 ====================
def risk_to_cn(risk_level):
    return "高" if risk_level == "high" else ("中" if risk_level == "medium" else "低")


def merge_risk(ai_risk, command):
    rule_risk, _, rule_reason = executor.check_command_safety(command)
    levels = {"low": 0, "medium": 1, "high": 2}
    final_risk = rule_risk if levels.get(rule_risk, 0) >= levels.get(ai_risk, 0) else ai_risk
    default_reason = {
        "high": "该命令可能影响系统可用性或关键目录",
        "medium": "该命令会修改系统状态，执行前请确认目标对象和影响范围",
        "low": "低风险操作",
    }
    return final_risk, rule_reason if final_risk == rule_risk else default_reason[final_risk]


def remember_execution(user_prompt, command_text, output_text):
    agent.remember_turn(user_prompt, command_text, output_text[:400] if output_text else "")


def current_ui_language():
    return st.session_state.get("ui_language", "auto")


def append_chat_message(message):
    st.session_state.messages.append(message)
    st.session_state.messages = st.session_state.messages[-50:]


def ensure_user_message(content):
    if not st.session_state.messages or st.session_state.messages[-1].get("content") != content:
        append_chat_message({"role": "user", "content": content})


def parse_language_instruction(prompt_text):
    lower_text = prompt_text.lower()
    direct_mappings = [
        ("用英文回答", "en"),
        ("用英文回复", "en"),
        ("用英文输出", "en"),
        ("用中文回答", "zh"),
        ("用中文回复", "zh"),
        ("用中文输出", "zh"),
    ]
    for marker, language in direct_mappings:
        if marker in prompt_text:
            return language, prompt_text.replace(marker, "").strip(" ，,。!！?")

    patterns = [
        (r"(?:please\s+)?(?:reply|respond|answer|output)\s+in\s+english", "en"),
        (r"(?:please\s+)?(?:reply|respond|answer|output)\s+in\s+chinese", "zh"),
    ]
    for pattern, language in patterns:
        if re.search(pattern, lower_text, re.IGNORECASE):
            cleaned = re.sub(pattern, "", prompt_text, flags=re.IGNORECASE).strip(" ，,。!！?")
            return language, cleaned
    return None, prompt_text


def inject_text_to_chat_input(text_value):
    safe_value = text_value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    html(
        f"""
        <script>
        const textValue = `{safe_value}`;
        const doc = window.parent.document;
        const selectors = [
            'textarea[data-testid="stChatInputTextArea"]',
            'div[data-testid="stChatInput"] textarea',
            'div[data-testid="stChatInput"] input'
        ];

        function fillChatInput() {{
            for (const selector of selectors) {{
                const element = doc.querySelector(selector);
                if (!element) {{
                    continue;
                }}
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
                    'value'
                ).set;
                nativeSetter.call(element, textValue);
                element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                element.focus();
                return;
            }}
        }}

        window.setTimeout(fillChatInput, 50);
        window.setTimeout(fillChatInput, 250);
        </script>
        """,
        height=0,
    )


def handle_voice_input():
    with st.container():
        st.caption("🎤 语音输入：录音结束后会自动识别并填入下方输入框")
        audio_file = st.audio_input(
            "点击录音并说出指令",
            key="voice_input_recorder",
            disabled=st.session_state.confirmation_request is not None,
            label_visibility="collapsed",
        )

    if not audio_file:
        if st.session_state.voice_transcript:
            inject_text_to_chat_input(st.session_state.voice_transcript)
        return

    audio_bytes = audio_file.getvalue()
    audio_hash = hashlib.md5(audio_bytes).hexdigest() if audio_bytes else ""
    if not audio_hash or audio_hash == st.session_state.voice_transcript_hash:
        if st.session_state.voice_transcript:
            inject_text_to_chat_input(st.session_state.voice_transcript)
        if st.session_state.voice_transcript_error:
            st.warning(st.session_state.voice_transcript_error)
        return

    try:
        with st.spinner("🎙️ 正在识别语音..."):
            transcript = transcribe_audio_bytes(
                audio_bytes,
                mime_type=audio_file.type or "audio/wav",
                client=agent.client,
            )
        st.session_state.voice_transcript = transcript
        st.session_state.voice_transcript_hash = audio_hash
        st.session_state.voice_transcript_error = ""
        add_audit_log("语音识别", transcript[:80], "success")
        st.success(f"🎤 已识别：{transcript}")
        inject_text_to_chat_input(transcript)
    except Exception as exc:
        st.session_state.voice_transcript = ""
        st.session_state.voice_transcript_hash = audio_hash
        st.session_state.voice_transcript_error = f"语音识别失败：{exc}"
        add_audit_log("语音识别", str(exc), "error")
        st.error(st.session_state.voice_transcript_error)


def queue_confirmation(task, task_kind, command_text, explanation, smart_risk, risk_reason):
    ensure_user_message(task["prompt"])
    append_chat_message({
        "role": "assistant",
        "command": command_text,
        "explanation": explanation,
        "risk": smart_risk,
        "feedback": f"待确认: {risk_reason}",
        "status": "pending_confirmation",
    })
    st.session_state.confirmation_request = {
        "task": task,
        "task_kind": task_kind,
        "command_text": command_text,
        "explanation": explanation,
        "smart_risk": smart_risk,
        "risk_reason": risk_reason,
    }
    add_audit_log("风险确认", f"{command_text} | {smart_risk}风险 | {risk_reason}", "warning")
    st.rerun()


def run_simple_task(task):
    prompt_text = task["prompt"]
    original_cmd = task["original_cmd"]
    explanation = task["exp"]
    smart_risk = task["smart_risk"]
    language = task.get("language", "zh")
    is_programming = task["is_programming"]
    programming_commands = task.get("programming_commands", [])
    filename = task.get("filename", "")
    lang = task.get("lang", "")
    code = task.get("code", "")

    ensure_user_message(prompt_text)

    with st.chat_message("user"):
        st.write(prompt_text)

    with st.chat_message("assistant"):
        col1, col2 = st.columns([3, 1])
        with col1:
            if is_programming:
                st.markdown("**📝 检测到编程任务:** 将由 AI 生成代码并编译运行")
            else:
                st.markdown(f"**📝 计划执行:** `{original_cmd}`")
        with col2:
            if smart_risk == "高":
                st.markdown('<span class="risk-high">⚠️ 高风险</span>', unsafe_allow_html=True)
            elif smart_risk == "中":
                st.markdown('<span class="risk-medium">⚡ 中风险</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="risk-low">✅ 低风险</span>', unsafe_allow_html=True)
        st.caption(f"📋 {explanation}")

        if is_programming and code:
            st.markdown("**📋 生成的代码:**")
            st.code(code, language="c")

        if is_programming:
            success, results = execute_programming_task(programming_commands, filename, lang, code)
            output = "\n".join(results)
            final_command = "; ".join(programming_commands)
            status = "success" if success else "error"
            add_audit_log("执行编程任务", final_command[:80], status)
            if success:
                feedback = agent.get_feedback_from_qwen(final_command, output, False, False, "", language)
                st.success(f"💬 {feedback}")
            else:
                feedback = "程序执行过程中出现错误，请检查代码或编译输出。"
                st.warning(f"💬 {feedback}")

            with st.expander("📋 查看详细输出", expanded=False):
                st.code(output, language="bash")

            add_to_history(prompt_text, final_command[:100], explanation, smart_risk, output[:500], status)
            remember_execution(prompt_text, final_command, output)
            append_chat_message({
                "role": "assistant",
                "command": final_command[:100],
                "explanation": explanation,
                "risk": smart_risk,
                "output": output,
                "feedback": feedback,
                "status": status,
            })
            return

        with st.spinner("⏳ 执行中..."):
            result = execute_single_command(original_cmd, explanation)
        output = result.combined_output()
        add_audit_log("执行命令", original_cmd[:80], result_status(result))

        is_dangerous = result.blocked
        feedback = agent.get_feedback_from_qwen(
            original_cmd,
            output,
            is_dangerous=is_dangerous,
            needs_warning=(smart_risk == "中"),
            risk_reason=task.get("risk_reason", ""),
            language=language,
        )

        if output:
            with st.expander("📋 查看结果", expanded=False):
                st.code(output, language="bash")

        if result_has_failed(result):
            st.warning(f"💬 {feedback}")
            status = "error"
        else:
            st.success(f"💬 {feedback}")
            status = "success"

        add_to_history(prompt_text, original_cmd, explanation, smart_risk, output, status)
        remember_execution(prompt_text, original_cmd, output)
        append_chat_message({
            "role": "assistant",
            "command": original_cmd,
            "explanation": explanation,
            "risk": smart_risk,
            "output": output,
            "feedback": feedback,
            "status": status,
        })


def run_complex_task(task):
    prompt_text = task["prompt"]
    steps = task["steps"]
    explanation = task.get("exp", "复杂任务")
    smart_risk = task["smart_risk"]
    language = task.get("language", "zh")

    ensure_user_message(prompt_text)

    with st.chat_message("user"):
        st.write(prompt_text)

    with st.chat_message("assistant"):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**📋 复杂任务计划:** 共 {len(steps)} 步")
        with col2:
            if smart_risk == "高":
                st.markdown('<span class="risk-high">⚠️ 高风险</span>', unsafe_allow_html=True)
            elif smart_risk == "中":
                st.markdown('<span class="risk-medium">⚡ 中风险</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="risk-low">✅ 低风险</span>', unsafe_allow_html=True)
        st.caption(f"📋 {explanation}")

        all_outputs = []
        all_success = True
        for step in steps:
            cmd = step["command"]
            exp = step["explanation"]
            step_risk, _ = merge_risk(step.get("risk_level", "low"), cmd)
            st.write(f"**第{step['step']}步:** {exp}")
            st.caption(f"`{cmd}` | 风险: {risk_to_cn(step_risk)}")

            with st.spinner(f"执行中: {cmd[:60]}..."):
                result = execute_single_command(cmd, exp)
            output = result.combined_output()
            add_audit_log("复杂任务步骤", f"第{step['step']}步 {cmd[:60]}", result_status(result))
            all_outputs.append(f"[Step {step['step']}] {output}")

            if output and output != "(命令执行成功，无输出)":
                with st.expander(f"查看第{step['step']}步输出", expanded=False):
                    st.code(output, language="bash")

            if result_has_failed(result):
                st.error(f"第{step['step']}步执行失败")
                all_success = False
                break

        final_output = "\n".join(all_outputs)
        command_summary = "; ".join(step["command"] for step in steps)
        feedback = agent.get_feedback_from_qwen(
            command_summary,
            final_output,
            False,
            smart_risk == "中",
            "",
            language,
        )
        status = "success" if all_success else "error"

        if all_success:
            st.success(f"💬 {feedback}")
        else:
            st.warning(f"💬 {feedback}")

        add_to_history(prompt_text, f"[{len(steps)}步任务]", explanation, smart_risk, final_output[:500], status)
        remember_execution(prompt_text, command_summary, final_output)
        append_chat_message({
            "role": "assistant",
            "command": f"复杂任务({len(steps)}步)",
            "explanation": explanation,
            "risk": smart_risk,
            "output": final_output,
            "feedback": feedback,
            "status": status,
        })


def queue_simple_task(task):
    st.session_state.pending_task = task
    st.rerun()


def queue_complex_task(task):
    st.session_state.pending_complex_task = task
    st.rerun()


def record_cancelled(prompt_text, command_text, explanation, smart_risk):
    st.info("⏸️ 操作已取消")
    add_to_history(prompt_text, command_text, explanation, smart_risk, None, "cancelled")
    add_audit_log("取消操作", command_text, "warning")
    ensure_user_message(prompt_text)
    append_chat_message({
        "role": "assistant",
        "command": command_text,
        "explanation": explanation,
        "risk": smart_risk,
        "feedback": "用户取消了操作",
        "status": "cancelled",
    })


if st.session_state.pending_complex_task is not None:
    task = st.session_state.pending_complex_task
    st.session_state.pending_complex_task = None
    run_complex_task(task)
    st.rerun()

if st.session_state.pending_task is not None:
    task = st.session_state.pending_task
    st.session_state.pending_task = None
    run_simple_task(task)
    st.rerun()

if st.session_state.confirmation_request is not None:
    request = st.session_state.confirmation_request
    st.markdown("## ⚠️ 待确认任务")
    st.warning(f"{request['smart_risk']}风险操作待确认：{request['risk_reason']}")
    st.markdown(f"**计划执行:** `{request['command_text']}`")
    st.caption(f"📋 {request['explanation']}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 确认并执行", type="primary", key="confirm_execute_request"):
            if request["task_kind"] == "complex":
                st.session_state.pending_complex_task = request["task"]
            else:
                st.session_state.pending_task = request["task"]
            st.session_state.confirmation_request = None
            st.rerun()
    with col2:
        if st.button("❌ 取消此次操作", key="cancel_execute_request"):
            task = request["task"]
            prompt_text = task["prompt"]
            record_cancelled(prompt_text, request["command_text"], request["explanation"], request["smart_risk"])
            st.session_state.confirmation_request = None
            st.rerun()

handle_voice_input()

prompt = st.chat_input(
    "请输入指令，例如：查看磁盘空间...",
    disabled=st.session_state.confirmation_request is not None,
)

if prompt:
    instructed_language, cleaned_prompt = parse_language_instruction(prompt)
    if instructed_language:
        st.session_state.ui_language = instructed_language
        prompt = cleaned_prompt or prompt
        language_label = "English" if instructed_language == "en" else "中文"
        add_audit_log("语言切换", f"聊天中切换为 {language_label}")
        if not cleaned_prompt:
            append_chat_message({"role": "user", "content": prompt})
            append_chat_message({
                "role": "assistant",
                "command": "语言切换",
                "explanation": f"后续默认回复语言已切换为 {language_label}",
                "risk": "低",
                "feedback": f"后续我会默认使用 {language_label} 回复。",
                "status": "success",
            })
            st.rerun()

    is_duplicate, dup_item = check_duplicate(prompt)
    if is_duplicate:
        with st.chat_message("assistant"):
            st.info("ℹ️ 这个问题你刚刚问过了")
            st.markdown(f"**上次执行:** `{dup_item['command']}`")
            st.caption(f"📋 {dup_item['explanation']}")
            if dup_item.get("output"):
                with st.expander("📋 查看上次结果"):
                    st.code(dup_item["output"], language="bash")
        ensure_user_message(prompt)
        append_chat_message({
            "role": "assistant",
            "command": dup_item["command"],
            "explanation": dup_item["explanation"],
            "risk": dup_item["risk"],
            "output": dup_item.get("output"),
            "feedback": "这是刚刚执行过的同类请求，直接复用了结果。",
            "status": "duplicate",
        })
        st.rerun()

    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("AI 正在理解..."):
            parsed = agent.get_command_from_qwen(prompt, preferred_language=current_ui_language())

        language = parsed.get("response_language", "zh")
        if parsed.get("is_complex"):
            steps = parsed.get("steps", [])
            if not steps:
                st.error("❌ 未生成可执行步骤")
                st.stop()

            step_risks = []
            for step in steps:
                final_step_risk, _ = merge_risk(step.get("risk_level", "low"), step.get("command", ""))
                step["risk_level"] = final_step_risk
                step_risks.append(final_step_risk)

            overall_risk = "high" if "high" in step_risks else ("medium" if "medium" in step_risks else "low")
            smart_risk = risk_to_cn(overall_risk)
            st.markdown(f"**📋 检测到复杂任务，共 {len(steps)} 个步骤：**")
            for step in steps:
                icon = "🔴" if step["risk_level"] == "high" else ("🟡" if step["risk_level"] == "medium" else "🟢")
                st.caption(f"{icon} 第{step['step']}步: {step['explanation']}")
                st.caption(f"`{step['command'][:100]}{'...' if len(step['command']) > 100 else ''}`")

            task = {
                "prompt": prompt,
                "steps": steps,
                "exp": parsed.get("explanation", "复杂任务"),
                "smart_risk": smart_risk,
                "language": language,
            }

            if overall_risk in ["medium", "high"]:
                queue_confirmation(
                    task=task,
                    task_kind="complex",
                    command_text=f"复杂任务({len(steps)}步)",
                    explanation=parsed.get("explanation", "复杂任务"),
                    smart_risk=smart_risk,
                    risk_reason=f"此任务包含{smart_risk}风险步骤，请确认后执行。",
                )

            queue_complex_task(task)

        original_cmd = parsed.get("command", "")
        explanation = parsed.get("explanation", "")
        if not original_cmd:
            st.error("❌ 未生成可执行命令")
            st.stop()

        final_risk, risk_reason = merge_risk(parsed.get("risk_level", "low"), original_cmd)
        smart_risk = risk_to_cn(final_risk)
        is_programming = is_programming_task(prompt, original_cmd)
        programming_commands, filename, lang, code = ([], "", "", "")
        if is_programming:
            programming_commands, filename, lang, code = generate_programming_commands_with_ai(prompt)

        col1, col2 = st.columns([3, 1])
        with col1:
            if is_programming:
                st.markdown("**📝 检测到编程任务:** 将生成代码并在远程主机执行")
            else:
                st.markdown(f"**📝 计划执行:** `{original_cmd}`")
        with col2:
            if smart_risk == "高":
                st.markdown('<span class="risk-high">⚠️ 高风险</span>', unsafe_allow_html=True)
            elif smart_risk == "中":
                st.markdown('<span class="risk-medium">⚡ 中风险</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="risk-low">✅ 低风险</span>', unsafe_allow_html=True)
        st.caption(f"📋 {explanation}")

        if is_programming and code:
            st.code(code, language="c")

        task = {
            "prompt": prompt,
            "original_cmd": original_cmd,
            "exp": explanation,
            "smart_risk": smart_risk,
            "risk_reason": risk_reason,
            "language": language,
            "is_programming": is_programming,
            "programming_commands": programming_commands,
            "filename": filename,
            "lang": lang,
            "code": code,
        }

        if final_risk in ["medium", "high"]:
            queue_confirmation(
                task=task,
                task_kind="simple",
                command_text=original_cmd,
                explanation=explanation,
                smart_risk=smart_risk,
                risk_reason=risk_reason,
            )

        queue_simple_task(task)
