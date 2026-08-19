from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SessionStatus = Literal[
    "waiting_mobile",
    "mobile_connected",
    "camera_ready",
    "streaming",
    "measuring",
    "completed",
    "error",
]

WeightSource = Literal["aruco_calibrated", "container_model", "visual_fallback", "unknown"]
EstimationLevel = Literal["calibrated", "approximate", "rough", "unsupported"]
UtensilType = Literal["chopsticks", "spoon", "fork", "hand", "unknown"]
IntakeState = Literal[
    "utensil_detected",
    "utensil_contact_food",
    "food_lifted",
    "moving_to_mouth",
    "intake_confirmed",
    "returned_to_plate",
    "uncertain",
]


class DeviceInfo(BaseModel):
    platform: str = "android"
    model: str = "unknown"
    user_agent: str = ""
    app_version: str = "web-demo"


class JoinSessionRequest(BaseModel):
    token: str
    device: DeviceInfo = Field(default_factory=DeviceInfo)


class CaptureEvent(BaseModel):
    token: str
    event: Literal[
        "camera_permission_granted",
        "camera_permission_denied",
        "stream_started",
        "stream_stopped",
        "capture_error",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class FrameUpload(BaseModel):
    token: str
    image: str
    width: int
    height: int
    timestamp_ms: int
    device_motion: dict[str, Any] = Field(default_factory=dict)


class Nutrition(BaseModel):
    calories_kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float = 0
    sodium_mg: float = 0


class FoodTrack(BaseModel):
    track_id: str
    name: str
    category: str
    profile_key: str = "unknown_food"
    cooking_method: str = "unknown"
    cooking_method_name: str = "未识别"
    cooking_confidence: float = 0
    raw_weight_g: float = 0
    area_ratio: float = 0
    bbox_area_ratio: float = 0
    scale_view_quality: float = 0
    scale_corrected: bool = False
    scale_confidence: float = 0
    scale_sample_count: int = 0
    scale_status: str = "calibrating"
    reference_detected: bool = False
    reference_type: str = "none"
    reference_marker_id: int | None = None
    scale_mm_per_px: float = 0
    weight_source: WeightSource = "visual_fallback"
    weight_estimation_level: EstimationLevel = "rough"
    area_cm2: float = 0
    estimated_height_cm: float = 0
    shape_factor: float = 0
    container_type: str = "none"
    container_confidence: float = 0
    occlusion_score: float = 0
    consumption_state: str = "observing"
    remaining_ratio: float | None = None
    intake_weight_sum_g: float = 0
    confirmed_intake_event_count: int = 0
    last_intake_event_at: int | None = None
    state: str = "tracking"
    bbox: list[int]
    polygon: list[list[int]] = Field(default_factory=list)
    mask_svg_path: str = ""
    color: str = "#7cf4bd"
    confidence: float
    volume_ml: float
    volume_confidence: float
    density_g_per_ml: float
    estimated_weight_g: float
    weight_error_g: float
    weight_confidence: float
    visible_frames: int = 1
    sample_count: int = 1
    stable_seconds: float = 0
    convergence: float = 0
    first_seen_seconds: float = 0
    last_seen_seconds: float = 0
    nutrition: Nutrition


class MeasurementQuality(BaseModel):
    angle_coverage: float = 0
    depth_completeness: float = 0
    mask_stability: float = 0
    motion_quality: float = 0
    lighting: float = 0
    blur: float = 0
    plate_visibility: float = 0
    reference_visibility: float = 0
    scale_quality: float = 0
    container_visibility: float = 0
    calibrated_frame_ratio: float = 0
    utensil_visibility: float = 0
    intake_event_quality: float = 0
    overall: float = 0


class IntakeEvent(BaseModel):
    event_id: str
    state: IntakeState
    utensil_type: UtensilType = "unknown"
    source_track_id: str | None = None
    source_profile_key: str = "unknown_food"
    source_confidence: float = 0
    mixed_sources: list[dict[str, Any]] = Field(default_factory=list)
    estimated_bite_weight_g: float = 0
    bite_weight_error_g: float = 0
    bite_area_cm2: float = 0
    bite_volume_ml: float = 0
    weight_source: WeightSource = "visual_fallback"
    reference_detected: bool = False
    scale_confidence: float = 0
    trajectory_confidence: float = 0
    intake_confidence: float = 0
    started_at_ms: int
    confirmed_at_ms: int | None = None


class VideoInfo(BaseModel):
    fps: float = 0
    resolution: str = "0x0"
    quality: str = "waiting"
    last_frame_at: str | None = None


class Guidance(BaseModel):
    message: str = "请用手机扫码并授权摄像头。"
    needed_action: str = "connect_mobile"


class SessionState(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    session_id: str
    status: SessionStatus
    created_at: datetime
    expires_at: datetime
    elapsed_seconds: float = 0
    frame_count: int = 0
    analyzed_frame_count: int = 0
    analyzer: str = "not_loaded"
    model_name: str = "none"
    capture_url: str
    qr_code_url: str
    video: VideoInfo = Field(default_factory=VideoInfo)
    measurement_quality: MeasurementQuality = Field(default_factory=MeasurementQuality)
    foods: list[FoodTrack] = Field(default_factory=list)
    intake_events: list[IntakeEvent] = Field(default_factory=list)
    confirmed_intake_weight_g: float = 0
    utensil_event_count: int = 0
    confirmed_intake_event_count: int = 0
    guidance: Guidance = Field(default_factory=Guidance)
    latest_frame_url: str | None = None
    device: DeviceInfo | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    token: str
    capture_url: str
    qr_code_url: str
    events_url: str
    expires_at: datetime


class Report(BaseModel):
    report_id: str
    session_id: str
    created_at: datetime
    meal_summary: dict[str, float]
    foods: list[dict[str, Any]]
    scan_quality: dict[str, Any]
    warnings: list[str]
