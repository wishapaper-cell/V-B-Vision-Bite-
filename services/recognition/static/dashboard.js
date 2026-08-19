const qs = (selector) => document.querySelector(selector);

const state = {
  session: null,
  socket: null,
  latest: null,
  report: null,
};

const qualityLabels = [
  ["angle_coverage", "视角覆盖"],
  ["depth_completeness", "深度完整度"],
  ["mask_stability", "主体稳定性"],
  ["motion_quality", "连续采集"],
  ["lighting", "光照质量"],
  ["blur", "清晰度"],
  ["plate_visibility", "主体可见"],
];

const scaleStatusLabels = {
  calibrating: "校准中",
  stable: "已稳定",
  too_close: "近距校正",
  too_far: "远距校正",
  corrected: "尺度校正",
  needs_reference: "待标准帧",
};

qs("#createSessionBtn").addEventListener("click", createSession);
qs("#finishBtn").addEventListener("click", finishSession);
qs("#copyUrlBtn").addEventListener("click", copyCaptureUrl);
qs("#openCaptureBtn").addEventListener("click", () => {
  if (state.session?.capture_url) window.open(state.session.capture_url, "_blank", "noopener");
});

async function createSession() {
  const response = await fetch("/api/sessions", { method: "POST" });
  if (!response.ok) throw new Error("create session failed");
  state.session = await response.json();
  state.report = null;
  qs("#reportJson").textContent = "";
  qs("#reportState").textContent = "未生成";
  qs("#sessionId").value = state.session.session_id;
  qs("#captureUrl").value = state.session.capture_url;
  qs("#qrImage").src = `${state.session.qr_code_url}?t=${Date.now()}`;
  qs("#copyUrlBtn").disabled = false;
  qs("#openCaptureBtn").disabled = false;
  qs("#finishBtn").disabled = false;
  connectEvents();
  const snapshot = await fetchJson(`/api/sessions/${state.session.session_id}/state`);
  render(snapshot);
}

function connectEvents() {
  if (state.socket) state.socket.close();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocol}://${location.host}/ws/sessions/${state.session.session_id}/events`;
  state.socket = new WebSocket(url);
  state.socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.state) render(message.state);
    if (message.report) renderReport(message.report);
  };
  state.socket.onclose = () => updateStatus("error", "连接断开");
}

async function finishSession() {
  if (!state.session) return;
  qs("#reportState").textContent = "生成中…";
  try {
    const report = await fetchJson(`/api/sessions/${state.session.session_id}/finish`, { method: "POST" });
    renderReport(report);
  } catch (error) {
    qs("#reportState").textContent = "生成失败";
    qs("#reportJson").textContent = `生成报告失败：${error.message}\n\n如果后端重启过，旧会话已失效，请点击"新建会话"重新测量。`;
  }
}

async function copyCaptureUrl() {
  if (!state.session?.capture_url) return;
  await navigator.clipboard.writeText(state.session.capture_url);
  qs("#copyUrlBtn").textContent = "已复制";
  setTimeout(() => {
    qs("#copyUrlBtn").textContent = "复制采集地址";
  }, 1200);
}

function render(nextState) {
  state.latest = nextState;
  updateStatus(nextState.status, statusLabel(nextState.status));
  qs("#videoMeta").textContent = `${nextState.video.resolution} · ${nextState.video.fps} FPS · 接收 ${nextState.frame_count} 帧 · 分析 ${nextState.analyzed_frame_count || 0} 帧 · ${nextState.elapsed_seconds}s`;
  qs("#analyzerLabel").textContent = `Analyzer: ${nextState.analyzer} / ${nextState.model_name}`;
  qs("#guidanceBadge").textContent = nextState.guidance.message;
  qs("#frameCount").textContent = `${nextState.frame_count} frames`;

  if (nextState.latest_frame_url) {
    qs("#latestFrame").src = `${nextState.latest_frame_url}&v=${nextState.frame_count}`;
    qs("#emptyVideo").style.display = "none";
    if (!nextState.foods.length && nextState.frame_count > 0) {
      qs("#guidanceBadge").textContent = "已收到手机画面，正在寻找稳定食物主体。";
    }
  }

  renderOverlay(nextState);
  renderFoods(nextState.foods);
  renderSummary(nextState.foods);
  renderIntake(nextState);
  renderQuality(nextState.measurement_quality);
}

