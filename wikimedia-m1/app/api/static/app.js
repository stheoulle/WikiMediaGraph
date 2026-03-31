const canvas = document.getElementById("graphCanvas");
const controls = document.getElementById("controls");
const pageTitleInput = document.getElementById("pageTitleInput");
const refreshInput = document.getElementById("refreshInput");
const limitInput = document.getElementById("limitInput");
const resetViewBtn = document.getElementById("resetViewBtn");
const clearGraphBtn = document.getElementById("clearGraphBtn");
const graphStatus = document.getElementById("graphStatus");
const centerMetrics = document.getElementById("centerMetrics");
const neighborList = document.getElementById("neighborList");

const CANVAS_WIDTH = 1000;
const CANVAS_HEIGHT = 700;
const CENTER_X = CANVAS_WIDTH / 2;
const CENTER_Y = CANVAS_HEIGHT / 2;
const NEIGHBOR_RING_RADIUS = 220;
const RING_RADIUS_STEP = 70;
const MIN_NODE_GAP = 20;
const MAX_PLACEMENT_ATTEMPTS = 64;
const ZOOM_MIN = 0.35;
const ZOOM_MAX = 2.6;
const ZOOM_STEP = 1.12;

const graphState = {
  nodes: new Map(),
  edges: new Map(),
  currentCenterId: null,
  transform: {
    scale: 1,
    tx: 0,
    ty: 0,
  },
  drag: {
    active: false,
    pointerId: null,
    lastX: 0,
    lastY: 0,
  },
};

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

function makeSvg(tagName, attrs = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
  Object.entries(attrs).forEach(([k, v]) => element.setAttribute(k, String(v)));
  return element;
}

function edgeKey(sourceId, targetId) {
  return `${sourceId}->${targetId}`;
}

function worldPointFromClient(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const sx = clientX - rect.left;
  const sy = clientY - rect.top;
  return {
    x: (sx - graphState.transform.tx) / graphState.transform.scale,
    y: (sy - graphState.transform.ty) / graphState.transform.scale,
    sx,
    sy,
  };
}

function applyTransform(viewport) {
  const { tx, ty, scale } = graphState.transform;
  viewport.setAttribute("transform", `translate(${tx} ${ty}) scale(${scale})`);
}

function resetView() {
  graphState.transform.scale = 1;
  graphState.transform.tx = 0;
  graphState.transform.ty = 0;
  renderGraph();
}

function clearExploredGraph() {
  graphState.nodes.clear();
  graphState.edges.clear();
  graphState.currentCenterId = null;
  resetView();
  centerMetrics.innerHTML = "";
  neighborList.innerHTML = "";
  graphStatus.textContent = "Graph cleared. Load a page to start exploring.";
}

function nodeRadius(node) {
  return sizeFromTotalEdits(node.total_edits, graphState.currentCenterId === node.page_id);
}

function collidesWithExisting(candidate, candidateRadius, ignoreNodeId = null) {
  for (const node of graphState.nodes.values()) {
    if (ignoreNodeId !== null && node.page_id === ignoreNodeId) {
      continue;
    }

    const otherRadius = nodeRadius(node);
    const dx = node.x - candidate.x;
    const dy = node.y - candidate.y;
    const distance = Math.hypot(dx, dy);
    const minAllowed = candidateRadius + otherRadius + MIN_NODE_GAP;
    if (distance < minAllowed) {
      return true;
    }
  }
  return false;
}

