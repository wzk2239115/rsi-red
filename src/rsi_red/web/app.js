let data,
  selected = null,
  cut = Infinity;
const $ = (id) => document.getElementById(id),
  NS = "http://www.w3.org/2000/svg";
function element(tag, text, parent, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  parent.appendChild(e);
  return e;
}
function svg(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
}
function field(title, text) {
  element("h3", title, $("detail"));
  element("p", text, $("detail"));
}
function details(type, item) {
  selected = { type, item };
  const d = $("detail");
  d.replaceChildren();
  element(
    "small",
    type === "bridge"
      ? item.id
      : type === "recipe"
        ? "RESEARCH RECIPE"
        : "RESEARCH ISLAND",
    d,
  );
  element("h2", item.name || item.title, d);
  if (type === "bridge") {
    element("span", item.status, d, "pill");
    field("研究假设", item.hypothesis);
    field("迁移的方法", item.method);
    field("证据链", item.evidence);
    field("贡献边界", item.boundary);
    field("下一步 · 对照实验", item.next);
  } else if (type === "recipe") {
    element("span", item.state + " · agent 上报", d, "pill");
    field("研究假设", item.hypothesis);
    field("方法", item.method);
    field("数据版本", item.datasets.join(" · ") || "未指定");
    field("父模型", item.parents.join(" · ") || "未指定");
    field("关键参数", JSON.stringify(item.parameters));
    field(
      "关联任务 · 服务记录",
      item.jobs.map((j) => j.id + " · " + j.state).join("；") ||
        "尚未提交计算任务",
    );
    field(
      "最近观察 · 未验证结论",
      item.history.at(-1)?.observation || "暂无上报",
    );
  } else {
    const events = item.events.filter((e) => e.time <= cut);
    element(
      "span",
      data.demo ? "演示工作区" : "研究项目 · 当前快照",
      d,
      "pill",
    );
    field("项目 ID", item.id);
    field(
      "当前任务",
      `${item.jobs.length} 项任务（当前状态；不随历史时间回退）`,
    );
    field(
      "研究记录",
      events.length
        ? `${events.length} 条事件；最近：${events.at(-1).type}`
        : "所选时刻暂无记录",
    );
    field("假设与方法桥", "当前未接入相应研究层接口。");
    for (const j of item.jobs)
      element("p", `${j.id.slice(0, 26)} · ${j.state}`, d);
  }
}
function renderAudits() {
  const states = {pending: "等待检查", running: "检查中", blocked: "已证实问题 · 禁止提交",
    incomplete: "检查不完整 · 禁止提交", checks_passed: "所选检查通过", needs_review: "待复核"};
  $("auditCases").replaceChildren();
  $("auditFeedback").replaceChildren();
  for (const audit of data.audits || []) {
    const card = element("article", undefined, $("auditCases"), "gpu-card");
    element("small", "DEVELOPMENT INTEGRITY", card);
    element("h3", states[audit.state] || audit.state, card);
    element("p", audit.model_id, card);
    for (const check of audit.checks) element("p", `${check.name} · ${check.state}`, card);
  }
  if (!data.audits?.length) element("p", "尚无审核案例；未执行检查不代表模型通过审核。", $("auditCases"), "empty");
  for (const item of data.audit_feedback || []) {
    const card = element("article", undefined, $("auditFeedback"), "gpu-card");
    const label = item.status === "suspected" ? "审核员疑点 · 未证实" : item.status === "confirmed_issue" ? "可信检查 · 已证实问题" : item.status === "incomplete" ? "覆盖不足" : "所选检查通过";
    element("h3", label, card);
    const reasons = {independent_review_requested: "审核员请求独立复核", selected_checks_blocked: "评分与保存输出不一致", selected_checks_incomplete: "必需检查尚未覆盖", selected_checks_checks_passed: "已完成所选检查"};
    const advice = {suspected: "请独立复核，不根据反馈反推考题。", confirmed_issue: "检查评分逻辑，由操作者修复后按冻结协议重新评测。", incomplete: "请操作者配置缺失检查器后重试。", checks_passed: "通过范围仅限已执行检查，继续保留研究证据。"};
    element("p", reasons[item.reason] || item.reason, card);
    element("p", advice[item.status] || item.recommendation, card);
    for (const peer of item.recipients) element("p", `${peer} · ${item.acknowledged_by.includes(peer) ? "已确认阅读" : "待确认（不代表已投递到会话）"}`, card);
    element("small", `CLI 确认：rsi audit ack ${item.id}`, card);
  }
}
function renderMonitoring() {
  $("agents").replaceChildren();
  for (const peer of data.agents || []) {
    const card = element("article", undefined, $("agents"), "agent-card");
    element(
      "small",
      data.demo ? "PEER SESSION / DEMO" : "RESEARCH ID / NO SESSION HEARTBEAT",
      card,
    );
    element("h2", peer.id, card);
    const active = peer.recipes.filter((r) =>
      ["planned", "trying"].includes(r.state),
    );
    element(
      "p",
      `${active.length} 个在尝试的 recipe · ${peer.requested_gpus} 张 GPU 申请量`,
      card,
    );
    for (const recipe of peer.recipes) {
      const button = element(
        "button",
        recipe.title + " · " + recipe.state,
        card,
      );
      button.onclick = () => details("recipe", recipe);
    }
    for (const job of (peer.jobs || []).slice(-5)) {
      if (!job.runtime?.state && job.outputs?.state === "not_requested") continue;
      const section = element("div", undefined, card, "job-execution");
      element("small", `任务 ${job.id.slice(-10)} · ${job.state}`, section);
      if (job.runtime?.state) {
        element("p", `环境 ${job.runtime.state} · ${job.runtime.isolation || "准备中"} · ${job.runtime.package_count} 个包`, section);
      }
      if (job.outputs && job.outputs.state !== "not_requested") {
        element("p", `产物 ${job.outputs.state}`, section);
        for (const output of job.outputs.items) element("p", `${output.name} · ${output.kind} · ${output.artifact_id.slice(-10)}`, section);
      }
    }
    if (!peer.recipes.length)
      element(
        "p",
        "尚未上报 recipe；不推断会话当前在思考什么。",
        card,
        "empty",
      );
  }
  if (!data.agents?.length) element("p", "尚无可见研究身份。", $("agents"));
  const telemetry = data.resources?.telemetry;
  const requested = (data.agents || []).reduce(
    (n, p) => n + p.requested_gpus,
    0,
  );
  $("gpuSummary").textContent =
    `未结束任务合计申请 ${requested} 张 GPU（包含排队任务；不代表实际分配量或利用率）。`;
  $("gpuCards").replaceChildren();
  const stale =
    telemetry?.sampled_at && Date.now() / 1000 - telemetry.sampled_at > 30;
  $("gpuTime").textContent = telemetry?.sampled_at
    ? (stale ? "采样已过期 · " : "采样 · ") +
      new Date(telemetry.sampled_at * 1000).toLocaleTimeString()
    : "未接入实测遥测";
  if (telemetry?.status !== "available" || !telemetry.gpus.length) {
    element(
      "p",
      telemetry?.status === "restricted"
        ? "当前身份无权查看节点 GPU 遥测。"
        : "暂无实际 GPU 采样；不会把未知利用率显示为 0%。",
      $("gpuCards"),
      "empty",
    );
    return;
  }
  element(
    "small",
    "采样范围：控制服务所在节点；不代表整个集群。未提供 job 到 GPU UUID 的映射。",
    $("gpuCards"),
  );
  for (const gpu of telemetry.gpus) {
    const card = element("article", undefined, $("gpuCards"), "gpu-card");
    element("h3", `GPU ${gpu.index} · ${gpu.name}`, card);
    element(
      "p",
      `利用率 ${gpu.utilization_percent ?? "未知"}${gpu.utilization_percent == null ? "" : "%"}${stale ? "（过期）" : ""}`,
      card,
    );
    element(
      "p",
      `显存 ${gpu.memory_used_mib ?? "未知"} / ${gpu.memory_total_mib ?? "未知"} MiB`,
      card,
    );
    element("p", `功耗 ${gpu.power_watts ?? "未知"} W`, card);
  }
}

