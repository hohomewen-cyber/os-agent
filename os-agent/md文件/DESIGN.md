# DESIGN

## 1. 架构概览

系统采用“Web 交互层 + Agent 决策层 + 安全控制层 + 环境感知层 + 远程执行层 + 审计持久层”的六层结构。

1. Web 交互层
   - `app.py`
   - 负责页面展示、聊天记录、语音录音、确认交互和执行结果回显
2. Agent 决策层
   - `agent.py`
   - 负责意图理解、命令规划、复杂任务拆解和结果总结
3. 安全控制层
   - `executor.py`
   - 负责风险分级、敏感命令识别、执行前检查、执行后验证和统一执行入口
4. 环境感知层
   - `executor.py`
   - 负责探测远程系统、包管理器、当前用户与权限状态
5. 审计持久层
   - `modules/audit_store.py`
   - 负责审计日志落盘、读取、导出与清空
6. 功能模块层
   - `modules/c_executor.py`
   - `modules/document_parser.py`
   - `modules/windows_terminal.py`
   - `voice_input.py`

## 2. 模块说明

### app.py

- Streamlit 主页面
- 管理聊天输入、复杂任务确认、批量执行和语音输入接入

### agent.py

- 封装千问模型调用
- 输出严格 JSON 计划
- 支持复杂任务拆解和自然语言反馈生成

### executor.py

- SSH 建连与命令执行
- 基于规则进行低、中、高风险识别
- 高风险命令直接拒绝
- 环境信息感知
- 执行前状态检查与执行后状态验证

### voice_input.py

- 接收录音字节流
- 构建 Base64 Data URL
- 调用千问 ASR 模型转写
- 输出纯文本识别结果

### modules/c_executor.py

- 处理 C 代码清洗、补头文件、远端编译和执行

### modules/document_parser.py

- 以 AI 为主、规则兜底，从 TXT / MD / PDF 中提取 Linux 命令和 C 代码片段

### modules/windows_terminal.py

- 在 Windows 桌面终端模式下辅助执行命令

## 3. 安全机制

### 风险分层

- 低风险：查询类命令、普通用户创建和删除
- 中风险：密码修改、权限修改、删除普通文件、停止服务
- 高风险：删除系统核心目录、格式化磁盘、重启/关机、远程脚本直连执行

### 处置策略

- 低风险：允许直接执行
- 中风险：提示风险并进行二次确认
- 高风险：拒绝执行并给出说明
- 执行前：对删除、权限、进程、用户等目标做状态检查
- 执行后：对安装、删除、服务、用户类动作做结果验证

### 可解释性

- 每条命令都带执行说明
- 风险来源同时参考大模型初判和本地规则
- 执行后基于统一执行结果生成自然语言反馈
- 页面、AI 反馈与终端镜像保持一致

## 4. 技术选型

- 前端框架：Streamlit
- 大模型接口：Qwen / DashScope OpenAI Compatible API
- 语音识别：Qwen ASR
- 远程执行：Paramiko SSH
- PDF 解析：pdfplumber + pypdf 兜底
- Windows 终端桥接：pyautogui + pygetwindow + pyperclip

## 5. 创新点

- 在运维场景中结合文本输入与语音输入
- 录音完成后自动识别并自动填入底部聊天输入框
- 大模型规划与本地安全规则双保险
- 环境感知 + 状态检查 + 结果验证形成执行闭环
- 同时支持单轮命令、多步复杂任务和文档驱动批量执行
- 提供去命令行化的 Linux 运维交互体验
