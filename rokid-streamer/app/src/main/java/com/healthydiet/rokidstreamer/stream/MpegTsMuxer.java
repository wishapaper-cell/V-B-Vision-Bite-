package com.healthydiet.rokidstreamer.stream;

import java.io.ByteArrayOutputStream;
import java.io.IOException;

/** Minimal MPEG-TS muxer for one H.264 video elementary stream. */
public final class MpegTsMuxer {
    public interface PacketSink {
        void writePacket(byte[] packet) throws IOException;
    }

    public static final int TS_PACKET_SIZE = 188;
    public static final int PMT_PID = 0x0100;
    public static final int VIDEO_PID = 0x0101;

    private int patContinuity;
    private int pmtContinuity;
    private int videoContinuity;
    private long frameCount;

    public synchronized void writeAccessUnit(
            byte[] annexB,
            long presentationTimeUs,
            boolean keyFrame,
            PacketSink sink
    ) throws IOException {
        if (annexB == null || annexB.length == 0) {
            return;
        }
        if (frameCount == 0 || keyFrame || frameCount % 30 == 0) {
            sink.writePacket(psiPacket(0, buildPatSection(), patContinuity++));
            sink.writePacket(psiPacket(PMT_PID, buildPmtSection(), pmtContinuity++));
        }
        byte[] pes = buildPes(annexB, presentationTimeUs);
        writePesPackets(pes, sink);
        frameCount++;
    }

    private void writePesPackets(byte[] pes, PacketSink sink) throws IOException {
        int offset = 0;
        boolean first = true;
        while (offset < pes.length) {
            int remaining = pes.length - offset;
            int payloadLength = Math.min(184, remaining);
            byte[] packet = new byte[TS_PACKET_SIZE];
            packet[0] = 0x47;
            packet[1] = (byte) (((first ? 0x40 : 0) | ((VIDEO_PID >> 8) & 0x1f)) & 0xff);
            packet[2] = (byte) (VIDEO_PID & 0xff);

            int payloadOffset;
            if (payloadLength == 184) {
                packet[3] = (byte) (0x10 | (videoContinuity++ & 0x0f));
                payloadOffset = 4;
            } else {
                packet[3] = (byte) (0x30 | (videoContinuity++ & 0x0f));
                int adaptationBytes = 184 - payloadLength;
                int adaptationLength = adaptationBytes - 1;
                packet[4] = (byte) adaptationLength;
                if (adaptationLength > 0) {
                    packet[5] = 0;
                    for (int index = 6; index < 5 + adaptationLength; index++) {
                        packet[index] = (byte) 0xff;
                    }
                }
                payloadOffset = 4 + adaptationBytes;
            }
            System.arraycopy(pes, offset, packet, payloadOffset, payloadLength);
            sink.writePacket(packet);
            offset += payloadLength;
            first = false;
        }
    }

    private static byte[] buildPes(byte[] annexB, long presentationTimeUs) {
        long pts = Math.max(0, presentationTimeUs) * 90L / 1_000L;
        ByteArrayOutputStream output = new ByteArrayOutputStream(annexB.length + 14);
        output.write(0);
        output.write(0);
        output.write(1);
        output.write(0xe0);
        output.write(0);
        output.write(0); // A zero PES length is valid for an unbounded video PES packet.
        output.write(0x80);
        output.write(0x80);
        output.write(5);
        output.write((int) (0x21 | (((pts >> 30) & 0x07) << 1)));
        output.write((int) ((pts >> 22) & 0xff));
        output.write((int) ((((pts >> 15) & 0x7f) << 1) | 1));
        output.write((int) ((pts >> 7) & 0xff));
        output.write((int) (((pts & 0x7f) << 1) | 1));
        output.write(annexB, 0, annexB.length);
        return output.toByteArray();
    }

    private static byte[] psiPacket(int pid, byte[] section, int continuity) {
        byte[] packet = new byte[TS_PACKET_SIZE];
        packet[0] = 0x47;
        packet[1] = (byte) (0x40 | ((pid >> 8) & 0x1f));
        packet[2] = (byte) (pid & 0xff);
        packet[3] = (byte) (0x10 | (continuity & 0x0f));
        packet[4] = 0; // pointer_field
        System.arraycopy(section, 0, packet, 5, section.length);
        for (int index = 5 + section.length; index < packet.length; index++) {
            packet[index] = (byte) 0xff;
        }
        return packet;
    }

    private static byte[] buildPatSection() {
        byte[] sectionWithoutCrc = new byte[] {
                0x00,
                (byte) 0xb0, 0x0d,
                0x00, 0x01,
                (byte) 0xc1,
                0x00, 0x00,
                0x00, 0x01,
                (byte) (0xe0 | ((PMT_PID >> 8) & 0x1f)), (byte) (PMT_PID & 0xff)
        };
        return appendCrc(sectionWithoutCrc);
    }

    private static byte[] buildPmtSection() {
        byte[] sectionWithoutCrc = new byte[] {
                0x02,
                (byte) 0xb0, 0x12,
                0x00, 0x01,
                (byte) 0xc1,
                0x00, 0x00,
                (byte) (0xe0 | ((VIDEO_PID >> 8) & 0x1f)), (byte) (VIDEO_PID & 0xff),
                (byte) 0xf0, 0x00,
                0x1b,
                (byte) (0xe0 | ((VIDEO_PID >> 8) & 0x1f)), (byte) (VIDEO_PID & 0xff),
                (byte) 0xf0, 0x00
        };
        return appendCrc(sectionWithoutCrc);
    }

    private static byte[] appendCrc(byte[] section) {
        long crc = mpegCrc32(section);
        byte[] result = new byte[section.length + 4];
        System.arraycopy(section, 0, result, 0, section.length);
        result[section.length] = (byte) ((crc >> 24) & 0xff);
        result[section.length + 1] = (byte) ((crc >> 16) & 0xff);
        result[section.length + 2] = (byte) ((crc >> 8) & 0xff);
        result[section.length + 3] = (byte) (crc & 0xff);
        return result;
    }

    private static long mpegCrc32(byte[] data) {
        long crc = 0xffffffffL;
        for (byte value : data) {
            crc ^= (long) (value & 0xff) << 24;
            for (int bit = 0; bit < 8; bit++) {
                crc = (crc & 0x80000000L) != 0
                        ? ((crc << 1) ^ 0x04c11db7L) & 0xffffffffL
                        : (crc << 1) & 0xffffffffL;
            }
        }
        return crc;
    }
}
