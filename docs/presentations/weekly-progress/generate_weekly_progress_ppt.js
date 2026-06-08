let pptxgen;
try {
  pptxgen = require("pptxgenjs");
} catch {
  pptxgen = require("/Users/yanjia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pptxgenjs");
}
const fs = require("fs");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "manage-deploy";
pptx.company = "BUPT";
pptx.subject = "两项验收指标进度汇报";
pptx.title = "周五组会：两项指标测试进度汇报";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};
pptx.defineLayout({ name: "WIDE", width: 13.333, height: 7.5 });
pptx.layout = "WIDE";

const C = {
  navy: "071827",
  navy2: "0B2435",
  panel: "102C3D",
  panel2: "12384B",
  cyan: "3DDCFF",
  teal: "27D6A4",
  green: "62E29A",
  yellow: "FFD166",
  red: "FF6B6B",
  white: "F8FBFF",
  text: "D9E8F2",
  muted: "8EA8B8",
  line: "244B5E",
  dark: "04111C",
};

const W = 13.333;
const H = 7.5;
const font = "Microsoft YaHei";
const screenshots = {
  intentDashboard: "docs/presentations/weekly-progress/screenshots/intent-evaluation-dashboard.png",
  intentSamples: "docs/presentations/weekly-progress/screenshots/intent-evaluation-samples.png",
  benchmark: "docs/presentations/weekly-progress/screenshots/benchmark-page.png",
  businessDetail: "docs/presentations/weekly-progress/screenshots/business-task-detail.png",
};

function addBg(slide, section = "进度汇报") {
  slide.background = { color: C.navy };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: W,
    h: H,
    fill: { color: C.navy },
    line: { color: C.navy },
  });
  slide.addShape(pptx.ShapeType.arc, {
    x: 10.55,
    y: -1.0,
    w: 3.9,
    h: 3.9,
    adjustPoint: 0.15,
    line: { color: C.cyan, transparency: 70, width: 1.2 },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 0.12,
    h: H,
    fill: { color: C.teal },
    line: { color: C.teal },
  });
  slide.addText(section, {
    x: 0.55,
    y: 0.25,
    w: 4.5,
    h: 0.25,
    fontFace: font,
    fontSize: 8.5,
    color: C.cyan,
    bold: true,
    charSpace: 1.5,
  });
}

function addFooter(slide, page) {
  slide.addShape(pptx.ShapeType.line, {
    x: 0.55,
    y: 7.05,
    w: 11.75,
    h: 0,
    line: { color: C.line, transparency: 30, width: 0.8 },
  });
  slide.addText("智联计算系统 · 两项验收指标进度", {
    x: 0.55,
    y: 7.12,
    w: 5.6,
    h: 0.22,
    fontFace: font,
    fontSize: 7.5,
    color: C.muted,
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 12.35,
    y: 7.02,
    w: 0.45,
    h: 0.32,
    rectRadius: 0.08,
    fill: { color: C.panel2 },
    line: { color: C.line, transparency: 40 },
  });
  slide.addText(String(page).padStart(2, "0"), {
    x: 12.35,
    y: 7.07,
    w: 0.45,
    h: 0.2,
    fontFace: font,
    fontSize: 8.5,
    color: C.white,
    align: "center",
    bold: true,
  });
}

function title(slide, text, sub) {
  slide.addText(text, {
    x: 0.65,
    y: 0.72,
    w: 8.8,
    h: 0.48,
    fontFace: font,
    fontSize: 26,
    color: C.white,
    bold: true,
    margin: 0,
    fit: "shrink",
  });
  if (sub) {
    slide.addText(sub, {
      x: 0.68,
      y: 1.25,
      w: 10.5,
      h: 0.32,
      fontFace: font,
      fontSize: 10.5,
      color: C.muted,
      margin: 0,
    });
  }
}

function card(slide, x, y, w, h, opts = {}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.12,
    fill: { color: opts.fill || C.panel, transparency: opts.transparency || 0 },
    line: { color: opts.line || C.line, transparency: 10, width: 0.8 },
  });
}

