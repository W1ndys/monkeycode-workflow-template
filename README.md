# MonkeyCode GitHub Workflow 集成模板

通过 GitHub Actions 将 MonkeyCode AI 开发平台与你的仓库对接，实现 Issue 驱动的自动化开发闭环：

1. 给 Issue 打上 `monkeycode` 标签 -> 自动登录平台、创建开发分支和 PR、创建 MonkeyCode 开发任务
2. MonkeyCode 完成开发后在 Issue 评论 `[MONKEYCODE_TASK_COMPLETE]` -> 自动创建 Review 任务
3. PR 合并后 -> 自动终止开发和 Review 任务、关闭 Issue、删除开发分支

## 工作流程

```
Issue (打 monkeycode 标签)
  |
  v
monkeycode-task.yml 触发
  |-- 权限校验：检查 Issue 提交者是否为仓库协作者（write 及以上）
  |-- 防重复：检查 Issue 评论中是否已有任务链接
  |-- 校验配置：检查 secrets/vars 是否齐全
  |-- 自动登录：通过邮箱密码自动登录 MonkeyCode 平台
  |-- 创建分支和 PR：自动创建 monkeycode/issue-N 分支和关联 PR
  |-- 创建任务：调用 MonkeyCode API 创建开发任务
  |-- 评论反馈：在 Issue 中贴出任务链接（或失败原因）
  v
MonkeyCode 自动开发 -> 提交代码 -> 推送到 PR
  |
  v
开发完成，在 Issue 评论 [MONKEYCODE_TASK_COMPLETE] + PR 链接
  |
  v
monkeycode-review.yml 触发
  |-- 防重复：检查是否已有 review 任务
  |-- 提取 PR 链接
  |-- 自动登录 + 创建 Review 任务
  |-- 评论 Review 任务链接
  v
Review 完成，修复问题后合并 PR
  |
  v
monkeycode-stop.yml 触发
  |-- 从 PR body 提取关联 Issue 编号
  |-- 分别提取开发任务 ID 和 Review 任务 ID
  |-- 自动登录 + 终止两个任务（释放资源）
  |-- 在 PR 下评论终止结果
  |-- 评论并关闭 Issue
  |-- 删除开发分支
```

## 快速开始

### 1. 复制文件到你的仓库

将以下文件复制到你的仓库对应目录：

```
你的仓库/
  .github/
    workflows/
      monkeycode-task.yml      # Issue 触发创建开发任务
      monkeycode-review.yml    # 开发完成后自动创建 Review 任务
      monkeycode-stop.yml      # PR 合并后终止任务并清理
    scripts/
      monkeycode_login.py      # 平台自动登录脚本
    prompts/
      task-instruction.md      # 开发任务默认指令模板
    ISSUE_TEMPLATE/
      monkeycode-task.yml      # MonkeyCode 开发任务 Issue 模板
      config.yml               # Issue 模板全局配置
```

### 2. 配置仓库 Secrets

进入仓库 Settings -> Secrets and variables -> Actions -> Secrets，添加：

| Secret | 说明 | 获取方式 |
|--------|------|---------|
| `MONKEYCODE_EMAIL` | MonkeyCode 平台登录邮箱 | 注册 MonkeyCode 时使用的邮箱 |
| `MONKEYCODE_PASSWORD` | MonkeyCode 平台登录密码 | 注册 MonkeyCode 时设置的密码 |

### 3. 配置仓库 Variables

进入仓库 Settings -> Secrets and variables -> Actions -> Variables，添加：

| Variable | 说明 | 获取方式 |
|----------|------|---------|
| `MONKEYCODE_MODEL_ID` | AI 模型 ID | MonkeyCode 控制台创建任务时抓包获取 |
| `MONKEYCODE_IMAGE_ID` | 开发环境镜像 ID | 同上 |
| `MONKEYCODE_PROJECT_ID` | 项目 ID | 同上 |
| `MONKEYCODE_TASK_PROMPT` | (可选) 自定义任务 prompt | 见下方说明 |

### 4. 开启 Actions 权限

进入仓库 Settings -> Actions -> General，确保：
- 勾选 "Allow GitHub Actions to create and approve pull requests"
- Workflow permissions 选择 "Read and write permissions"

### 5. 创建 monkeycode 标签

在仓库的 Issues -> Labels 中创建名为 `monkeycode` 的标签（如果使用了 Issue 模板，标签会自动创建）。

### 6. 使用

创建一个 Issue 描述开发需求，打上 `monkeycode` 标签（或使用 MonkeyCode 开发任务模板），workflow 会自动触发。

## 配置详解

### 认证方式

本模板使用邮箱密码自动登录，替代了手动抓取 Cookie 的方式。登录脚本会自动完成 captcha challenge 求解和密码认证，无需手动维护 Cookie。

### 获取 Model ID / Image ID / Project ID

1. 登录 MonkeyCode 控制台
2. 手动创建一个开发任务（不需要真正执行）
3. 打开 DevTools -> Network，观察创建任务的 POST 请求
4. 从请求体中提取 `model_id`、`image_id`，从响应或 URL 中提取 `project_id`

### 自定义任务 Prompt