const intakeStateLabels = {
  utensil_contact_food: "接触食物",
  food_lifted: "夹起食物",
  moving_to_mouth: "送向嘴边",
  intake_confirmed: "确认进食",
  returned_to_plate: "放回盘中",
  uncertain: "动作不明",
};

function renderIntake(nextState) {
  const foods = nextState.foods || [];
  const intakeCalories = foods.reduce((acc, food) => {
    const perGramKcal = food.estimated_weight_g > 0 ? food.nutrition.calories_kcal / food.estimated_weight_g : 0;
    return acc + (food.intake_weight_sum_g || 0) * perGramKcal;
  }, 0);
  qs("#intakeWeight").textContent = `${(nextState.confirmed_intake_weight_g || 0).toFixed(1)}g`;
  qs("#intakeCalories").textContent = `${intakeCalories.toFixed(1)}kcal`;
  qs("#intakeEventCount").textContent = `${nextState.confirmed_intake_event_count || 0} 口`;
  const events = nextState.intake_events || [];
  const last = events[events.length - 1];
  qs("#lastIntakeState").textContent = last ? (intakeStateLabels[last.state] || last.state) : "--";
}

function renderOverlay(nextState) {
  const svg = qs("#overlaySvg");
  const [width = 1280, height = 720] = nextState.video.resolution.split("x").map((value) => Number(value));
  const frameArea = Math.max(1, width * height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";
  nextState.foods.forEach((food) => {
    const [x1, y1, x2, y2] = food.bbox;
    const bboxArea = Math.max(1, (x2 - x1) * (y2 - y1));
    if (bboxArea / frameArea > 0.5) return;

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", food.mask_svg_path || `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${y2} L ${x1} ${y2} Z`);
    path.setAttribute("fill", food.color);
    path.setAttribute("fill-opacity", food.state === "lost" ? "0.05" : "0.1");
    path.setAttribute("stroke", food.color);
    path.setAttribute("stroke-width", "3");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);

    const labelX = Math.max(6, Math.min(width - 250, x1));
    const labelY = Math.max(32, y1 - 10);
    const labelBg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    labelBg.setAttribute("x", labelX);
    labelBg.setAttribute("y", labelY - 28);
    labelBg.setAttribute("width", "244");
    labelBg.setAttribute("height", "32");
    labelBg.setAttribute("rx", "4");
    labelBg.setAttribute("fill", "rgba(7, 12, 9, 0.86)");
    labelBg.setAttribute("stroke", food.color);
    labelBg.setAttribute("stroke-width", "1");
    svg.appendChild(labelBg);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", labelX + 8);
    label.setAttribute("y", labelY - 8);
    label.setAttribute("fill", "#f7fff9");
    label.setAttribute("font-size", "15");
    label.setAttribute("font-weight", "800");
    label.textContent = `${food.name} ${Math.round(food.estimated_weight_g)}±${Math.round(food.weight_error_g)}g`;
    svg.appendChild(label);
  });
}

function renderFoods(foods) {
  qs("#foodRows").innerHTML = foods.map((food) => `
    <tr class="${food.state === "lost" ? "lost-row" : ""}">
      <td>${food.name}<small>${food.category} · ${food.state === "lost" ? "短暂丢失" : "主体跟踪"} · ${food.container_type || "none"}</small></td>
      <td>${food.cooking_method_name || "未识别"}<small>${Math.round((food.cooking_confidence || 0) * 100)}%</small></td>
      <td><strong>${food.estimated_weight_g}g</strong><small>±${food.weight_error_g}g · ${food.weight_estimation_level || "rough"}</small></td>
      <td>
        <span class="scale-badge ${food.reference_detected ? "corrected" : ""}">${food.weight_source === "visual_fallback" ? "粗估" : "标定卡"}</span>
        <small>${Math.round((food.scale_confidence || 0) * 100)}% · ${food.area_cm2 ? `${food.area_cm2}cm²` : `原始 ${Math.round(food.raw_weight_g || food.estimated_weight_g)}g`}</small>
      </td>
      <td>${food.nutrition.calories_kcal}kcal</td>
      <td>${food.nutrition.protein_g}g</td>
      <td>${food.nutrition.carbs_g}g</td>
      <td>${food.nutrition.fat_g}g</td>
      <td>${food.sample_count || food.visible_frames || 1}</td>
      <td>${Math.round((food.convergence || 0) * 100)}%</td>
      <td>${Math.round(food.weight_confidence * 100)}%<small>已吃 ${(food.intake_weight_sum_g || 0).toFixed(1)}g / ${food.confirmed_intake_event_count || 0} 口</small></td>
    </tr>
  `).join("");
}

