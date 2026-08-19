package com.healthydiet.rokidstreamer.camera;

import android.content.Context;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaCodec;
import android.media.MediaRecorder;
import android.util.Range;
import android.util.Size;

import com.healthydiet.rokidstreamer.model.StreamConfig;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

public final class CameraProfileSelector {
    private final CameraManager cameraManager;

    public CameraProfileSelector(Context context) {
        cameraManager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
    }

    public List<CameraProfile> orderedProfiles(StreamConfig requested) throws Exception {
        String cameraId = chooseCameraId();
        CameraCharacteristics characteristics = cameraManager.getCameraCharacteristics(cameraId);
        StreamConfigurationMap map = characteristics.get(
                CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP
        );
        if (map == null) {
            throw new IllegalStateException("camera has no stream configuration map");
        }
        Class<?> outputClass = MediaCodec.class;
        Size[] sizes = map.getOutputSizes(outputClass);
        if (sizes == null || sizes.length == 0) {
            outputClass = MediaRecorder.class;
            sizes = map.getOutputSizes(outputClass);
        }
        if (sizes == null || sizes.length == 0) {
            throw new IllegalStateException("camera has no encoder output sizes");
        }

        Range<Integer>[] fpsRanges = characteristics.get(
                CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES
        );
        int sensorMaxFps = 1;
        if (fpsRanges != null) {
            for (Range<Integer> range : fpsRanges) {
                sensorMaxFps = Math.max(sensorMaxFps, range.getUpper());
            }
        }
        String rangesText = fpsRanges == null ? "[]" : Arrays.toString(fpsRanges);

        List<CameraProfile> profiles = new ArrayList<>();
        for (Size size : sizes) {
            if (size.getWidth() % 2 != 0 || size.getHeight() % 2 != 0) {
                continue;
            }
            long durationNanos = map.getOutputMinFrameDuration(outputClass, size);
            int durationMaxFps = durationNanos > 0
                    ? Math.max(1, (int) Math.floor(1_000_000_000d / durationNanos))
                    : sensorMaxFps;
            int maxFps = Math.max(1, Math.min(sensorMaxFps, durationMaxFps));
            profiles.add(new CameraProfile(
                    cameraId,
                    size.getWidth(),
                    size.getHeight(),
                    Math.min(requested.fps, maxFps),
                    maxFps,
                    rangesText
            ));
        }

        profiles.sort(profileComparator(requested));
        return profiles;
    }

    private String chooseCameraId() throws Exception {
        String[] ids = cameraManager.getCameraIdList();
        if (ids.length == 0) {
            throw new IllegalStateException("no camera is available");
        }
        for (String id : ids) {
            Integer facing = cameraManager.getCameraCharacteristics(id).get(
                    CameraCharacteristics.LENS_FACING
            );
            if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) {
                return id;
            }
        }
        return ids[0];
    }

    private Comparator<CameraProfile> profileComparator(StreamConfig requested) {
        return (left, right) -> {
            boolean leftMeetsFps = left.maxFps >= requested.fps;
            boolean rightMeetsFps = right.maxFps >= requested.fps;
            if (leftMeetsFps != rightMeetsFps) {
                return leftMeetsFps ? -1 : 1;
            }
            if (!leftMeetsFps && left.maxFps != right.maxFps) {
                return Integer.compare(right.maxFps, left.maxFps);
            }

            int leftRank = resolutionRank(left, requested);
            int rightRank = resolutionRank(right, requested);
            if (leftRank != rightRank) {
                return Integer.compare(leftRank, rightRank);
            }

            long requestedArea = (long) requested.width * requested.height;
            long leftDistance = Math.abs((long) left.width * left.height - requestedArea);
            long rightDistance = Math.abs((long) right.width * right.height - requestedArea);
            return Long.compare(leftDistance, rightDistance);
        };
    }

    private int resolutionRank(CameraProfile profile, StreamConfig requested) {
        if (profile.width == requested.width && profile.height == requested.height) {
            return 0;
        }
        if (profile.width == 1280 && profile.height == 720) {
            return 1;
        }
        if (profile.width == 960 && profile.height == 540) {
            return 2;
        }
        if (profile.width == 640 && profile.height == 480) {
            return 3;
        }
        long left = (long) profile.width * requested.height;
        long right = (long) requested.width * profile.height;
        return left == right ? 10 : 20;
    }
}