function tag(slide, text, x, y, color = C.teal, w = 1.28) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h: 0.3,
    rectRadius: 0.08,
    fill: { color, transparency: 8 },
    line: { color, transparency: 15, width: 0.6 },
  });
  slide.addText(text, {
    x,
    y: y + 0.055,
    w,
    h: 0.18,
    fontFace: font,
    fontSize: 7.5,
    color: C.dark,
    align: "center",
    bold: true,
  });
}

function metricCard(slide, x, y, w, label, value, hint, color = C.green) {
  card(slide, x, y, w, 1.28, { fill: C.panel2 });
  slide.addText(label, {
    x: x + 0.25,
    y: y + 0.2,
    w: w - 0.5,
    h: 0.23,
    fontFace: font,
    fontSize: 8,
    color: C.muted,
  });
  slide.addText(value, {
    x: x + 0.25,
    y: y + 0.45,
    w: w - 0.5,
    h: 0.44,
    fontFace: font,
    fontSize: 22,
    color,
    bold: true,
    fit: "shrink",
  });
  slide.addText(hint, {
    x: x + 0.25,
    y: y + 0.93,
    w: w - 0.5,
    h: 0.2,
    fontFace: font,
    fontSize: 7.6,
    color: C.text,
    fit: "shrink",
  });
}

function bullet(slide, lines, x, y, w, opts = {}) {
  slide.addText(
    lines.map((line) => ({
      text: line,
      options: {
        bullet: { type: "bullet" },
        breakLine: true,
      },
    })),
    {
      x,
      y,
      w,
      h: opts.h || 1.8,
      fontFace: font,
      fontSize: opts.fontSize || 12,
      color: opts.color || C.text,
      breakLine: false,
      paraSpaceAfterPt: 7,
      fit: "shrink",
    }
  );
}

function progress(slide, x, y, w, h, ratio, color, label, valueText) {
  slide.addText(label, {
    x,
    y: y - 0.28,
    w,
    h: 0.18,
    fontFace: font,
    fontSize: 8,
    color: C.muted,
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    fill: { color: C.dark, transparency: 15 },
    line: { color: C.line, transparency: 40 },
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w: Math.max(0.08, w * Math.min(1, Math.max(0, ratio))),
    h,
    rectRadius: 0.08,
    fill: { color, transparency: 0 },
    line: { color, transparency: 100 },
  });
  slide.addText(valueText, {
    x,
    y: y + h + 0.05,
    w,
    h: 0.2,
    fontFace: font,
    fontSize: 8.5,
    color: C.white,
    bold: true,
    align: "right",
  });
}

function miniBar(slide, x, y, w, label, value, max, color) {
  slide.addText(label, {
    x,
    y,
    w: 2.0,
    h: 0.22,
    fontFace: font,
    fontSize: 8.2,
    color: C.text,
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: x + 2.1,
    y: y + 0.04,
    w,
    h: 0.16,
    fill: { color: C.dark, transparency: 20 },
    line: { color: C.dark, transparency: 100 },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: x + 2.1,
    y: y + 0.04,
    w: (w * value) / max,
    h: 0.16,
    fill: { color, transparency: 0 },
    line: { color, transparency: 100 },
  });
  slide.addText(String(value), {
    x: x + 2.1 + w + 0.12,
    y: y - 0.01,
    w: 0.42,
    h: 0.2,
    fontFace: font,
    fontSize: 8,
    color: C.white,
    bold: true,
  });
}

function flowNode(slide, x, y, w, text, color = C.panel2) {
  card(slide, x, y, w, 0.58, { fill: color, line: C.line });
  slide.addText(text, {
    x,
    y: y + 0.18,
    w,
    h: 0.18,
    fontFace: font,
    fontSize: 8.8,
    color: C.white,
    bold: true,
    align: "center",
  });
}

function arrow(slide, x1, y1, x2, y2, color = C.cyan) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: { color, width: 1.4, beginArrowType: "none", endArrowType: "triangle" },
  });
}

