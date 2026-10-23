import "./vendor/video-stream.js";

const LAYOUT_KEY = "homecam.layout";
const PANEL_KEY = "homecam.panelCollapsed";
const SOUND_KEY = "homecam.sound";
const VOLUME_KEY = "homecam.volumes";

const LAYOUTS = {
  single: 1,
  quad: 4,
  nine: 9,
};

const wall = document.getElementById("wall");
const cameraList = document.getElementById("camera-list");
const emptyHint = document.getElementById("empty-hint");
const addForm = document.getElementById("add-form");
const formError = document.getElementById("form-error");
const panel = document.getElementById("panel");
const togglePanel = document.getElementById("toggle-panel");
const openPanel = document.getElementById("open-panel");
const layoutButtons = document.querySelectorAll(".layout-btn");
const soundBtn = document.getElementById("sound-btn");

let cameras = [];
let layout = localStorage.getItem(LAYOUT_KEY) || "single";
let soundEnabled = localStorage.getItem(SOUND_KEY) === "1";
let dragId = null;
let audioSyncing = false;

function readVolumes() {
  try {
    const parsed = JSON.parse(localStorage.getItem(VOLUME_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function savedVolume(streamName) {
  if (!streamName) return null;
  const value = readVolumes()[streamName];
  return typeof value === "number" && value >= 0 && value <= 1 ? value : null;
}

function rememberVolume(streamName, volume) {
  if (!streamName) return;
  const volumes = readVolumes();
  volumes[streamName] = volume;
  localStorage.setItem(VOLUME_KEY, JSON.stringify(volumes));
}

function syncVideoAudio(video, streamName, { unmute = true } = {}) {
  const volume = savedVolume(streamName);
  const userActivated = navigator.userActivation?.hasBeenActive === true;
  audioSyncing = true;
  try {
    if (volume !== null) video.volume = volume;
    else if (soundEnabled && video.volume === 0) video.volume = 1;
    if (!soundEnabled) video.muted = true;
    else if (unmute || userActivated) video.muted = false;
  } finally {
    audioSyncing = false;
  }
}

function bindStreamVolume(el, streamName) {
  el.dataset.stream = streamName;

  const attach = (video) => {
    if (video.dataset.volumeBound) return;
    video.dataset.volumeBound = "1";

    let pointerDown = false;
    let userAdjustUntil = 0;
    const markAdjust = () => {
      userAdjustUntil = Date.now() + 500;
    };

    video.addEventListener("pointerdown", () => {
      pointerDown = true;
      markAdjust();
    });
    video.addEventListener("pointerup", () => {
      pointerDown = false;
      markAdjust();
    });
    video.addEventListener("pointercancel", () => {
      pointerDown = false;
      markAdjust();
    });
    video.addEventListener("keydown", markAdjust);
    video.addEventListener("volumechange", () => {
      if (audioSyncing || (!pointerDown && Date.now() > userAdjustUntil)) return;
      rememberVolume(streamName, video.volume);
    });

    const restore = () => syncVideoAudio(video, streamName, { unmute: false });
    video.addEventListener("emptied", () => {
      requestAnimationFrame(restore);
    });
    video.addEventListener("loadedmetadata", restore);
    video.addEventListener("loadeddata", restore);
    video.addEventListener("play", restore);
    restore();
  };

  const scan = () => {
    const video = el.querySelector("video");
    if (video) attach(video);
  };
  scan();
  new MutationObserver(scan).observe(el, { childList: true, subtree: true });
}

function playVideo(video) {
  const pending = video.play();
  if (!pending || !pending.catch) return;
  pending.catch((err) => {
    // Tab switches abort playback. That is not an autoplay rejection.
    if (err && err.name !== "NotAllowedError") return;
    if (!soundEnabled || video.muted) return;
    video.muted = true;
    video.play().catch(() => {});
  });
}

function applyWallSound() {
  document.querySelectorAll(".tile video-stream").forEach((el) => {
    const video = el.querySelector("video");
    if (!video) return;
    syncVideoAudio(video, el.dataset.stream);
    playVideo(video);
  });
  if (soundBtn) {
    soundBtn.classList.toggle("active", soundEnabled);
    soundBtn.setAttribute("aria-pressed", soundEnabled ? "true" : "false");
    soundBtn.textContent = soundEnabled ? "Sound on" : "Sound off";
  }
}

function setSoundEnabled(enabled) {
  soundEnabled = enabled;
  localStorage.setItem(SOUND_KEY, enabled ? "1" : "0");
  applyWallSound();
}

function setLayoutActive(name) {
  layout = name;
  localStorage.setItem(LAYOUT_KEY, name);
  layoutButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.layout === name);
  });
  renderWall();
}

function setPanelCollapsed(collapsed) {
  panel.classList.toggle("collapsed", collapsed);
  openPanel.hidden = !collapsed;
  localStorage.setItem(PANEL_KEY, collapsed ? "1" : "0");
}

function normalizeRtspUrl(url) {
  const trimmed = url.trim();
  const match = trimmed.match(/^([a-zA-Z]+)(:\/\/.*)$/);
  if (match && /^rtsps?$/i.test(match[1])) {
    return match[1].toLowerCase() + match[2];
  }
  return trimmed;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function chunk(array, size) {
  const pages = [];
  for (let i = 0; i < array.length; i += size) {
    pages.push(array.slice(i, i + size));
  }
  return pages;
}

function createStreamElement(streamName) {
  const el = document.createElement("video-stream");
  el.mode = "mse";
  el.media = "video,audio";
  el.visibilityThreshold = 0.15;
  // Keep the socket up when the browser tab is in the background. The player
  // otherwise disconnects after a few seconds and the new stream drops volume.
  el.visibilityCheck = false;
  el.background = false;
  bindStreamVolume(el, streamName);
  const q = new URLSearchParams({ src: streamName });
  el.src = `/rtc/api/ws?${q.toString()}`;
  return el;
}

function renderWall() {
  wall.innerHTML = "";
  if (!cameras.length) {
    const empty = document.createElement("div");
    empty.className = "wall-empty";
    empty.textContent = "Add cameras in the side panel to start watching.";
    wall.appendChild(empty);
    return;
  }

  const perPage = LAYOUTS[layout] || 1;
  const pages = chunk(cameras, perPage);

  for (const pageCameras of pages) {
    const page = document.createElement("section");
    page.className = `page layout-${layout}`;

    for (const cam of pageCameras) {
      const tile = document.createElement("div");
      tile.className = "tile";

      const label = document.createElement("div");
      label.className = "tile-label";
      label.textContent = cam.name;

      tile.appendChild(createStreamElement(cam.stream));
      tile.appendChild(label);
      page.appendChild(tile);
    }

    wall.appendChild(page);
  }
  requestAnimationFrame(() => applyWallSound());
}

function renderCameraList() {
  cameraList.innerHTML = "";
  emptyHint.hidden = cameras.length > 0;

  for (const cam of cameras) {
    const li = document.createElement("li");
    li.className = "camera-item";
    li.draggable = true;
    li.dataset.id = cam.id;

    li.innerHTML = `
      <span class="drag-handle" aria-hidden="true">⋮⋮</span>
      <span class="name"></span>
      <button type="button" class="btn-danger" title="Remove">Remove</button>
    `;
    li.querySelector(".name").textContent = cam.name;

    li.addEventListener("dragstart", (e) => {
      dragId = cam.id;
      li.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    li.addEventListener("dragend", () => {
      dragId = null;
      li.classList.remove("dragging");
    });
    li.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    });
    li.addEventListener("drop", async (e) => {
      e.preventDefault();
      const targetId = cam.id;
      if (!dragId || dragId === targetId) return;
      const from = cameras.findIndex((c) => c.id === dragId);
      const to = cameras.findIndex((c) => c.id === targetId);
      if (from < 0 || to < 0) return;
      const next = [...cameras];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      cameras = await api("/api/cameras/order", {
        method: "PUT",
        body: JSON.stringify({ order: next.map((c) => c.id) }),
      });
      renderCameraList();
      renderWall();
    });

    li.querySelector(".btn-danger").addEventListener("click", async () => {
      if (!confirm(`Remove "${cam.name}"?`)) return;
      await api(`/api/cameras/${cam.id}`, { method: "DELETE" });
      await refreshCameras();
    });

    cameraList.appendChild(li);
  }
}

async function refreshCameras() {
  cameras = await api("/api/cameras");
  renderCameraList();
  renderWall();
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.hidden = true;
  const fd = new FormData(addForm);
  const name = fd.get("name")?.toString().trim();
  const rtsp = normalizeRtspUrl(fd.get("rtsp")?.toString() || "");
  try {
    await api("/api/cameras", {
      method: "POST",
      body: JSON.stringify({ name, rtsp }),
    });
    addForm.reset();
    await refreshCameras();
  } catch (err) {
    formError.textContent = err.message;
    formError.hidden = false;
  }
});

layoutButtons.forEach((btn) => {
  btn.addEventListener("click", () => setLayoutActive(btn.dataset.layout));
});

soundBtn?.addEventListener("click", () => setSoundEnabled(!soundEnabled));

let resumeSoundTimer = 0;
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  applyWallSound();
  // Firefox pauses background media, and that pause can abort the first
  // resume. Restore sound again after the pause has settled.
  clearTimeout(resumeSoundTimer);
  resumeSoundTimer = setTimeout(() => {
    if (!document.hidden) applyWallSound();
  }, 300);
});

togglePanel.addEventListener("click", () => setPanelCollapsed(true));
openPanel.addEventListener("click", () => setPanelCollapsed(false));

setLayoutActive(layout);
setPanelCollapsed(localStorage.getItem(PANEL_KEY) === "1");
applyWallSound();

refreshCameras().catch((err) => {
  console.error(err);
  formError.textContent = "Could not load cameras.";
  formError.hidden = false;
});
