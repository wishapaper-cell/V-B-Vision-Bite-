package com.healthydiet.rokidstreamer.service;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.Process;
import android.os.SystemClock;
import android.util.Log;

import com.healthydiet.rokidstreamer.MainActivity;
import com.healthydiet.rokidstreamer.camera.CameraEncoderStreamer;
import com.healthydiet.rokidstreamer.camera.CameraProfile;
import com.healthydiet.rokidstreamer.camera.CameraProfileSelector;
import com.healthydiet.rokidstreamer.cxr.CxrBridgeHub;
import com.healthydiet.rokidstreamer.model.StreamCommand;
import com.healthydiet.rokidstreamer.model.StreamConfig;
import com.healthydiet.rokidstreamer.model.StreamStatus;
import com.healthydiet.rokidstreamer.protocol.StatusJson;
import com.healthydiet.rokidstreamer.protocol.StreamCommandParser;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

public final class StreamService extends Service implements CxrBridgeHub.Listener {
    public static final String ACTION_ENSURE_CONTROL =
            "com.healthydiet.rokidstreamer.action.ENSURE_CONTROL";

    private static final String TAG = "RokidStreamService";
    private static final String CHANNEL_ID = "rokid_camera_stream";
    private static final int NOTIFICATION_ID = 7101;
    private static final long STATUS_INTERVAL_MS = 1_000L;
    private static final long REMOTE_STATUS_INTERVAL_MS = 5_000L;
    private static final String PREFS = "stream_runtime";

    private final StreamCommandParser commandParser = new StreamCommandParser();
    private final AtomicBoolean destroyed = new AtomicBoolean(false);

    private HandlerThread workerThread;
    private Handler worker;
    private Handler mainHandler;
    private CxrBridgeHub bridgeHub;
    private CameraProfileSelector cameraProfileSelector;
    private SharedPreferences preferences;
    private PowerManager powerManager;
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private PowerManager.OnThermalStatusChangedListener thermalListener;

    private CameraEncoderStreamer stream;
    private CameraProfile activeProfile;
    private StreamConfig config = StreamConfig.defaults();
    private String state = "idle";
    private String error = "";
    private String bridgeState = "initializing";
    private int actualFps;
    private int thermalStatus;
    private boolean stoppingIntentionally;
    private String lastReplyTopic = CxrBridgeHub.STATUS_TOPIC;
    private long lastRemoteStatusAt;

