# Agent 配置说明

## 1. Agent 组成

本项目采用“程序逻辑 + Agent 决策”混合方案：

- 程序逻辑负责 UI、状态管理、风险控制、SSH 执行、结果展示
- Agent 负责自然语言意图解析、命令规划、复杂任务拆解、反馈总结

## 2. 模型与配置项

配置文件：`config.py`

- `QWEN_API_BASE`：千问兼容模式接口地址
- `QWEN_API_KEY`：千问鉴权密钥
- `QWEN_MODEL`：主对话模型，默认 `qwen-plus-2025-07-28`
- `QWEN_ASR_MODEL`：语音识别模型，默认 `qwen3-asr-flash`
- `SSH_HOST` / `SSH_USER` / `SSH_PASSWORD` / `SSH_PORT`：目标 Linux 连接参数

## 3. Agent 行为边界

- 优先输出可执行的 Ubuntu/Linux 命令
- 避免纯交互式命令直接自动执行
- 复杂任务输出步骤化计划
- 风险等级仅作为初判，最终由执行器规则二次校验
- 高风险或敏感操作需要确认或拦截

## 4. 会话能力

- 支持有限对话历史记忆
- 支持基于上下文的代词和省略补全
- 支持中英文回复语言识别与切换

## 5. 语音接入方式

- 前端使用 `st.audio_input` 采集浏览器录音
- 后端将音频转为 Data URL
- 使用千问兼容模式 `responses.create` 的 `input_audio` 能力执行转写
- 识别成功后自动回填到底部聊天输入框
