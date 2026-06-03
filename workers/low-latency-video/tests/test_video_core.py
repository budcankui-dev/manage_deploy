from video_core import run_video_profile


def test_video_profile_reports_p90_latency():
    result = run_video_profile(
        {
            "frame_count": 90,
            "frame_stride": 30,
            "warmup_frames": 1,
            "measured_frames": 4,
            "work_units": 100,
            "seed": 7,
        }
    )

    assert result["frame_latency_p90_ms"] > 0
    assert result["frame_latency_max_ms"] >= result["frame_latency_p90_ms"]
    assert result["measured_frames"] == 4
    assert result["aggregation"] == "p90_after_warmup"