    private final Runnable statusTicker = new Runnable() {
        @Override
        public void run() {
            if (destroyed.get()) {
                return;
            }
            publishStatus(false);
            worker.postDelayed(this, STATUS_INTERVAL_MS);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        mainHandler = new Handler(Looper.getMainLooper());
        workerThread = new HandlerThread(
                "rokid-camera-stream",
                Process.THREAD_PRIORITY_DISPLAY
        );
        workerThread.start();
        worker = new Handler(workerThread.getLooper());
        preferences = getSharedPreferences(PREFS, MODE_PRIVATE);
        config = loadConfig();
        cameraProfileSelector = new CameraProfileSelector(this);
        powerManager = (PowerManager) getSystemService(Context.POWER_SERVICE);
        thermalStatus = powerManager.getCurrentThermalStatus();

        createNotificationChannel();
        startAsForeground();
        createPowerLocks();
        acquireControlWakeLock();
        registerThermalListener();

        try {
            bridgeHub = CxrBridgeHub.get();
            bridgeState = bridgeHub.getBridgeState();
            bridgeHub.attach(this);
        } catch (Throwable bridgeError) {
            bridgeState = "unavailable";
            error = "CXR-S bridge unavailable: " + safeMessage(bridgeError);
            Log.e(TAG, error, bridgeError);
        }

        worker.post(() -> {
            publishStatus(true);
            if (preferences.getBoolean("resume_stream", false)
                    && config.isValid(true)
                    && hasCameraPermission()) {
                startStreaming(config, CxrBridgeHub.STATUS_TOPIC);
            }
            worker.postDelayed(statusTicker, STATUS_INTERVAL_MS);
        });
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        // The foreground service owns the camera session, so closing the Activity is harmless.
        super.onTaskRemoved(rootIntent);
    }

    @Override
    public void onDestroy() {
        destroyed.set(true);
        if (bridgeHub != null) {
            bridgeHub.detach(this);
        }
        if (worker != null) {
            worker.removeCallbacksAndMessages(null);
            if (Looper.myLooper() == worker.getLooper()) {
                releaseStreamAndAllLocks();
            } else {
                worker.post(this::releaseStreamAndAllLocks);
            }
        } else {
            releaseStreamAndAllLocks();
        }
        unregisterThermalListener();
        if (workerThread != null) {
            workerThread.quitSafely();
        }
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override
    public void onCommand(String replyTopic, String json) {
        Handler handler = worker;
        if (handler == null || destroyed.get()) {
            return;
        }
        handler.post(() -> handleCommand(replyTopic, json));
    }

    @Override
    public void onBridgeStateChanged(String newBridgeState) {
        Handler handler = worker;
        if (handler == null || destroyed.get()) {
            bridgeState = newBridgeState;
            return;
        }
        handler.post(() -> {
            bridgeState = newBridgeState;
            publishStatus(false);
        });
    }

    private void handleCommand(String replyTopic, String json) {
        lastReplyTopic = sanitizeReplyTopic(replyTopic);
        try {
            StreamCommand command = commandParser.parse(json, config);
            switch (command.action) {
                case CONFIGURE:
                    if (isStreamActive()) {
                        stopStreaming(false, "configured");
                    }
                    config = command.config;
                    activeProfile = null;
                    state = "configured";
                    error = "";
                    saveConfig(false);
                    publishStatus(true);
                    break;
                case START:
                    if (isStreamActive() && config.equals(command.config)) {
                        // The phone retries until it receives a status acknowledgement. Treat an
                        // identical START as idempotent so a delayed screen-off acknowledgement
                        // cannot repeatedly tear down a healthy camera session.
                        publishStatus(true);
                    } else {
                        config = command.config;
                        startStreaming(config, lastReplyTopic);
                    }
                    break;
                case STOP:
                    stopStreaming(true, "stopped");
                    break;
                case STATUS:
                    publishStatus(true);
                    break;
                default:
                    throw new IllegalArgumentException("unsupported command action");
            }
        } catch (RuntimeException commandError) {
            error = "Command rejected: " + safeMessage(commandError);
            Log.w(TAG, error, commandError);
            publishStatus(true);
        }
    }

    private void startStreaming(StreamConfig requestedConfig, String replyTopic) {
        if (!hasCameraPermission()) {
            state = "permission_required";
            error = "CAMERA permission is not granted";
            preferences.edit().putBoolean("resume_stream", false).apply();
            publishStatus(true);
            return;
        }
        if (thermalStatus >= PowerManager.THERMAL_STATUS_CRITICAL) {
            state = "thermal_shutdown";
            error = "Streaming is blocked while thermal status is critical";
            preferences.edit().putBoolean("resume_stream", false).apply();
            publishStatus(true);
            return;
        }

        stopStreamingInternal();
        config = requestedConfig;
        lastReplyTopic = sanitizeReplyTopic(replyTopic);
        state = "preparing";
        error = "";
        actualFps = 0;
        activeProfile = null;
        stoppingIntentionally = false;
        saveConfig(true);
        acquirePowerLocks();
        publishStatus(true);

        try {
            List<CameraProfile> candidates = cameraProfileSelector.orderedProfiles(config);
            if (candidates.isEmpty()) {
                throw new IllegalStateException("camera reported no usable video profiles");
            }

            Exception lastPrepareError = null;
            for (CameraProfile candidate : candidates) {
                try {
                    CameraEncoderStreamer prepared = prepareStream(candidate);
                    stream = prepared;
                    activeProfile = candidate;
                    state = "starting";
                    publishStatus(true);
                    return;
                } catch (Exception prepareError) {
                    lastPrepareError = prepareError;
                    Log.w(
                            TAG,
                            "Profile rejected: " + candidate.width + "x" + candidate.height
                                    + "@" + candidate.fps,
                            prepareError
                    );
                    releaseStreamOnly();
                }
            }

            throw new IllegalStateException(
                    "no camera/encoder profile could be prepared",
                    lastPrepareError
            );
        } catch (Exception startError) {
            failStream("Unable to start stream: " + safeMessage(startError), startError);
        }
    }

    private CameraEncoderStreamer prepareStream(CameraProfile profile) throws Exception {
        CameraEncoderStreamer candidateStream = new CameraEncoderStreamer(
                this,
                worker,
                new CameraEncoderStreamer.Listener() {
            @Override
            public void onStreamingStarted() {
                if (!stoppingIntentionally && isStreamActive()) {
                    state = "streaming";
                    error = "";
                    publishStatus(true);
                }
            }

            @Override
            public void onFps(int measuredFps) {
                actualFps = measuredFps;
                if (measuredFps > 0 && !stoppingIntentionally) {
                    state = "streaming";
                }
                publishStatus(false);
            }

            @Override
            public void onError(String message, Throwable streamError) {
                failStream(
                        streamError == null ? message : message + ": " + safeMessage(streamError),
                        streamError
                );
            }

            @Override
            public void onCameraDisconnected() {
                if (!stoppingIntentionally && isStreamActive()) {
                    failStream("Camera disconnected", null);
                }
            }
        });
        candidateStream.start(profile, config);
        return candidateStream;
    }

    private void stopStreaming(boolean forgetResume, String nextState) {
        stoppingIntentionally = true;
        stopStreamingInternal();
        if (forgetResume) {
            preferences.edit().putBoolean("resume_stream", false).apply();
        }
        state = nextState;
        actualFps = 0;
        error = "";
        releasePowerLocks();
        publishStatus(true);
        stoppingIntentionally = false;
    }

    private void stopStreamingInternal() {
        stoppingIntentionally = true;
        releaseStreamOnly();
        actualFps = 0;
    }

    private void failStream(String failure, Throwable throwable) {
        if (destroyed.get()) {
            return;
        }
        if (throwable != null) {
            Log.e(TAG, failure, throwable);
        } else {
            Log.e(TAG, failure);
        }
        stoppingIntentionally = true;
        error = failure;
        state = thermalStatus >= PowerManager.THERMAL_STATUS_CRITICAL
                ? "thermal_shutdown"
                : "error";
        preferences.edit().putBoolean("resume_stream", false).apply();
        releaseStreamOnly();
        actualFps = 0;
        releasePowerLocks();
        publishStatus(true);
        stoppingIntentionally = false;
    }

    private void releaseStreamOnly() {
        CameraEncoderStreamer current = stream;
        stream = null;
        if (current != null) {
            try {
                current.stop();
            } catch (RuntimeException releaseError) {
                Log.w(TAG, "Unable to release stream cleanly", releaseError);
            }
        }
    }

    private void releaseStreamAndAllLocks() {
        stoppingIntentionally = true;
        releaseStreamOnly();
        releaseAllPowerLocks();
    }

    private boolean isStreamActive() {
        return stream != null
                || "preparing".equals(state)
                || "connecting".equals(state)
                || "starting".equals(state)
                || "streaming".equals(state);
    }

    private void publishStatus(boolean forceRemote) {
        if (worker != null && Looper.myLooper() != worker.getLooper()) {
            worker.post(() -> publishStatus(forceRemote));
            return;
        }
        StreamStatus status = snapshotStatus();
        StreamStatusBus.publish(status);
        updateNotification(status);

        long now = SystemClock.elapsedRealtime();
        if (bridgeHub != null
                && (forceRemote || now - lastRemoteStatusAt >= REMOTE_STATUS_INTERVAL_MS)) {
            bridgeHub.sendStatus(lastReplyTopic, StatusJson.encode(status));
            lastRemoteStatusAt = now;
        }
    }

    private StreamStatus snapshotStatus() {
        CameraEncoderStreamer current = stream;
        long framesSent = 0;
        long droppedFrames = 0;
        if (current != null) {
            try {
                framesSent = current.getFramesSent();
                droppedFrames = current.getDroppedFrames();
                actualFps = current.getActualFps();
            } catch (RuntimeException metricsError) {
                Log.w(TAG, "Unable to read UDP metrics", metricsError);
            }
        }

        CameraProfile profile = activeProfile;
        int width = profile == null ? config.width : profile.width;
        int height = profile == null ? config.height : profile.height;
        int configuredFps = profile == null ? config.fps : profile.fps;
        int supportedMaxFps = profile == null ? 0 : profile.maxFps;
        String endpoint = config.host.isEmpty() ? "" : config.endpoint();

        return new StreamStatus(
                state,
                configuredFps,
                actualFps,
                width,
                height,
                config.bitrate,
                framesSent,
                droppedFrames,
                thermalStatus,
                thermalStatusName(thermalStatus),
                error,
                config.host,
                config.port,
                endpoint,
                bridgeState,
                supportedMaxFps
        );
    }

    private void createPowerLocks() {
        wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "HealthyDiet:RokidCameraStream"
        );
        wakeLock.setReferenceCounted(false);

        WifiManager wifiManager = (WifiManager) getApplicationContext().getSystemService(
                Context.WIFI_SERVICE
        );
        wifiLock = wifiManager.createWifiLock(
                WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                "HealthyDiet:RokidCameraStream"
        );
        wifiLock.setReferenceCounted(false);
    }

    private void acquirePowerLocks() {
        acquireControlWakeLock();
        try {
            if (wifiLock != null && !wifiLock.isHeld()) {
                wifiLock.acquire();
            }
        } catch (RuntimeException lockError) {
            Log.w(TAG, "Unable to acquire stream power locks", lockError);
        }
    }

    private void releasePowerLocks() {
        try {
            if (wifiLock != null && wifiLock.isHeld()) {
                wifiLock.release();
            }
        } catch (RuntimeException lockError) {
            Log.w(TAG, "Unable to release Wi-Fi lock", lockError);
        }
    }

    private void acquireControlWakeLock() {
        try {
            if (wakeLock != null && !wakeLock.isHeld()) {
                wakeLock.acquire();
            }
        } catch (RuntimeException lockError) {
            Log.w(TAG, "Unable to acquire control wake lock", lockError);
        }
    }

    private void releaseAllPowerLocks() {
        releasePowerLocks();
        try {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
        } catch (RuntimeException lockError) {
            Log.w(TAG, "Unable to release wake lock", lockError);
        }
    }

    private void registerThermalListener() {
        thermalListener = newStatus -> {
            Handler handler = worker;
            if (handler == null || destroyed.get()) {
                thermalStatus = newStatus;
                return;
            }
            handler.post(() -> {
                thermalStatus = newStatus;
                if (newStatus >= PowerManager.THERMAL_STATUS_CRITICAL && isStreamActive()) {
                    failStream("Thermal status is critical; camera stream stopped", null);
                } else {
                    publishStatus(true);
                }
            });
        };
        powerManager.addThermalStatusListener(thermalListener);
    }

    private void unregisterThermalListener() {
        if (powerManager != null && thermalListener != null) {
            try {
                powerManager.removeThermalStatusListener(thermalListener);
            } catch (RuntimeException error) {
                Log.w(TAG, "Unable to unregister thermal listener", error);
            }
        }
    }

    private void createNotificationChannel() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Rokid camera streaming",
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Keeps the Rokid glasses camera stream active while the display is off");
        manager.createNotificationChannel(channel);
    }

