package com.healthydiet.rokidstreamer.protocol;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

import com.healthydiet.rokidstreamer.model.StreamCommand;
import com.healthydiet.rokidstreamer.model.StreamConfig;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

@RunWith(JUnit4.class)
public final class StreamCommandParserTest {
    private final StreamCommandParser parser = new StreamCommandParser();

    @Test
    public void configure_parsesDefaultsAndExplicitTarget() {
        StreamCommand command = parser.parse(
                "{\"action\":\"configure\",\"host\":\"192.168.1.9\"}",
                StreamConfig.defaults()
        );

        assertThat(command.action).isEqualTo(StreamCommand.Action.CONFIGURE);
        assertThat(command.config.host).isEqualTo("192.168.1.9");
        assertThat(command.config.port).isEqualTo(5000);
        assertThat(command.config.width).isEqualTo(1280);
        assertThat(command.config.height).isEqualTo(720);
        assertThat(command.config.fps).isEqualTo(30);
        assertThat(command.config.bitrate).isEqualTo(4_000_000);
        assertThat(command.config.endpoint()).isEqualTo("udp://192.168.1.9:5000");
    }

    @Test
    public void commandAlias_isAcceptedAndMergesCurrentConfig() {
        StreamConfig current = new StreamConfig("10.0.0.2", 5001, 960, 540, 30, 3_000_000);

        StreamCommand command = parser.parse("{\"command\":\"start\"}", current);

        assertThat(command.action).isEqualTo(StreamCommand.Action.START);
        assertThat(command.config).isEqualTo(current);
    }

    @Test
    public void configure_rejectsOddResolution() {
        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> parser.parse(
                        "{\"action\":\"configure\",\"host\":\"10.0.0.2\",\"width\":1279}",
                        StreamConfig.defaults()
                )
        );

        assertThat(error).hasMessageThat().contains("width");
    }

    @Test
    public void start_requiresTargetHost() {
        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> parser.parse("{\"action\":\"start\"}", StreamConfig.defaults())
        );

        assertThat(error).hasMessageThat().contains("host is required");
    }

    @Test
    public void ipv6Endpoint_addsRequiredBrackets() {
        StreamConfig config = new StreamConfig("fe80::1234", 5000, 1280, 720, 30, 4_000_000);

        assertThat(config.endpoint()).isEqualTo("udp://[fe80::1234]:5000");
    }
}