function pickNeighborPosition(centerNode, neighborNode, index, total) {
  const radius = sizeFromTotalEdits(neighborNode.total_edits, false);
  const safeTotal = Math.max(total, 1);
  const phase = Math.random() * (Math.PI / 8);

  for (let ring = 0; ring < 4; ring += 1) {
    const ringRadius = NEIGHBOR_RING_RADIUS + ring * RING_RADIUS_STEP;
    for (let attempt = 0; attempt < MAX_PLACEMENT_ATTEMPTS; attempt += 1) {
      const angle = ((2 * Math.PI * (index + attempt)) / safeTotal) - Math.PI / 2 + phase;
      const candidate = {
        x: centerNode.x + ringRadius * Math.cos(angle),
        y: centerNode.y + ringRadius * Math.sin(angle),
      };

      if (!collidesWithExisting(candidate, radius, neighborNode.page_id)) {
        return candidate;
      }
    }
  }

  const fallbackAngle = ((2 * Math.PI * index) / safeTotal) - Math.PI / 2;
  return {
    x: centerNode.x + (NEIGHBOR_RING_RADIUS + 3 * RING_RADIUS_STEP) * Math.cos(fallbackAngle),
    y: centerNode.y + (NEIGHBOR_RING_RADIUS + 3 * RING_RADIUS_STEP) * Math.sin(fallbackAngle),
  };
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

function mergeGraphPayload(payload) {
  const center = payload.center;
  const neighbors = payload.neighbors;
  const previousCenterId = graphState.currentCenterId;
  const previousCenter = previousCenterId ? graphState.nodes.get(previousCenterId) : null;

  const centerExisting = graphState.nodes.get(center.page_id);
  let centerNode;

  if (centerExisting) {
    centerNode = {
      ...centerExisting,
      ...center,
      x: centerExisting.x,
      y: centerExisting.y,
    };
  } else if (previousCenter) {
    centerNode = {
      ...center,
      x: previousCenter.x + NEIGHBOR_RING_RADIUS,
      y: previousCenter.y,
    };
  } else {
    centerNode = {
      ...center,
      x: CENTER_X,
      y: CENTER_Y,
    };
  }

  graphState.nodes.set(center.page_id, centerNode);
  graphState.currentCenterId = center.page_id;

  neighbors.forEach((neighbor, idx) => {
    const existing = graphState.nodes.get(neighbor.page_id);
    if (existing) {
      graphState.nodes.set(neighbor.page_id, {
        ...existing,
        ...neighbor,
        x: existing.x,
        y: existing.y,
      });
    } else {
      const placed = pickNeighborPosition(centerNode, neighbor, idx, neighbors.length);
      graphState.nodes.set(neighbor.page_id, {
        ...neighbor,
        x: placed.x,
        y: placed.y,
      });
    }

    graphState.edges.set(
      edgeKey(center.page_id, neighbor.page_id),
      {
        source_page_id: center.page_id,
        target_page_id: neighbor.page_id,
        relation_type: neighbor.relation_type || "link",
      },
    );
  });
}

function renderGraph() {
  while (canvas.firstChild) {
    canvas.removeChild(canvas.firstChild);
  }

  const viewport = makeSvg("g");
  applyTransform(viewport);

  const grid = makeSvg("g", { class: "grid" });
  const gridStep = 120;
  const minX = -3000;
  const maxX = 4000;
  const minY = -3000;
  const maxY = 4000;

  for (let x = minX; x <= maxX; x += gridStep) {
    grid.appendChild(
      makeSvg("line", {
        x1: x,
        y1: minY,
        x2: x,
        y2: maxY,
        class: "grid-line",
      }),
    );
  }

  for (let y = minY; y <= maxY; y += gridStep) {
    grid.appendChild(
      makeSvg("line", {
        x1: minX,
        y1: y,
        x2: maxX,
        y2: y,
        class: "grid-line",
      }),
    );
  }

  viewport.appendChild(grid);

  for (const edge of graphState.edges.values()) {
    const source = graphState.nodes.get(edge.source_page_id);
    const target = graphState.nodes.get(edge.target_page_id);
    if (!source || !target) {
      continue;
    }

    viewport.appendChild(
      makeSvg("line", {
        x1: source.x,
        y1: source.y,
        x2: target.x,
        y2: target.y,
        class: "edge",
      }),
    );
  }

  const nodes = Array.from(graphState.nodes.values());
  nodes.sort((a, b) => {
    const aCenter = a.page_id === graphState.currentCenterId ? 1 : 0;
    const bCenter = b.page_id === graphState.currentCenterId ? 1 : 0;
    return aCenter - bCenter;
  });

  nodes.forEach((node) => {
    const isCenter = node.page_id === graphState.currentCenterId;
    const group = makeSvg("g", { class: "node" });
    const radius = sizeFromTotalEdits(node.total_edits, isCenter);

    const circle = makeSvg("circle", {
      cx: node.x,
      cy: node.y,
      r: radius,
      fill: nodeColor(node, isCenter),
      stroke: isCenter ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.8)",
      "stroke-width": isCenter ? 2.2 : 1.3,
    });

    const label = makeSvg("text", {
      x: node.x,
      y: node.y + 4,
      class: "label",
    });
    const titleMax = isCenter ? 22 : 18;
    label.textContent = node.title.length > titleMax ? `${node.title.slice(0, titleMax)}...` : node.title;

    group.appendChild(circle);
    group.appendChild(label);
    group.addEventListener("click", () => {
      pageTitleInput.value = node.title;
      loadGraph(node.title, false);
    });
    viewport.appendChild(group);
  });

  canvas.appendChild(viewport);
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
    mergeGraphPayload(payload);
    renderGraph();
    updateMetrics(payload);
    graphStatus.textContent = `Centered on ${payload.center.title}. Showing ${graphState.nodes.size} explored nodes and ${graphState.edges.size} edges.`;
  } catch (error) {
    graphStatus.textContent = `Error: ${error.message}`;
  }
}

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const factor = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
  const nextScale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, graphState.transform.scale * factor));

  if (nextScale === graphState.transform.scale) {
    return;
  }

  const point = worldPointFromClient(event.clientX, event.clientY);
  graphState.transform.tx = point.sx - point.x * nextScale;
  graphState.transform.ty = point.sy - point.y * nextScale;
  graphState.transform.scale = nextScale;
  renderGraph();
});

canvas.addEventListener("pointerdown", (event) => {
  graphState.drag.active = true;
  graphState.drag.pointerId = event.pointerId;
  graphState.drag.lastX = event.clientX;
  graphState.drag.lastY = event.clientY;
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (!graphState.drag.active || event.pointerId !== graphState.drag.pointerId) {
    return;
  }

  const dx = event.clientX - graphState.drag.lastX;
  const dy = event.clientY - graphState.drag.lastY;
  graphState.drag.lastX = event.clientX;
  graphState.drag.lastY = event.clientY;
  graphState.transform.tx += dx;
  graphState.transform.ty += dy;
  renderGraph();
});

function stopDragging(event) {
  if (!graphState.drag.active || event.pointerId !== graphState.drag.pointerId) {
    return;
  }

  graphState.drag.active = false;
  graphState.drag.pointerId = null;
  canvas.releasePointerCapture(event.pointerId);
}

canvas.addEventListener("pointerup", stopDragging);
canvas.addEventListener("pointercancel", stopDragging);

resetViewBtn.addEventListener("click", () => {
  resetView();
});

clearGraphBtn.addEventListener("click", () => {
  clearExploredGraph();
});

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
