# 2026-07-25 桌面归档整合记录

## 目的

将桌面上的 `管理端.zip` 与 `v2.zip` 归并到 AdventureX 分层单仓库，保留有效源码、品牌资源和当前文档，同时避免重新引入旧顶层工程、运行数据、密钥及本地构建工具。

## 规范映射

| 归档来源 | 规范目录 | 处理方式 |
|---|---|---|
| `管理端.zip/admin_panel` | `apps/supervisor-web` | 采用较新的管理端业务代码、模板和样式 |
| `v2.zip/apps/user-web` | `apps/user-web` | 采用规范用户端、Android 工程和页面代码 |
| `v2.zip/services/recognition` | `services/recognition` | 合入识别、会话 API 和 UDP 视频流代码 |
| `v2.zip/health_diet_app/static/brand` | `apps/user-web/static/brand` | 只提取品牌静态资源，不恢复重复旧应用 |
| `v2.zip/health_diet_app/android/.../res` | `apps/user-web/android/.../res` | 只提取 Android 启动图标与品牌资源 |
| `v2.zip/assets` | `assets` | 保存跨应用 V&B 品牌源文件 |
| `v2.zip` 的资源生成脚本 | `tools` | 保存可复现品牌和参考卡资源的工具 |

`v2.zip` 中较旧的管理端没有覆盖 `管理端.zip` 的新版实现。项目 50×50 mm 参考物的标定源码、模型和测试与当前仓库版本一致，因此保留规范路径中的实现。

## 明确排除

以下内容属于运行环境、交付物、历史副本或敏感数据，不进入源码仓库：

- 嵌套 `.git`、数据库、备份、管理员会话密钥、PID 和运行状态文件。
- `.build-tools` 中的 JDK、Android SDK、Gradle、Python 运行时与依赖缓存。
- `build/`、Gradle 缓存、Python 缓存、虚拟环境和测试缓存。
- APK、AAB、发布压缩包、二进制中间产物和临时日志。
- 重复顶层 `health_diet_app`、旧模板目录和失效的根目录启动器。

## 文档与二进制资料

归档内的产品需求 DOCX 与赛事协议 PDF 经 SHA-256 对比，分别与仓库现有的以下文件完全一致，因此没有重复覆盖：

- `docs/product/NutritionGlass_现状实现与实时饮食记录需求说明.docx`
- `docs/legal/AdventureX 2026 黑客松赛事出行补贴协议（中英双语）.pdf`

归档中的 `启动 V&B.bat` 依赖不存在的根目录 `launcher.ps1`，未原样合入。规范启动入口继续位于 `scripts/dev/`。

## 运行边界

`tools/camera-link` 仍是 Rokid 本地设备联调与预览的规范入口，HTTP 端口为 `9088`，UDP 端口为 `5000`。`services/recognition/server.py` 是额外的 FastAPI 会话兼容/测试入口，HTTP 端口为 `8000`，也会监听 UDP `5000`；两套 UDP 接收器不能同时运行。
