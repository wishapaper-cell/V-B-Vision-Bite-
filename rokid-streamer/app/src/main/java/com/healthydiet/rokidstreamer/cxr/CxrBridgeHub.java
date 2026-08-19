package com.healthydiet.rokidstreamer.cxr;

import android.util.Log;

import com.rokid.cxr.Caps;
import com.rokid.cxr.CXRServiceBridge;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

public final class CxrBridgeHub {
    public static final String CONTROL_TOPIC = "health_diet_stream_control";
    public static final String STATUS_TOPIC = "health_diet_stream_status";

    public interface Listener {
        void onCommand(String replyTopic, String json);

        void onBridgeStateChanged(String bridgeState);
    }

    private static final String TAG = "CxrBridgeHub";
    private static CxrBridgeHub instance;

    private final CXRServiceBridge bridge;
    private final AtomicReference<Listener> listener = new AtomicReference<>();
    private final AtomicReference<InboundCommand> pendingCommand = new AtomicReference<>();
    private volatile String bridgeState = "initializing";

    private CxrBridgeHub() {
        bridge = new CXRServiceBridge();
        bridge.setStatusListener(new CXRServiceBridge.StatusListener() {
            @Override
            public void onConnected(String deviceName, String deviceAddress, int deviceType) {
                updateBridgeState("connected");
            }

            @Override
            public void onDisconnected() {
                updateBridgeState("disconnected");
            }

            @Override
            public void onConnecting(String deviceName, String deviceAddress, int deviceType) {
                updateBridgeState("connecting");
            }

            @Override
            public void onARTCStatus(float value, boolean ready) {
                // Camera streaming uses Wi-Fi UDP; ARTC state is not part of this transport.
            }

            @Override
            public void onRokidAccountChanged(String account) {
                // Account changes do not affect the local custom command channel.
            }

            // Present in newer CXR-S bridge builds; harmless as an extra method on 1.0.
            public void onAudioNoise(float value) {
            }
        });

        int result = bridge.subscribe(CONTROL_TOPIC, this::onReceive);
        if (result == 0) {
            bridgeState = "subscribed";
        } else {
            bridgeState = "subscribe_error_" + result;
            Log.e(TAG, "CXR-S subscribe failed: " + result);
        }
    }

    public static synchronized CxrBridgeHub initialize() {
        if (instance == null) {
            instance = new CxrBridgeHub();
        }
        return instance;
    }

    public static synchronized CxrBridgeHub get() {
        return initialize();
    }

    public void attach(Listener newListener) {
        listener.set(newListener);
        newListener.onBridgeStateChanged(bridgeState);
        InboundCommand pending = pendingCommand.getAndSet(null);
        if (pending != null) {
            newListener.onCommand(pending.replyTopic, pending.json);
        }
    }

    public void detach(Listener oldListener) {
        listener.compareAndSet(oldListener, null);
    }

    public int sendStatus(String replyTopic, String json) {
        String topic = replyTopic == null || replyTopic.isBlank() ? STATUS_TOPIC : replyTopic;
        Caps payload = new Caps();
        payload.write("status");
        payload.write(json);
        try {
            return bridge.sendMessage(topic, payload);
        } catch (Throwable error) {
            Log.e(TAG, "CXR-S status send failed", error);
            return CXRServiceBridge.EFAULT;
        }
    }

    public String getBridgeState() {
        return bridgeState;
    }

    private void onReceive(String name, Caps args, byte[] bytes) {
        if (name != null && !CONTROL_TOPIC.equals(name)) {
            return;
        }
        List<String> values = readStrings(args);
        if (values.isEmpty()) {
            Log.w(TAG, "Ignored command without string payload");
            return;
        }

        String replyTopic = STATUS_TOPIC;
        String json;
        if (values.size() >= 2 && !values.get(0).trim().startsWith("{")) {
            replyTopic = values.get(0).trim().isEmpty() ? STATUS_TOPIC : values.get(0).trim();
            json = values.get(1);
        } else {
            json = values.get(values.size() - 1);
        }

        InboundCommand command = new InboundCommand(replyTopic, json);
        Listener currentListener = listener.get();
        if (currentListener == null) {
            pendingCommand.set(command);
        } else {
            currentListener.onCommand(replyTopic, json);
        }
    }

    private List<String> readStrings(Caps args) {
        List<String> values = new ArrayList<>();
        if (args == null) {
            return values;
        }
        for (int index = 0; index < args.size(); index++) {
            try {
                Caps.Value value = args.at(index);
                if (value != null && value.type() == Caps.Value.TYPE_STRING) {
                    values.add(value.getString());
                }
            } catch (RuntimeException error) {
                Log.w(TAG, "Unable to decode CXR-S Caps value at " + index, error);
            }
        }
        return values;
    }

    private void updateBridgeState(String state) {
        bridgeState = state;
        Listener currentListener = listener.get();
        if (currentListener != null) {
            currentListener.onBridgeStateChanged(state);
        }
    }

    private static final class InboundCommand {
        final String replyTopic;
        final String json;

        InboundCommand(String replyTopic, String json) {
            this.replyTopic = replyTopic;
            this.json = json;
        }
    }
}
