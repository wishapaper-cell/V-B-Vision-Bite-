package com.healthydiet.rokidstreamer.camera;

import android.annotation.SuppressLint;
import android.content.Context;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureFailure;
import android.hardware.camera2.CaptureRequest;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Range;
import android.view.Surface;

import com.healthydiet.rokidstreamer.model.StreamConfig;
import com.healthydiet.rokidstreamer.stream.MpegTsMuxer;
import com.healthydiet.rokidstreamer.stream.UdpTsSender;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.concurrent.atomic.AtomicBoolean;

/** Owns one Camera2 -> MediaCodec -> H.264/MPEG-TS/UDP streaming session. */
public final class CameraEncoderStreamer {
    public interface Listener {
        void onStreamingStarted();

        void onFps(int fps);

        void onError(String message, Throwable error);

        void onCameraDisconnected();
    }

    private static final String MIME_TYPE = MediaFormat.MIMETYPE_VIDEO_AVC;
    private static final byte[] START_CODE = new byte[] {0, 0, 0, 1};

    private final Context context;
    private final Handler callbackHandler;
    private final Listener listener;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean errorDelivered = new AtomicBoolean(false);

    private CameraProfile profile;
    private StreamConfig config;
    private CameraDevice cameraDevice;
    private CameraCaptureSession captureSession;
    private MediaCodec encoder;
    private Surface encoderSurface;
    private UdpTsSender sender;
    private Thread drainThread;
    private byte[] codecConfig = new byte[0];
    private volatile long framesSent;
    private volatile long droppedFrames;
    private volatile int actualFps;
    private long fpsWindowStartedAt;
    private int fpsWindowFrames;

    public CameraEncoderStreamer(Context context, Handler callbackHandler, Listener listener) {
        this.context = context.getApplicationContext();
        this.callbackHandler = callbackHandler;
        this.listener = listener;
    }

    @SuppressLint("MissingPermission")
    public void start(CameraProfile profile, StreamConfig config) throws Exception {
        if (!running.compareAndSet(false, true)) {
            throw new IllegalStateException("stream is already running");
        }
        this.profile = profile;
        this.config = config;
        errorDelivered.set(false);
        framesSent = 0;
        droppedFrames = 0;
        actualFps = 0;
        codecConfig = new byte[0];
        fpsWindowStartedAt = SystemClock.elapsedRealtime();
        fpsWindowFrames = 0;

        try {
            sender = new UdpTsSender(config.host, config.port);
            prepareEncoder();
            startDrainThread();
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            manager.openCamera(profile.cameraId, cameraStateCallback, callbackHandler);
        } catch (Exception error) {
            stop();
            throw error;
        }
    }

