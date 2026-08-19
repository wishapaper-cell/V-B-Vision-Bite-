# Rokid Glasses RV101 官方资料核验记录

核验日期：2026-07-24  
用途：核验“RV101 摄像头画面传到电脑”的官方能力。核验结论现已用于
`apps/user-web/android` 的 CXR-L Android 实现，并通过 `/api/analyze`
接入现有识别算法。

## 1. 已确认设备

- 产品：Rokid Glasses
- 型号：RV101
- 系统：YodaOS-Sprite
- 用户提供的眼镜固件：`1.22.009-20260710-150201`
- 用户提供的 Rokid AI App：`v1.10.12.0713`

Rokid 开放平台将 Rokid Glasses 描述为搭载高清摄像头、YodaOS-Sprite
的智能眼镜。官方 SDK 页面说明 YodaOS-Sprite 运行于 Rokid Glasses 和
Bolon AI Glasses。

## 2. 官方 SDK 选型结论

### 2.1 CXR-L：本 Demo 的首选

官方页面当前列出的公开版本：

- 版本：`1.0.4`
- 状态：活跃维护
- 更新日期：2026-06-25
- 运行位置：手机
- 平台：Android + iOS
- 需要 Rokid AI App：是
- 获取方式：公开

CXR-L 让开发者自己的移动 App 经 Rokid AI App 获取 Glasses 的 IO
能力，包括图像、音频、显示和指令通道。

适用于本项目的第一阶段：

```text
RV101 -> Rokid AI App/CXR-L -> Android 测试 App
      -> JPEG -> 电脑 /api/frame -> 监看页
```

### 2.2 CXR-M：真正实时音视频的官方移动端路线

官方页面当前列出：

- 版本：`1.1.0`
- 更新日期：2026-04-01
- 运行位置：手机
- 获取方式：商务合作，非公开
- 能力：实时音视频、Wi-Fi P2P、高速传输、自定义页面和双向指令
- 限制：不能与 Rokid AI App 在同一设备并行使用

若最终目标要求连续、低延迟视频而非周期 JPEG，需要评估 CXR-M。

### 2.3 眼镜端裸机开发：不经手机取得 Camera 的路线

官方页面当前列出：

- 版本：`1.0.0`
- 状态：活跃维护
- 更新日期：2026-06-05
- 获取方式：公开
- 系统：YodaOS-Sprite，AOSP Android Go，API 31
- 能力：眼镜端应用可以管理按键、IMU、Camera 等资源

这条路线可用于未来开发眼镜端 APK，让 RV101 直接通过 Wi-Fi 向电脑
推送画面；复杂度和设备部署成本高于 CXR-L。

## 3. CXR-L 1.0.4 官方依赖

Rokid Maven 仓库：

```kotlin
dependencyResolutionManagement {
    repositories {
        maven {
            url = uri("https://maven.rokid.com/repository/maven-public/")
        }
    }
}
```

Android 依赖：

```kotlin
dependencies {
    implementation("com.rokid.cxr:client-l:1.0.4")
}
```

已通过 HTTP 核验以下官方构件可公开访问：

- `client-l-1.0.4.pom`：HTTP 200
- `client-l-1.0.4.aar`：HTTP 200
- AAR 大小：70,543 bytes
- 官方 Gradle metadata SHA-256：
  `3e1f835d574e9d5c2a74a5498a17b445ad09652fc8d4f917dcacb588713f7f19`

## 4. 官方快速接入约束

官方 SDK 页明确给出：

- `minSdk >= 31`，即 Android 12+
- `CXRLink` 应为 Application 级单例，不能在 Activity 中反复创建
- `connect(token)` 返回成功不表示相机能力已可调用
- 链路就绪必须同时满足：
  - `onCXRLConnected(true)`
  - `onGlassBtConnected(true)`
- `CUSTOMVIEW` 会话还需等待 `onCustomViewOpened`
- `CUSTOMAPP` 会话还需等待 `onOpenAppResult(true)`

官方快速接入示意：

```kotlin
val cxrLink = CxrLink(context, CXRSessionType.CUSTOMVIEW)
cxrLink.connect(token)
```

注意：实际工程中的类名、构造方式和回调注册应以 `1.0.4` AAR 和官方
示例工程为准，不能只根据示意代码猜测。

## 5. 相机 API 核验

官方移动端课程和公开 AAR共同确认：

- 眼镜权限：`GlassPermission.CAMERA`
- 拍照入口：`takePhoto(width, height, quality)`
- 图片回调：`IImageStreamCbk.onImageReceived(byte[])`
- 错误回调：`IImageStreamCbk.onImageError(code, message)`
- `quality` 是 JPEG 压缩质量，范围 `0..100`

公开 AAR还确认存在：

- `AuthorizationHelper.requestAuthorization`
- `AuthorizationHelper.parseAuthorizationResult`
- `AuthorizationHelper.hasGlassPermission`
- `ICXRLinkCbk.onCXRLConnected`
- `ICXRLinkCbk.onGlassBtConnected`
- `ICXRLinkCbk.onGlassDeviceInfo`
- `ICXRLinkCbk.onGlassWearingStatus`
- `CXRSessionType.CUSTOMVIEW`
- `CXRSessionType.CUSTOMAPP`

第一版因此应实现低频 JPEG，而不应把 CXR-L 描述成连续视频流。

## 6. Maven 元数据风险

核验时发现 `client-l:1.0.4` 的 POM 和 Gradle metadata 声明了传递依赖：

```text
com.rokid.cxr:cxr-service-bridge:1.0-20260522.063600-105
```

但按标准 Maven release 路径访问该坐标时返回 HTTP 404。仓库当前列出的
`cxr-service-bridge` 版本是：

- release：`1.0`
- snapshot：`1.0-SNAPSHOT`
- 当前 snapshot 构建：`1.0-20260723.084651-108`

因此正式创建 Android 工程后，必须首先跑一次 Gradle 依赖解析。若确实
因旧快照坐标失败，不应直接猜测替换版本；应优先查最新版官方示例或向
Rokid 开发者支持确认。可能的实验性处理只有在二进制兼容性核验后才可用：

```kotlin
implementation("com.rokid.cxr:client-l:1.0.4") {
    exclude(group = "com.rokid.cxr", module = "cxr-service-bridge")
}
implementation("com.rokid.cxr:cxr-service-bridge:1.0")
```

上面的排除/替换不是当前官方文档指令，不能在未验证前作为最终配置。

## 7. Demo 阶段决策

第一阶段目标：

```text
每 700~1500ms 调用一次 takePhoto
-> onImageReceived 得到 JPEG
-> POST 到电脑 http://<LAN-IP>:9088/api/frame
-> 电脑监看页显示
```

暂不实现：

- CXR-M
- 30 FPS 连续视频
- WebRTC
- 眼镜端裸机 APK
- 食物识别算法接入

## 8. 官方来源

- Rokid 开放平台：<https://open.rokid.com/>
- Rokid SDK 选型页：<https://developerdoc.rokid.com/sdk?lang=zh>
- CXR-L 官方移动端课程：<https://t.rokid.com/jwnvn5yc>
- Rokid Maven：
  <https://maven.rokid.com/repository/maven-public/>
- `client-l:1.0.4` POM：
  <https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/1.0.4/client-l-1.0.4.pom>
- `client-l:1.0.4` Gradle metadata：
  <https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/1.0.4/client-l-1.0.4.module>
