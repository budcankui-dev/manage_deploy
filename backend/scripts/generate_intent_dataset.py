"""Generate the fixed multi-business intent evaluation dataset.

The dataset is deterministic by design: templates define expression styles,
slots define valid node/time/profile values, and labels are emitted from the
same slots.  This makes the evaluation explainable for acceptance review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.modality_catalog import default_objective_for_task_type, modality_for_task_type, task_name_for_task_type
from services.topology_catalog import INTENT_VALID_NODES


NODES = INTENT_VALID_NODES
STRATEGIES = [
    (
        "resource_guarantee",
        [
            "按默认策略",
            "没有特别偏好",
            "资源够用即可",
            "采用资源保障策略",
            "按系统默认选路",
            "只要资源满足就行",
            "不需要额外倾向",
            "正常调度即可",
        ],
    ),
    (
        "fastest_completion",
        [
            "希望性能更高",
            "尽快完成",
            "优先选择更快节点",
            "完成时间越短越好",
            "更看重处理速度",
            "吞吐性能优先",
            "希望少排队尽早跑完",
            "优先完成计算",
        ],
    ),
    (
        "low_latency_forwarding",
        [
            "采用低时延转发策略",
            "希望走低时延路由",
            "低时延策略优先",
            "优先保障端到端时延",
            "按低时延选路",
            "希望转发时延更低",
            "低延时链路优先",
            "尽量减少链路时延",
        ],
    ),
    (
        "load_balance",
        [
            "选择空闲节点负载均衡",
            "尽量避开高负载机器",
            "放在竞争少的节点上",
            "希望负载更均衡",
            "优先放到低负载节点",
            "避免和其他任务抢资源",
            "尽量均摊到空闲机器",
            "希望调度更平衡",
        ],
    ),
    (
        "cost_priority",
        [
            "希望成本更低",
            "成本优先省钱",
            "尽量少占资源",
            "优先低成本方案",
            "希望省钱一些",
            "希望费用低一些",
            "能省资源就省资源",
            "选择经济型方案",
        ],
    ),
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
        "profile_text_template": "{matrix_size}阶矩阵，{batch_count}批",
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
        "profile_text_template": "{frame_count}帧，{resolution}，{fps}fps",
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
        "profile_text_template": "prompt {prompt_tokens} tokens，生成 {max_new_tokens} tokens，batch {batch_size}",
    },
    "ai_model_training": {
        "valid_templates": [
            "智算中心模型训练任务，从 {src} 到 {dst}，训练 {sample_count} 条样本，{time}，{strategy_text}",
            "在智算中心跑文本模型训练：source={src} dest={dst}, samples={sample_count}, {time}, {strategy_text}",
            "提交模型训练业务，业务源节点 {src}，业务目的节点 {dst}，样本数 {sample_count}，{time}，{strategy_text}",
            "帮我安排一条训练类智算任务，源终端 {src}，目的终端 {dst}，数据集 {sample_count} 条样本，{time}，{strategy_text}",
            "需要做神经网络训练验证，从 {src} 发起到 {dst} 汇总，训练样本 {sample_count}，{time}，{strategy_text}",
        ],
        "slots": [
            {"sample_count": 5000},
            {"sample_count": 10000},
            {"sample_count": 20000},
        ],
        "profile_text_template": "训练 {sample_count} 条样本",
    },
    "distributed_storage_compute": {
        "valid_templates": [
            "分布式存算任务，从 {src} 到 {dst}，拉取 {data_size_gb}GB 数据就近计算，{time}，{strategy_text}",
            "视联网多节点存算业务 source={src} dest={dst}, data={data_size_gb}GB, {time}, {strategy_text}",
            "创建分布式存算工单，业务源节点 {src}，业务目的节点 {dst}，数据规模 {data_size_gb}GB，{time}，{strategy_text}",
            "我要把 {data_size_gb}GB 数据做存算协同处理，源终端 {src}，目的终端 {dst}，{time}，{strategy_text}",
            "多节点数据拉取后就近计算，从 {src} 到 {dst}，数据量 {data_size_gb}GB，{time}，{strategy_text}",
        ],
        "slots": [
            {"data_size_gb": 50},
            {"data_size_gb": 100},
            {"data_size_gb": 200},
        ],
        "profile_text_template": "{data_size_gb}GB 数据就近计算",
    },
    "massive_connection_collect": {
        "valid_templates": [
            "大规模连接采集任务，从 {src} 到 {dst}，接入 {connection_count} 个终端，{time}，{strategy_text}",
            "虚拟电厂海量接入 source={src} dest={dst}, {connection_count} 个设备连接，{time}, {strategy_text}",
            "创建海量连接业务，业务源节点 {src}，业务目的节点 {dst}，连接数 {connection_count}，{time}，{strategy_text}",
            "需要承载一批终端上报，源终端 {src}，目的终端 {dst}，大约 {connection_count} 个设备，{time}，{strategy_text}",
            "多用户大规模接入测试，从 {src} 到 {dst}，并发连接 {connection_count}，{time}，{strategy_text}",
        ],
        "slots": [
            {"connection_count": 5000},
            {"connection_count": 10000},
            {"connection_count": 20000},
        ],
        "profile_text_template": "接入 {connection_count} 个终端",
    },
    "deterministic_forwarding": {
        "valid_templates": [
            "确定性转发任务，从 {src} 到 {dst}，抖动不超过 {max_jitter_ms}ms，{time}，{strategy_text}",
            "配电线路巡检稳定转发 source={src} dest={dst}, jitter={max_jitter_ms}ms, {time}, {strategy_text}",
            "创建确定性转发业务，业务源节点 {src}，业务目的节点 {dst}，最大抖动 {max_jitter_ms}ms，{time}，{strategy_text}",
            "需要稳定时延链路，从源终端 {src} 到目的终端 {dst}，抖动上限 {max_jitter_ms}ms，{time}，{strategy_text}",
            "给巡检数据开一条确定性通道，{src} -> {dst}，jitter 控制在 {max_jitter_ms}ms，{time}，{strategy_text}",
        ],
        "slots": [
            {"max_jitter_ms": 3},
            {"max_jitter_ms": 5},
            {"max_jitter_ms": 8},
        ],
        "profile_text_template": "抖动不超过 {max_jitter_ms}ms",
    },
    "energy_efficient_edge_inference": {
        "valid_templates": [
            "高能效边缘推理任务，从 {src} 到 {dst}，处理 {frame_count} 帧，功耗 {power_budget_w}W，{time}，{strategy_text}",
            "输电线路巡检边缘计算 source={src} dest={dst}, frames={frame_count}, 功耗预算 {power_budget_w}W, {time}, {strategy_text}",
            "创建低功耗边缘推理业务，业务源节点 {src}，业务目的节点 {dst}，{frame_count}帧，{power_budget_w}W，{time}，{strategy_text}",
            "边缘侧做轻量识别，从 {src} 到 {dst}，抽取 {frame_count} 帧，功耗限制 {power_budget_w}W，{time}，{strategy_text}",
            "巡检图片就近推理，源终端 {src}，目的终端 {dst}，共 {frame_count} 帧，能耗预算 {power_budget_w}W，{time}，{strategy_text}",
        ],
        "slots": [
            {"frame_count": 90, "power_budget_w": 30},
            {"frame_count": 120, "power_budget_w": 50},
            {"frame_count": 180, "power_budget_w": 80},
        ],
        "profile_text_template": "{frame_count}帧，功耗 {power_budget_w}W",
    },
    "secure_transmission": {
        "valid_templates": [
            "高安全传输任务，从 {src} 到 {dst}，敏感数据加密回传，{time}，{strategy_text}",
            "低空远程作业安全传输 source={src} dest={dst}, 高安全加密链路, {time}, {strategy_text}",
            "创建高安全传输业务，业务源节点 {src}，业务目的节点 {dst}，安全级别 high，{time}，{strategy_text}",
            "需要安全回传低空作业数据，源终端 {src}，目的终端 {dst}，要求高安全传输，{time}，{strategy_text}",
            "敏感视频信息加密传输，从 {src} 到 {dst}，安全等级 high，{time}，{strategy_text}",
        ],
        "slots": [
            {"security_level": "high"},
            {"security_level": "high"},
            {"security_level": "high"},
        ],
        "profile_text_template": "高安全加密传输",
    },
}

INCOMPLETE_TEMPLATES = [
    ("missing_source", "{task_name}，业务目的节点 {dst}，{profile_text}，{time}，{strategy_text}", ["source_name"]),
    ("missing_destination", "{task_name}，从业务源节点 {src} 出发，{profile_text}，{time}，{strategy_text}", ["destination_name"]),
    ("missing_time", "{task_name}，从业务源节点 {src} 到业务目的节点 {dst}，{profile_text}，{strategy_text}", ["business_start_time", "business_end_time"]),
    ("wrong_source_node", "{task_name}，从 unknown-node 到 {dst}，{profile_text}，{time}，{strategy_text}", ["source_name"]),
    ("wrong_destination_node", "{task_name}，从 {src} 到 ghost-node，{profile_text}，{time}，{strategy_text}", ["destination_name"]),
]

TASK_NAMES = {task_type: task_name_for_task_type(task_type) for task_type in TASKS}


def _node_pairs() -> list[tuple[str, str]]:
    return [(s, d) for s in NODES for d in NODES if s != d]


def _strategy_for(index: int) -> tuple[str, str]:
    strategy, phrases = STRATEGIES[index % len(STRATEGIES)]
    return strategy, phrases[(index // len(STRATEGIES)) % len(phrases)]


def _profile_text(task_type: str, profile: dict) -> str:
    template = TASKS[task_type].get("profile_text_template")
    return template.format(**profile) if template else "固定业务参数"


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
        "modality": modality_for_task_type(task_type),
        "source_name": src,
        "destination_name": dst,
        "data_profile": dict(profile),
        "runtime_plan": runtime_plan,
        "business_objective": default_objective_for_task_type(task_type),
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
    strategy, strategy_text = _strategy_for(index)
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
    strategy, strategy_text = _strategy_for(index)
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

    for index, row in enumerate(rows):
        row["sample_id"] = f"sample-{index:04d}"

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
