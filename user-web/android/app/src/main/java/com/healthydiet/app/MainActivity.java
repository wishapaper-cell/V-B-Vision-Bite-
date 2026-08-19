package com.healthydiet.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Pair;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.rokid.cxr.Caps;
import com.rokid.cxr.link.CXRLink;
import com.rokid.cxr.link.callbacks.ICustomCmdCbk;
import com.rokid.cxr.link.callbacks.ICXRLinkCbk;
import com.rokid.cxr.link.callbacks.ICXRSessionCbk;
import com.rokid.cxr.link.callbacks.IGlassAppCbk;
import com.rokid.cxr.link.utils.CxrDefs;
import com.rokid.cxr.link.utils.GlassInfo;
import com.rokid.sprite.aiapp.externalapp.auth.AuthResult;
import com.rokid.sprite.aiapp.externalapp.auth.AuthorizationHelper;
import com.rokid.sprite.aiapp.externalapp.auth.GlassPermission;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity
        implements ICXRLinkCbk, ICXRSessionCbk {

    private static final int AUTHORIZATION_REQUEST = 4101;
    private static final int BLUETOOTH_PERMISSION_REQUEST = 4102;

    private static final String STREAMER_PACKAGE = "com.healthydiet.rokidstreamer";
    private static final String STREAMER_ENTRY = STREAMER_PACKAGE + ".MainActivity";
    private static final String STREAMER_ASSET = "rokid-glasses-streamer.apk";
    private static final String CONTROL_CHANNEL = "health_diet_stream_control";
    private static final String STATUS_KEY = "health_diet_stream_status";
    private static final int STREAM_PORT = 5000;
    private static final int STREAM_WIDTH = 1280;
    private static final int STREAM_HEIGHT = 720;
    private static final int STREAM_FPS = 30;
    private static final int STREAM_BITRATE = 4_000_000;
    private static final int START_COMMAND_MAX_ATTEMPTS = 12;
    private static final long START_COMMAND_RETRY_MS = 1_500L;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService serverExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService ioExecutor = Executors.newSingleThreadExecutor();

    private WebView webView;
    private CXRLink cxrLink;
    private SharedPreferences preferences;
    private boolean cxrConnected;
    private boolean glassBtConnected;
    private boolean sessionReady;
    private boolean streamerInstalled;
    private boolean streamerInstalling;
    private boolean streamerAppOpen;
    private boolean streamerStreaming;
    private boolean streamerApkEmbedded;
    private boolean streamerLaunchInFlight;
    private boolean streamerRuntimeReady;
    private JSONObject streamerStatus = new JSONObject();
    private JSONObject pendingStartCommand;
    private JSONObject retryingStartCommand;
    private int startCommandAttempt;
    private int statusProbeAttempt;

    private final Runnable startCommandRetry = new Runnable() {
        @Override
        public void run() {
            if (retryingStartCommand == null) {
                return;
            }
            if (!isCommandTransportReady()) {
                mainHandler.postDelayed(this, START_COMMAND_RETRY_MS);
                return;
            }
            startCommandAttempt++;
            sendStreamCommand(
                    retryingStartCommand,
                    "正在发送眼镜视频流启动指令（第 " + startCommandAttempt + " 次）"
            );
            if (retryingStartCommand != null
                    && startCommandAttempt < START_COMMAND_MAX_ATTEMPTS) {
                mainHandler.postDelayed(this, START_COMMAND_RETRY_MS);
            } else if (startCommandAttempt >= START_COMMAND_MAX_ATTEMPTS) {
                retryingStartCommand = null;
                emitError("眼镜端后台服务未响应。请确认已至少亮屏启动过一次推流程序并授予相机权限");
            }
        }
    };

    private final Runnable statusProbeRetry = new Runnable() {
        @Override
        public void run() {
            if (!streamerAppOpen || !isControlReady() || statusProbeAttempt >= 3) {
                return;
            }
            statusProbeAttempt++;
            sendStatusCommand("正在等待眼镜端控制通道就绪");
            if (statusProbeAttempt < 3) {
                mainHandler.postDelayed(this, 1200L);
            }
        }
    };

    private final IGlassAppCbk glassAppCallback = new IGlassAppCbk() {
        @Override
        public void onInstallAppResult(boolean success) {
            streamerInstalling = false;
            streamerInstalled = success;
            preferences.edit().putBoolean("streamer_installed", success).apply();
            if (success) {
                emitState("眼镜端推流程序安装成功");
                queryStreamerInstalled();
            } else {
                emitError("眼镜端推流程序安装失败，请保持眼镜与手机连接后重试");
            }
        }

        @Override
        public void onUnInstallAppResult(boolean success) {
            if (success) {
                streamerInstalled = false;
                streamerRuntimeReady = false;
                preferences.edit().putBoolean("streamer_installed", false).apply();
                streamerAppOpen = false;
                streamerStreaming = false;
            }
            emitState(success ? "眼镜端推流程序已卸载" : "眼镜端推流程序卸载失败");
        }

        @Override
        public void onOpenAppResult(boolean success) {
            streamerLaunchInFlight = false;
            streamerAppOpen = success;
            if (!success) {
                emitError("眼镜端推流程序启动失败；已保留推流请求，将继续尝试后台控制通道");
                sendPendingStartOrStatus();
                return;
            }
            emitState("眼镜端推流程序已启动");
            sendPendingStartOrStatus();
        }

        @Override
        public void onStopAppResult(boolean success) {
            if (success) {
                streamerAppOpen = false;
                streamerStreaming = false;
            }
            emitState(success ? "眼镜端推流程序已停止" : "眼镜端推流程序停止失败");
        }

        @Override
        public void onGlassAppResume(boolean resumed) {
            streamerAppOpen = resumed;
            if (resumed) {
                sendPendingStartOrStatus();
            }
            emitState(resumed ? "眼镜端推流程序正在运行" : "眼镜端推流程序已离开前台，后台服务状态待查询");
        }

        @Override
        public void onQueryAppResult(boolean installed) {
            streamerInstalled = installed;
            preferences.edit().putBoolean("streamer_installed", installed).apply();
            streamerInstalling = false;
            emitState(installed
                    ? "眼镜端推流程序已安装"
                    : "眼镜端尚未安装推流程序，请点击安装");
            if (installed) {
                ensureStreamerRuntime();
            }
        }
    };

    private final ICustomCmdCbk customCmdCallback = new ICustomCmdCbk() {
        @Override
        public void onCustomCmdResult(String key, byte[] payload) {
            if (!STATUS_KEY.equals(key) || payload == null) {
                return;
            }
            try {
                Caps caps = Caps.fromBytes(payload);
                if (caps == null || caps.size() < 2) {
                    throw new JSONException("状态数据结构不完整");
                }
                String protocolKey = caps.at(0).getString();
                if (!"status".equals(protocolKey) && !STATUS_KEY.equals(protocolKey)) {
                    return;
                }
                JSONObject status = new JSONObject(caps.at(1).getString());
                mainHandler.removeCallbacks(statusProbeRetry);
                statusProbeAttempt = 0;
                streamerStatus = status;
                streamerInstalled = true;
                streamerRuntimeReady = true;
                streamerLaunchInFlight = false;
                preferences.edit().putBoolean("streamer_installed", true).apply();
                String streamState = status.optString("state", "");
                streamerStreaming = "streaming".equals(streamState);
                boolean startAccepted = "preparing".equals(streamState)
                        || "connecting".equals(streamState)
                        || "starting".equals(streamState)
                        || streamerStreaming;
                boolean hasError = !status.optString("error", "").isEmpty();
                if (startAccepted || hasError) {
                    mainHandler.removeCallbacks(startCommandRetry);
                    retryingStartCommand = null;
                }
                emitStreamerStatus(status);
                emitState(status.optString(
                        "message",
                        streamerStreaming ? "眼镜视频流正在传输" : "眼镜视频流已停止"
                ));
            } catch (Exception error) {
                emitError("无法解析眼镜端推流状态：" + error.getMessage());
            }
        }
    };

    @Override
    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        preferences = getSharedPreferences("rokid_glasses", MODE_PRIVATE);
        streamerInstalled = preferences.getBoolean("streamer_installed", false);
        cxrLink = ((RokidApplication) getApplication()).getCxrLink();
        streamerApkEmbedded = hasAsset(STREAMER_ASSET);
        configureCxrCallbacks();

        webView = new WebView(this);
        webView.setLayoutParams(new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new GlassesJavascriptBridge(), "RokidGlasses");
        setContentView(webView);

        startEmbeddedHealthServer();
    }

    private void configureCxrCallbacks() {
        cxrLink.setCXRLinkCbk(this);
        cxrLink.setCXRCustomCmdCbk(customCmdCallback);
        CxrDefs.CXRSession session = new CxrDefs.CXRSession(
                CxrDefs.CXRSessionType.CUSTOMAPP,
                STREAMER_PACKAGE
        );
        cxrLink.configCXRSession(session, this);
    }

    private void startEmbeddedHealthServer() {
        serverExecutor.execute(() -> {
            try {
                File resourceDir = new File(getFilesDir(), "web");
                copyAssetTree("web", resourceDir);
                File uploadDir = new File(resourceDir, "static/uploads/avatars");
                if (!uploadDir.exists() && !uploadDir.mkdirs()) {
                    throw new IOException("无法创建头像目录");
                }
                File database = new File(getFilesDir(), "health.db");
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(this));
                }
                Python.getInstance()
                        .getModule("android_server")
                        .callAttr(
                                "start",
                                database.getAbsolutePath(),
                                resourceDir.getAbsolutePath(),
                                uploadDir.getAbsolutePath()
                        );
            } catch (Exception error) {
                emitError("本地健康服务启动失败：" + error.getMessage());
            }
        });
        waitForHealthServer(0);
    }

    private void waitForHealthServer(int attempt) {
        ioExecutor.execute(() -> {
            boolean ready = false;
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(
                        "http://127.0.0.1:5000/login"
                ).openConnection();
                connection.setConnectTimeout(500);
                connection.setReadTimeout(500);
                connection.setInstanceFollowRedirects(false);
                ready = connection.getResponseCode() > 0;
            } catch (IOException ignored) {
                // Flask is still starting.
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
            boolean finalReady = ready;
            mainHandler.post(() -> {
                if (finalReady) {
                    webView.loadUrl("http://127.0.0.1:5000");
                } else if (attempt < 80) {
                    mainHandler.postDelayed(() -> waitForHealthServer(attempt + 1), 250);
                } else {
                    emitError("等待本地健康服务启动超时");
                }
            });
        });
    }

    private void copyAssetTree(String assetPath, File target) throws IOException {
        String[] children = getAssets().list(assetPath);
        if (children == null || children.length == 0) {
            copyAssetFile(assetPath, target);
            return;
        }
        if (!target.exists() && !target.mkdirs()) {
            throw new IOException("无法创建目录：" + target);
        }
        for (String child : children) {
            copyAssetTree(assetPath + "/" + child, new File(target, child));
        }
    }

    private void copyAssetFile(String assetPath, File target) throws IOException {
        File parent = target.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("无法创建目录：" + parent);
        }
        try (InputStream input = getAssets().open(assetPath);
             FileOutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
            }
        }
    }

    private boolean hasAsset(String assetPath) {
        try (InputStream ignored = getAssets().open(assetPath)) {
            return true;
        } catch (IOException ignored) {
            return false;
        }
    }

    private void requestBluetoothThenAuthorize() {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                != PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{
                            Manifest.permission.BLUETOOTH_CONNECT,
                            Manifest.permission.BLUETOOTH_SCAN
                    },
                    BLUETOOTH_PERMISSION_REQUEST
            );
            return;
        }
        requestRokidAuthorization();
    }

    private void requestRokidAuthorization() {
        AuthorizationHelper helper = AuthorizationHelper.INSTANCE;
        if (!helper.isRequiredRokidAppInstalled(this)) {
            emitError("请先安装并登录 Rokid AI App，再在其中完成 RV101 蓝牙配对。");
            return;
        }
        if (helper.hasGlassPermission(GlassPermission.CAMERA)) {
            String token = preferences.getString("cxr_token", "");
            if (!token.isEmpty()) {
                connectCxr(token);
                return;
            }
        }
        Pair<Integer, Intent> immediateResult = helper.requestAuthorization(
                this,
                new GlassPermission[]{GlassPermission.CAMERA},
                AUTHORIZATION_REQUEST
        );
        if (immediateResult != null) {
            handleAuthorizationResult(immediateResult.first, immediateResult.second);
        } else {
            emitState("等待 Rokid AI App 授予眼镜相机权限");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == AUTHORIZATION_REQUEST) {
            handleAuthorizationResult(resultCode, data);
        }
    }

    private void handleAuthorizationResult(int resultCode, Intent data) {
        AuthResult result = AuthorizationHelper.INSTANCE
                .parseAuthorizationResult(resultCode, data);
        if (result instanceof AuthResult.AuthSuccess) {
            String token = ((AuthResult.AuthSuccess) result).getToken();
            preferences.edit().putString("cxr_token", token).apply();
            try {
                connectCxr(token);
            } catch (RuntimeException error) {
                emitError("Rokid 眼镜连接初始化失败：" + error.getMessage());
            }
        } else if (result instanceof AuthResult.AuthCancel) {
            emitError("已取消 Rokid 眼镜授权");
        } else {
            emitError("Rokid 眼镜授权失败，请回到 Rokid AI App 检查配对状态");
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != BLUETOOTH_PERMISSION_REQUEST) {
            return;
        }
        boolean granted = grantResults.length > 0;
        for (int result : grantResults) {
            granted &= result == PackageManager.PERMISSION_GRANTED;
        }
        if (granted) {
            requestRokidAuthorization();
        } else {
            emitError("需要附近设备权限才能通过 Rokid AI App 连接眼镜");
        }
    }

    private void connectCxr(String token) {
        configureCxrCallbacks();
        boolean accepted = cxrLink.connect(token);
        emitState(accepted ? "正在连接 Rokid AI App 与眼镜" : "CXR-L 拒绝了连接请求");
    }

    private boolean isControlReady() {
        return isCommandTransportReady() && sessionReady;
    }

    private boolean isCommandTransportReady() {
        return cxrConnected && glassBtConnected;
    }

    private void ensureStreamer() {
        if (!isControlReady()) {
            emitState("请先完成 Rokid AI App 授权与眼镜连接");
            requestBluetoothThenAuthorize();
            return;
        }
        queryStreamerInstalled();
    }

    private void queryStreamerInstalled() {
        if (!isControlReady()) {
            emitError("眼镜控制会话尚未就绪，无法查询推流程序");
            return;
        }
        try {
            emitState("正在检查眼镜端推流程序");
            cxrLink.appIsInstalled(glassAppCallback);
        } catch (RuntimeException error) {
            emitError("查询眼镜端推流程序失败：" + error.getMessage());
        }
    }

    /**
     * Starts the glasses-side foreground control service while a screen-bound CXR session is
     * available. After this one-time bootstrap, commands are delivered directly to that service
     * and no longer depend on the glasses display or Activity lifecycle.
     */
    private void ensureStreamerRuntime() {
        if (!streamerInstalled
                || streamerRuntimeReady
                || streamerAppOpen
                || streamerLaunchInFlight
                || !isControlReady()) {
            return;
        }
        try {
            streamerLaunchInFlight = true;
            emitState("正在准备眼镜端常驻后台控制服务");
            cxrLink.appStart(STREAMER_ENTRY, glassAppCallback);
        } catch (RuntimeException error) {
            streamerLaunchInFlight = false;
            emitError("启动眼镜端后台控制服务失败：" + error.getMessage());
        }
    }

    private void flushBackgroundControl() {
        if (!isCommandTransportReady()) {
            return;
        }
        if (pendingStartCommand != null) {
            sendPendingStartOrStatus();
        } else if (retryingStartCommand != null) {
            mainHandler.removeCallbacks(startCommandRetry);
            mainHandler.post(startCommandRetry);
        }
    }

    private void installStreamer() {
        if (!isControlReady()) {
            emitError("请先连接眼镜，再安装眼镜端推流程序");
            return;
        }
        if (!streamerApkEmbedded) {
            emitError(
                    "当前手机 APK 未内置眼镜端推流程序。请先构建 apps/rokid-streamer，"
                            + "或在 Gradle 中传入 -ProkidStreamerApk=<APK路径> 后重新构建手机 APK。"
            );
            return;
        }
        if (streamerInstalling) {
            emitState("眼镜端推流程序正在安装，请稍候");
            return;
        }
        streamerInstalling = true;
        emitState("正在准备并上传眼镜端推流程序");
        ioExecutor.execute(() -> {
            try {
                File apk = new File(getFilesDir(), STREAMER_ASSET);
                copyAssetFile(STREAMER_ASSET, apk);
                if (!apk.isFile() || apk.length() == 0) {
                    throw new IOException("内置 APK 文件为空");
                }
                mainHandler.post(() -> {
                    try {
                        cxrLink.appUploadAndInstall(apk.getAbsolutePath(), glassAppCallback);
                        emitState("正在向眼镜上传并安装推流程序");
                    } catch (RuntimeException error) {
                        streamerInstalling = false;
                        emitError("上传眼镜端推流程序失败：" + error.getMessage());
                    }
                });
            } catch (IOException error) {
                streamerInstalling = false;
                emitError("读取眼镜端推流程序失败：" + error.getMessage());
            }
        });
    }

    private String normalizeServerUrl(String value) throws IOException {
        if (value == null || value.trim().isEmpty()) {
            throw new IOException("请输入电脑识别服务地址");
        }
        URL url = new URL(value.trim());
        if (!("http".equalsIgnoreCase(url.getProtocol())
                || "https".equalsIgnoreCase(url.getProtocol()))
                || url.getHost() == null
                || url.getHost().isEmpty()) {
            throw new IOException("地址必须是 http:// 或 https:// 开头的完整地址");
        }
        String normalized = url.getProtocol().toLowerCase() + "://" + url.getAuthority();
        return normalized.replaceAll("/+$", "");
    }

    private JSONObject buildStartCommand(String serverUrl) throws IOException, JSONException {
        String normalized = normalizeServerUrl(serverUrl);
        URL url = new URL(normalized);
        preferences.edit().putString("analysis_server", normalized).apply();
        JSONObject command = new JSONObject();
        command.put("command", "start");
        command.put("host", url.getHost());
        command.put("port", STREAM_PORT);
        command.put("width", STREAM_WIDTH);
        command.put("height", STREAM_HEIGHT);
        command.put("fps", STREAM_FPS);
        command.put("bitrate", STREAM_BITRATE);
        command.put("protocol", "udp-mpegts");
        command.put("protocol_version", 1);
        return command;
    }

    private void startStream(String serverUrl) {
        try {
            pendingStartCommand = buildStartCommand(serverUrl);
            if (!streamerInstalled) {
                emitError("眼镜端尚未安装推流程序，请先亮屏完成一次检查和安装");
                return;
            }
            sendPendingStartOrStatus();
            if (!isCommandTransportReady()) {
                emitState("推流请求已保存，正在恢复 Rokid 连接");
                requestBluetoothThenAuthorize();
            } else if (!streamerRuntimeReady && sessionReady) {
                ensureStreamerRuntime();
            }
        } catch (Exception error) {
            pendingStartCommand = null;
            emitError("无法启动视频流：" + error.getMessage());
        }
    }

    private void sendPendingStartOrStatus() {
        JSONObject command = pendingStartCommand;
        pendingStartCommand = null;
        if (command != null) {
            retryingStartCommand = command;
            startCommandAttempt = 0;
            mainHandler.removeCallbacks(startCommandRetry);
            mainHandler.post(startCommandRetry);
        } else if (isCommandTransportReady() && retryingStartCommand == null) {
            statusProbeAttempt = 0;
            mainHandler.removeCallbacks(statusProbeRetry);
            mainHandler.postDelayed(statusProbeRetry, 1000L);
        }
    }

    private void stopStream() {
        pendingStartCommand = null;
        retryingStartCommand = null;
        mainHandler.removeCallbacks(startCommandRetry);
        mainHandler.removeCallbacks(statusProbeRetry);
        JSONObject command = new JSONObject();
        try {
            command.put("command", "stop");
            command.put("protocol_version", 1);
        } catch (JSONException ignored) {
            // Primitive JSON fields cannot fail in normal use.
        }
        sendStreamCommand(command, "正在停止眼镜视频流");
    }

    private void requestStreamStatus() {
        sendStatusCommand("正在查询眼镜视频流状态");
    }

    private void sendStatusCommand(String message) {
        JSONObject command = new JSONObject();
        try {
            command.put("command", "status");
            command.put("protocol_version", 1);
        } catch (JSONException ignored) {
            // Primitive JSON fields cannot fail in normal use.
        }
        sendStreamCommand(command, message);
    }

    private void sendStreamCommand(JSONObject command, String message) {
        if (!isCommandTransportReady()) {
            emitState("眼镜传输链路暂不可用，推流指令将在重连后发送");
            return;
        }
        try {
            Caps caps = new Caps();
            caps.write(STATUS_KEY);
            caps.write(command.toString());
            cxrLink.sendCustomCmd(CONTROL_CHANNEL, caps);
            emitState(message);
        } catch (RuntimeException error) {
            emitError("发送眼镜推流指令失败：" + error.getMessage());
        }
    }

    private JSONObject stateJson(String message) {
        JSONObject state = new JSONObject();
        try {
            state.put("cxr_connected", cxrConnected);
            state.put("glass_bt_connected", glassBtConnected);
            state.put("session_ready", sessionReady);
            state.put("control_ready", isControlReady());
            state.put("background_control_ready", isCommandTransportReady());
            state.put("streamer_apk_embedded", streamerApkEmbedded);
            state.put("streamer_installed", streamerInstalled);
            state.put("streamer_installing", streamerInstalling);
            state.put("streamer_app_open", streamerAppOpen);
            state.put("streaming", streamerStreaming);
            state.put("target_fps", STREAM_FPS);
            state.put("server_url", preferences.getString(
                    "analysis_server",
                    "http://192.168.1.100:9088"
            ));
            state.put("streamer_status", streamerStatus);
            state.put("message", message);
        } catch (JSONException ignored) {
            // The fields above are primitives or valid JSON objects.
        }
        return state;
    }

    private void emitState(String message) {
        String quoted = JSONObject.quote(stateJson(message).toString());
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onState(" + quoted + ")"
        );
    }

    private void emitStreamerStatus(JSONObject status) {
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onStreamerStatus("
                        + JSONObject.quote(status.toString()) + ")"
        );
    }

    private void emitError(String message) {
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onError("
                        + JSONObject.quote(message) + ")"
        );
    }

    private void evaluateJavascript(String script) {
        mainHandler.post(() -> {
            if (webView != null) {
                webView.evaluateJavascript(script, null);
            }
        });
    }

    @Override
    public void onCXRLConnected(boolean connected) {
        cxrConnected = connected;
        if (!connected) {
            sessionReady = false;
            streamerAppOpen = false;
        }
        emitState(connected ? "CXR-L 服务已连接" : "CXR-L 服务已断开");
        if (connected) {
            flushBackgroundControl();
        }
    }

    @Override
    public void onGlassBtConnected(boolean connected) {
        glassBtConnected = connected;
        if (!connected) {
            sessionReady = false;
            streamerAppOpen = false;
        }
        emitState(connected ? "RV101 蓝牙已连接" : "RV101 蓝牙未连接");
        if (connected) {
            flushBackgroundControl();
        }
    }

    @Override
    public void onGlassDeviceInfo(GlassInfo info) {
        if (info != null) {
            emitState("眼镜：" + info.deviceName + " · 电量 " + info.batteryLevel + "%");
        }
    }

    @Override
    public void onGlassWearingStatus(boolean wearing) {
        emitState(wearing ? "眼镜佩戴中" : "眼镜未佩戴");
    }

    @Override
    public void onGlassAiAssistStart() {
        emitState("眼镜 AI 助手正在占用控制会话");
    }

    @Override
    public void onGlassAiAssistStop() {
        emitState("眼镜 AI 助手已释放控制会话");
    }

    @Override
    public void onGlassAiInterrupt(boolean interrupted) {
        emitState(interrupted ? "眼镜控制会话被打断" : "眼镜控制会话已恢复");
    }

    @Override
    public void onSessionAvailable(CxrDefs.CXRSessionReason reason) {
        sessionReady = true;
        emitState("眼镜自定义应用会话可用");
        queryStreamerInstalled();
    }

    @Override
    public void onSessionStart(CxrDefs.CXRSessionReason reason) {
        sessionReady = true;
        emitState("眼镜自定义应用会话已就绪");
        queryStreamerInstalled();
    }

    @Override
    public void onSessionPause(CxrDefs.CXRSessionReason reason) {
        sessionReady = false;
        emitState(reason == CxrDefs.CXRSessionReason.SESSION_SCREEN_OFF
                ? "眼镜已熄屏；后台控制服务保持在线，可继续启动、停止和查询推流"
                : "眼镜自定义应用会话暂停：" + reason);
        flushBackgroundControl();
    }

    @Override
    public void onSessionUnavailable(CxrDefs.CXRSessionReason reason) {
        sessionReady = false;
        streamerAppOpen = false;
        emitState("眼镜自定义应用会话不可用：" + reason);
    }

    @Override
    protected void onDestroy() {
        pendingStartCommand = null;
        retryingStartCommand = null;
        mainHandler.removeCallbacks(startCommandRetry);
        mainHandler.removeCallbacks(statusProbeRetry);
        cxrLink.disconnect();
        serverExecutor.shutdownNow();
        ioExecutor.shutdownNow();
        if (webView != null) {
            webView.removeJavascriptInterface("RokidGlasses");
            webView.destroy();
        }
        super.onDestroy();
    }

    public final class GlassesJavascriptBridge {
        @JavascriptInterface
        public void requestAuthorizationAndConnect() {
            runOnUiThread(MainActivity.this::requestBluetoothThenAuthorize);
        }

        @JavascriptInterface
        public void ensure() {
            runOnUiThread(MainActivity.this::ensureStreamer);
        }

        @JavascriptInterface
        public void install() {
            runOnUiThread(MainActivity.this::installStreamer);
        }

        @JavascriptInterface
        public void start(String serverUrl) {
            runOnUiThread(() -> startStream(serverUrl));
        }

        @JavascriptInterface
        public void stop() {
            runOnUiThread(MainActivity.this::stopStream);
        }

        @JavascriptInterface
        public void status() {
            runOnUiThread(MainActivity.this::requestStreamStatus);
        }

        @JavascriptInterface
        public String getState() {
            return stateJson("当前眼镜视频流状态").toString();
        }

        @JavascriptInterface
        public String getServerUrl() {
            return preferences.getString(
                    "analysis_server",
                    "http://192.168.1.100:9088"
            );
        }

        @JavascriptInterface
        public boolean setServerUrl(String serverUrl) {
            try {
                String normalized = normalizeServerUrl(serverUrl);
                preferences.edit().putString("analysis_server", normalized).apply();
                emitState("电脑视频接收服务地址已保存");
                return true;
            } catch (IOException error) {
                return false;
            }
        }
    }
}