function pngSize(file) {
  const buf = fs.readFileSync(file);
  return {
    width: buf.readUInt32BE(16),
    height: buf.readUInt32BE(20),
  };
}

function screenshotFrame(slide, file, x, y, w, h, caption) {
  card(slide, x, y, w, h, { fill: "F6FAFF", line: C.cyan });
  if (!fs.existsSync(file)) {
    slide.addText(`缺少截图：${file}`, {
      x: x + 0.22,
      y: y + 0.32,
      w: w - 0.44,
      h: 0.35,
      fontFace: font,
      fontSize: 9,
      color: C.red,
      fit: "shrink",
    });
    return;
  }

  const pad = 0.1;
  const size = pngSize(file);
  const boxW = w - pad * 2;
  const boxH = h - pad * 2 - (caption ? 0.28 : 0);
  let imgW = boxW;
  let imgH = imgW * (size.height / size.width);
  if (imgH > boxH) {
    imgH = boxH;
    imgW = imgH * (size.width / size.height);
  }
  slide.addImage({
    path: file,
    x: x + pad + (boxW - imgW) / 2,
    y: y + pad,
    w: imgW,
    h: imgH,
  });

  if (caption) {
    slide.addShape(pptx.ShapeType.rect, {
      x: x + pad,
      y: y + h - 0.36,
      w: w - pad * 2,
      h: 0.24,
      fill: { color: "EAF2FA", transparency: 0 },
      line: { color: "EAF2FA", transparency: 100 },
    });
    slide.addText(caption, {
      x: x + 0.2,
      y: y + h - 0.32,
      w: w - 0.4,
      h: 0.16,
      fontFace: font,
      fontSize: 7.2,
      color: C.navy2,
      align: "center",
      fit: "shrink",
    });
  }
}

// Slide 1
{
  const slide = pptx.addSlide();
  addBg(slide, "周五组会");
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.7,
    y: 1.25,
    w: 11.9,
    h: 4.6,
    rectRadius: 0.18,
    fill: { color: C.panel, transparency: 5 },
    line: { color: C.line, transparency: 15 },
  });
  tag(slide, "进度汇报", 0.98, 1.62, C.cyan, 1.0);
  slide.addText("两项验收指标测试进度汇报", {
    x: 0.98,
    y: 2.06,
    w: 8.0,
    h: 0.62,
    fontFace: font,
    fontSize: 32,
    color: C.white,
    bold: true,
    margin: 0,
  });
  slide.addText("意图解析参数提取准确率  |  业务目标成功率", {
    x: 1.0,
    y: 2.86,
    w: 8.4,
    h: 0.32,
    fontFace: font,
    fontSize: 16,
    color: C.cyan,
    bold: true,
  });
  slide.addText("围绕任务书验收口径，汇报当前定义、测试方案、已完成进度、问题与下周计划。", {
    x: 1.0,
    y: 3.35,
    w: 8.3,
    h: 0.45,
    fontFace: font,
    fontSize: 12,
    color: C.text,
    fit: "shrink",
  });
  metricCard(slide, 9.25, 1.68, 2.72, "指标一", "≥90%", "意图参数提取准确率", C.green);
  metricCard(slide, 9.25, 3.22, 2.72, "指标二", "≥90%", "业务目标成功率", C.green);
  slide.addText("2026-06-05", {
    x: 1.0,
    y: 5.05,
    w: 2.5,
    h: 0.28,
    fontFace: font,
    fontSize: 10,
    color: C.muted,
  });
  addFooter(slide, 1);
}

