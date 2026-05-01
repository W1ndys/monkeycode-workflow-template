# 用户指令记忆

本文件记录了用户的指令、偏好和教导，用于在未来的交互中提供参考。

## 格式

### 用户指令条目
用户指令条目应遵循以下格式：

[用户指令摘要]
- Date: [YYYY-MM-DD]
- Context: [提及的场景或时间]
- Instructions:
  - [用户教导或指示的内容，逐行描述]

### 项目知识条目
Agent 在任务执行过程中发现的条目应遵循以下格式：

[项目知识摘要]
- Date: [YYYY-MM-DD]
- Context: Agent 在执行 [具体任务描述] 时发现
- Category: [代码结构|代码模式|代码生成|构建方法|测试方法|依赖关系|环境配置]
- Instructions:
  - [具体的知识点，逐行描述]

## 去重策略
- 添加新条目前，检查是否存在相似或相同的指令
- 若发现重复，跳过新条目或与已有条目合并
- 合并时，更新上下文或日期信息
- 这有助于避免冗余条目，保持记忆文件整洁

## 条目

### 项目结构与 API 模式
- Date: 2026-05-01
- Context: Agent 在执行 Issue #4（增加辅助脚本）任务时发现
- Category: 代码结构
- Instructions:
  - 项目是一个 GitHub Actions 工作流模板，用于将 MonkeyCode AI 开发平台与 GitHub 仓库对接
  - 脚本位于 `.github/scripts/` 目录，使用纯 Python 标准库（无第三方依赖，除 websocket-client）
  - 登录脚本 `monkeycode_login.py` 实现了 captcha challenge -> PoW 求解 -> redeem -> 密码登录的完整流程
  - MonkeyCode API 基础 URL 为 `https://monkeycode-ai.com`，使用 Session Cookie 认证
  - API 分页使用游标模式（cursor + limit），响应格式为 `{"code": 0, "data": {...}, "page": {"cursor": "...", "has_more": bool}}`
  - 关键 API 端点：`GET /api/v1/users/models`（模型列表）、`GET /api/v1/users/projects`（项目列表）、`GET /api/v1/users/images`（镜像列表）
