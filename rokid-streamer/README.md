# Rokid Streamer

运行在 Rokid 眼镜端的 Android 视频推流应用。负责摄像头采集、编码 MPEG-TS/H.264，并通过 UDP 发送到电脑端 `tools/camera-link`。

## 构建

```powershell
Set-Location apps\rokid-streamer
.\gradlew.bat :app:assembleDebug
```

输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

该 APK 可在构建 `apps/user-web/android` 时嵌入用户端安装包。