// Slide 2
{
  const slide = pptx.addSlide();
  addBg(slide, "一页结论");
  title(slide, "总体进度判断", "两个指标的测试链路已经跑通；当前重点是正式留档、口径核对和外部路由联调。");
  metricCard(slide, 0.72, 1.85, 3.7, "意图解析参数提取准确率", "360/360", "真实大模型 Batch 评测记录，准确率 100%", C.green);
  metricCard(slide, 4.82, 1.85, 3.7, "业务目标成功率", "15/15", "当前远端轮次可查询样本全部达标，成功率 100%", C.yellow);
  metricCard(slide, 8.92, 1.85, 3.7, "正式验收目标", "≥90%", "30 个可评价任务中至少 27 个达标", C.cyan);
  card(slide, 0.72, 3.7, 11.9, 2.45, { fill: C.panel });
  slide.addText("当前可以汇报的结论", {
    x: 1.02,
    y: 3.98,
    w: 3.2,
    h: 0.28,
    fontFace: font,
    fontSize: 14,
    color: C.white,
    bold: true,
  });
  bullet(slide, [
    "意图解析：数据集构造、规则兜底、真实 Qwen Batch 评测、前端评测看板均已具备。",
    "业务目标：矩阵乘法 source -> compute -> sink 部署、GPU 分配、指标上报与 baseline 判定闭环已跑通。",
    "当前风险：业务目标正式 30 样本留档口径需最后核对；外部路由系统 placements/GPU 回写需联调。",
  ], 1.02, 4.38, 11.0, { h: 1.25, fontSize: 12 });
  progress(slide, 1.02, 5.82, 4.9, 0.22, 1.0, C.green, "意图解析", "100% / 目标 90%");
  progress(slide, 6.35, 5.82, 4.9, 0.22, 1.0, C.yellow, "业务目标当前可评价样本", "100% / 样本数待补齐核对");
  addFooter(slide, 2);
}

// Slide 3
{
  const slide = pptx.addSlide();
  addBg(slide, "指标定义");
  title(slide, "指标一：意图解析参数提取准确率", "验证系统能否把用户自然语言稳定解析为结构化业务工单参数。");
  card(slide, 0.75, 1.78, 5.7, 4.45, { fill: C.panel });
  slide.addText("验收口径", {
    x: 1.05,
    y: 2.08,
    w: 2.0,
    h: 0.3,
    fontFace: font,
    fontSize: 15,
    color: C.white,
    bold: true,
  });
  slide.addText("准确率 = 全字段正确样本数 / 总样本数 × 100%", {
    x: 1.05,
    y: 2.55,
    w: 4.9,
    h: 0.38,
    fontFace: font,
    fontSize: 16,
    color: C.cyan,
    bold: true,
    fit: "shrink",
  });
  bullet(slide, [
    "任务类型、源节点、目的节点精确匹配",
    "开始/结束时间按持续时长校验",
    "业务参数 profile 与路由策略精确匹配",
    "缺字段/错误节点样本需正确判定 incomplete",
  ], 1.05, 3.22, 4.9, { h: 1.45, fontSize: 11.3 });
  card(slide, 6.82, 1.78, 5.75, 4.45, { fill: C.panel2 });
  slide.addText("解析后输出字段", {
    x: 7.1,
    y: 2.08,
    w: 2.2,
    h: 0.28,
    fontFace: font,
    fontSize: 15,
    color: C.white,
    bold: true,
  });
  const fields = [
    ["task_type", "业务类型"],
    ["source_name", "源节点"],
    ["destination_name", "目的节点"],
    ["business_start/end_time", "时间窗口"],
    ["data_profile", "业务参数"],
    ["runtime_plan.routing_strategy", "路由策略"],
    ["parse_status", "完整性状态"],
  ];
  fields.forEach((row, idx) => {
    const y = 2.58 + idx * 0.43;
    tag(slide, row[0], 7.12, y, idx % 2 ? C.cyan : C.teal, 2.62);
    slide.addText(row[1], {
      x: 9.95,
      y: y + 0.06,
      w: 1.8,
      h: 0.18,
      fontFace: font,
      fontSize: 8.4,
      color: C.text,
    });
  });
  addFooter(slide, 3);
}

