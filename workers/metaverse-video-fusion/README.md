# Metaverse Video Fusion Worker

`metaverse_video_fusion` is an additive three-node worker: `source` exposes
the two bundled MP4 inputs over the business plane, `compute` downloads them
from `PEER_SOURCE_URL`, performs GPU MODNet foreground/background fusion and
stores durable evidence in MinIO, and `sink` reports only the P90 frame-fusion
summary and result object URIs.

For every completed instance, Compute archives the following objects in
`task-results/<instance-id>/metaverse/`:

- `fusion-result.mp4`
- `fusion-preview.jpg`
- `result.json`

On a Linux AMD64 host, build and inspect both images from a clean checkout
(the tag is intentionally immutable for acceptance):

```bash
TAG="metaverse-$(git rev-parse --short HEAD)"
WORKER_KIND=metaverse-fusion WORKER_IMAGE=manage-deploy/metaverse-video-fusion \
  WORKER_TAG="$TAG" ./scripts/build_workers.sh
WORKER_KIND=metaverse-fusion-endpoint WORKER_IMAGE=manage-deploy/metaverse-video-fusion-endpoint \
  WORKER_TAG="$TAG" ./scripts/build_workers.sh

docker image inspect "manage-deploy/metaverse-video-fusion:$TAG" \
  "manage-deploy/metaverse-video-fusion-endpoint:$TAG" \
  --format '{{.RepoTags}} {{.Architecture}}'
```

For a cross-platform acceptance build, the maintenance environment pushes the
two images to its own registry. A buildx image with `WORKER_PUSH=1` is not
loaded into the local daemon, so validate the published manifest instead:

```bash
TAG="metaverse-$(git rev-parse --short HEAD)"
WORKER_KIND=metaverse-fusion WORKER_IMAGE=<private-registry>/metaverse-video-fusion \
  WORKER_TAG="$TAG" WORKER_PLATFORM=linux/amd64 WORKER_PUSH=1 ./scripts/build_workers.sh
WORKER_KIND=metaverse-fusion-endpoint WORKER_IMAGE=<private-registry>/metaverse-video-fusion-endpoint \
  WORKER_TAG="$TAG" WORKER_PLATFORM=linux/amd64 WORKER_PUSH=1 ./scripts/build_workers.sh
docker manifest inspect "<private-registry>/metaverse-video-fusion:$TAG"
docker manifest inspect "<private-registry>/metaverse-video-fusion-endpoint:$TAG"
```

Runtime contract:

- Compute requires a GPU-capable NVIDIA runtime.
- The platform injects `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_ACCESS_KEY`,
  `MINIO_SECRET_KEY`, `TASK_INSTANCE_ID`, and `PEER_SOURCE_URL`.
- The repository already includes the MODNet checkpoint and both test videos;
  no private package source, manual model download, runtime asset mount, or
  management-network credential is required to build the images.

The checked-in assets include `cam0.mp4`, `cam1.mp4`, and the MODNet checkpoint.
