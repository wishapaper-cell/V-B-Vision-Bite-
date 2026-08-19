package com.healthydiet.rokidstreamer.protocol;

import static com.google.common.truth.Truth.assertThat;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.healthydiet.rokidstreamer.model.StreamStatus;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

@RunWith(JUnit4.class)
public final class StatusJsonTest {
    @Test
    public void encode_containsMeasuredAndTransportFields() {
        StreamStatus status = new StreamStatus(
                "streaming",
                30,
                29,
                1280,
                720,
                4_000_000,
                900,
                3,
                2,
                "moderate",
                "",
                "192.168.1.9",
                5000,
                "udp://192.168.1.9:5000",
                "connected",
                30
        );

        JsonObject json = JsonParser.parseString(StatusJson.encode(status)).getAsJsonObject();

        assertThat(json.get("state").getAsString()).isEqualTo("streaming");
        assertThat(json.get("configuredFps").getAsInt()).isEqualTo(30);
        assertThat(json.get("actualFps").getAsInt()).isEqualTo(29);
        assertThat(json.get("framesSent").getAsLong()).isEqualTo(900);
        assertThat(json.get("droppedFrames").getAsLong()).isEqualTo(3);
        assertThat(json.get("thermalStatus").getAsInt()).isEqualTo(2);
    }
}
