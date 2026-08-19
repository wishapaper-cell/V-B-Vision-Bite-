# User Web

V&B 用户端健康饮食应用，包含 Flask Web 服务、SQLite 数据访问、视觉识别适配、服务端渲染页面以及 Android 容器工程。

## 启动

从仓库根目录完成 Python 环境初始化后运行：

```powershell
.\scripts\dev\start-user-web.ps1
```

访问 `http://127.0.0.1:5000`。

## 当前能力

- 手机号或邮箱验证码注册、密码登录、用户启停检查和最近活跃时间。
- 个人目标、身体指标、健康资料、头像和双向共享关系。
- 手工饮食记录、眼镜/图片识别记录和视频摄入事件导入。
- 饮食图片受权限保护地存储与访问。
- 今日/历史记录、餐次、描述、热量及蛋白质/脂肪/碳水/纤维展示。
- 对识别图片重新分析，保存候选建议，并修正食物、克重、时间、餐次、描述和图片。
- 修正时保留原食物名称、原克重和修正时间，便于追溯。
- V&B 品牌页面资源和 Android 启动图标。

## 关键环境变量

| 环境变量 | 默认值或作用 |
|---|---|
| `HEALTH_SECRET_KEY` | Flask 会话签名密钥 |
| `HEALTH_DB_PATH` | `.workspace/data/user-web/health.db` |
| `HEALTH_RUNTIME_DIR` | 本机 PID、密钥等运行文件目录 |
| `HEALTH_UPLOAD_DIR` | 用户头像目录；饮食图片存放在同级 `diet/` |
| `RECOGNITION_ALGORITHM_DIR` | 默认指向 `services/recognition` |

数据库、上传图片和运行密钥不会加入 Git。

## 识别依赖

仅运行基础 Web 功能时安装用户端依赖；启用本地视觉识别时额外安装：

```powershell
python -m pip install -r apps\user-web\requirements-recognition.txt
```

50×50 mm 参考物检测、食物分析和克重估算的规范实现位于 `services/recognition`。

## 测试

浏览器冒烟脚本会使用一次性数据库，建议通过仓库测试说明中提供的服务包装器运行：

```powershell
python apps\user-web\tests\browser_smoke.py
```

## Android

Android 工程位于 `android/`。构建时会同步当前用户端的 Python、模板与静态资源，并可嵌入 `apps/rokid-streamer` 的 Debug APK。构建产物、SDK/JDK 和本地 Gradle 缓存均不纳入仓库。