    private void startAsForeground() {
        Notification notification = buildNotification(snapshotStatus());
        startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
        );
    }

    private void updateNotification(StreamStatus status) {
        mainHandler.post(() -> {
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.notify(NOTIFICATION_ID, buildNotification(status));
        });
    }

    private Notification buildNotification(StreamStatus status) {
        Intent activityIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                0,
                activityIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        String text;
        if ("streaming".equals(status.state)) {
            text = String.format(
                    Locale.CHINA,
                    "%dx%d, %d/%d FPS, sent %d",
                    status.width,
                    status.height,
                    status.actualFps,
                    status.configuredFps,
                    status.framesSent
            );
        } else if (!status.error.isEmpty()) {
            text = status.error;
        } else {
            text = "Waiting for a stream command";
        }
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_camera)
                .setContentTitle("Rokid camera: " + status.state)
                .setContentText(text)
                .setContentIntent(pendingIntent)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .build();
    }

    private boolean hasCameraPermission() {
        return checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
    }

    private StreamConfig loadConfig() {
        return new StreamConfig(
                preferences.getString("host", ""),
                preferences.getInt("port", StreamConfig.DEFAULT_PORT),
                preferences.getInt("width", StreamConfig.DEFAULT_WIDTH),
                preferences.getInt("height", StreamConfig.DEFAULT_HEIGHT),
                preferences.getInt("fps", StreamConfig.DEFAULT_FPS),
                preferences.getInt("bitrate", StreamConfig.DEFAULT_BITRATE)
        );
    }

    private void saveConfig(boolean resume) {
        preferences.edit()
                .putString("host", config.host)
                .putInt("port", config.port)
                .putInt("width", config.width)
                .putInt("height", config.height)
                .putInt("fps", config.fps)
                .putInt("bitrate", config.bitrate)
                .putBoolean("resume_stream", resume)
                .apply();
    }

    private static String sanitizeReplyTopic(String topic) {
        if (topic == null || topic.isBlank() || topic.length() > 128) {
            return CxrBridgeHub.STATUS_TOPIC;
        }
        return topic.trim();
    }

    private static String thermalStatusName(int status) {
        switch (status) {
            case PowerManager.THERMAL_STATUS_NONE:
                return "none";
            case PowerManager.THERMAL_STATUS_LIGHT:
                return "light";
            case PowerManager.THERMAL_STATUS_MODERATE:
                return "moderate";
            case PowerManager.THERMAL_STATUS_SEVERE:
                return "severe";
            case PowerManager.THERMAL_STATUS_CRITICAL:
                return "critical";
            case PowerManager.THERMAL_STATUS_EMERGENCY:
                return "emergency";
            case PowerManager.THERMAL_STATUS_SHUTDOWN:
                return "shutdown";
            default:
                return "unknown";
        }
    }

    private static String safeMessage(Throwable error) {
        String message = error.getMessage();
        if (message == null || message.isBlank()) {
            return error.getClass().getSimpleName();
        }
        return message;
    }
}
