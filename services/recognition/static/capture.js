const qs = (selector) => document.querySelector(selector);
const params = new URLSearchParams(location.search);

const capture = {
  sessionId: params.get("session_id"),
  token: params.get("token"),
  stream: null,
  facingMode: "environment",
  timer: null,
  healthTimer: null,
  stateTimer: null,
  running: false,
  uploading: false,
  frameIntervalMs: 150,
  retryDelayMs: 900,
  sentFrames: 0,
  failedFrames: 0,
};

qs("#mobileSessionId").value = capture.sessionId || "missing";
qs("#joinBtn").addEventListener("click", joinSession);
qs("#cameraBtn").addEventListener("click", requestCamera);
qs("#switchCameraBtn").addEventListener("click", switchCamera);
qs("#streamBtn").addEventListener("click", toggleStream);

const complianceLabels = {
  compliant: "符合",
  generally_compliant: "一般符合",
  non_compliant: "非常不符合",
};

function setStatus(status, label) {
  const pill = qs("#mobileStatus");
  pill.textContent = label;
  pill.className = `pill ${status}`;
}

function setHint(message) {
  qs("#mobileHint").value = message;
}

function setCameraDebug(message) {
  qs("#cameraDebug").textContent = message;
}

function foodName(food = {}) {
  if (food.profile_key === "pork_floss_pastry") return "肉松糕点";
  return food.name || food.itemName || "未命名食物";
}

function foodWeight(food = {}) {
  return Number(food.weight_g || food.estimated_weight_g || food.grams || 0);
}

function foodCalories(food = {}) {
  const nutrition = food.nutrition || {};
  return Number(food.calories_kcal || nutrition.calories_kcal || food.caloriesKcal || 0);
}

function complianceForFood(food = {}) {
  const profileKey = `${food.profile_key || food.profileKey || ""}`;
  const name = `${food.name || food.itemName || ""}`;
  const category = `${food.category || ""}`;
  const cooking = `${food.cooking_method || ""}`;
  const weight = Math.max(foodWeight(food), 1);
  const caloriesPer100 = foodCalories(food) / weight * 100;
  if (profileKey === "pork_floss_pastry" || cooking === "deep_fried" || category === "甜点" || category === "零食" || caloriesPer100 >= 320 || /高糖|甜点|蛋糕|奶茶|糖|炸|油炸|肥肉/.test(name)) {
    return "non_compliant";
  }
  if (Number(food.confidence || 0) < 0.62 || caloriesPer100 >= 220 || ["pan_fried", "stir_fried", "braised"].includes(cooking)) {
    return "generally_compliant";
  }
  return "compliant";
}

function renderRecognitionState(state = {}) {
  const foods = state.foods || [];
  const quality = state.measurement_quality || {};
  const total = foods.reduce((acc, food) => {
    acc.weight += foodWeight(food);
    acc.calories += foodCalories(food);
    return acc;
  }, { weight: 0, calories: 0 });
  qs("#mobileFrameMeta").textContent = `${state.frame_count || 0} 帧 / 已分析 ${state.analyzed_frame_count || 0}`;
  qs("#mobileTotalWeight").textContent = `${Math.round(total.weight)}g`;
  qs("#mobileTotalCalories").textContent = `${Math.round(total.calories)}kcal`;
  qs("#mobileQuality").textContent = `${Math.round(Number(quality.overall || 0) * 100)}%`;
  qs("#mobileFoods").innerHTML = foods.length ? foods.map((food) => {
    const level = complianceForFood(food);
    return `
      <article class="${level}">
        <div>
          <strong>${foodName(food)}</strong>
          <span>${food.cooking_method_name || "估算"} · ${complianceLabels[level]}</span>
        </div>
        <b>${Math.round(foodWeight(food))}g</b>
      </article>
    `;
  }).join("") : `<span>等待识别食物主体。请保持餐盘在框内并缓慢移动镜头。</span>`;
}

async function refreshRecognitionState() {
  if (!capture.sessionId) return;
  try {
    const response = await fetch(`/api/sessions/${capture.sessionId}/state`, { cache: "no-store" });
    if (!response.ok) throw new Error(await response.text());
    renderRecognitionState(await response.json());
  } catch (error) {
    qs("#mobileFoods").innerHTML = `<span>识别状态同步失败：${error.message}</span>`;
  }
}

function startStatePolling() {
  if (capture.stateTimer) window.clearInterval(capture.stateTimer);
  capture.stateTimer = window.setInterval(refreshRecognitionState, 1300);
  refreshRecognitionState();
}

function videoStatus() {
  const video = qs("#cameraPreview");
  const track = capture.stream?.getVideoTracks?.()[0];
  const settings = track?.getSettings?.() || {};
  return {
    width: video.videoWidth || 0,
    height: video.videoHeight || 0,
    readyState: video.readyState,
    paused: video.paused,
    trackState: track?.readyState || "none",
    muted: Boolean(track?.muted),
    label: track?.label || "未命名摄像头",
    settings,
  };
}

