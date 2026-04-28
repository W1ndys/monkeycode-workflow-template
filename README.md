# MonkeyCode GitHub Workflow 集成模板

通过 GitHub Actions 将 MonkeyCode AI 开发平台与你的仓库对接，实现 Issue 驱动的自动化开发闭环：

1. 给 Issue 打上 `monkeycode` 标签 -> 自动创建 MonkeyCode 开发任务
2. MonkeyCode 完成开发后提交 PR
3. PR 合并后 -> 自动终止 MonkeyCode 任务并关闭关联 Issue

## 工作流程

```
Issue (打 monkeycode 标签)
  |
  v
monkeycode-task.yml 触发
  |-- 防重复：检查 Issue 评论中是否已有任务链接
  |-- 校验配置：检查 secrets/vars 是否齐全
  |-- 验证 Cookie：调用订阅接口确认登录态有效
  |-- 创建任务：调用 MonkeyCode API 创建开发任务
  |-- 评论反馈：在 Issue 中贴出任务链接（或失败原因）
  v
MonkeyCode 自动开发 -> 提交代码 -> 发起 PR (body 中包含 Closes #N)
  |
  v
PR 合并
  |
  v
monkeycode-stop.yml 触发
  |-- 从 PR body 提取关联 Issue 编号
  |-- 从 Issue 评论提取 MonkeyCode 任务 ID
  |-- 调用 API 终止任务（释放资源）
  |-- 评论并关闭 Issue
```

## 快速开始

### 1. 复制 workflow 文件

将 `.github/workflows/` 下的两个文件复制到你的仓库：

```
你的仓库/
  .github/
    workflows/
      monkeycode-task.yml
      monkeycode-stop.yml
```

### 2. 配置仓库 Secrets

进入仓库 Settings -> Secrets and variables -> Actions -> Secrets，添加：

| Secret | 说明 | 获取方式 |
|--------|------|---------|
| `MONKEYCODE_COOKIE` | MonkeyCode 平台的登录 Cookie | 浏览器登录 monkeycode-ai.com 后从 DevTools 抓取 |

### 3. 配置仓库 Variables

进入仓库 Settings -> Secrets and variables -> Actions -> Variables，添加：

| Variable | 说明 | 获取方式 |
|----------|------|---------|
| `MONKEYCODE_MODEL_ID` | AI 模型 ID | MonkeyCode 控制台创建任务时抓包获取 |
| `MONKEYCODE_IMAGE_ID` | 开发环境镜像 ID | 同上 |
| `MONKEYCODE_PROJECT_ID` | 项目 ID | 同上 |
| `MONKEYCODE_TASK_PROMPT` | (可选) 自定义任务 prompt | 见下方说明 |

### 4. 创建 monkeycode 标签

在仓库的 Issues -> Labels 中创建名为 `monkeycode` 的标签。

### 5. 使用

创建一个 Issue 描述开发需求，打上 `monkeycode` 标签，workflow 会自动触发。

## 配置详解

### 获取 Cookie

1. 浏览器登录 https://monkeycode-ai.com
2. 打开 DevTools (F12) -> Network 标签
3. 刷新页面，找到任意 API 请求
4. 复制请求头中的 `Cookie` 值
5. 粘贴到仓库 Secret `MONKEYCODE_COOKIE`

Cookie 会过期，过期后 workflow 会在 Issue 中评论提醒，届时重新抓取并更新即可。

### 获取 Model ID / Image ID / Project ID

1. 登录 MonkeyCode 控制台
2. 手动创建一个开发任务（不需要真正执行）
3. 打开 DevTools -> Network，观察创建任务的 POST 请求
4. 从请求体中提取 `model_id`、`image_id`，从响应或 URL 中提取 `project_id`

### 自定义任务 Prompt

默认 prompt 模板：

```
新开一个分支完成这个任务，完成之后提交推送并发起pr，请直接在修改代码之前发起PR，
然后再每次提交直接提交推送到PR，开发任务完成之后自己进行一次review，issues链接为{ISSUE_URL}
```

如需自定义，在仓库 Variables 中设置 `MONKEYCODE_TASK_PROMPT`，workflow 会自动在末尾拼接 `，issues链接为{ISSUE_URL}`。

自定义示例：

```
新开一个分支完成这个任务，完成之后提交推送并发起pr，commit作者邮箱是your@email.com，
用户名是YourName，请直接在修改代码之前发起PR，然后再每次提交直接提交推送到PR，
开发任务完成之后自己进行一次review
```

### 资源配置

默认任务资源配置在 `monkeycode-task.yml` 中：

```json
{
  "core": 2,
  "memory": 8589934592,
  "life": 7200
}
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `core` | 2 | CPU 核心数 |
| `memory` | 8589934592 | 内存 (8GB) |
| `life` | 7200 | 任务最大存活时间 (秒，默认 2 小时) |

如需调整，直接修改 workflow 文件中的 `resource` 字段。

### 默认分支

默认从 `main` 分支拉取代码。如果你的默认分支是 `master`，修改 workflow 中的：

```yaml
repo: {
  branch: "main"
}
```

## 工作流行为说明

### monkeycode-task.yml

触发条件：Issue 被创建或被打上 `monkeycode` 标签。

防重复机制：如果 Issue 评论中已存在 MonkeyCode 任务链接，不会重复创建。

失败反馈：workflow 会根据不同失败原因在 Issue 中评论：
- 配置缺失 -> 提示补齐哪些配置
- Cookie 过期 -> 提示重新抓取
- API 调用失败 -> 输出 HTTP 状态码和错误信息

并发控制：同一 Issue 的多次触发会排队执行（`cancel-in-progress: false`），不会互相取消。

### monkeycode-stop.yml

触发条件：PR 被合并（非关闭）。

关联机制：从 PR body 中匹配 `Closes #N` / `Fixes #N` / `Resolves #N` 提取 Issue 编号，再从该 Issue 的评论中提取任务 ID。

PR body 中必须包含关联 Issue 的关键词，否则不会触发终止流程。

## 目录结构

```
.github/
  workflows/
    monkeycode-task.yml   # Issue 触发创建 MonkeyCode 开发任务
    monkeycode-stop.yml   # PR 合并后终止任务并关闭 Issue
```

## 常见问题

### Cookie 多久过期？

取决于 MonkeyCode 平台的会话策略，通常几天到几周不等。过期后 workflow 会自动在 Issue 中提醒。

### 同一个 Issue 能重复触发吗？

不能。workflow 会检查 Issue 评论中是否已有任务链接，已有则跳过。如需重新触发，需要先手动删除之前的任务评论。

### PR 没有关联 Issue 会怎样？

`monkeycode-stop.yml` 会跳过终止流程，不会报错。但 MonkeyCode 任务会继续运行直到超时，建议始终在 PR body 中关联 Issue。

### 需要什么 GitHub 权限？

workflow 使用 `github.token` 自动授权，需要 `contents: read` 和 `issues: write` 权限，这些已在 workflow 中声明。

## License

MIT
