# 本地开发环境

## 前置条件

- Windows 10/11。
- Python 3.11。
- JDK 17。
- Android SDK 35（构建 Android 时）。
- Rokid AI App 和 RV101（设备联调时）。

## Python 环境

统一安装：

```powershell
Set-Location F:\adventureX
.\scripts\dev\setup-python.ps1
```

默认虚拟环境：

```text
apps/user-web/.venv
```

虚拟环境属于本机内容，已通过 `.gitignore` 排除。

## 配置

复制 `.env.example` 的值到本机环境或启动配置。不要提交真实密钥。

开发脚本会自动设置：

```text
HEALTH_DB_PATH
HEALTH_RUNTIME_DIR
HEALTH_UPLOAD_DIR
RECOGNITION_ALGORITHM_DIR
USER_APP_DB_PATH
ADMIN_DB_PATH
```

## 启动

分别在独立终端运行：

```powershell
.\scripts\dev\start-user-web.ps1
.\scripts\dev\start-rokid-backend.ps1
.\scripts\dev\start-supervisor-web.ps1
```

停止本地服务：

```powershell
.\scripts\dev\stop-local-services.ps1
```

## 本机数据

```text
.workspace/data/user-web/health.db
.workspace/data/user-web/uploads/
.workspace/data/supervisor-web/admin.db
.workspace/run/
```

删除或替换数据库前必须备份。不要将 `.workspace/` 当作源码目录。

## Android

Android SDK 路径由 `apps/user-web/android/local.properties` 或环境变量提供。`local.properties` 不应提交。