function renderCameraDebug(prefix = "") {
  const status = videoStatus();
  const size = status.width && status.height ? `${status.width}x${status.height}` : "0x0";
  const settingSize = status.settings.width && status.settings.height ? `${status.settings.width}x${status.settings.height}` : "-";
  setCameraDebug(`${prefix}${prefix ? "\n" : ""}画面 ${size} / 轨道 ${status.trackState}${status.muted ? " muted" : ""} / video ${status.readyState}${status.paused ? " paused" : ""}\n设备 ${status.label} / 设置 ${settingSize}`);
}

function stopCamera() {
  if (capture.healthTimer) window.clearInterval(capture.healthTimer);
  capture.healthTimer = null;
  if (capture.timer) window.clearTimeout(capture.timer);
  capture.timer = null;
  capture.running = false;
  capture.uploading = false;
  if (capture.stream) {
    capture.stream.getTracks().forEach((track) => track.stop());
  }
  capture.stream = null;
  const video = qs("#cameraPreview");
  video.pause();
  video.srcObject = null;
  qs("#streamBtn").disabled = true;
  qs("#streamBtn").textContent = "开始推流";
}

function waitForVideoReady(video, timeoutMs = 3600) {
  return new Promise((resolve, reject) => {
    if (video.videoWidth && video.videoHeight) {
      resolve(true);
      return;
    }
    const started = Date.now();
    let timer = null;
    const cleanup = () => {
      if (timer) window.clearInterval(timer);
      video.removeEventListener("loadedmetadata", check);
      video.removeEventListener("canplay", check);
      video.removeEventListener("playing", check);
      video.removeEventListener("error", onError);
    };
    const check = () => {
      renderCameraDebug("等待摄像头画面");
      if (video.videoWidth && video.videoHeight) {
        cleanup();
        resolve(true);
      } else if (Date.now() - started > timeoutMs) {
        cleanup();
        reject(new Error("摄像头已授权，但浏览器没有输出可用画面。请点“切换镜头”或在浏览器权限里重新允许摄像头。"));
      }
    };
    const onError = () => {
      cleanup();
      reject(new Error(video.error?.message || "视频预览播放失败"));
    };
    video.addEventListener("loadedmetadata", check);
    video.addEventListener("canplay", check);
    video.addEventListener("playing", check);
    video.addEventListener("error", onError);
    timer = window.setInterval(check, 180);
    check();
  });
}

async function bindStream(stream) {
  const video = qs("#cameraPreview");
  capture.stream = stream;
  video.srcObject = stream;
  video.muted = true;
  video.playsInline = true;
  await video.play();
  await waitForVideoReady(video);
  stream.getVideoTracks().forEach((track) => {
    track.onended = () => {
      setStatus("error", "摄像头中断");
      setHint("摄像头轨道已中断，请重新授权摄像头。");
      renderCameraDebug("轨道已中断");
      stopCamera();
    };
    track.onmute = () => renderCameraDebug("摄像头暂未输出画面");
    track.onunmute = () => renderCameraDebug("摄像头画面恢复");
  });
  if (capture.healthTimer) window.clearInterval(capture.healthTimer);
  capture.healthTimer = window.setInterval(() => renderCameraDebug(), 1200);
  renderCameraDebug("摄像头就绪");
}