function draw() {
  const map = $("map");
  map.replaceChildren();
  const count = data.islands.length;
  const rows = Math.ceil(count / 2) || 1,
    height = Math.max(500, rows * 245);
  map.setAttribute("viewBox", `0 0 820 ${height}`);
  const positions = data.islands.map((_, i) => [
    i % 2 ? 595 : 215,
    Math.floor(i / 2) * 245 + 130,
  ]);

  data.islands.forEach((island, i) => {
    const [x, y] = positions[i];
    const g = svg(
      "g",
      { tabindex: 0, role: "button", "aria-label": island.name },
      map,
    );
    for (let ring = 0; ring < 7; ring++) {
      let points = [];
      for (let k = 0; k <= 100; k++) {
        const a = (k / 100) * Math.PI * 2,
          r = 1 + 0.08 * Math.sin(3 * a + i) + 0.06 * Math.cos(5 * a);
        points.push(
          `${x + Math.cos(a) * (145 - ring * 13) * r},${y + Math.sin(a) * (85 - ring * 7) * r}`,
        );
      }
      svg(
        "path",
        {
          d: "M" + points.join(" L") + " Z",
          fill: ring === 0 ? "#e8ece123" : "none",
          stroke: "#b8c2aa",
          "stroke-width": 0.8,
          opacity: 0.8,
        },
        g,
      );
    }
    const events = island.events.filter((e) => e.time <= cut);
    for (let n = 0; n < Math.min(events.length, 14); n++) {
      const dx = x - 65 + n * 10,
        dy = y + 20 - Math.sin(n * 0.8) * 20;
      svg("circle", { cx: dx, cy: dy, r: 3, fill: "#6e886e" }, g);
    }
    svg(
      "text",
      { x: x - 100, y: y + 108, fill: "#7c8477", "font-size": 10 },
      g,
    ).textContent = island.id.slice(0, 15);
    svg(
      "text",
      { x: x - 100, y: y + 132, fill: "#303b31", "font-size": 17 },
      g,
    ).textContent = island.name;
    svg(
      "text",
      { x: x - 100, y: y + 151, fill: "#858980", "font-size": 10 },
      g,
    ).textContent =
      `${events.length} 条记录 · ${island.jobs.length} 项当前任务`;
    g.onclick = () => details("island", island);
    g.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") details("island", island);
    };
  });
  for (const b of data.bridges.filter((b) => b.time <= cut)) {
    const a = data.islands.findIndex((i) => i.id === b.source),
      z = data.islands.findIndex((i) => i.id === b.target);
    if (a < 0 || z < 0) continue;
    const [x, y] = positions[a],
      [xx, yy] = positions[z];
    const path = svg(
      "path",
      {
        d: `M${x} ${y} C${x + 220} ${y - 120},${xx - 200} ${yy + 100},${xx} ${yy}`,
        fill: "none",
        stroke: "#6e886e",
        "stroke-width": 2.5,
        tabindex: 0,
        role: "button",
        "aria-label": b.name,
      },
      map,
    );
    path.onclick = () => details("bridge", b);
    path.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") details("bridge", b);
    };
    svg(
      "text",
      {
        x: (x + xx) / 2,
        y: (y + yy) / 2 - 20,
        fill: "#61755e",
        "font-size": 12,
      },
      map,
    ).textContent = b.name;
  }
  if (!count)
    svg(
      "text",
      { x: 200, y: 240, fill: "#858980", "font-size": 16 },
      map,
    ).textContent = "暂无可访问的研究项目";
  $("islandList").replaceChildren();
  for (const i of data.islands) {
    const b = element("button", i.name, $("islandList"));
    b.onclick = () => details("island", i);
  }
  for (const b of data.bridges.filter((b) => b.time <= cut)) {
    const button = element(
      "button",
      "桥 " + b.id + " · " + b.name,
      $("islandList"),
    );
    button.onclick = () => details("bridge", b);
  }
  if (selected && selected.type === "bridge" && selected.item.time > cut)
    selected = null;
  if (selected) details(selected.type, selected.item);
  else if (data.bridges.some((b) => b.time <= cut))
    details(
      "bridge",
      data.bridges.find((b) => b.time <= cut),
    );
  else if (count) details("island", data.islands[0]);
  else {
    $("detail").replaceChildren();
    field(
      "研究工作区",
      "服务中尚无可访问项目。可通过 CLI 创建 campaign，或以 --demo 预览。",
    );
  }
}
function timeline() {
  const times = data.islands.flatMap((i) => i.events.map((e) => e.time));
  const min = Math.min(...times),
    max = Math.max(...times),
    v = Number($("timeline").value);
  cut = v === 100 ? Infinity : min + ((max - min) * v) / 100;
  $("timeLabel").textContent =
    cut === Infinity
      ? "当前记录"
      : data.demo
        ? `示意时间 ${cut.toFixed(0)}h`
        : new Date(cut * 1000).toLocaleString();
  draw();
}
async function load(preserve = false) {
  const button = $("refresh");
  button.disabled = true;
  try {
    const r = await fetch("/api/snapshot");
    const body = await r.json();
    if (!r.ok) throw Error(body.error);
    data = body;
    if (preserve && selected) {
      const entries =
        selected.type === "recipe"
          ? data.agents.flatMap((p) => p.recipes)
          : selected.type === "bridge"
            ? data.bridges
            : data.islands;
      const item = entries.find((i) => i.id === selected.item.id);
      selected = item ? { type: selected.type, item } : null;
    } else selected = null;
    renderMonitoring();
    renderAudits();
    $("notice").className = "";
    $("notice").textContent = data.notice;
    $("mode").textContent = data.demo ? "DEMO / 示意数据" : "LIVE / 只读连接";
    timeline();
  } catch (e) {
    data = null;
    $("map").replaceChildren();
    $("detail").replaceChildren();
    $("islandList").replaceChildren();
    $("agents").replaceChildren();
    $("gpuCards").replaceChildren();
    $("auditCases").replaceChildren();
    $("auditFeedback").replaceChildren();
    $("gpuTime").textContent = "连接已断开";
    $("gpuSummary").textContent = "无法读取最新资源状态";
    $("notice").textContent = e.message;
    $("notice").className = "error";
    $("mode").textContent = "DISCONNECTED";
  } finally {
    button.disabled = false;
  }
}
$("refresh").onclick = () => load();
$("timeline").oninput = () => {
  if (data) timeline();
};
load();

setInterval(() => {
  if (!$("refresh").disabled && !document.hidden) load(true);
}, 10000);
