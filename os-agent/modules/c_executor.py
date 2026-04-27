import re
# 这个文件是基于我的学校里面的os实验报告格式进行提取的c语言命令模板兼容性可能不强，后续可以接入api进行提取
class CExecutor:
    def __init__(self):
        self.ssh_executor = None

    def set_ssh_executor(self, executor):
        self.ssh_executor = executor

    def execute(self, code: str, timeout: int = 30) -> dict:
        if not self.ssh_executor:
            return {
                "success": False,
                "output": "",
                "error": "SSH 执行器未配置，无法在远程服务器执行",
            }
        code = self._clean_code(code)
        code = self._auto_add_headers(code)
        if "main" not in code:
            return {
                "success": False,
                "output": "",
                "error": "代码中没有找到main函数",
            }
        if self._is_interactive_program(code):
            return {
                "success": False,
                "output": "",
                "error": "⚠️ 此程序包含交互式输入（如 scanf），无法自动执行。\n💡 建议：请在终端中手动运行，或修改代码使用硬编码测试数据。",
            }
        import time
        import random

        file_id = f"{int(time.time())}_{random.randint(1000, 9999)}"
        filename = f"/tmp/program_{file_id}.c"
        output_name = f"/tmp/program_{file_id}"
        try:
            create_cmd = f'cat > {filename} << "EOF"\n{code}\nEOF'
            result = self.ssh_executor.execute(create_cmd, skip_confirmation=True)
            if "error" in result.lower() or "❌" in result:
                return {
                    "success": False,
                    "output": "",
                    "error": f"创建文件失败: {result}",
                }
            compile_cmd = f"gcc {filename} -o {output_name} 2>&1"
            compile_result = self.ssh_executor.execute(compile_cmd, skip_confirmation=True)
            if "error" in compile_result.lower() or "❌" in compile_result:
                self.ssh_executor.execute(f"rm -f {filename}", skip_confirmation=True)
                return {
                    "success": False,
                    "output": "",
                    "error": f"编译失败:\n{compile_result}",
                }
            run_cmd = f"{output_name}"
            run_result = self.ssh_executor.execute(run_cmd, skip_confirmation=True)
            self.ssh_executor.execute(f"rm -f {filename} {output_name}", skip_confirmation=True)

            if not run_result or run_result == "(命令执行成功，无输出)":
                run_result = "✅ 程序执行成功（无输出）"
            return {
                "success": True,
                "output": run_result[:2000],
                "error": "",
            }
        except Exception as e:
            try:
                self.ssh_executor.execute(f"rm -f {filename} {output_name}", skip_confirmation=True)
            except Exception:
                pass

            return {
                "success": False,
                "output": "",
                "error": f"执行异常: {str(e)}",
            }

    def _clean_code(self, code: str) -> str:
        punctuation_map = {
            "“": '"',
            "”": '"',
            "‘": "'",
            "’": "'",
            "（": "(",
            "）": ")",
            "；": ";",
            "：": ":",
            "，": ",",
            "。": ".",
            "！": "!",
            "？": "?",
            "【": "[",
            "】": "]",
            "《": "<",
            "》": ">",
            "—": "-",
            "–": "-",
            "　": " ",
        }
        for chinese, english in punctuation_map.items():
            code = code.replace(chinese, english)
        code = code.replace("“", '"').replace("”", '"')
        code = code.replace("‘", "'").replace("’", "'")
        lines = code.strip().split("\n")
        cleaned = []
        for line in lines:
            line_stripped = line.strip()

            if line_stripped in ["```c", "```", "```cpp"]:
                continue
            if not line_stripped:
                cleaned.append(line)
                continue
            if re.search(r"[\u4e00-\u9fff]", line):
                if "//" in line or "/*" in line or "*/" in line:
                    cleaned.append(line)
                continue
            if re.match(r"^\d+[\.\、]\s*", line_stripped):
                line = re.sub(r"^\d+[\.\、]\s*", "", line_stripped)
            if re.search(r"[\u4e00-\u9fff]", line) and "//" not in line and "/*" not in line:
                continue
            cleaned.append(line)
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        return "\n".join(cleaned)

    def _auto_add_headers(self, code: str) -> str:
        if "main()" in code and "int main()" not in code and "void main()" not in code:
            code = code.replace("main()", "int main()")
        needs_stdio = any(kw in code for kw in ["printf", "scanf", "puts", "putchar", "getchar"])
        needs_unistd = any(kw in code for kw in ["fork", "getpid", "getppid", "exec", "sleep"])
        needs_sys_types = "pid_t" in code
        needs_stdlib = any(kw in code for kw in ["malloc", "free", "exit", "atoi", "rand"])
        needs_string = any(kw in code for kw in ["strcpy", "strlen", "strcmp", "memset", "strcat"])
        missing_includes = []
        code_lower = code.lower()
        if needs_stdio and "#include <stdio.h>" not in code_lower:
            missing_includes.append("#include <stdio.h>")
        if needs_unistd and "#include <unistd.h>" not in code_lower:
            missing_includes.append("#include <unistd.h>")
        if needs_sys_types and "#include <sys/types.h>" not in code_lower:
            missing_includes.append("#include <sys/types.h>")
        if needs_stdlib and "#include <stdlib.h>" not in code_lower:
            missing_includes.append("#include <stdlib.h>")
        if needs_string and "#include <string.h>" not in code_lower:
            missing_includes.append("#include <string.h>")
        if missing_includes:
            includes_str = "\n".join(missing_includes)
            code = includes_str + "\n\n" + code
        return code

    def _is_interactive_program(self, code: str) -> bool:
        interactive_keywords = [
            "scanf",
            "getchar",
            "getch",
            "getche",
            "gets",
            "fgets(stdin",
            "cin",
            "System.console()",
            "readLine",
        ]
        code_lower = code.lower()
        return any(kw in code_lower for kw in interactive_keywords)


c_executor = CExecutor()
