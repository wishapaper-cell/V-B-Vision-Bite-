from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from backend.models.schemas import FoodTrack, IntakeEvent
from backend.services.nutrition import profile_for_key
from backend.services.utensil_tracker import UtensilObservation
from backend.services.volume_estimator import estimate_bite_weight
from backend.services.calibration import ScaleMetadata


@dataclass
class _UtensilTrack:
    track_id: str
    utensil_type: str
    last_bbox: list[int]
    last_center: tuple[float, float]
    state: str = "utensil_detected"
    contact_food_track_id: str | None = None
    carried_food_area_px: int = 0
    confidence: float = 0.0
    frame_height: int = 0
    frames_in_state: int = 0
    last_seen_ms: int = 0
    emitted_states: set[str] = field(default_factory=set)
    lift_start_center_y: float | None = None
    contact_frames: int = 0
    cooldown_until_ms: int = 0
    recent_centers: deque[tuple[int, tuple[float, float]]] = field(default_factory=lambda: deque(maxlen=8))


class ConsumptionTracker:
    MAX_CONFIRMS_PER_MINUTE = 20

    def __init__(self) -> None:
        self.next_event_index = 1
        self._tracks: dict[str, _UtensilTrack] = {}
        self._next_track_id = 1
        self._confirm_times: deque[int] = deque(maxlen=32)

    def _confirm_allowed(self, timestamp_ms: int) -> bool:
        while self._confirm_times and timestamp_ms - self._confirm_times[0] > 60_000:
            self._confirm_times.popleft()
        return len(self._confirm_times) < self.MAX_CONFIRMS_PER_MINUTE

    def build_events(
        self,
        *,
        timestamp_ms: int,
        foods: list[FoodTrack],
        utensils: list[UtensilObservation],
        scale: ScaleMetadata | None,
    ) -> list[IntakeEvent]:
        events: list[IntakeEvent] = []
        food_by_id = {food.track_id: food for food in foods}
        assigned_tracks: set[str] = set()

        for utensil in utensils:
            track_id = self._match_track(utensil, timestamp_ms)
            if track_id is None:
                # First-person view: the wearer's utensil extends from their
                # hand at the bottom of the frame. Utensils that never reach
                # the lower half belong to other diners; don't track them.
                frame_h = utensil.frame_height or 0
                if frame_h > 0 and utensil.bbox[3] < 0.45 * frame_h:
                    continue
                track_id = f"utensil_track_{self._next_track_id:03d}"
                self._next_track_id += 1
                self._tracks[track_id] = _UtensilTrack(
                    track_id=track_id,
                    utensil_type=utensil.utensil_type,
                    last_bbox=utensil.bbox,
                    last_center=_center(utensil.bbox),
                    state="utensil_detected",
                    frame_height=utensil.frame_height or max(utensil.bbox[3] - utensil.bbox[1], 1) * 4,
                    last_seen_ms=timestamp_ms,
                    confidence=utensil.confidence,
                )

            track = self._tracks[track_id]
            assigned_tracks.add(track_id)
            current_center = _center(utensil.bbox)
            delta_y = current_center[1] - track.last_center[1]
            frame_height = max(1, utensil.frame_height or track.frame_height)
            track.last_bbox = utensil.bbox
            track.last_center = current_center
            track.last_seen_ms = timestamp_ms
            track.confidence = utensil.confidence
            track.frame_height = frame_height
            track.utensil_type = utensil.utensil_type
            track.recent_centers.append((timestamp_ms, current_center))

            has_contact = utensil.contact_food_track_id is not None
            if has_contact:
                track.contact_food_track_id = utensil.contact_food_track_id
                track.carried_food_area_px = utensil.carried_food_area_px
                track.contact_frames += 1
            else:
                track.contact_frames = 0

            contact_confirmed = has_contact and track.contact_frames >= 2

            new_state = self._next_state(
                track=track,
                has_contact=contact_confirmed,
                delta_y=delta_y,
                frame_height=frame_height,
                timestamp_ms=timestamp_ms,
            )

            if new_state == "intake_confirmed" and not self._confirm_allowed(timestamp_ms):
                new_state = "uncertain"

            if new_state != track.state:
                if new_state == "intake_confirmed":
                    self._confirm_times.append(timestamp_ms)
                event = self._emit_event(
                    track=track,
                    new_state=new_state,
                    timestamp_ms=timestamp_ms,
                    foods=food_by_id,
                    scale=scale,
                )
                if event is not None:
                    events.append(event)
                track.state = new_state
                track.frames_in_state = 1
                track.emitted_states.add(new_state)
                if new_state in {"food_lifted", "moving_to_mouth"} and track.lift_start_center_y is None:
                    track.lift_start_center_y = track.last_center[1]
                if new_state == "intake_confirmed":
                    track.cooldown_until_ms = timestamp_ms + 1000
                    track.lift_start_center_y = None
                elif new_state in {"returned_to_plate", "uncertain"}:
                    track.lift_start_center_y = None
            else:
                track.frames_in_state += 1

        # A utensil that vanished while lifted (moved off-frame toward the
        # mouth) counts as a confirmed intake: first-person view loses the
        # utensil exactly when the bite happens.
        vanish_confirm_ms = 400
        for track_id, track in self._tracks.items():
            if track_id in assigned_tracks:
                continue
            gone_ms = timestamp_ms - track.last_seen_ms
            if gone_ms < vanish_confirm_ms:
                continue
            near_top = track.last_center[1] < 0.5 * max(1, track.frame_height)
            carried_food = track.contact_food_track_id is not None and track.carried_food_area_px > 0
            if track.state in {"food_lifted", "moving_to_mouth"} and near_top and carried_food:
                if not self._confirm_allowed(timestamp_ms):
                    continue
                self._confirm_times.append(timestamp_ms)
                event = self._emit_event(
                    track=track,
                    new_state="intake_confirmed",
                    timestamp_ms=timestamp_ms,
                    foods=food_by_id,
                    scale=scale,
                )
                if event is not None:
                    events.append(event)
                track.state = "intake_confirmed"
                track.frames_in_state = 1
                track.emitted_states.add("intake_confirmed")
                track.cooldown_until_ms = timestamp_ms + 1000
                track.lift_start_center_y = None

        # Remove tracks that have not been seen for a while.
        stale_threshold_ms = 1500
        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if track_id in assigned_tracks or (timestamp_ms - track.last_seen_ms) <= stale_threshold_ms
        }
        return events

    def _match_track(self, utensil: UtensilObservation, timestamp_ms: int) -> str | None:
        same_type: list[tuple[str, _UtensilTrack]] = [
            (track_id, track)
            for track_id, track in self._tracks.items()
            if track.utensil_type == utensil.utensil_type
        ]
        if not same_type:
            return None

        # Prefer a track seen very recently, even if it moved far (mouth motion).
        # Use 300 ms (~10 frames at 30 FPS) to tolerate fast upward motion.
        recent_candidates: list[tuple[float, str]] = []
        for track_id, track in same_type:
            if timestamp_ms - track.last_seen_ms <= 300:
                center_a = _center(track.last_bbox)
                center_b = _center(utensil.bbox)
                distance = math.hypot(center_a[0] - center_b[0], center_a[1] - center_b[1])
                recent_candidates.append((distance, track_id))
        if recent_candidates:
            return min(recent_candidates)[1]

        best_id: str | None = None
        best_score = 0.20
        frame_size = max(1, utensil.frame_width, utensil.frame_height)
        distance_threshold = max(120, int(frame_size * 0.55))
        for track_id, track in same_type:
            iou = _bbox_iou(track.last_bbox, utensil.bbox)
            center_a = _center(track.last_bbox)
            center_b = _center(utensil.bbox)
            distance = math.hypot(center_a[0] - center_b[0], center_a[1] - center_b[1])
            proximity = max(0.0, 1.0 - distance / distance_threshold)
            score = max(iou, proximity)
            if score > best_score:
                best_score = score
                best_id = track_id
        return best_id

    def _next_state(
        self,
        *,
        track: _UtensilTrack,
        has_contact: bool,
        delta_y: float,
        frame_height: int,
        timestamp_ms: int,
    ) -> str:
        state = track.state
        smoothed_dy = _smoothed_vertical_delta(track.recent_centers, window_ms=200)
        dy = smoothed_dy if smoothed_dy is not None else delta_y
        lifted = dy < -0.10 * frame_height
        lowered = dy > 0.07 * frame_height
        near_top = track.last_center[1] < 0.35 * frame_height
        near_bottom = track.last_center[1] > 0.60 * frame_height
        in_cooldown = timestamp_ms < track.cooldown_until_ms

        if state in {"intake_confirmed", "returned_to_plate", "uncertain"}:
            # Reset after a completed action; honor cooldown before next intake.
            if in_cooldown:
                return state
            if has_contact:
                return "utensil_contact_food"
            return "utensil_detected"

        if state == "utensil_detected":
            if has_contact:
                return "utensil_contact_food"
            return state

        if state == "utensil_contact_food":
            if lifted:
                return "food_lifted"
            if not has_contact:
                return "utensil_detected"
            return state

        if state == "food_lifted":
            lifted_far = (
                track.lift_start_center_y is not None
                and (track.lift_start_center_y - track.last_center[1]) > 0.20 * frame_height
            )
            if lifted or lifted_far or (track.frames_in_state >= 2 and near_top):
                return "moving_to_mouth"
            if lowered and has_contact:
                return "returned_to_plate"
            if lowered and not has_contact:
                return "uncertain"
            return state

        if state == "moving_to_mouth":
            lowered_far = (
                track.lift_start_center_y is not None
                and (track.last_center[1] - track.lift_start_center_y) > 0.12 * frame_height
            )
            if lowered_far or lowered or near_bottom:
                return "intake_confirmed"
            if not has_contact and track.frames_in_state >= 2:
                # Lost contact while raised; assume bite taken.
                return "intake_confirmed"
            return state

        return state

    def _emit_event(
        self,
        *,
        track: _UtensilTrack,
        new_state: str,
        timestamp_ms: int,
        foods: dict[str, FoodTrack],
        scale: ScaleMetadata | None,
    ) -> IntakeEvent | None:
        source = foods.get(track.contact_food_track_id) if track.contact_food_track_id else None
        if source is not None:
            profile = profile_for_key(source.profile_key)
            bite = estimate_bite_weight(
                carried_food_area_px=max(1, track.carried_food_area_px),
                profile=profile,
                utensil_type=track.utensil_type,
                scale=scale,
                confidence=min(source.confidence, track.confidence),
            )
            estimated_bite_weight_g = bite.weight_g
            bite_weight_error_g = bite.weight_error_g
            bite_area_cm2 = bite.area_cm2
            bite_volume_ml = bite.volume_ml
            weight_source = bite.weight_source
        else:
            estimated_bite_weight_g = 0.0
            bite_weight_error_g = 0.0
            bite_area_cm2 = 0.0
            bite_volume_ml = 0.0
            weight_source = "visual_fallback"

        if new_state == "utensil_detected":
            return None
        source_confidence = round(min(0.82, (source.confidence if source else 0) * 0.62 + track.confidence * 0.24), 2)
        intake_confidence = self._intake_confidence(new_state, track, scale)
        event_id = f"intake_{self.next_event_index:04d}"
        self.next_event_index += 1
        return IntakeEvent(
            event_id=event_id,
            state=new_state,
            utensil_type=track.utensil_type,
            source_track_id=source.track_id if source else None,
            source_profile_key=source.profile_key if source else "unknown_food",
            source_confidence=source_confidence,
            mixed_sources=[],
            estimated_bite_weight_g=estimated_bite_weight_g,
            bite_weight_error_g=bite_weight_error_g,
            bite_area_cm2=bite_area_cm2,
            bite_volume_ml=bite_volume_ml,
            weight_source=weight_source,
            reference_detected=bool(scale and scale.usable),
            scale_confidence=round(scale.confidence, 2) if scale else 0,
            trajectory_confidence=round(track.confidence * 0.45, 2),
            intake_confidence=intake_confidence,
            started_at_ms=timestamp_ms,
        )

    @staticmethod
    def _intake_confidence(state: str, track: _UtensilTrack, scale: ScaleMetadata | None) -> float:
        if state == "intake_confirmed":
            base = 0.72
        elif state == "moving_to_mouth":
            base = 0.55
        elif state == "food_lifted":
            base = 0.42
        elif state == "returned_to_plate":
            base = 0.30
        else:
            base = 0.28
        scale_bonus = 0.12 if scale and scale.usable else 0.0
        return round(min(0.92, base + track.confidence * 0.16 + scale_bonus), 2)


def summarize_confirmed_intake(events: list[IntakeEvent], track_id: str) -> tuple[float, int]:
    confirmed = [event for event in events if event.source_track_id == track_id and event.state == "intake_confirmed"]
    return round(sum(event.estimated_bite_weight_g for event in confirmed), 1), len(confirmed)


def _center(bbox: list[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _bbox_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    intersection = iw * ih
    union = max(1, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
    return intersection / union


def _smoothed_vertical_delta(centers: deque[tuple[int, tuple[float, float]]], window_ms: int) -> float | None:
    """Average vertical speed (px/ms) over the last `window_ms`."""
    if len(centers) < 2:
        return None
    newest_ts, newest_y = centers[-1][0], centers[-1][1][1]
    total_dy = 0.0
    total_dt = 0.0
    for ts, (_, y) in list(centers)[:-1]:
        dt = newest_ts - ts
        if dt <= 0 or dt > window_ms:
            continue
        total_dy += (newest_y - y) / dt
        total_dt += 1.0
    if total_dt == 0:
        return None
    # Return the displacement over the whole window so thresholds hold
    # regardless of capture cadence (33ms video vs ~150ms phone frames).
    return (total_dy / total_dt) * window_ms
