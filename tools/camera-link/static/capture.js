const $ = (selector) => document.querySelector(selector);

const capture = {
  stream: null,
  running: false,
  uploading: false,
  timer: null,
  facingMode: "environment",
  sent: 0,
  failed: 0,
  intervalMs: 700,
};

function log(message) {
  const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  $("#activityLog").textContent = `${time}  ${message}`;
}

function setBadge(kind, text) {
  $("#captureBadge").className = `connection-badge ${kind}`;
  $("#captureStatus").textContent = text;
}

function updateCounters() {
  $("#sentValue").textContent = String(capture.sent);
  $("#failureValue").textContent = `${capture.failed} errors`;
}

function stopCamera() {
  if (capture.timer) window.clearTimeout(capture.timer);
  capture.timer = null;
  capture.running = false;
  capture.uploading = false;
  capture.stream?.getTracks().forEach((track) => track.stop());
  capture.stream = null;
  const video = $("#cameraPreview");
  video.pause();
  video.srcObject = null;
  $("#streamButton").disabled = true;
  $("#streamButton").textContent = "开始传输";
}

async function waitForVideo(video) {
  if (video.videoWidth && video.videoHeight) return;
  await new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error("摄像头已打开，但未输出可用画面"));
    }, 5000);
    video.addEventListener(
      "loadedmetadata",
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      { once: true },
    );
  });
}

async function openCamera() {
  try {
    stopCamera();
    setBadge("waiting", "请求摄像头");
    log("正在请求摄像头权限…");
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: capture.facingMode },
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 24 },
      },
    });
    const video = $("#cameraPreview");
    capture.stream = stream;
    video.srcObject = stream;
    await video.play();
    await waitForVideo(video);
    $("#captureEmpty").hidden = true;
    $("#streamButton").disabled = false;
    $("#switchButton").disabled = false;
    setBadge("live", "摄像头就绪");
    const track = stream.getVideoTracks()[0];
    const settings = track?.getSettings?.() || {};
    log(`已连接：${track?.label || "未命名摄像头"}，${settings.width || video.videoWidth}×${settings.height || video.videoHeight}`);
  } catch (error) {
    setBadge("error", "摄像头失败");
    $("#captureEmpty").hidden = false;
    log(`${error.name || "CameraError"}：${error.message}`);
  }
}

async function switchCamera() {
  capture.facingMode = capture.facingMode === "environment" ? "user" : "environment";
  log(`正在切换到${capture.facingMode === "environment" ? "后置" : "前置"}摄像头…`);
  await openCamera();
}

function scheduleNext(delay = capture.intervalMs) {
  if (!capture.running) return;
  if (capture.timer) window.clearTimeout(capture.timer);
  capture.timer = window.setTimeout(uploadFrame, delay);
}

async function uploadFrame() {
  if (!capture.running || !capture.stream || capture.uploading) return;
  const video = $("#cameraPreview");
  if (!video.videoWidth || !video.videoHeight) {
    scheduleNext(200);
    return;
  }

  capture.uploading = true;
  $("#uploadValue").textContent = "SEND";
  try {
    const canvas = $("#captureCanvas");
    const width = Math.min(1280, video.videoWidth);
    const height = Math.round((width * video.videoHeight) / video.videoWidth);
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    context.drawImage(video, 0, 0, width, height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.76));
    if (!blob) throw new Error("JPEG 编码失败");

    const track = capture.stream.getVideoTracks()[0];
    const response = await fetch("/api/frame", {
      method: "POST",
      headers: {
        "Content-Type": "image/jpeg",
        "X-Device-Name": track?.label || navigator.userAgent,
        "X-Frame-Width": String(width),
        "X-Frame-Height": String(height),
      },
      body: blob,
      cache: "no-store",
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error || `HTTP ${response.status}`);
    }
    capture.sent += 1;
    $("#uploadValue").textContent = "LIVE";
    setBadge("live", `传输中 · ${capture.sent}`);
    log(`第 ${capture.sent} 帧已发送，${(blob.size / 1024).toFixed(1)}KB`);
    scheduleNext();
  } catch (error) {
    capture.failed += 1;
    $("#uploadValue").textContent = "RETRY";
    setBadge("error", "正在重试");
    log(`发送失败：${error.message}`);
    scheduleNext(1200);
  } finally {
    updateCounters();
    capture.uploading = false;
  }
}

function toggleStreaming() {
  if (capture.running) {
    capture.running = false;
    if (capture.timer) window.clearTimeout(capture.timer);
    capture.timer = null;
    $("#streamButton").textContent = "开始传输";
    $("#uploadValue").textContent = "PAUSE";
    setBadge("waiting", "传输已暂停");
    log(`传输暂停，共发送 ${capture.sent} 帧。`);
    return;
  }
  if (!capture.stream) {
    log("请先打开摄像头。");
    return;
  }
  capture.running = true;
  $("#streamButton").textContent = "停止传输";
  setBadge("live", "正在传输");
  log("开始向电脑发送 JPEG 画面。");
  scheduleNext(0);
}

$("#securityNotice").hidden = window.isSecureContext;
$("#cameraButton").addEventListener("click", openCamera);
$("#streamButton").addEventListener("click", toggleStreaming);
$("#switchButton").addEventListener("click", switchCamera);
window.addEventListener("pagehide", stopCamera);

if (!navigator.mediaDevices?.getUserMedia) {
  $("#cameraButton").disabled = true;
  setBadge("error", "浏览器不支持");
  log("当前浏览器没有提供 getUserMedia 摄像头接口。请改用 Rokid 原生采集适配器。");
} else if (!window.isSecureContext) {
  log("电脑连接已可测试，但当前 HTTP 页面可能被浏览器禁止使用摄像头。");
}
