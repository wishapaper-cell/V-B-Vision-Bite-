package com.healthydiet.rokidstreamer;

import android.app.Application;
import android.util.Log;

import com.healthydiet.rokidstreamer.cxr.CxrBridgeHub;

public final class RokidStreamerApplication extends Application {
    private static final String TAG = "RokidStreamerApp";

    @Override
    public void onCreate() {
        super.onCreate();
        try {
            CxrBridgeHub.initialize();
        } catch (Throwable error) {
            Log.e(TAG, "Unable to initialize CXR-S command bridge", error);
        }
    }
}
