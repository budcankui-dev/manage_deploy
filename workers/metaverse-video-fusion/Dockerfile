FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime

WORKDIR /app

RUN pip install --no-cache-dir \
    opencv-python-headless==4.10.0.84 \
    pillow==11.3.0 \
    httpx==0.28.1 \
    minio==7.2.15

COPY _common /app/_common
COPY metaverse-video-fusion/src /app/src
COPY metaverse-video-fusion/assets /app/assets

ENV PYTHONPATH=/app/src:/app:/app/assets/MODNet
ENV METAVERSE_ASSET_DIR=/app/assets
ENV USE_GPU=true
ENV STRICT_GPU=true
ENV LD_LIBRARY_PATH=/opt/conda/lib:${LD_LIBRARY_PATH}

CMD ["python3", "/app/src/source_main.py"]
