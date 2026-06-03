# Low Latency Video Pipeline Worker

Lightweight video AI inference surrogate for acceptance demos.

The worker keeps the same routed data-flow shape as the matmul demo:

```text
source -> compute -> sink
```

It does not stream a full video file. The source generates deterministic frame
metadata and sends every `frame_stride`-th frame to the compute role. The
compute role simulates fixed-profile per-frame inference, records latency
samples, and the sink reports `frame_latency_p90_ms` to Task Manager.

This is intentionally small and reproducible for lab acceptance runs. A future
real model can replace `video_core.simulate_inference` without changing the
business objective contract.
