# 测试和质量检查

## 一键检查

```powershell
.\scripts\quality\check.ps1
```

## 分模块测试

相机链路：

```powershell
Set-Location tools\camera-link
..\..\apps\user-web\.venv\Scripts\python.exe -m pytest tests -q
```

识别服务：

```powershell
Set-Location services\recognition
..\..\apps\user-web\.venv\Scripts\python.exe -m pytest tests -q
```

用户端浏览器冒烟测试：

```powershell
Set-Location apps\user-web
.\.venv\Scripts\python.exe tests\browser_smoke.py
```

## 测试分层

- 单元测试：纯函数、状态转换、数据校验和幂等逻辑。
- 集成测试：SQLite、Flask 路由、识别适配器和推送 Outbox。
- 设备测试：Rokid 授权、推流、息屏和断线恢复。
- 端到端测试：用餐开始、识别、确认、落库和监管端展示。

## PR 最低要求

- 修改模块的现有测试通过。
- 新增业务规则应包含测试。
- 数据库迁移必须验证旧数据库升级。
- Android 变更至少完成 Debug 构建。
- 设备相关变更记录设备型号、App 版本、网络环境和日志位置。