// Slide 4
{
  const slide = pptx.addSlide();
  addBg(slide, "指标一进度");
  title(slide, "意图解析：已跑通真实大模型 Batch 评测", "固定 360 条多业务数据集，覆盖有效输入、缺字段、错误节点和三类业务模态。");
  metricCard(slide, 0.75, 1.82, 2.7, "固定数据集", "360", "multi_business.jsonl", C.cyan);
  metricCard(slide, 3.72, 1.82, 2.7, "真实 LLM", "Qwen", "qwen3.7-plus Batch", C.green);
  metricCard(slide, 6.7, 1.82, 2.7, "准确率记录", "100%", "360/360 全字段匹配", C.green);
  metricCard(slide, 9.68, 1.82, 2.7, "目标", "≥90%", "通过验收阈值", C.cyan);
  card(slide, 0.75, 3.55, 5.8, 2.55, { fill: C.panel });
  slide.addText("数据集分布", {
    x: 1.05,
    y: 3.82,
    w: 1.8,
    h: 0.25,
    fontFace: font,
    fontSize: 14,
    color: C.white,
    bold: true,
  });
  miniBar(slide, 1.05, 4.25, 2.25, "valid", 251, 251, C.green);
  miniBar(slide, 1.05, 4.62, 2.25, "missing_source", 22, 251, C.cyan);
  miniBar(slide, 1.05, 4.99, 2.25, "missing_destination", 22, 251, C.cyan);
  miniBar(slide, 1.05, 5.36, 2.25, "missing_time", 22, 251, C.yellow);
  miniBar(slide, 1.05, 5.73, 2.25, "wrong_node", 43, 251, C.red);
  card(slide, 6.85, 3.55, 5.55, 2.55, { fill: C.panel2 });
  slide.addText("已完成能力", {
    x: 7.15,
    y: 3.82,
    w: 1.8,
    h: 0.25,
    fontFace: font,
    fontSize: 14,
    color: C.white,
    bold: true,
  });
  bullet(slide, [
    "模板 + 槽位自动扩展，数据集可复现",
    "支持规则兜底评测与真实大模型 Batch 评测",
    "前端页面支持样本明细、成功/失败样本和文件下载",
    "单条解析检测可用于演示和排错",
  ], 7.12, 4.24, 4.75, { h: 1.25, fontSize: 10.8 });
  addFooter(slide, 4);
}

// Slide 5
{
  const slide = pptx.addSlide();
  addBg(slide, "系统截图");
  title(slide, "系统截图：意图解析评测看板", "用页面截图证明评测流程、Batch 结果、样本明细和字段判定均已可视化。");
  screenshotFrame(
    slide,
    screenshots.intentDashboard,
    0.72,
    1.72,
    5.85,
    4.8,
    "评测看板：360 条固定数据集，真实 Qwen Batch 与规则兜底结果"
  );
  screenshotFrame(
    slide,
    screenshots.intentSamples,
    6.78,
    1.72,
    5.85,
    4.8,
    "样本明细：单条输入、解析结果、字段级期望值/解析值对比"
  );
  slide.addText("汇报时可强调：评测不是只看一个总分，而是能下钻到每个样本，检查缺字段、错误节点、时间窗口和业务参数是否按规则判定。", {
    x: 0.85,
    y: 6.72,
    w: 11.35,
    h: 0.25,
    fontFace: font,
    fontSize: 10.5,
    color: C.cyan,
    bold: true,
    fit: "shrink",
  });
  addFooter(slide, 5);
}

