from video_core import run_video_profile


def test_video_profile_reports_p90_latency():
    result = run_video_profile(
        {
            "frame_count": 90,
            "frame_stride": 30,
            "profile_id": "video_industrial_inspection_720p",
            "resolution": "720p",
            "fps": 30,
            "warmup_frames": 1,
            "measured_frames": 4,
            "work_units": 100,
            "seed": 7,
        }
    )

    assert result["frame_latency_p90_ms"] > 0
    assert result["frame_latency_max_ms"] >= result["frame_latency_p90_ms"]
    assert result["measured_frames"] == 4
    assert result["profile_id"] == "video_industrial_inspection_720p"
    assert result["resolution"] == "720p"
    assert result["fps"] == 30
    assert result["aggregation"] == "p90_after_warmup"
    assert result["annotated_frame_data_url"].startswith("data:image/")
    assert "annotated_frame_latency_ms" in result
    assert result["preview_frame_width"] > 0
    assert result["preview_frame_height"] > 0
    assert result["annotated_frame_overlay"] in {"zh_yolo_v1", "yolo_boxes_v1", "embedded_boxes_v1"}
    assert result["detection_count"] >= 1
    assert result["detections"]
    assert result["detections"][0]["label_zh"]
    assert result["detections"][0]["bbox_xyxy"]
