const $ = (selector) => document.querySelector(selector);

const state = {
  requestRunning: false,
  previewStarted: false,
  previewRetry: null,
};

function formatTime(timestampMs) {
  if (!timestampMs) return "-";
  return new Date(timestampMs).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function setConnection(kind, text) {
  const badge = $("#connectionBadge");
  badge.className = `connection-badge ${kind}`;
  $("#connectionText").textContent = text;
}

function startPreview() {
  if (state.previewStarted) return;
  state.previewStarted = true;
  const image = $("#liveFrame");
  image.onload = () => {
    image.hidden = false;
    $("#emptyState").hidden = true;
  };
  image.onerror = () => {
    state.previewStarted = false;
    image.hidden = true;
    $("#emptyState").hidden = false;
    window.clearTimeout(state.previewRetry);
    state.previewRetry = window.setTimeout(startPreview, 1000);
  };
  image.src = `/api/stream.mjpg?started=${Date.now()}`;
}

async function loadServerConfig() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    $("#streamUrl").value = config.stream_url || "udp://<computer-ip>:5000";
  } catch {
    $("#streamUrl").value = "udp://<computer-ip>:5000";
    $("#copyFeedback").textContent = "无法读取局域网地址";
  }
}

function renderStatus(payload) {
  const stream = payload.stream || {};
  const frame = payload.frame || {};
  const dependencyMissing = stream.dependencyAvailable === false;

  if (dependencyMissing) {
    setConnection("error", "视频解码依赖缺失");
  } else if (payload.streamConnected) {
    setConnection("live", "UDP 视频流在线");
  } else {
    setConnection("waiting", "等待眼镜视频流");
  }

  $("#latencyValue").textContent =
    payload.age_ms === null || payload.age_ms === undefined ? "-" : String(payload.age_ms);
  $("#fpsValue").textContent = Number(payload.inputFps || 0).toFixed(1);
  $("#receiveFpsValue").textContent = Number(payload.receiveFps || 0).toFixed(1);
  $("#replacedValue").textContent = String(stream.replacedFrames || 0);
  $("#decodedValue").textContent = String(stream.decodedFrames || 0);
  $("#errorValue").textContent = String(stream.decodeErrors || 0);

  $("#frameCounter").textContent = payload.has_frame
    ? `FRAME ${String(frame.sequence).padStart(6, "0")}`
    : "FRAME -";
  $("#resolutionValue").textContent =
    frame.width && frame.height ? `${frame.width} x ${frame.height}` : "NO SIGNAL";
  $("#deviceValue").textContent = frame.device_name || "Rokid RV101";
  $("#ipValue").textContent = `UDP :${stream.listenPort || 5000}`;
  $("#receivedValue").textContent = formatTime(stream.lastDecodeAtMs);

  if (dependencyMissing) {
    $("#diagnosticText").textContent =
      stream.lastError || "请安装 requirements.txt 中的视频解码依赖";
  } else if (payload.streamConnected) {
    const recognition = payload.recognition || {};
    $("#diagnosticText").textContent = recognition.lastError
      ? `视频正常，识别异常：${recognition.lastError}`
      : `视频持续解码；识别上限 ${Number(recognition.targetFps || 0).toFixed(1)} FPS`;
  } else if (stream.lastError) {
    $("#diagnosticText").textContent = stream.lastError;
  } else {
    $("#diagnosticText").textContent = "监听已就绪，等待 MPEG-TS / H.264 数据";
  }
}

async function pollStatus() {
  if (state.requestRunning) return;
  state.requestRunning = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderStatus(await response.json());
  } catch (error) {
    setConnection("error", "电脑服务异常");
    $("#diagnosticText").textContent = `状态读取失败：${error.message}`;
  } finally {
    state.requestRunning = false;
  }
}

async function copyStreamUrl() {
  const value = $("#streamUrl").value;
  try {
    await navigator.clipboard.writeText(value);
    $("#copyFeedback").textContent = "推流目标已复制";
  } catch {
    $("#streamUrl").select();
    document.execCommand("copy");
    $("#copyFeedback").textContent = "推流目标已复制";
  }
}

$("#copyButton").addEventListener("click", copyStreamUrl);

window.setInterval(() => {
  $("#clockValue").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}, 500);
window.setInterval(pollStatus, 500);
loadServerConfig();
startPreview();
pollStatus();
