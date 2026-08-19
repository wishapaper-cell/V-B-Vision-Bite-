package com.healthydiet.rokidstreamer.protocol;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.healthydiet.rokidstreamer.model.StreamCommand;
import com.healthydiet.rokidstreamer.model.StreamConfig;

import java.util.List;
import java.util.Locale;

public final class StreamCommandParser {
    public StreamCommand parse(String json, StreamConfig currentConfig) {
        if (json == null || json.trim().isEmpty()) {
            throw new IllegalArgumentException("command JSON is empty");
        }

        JsonElement parsed;
        try {
            parsed = JsonParser.parseString(json);
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("command is not valid JSON", error);
        }
        if (!parsed.isJsonObject()) {
            throw new IllegalArgumentException("command must be a JSON object");
        }

        JsonObject object = parsed.getAsJsonObject();
        String actionValue = optionalString(object, "action", null);
        if (actionValue == null) {
            actionValue = optionalString(object, "command", null);
        }
        if (actionValue == null || actionValue.trim().isEmpty()) {
            throw new IllegalArgumentException("action is required");
        }

        StreamCommand.Action action;
        try {
            action = StreamCommand.Action.valueOf(actionValue.trim().toUpperCase(Locale.US));
        } catch (IllegalArgumentException error) {
            throw new IllegalArgumentException("unsupported action: " + actionValue, error);
        }

        StreamConfig merged = mergeConfig(object, currentConfig);
        if (action == StreamCommand.Action.CONFIGURE || action == StreamCommand.Action.START) {
            List<String> errors = merged.validationErrors(true);
            if (!errors.isEmpty()) {
                throw new IllegalArgumentException(String.join("; ", errors));
            }
        }
        return new StreamCommand(action, merged);
    }

    private StreamConfig mergeConfig(JsonObject object, StreamConfig current) {
        return new StreamConfig(
                optionalString(object, "host", current.host),
                optionalInt(object, "port", current.port),
                optionalInt(object, "width", current.width),
                optionalInt(object, "height", current.height),
                optionalInt(object, "fps", current.fps),
                optionalInt(object, "bitrate", current.bitrate)
        );
    }

    private static String optionalString(JsonObject object, String name, String fallback) {
        if (!object.has(name) || object.get(name).isJsonNull()) {
            return fallback;
        }
        JsonElement value = object.get(name);
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) {
            throw new IllegalArgumentException(name + " must be a string");
        }
        return value.getAsString();
    }

    private static int optionalInt(JsonObject object, String name, int fallback) {
        if (!object.has(name) || object.get(name).isJsonNull()) {
            return fallback;
        }
        JsonElement value = object.get(name);
        try {
            if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) {
                throw new NumberFormatException();
            }
            return value.getAsInt();
        } catch (RuntimeException error) {
            throw new IllegalArgumentException(name + " must be an integer", error);
        }
    }
}
