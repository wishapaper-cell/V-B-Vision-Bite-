# 健康饮食 Android · Rokid RV101

这个工程重建了原 APK 的 Android 原生壳，并用 Rokid CXR-L 1.0.4
替换网页/手机摄像头入口。

## 数据流

```text
健康饮食 Android App
  -> Rokid AI App / CXR-L
  -> RV101 蓝牙链路
  -> takePhoto(1280, 720, 82)
  -> IImageStreamCbk JPEG
  -> http://电脑IP:9088/api/analyze
  -> services/recognition
  -> WebView 显示结果并回填饮食记录
```

CXR-L 是低频拍照 API，不是连续视频 API。自动采集默认每 1200ms 请求
一张，限制范围为 700~5000ms。

## 运行前提

1. 手机为 Android 12（API 31）或更高版本。
2. 安装并登录 Rokid AI App。
3. 在 Rokid AI App 中先完成 RV101 蓝牙配对。
4. 手机和电脑处于同一 Wi-Fi。
5. 电脑启动识别服务：

```powershell
cd F:\adventureX
.\scripts\dev\start-rokid-backend.ps1
```

6. App 饮食页填写 `http://电脑IPv4:9088`，再点击“授权并连接眼镜”。

## 构建

```powershell
cd F:\adventureX\apps\user-web\android
.\gradlew.bat :app:assembleDebug
```

生成文件：

```text
app\build\outputs\apk\debug\app-debug.apk
```

原 APK 没有提供签名密钥。测试工程使用并存包名
`com.healthydiet.app.rokid`，不会要求卸载旧版或清除旧版数据。取得正式
签名密钥并确认数据迁移方案后，可将 `applicationId` 切回
`com.healthydiet.app` 生成覆盖升级包。

## SDK

工程使用经过 SHA-256 核验的官方二进制：

- `client-l-1.0.4.aar`
  `3e1f835d574e9d5c2a74a5498a17b445ad09652fc8d4f917dcacb588713f7f19`
- `cxr-service-bridge-1.0.aar`
  `fbf6da50ac99542f9474487a193c17612ead399cfebae172bed7df1d254a0384`

之所以将两个 AAR 固定在 `app/libs`，是因为 CXR-L 1.0.4 的官方 Gradle
元数据引用了一个仓库中已不存在的旧快照版本。固定公开 release 构件可以
避免每次构建解析到不稳定坐标。
