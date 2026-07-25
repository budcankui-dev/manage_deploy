# Metaverse Video Fusion Worker

`metaverse_video_fusion` is an additive three-node worker: `source` sends the
two bundled-video asset description, `compute` performs GPU MODNet
foreground/background fusion and stores durable evidence in MinIO, and `sink`
reports only the P90 frame-fusion summary and result object URIs.

For every completed instance, Compute archives the following objects in
`task-results/<instance-id>/metaverse/`:

- `fusion-result.mp4`
- `fusion-preview.jpg`
- `result.json`

Build the compute image:

```bash
WORKER_KIND=metaverse-fusion ./scripts/build_workers.sh
```

Build the smaller source/sink image:

```bash
WORKER_KIND=metaverse-fusion-endpoint ./scripts/build_workers.sh
```

The checked-in assets include `cam0.mp4`, `cam1.mp4`, and the MODNet checkpoint.
