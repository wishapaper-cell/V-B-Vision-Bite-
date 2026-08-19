package com.healthydiet.rokidstreamer.model;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

public final class StreamConfig {
    public static final int DEFAULT_PORT = 5000;
    public static final int DEFAULT_WIDTH = 1280;
    public static final int DEFAULT_HEIGHT = 720;
    public static final int DEFAULT_FPS = 30;
    public static final int DEFAULT_BITRATE = 4_000_000;

    public final String host;
    public final int port;
    public final int width;
    public final int height;
    public final int fps;
    public final int bitrate;

    public StreamConfig(
            String host,
            int port,
            int width,
            int height,
            int fps,
            int bitrate
    ) {
        this.host = host == null ? "" : host.trim();
        this.port = port;
        this.width = width;
        this.height = height;
        this.fps = fps;
        this.bitrate = bitrate;
    }

    public static StreamConfig defaults() {
        return new StreamConfig(
                "",
                DEFAULT_PORT,
                DEFAULT_WIDTH,
                DEFAULT_HEIGHT,
                DEFAULT_FPS,
                DEFAULT_BITRATE
        );
    }

    public List<String> validationErrors(boolean requireHost) {
        List<String> errors = new ArrayList<>();
        if (requireHost && host.isEmpty()) {
            errors.add("host is required");
        }
        if (!host.isEmpty()) {
            if (host.length() > 253 || containsWhitespace(host)
                    || containsAny(host, '/', '?', '#', '@')) {
                errors.add("host is malformed");
            }
        }
        if (port < 1 || port > 65_535) {
            errors.add("port must be between 1 and 65535");
        }
        if (width < 160 || width > 3840 || width % 2 != 0) {
            errors.add("width must be an even value between 160 and 3840");
        }
        if (height < 120 || height > 2160 || height % 2 != 0) {
            errors.add("height must be an even value between 120 and 2160");
        }
        if (fps < 1 || fps > 60) {
            errors.add("fps must be between 1 and 60");
        }
        if (bitrate < 128_000 || bitrate > 30_000_000) {
            errors.add("bitrate must be between 128000 and 30000000");
        }
        return errors;
    }

    public boolean isValid(boolean requireHost) {
        return validationErrors(requireHost).isEmpty();
    }

    public String endpoint() {
        String endpointHost = host;
        if (host.indexOf(':') >= 0 && !(host.startsWith("[") && host.endsWith("]"))) {
            endpointHost = "[" + host + "]";
        }
        return String.format(Locale.US, "udp://%s:%d", endpointHost, port);
    }

    private static boolean containsWhitespace(String value) {
        for (int i = 0; i < value.length(); i++) {
            if (Character.isWhitespace(value.charAt(i))) {
                return true;
            }
        }
        return false;
    }

    private static boolean containsAny(String value, char... characters) {
        for (char character : characters) {
            if (value.indexOf(character) >= 0) {
                return true;
            }
        }
        return false;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof StreamConfig)) {
            return false;
        }
        StreamConfig that = (StreamConfig) other;
        return port == that.port
                && width == that.width
                && height == that.height
                && fps == that.fps
                && bitrate == that.bitrate
                && host.equals(that.host);
    }

    @Override
    public int hashCode() {
        return Objects.hash(host, port, width, height, fps, bitrate);
    }
}
