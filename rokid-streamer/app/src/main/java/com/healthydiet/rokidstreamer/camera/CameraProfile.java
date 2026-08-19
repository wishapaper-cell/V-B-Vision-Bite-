package com.healthydiet.rokidstreamer.camera;

public final class CameraProfile {
    public final String cameraId;
    public final int width;
    public final int height;
    public final int fps;
    public final int maxFps;
    public final String fpsRanges;

    public CameraProfile(
            String cameraId,
            int width,
            int height,
            int fps,
            int maxFps,
            String fpsRanges
    ) {
        this.cameraId = cameraId;
        this.width = width;
        this.height = height;
        this.fps = fps;
        this.maxFps = maxFps;
        this.fpsRanges = fpsRanges;
    }
}
