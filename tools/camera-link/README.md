# Rokid Camera Link Demo

这是一个与正式业务解耦的 Rokid 摄像头链路和识别联调工具。

它只验证：

```text
采集设备取得摄像头画面
        ↓
通过局域网上传 JPEG
        ↓
Windows 电脑实时显示
```

它不会加载食物识别模型，也不会修改现有算法项目。

## 目录

```text
tools/camera-link/
├── server.py                 # 零第三方依赖的电脑接收服务
├── start_demo.ps1            # Windows 启动脚本
├── static/
│   ├── viewer.html           # 电脑监看页
│   ├── viewer.js
│   ├── capture.html          # 浏览器采集页
│   ├── capture.js
│   └── styles.css
├── tools/
│   └── send_test_frame.py    # 不需要摄像头的接口自测
├── docs/
│   └── rokid_rv101_official_research.md
└── tests/
    └── test_server.py
```

RV101、CXR-L 1.0.4、CXR-M 和眼镜端裸机开发的官方资料核验结果见
[`docs/rokid_rv101_official_research.md`](docs/rokid_rv101_official_research.md)。

## 1. 启动电脑端

在 PowerShell 中运行：

```powershell
cd F:\adventureX\tools\camera-link
.\start_demo.ps1
```

也可以直接运行：

```powershell
python .\server.py --host 0.0.0.0 --port 9088
```

电脑打开：

```text
http://127.0.0.1:9088/
```

页面右侧会显示实际采集地址，例如：

```text
http://192.168.1.105:9088/capture.html
```

## 2. 先验证电脑接收服务

保持服务运行，打开另一个 PowerShell：

```powershell
cd F:\adventureX\tools\camera-link
python .\tools\send_test_frame.py
```

电脑监看页应从“等待眼镜画面”变为“光学链路在线”，设备名显示为：

```text
python-self-test
```

这一步不需要 Rokid，也不需要摄像头。

## 3. 使用浏览器采集页

在具有摄像头的设备上打开监看页显示的采集地址。

依次点击：

1. `打开摄像头`
2. 允许摄像头权限
3. `开始传输`

如果浏览器允许局域网 HTTP 页面调用摄像头，电脑上会看到连续 JPEG 画面。

### 重要：浏览器安全限制

Chrome 等浏览器通常只允许以下安全上下文使用摄像头：

- `https://...`
- 当前设备自己的 `http://localhost`

因此手机或眼镜通过 `http://电脑IP:9088/capture.html` 打开时，浏览器可能拒绝摄像头。
这不代表电脑接收端有问题。

该浏览器页面的用途是：

- 本机快速测试；
- 检查设备厂商浏览器是否特别允许摄像头；
- 演示完整的 JPEG 上传协议；
- 给 Rokid 原生 SDK 采集端提供行为参考。

Rokid 真机正式测试优先使用原生 SDK 或眼镜端 Android APK。

## 4. Rokid 原生采集端需要调用的接口

原始 JPEG 上传：

```http
POST /api/frame
Content-Type: image/jpeg
X-Device-Name: Rokid-Model
X-Frame-Width: 1280
X-Frame-Height: 720

<JPEG bytes>
```

成功响应：

```json
{
  "ok": true,
  "frame": {
    "sequence": 1,
    "received_at_ms": 1784830000000,
    "device_name": "Rokid-Model",
    "client_ip": "192.168.1.106",
    "content_type": "image/jpeg",
    "size_bytes": 98231,
    "width": 1280,
    "height": 720
  }
}
```

也支持现有算法项目风格的 Base64 JSON：

```json
{
  "image": "data:image/jpeg;base64,...",
  "width": 1280,
  "height": 720,
  "device_name": "Rokid-Model"
}
```

推荐原生端使用原始 JPEG，因为 Base64 会增加约三分之一的传输体积。

健康饮食 Android App 使用眼镜 JPEG 调用识别接口：

```http
POST /api/analyze
Content-Type: image/jpeg
X-Device-Name: Rokid-RV101
```

该接口会调用 `services/recognition`，并返回食物、估算克重、营养、
画面质量和拍摄建议。请使用已经安装识别依赖的 Python 启动：

```powershell
F:\adventureX\apps\user-web\.venv\Scripts\python.exe server.py --host 0.0.0.0 --port 9088
```

## 5. 网络要求

- 电脑和采集设备连接同一个 Wi-Fi。
- 服务监听 `0.0.0.0:9088`。
- Windows 防火墙允许 Python 在专用网络通信。
- 路由器不能开启 AP 隔离或客户端隔离。

从采集设备访问：

```text
http://电脑IPv4地址:9088/api/health
```

应看到：

```json
{"ok":true,"service":"rokid-camera-link-demo"}
```

## 6. 当前边界

现已确认设备为 Rokid Glasses RV101，并在
`apps/user-web/android` 中使用官方 CXR-L 1.0.4 AAR 完成 Android
采集端。真实 SDK 方法签名已经通过 Java 编译，Debug APK 也已生成。

当前仍需真机完成的验证是：

- Rokid AI App 授权页面与实际 token 返回；
- `onCXRLConnected(true)` 和 `onGlassBtConnected(true)`；
- RV101 固件 `1.22.009-20260710-150201` 的 `takePhoto` JPEG 回调；
- 手机所在局域网到电脑 `9088` 端口的可达性。

CXR-L 第一版是低频 JPEG。连续低延迟视频需要 CXR-M 商务 SDK，或改为
眼镜端裸机 APK。
