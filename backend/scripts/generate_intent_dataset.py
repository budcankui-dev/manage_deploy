"""Generate the fixed multi-business intent evaluation dataset.

The dataset is deterministic by design: templates define expression styles,
slots define valid node/time/profile values, and labels are emitted from the
same slots.  This makes the evaluation explainable for acceptance review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


NODES = ["compute-1", "compute-2", "compute-3"]
STRATEGIES = [
    ("resource_guarantee", "资源保障策略"),
    ("fastest_completion", "尽快完成"),
    ("load_balance", "选择空闲节点负载均衡"),
    ("cost_priority", "成本优先省钱"),
]
TIME_PHRASES = [
    ("现在开始跑2小时", 120),
    ("立即运行60分钟", 60),
    ("马上开始跑3小时", 180),
]

TASKS = {
    "high_throughput_matmul": {
        "valid_templates": [
            "矩阵乘法任务，从 {src} 到 {dst}，{matrix_size}阶矩阵，{batch_count}批，{time}，{strategy_text}",
            "请提交通用计算任务 source: {src} dest: {dst}, matrix_size={matrix_size}, batch_count={batch_count}, {time}, {strategy_text}",
            "从{src}到{dst}跑 matmul，{matrix_size}x{matrix_size}，batch {batch_count}，{time}，{strategy_text}",
            "业务节点随路计算：{src} -> {dst}，矩阵大小{matrix_size}，总共{batch_count}批次，{time}，{strategy_text}",
            "创建矩阵计算业务，业务源节点是 {src}，业务目的节点是 {dst}，规模 {matrix_size} 阶，连续执行 {batch_count} 批，{time}，{strategy_text}",
            "我要验证通用计算能力，任务源节点 {src}、任务目的节点 {dst}，矩阵 {matrix_size}x{matrix_size}，批次数 {batch_count}，{time}，{strategy_text}",
            "提交一条随路计算工单：从业务源节点 {src} 到业务目的节点 {dst}，执行 {matrix_size} 阶矩阵乘法 {batch_count} 批，{time}，{strategy_text}",
        ],
        "slots": [
            {"matrix_size": 512, "batch_count": 20},
            {"matrix_size": 1024, "batch_count": 50},
            {"matrix_size": 2048, "batch_count": 80},
        ],
        "modality": "high_throughput_compute",
        "objective": {"metric_key": "effective_gflops", "operator": ">=", "unit": "GFLOPS"},
    },
    "low_latency_video_pipeline": {
        "valid_templates": [
            "低时延视频推理任务，从 {src} 到 {dst}，处理 {frame_count} 帧，{resolution}，{fps}fps，{time}，{strategy_text}",
            "请部署视频AI推理 source={src} dest={dst}, frames={frame_count}, resolution={resolution}, fps={fps}, {time}, {strategy_text}",
            "从{src}到{dst}做视频链路随路计算，{resolution} 分辨率，{frame_count}帧，帧率 {fps}，{time}，{strategy_text}",
            "发起低时延视频业务，业务源节点 {src}，业务目的节点 {dst}，输入 {frame_count} 帧 {resolution} 视频，目标帧率 {fps}fps，{time}，{strategy_text}",
            "创建视频 AI 推理工单：从任务源节点 {src} 到任务目的节点 {dst}，处理 {resolution}/{fps}fps 的 {frame_count} 帧，{time}，{strategy_text}",
            "视频链路验收测试，source={src} destination={dst}，frames={frame_count}，分辨率 {resolution}，帧率 {fps}，{time}，{strategy_text}",
        ],
        "slots": [
            {"frame_count": 90, "resolution": "720p", "fps": 30},
            {"frame_count": 120, "resolution": "1080p", "fps": 30},
            {"frame_count": 180, "resolution": "1080p", "fps": 60},
        ],
        "modality": "low_latency_forwarding",
        "objective": {"metric_key": "frame_latency_p90_ms", "operator": "<=", "unit": "ms"},
    },
    "llm_text_generation": {
        "valid_templates": [
            "大模型文本生成任务，从 {src} 到 {dst}，prompt {prompt_tokens} tokens，生成 {max_new_tokens} tokens，batch {batch_size}，{time}，{strategy_text}",
            "请跑 LLM 文本生成 source={src} dest={dst}, prompt_tokens={prompt_tokens}, max_new_tokens={max_new_tokens}, batch_size={batch_size}, {time}, {strategy_text}",
            "从{src}到{dst}做文本模型训练/生成演示，输入 {prompt_tokens} tokens，输出 {max_new_tokens} tokens，批大小 {batch_size}，{time}，{strategy_text}",
            "提交文本生成业务，业务源节点为 {src}，业务目的节点为 {dst}，输入 {prompt_tokens} tokens，最多生成 {max_new_tokens} tokens，batch_size {batch_size}，{time}，{strategy_text}",
            "我要跑一个 LLM 推理任务，任务源节点 {src}、任务目的节点 {dst}，prompt 长度 {prompt_tokens} tokens，生成长度 {max_new_tokens} tokens，批大小 {batch_size}，{time}，{strategy_text}",
            "大模型文本业务验收：source={src} destination={dst}，prompt_tokens={prompt_tokens}，max_new_tokens={max_new_tokens}，batch={batch_size}，{time}，{strategy_text}",
        ],
        "slots": [
            {"prompt_tokens": 256, "max_new_tokens": 128, "batch_size": 1},
            {"prompt_tokens": 512, "max_new_tokens": 256, "batch_size": 2},
            {"prompt_tokens": 1024, "max_new_tokens": 512, "batch_size": 4},
        ],
        "modality": "llm_text",
        "objective": {"metric_key": "tokens_per_second", "operator": ">=", "unit": "tokens/s"},
    },
}

INCOMPLETE_TEMPLATES = [
    ("missing_source", "{task_name}，业务目的节点 {dst}，{profile_text}，{time}，{strategy_text}", ["source_name"]),
    ("missing_destination", "{task_name}，从业务源节点 {src} 出发，{profile_text}，{time}，{strategy_text}", ["destination_name"]),
    ("missing_time", "{task_name}，从业务源节点 {src} 到业务目的节点 {dst}，{profile_text}，{strategy_text}", ["business_start_time", "business_end_time"]),
    ("wrong_source_node", "{task_name}，从 unknown-node 到 {dst}，{profile_text}，{time}，{strategy_text}", ["source_name"]),
    ("wrong_destination_node", "{task_name}，从 {src} 到 ghost-node，{profile_text}，{time}，{strategy_text}", ["destination_name"]),
]

TASK_NAMES = {
    "high_throughput_matmul": "矩阵乘法任务",
    "low_latency_video_pipeline": "低时延视频推理任务",
    "llm_text_generation": "大模型文本生成任务",
}


def _node_pairs() -> list[tuple[str, str]]:
    return [(s, d) for s in NODES for d in NODES if s != d]


def _profile_text(task_type: str, profile: dict) -> str:
    if task_type == "high_throughput_matmul":
        return f"{profile['matrix_size']}阶矩阵，{profile['batch_count']}批"
    if task_type == "low_latency_video_pipeline":
        return f"{profile['frame_count']}帧，{profile['resolution']}，{profile['fps']}fps"
    return (
        f"prompt {profile['prompt_tokens']} tokens，"
        f"生成 {profile['max_new_tokens']} tokens，batch {profile['batch_size']}"
    )


def _expected(
    *,
    task_type: str,
    src: str | None,
    dst: str | None,
    profile: dict,
    strategy: str,
    parse_status: str,
    duration_minutes: int | None = None,
    missing_params: list[str] | None = None,
) -> dict:
    runtime_plan = {"routing_strategy": strategy}
    expected = {
        "task_type": task_type,
        "source_name": src,
        "destination_name": dst,
        "data_profile": dict(profile),
        "runtime_plan": runtime_plan,
        "business_objective": TASKS[task_type]["objective"],
        "parse_status": parse_status,
        "missing_params": missing_params or [],
    }
    if duration_minutes is not None:
        expected["expected_time"] = {
            "mode": "relative_duration",
            "duration_minutes": duration_minutes,
        }
    return expected


def _valid_row(task_type: str, index: int) -> dict:
    spec = TASKS[task_type]
    pairs = _node_pairs()
    src, dst = pairs[index % len(pairs)]
    profile = spec["slots"][index % len(spec["slots"])]
    strategy, strategy_text = STRATEGIES[index % len(STRATEGIES)]
    time, duration_minutes = TIME_PHRASES[index % len(TIME_PHRASES)]
    template = spec["valid_templates"][index % len(spec["valid_templates"])]
    utterance = template.format(
        src=src,
        dst=dst,
        time=time,
        strategy_text=strategy_text,
        **profile,
    )
    return {
        "case_type": "valid",
        "utterance": utterance,
        "expected": _expected(
            task_type=task_type,
            src=src,
            dst=dst,
            profile=profile,
            strategy=strategy,
            parse_status="valid",
            duration_minutes=duration_minutes,
        ),
    }


def _incomplete_row(task_type: str, index: int) -> dict:
    pairs = _node_pairs()
    src, dst = pairs[index % len(pairs)]
    profile = TASKS[task_type]["slots"][index % len(TASKS[task_type]["slots"])]
    strategy, strategy_text = STRATEGIES[index % len(STRATEGIES)]
    time, duration_minutes = TIME_PHRASES[index % len(TIME_PHRASES)]
    kind, template, missing = INCOMPLETE_TEMPLATES[index % len(INCOMPLETE_TEMPLATES)]
    utterance = template.format(
        task_name=TASK_NAMES[task_type],
        src=src,
        dst=dst,
        profile_text=_profile_text(task_type, profile),
        time=time,
        strategy_text=strategy_text,
    )
    return {
        "case_type": kind,
        "utterance": utterance,
        "expected": _expected(
            task_type=task_type,
            src=None if "source_name" in missing else src,
            dst=None if "destination_name" in missing else dst,
            profile=profile,
            strategy=strategy,
            parse_status="incomplete",
            duration_minutes=None if "business_start_time" in missing else duration_minutes,
            missing_params=missing,
        ),
    }


def generate_dataset(count: int) -> list[dict]:
    rows: list[dict] = []
    task_types = list(TASKS)
    valid_target = int(count * 0.7)

    for index in range(valid_target):
        task_type = task_types[index % len(task_types)]
        rows.append(_valid_row(task_type, index))

    for index in range(count - valid_target):
        task_type = task_types[index % len(task_types)]
        rows.append(_incomplete_row(task_type, index))

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=360)
    parser.add_argument("--output", default="datasets/intent_eval/multi_business.jsonl")
    args = parser.parse_args()

    rows = generate_dataset(args.count)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Generated {len(rows)} samples: {output}")


if __name__ == "__main__":
    main()
