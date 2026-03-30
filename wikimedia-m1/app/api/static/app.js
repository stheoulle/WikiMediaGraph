const canvas = document.getElementById("graphCanvas");
const controls = document.getElementById("controls");
const pageTitleInput = document.getElementById("pageTitleInput");
const refreshInput = document.getElementById("refreshInput");
const limitInput = document.getElementById("limitInput");
const graphStatus = document.getElementById("graphStatus");
const centerMetrics = document.getElementById("centerMetrics");
const neighborList = document.getElementById("neighborList");

const CANVAS_WIDTH = 1000;
const CANVAS_HEIGHT = 700;
const CENTER_X = CANVAS_WIDTH / 2;
const CENTER_Y = CANVAS_HEIGHT / 2;
const NEIGHBOR_RING_RADIUS = 240;

function fmtNumber(value) {
  return new Intl.NumberFormat().format(value || 0);
}

function sizeFromTotalEdits(totalEdits, isCenter = false) {
  const base = isCenter ? 45 : 18;
  const alpha = isCenter ? 12 : 9;
  return base + alpha * Math.log(totalEdits + 1);
}

function nodeColor(node, isCenter = false) {
  if (isCenter) {
    return "#ffd166";
  }
  return node.has_recent_modifications ? "#2ad18d" : "#fb5f6f";
}

function clearCanvas() {
  while (canvas.firstChild) {
    canvas.removeChild(canvas.firstChild);
  }
}

function makeSvg(tagName, attrs = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
  Object.entries(attrs).forEach(([k, v]) => element.setAttribute(k, String(v)));
  return element;
}

function updateMetrics(payload) {
  const center = payload.center;
  const values = [
    ["Title", center.title],
    ["Total edits", fmtNumber(center.total_edits)],
    ["Edits last hour", fmtNumber(center.edits_last_hour)],
    ["Recent activity", center.has_recent_modifications ? "Yes" : "No"],
    ["Last edit", center.last_edit_time || "N/A"],
    ["Neighbor count", fmtNumber(payload.count)],
  ];

  centerMetrics.innerHTML = "";
  values.forEach(([label, value]) => {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    wrap.appendChild(dt);
    wrap.appendChild(dd);
    centerMetrics.appendChild(wrap);
  });

  neighborList.innerHTML = "";
  payload.neighbors.forEach((node) => {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = node.title;

    const details = document.createElement("div");
    details.textContent = `edits=${fmtNumber(node.total_edits)} | last_hour=${fmtNumber(node.edits_last_hour)}`;

    item.appendChild(title);
    item.appendChild(details);
    neighborList.appendChild(item);
  });
}

function drawGraph(payload) {
  clearCanvas();
  const center = payload.center;
  const neighbors = payload.neighbors;

  const backgroundGrid = makeSvg("circle", {
    cx: CENTER_X,
    cy: CENTER_Y,
    r: NEIGHBOR_RING_RADIUS,
    fill: "none",
    stroke: "rgba(160, 190, 230, 0.12)",
    "stroke-dasharray": "6 8",
  });
  canvas.appendChild(backgroundGrid);

  const neighborPositions = neighbors.map((node, idx) => {
    const angle = (2 * Math.PI * idx) / Math.max(neighbors.length, 1) - Math.PI / 2;
    const x = CENTER_X + NEIGHBOR_RING_RADIUS * Math.cos(angle);
    const y = CENTER_Y + NEIGHBOR_RING_RADIUS * Math.sin(angle);
    return { ...node, x, y };
  });

  neighborPositions.forEach((node) => {
    const edge = makeSvg("line", {
      x1: CENTER_X,
      y1: CENTER_Y,
      x2: node.x,
      y2: node.y,
      class: "edge",
    });
    canvas.appendChild(edge);
  });

  neighborPositions.forEach((node) => {
    const group = makeSvg("g", { class: "node" });
    const radius = sizeFromTotalEdits(node.total_edits, false);

    const circle = makeSvg("circle", {
      cx: node.x,
      cy: node.y,
      r: radius,
      fill: nodeColor(node),
      stroke: "rgba(255,255,255,0.8)",
      "stroke-width": 1.3,
    });

    const label = makeSvg("text", {
      x: node.x,
      y: node.y + 4,
      class: "label",
    });
    const shortTitle = node.title.length > 18 ? `${node.title.slice(0, 18)}...` : node.title;
    label.textContent = shortTitle;

    group.appendChild(circle);
    group.appendChild(label);
    group.addEventListener("click", () => {
      pageTitleInput.value = node.title;
      loadGraph(node.title, false);
    });

    canvas.appendChild(group);
  });

  const centerGroup = makeSvg("g", { class: "node" });
  const centerRadius = sizeFromTotalEdits(center.total_edits, true);
  const centerCircle = makeSvg("circle", {
    cx: CENTER_X,
    cy: CENTER_Y,
    r: centerRadius,
    fill: nodeColor(center, true),
    stroke: "rgba(255,255,255,0.95)",
    "stroke-width": 2.2,
  });
  const centerLabel = makeSvg("text", {
    x: CENTER_X,
    y: CENTER_Y + 4,
    class: "label",
  });
  centerLabel.textContent = center.title.length > 22 ? `${center.title.slice(0, 22)}...` : center.title;

  centerGroup.appendChild(centerCircle);
  centerGroup.appendChild(centerLabel);
  canvas.appendChild(centerGroup);
}

async function loadGraph(pageTitle, refresh) {
  const limit = Number.parseInt(limitInput.value, 10) || 25;
  const params = new URLSearchParams({
    page_title: pageTitle,
    refresh: String(Boolean(refresh)),
    limit: String(Math.min(Math.max(limit, 1), 300)),
  });

  graphStatus.textContent = `Loading ${pageTitle}...`;

  try {
    const response = await fetch(`/api/graph?${params.toString()}`);
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }

    const payload = await response.json();
    drawGraph(payload);
    updateMetrics(payload);
    graphStatus.textContent = `Centered on ${payload.center.title} with ${payload.count} neighbors.`;
  } catch (error) {
    graphStatus.textContent = `Error: ${error.message}`;
  }
}

controls.addEventListener("submit", (event) => {
  event.preventDefault();
  const title = pageTitleInput.value.trim();
  if (!title) {
    graphStatus.textContent = "Please enter a page title.";
    return;
  }
  loadGraph(title, refreshInput.checked);
});

loadGraph(pageTitleInput.value.trim(), false);
