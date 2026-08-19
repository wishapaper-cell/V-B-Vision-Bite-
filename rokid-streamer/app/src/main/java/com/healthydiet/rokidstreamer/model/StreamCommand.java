package com.healthydiet.rokidstreamer.model;

public final class StreamCommand {
    public enum Action {
        CONFIGURE,
        START,
        STOP,
        STATUS
    }

    public final Action action;
    public final StreamConfig config;

    public StreamCommand(Action action, StreamConfig config) {
        this.action = action;
        this.config = config;
    }
}
