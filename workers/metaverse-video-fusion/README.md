# Metaverse Video Fusion Worker

`metaverse_video_fusion` is an additive three-node worker: `source` reads two
bundled videos, `compute` performs GPU MODNet foreground/background fusion,
and `sink` reports the P90 frame-fusion latency and preview frames.

Build the compute image:

```bash
WORKER_KIND=metaverse-fusion ./scripts/build_workers.sh
```

Build the smaller source/sink image:

```bash
WORKER_KIND=metaverse-fusion-endpoint ./scripts/build_workers.sh
```

The checked-in assets include `cam0.mp4`, `cam1.mp4`, and the MODNet checkpoint.