    public void stop() {
        running.set(false);
        CameraCaptureSession session = captureSession;
        captureSession = null;
        if (session != null) {
            try {
                session.stopRepeating();
            } catch (Exception ignored) {
                // The camera may already be closing after a disconnect.
            }
            session.close();
        }
        CameraDevice device = cameraDevice;
        cameraDevice = null;
        if (device != null) {
            device.close();
        }

        Thread thread = drainThread;
        drainThread = null;
        if (thread != null && thread != Thread.currentThread()) {
            thread.interrupt();
            try {
                thread.join(1_500L);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }

        MediaCodec codec = encoder;
        encoder = null;
        if (codec != null) {
            try {
                codec.stop();
            } catch (RuntimeException ignored) {
                // A codec error may already have transitioned it to a terminal state.
            }
            codec.release();
        }
        Surface surface = encoderSurface;
        encoderSurface = null;
        if (surface != null) {
            surface.release();
        }
        UdpTsSender transport = sender;
        sender = null;
        if (transport != null) {
            transport.close();
        }
        actualFps = 0;
    }

    public long getFramesSent() {
        return framesSent;
    }

    public long getDroppedFrames() {
        return droppedFrames;
    }

    public int getActualFps() {
        return actualFps;
    }

    private void prepareEncoder() throws IOException {
        MediaFormat format = MediaFormat.createVideoFormat(MIME_TYPE, profile.width, profile.height);
        format.setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface
        );
        format.setInteger(MediaFormat.KEY_BIT_RATE, config.bitrate);
        format.setInteger(MediaFormat.KEY_FRAME_RATE, profile.fps);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2);
        format.setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR);
        format.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0);
        format.setInteger(MediaFormat.KEY_PRIORITY, 0);

        encoder = MediaCodec.createEncoderByType(MIME_TYPE);
        encoder.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        encoderSurface = encoder.createInputSurface();
        encoder.start();
    }

    private void startDrainThread() {
        drainThread = new Thread(this::drainEncoder, "rokid-h264-drain");
        drainThread.start();
    }

    private final CameraDevice.StateCallback cameraStateCallback = new CameraDevice.StateCallback() {
        @Override
        public void onOpened(CameraDevice camera) {
            if (!running.get()) {
                camera.close();
                return;
            }
            cameraDevice = camera;
            createCaptureSession(camera);
        }

        @Override
        public void onDisconnected(CameraDevice camera) {
            camera.close();
            cameraDevice = null;
            if (running.get()) {
                callbackHandler.post(listener::onCameraDisconnected);
            }
        }

        @Override
        public void onError(CameraDevice camera, int error) {
            camera.close();
            cameraDevice = null;
            deliverError("Camera2 open error: " + error, null);
        }
    };

    private void createCaptureSession(CameraDevice camera) {
        try {
            camera.createCaptureSession(
                    Collections.singletonList(encoderSurface),
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession session) {
                            if (!running.get()) {
                                session.close();
                                return;
                            }
                            captureSession = session;
                            startRepeatingCapture(camera, session);
                        }

                        @Override
                        public void onConfigureFailed(CameraCaptureSession session) {
                            session.close();
                            deliverError("Camera2 capture session configuration failed", null);
                        }
                    },
                    callbackHandler
            );
        } catch (CameraAccessException | RuntimeException error) {
            deliverError("Unable to create Camera2 capture session", error);
        }
    }

    private void startRepeatingCapture(
            CameraDevice camera,
            CameraCaptureSession session
    ) {
        try {
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_RECORD);
            request.addTarget(encoderSurface);
            request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
            Range<Integer> fpsRange = chooseFpsRange(profile.cameraId, profile.fps);
            if (fpsRange != null) {
                request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, fpsRange);
            }
            session.setRepeatingRequest(
                    request.build(),
                    new CameraCaptureSession.CaptureCallback() {
                        @Override
                        public void onCaptureFailed(
                                CameraCaptureSession captureSession,
                                CaptureRequest captureRequest,
                                CaptureFailure failure
                        ) {
                            droppedFrames++;
                        }
                    },
                    callbackHandler
            );
            callbackHandler.post(listener::onStreamingStarted);
        } catch (CameraAccessException | RuntimeException error) {
            deliverError("Unable to start Camera2 repeating capture", error);
        }
    }

    private Range<Integer> chooseFpsRange(String cameraId, int targetFps) {
        try {
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            Range<Integer>[] ranges = manager.getCameraCharacteristics(cameraId).get(
                    CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES
            );
            if (ranges == null || ranges.length == 0) {
                return null;
            }
            Range<Integer> best = null;
            int bestScore = Integer.MAX_VALUE;
            for (Range<Integer> range : ranges) {
                if (!range.contains(targetFps)) {
                    continue;
                }
                int score = Math.abs(range.getUpper() - targetFps) * 100
                        + (range.getUpper() - range.getLower());
                if (score < bestScore) {
                    best = range;
                    bestScore = score;
                }
            }
            return best;
        } catch (CameraAccessException error) {
            return null;
        }
    }

    private void drainEncoder() {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        MpegTsMuxer muxer = new MpegTsMuxer();
        try {
            while (running.get()) {
                MediaCodec codec = encoder;
                if (codec == null) {
                    return;
                }
                int index = codec.dequeueOutputBuffer(info, 10_000L);
                if (index == MediaCodec.INFO_TRY_AGAIN_LATER) {
                    continue;
                }
                if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    codecConfig = codecConfigFromFormat(codec.getOutputFormat());
                    continue;
                }
                if (index < 0) {
                    continue;
                }
                try {
                    ByteBuffer output = codec.getOutputBuffer(index);
                    if (output == null || info.size <= 0) {
                        continue;
                    }
                    output.position(info.offset);
                    output.limit(info.offset + info.size);
                    byte[] encoded = new byte[info.size];
                    output.get(encoded);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0) {
                        codecConfig = normaliseCodecConfig(encoded);
                        continue;
                    }
                    boolean keyFrame = (info.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0;
                    byte[] annexB = toAnnexB(encoded);
                    if (keyFrame && codecConfig.length > 0 && !containsNalType(annexB, 7)) {
                        annexB = concatenate(codecConfig, annexB);
                    }
                    UdpTsSender transport = sender;
                    if (transport == null) {
                        return;
                    }
                    muxer.writeAccessUnit(
                            annexB,
                            Math.max(0L, info.presentationTimeUs),
                            keyFrame,
                            transport
                    );
                    transport.flush();
                    framesSent++;
                    updateFps();
                } finally {
                    codec.releaseOutputBuffer(index, false);
                }
            }
        } catch (Exception error) {
            if (running.get()) {
                deliverError("H.264/MPEG-TS encoder failed", error);
            }
        }
    }

    private void updateFps() {
        fpsWindowFrames++;
        long now = SystemClock.elapsedRealtime();
        long elapsed = now - fpsWindowStartedAt;
        if (elapsed < 1_000L) {
            return;
        }
        actualFps = (int) Math.round(fpsWindowFrames * 1_000d / Math.max(1L, elapsed));
        fpsWindowFrames = 0;
        fpsWindowStartedAt = now;
        int measured = actualFps;
        callbackHandler.post(() -> listener.onFps(measured));
    }

    private void deliverError(String message, Throwable error) {
        if (!errorDelivered.compareAndSet(false, true)) {
            return;
        }
        running.set(false);
        callbackHandler.post(() -> listener.onError(message, error));
    }

    private static byte[] codecConfigFromFormat(MediaFormat format) {
        return concatenate(
                normaliseCodecConfig(readBuffer(format.getByteBuffer("csd-0"))),
                normaliseCodecConfig(readBuffer(format.getByteBuffer("csd-1")))
        );
    }

    private static byte[] readBuffer(ByteBuffer source) {
        if (source == null) {
            return new byte[0];
        }
        ByteBuffer copy = source.duplicate();
        byte[] result = new byte[copy.remaining()];
        copy.get(result);
        return result;
    }

    static byte[] normaliseCodecConfig(byte[] data) {
        if (data == null || data.length == 0) {
            return new byte[0];
        }
        if ((data[0] & 0xff) != 1 || data.length < 7) {
            return toAnnexB(data);
        }
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream(data.length + 8);
            int offset = 5;
            int spsCount = data[offset++] & 0x1f;
            for (int index = 0; index < spsCount; index++) {
                offset = appendAvcConfigNal(data, offset, output);
            }
            int ppsCount = data[offset++] & 0xff;
            for (int index = 0; index < ppsCount; index++) {
                offset = appendAvcConfigNal(data, offset, output);
            }
            return output.toByteArray();
        } catch (RuntimeException malformedConfig) {
            return toAnnexB(data);
        }
    }

    private static int appendAvcConfigNal(
            byte[] data,
            int offset,
            ByteArrayOutputStream output
    ) {
        if (offset + 2 > data.length) {
            throw new IllegalArgumentException("truncated AVC configuration");
        }
        int length = ((data[offset] & 0xff) << 8) | (data[offset + 1] & 0xff);
        offset += 2;
        if (length <= 0 || offset + length > data.length) {
            throw new IllegalArgumentException("invalid AVC NAL length");
        }
        output.write(START_CODE, 0, START_CODE.length);
        output.write(data, offset, length);
        return offset + length;
    }

    static byte[] toAnnexB(byte[] data) {
        if (data == null || data.length == 0) {
            return new byte[0];
        }
        if (startsWithStartCode(data, 0)) {
            return data;
        }
        ByteArrayOutputStream output = new ByteArrayOutputStream(data.length + 16);
        int offset = 0;
        boolean parsedLengths = false;
        while (offset + 4 <= data.length) {
            int length = ((data[offset] & 0xff) << 24)
                    | ((data[offset + 1] & 0xff) << 16)
                    | ((data[offset + 2] & 0xff) << 8)
                    | (data[offset + 3] & 0xff);
            if (length <= 0 || offset + 4 + length > data.length) {
                parsedLengths = false;
                break;
            }
            output.write(START_CODE, 0, START_CODE.length);
            output.write(data, offset + 4, length);
            offset += 4 + length;
            parsedLengths = true;
        }
        if (parsedLengths && offset == data.length) {
            return output.toByteArray();
        }
        return concatenate(START_CODE, data);
    }

    private static boolean containsNalType(byte[] annexB, int expectedType) {
        for (int index = 0; index + 4 < annexB.length; index++) {
            int nalOffset = -1;
            if (annexB[index] == 0 && annexB[index + 1] == 0 && annexB[index + 2] == 1) {
                nalOffset = index + 3;
            } else if (index + 4 < annexB.length
                    && annexB[index] == 0 && annexB[index + 1] == 0
                    && annexB[index + 2] == 0 && annexB[index + 3] == 1) {
                nalOffset = index + 4;
            }
            if (nalOffset >= 0 && nalOffset < annexB.length
                    && (annexB[nalOffset] & 0x1f) == expectedType) {
                return true;
            }
        }
        return false;
    }

    private static boolean startsWithStartCode(byte[] data, int offset) {
        return data.length - offset >= 3
                && data[offset] == 0
                && data[offset + 1] == 0
                && (data[offset + 2] == 1
                || (data.length - offset >= 4 && data[offset + 2] == 0 && data[offset + 3] == 1));
    }

    private static byte[] concatenate(byte[] first, byte[] second) {
        if (first == null || first.length == 0) {
            return second == null ? new byte[0] : second;
        }
        if (second == null || second.length == 0) {
            return first;
        }
        byte[] result = new byte[first.length + second.length];
        System.arraycopy(first, 0, result, 0, first.length);
        System.arraycopy(second, 0, result, first.length, second.length);
        return result;
    }
}