// Slide 6
{
  const slide = pptx.addSlide();
  addBg(slide, "指标定义");
  title(slide, "指标二：业务目标成功率", "验证路由放置后的业务容器是否真实运行，并达到节点历史基准能力。");
  card(slide, 0.75, 1.78, 5.65, 4.6, { fill: C.panel });
  slide.addText("验收口径", {
    x: 1.05,
    y: 2.08,
    w: 2.0,
    h: 0.28,
    fontFace: font,
    fontSize: 15,
    color: C.white,
    bold: true,
  });
  slide.addText("业务目标成功率 = 达标工单数 / 已完成可评价工单数 × 100%", {
    x: 1.05,
    y: 2.52,
    w: 4.85,
    h: 0.48,
    fontFace: font,
    fontSize: 15,
    color: C.cyan,
    bold: true,
    fit: "shrink",
  });
  slide.addText("矩阵计算业务目标", {
    x: 1.05,
    y: 3.3,
    w: 2.2,
    h: 0.25,
    fontFace: font,
    fontSize: 12,
    color: C.yellow,
    bold: true,
  });
  bullet(slide, [
    "过程性指标：effective_gflops",
    "达标条件：actual ≥ baseline × 0.8",
    "采集方式：compute 持续采样，sink 汇总上报",
    "不以绝对完成时间作为业务目标，避免输入规模差异干扰",
  ], 1.05, 3.72, 4.85, { h: 1.35, fontSize: 10.8 });
  card(slide, 6.82, 1.78, 5.75, 4.6, { fill: C.panel2 });
  slide.addText("随路计算数据流", {
    x: 7.12,
    y: 2.08,
    w: 2.4,
    h: 0.28,
    fontFace: font,
    fontSize: 15,
    color: C.white,
    bold: true,
  });
  flowNode(slide, 7.15, 2.75, 1.5, "source", C.panel);
  flowNode(slide, 9.02, 2.75, 1.55, "compute", C.panel);
  flowNode(slide, 10.95, 2.75, 1.35, "sink", C.panel);
  arrow(slide, 8.65, 3.04, 9.0, 3.04);
  arrow(slide, 10.57, 3.04, 10.93, 3.04);
  bullet(slide, [
    "外部路由返回 source / compute / sink placements",
    "compute 节点携带 GPU 编号，注入容器环境变量",
    "Task Manager 根据 compute 节点 baseline 判定达标",
  ], 7.12, 4.0, 4.95, { h: 1.05, fontSize: 10.8 });
  addFooter(slide, 6);
}

// Slide 7
{
  const slide = pptx.addSlide();
  addBg(slide, "指标二进度");
  title(slide, "业务目标：矩阵乘法闭环已在四节点环境跑通", "当前重点是把正式 30 任务样本、截图和 JSON 报告统一留档。");
  metricCard(slide, 0.75, 1.75, 2.72, "测试拓扑", "4 节点", "admin-server + compute-1/2/3", C.cyan);
  metricCard(slide, 3.75, 1.75, 2.72, "当前可查询", "15/15", "已评价样本全部达标", C.yellow);
  metricCard(slide, 6.75, 1.75, 2.72, "成功率", "100%", "目标阈值 ≥90%", C.green);
  metricCard(slide, 9.75, 1.75, 2.72, "证据链", "GPU", "显示节点/GPU/后端/指标", C.cyan);
  card(slide, 0.75, 3.45, 5.78, 2.58, { fill: C.panel });
  slide.addText("已完成链路", {
    x: 1.05,
    y: 3.73,
    w: 2.0,
    h: 0.25,
    fontFace: font,
    fontSize: 14,
    color: C.white,
    bold: true,
  });
  bullet(slide, [
    "远端 Node Agent 控制容器创建、启动、停止与清理",
    "mock 路由可返回 compute GPU 设备号",
    "worker 上报 backend=cupy_gpu、gpu_device、effective_gflops",
    "业务工单中心可筛选 benchmark_run_id 并查看详情",
  ], 1.05, 4.16, 4.85, { h: 1.28, fontSize: 10.6 });
  card(slide, 6.85, 3.45, 5.58, 2.58, { fill: C.panel2 });
  slide.addText("谨慎说明", {
    x: 7.15,
    y: 3.73,
    w: 2.0,
    h: 0.25,
    fontFace: font,
    fontSize: 14,
    color: C.yellow,
    bold: true,
  });
  bullet(slide, [
    "当前接口返回：count=30，evaluated=15，success=15",
    "前序文档记录过 30/30，正式汇报前需重新核对口径",
    "正式留档建议补齐 Step1/Step3/详情/Step4 截图",
  ], 7.15, 4.18, 4.8, { h: 1.05, fontSize: 10.8 });
  addFooter(slide, 7);
}

