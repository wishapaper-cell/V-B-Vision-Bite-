package com.healthydiet.rokidstreamer.protocol;

import com.google.gson.Gson;
import com.healthydiet.rokidstreamer.model.StreamStatus;

public final class StatusJson {
    private static final Gson GSON = new Gson();

    private StatusJson() {
    }

    public static String encode(StreamStatus status) {
        return GSON.toJson(status);
    }
}
