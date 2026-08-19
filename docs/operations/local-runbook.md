# 本地运行手册

## 服务和端口

| 服务 | 端口 | 健康检查/入口 |
|---|---:|---|
| 用户端 | 5000 | `http://127.0.0.1:5000` |
| Rokid 后端 | 9088 | `http://127.0.0.1:9088/api/health` |
| 监管端 | 5100 | `http://127.0.0.1:5100` |
| 眼镜 UDP | 5000/UDP | `udp://<computer-ip>:5000` |

## 标准启动顺序

1. 启动用户端。
2. 启动 Rokid 后端。
3. 启动监管端。
4. 手机和眼镜连接同一 Wi-Fi。
5. 在 App 中填写电脑的局域网地址，例如 `http://192.168.1.10:9088`。

## 常见问题

### 监管端提示找不到用户数据库

确认以下文件存在：

```text
.workspace/data/user-web/health.db
```

并确认 `USER_APP_DB_PATH` 指向该文件。

### 识别服务提示找不到算法目录

确认：

```text
services/recognition/backend
```

并设置：

```text
RECOGNITION_ALGORITHM_DIR=F:\adventureX\services\recognition
```

### 9088 端口被占用

运行：

```powershell
.\scripts\dev\stop-local-services.ps1
```

或检查占用端口的进程后再启动。

### Android 找不到眼镜推流 APK

先构建：

```powershell
Set-Location apps\rokid-streamer
.\gradlew.bat :app:assembleDebug
```

再构建用户端 Android 工程。

## 数据备份

停止用户端和监管端后，备份：

```text
.workspace/data/user-web/health.db
.workspace/data/supervisor-web/admin.db
```

SQLite 运行时可能存在 `-wal` 和 `-shm` 文件。必须在服务停止或使用 SQLite 在线备份机制时备份，避免不一致。
