# 协作与贡献规范

## 基本原则

- 新功能只在 `apps/`、`services/`、`ml/` 或 `tools/` 的规范目录开发。
- `legacy/` 只用于历史追溯，不作为新功能基线。
- 运行数据、数据库、日志、缓存和密钥必须放在 `.workspace/`，不得进入源码目录。
- APK、截图和调试日志放在 `artifacts/`，不得与源代码混放。
- 任何跨模块接口变化必须同步更新 `docs/architecture/` 和相关产品文档。

## 分支和提交

建议分支命名：

```text
feature/<short-name>
fix/<short-name>
docs/<short-name>
refactor/<short-name>
chore/<short-name>
```

建议使用 Conventional Commits：

```text
feat(user-web): add meal session creation
fix(camera-link): handle stale UDP stream
docs(architecture): document intake event flow
refactor(recognition): isolate weight estimation
```

## 开发流程

1. 阅读 `README.md` 和相关模块 README。
2. 从 `.env.example` 创建本机配置，不提交真实密钥。
3. 修改代码并同步测试。
4. 运行 `scripts/quality/check.ps1`。
5. 更新相关文档和变更记录。
6. 提交 PR 时说明影响模块、验证方式、数据迁移和回滚方法。

## 代码要求

- Python 目标版本为 3.11。
- 新代码应使用清晰的模块边界和类型标注。
- API 输入必须校验，用户身份必须来自服务端会话或令牌。
- 数据库变更必须采用可重复执行的迁移，不得手工修改生产数据结构。
- 不捕获无边界的异常后静默忽略；降级行为必须可观察。
- 实时事件必须包含幂等 ID 和版本号。
- 不在代码中硬编码本机绝对路径、账号、密钥或 IP。

## 文档要求

新增或修改以下内容时必须同步文档：

- 目录结构和模块归属。
- 启动命令和环境变量。
- 数据库表和迁移。
- HTTP/WebSocket 接口。
- Android/Rokid 构建流程。
- 生产部署、安全或隐私策略。

## 评审清单

- [ ] 功能范围明确。
- [ ] 没有修改 `legacy/` 作为主实现。
- [ ] 没有提交数据库、密钥、缓存和构建目录。
- [ ] 新增行为有测试或明确的人工验证步骤。
- [ ] 接口和数据结构兼容性已说明。
- [ ] 失败、重试、幂等和权限边界已考虑。
- [ ] 文档已更新。
