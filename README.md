# AdventureX NutritionGlass

NutritionGlass 是一个基于 Rokid RV101 的饮食识别与营养监管项目。单仓库包含用户端、监管端、眼镜推流应用、视频接收工具、食物识别服务和模型训练代码。

## 仓库结构

```text
adventureX/
├─ apps/                         可部署应用
│  ├─ user-web/                  用户端 Flask + Android 容器
│  ├─ supervisor-web/            监管管理端 Flask
│  └─ rokid-streamer/            RV101 眼镜端视频推流 Android 应用
├─ services/
│  └─ recognition/               食物识别、估重、会话和进食事件服务
├─ ml/
│  └─ training/                  食物/餐具模型训练与数据转换脚本
├─ tools/
│  └─ camera-link/               电脑端视频接收、预览和识别联调工具
├─ docs/                         产品、架构、开发和运维文档
├─ scripts/                      统一启动、安装和质量检查脚本
├─ artifacts/                    APK、调试日志和设备截图，不属于源码
├─ legacy/                       迁移前的旧仓库快照，仅供追溯
└─ .workspace/                   本机数据、运行文件、缓存和研究临时文件
```

目录边界和所有权见 [仓库结构说明](docs/architecture/repository-structure.md)。

## 快速开始

### 1. 初始化 Python 环境

```powershell
Set-Location F:\adventureX
.\scripts\dev\setup-python.ps1
```

### 2. 启动用户端

```powershell
.\scripts\dev\start-user-web.ps1
```

浏览器访问 `http://127.0.0.1:5000`。

### 3. 启动 Rokid 视频接收与识别后端

```powershell
.\scripts\dev\start-rokid-backend.ps1
```

浏览器访问 `http://127.0.0.1:9088`。

### 4. 启动监管管理端

```powershell
.\scripts\dev\start-supervisor-web.ps1
```

浏览器访问 `http://127.0.0.1:5100`。

## 数据和配置

本机运行数据统一放在 `.workspace/`，不与源码混放：

```text
.workspace/data/user-web/health.db
.workspace/data/supervisor-web/admin.db
.workspace/run/
```

可配置环境变量见 [.env.example](.env.example)。默认配置适合本地开发，生产环境必须设置独立密钥、正式数据库、HTTPS 和反向代理。

## 测试与质量检查

```powershell
.\scripts\quality\check.ps1
```

该脚本执行：

- Python 语法编译检查。
- 用户端关键模块导入检查。
- 相机链路单元测试。
- 识别服务测试（依赖可用时）。
- 仓库结构和敏感文件检查。

## Android 构建

用户端 APK：

```powershell
Set-Location apps\user-web\android
.\gradlew.bat :app:assembleDebug
```

眼镜推流 APK：

```powershell
Set-Location apps\rokid-streamer
.\gradlew.bat :app:assembleDebug
```

构建产物应复制到 `artifacts/releases/android/`，不要提交 `build/` 和 `.gradle/`。

## 文档入口

- [文档总览](docs/README.md)
- [系统架构](docs/architecture/system-overview.md)
- [仓库结构](docs/architecture/repository-structure.md)
- [本地开发环境](docs/development/local-setup.md)
- [测试规范](docs/development/testing.md)
- [运行手册](docs/operations/local-runbook.md)
- [实时饮食记录需求](docs/product/real-time-intake-requirements.md)
- [协作规范](CONTRIBUTING.md)
- [安全说明](SECURITY.md)

## 兼容入口

根目录的 `start_rokid_backend.ps1` 保留为兼容入口，内部转发到 `scripts/dev/start-rokid-backend.ps1`。新文档和新脚本只使用规范目录。

## 历史代码

`legacy/recognition-algorithm-repository/` 是迁移前的嵌套 Git 仓库快照，用于追溯旧路径和实验实现，不是后续开发基线。除修复历史复现问题外，不应在该目录继续开发新功能。