async function joinSession() {
  if (!capture.sessionId || !capture.token) {
    setStatus("error", "参数缺失");
    setHint("采集地址缺少 session_id 或 token，请重新扫码。");
    return;
  }
  const payload = {
    token: capture.token,
    device: {
      platform: "android",
      model: navigator.userAgent,
      user_agent: navigator.userAgent,
      app_version: "mobile-web-demo",
    },
  };
  const response = await fetch(`/api/sessions/${capture.sessionId}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    setStatus("error", "连接失败");
    setHint(await response.text());
    return;
  }
  setStatus("ready", "已连接");
  setHint("会话已连接。当前设备会作为摄像头采集端；也可以用电脑或另一台手机打开此页模拟手机采集。请点击“授权摄像头”。");
  qs("#cameraBtn").disabled = false;
  qs("#joinBtn").disabled = true;
  startStatePolling();
}

async function requestCamera() {
  try {
    stopCamera();
    setStatus("ready", "请求摄像头");
    setHint("正在请求摄像头权限。如果浏览器弹窗，请选择允许。");
    setCameraDebug("正在打开摄像头...");
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: capture.facingMode },
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
      },
    });
    await bindStream(stream);
    qs("#cameraEmpty").style.display = "none";
    qs("#streamBtn").disabled = false;
    qs("#switchCameraBtn").disabled = false;
    setStatus("ready", "摄像头就绪");
    setHint("摄像头已授权。请将餐盘放入框内，然后开始连续推流。");
    await sendEvent("camera_permission_granted", {
      tracks: stream.getVideoTracks().map((track) => track.label),
      status: videoStatus(),
    });
  } catch (error) {
    stopCamera();
    qs("#cameraEmpty").style.display = "grid";
    qs("#switchCameraBtn").disabled = false;
    setStatus("error", "授权失败");
    setHint(`摄像头无法输出画面：${error.message}\n可尝试：1. 点“切换镜头”；2. 浏览器地址栏权限里重新允许摄像头；3. 用系统浏览器打开 HTTPS 采集链接。`);
    renderCameraDebug(`失败：${error.name || "CameraError"} ${error.message}`);
    await sendEvent("camera_permission_denied", { message: error.message, name: error.name, status: videoStatus() });
  }
}

async function switchCamera() {
  capture.facingMode = capture.facingMode === "environment" ? "user" : "environment";
  setHint(`正在切换到${capture.facingMode === "environment" ? "后置" : "前置"}摄像头...`);
  await requestCamera();
}

async function toggleStream() {
  if (capture.running) {
    capture.running = false;
    if (capture.timer) window.clearTimeout(capture.timer);
    capture.timer = null;
    qs("#streamBtn").textContent = "开始推流";
    setStatus("ready", "已暂停");
    setHint(`推流已暂停。本次已上传 ${capture.sentFrames} 帧，失败 ${capture.failedFrames} 帧。`);
    await sendEvent("stream_stopped");
    return;
  }
  if (!capture.stream) {
    setHint("请先授权摄像头。");
    return;
  }
  const status = videoStatus();
  if (!status.width || !status.height || status.trackState !== "live") {
    setStatus("error", "画面未就绪");
    setHint("摄像头还没有输出画面，无法推流。请点“授权摄像头”重试，或点“切换镜头”。");
    renderCameraDebug("推流前检查失败");
    return;
  }
  capture.running = true;
  capture.sentFrames = 0;
  capture.failedFrames = 0;
  await sendEvent("stream_started");
  qs("#streamBtn").textContent = "停止推流";
  setStatus("streaming", "推流中");
  setHint("正在连续上传视频帧。请缓慢绕餐盘移动，采集越久估重越稳定。");
  scheduleNextFrame(0);
}

function scheduleNextFrame(delayMs = capture.frameIntervalMs) {
  if (!capture.running) return;
  if (capture.timer) window.clearTimeout(capture.timer);
  capture.timer = window.setTimeout(uploadFrame, delayMs);
}

async function uploadFrame() {
  if (capture.uploading || !capture.stream || !capture.running) return;
  const video = qs("#cameraPreview");
  if (!video.videoWidth || !video.videoHeight) {
    renderCameraDebug("等待视频宽高");
    scheduleNextFrame(180);
    return;
  }
  capture.uploading = true;
  try {
    const canvas = qs("#captureCanvas");
    const targetWidth = Math.min(640, video.videoWidth);
    const targetHeight = Math.round((targetWidth * video.videoHeight) / video.videoWidth);
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext("2d", { alpha: false });
    ctx.drawImage(video, 0, 0, targetWidth, targetHeight);
    const image = canvas.toDataURL("image/jpeg", 0.62);
    const payload = {
      token: capture.token,
      image,
      width: targetWidth,
      height: targetHeight,
      timestamp_ms: Date.now(),
      device_motion: {},
    };
    const response = await fetch(`/api/sessions/${capture.sessionId}/frames`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await response.text());
    const state = await response.json();
    renderRecognitionState(state);
    capture.sentFrames += 1;
    setStatus("streaming", `推流中 ${capture.sentFrames}`);
    setHint(`${state.guidance.message}\n已上传 ${capture.sentFrames} 帧，后端已分析 ${state.analyzed_frame_count || 0} 帧。`);
    scheduleNextFrame(capture.frameIntervalMs);
  } catch (error) {
    capture.failedFrames += 1;
    setStatus("streaming", "重试中");
    setHint(`上传短暂失败，正在继续重试：${error.message}`);
    scheduleNextFrame(capture.retryDelayMs);
  } finally {
    capture.uploading = false;
  }
}

async function sendEvent(event, payload = {}) {
  if (!capture.sessionId || !capture.token) return;
  await fetch(`/api/sessions/${capture.sessionId}/capture-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: capture.token, event, payload }),
  });
}

if (!window.isSecureContext) {
  setStatus("error", "非安全上下文");
  setHint("当前页面不是安全上下文。Android 真机摄像头授权通常需要 HTTPS，请使用二维码中的 HTTPS 地址。");
} else {
  setStatus("waiting", "待连接");
  setHint("请先点击“连接会话”。");
}
