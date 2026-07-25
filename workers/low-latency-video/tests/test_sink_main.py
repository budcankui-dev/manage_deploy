import sink_main


def test_metric_tags_publish_uploaded_video_objects_without_inline_base64():
    tags = sink_main._metric_tags(
        {
            "frame_latency_p90_ms": 12.3,
            "evidence_manifest_uri": "s3://task-results/instance-1/video/result.json",
            "evidence_frame_count": 1,
            "evidence_frames": [
                {"frame_index": 12, "uri": "s3://task-results/instance-1/video/frames/000012.jpg"}
            ],
            "result_objects": [
                {"name": "video-result.json", "uri": "s3://task-results/instance-1/video/result.json", "content_type": "application/json"},
                {"name": "video-frame-000012", "uri": "s3://task-results/instance-1/video/frames/000012.jpg", "content_type": "image/jpeg"},
            ],
            "annotated_frame_data_url": "data:image/jpeg;base64,should-not-be-reported",
        }
    )

    assert tags["objects"][1]["uri"].endswith("000012.jpg")
    assert tags["result"]["evidence_frame_count"] == 1
    assert "annotated_frame_data_url" not in tags["result"]