function renderSummary(foods) {
  const total = foods.reduce((acc, food) => {
    acc.weight += food.estimated_weight_g;
    acc.error2 += food.weight_error_g ** 2;
    acc.calories += food.nutrition.calories_kcal;
    acc.protein += food.nutrition.protein_g;
    acc.carbs += food.nutrition.carbs_g;
    acc.fat += food.nutrition.fat_g;
    acc.confidence += food.weight_confidence;
    acc.convergence += food.convergence || 0;
    return acc;
  }, { weight: 0, error2: 0, calories: 0, protein: 0, carbs: 0, fat: 0, confidence: 0, convergence: 0 });
  const error = Math.sqrt(total.error2);
  qs("#totalWeight").textContent = `${total.weight.toFixed(1)}g`;
  qs("#totalWeightError").textContent = `±${error.toFixed(1)}g`;
  qs("#totalCalories").textContent = `${total.calories.toFixed(1)}kcal`;
  qs("#totalProtein").textContent = `${total.protein.toFixed(1)}g`;
  qs("#totalCarbs").textContent = `${total.carbs.toFixed(1)}g`;
  qs("#totalFat").textContent = `${total.fat.toFixed(1)}g`;
  qs("#overallConfidence").textContent = `${Math.round((foods.length ? total.confidence / foods.length : 0) * 100)}%`;
  qs("#overallConvergence").textContent = `${Math.round((foods.length ? total.convergence / foods.length : 0) * 100)}%`;
}

function renderQuality(quality) {
  qs("#qualityScore").textContent = `${Math.round(quality.overall * 100)}%`;
  qs("#qualityBars").innerHTML = qualityLabels.map(([key, label]) => {
    const value = quality[key] || 0;
    return `<div><span>${label}</span><i><b style="width:${Math.round(value * 100)}%"></b></i><strong>${Math.round(value * 100)}%</strong></div>`;
  }).join("");
}

function renderReport(report) {
  state.report = report;
  qs("#reportState").textContent = "已生成";
  qs("#reportJson").textContent = JSON.stringify(report, null, 2);
}

function updateStatus(status, label) {
  const pill = qs("#statusPill");
  pill.textContent = label;
  pill.className = `pill ${status}`;
}

function statusLabel(status) {
  return {
    waiting_mobile: "等待手机",
    mobile_connected: "手机已连接",
    camera_ready: "摄像头就绪",
    streaming: "推流中",
    measuring: "测量中",
    completed: "已完成",
    error: "错误",
  }[status] || status;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function initFromUrl() {
  const params = new URLSearchParams(location.search);
  const sessionId = params.get("session_id");
  if (!sessionId) {
    await createSession();
    return;
  }
  try {
    state.session = { session_id: sessionId };
    const snapshot = await fetchJson(`/api/sessions/${sessionId}/state`);
    state.session.capture_url = snapshot.capture_url;
    qs("#sessionId").value = sessionId;
    qs("#captureUrl").value = snapshot.capture_url || "";
    qs("#copyUrlBtn").disabled = false;
    qs("#openCaptureBtn").disabled = false;
    qs("#finishBtn").disabled = false;
    render(snapshot);
    connectEvents();
  } catch (error) {
    updateStatus("error", "会话加载失败");
    qs("#guidanceBadge").textContent = error.message;
  }
}

initFromUrl().catch((error) => {
  updateStatus("error", "初始化失败");
  qs("#guidanceBadge").textContent = error.message;
});
