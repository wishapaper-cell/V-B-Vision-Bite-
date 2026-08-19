package com.healthydiet.rokidstreamer.model;

import java.util.Locale;

public final class StreamStatus {
    public final String state;
    public final int configuredFps;
    public final int actualFps;
    public final int width;
    public final int height;
    public final int bitrate;
    public final long framesSent;
    public final long droppedFrames;
    public final int thermalStatus;
    public final String thermalStatusName;
    public final String error;
    public final String host;
    public final int port;
    public final String endpoint;
    public final String bridgeState;
    public final int supportedMaxFps;

    public StreamStatus(
            String state,
            int configuredFps,
            int actualFps,
            int width,
            int height,
            int bitrate,
            long framesSent,
            long droppedFrames,
            int thermalStatus,
            String thermalStatusName,
            String error,
            String host,
            int port,
            String endpoint,
            String bridgeState,
            int supportedMaxFps
    ) {
        this.state = state;
        this.configuredFps = configuredFps;
        this.actualFps = actualFps;
        this.width = width;
        this.height = height;
        this.bitrate = bitrate;
        this.framesSent = framesSent;
        this.droppedFrames = droppedFrames;
        this.thermalStatus = thermalStatus;
        this.thermalStatusName = thermalStatusName;
        this.error = error == null ? "" : error;
        this.host = host;
        this.port = port;
        this.endpoint = endpoint;
        this.bridgeState = bridgeState;
        this.supportedMaxFps = supportedMaxFps;
    }

    public String displayText() {
        String errorLine = error.isEmpty() ? "none" : error;
        return String.format(
                Locale.CHINA,
                "State: %s\nCXR-S: %s\nTarget: %s\nResolution: %dx%d\n"
                        + "Configured: %d FPS\nMeasured: %d FPS\nBitrate: %d bps\n"
                        + "Frames sent: %d\nDropped: %d\nThermal: %s (%d)\nError: %s",
                state,
                bridgeState,
                endpoint,
                width,
                height,
                configuredFps,
                actualFps,
                bitrate,
                framesSent,
                droppedFrames,
                thermalStatusName,
                thermalStatus,
                errorLine
        );
    }
}
