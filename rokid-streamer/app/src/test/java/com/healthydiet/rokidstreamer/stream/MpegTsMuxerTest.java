package com.healthydiet.rokidstreamer.stream;

import static com.google.common.truth.Truth.assertThat;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

import java.util.ArrayList;
import java.util.List;

@RunWith(JUnit4.class)
public final class MpegTsMuxerTest {
    @Test
    public void keyFrameEmitsPatPmtAndVideoPackets() throws Exception {
        MpegTsMuxer muxer = new MpegTsMuxer();
        List<byte[]> packets = new ArrayList<>();
        byte[] accessUnit = new byte[520];
        accessUnit[0] = 0;
        accessUnit[1] = 0;
        accessUnit[2] = 0;
        accessUnit[3] = 1;
        accessUnit[4] = 0x65;

        muxer.writeAccessUnit(accessUnit, 1_000_000L, true, packets::add);

        assertThat(packets.size()).isAtLeast(5);
        for (byte[] packet : packets) {
            assertThat(packet).hasLength(MpegTsMuxer.TS_PACKET_SIZE);
            assertThat(packet[0] & 0xff).isEqualTo(0x47);
        }
        assertThat(pid(packets.get(0))).isEqualTo(0);
        assertThat(pid(packets.get(1))).isEqualTo(MpegTsMuxer.PMT_PID);
        assertThat(pid(packets.get(2))).isEqualTo(MpegTsMuxer.VIDEO_PID);
        assertThat(packets.get(2)[1] & 0x40).isNotEqualTo(0);
    }

    @Test
    public void regularFrameDoesNotRepeatTablesBeforeInterval() throws Exception {
        MpegTsMuxer muxer = new MpegTsMuxer();
        List<byte[]> packets = new ArrayList<>();
        byte[] accessUnit = new byte[] {0, 0, 0, 1, 0x41, 1, 2, 3};

        muxer.writeAccessUnit(accessUnit, 0L, true, packet -> { });
        muxer.writeAccessUnit(accessUnit, 33_333L, false, packets::add);

        assertThat(packets).isNotEmpty();
        assertThat(pid(packets.get(0))).isEqualTo(MpegTsMuxer.VIDEO_PID);
    }

    private static int pid(byte[] packet) {
        return ((packet[1] & 0x1f) << 8) | (packet[2] & 0xff);
    }
}
