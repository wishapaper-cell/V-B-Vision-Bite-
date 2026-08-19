package com.healthydiet.rokidstreamer.service;

import com.healthydiet.rokidstreamer.model.StreamStatus;

import java.util.concurrent.CopyOnWriteArraySet;
import java.util.concurrent.atomic.AtomicReference;

public final class StreamStatusBus {
    public interface Listener {
        void onStatus(StreamStatus status);
    }

    private static final AtomicReference<StreamStatus> LATEST = new AtomicReference<>();
    private static final CopyOnWriteArraySet<Listener> LISTENERS = new CopyOnWriteArraySet<>();

    private StreamStatusBus() {
    }

    public static void addListener(Listener listener) {
        LISTENERS.add(listener);
        StreamStatus latest = LATEST.get();
        if (latest != null) {
            listener.onStatus(latest);
        }
    }

    public static void removeListener(Listener listener) {
        LISTENERS.remove(listener);
    }

    public static StreamStatus latest() {
        return LATEST.get();
    }

    public static void publish(StreamStatus status) {
        LATEST.set(status);
        for (Listener listener : LISTENERS) {
            listener.onStatus(status);
        }
    }
}