// Slide 8
{
  const slide = pptx.addSlide();
  addBg(slide, "系统截图");
  title(slide, "系统截图：业务目标验收与工单证据链", "远端 admin-server 页面截图，展示基线、压测参数、工单详情、原始 JSON 和业务目标。");
  screenshotFrame(
    slide,
    screenshots.benchmark,
    0.72,
    1.7,
    5.85,
    4.85,
    "业务目标验收页：节点基线、批量压测参数、当前轮次"
  );
  screenshotFrame(
    slide,
    screenshots.businessDetail,
    6.78,
    1.7,
    5.85,
    4.85,
    "工单详情抽屉：业务输入、原始 JSON、运行计划与目标口径"
  );
  slide.addText("汇报时可强调：每个验收样本都能从成功率统计追溯到具体工单和部署记录，后续外部路由回调 placements/GPU 后仍复用同一条证据链。", {
    x: 0.85,
    y: 6.72,
    w: 11.35,
    h: 0.25,
    fontFace: font,
    fontSize: 10.5,
    color: C.cyan,
    bold: true,
    fit: "shrink",
  });
  addFooter(slide, 8);
}

// Slide 9
{
  const slide = pptx.addSlide();
  addBg(slide, "系统证据链");
  title(slide, "为什么能证明“不是静态造数”", "每个达标样本都能回溯到工单、路由放置、容器实例、GPU 和业务指标。");
  const steps = [
    ["用户/测试输入", "自然语言或批量压测参数"],
    ["DAG 生成", "source -> compute -> sink"],
    ["路由放置", "节点 + GPU 编号"],
    ["容器部署", "Node Agent + Docker"],
    ["指标上报", "effective_gflops / 结果 JSON"],
    ["成功率统计", "达标数 / 可评价任务数"],
  ];
  steps.forEach((s, idx) => {
    const x = 0.8 + (idx % 3) * 4.05;
    const y = 2.0 + Math.floor(idx / 3) * 1.75;
    card(slide, x, y, 3.25, 1.05, { fill: idx % 2 ? C.panel2 : C.panel });
    slide.addText(`${idx + 1}. ${s[0]}`, {
      x: x + 0.25,
      y: y + 0.22,
      w: 2.75,
      h: 0.25,
      fontFace: font,
      fontSize: 12,
      color: C.white,
      bold: true,
    });
    slide.addText(s[1], {
      x: x + 0.25,
      y: y + 0.58,
      w: 2.75,
      h: 0.2,
      fontFace: font,
      fontSize: 8.5,
      color: C.muted,
      fit: "shrink",
    });
    if (idx % 3 !== 2) {
      arrow(slide, x + 3.28, y + 0.52, x + 3.86, y + 0.52, C.cyan);
    }
  });
  arrow(slide, 11.02, 3.08, 11.02, 3.68, C.cyan);
  slide.addText("验收页面与业务工单中心已经围绕这条证据链补齐展示：工单筛选、详情抽屉、结果 JSON、GPU 设备、执行后端、清理实例保留工单。", {
    x: 0.95,
    y: 5.78,
    w: 11.2,
    h: 0.4,
    fontFace: font,
    fontSize: 12,
    color: C.text,
    bold: true,
    fit: "shrink",
  });
  addFooter(slide, 9);
}

