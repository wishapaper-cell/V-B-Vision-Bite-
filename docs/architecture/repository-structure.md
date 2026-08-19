# 仓库结构和模块边界

## 设计原则

- 按可部署单元和业务职责分层，而不是按开发者或临时任务分目录。
- 源码、运行数据、交付物、文档和实验材料分离。
- 唯一规范路径；历史副本进入 `legacy/`。
- 根目录只保留仓库级配置、入口和治理文档。

## 目录职责

| 目录 | 允许内容 | 禁止内容 |
|---|---|---|
| `apps/` | 面向用户或设备的可部署应用 | 临时日志、数据库、研究解压目录 |
| `services/` | 后端和算法服务 | UI 发布物、APK 历史版本 |
| `ml/` | 训练、数据转换、模型评估 | 生产用户数据 |
| `tools/` | 联调、诊断和开发工具 | 正式业务持久化 |
| `assets/` | 跨应用品牌源文件和设计母版 | 运行时上传、页面业务逻辑 |
| `docs/` | 当前有效文档 | 运行缓存 |
| `scripts/` | 仓库级自动化脚本 | 模块业务逻辑 |
| `artifacts/` | APK、截图、日志、发布包 | 唯一源码 |
| `legacy/` | 迁移前快照和历史仓库 | 新功能开发 |
| `.workspace/` | 本机数据库、缓存、研究临时文件 | 需要共享的源码和文档 |

## 规范路径

```text
apps/user-web
apps/supervisor-web
apps/rokid-streamer
services/recognition
ml/training
tools/camera-link
assets
```

禁止重新创建以下旧顶层目录：

```text
health_diet_app
recognition_algorithm
rokid_camera_link_demo
```

## 依赖方向

允许：

```text
apps/user-web -> services/recognition
tools/camera-link -> apps/user-web/recognition_adapter
apps/user-web/android -> apps/rokid-streamer 构建产物
apps/supervisor-web -> 用户业务数据库（仅本地原型）
```

不建议：

- 识别服务反向导入 Flask 用户端。
- 训练代码导入用户业务代码。
- `legacy/` 被任何正式入口引用。
- 模块使用硬编码个人目录。

## 模块 README

每个可部署应用或服务至少应说明：

- 职责和边界。
- 依赖和环境变量。
- 启动、测试、构建方式。
- 数据和端口。
- 已知限制。
- 负责人或维护范围。
