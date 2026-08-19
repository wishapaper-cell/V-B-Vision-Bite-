package com.healthydiet.rokidstreamer;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.healthydiet.rokidstreamer.model.StreamStatus;
import com.healthydiet.rokidstreamer.service.StreamService;
import com.healthydiet.rokidstreamer.service.StreamStatusBus;

public final class MainActivity extends Activity {
    private static final int CAMERA_PERMISSION_REQUEST = 100;
    private static final int NOTIFICATION_PERMISSION_REQUEST = 101;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private TextView statusView;
    private Button permissionButton;

    private final StreamStatusBus.Listener statusListener = status ->
            mainHandler.post(() -> renderStatus(status));

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(createContentView());
        if (hasCameraPermission()) {
            startControlService();
            finishWhenNotificationPermissionHandled();
        } else {
            permissionButton.setVisibility(View.VISIBLE);
            statusView.setText(
                    "Camera permission is required before the glasses can stream video."
            );
            requestCameraPermission();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        StreamStatusBus.addListener(statusListener);
    }

    @Override
    protected void onStop() {
        StreamStatusBus.removeListener(statusListener);
        super.onStop();
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_PERMISSION_REQUEST) {
            if (hasCameraPermission()) {
                permissionButton.setVisibility(View.GONE);
                startControlService();
                finishWhenNotificationPermissionHandled();
            } else {
                statusView.setText(
                        "Camera permission was denied. The streaming service is stopped."
                );
            }
        } else if (requestCode == NOTIFICATION_PERMISSION_REQUEST) {
            finishAndRemoveTask();
        }
    }

    private View createContentView() {
        int padding = Math.round(20 * getResources().getDisplayMetrics().density);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(padding, padding, padding, padding);
        content.setBackgroundColor(Color.BLACK);
        content.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView title = new TextView(this);
        title.setText("Rokid Camera Stream");
        title.setTextColor(Color.WHITE);
        title.setTextSize(22);
        content.addView(title, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        statusView = new TextView(this);
        statusView.setTextColor(Color.rgb(96, 220, 130));
        statusView.setTextSize(16);
        statusView.setPadding(0, padding, 0, padding);
        ScrollView scrollView = new ScrollView(this);
        scrollView.addView(statusView);
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1
        );
        content.addView(scrollView, scrollParams);

        permissionButton = new Button(this);
        permissionButton.setText("Grant camera permission");
        permissionButton.setVisibility(View.GONE);
        permissionButton.setOnClickListener(view -> requestCameraPermission());
        content.addView(permissionButton, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        return content;
    }

    private boolean hasCameraPermission() {
        return checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void requestCameraPermission() {
        requestPermissions(
                new String[]{Manifest.permission.CAMERA},
                CAMERA_PERMISSION_REQUEST
        );
    }

    private void finishWhenNotificationPermissionHandled() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    NOTIFICATION_PERMISSION_REQUEST
            );
            return;
        }
        finishAndRemoveTask();
    }

    private void startControlService() {
        Intent intent = new Intent(this, StreamService.class)
                .setAction(StreamService.ACTION_ENSURE_CONTROL);
        startForegroundService(intent);
    }

    private void renderStatus(StreamStatus status) {
        permissionButton.setVisibility(hasCameraPermission() ? View.GONE : View.VISIBLE);
        statusView.setText(status.displayText());
    }
}