默认使用 `.github/prompts/task-instruction.md` 文件中的模板。如需自定义，有两种方式：

1. 直接修改 `.github/prompts/task-instruction.md` 文件
2. 在仓库 Variables 中设置 `MONKEYCODE_TASK_PROMPT`（优先级更高）

默认模板中的 commit 作者信息（邮箱和用户名）需要根据实际情况修改。

### 资源配置

默认任务资源配置在 workflow 文件中：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `core` | 2 | CPU 核心数 |
| `memory` | 8589934592 | 内存 (8GB) |
| `life` | 7200 | 任务最大存活时间 (秒，默认 2 小时) |

如需调整，直接修改 workflow 文件中的 `resource` 字段。

### 默认分支

默认从 `main` 分支拉取代码并创建 PR。如果你的默认分支是 `master`，需要修改：
- `monkeycode-task.yml` 中 `--base main` 改为 `--base master`
- workflow 中 `repo: { branch: "main" }` 改为 `repo: { branch: "master" }`

## 工作流行为说明

### monkeycode-task.yml

触发条件：Issue 被创建或被打上 `monkeycode` 标签。

权限校验：只有仓库协作者（write 及以上权限）才能触发任务，防止外部用户滥用。

自动创建 PR：workflow 会自动创建 `monkeycode/issue-N` 分支和关联 PR，PR body 中包含 `Closes #N` 以便合并时自动关闭 Issue。

防重复机制：如果 Issue 评论中已存在 MonkeyCode 任务链接，不会重复创建。

失败反馈：workflow 会根据不同失败原因在 Issue 中评论：
- 权限不足 -> 移除标签并提示
- 配置缺失 -> 提示补齐哪些配置
- 登录失败 -> 提示检查邮箱密码
- API 调用失败 -> 输出 HTTP 状态码和错误信息

并发控制：同一 Issue 的多次触发会排队执行（`cancel-in-progress: false`），不会互相取消。

### monkeycode-review.yml

触发条件：Issue 评论中包含 `[MONKEYCODE_TASK_COMPLETE]` 标记。

防重复机制：如果已有 `[MONKEYCODE_REVIEW_TASK]` 标记的评论，不会重复创建。

PR 链接提取：优先从触发评论中提取，其次从 Issue 所有评论中查找。

### monkeycode-stop.yml

触发条件：PR 被合并（非关闭）。

关联机制：从 PR body 中匹配 `Closes #N` / `Fixes #N` / `Resolves #N` 提取 Issue 编号。

任务终止：分别终止开发任务和 Review 任务，并在 PR 下评论终止结果。

清理操作：关闭关联 Issue 并删除开发分支。

## 目录结构

```
.github/
  workflows/
    monkeycode-task.yml       # Issue 触发创建 MonkeyCode 开发任务
    monkeycode-review.yml     # 开发完成后自动创建 Review 任务
    monkeycode-stop.yml       # PR 合并后终止任务并清理
  scripts/
    monkeycode_login.py       # MonkeyCode 平台自动登录脚本
  prompts/
    task-instruction.md       # 开发任务默认指令模板
  ISSUE_TEMPLATE/
    monkeycode-task.yml       # MonkeyCode 开发任务 Issue 模板
    config.yml                # Issue 模板全局配置
```

## 与旧版的区别

本模板相比旧版（基于手动 Cookie）有以下改进：

| 特性 | 旧版 | 新版 |
|------|------|------|
| 认证方式 | 手动抓取 Cookie | 邮箱密码自动登录 |
| Cookie 过期 | 需要手动更新 | 自动登录，无需维护 |
| 权限校验 | 无 | 校验 Issue 提交者权限 |
| PR 创建 | 需要 MonkeyCode 手动创建 | workflow 自动创建分支和 PR |
| Review 工作流 | 无 | 开发完成后自动创建 Review 任务 |
| 任务终止 | 仅终止开发任务 | 同时终止开发和 Review 任务 |
| 分支清理 | 无 | PR 合并后自动删除开发分支 |
| 错误反馈 | 基础 | 分阶段详细错误提示 |

## 常见问题

### 登录失败怎么办？

检查 `MONKEYCODE_EMAIL` 和 `MONKEYCODE_PASSWORD` 是否正确配置。workflow 会在 Issue 中评论具体的错误信息。

### 同一个 Issue 能重复触发吗？

不能。workflow 会检查 Issue 评论中是否已有任务链接，已有则跳过。如需重新触发，需要先手动删除之前的任务评论。

### PR 没有关联 Issue 会怎样？

`monkeycode-stop.yml` 会跳过终止流程，不会报错。但 MonkeyCode 任务会继续运行直到超时，建议始终在 PR body 中关联 Issue。

### PR 自动创建失败怎么办？

确保在仓库 Settings -> Actions -> General 中勾选了 "Allow GitHub Actions to create and approve pull requests"。如果仍然失败，workflow 会提示在已创建的分支上手动创建 PR。

### 需要什么 GitHub 权限？

workflow 使用 `github.token` 自动授权，需要 `contents: write`、`issues: write` 和 `pull-requests: write` 权限，这些已在 workflow 中声明。

## License

MIT
