# 操作系统智能代理

一个基于 Streamlit + 通义千问 + SSH 的 Linux 操作系统智能代理。用户可以通过文本或语音描述需求，系统自动完成意图解析、风险判断、命令执行和自然语言反馈。

## 项目简介

本项目面向 AI Hackathon 2026 预赛题目“操作系统智能代理”。系统运行在 Windows 侧，通过 SSH 连接真实 Linux 服务器，把自然语言请求转换为可执行的系统管理动作，并提供风险预警、二次确认和执行说明。

## 功能特性

- 文本自然语言输入
- 语音录音输入
- 录音结束后自动识别并回填到底部聊天输入框
- Linux 基础运维指令执行
- 普通用户创建与删除
- 文件、目录、端口、磁盘、内存等查询
- 高风险命令拦截
- 中风险命令二次确认
- 多步复杂任务编排
- 环境信息感知并注入 Agent 提示词
- 执行前状态检查（文件/权限/进程/用户）
- 执行后状态验证（安装/删除/服务/用户）
- 审计日志持久化、手动清空与导出
- AI 主导的文档内容解析与批量执行辅助
- 执行结果和风险依据的自然语言反馈

## 目录结构

```text
.
├── app.py
├── agent.py
├── config.py
├── executor.py
├── voice_input.py
├── modules/
│   ├── __init__.py
│   ├── audit_store.py
│   ├── c_executor.py
│   ├── document_parser.py
│   └── windows_terminal.py
├── data/
│   └── audit_log.json
├── requirements.txt
├── README.md
├── DESIGN.md
├── TEST.md
├── AGENT_CONFIG.md
├── PROMPTS.md
├── TOOLS.md
└── DELIVERY_CHECKLIST.md
```

## 安装

1. 安装 Python 3.10 或更高版本
2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 配置环境变量

```bash
set QWEN_API_KEY=你的千问密钥
set QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
set QWEN_MODEL=qwen-plus-2025-07-28
set QWEN_ASR_MODEL=qwen3-asr-flash
set SSH_HOST=你的Linux服务器地址
set SSH_USER=用户名
set SSH_PASSWORD=密码
set SSH_PORT=22
```

## 运行

```bash
streamlit run app.py
```

## 使用示例

文本输入示例：

- 查看磁盘剩余空间
- 查看当前监听端口
- 创建普通用户 demo01
- 删除普通用户 demo01
- 写一个判断素数的 C 程序代码并编译执行

语音输入示例：

1. 点击页面底部上方的录音控件开始录音
2. 说出“查看磁盘剩余空间”
3. 结束录音后，系统自动调用千问语音识别
4. 识别文本自动填入底部聊天输入框
5. 用户可直接发送或继续编辑

## 交付文档

- [DESIGN.md](DESIGN.md)
- [TEST.md](TEST.md)
- [AGENT_CONFIG.md](AGENT_CONFIG.md)
- [PROMPTS.md](PROMPTS.md)
- [TOOLS.md](TOOLS.md)
- [DELIVERY_CHECKLIST.md](DELIVERY_CHECKLIST.md)

## 注意事项

- 项目依赖真实 Linux 环境完成最终演示
- 若未配置 `QWEN_API_KEY`，部分大模型能力与语音识别无法使用
- 若未配置 `QWEN_API_KEY`，文档解析会自动退回规则兜底模式
- 若未配置 SSH 或 `paramiko`，远程执行能力不可用