// Slide 10
{
  const slide = pptx.addSlide();
  addBg(slide, "问题与计划");
  title(slide, "当前问题与预计解决时间", "按组会要求，问题以表格方式呈现，并给出务实的后续时间预估。");
  const cols = [0.75, 3.8, 7.6, 10.55];
  const widths = [2.85, 3.55, 2.72, 1.72];
  const y0 = 1.85;
  const rowH = 0.72;
  const headers = ["问题", "原因", "下一步动作", "预计时间"];
  headers.forEach((h, idx) => {
    slide.addShape(pptx.ShapeType.rect, {
      x: cols[idx],
      y: y0,
      w: widths[idx],
      h: 0.45,
      fill: { color: C.teal },
      line: { color: C.teal },
    });
    slide.addText(h, {
      x: cols[idx] + 0.08,
      y: y0 + 0.13,
      w: widths[idx] - 0.16,
      h: 0.16,
      fontFace: font,
      fontSize: 8.5,
      color: C.dark,
      bold: true,
      align: "center",
    });
  });
  const rows = [
    ["业务目标 30 样本留档口径需核对", "远端当前查询到 evaluated=15，需确认历史 30/30 记录与当前库表状态", "重新跑或补齐正式 30 任务，并保存截图/API 报告", "本周内"],
    ["外部路由系统未正式联调", "目前验收页使用 mock 路由，只证明部署与评价闭环", "对接 DAG 输入、placements/GPU 回写和部署触发", "1 周"],
    ["视频业务仅扩展演示", "worker 和页面入口已具备，但未做四节点 30 任务正式压测", "构建镜像，复用成功率流程跑视频任务", "1-2 周"],
    ["测试方案材料需整理", "系统功能已迭代，正式文档需同步截图、命令和指标口径", "形成测试方案 PDF/PPT 附录与演示流程", "本周内"],
  ];
  rows.forEach((row, ridx) => {
    const y = y0 + 0.45 + ridx * rowH;
    row.forEach((cell, idx) => {
      slide.addShape(pptx.ShapeType.rect, {
        x: cols[idx],
        y,
        w: widths[idx],
        h: rowH,
        fill: { color: ridx % 2 ? C.panel2 : C.panel, transparency: 0 },
        line: { color: C.line, transparency: 20, width: 0.5 },
      });
      slide.addText(cell, {
        x: cols[idx] + 0.1,
        y: y + 0.12,
        w: widths[idx] - 0.2,
        h: rowH - 0.18,
        fontFace: font,
        fontSize: 8.2,
        color: idx === 3 ? C.yellow : C.text,
        fit: "shrink",
        valign: "mid",
      });
    });
  });
  addFooter(slide, 10);
}

// Slide 11
{
  const slide = pptx.addSlide();
  addBg(slide, "下周计划");
  title(slide, "下一步计划与汇报收口", "目标是把“已跑通”收敛为“可复现、可截图、可专家复核”的正式材料。");
  const plan = [
    ["01", "确认指标口径", "意图解析报告、业务目标 30 样本统计、失败/缺失样本口径统一。"],
    ["02", "补齐正式留档", "保存前端截图、API JSON、Batch 输入输出、benchmark_run_id。"],
    ["03", "外部路由联调", "对接 DAG 资源需求与 placements/GPU 回写，跑通部署触发。"],
    ["04", "扩展演示准备", "视频 AI 推理业务作为多模态扩展，视时间做 30 任务压测。"],
  ];
  plan.forEach((item, idx) => {
    const x = idx < 2 ? 0.85 : 6.75;
    const y = idx % 2 === 0 ? 1.95 : 4.0;
    card(slide, x, y, 5.55, 1.46, { fill: idx % 2 ? C.panel2 : C.panel });
    tag(slide, item[0], x + 0.25, y + 0.25, idx < 2 ? C.teal : C.cyan, 0.55);
    slide.addText(item[1], {
      x: x + 0.95,
      y: y + 0.27,
      w: 2.9,
      h: 0.28,
      fontFace: font,
      fontSize: 14,
      color: C.white,
      bold: true,
    });
    slide.addText(item[2], {
      x: x + 0.95,
      y: y + 0.7,
      w: 4.1,
      h: 0.35,
      fontFace: font,
      fontSize: 10,
      color: C.text,
      fit: "shrink",
    });
  });
  slide.addText("组会表达建议：先讲结论，再讲两个指标的定义和证据，最后主动说明剩余问题与时间表。控制在 8-10 分钟内。", {
    x: 0.95,
    y: 6.05,
    w: 11.1,
    h: 0.35,
    fontFace: font,
    fontSize: 12,
    color: C.cyan,
    bold: true,
    fit: "shrink",
  });
  addFooter(slide, 11);
}

pptx.writeFile({
  fileName: "docs/presentations/weekly-progress/周五组会_两项指标进度汇报_2026-06-05.pptx",
});
