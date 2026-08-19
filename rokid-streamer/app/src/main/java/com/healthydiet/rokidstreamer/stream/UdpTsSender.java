package com.healthydiet.rokidstreamer.stream;

import java.io.Closeable;
import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

/** Sends MPEG-TS in conventional seven-packet (1316-byte) UDP datagrams. */
public final class UdpTsSender implements MpegTsMuxer.PacketSink, Closeable {
    private static final int PACKETS_PER_DATAGRAM = 7;

    private final DatagramSocket socket;
    private final InetAddress address;
    private final int port;
    private final byte[] datagram = new byte[MpegTsMuxer.TS_PACKET_SIZE * PACKETS_PER_DATAGRAM];
    private int datagramLength;

    public UdpTsSender(String host, int port) throws IOException {
        address = InetAddress.getByName(host);
        this.port = port;
        socket = new DatagramSocket();
        socket.setSendBufferSize(512 * 1024);
    }

    @Override
    public synchronized void writePacket(byte[] packet) throws IOException {
        if (packet == null || packet.length != MpegTsMuxer.TS_PACKET_SIZE) {
            throw new IOException("MPEG-TS packet must contain exactly 188 bytes");
        }
        if (datagramLength + packet.length > datagram.length) {
            flush();
        }
        System.arraycopy(packet, 0, datagram, datagramLength, packet.length);
        datagramLength += packet.length;
        if (datagramLength == datagram.length) {
            flush();
        }
    }

    public synchronized void flush() throws IOException {
        if (datagramLength == 0) {
            return;
        }
        DatagramPacket packet = new DatagramPacket(datagram, datagramLength, address, port);
        socket.send(packet);
        datagramLength = 0;
    }

    @Override
    public synchronized void close() {
        try {
            flush();
        } catch (IOException ignored) {
            // Closing is best-effort; the service already reports transport errors while active.
        }
        socket.close();
    }
}
