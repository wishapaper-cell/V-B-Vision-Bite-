# Recognition Service

食物识别、参考物标定、克重估算和实时摄入事件核心。该目录既可作为 Python 算法模块被用户端调用，也提供一个独立 FastAPI 会话服务用于兼容联调和算法演示。

## 能力

- 食物实例分割、OpenCV 回退识别和烹饪方式推断。
- 项目专用 50×50 mm 参考物检测，模型位于 `models/reference_marker_v1.json`。
- 兼容旧版 50 mm ArUco 标定卡。
- 参考物透视校正、毫米/像素比例、容器、体积、密度和克重估算。
- 营养换算、多帧 Track 聚合、餐具识别和进食事件。
- 浏览器 JPEG 帧上传和 Rokid UDP MPEG-TS 视频接收。

项目参考物会优先于 ArUco 检测。只有参考物尺寸、清晰度、图案特征和几何质量达到阈值时，结果才进入标定克重；否则界面会明确标记为视觉粗估。

## 目录

```text
backend/models/       Pydantic 数据模型
backend/services/     标定、识别、跟踪、营养和 UDP 会话服务
models/               本地权重及 50×50 mm 参考物模型
scripts/              标定卡生成、模型下载和调试脚本
tests/                单元测试与参考物合成场景测试
static/               FastAPI Demo 页面
server.py             HTTP 会话 API，默认 8000 端口
server_https.py       需要本地证书的可选 HTTPS 包装器
```

## 安装与测试

从仓库根目录运行：

```powershell
python -m pip install -r services\recognition\requirements.txt
$env:PYTHONPATH = 'services\recognition'
python -m pytest services\recognition\tests -q
```

`av`（PyAV）用于解码 Rokid 发送的 H.264/MPEG-TS UDP 流；未安装时，图片识别仍可用，但 UDP 接收线程会退出并提示安装依赖。

## FastAPI 会话服务

```powershell
$env:PYTHONPATH = 'services\recognition'
python services\recognition\server.py
```

服务默认监听 `http://127.0.0.1:8000`，UDP 接收器监听 `0.0.0.0:5000`。如需本地 HTTPS，在 `services/recognition` 放置不入库的 `cert.pem` 与 `key.pem`，然后运行 `server_https.py`。

`services/recognition/server.py` 是算法会话兼容/测试入口；仓库日常的 Rokid 本地设备联调仍使用 `tools/camera-link` 和 `scripts/dev/start-rokid-backend.ps1`，其 HTTP 端口为 `9088`。两个入口不要同时抢占 UDP `5000`。

## 边界

本模块产生 `FoodTrack`、标定质量和 `IntakeEvent`，不决定用户权限，也不直接写入正式业务记录。只有用户端在用户确认后负责持久化摄入数据。
