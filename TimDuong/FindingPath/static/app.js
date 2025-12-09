const FOCUS_PLACE = "Khuong Dinh, Thanh Xuan, Hanoi";
const DEFAULT_PLACE = FOCUS_PLACE;
const INITIAL_VIEW = [20.9945, 105.8155];
const INITIAL_ZOOM = 15;

let selectionMode = "start";
let cachedPlace = DEFAULT_PLACE;
let startLatLng = null;
let goalLatLng = null;
let nodeFeatures = [];
let createNodeMode = false;
let createNodeBusy = false;
let createdNodes = [];
let startCreatedId = null;
let goalCreatedId = null;

const placeInput = document.getElementById("place-input");
const loadMapBtn = document.getElementById("load-map-btn");
const runBtn = document.getElementById("run-btn");
const algorithmSelect = document.getElementById("algorithm-select");
const errorBox = document.getElementById("error-box");
const resultPanel = document.getElementById("result-panel");
const startDisplay = document.getElementById("start-display");
const goalDisplay = document.getElementById("goal-display");
const selectionButtons = document.querySelectorAll(".selection-buttons .toggle");
const graphOnlyToggle = document.getElementById("graph-only-toggle");
const graphSummary = document.getElementById("graph-summary");
const graphmlOutput = document.getElementById("graphml-output");
const downloadGraphBtn = document.getElementById("download-graph-btn");
const defaultResultMessage = resultPanel.innerHTML;
const createNodeBtn = document.getElementById("create-node-btn");
const createNodeStatus = document.getElementById("create-node-status");
const defaultCreateNodeStatus = createNodeStatus ? createNodeStatus.textContent : "";
const createdNodeSelect = document.getElementById("created-node-select");
const deleteNodeBtn = document.getElementById("delete-node-btn");

placeInput.value = DEFAULT_PLACE;
placeInput.readOnly = true;
placeInput.title = "Khu vực cố định: Khương Đình, Thanh Xuân, Hà Nội";
if (graphmlOutput) {
  graphmlOutput.value = "Chưa có dữ liệu GraphML.";
}
if (downloadGraphBtn) {
  downloadGraphBtn.disabled = true;
}

const map = L.map("map", {
  zoomControl: true,
  preferCanvas: true,
});

const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

map.setView(INITIAL_VIEW, INITIAL_ZOOM);

const edgeLayer = L.geoJSON(null, {
  style: () => ({
    color: "#9aa0a6",
    weight: 1.5,
    opacity: 0.7,
  }),
  onEachFeature: (feature, layer) => {
    const props = feature?.properties || {};
    const direction = typeof props.from !== "undefined" && typeof props.to !== "undefined"
      ? `Cạnh ${props.from} → ${props.to}`
      : "Cạnh";
    const hasLength = typeof props.length_m === "number";
    const length = hasLength ? `${Number(props.length_m).toFixed(1)} m` : null;
    const name = props.name ? `Đường: ${props.name}` : null;
    const details = [direction];
    if (name) details.push(name);
    if (length) details.push(`Dài: ${length}`);
    layer.bindTooltip(details.join("\n"));
  },
});

const blockedLayer = L.geoJSON(null, {
  style: () => ({
    color: "#424242",
    weight: 3,
    opacity: 0.85,
    dashArray: "8 6",
  }),
});

const floodLayer = L.geoJSON(null, {
  style: () => ({
    color: "#ef6c00",
    weight: 2,
    fillColor: "#ef6c00",
    fillOpacity: 0.35,
  }),
});

edgeLayer.addTo(map);
floodLayer.addTo(map);
blockedLayer.addTo(map);

const nodeLayer = L.geoJSON(null, {
  pointToLayer: (feature, latlng) =>
    L.circleMarker(latlng, {
      radius: 4,
      weight: 1,
      color: "#1a237e",
      fillColor: "#3949ab",
      fillOpacity: 0.9,
    }),
  onEachFeature: (feature, layer) => {
    const id = feature?.properties?.id;
    const degree = feature?.properties?.degree;
    const tooltip = [`Nút ${id}`];
    if (typeof degree === "number") {
      tooltip.push(`Bậc: ${degree}`);
    }
    layer.bindTooltip(tooltip.join("\n"));
  },
});

nodeLayer.addTo(map);

const createdNodeLayer = L.layerGroup();
createdNodeLayer.addTo(map);

let pathLayer = null;
let startMarker = null;
let goalMarker = null;
let cachedGraphml = "";

function createMarkerIcon(type, label) {
  return L.divIcon({
    className: `marker marker-${type}`,
    html: `<span>${label}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

const startIcon = createMarkerIcon("start", "S");
const goalIcon = createMarkerIcon("goal", "G");

function updateMarker(marker, latlng, iconFactory) {
  if (!latlng) {
    if (marker) {
      map.removeLayer(marker);
    }
    return null;
  }
  if (marker) {
    marker.setLatLng(latlng);
    return marker;
  }
  const newMarker = L.marker(latlng, { icon: iconFactory });
  newMarker.addTo(map);
  return newMarker;
}

function featureCollection(features) {
  if (!Array.isArray(features) || features.length === 0) {
    return null;
  }
  return { type: "FeatureCollection", features };
}

function updateCoordinateDisplay() {
  const startSuffix = startCreatedId ? ` (node ${startCreatedId})` : "";
  const goalSuffix = goalCreatedId ? ` (node ${goalCreatedId})` : "";
  startDisplay.textContent = startLatLng
    ? `${startLatLng.lat.toFixed(6)}, ${startLatLng.lng.toFixed(6)}${startSuffix}`
    : "Chưa chọn";
  goalDisplay.textContent = goalLatLng
    ? `${goalLatLng.lat.toFixed(6)}, ${goalLatLng.lng.toFixed(6)}${goalSuffix}`
    : "Chưa chọn";
}

function clearPathLayers() {
  if (pathLayer) {
    map.removeLayer(pathLayer);
    pathLayer = null;
  }
  blockedLayer.clearLayers();
  floodLayer.clearLayers();
}

function renderNodes(features) {
  nodeLayer.clearLayers();
  const collection = featureCollection(features);
  if (collection) {
    nodeLayer.addData(collection);
    nodeLayer.bringToFront();
  }
}

function renderCreatedNodes(list) {
  createdNodeLayer.clearLayers();
  if (!Array.isArray(list)) {
    return;
  }
  list.forEach((node) => {
    const lat = Number(node.lat);
    const lon = Number(node.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      return;
    }
    const marker = L.circleMarker([lat, lon], {
      radius: 6,
      weight: 2,
      color: "#00695c",
      fillColor: "#26a69a",
      fillOpacity: 0.9,
    });
    const tooltip = [`Node da tao: ${node.id || "?"}`];
    marker.bindTooltip(tooltip.join("\n"));
    marker.on("click", () => {
      if (createNodeMode) return;
      const snapped = findNearestNode(L.latLng(lat, lon));
      const latlng = snapped?.latlng || L.latLng(lat, lon);
      setSelectionFromLatlng(latlng, node.id || null);
    });
    marker.addTo(createdNodeLayer);
  });
  if (createdNodeLayer.bringToFront) {
    createdNodeLayer.bringToFront();
  }
}

function renderCreatedNode(latlng, nodeId) {
  const marker = L.circleMarker(latlng, {
    radius: 7,
    weight: 2,
    color: "#00897b",
    fillColor: "#26a69a",
    fillOpacity: 0.9,
  });
  if (nodeId) {
    marker.bindTooltip(`Node moi: ${nodeId}`);
  }
  marker.addTo(createdNodeLayer);
  if (marker.bringToFront) {
    marker.bringToFront();
  }
}

function updateCreateNodeStatus(message, isError = false) {
  if (!createNodeStatus) {
    return;
  }
  createNodeStatus.textContent = message || defaultCreateNodeStatus;
  createNodeStatus.classList.toggle("error", Boolean(isError));
}

function setCreateNodeMode(enabled) {
  if (!createNodeBtn) {
    return;
  }
  createNodeMode = enabled;
  createNodeBtn.classList.toggle("active", enabled);
  createNodeBtn.textContent = enabled ? "Dang bat: click ban do de tao node" : "Bat che do tao node";
  updateCreateNodeStatus(
    enabled
      ? "Click bat ky vi tri tren ban do de gui toa do tao node."
      : defaultCreateNodeStatus || "Chua gui yeu cau nao."
  );
}

function updateCreatedNodeSelect() {
  if (!createdNodeSelect) {
    return;
  }
  createdNodeSelect.innerHTML = "";
  if (!Array.isArray(createdNodes) || createdNodes.length === 0) {
    createdNodeSelect.innerHTML = '<option value="">(Chua co node)</option>';
    if (deleteNodeBtn) deleteNodeBtn.disabled = true;
    return;
  }
  createdNodes.forEach((node) => {
    const label = `${node.id || "node"} (${Number(node.lat).toFixed(6)}, ${Number(node.lon).toFixed(6)})`;
    const option = document.createElement("option");
    option.value = node.id || "";
    option.textContent = label;
    createdNodeSelect.appendChild(option);
  });
  if (deleteNodeBtn) deleteNodeBtn.disabled = false;
}

function removeSelectionsUsingNode(nodeId) {
  if (startCreatedId === nodeId) {
    if (startMarker) {
      map.removeLayer(startMarker);
      startMarker = null;
    }
    startLatLng = null;
    startCreatedId = null;
  }
  if (goalCreatedId === nodeId) {
    if (goalMarker) {
      map.removeLayer(goalMarker);
      goalMarker = null;
    }
    goalLatLng = null;
    goalCreatedId = null;
  }
  updateCoordinateDisplay();
}

function setSelectionFromLatlng(latlng, createdId = null) {
  if (selectionMode === "start") {
    startLatLng = latlng;
    startCreatedId = createdId;
    startMarker = updateMarker(startMarker, startLatLng, startIcon);
  } else {
    goalLatLng = latlng;
    goalCreatedId = createdId;
    goalMarker = updateMarker(goalMarker, goalLatLng, goalIcon);
  }
  updateCoordinateDisplay();
}

selectionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectionButtons.forEach((btn) => btn.classList.remove("active"));
    button.classList.add("active");
    selectionMode = button.dataset.mode;
  });
});

map.on("click", (event) => {
  if (createNodeMode) {
    handleCreateNode(event.latlng);
    return;
  }
  const candidate = findNearestCandidate(event.latlng);
  if (!candidate || !candidate.latlng) {
    showError("Không tìm thấy nút nào gần điểm đã chọn. Hãy tải lại bản đồ hoặc chọn khu vực có dữ liệu.");
    return;
  }
  setSelectionFromLatlng(candidate.latlng, candidate.createdId || null);
});

async function fetchJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Yêu cầu thất bại");
  }
  return data;
}

function parseBlockedInput() {
  return [];
}

function parseFloodInput() {
  return [];
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function updateResultPanel(data) {
  const lengthKm = (data.total_length_m / 1000).toFixed(2);
  const costDiff =
    typeof data.total_cost_m === "number" &&
    Math.abs(data.total_cost_m - data.total_length_m) > 1e-6;
  const costLine = costDiff
    ? `<div><strong>Chi phí:</strong> ${data.total_cost_m.toFixed(1)} m (${(data.total_cost_m / 1000).toFixed(2)} km)</div>`
    : "";
  const segmentsHtml = data.segments
    .map((segment, index) => {
      const name = segment.name || "Đường không tên";
      const length = typeof segment.length_m === "number" ? segment.length_m.toFixed(1) : "?";
      const hasCost =
        typeof segment.cost_m === "number" &&
        typeof segment.length_m === "number" &&
        Math.abs(segment.cost_m - segment.length_m) > 1e-6;
      const costText = hasCost ? ` (chi phí ${segment.cost_m.toFixed(1)} m)` : "";
      const penalty = segment.penalty_multiplier && segment.penalty_multiplier !== 1
        ? `<span class="penalty">x${Number(segment.penalty_multiplier).toFixed(2)}</span>`
        : "";
      return `<li><strong>${index + 1}.</strong> ${name} – ${length} m${costText} ${penalty}</li>`;
    })
    .join("");

  resultPanel.innerHTML = `
    <div><strong>Thuật toán:</strong> ${data.algorithm.toUpperCase()}</div>
    <div><strong>Độ dài:</strong> ${data.total_length_m.toFixed(1)} m (${lengthKm} km)</div>
    ${costLine}
    <div><strong>Số cạnh:</strong> ${data.segments.length}</div>
    <ul class="segments">${segmentsHtml}</ul>
  `;
}

function resetSelections() {
  startLatLng = null;
  goalLatLng = null;
  startCreatedId = null;
  goalCreatedId = null;
  updateCoordinateDisplay();
  if (startMarker) {
    map.removeLayer(startMarker);
    startMarker = null;
  }
  if (goalMarker) {
    map.removeLayer(goalMarker);
    goalMarker = null;
  }
}

function renderEdges(features) {
  edgeLayer.clearLayers();
  const collection = featureCollection(features);
  if (collection) {
    edgeLayer.addData(collection);
    edgeLayer.bringToBack();
  }
}

function renderPath(pathCoords, blockedFeatures, floodFeatures) {
  if (pathLayer) {
    map.removeLayer(pathLayer);
    pathLayer = null;
  }

  if (Array.isArray(pathCoords) && pathCoords.length >= 2) {
    if (typeof window !== "undefined") {
      window.__lastRawPathCoords = pathCoords;
    }
    let coords = [];
    const isSame = (a, b) =>
      Math.abs(a[0] - b[0]) < 1e-7 && Math.abs(a[1] - b[1]) < 1e-7;

    pathCoords.forEach((pair) => {
      if (!Array.isArray(pair) || pair.length < 2) return;
      const lat = Number(pair[0]);
      const lon = Number(pair[1]);
      if (Number.isNaN(lat) || Number.isNaN(lon)) return;
      const current = [lat, lon];
      const last = coords[coords.length - 1];
      if (last && isSame(last, current)) {
        return; // skip duplicate point
      }
      coords.push(current);
    });

    if (typeof window !== "undefined") {
      window.__lastPathCoords = coords;
      window.__lastPathSegments = []; // no segment splitting
    }

    const latLngs = coords.map(([lat, lon]) => [lat, lon]);
    pathLayer = L.polyline(latLngs, {
      color: "#1976d2",
      weight: 5,
      opacity: 0.9,
    }).addTo(map);
    if (pathLayer.bringToFront) {
      pathLayer.bringToFront();
    }
  }

  blockedLayer.clearLayers();
  const blockedCollection = featureCollection(blockedFeatures);
  if (blockedCollection) {
    blockedLayer.addData(blockedCollection);
    blockedLayer.bringToFront();
  }

  floodLayer.clearLayers();
  const floodCollection = featureCollection(floodFeatures);
  if (floodCollection) {
    floodLayer.addData(floodCollection);
    floodLayer.bringToBack();
  }
}

function findNearestNode(latlng) {
  if (!Array.isArray(nodeFeatures) || nodeFeatures.length === 0) {
    return null;
  }
  let best = null;
  let bestDist = Infinity;
  nodeFeatures.forEach((feature) => {
    const coords = feature?.geometry?.coordinates;
    if (!Array.isArray(coords) || coords.length < 2) return;
    const nLat = Number(coords[1]);
    const nLng = Number(coords[0]);
    if (Number.isNaN(nLat) || Number.isNaN(nLng)) return;
    const dLat = latlng.lat - nLat;
    const dLng = latlng.lng - nLng;
    const dist2 = dLat * dLat + dLng * dLng; // Euclidean in degrees is fine for small areas
    if (dist2 < bestDist) {
      bestDist = dist2;
      best = { latlng: L.latLng(nLat, nLng), dist2 };
    }
  });
  return best;
}

function findNearestCreatedNode(latlng) {
  if (!Array.isArray(createdNodes) || createdNodes.length === 0) {
    return null;
  }
  let best = null;
  let bestDist = Infinity;
  createdNodes.forEach((node) => {
    const lat = Number(node.lat);
    const lon = Number(node.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    const dLat = latlng.lat - lat;
    const dLng = latlng.lng - lon;
    const dist2 = dLat * dLat + dLng * dLng;
    if (dist2 < bestDist) {
      bestDist = dist2;
      best = { latlng: L.latLng(lat, lon), id: node.id || null, dist2 };
    }
  });
  return best;
}

function findNearestCandidate(latlng) {
  const created = findNearestCreatedNode(latlng);
  const snapped = findNearestNode(latlng);
  const snappedDist = snapped ? snapped.dist2 : Infinity;

  if (created && created.dist2 <= snappedDist) {
    const snappedForCreated = findNearestNode(created.latlng);
    const targetLatlng = snappedForCreated?.latlng || created.latlng;
    return { latlng: targetLatlng, createdId: created.id };
  }
  if (snapped) {
    return { latlng: snapped.latlng, createdId: null };
  }
  return null;
}

async function handleCreateNode(latlng) {
  if (createNodeBusy) {
    return;
  }
  createNodeBusy = true;
  if (createNodeBtn) {
    createNodeBtn.disabled = true;
  }
  const coordText = `${latlng.lat.toFixed(6)}, ${latlng.lng.toFixed(6)}`;
  updateCreateNodeStatus(`Dang gui toa do ${coordText}...`);
  try {
    clearError();
    const payload = {
      lat: latlng.lat,
      lon: latlng.lng,
      place: cachedPlace,
    };
    const data = await fetchJson("/api/nodes", payload);
    const nodeId = data.node_id || data.id || `node-${createdNodeLayer.getLayers().length + 1}`;
    const created = {
      id: nodeId,
      lat: data.lat ?? latlng.lat,
      lon: data.lon ?? latlng.lng,
    };
    createdNodes.push(created);
    renderCreatedNodes(createdNodes);
    updateCreatedNodeSelect();
    updateCreateNodeStatus(`Da gui node ${nodeId} tai (${coordText})`);
  } catch (error) {
    const message = (error && error.message) || "Tao node that bai";
    updateCreateNodeStatus(message, true);
    showError(message);
  } finally {
    createNodeBusy = false;
    if (createNodeBtn) {
      createNodeBtn.disabled = false;
    }
  }
}

async function loadMap() {
  try {
    clearError();
    const place = FOCUS_PLACE;
    if (graphSummary) {
      graphSummary.textContent = "Đang tải dữ liệu Khương Đình...";
    }
    updateGraphmlOutput("");
    const data = await fetchJson("/api/load", { place });
    cachedPlace = place;
    nodeFeatures = Array.isArray(data.nodes) ? data.nodes : [];
    createdNodes = Array.isArray(data.created_nodes) ? data.created_nodes : [];
    renderEdges(data.edges);
    renderNodes(data.nodes);
    renderCreatedNodes(createdNodes);
    updateCreatedNodeSelect();
    setCreateNodeMode(false);
    updateCreateNodeStatus(defaultCreateNodeStatus || "Chua gui yeu cau nao.");
    resetSelections();
    clearPathLayers();
    resultPanel.innerHTML = defaultResultMessage;
    updateGraphSummary(data.graph_stats);
    updateGraphmlOutput(data.graphml);
    const bounds = L.latLngBounds(data.bounds.map(([lat, lon]) => [lat, lon]));
    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.1));
    } else if (Array.isArray(data.centroid)) {
      map.setView([data.centroid[0], data.centroid[1]], INITIAL_ZOOM);
    }
  } catch (error) {
    showError(error.message);
  }
}

async function runPathfinding() {
  if (!startLatLng || !goalLatLng) {
    showError("Cần chọn cả điểm xuất phát và đích trên bản đồ.");
    return;
  }

  try {
    clearError();
    const payload = {
      place: cachedPlace,
      algorithm: algorithmSelect.value,
      start: [startLatLng.lat, startLatLng.lng],
      goal: [goalLatLng.lat, goalLatLng.lng],
      startNodeId: startCreatedId,
      goalNodeId: goalCreatedId,
      blockedStreets: parseBlockedInput(),
      floodZones: parseFloodInput(),
    };

    const data = await fetchJson("/api/path", payload);
    const coords = Array.isArray(data.path_coords) ? data.path_coords : data.path;
    renderPath(coords, data.blocked, data.flood_zones);
    updateResultPanel(data);
  } catch (error) {
    showError(error.message);
  }
}

function updateGraphSummary(stats) {
  if (!graphSummary) {
    return;
  }
  if (!stats) {
    graphSummary.textContent = "Chưa tải";
    return;
  }
  const lengthKm = stats.total_length_m ? stats.total_length_m / 1000 : 0;
  const avgDegree = stats.average_degree ? Number(stats.average_degree) : 0;
  const direction = stats.is_directed ? "có hướng" : "vô hướng";
  graphSummary.textContent = `${stats.node_count} nút, ${stats.edge_count} cạnh ${direction}, ${lengthKm.toFixed(
    2
  )} km tổng độ dài, bậc TB ${avgDegree.toFixed(1)}`;
}

function updateGraphmlOutput(graphmlText) {
  cachedGraphml = typeof graphmlText === "string" ? graphmlText : "";
  if (!graphmlOutput || !downloadGraphBtn) {
    return;
  }
  graphmlOutput.value = cachedGraphml || "Chưa có dữ liệu GraphML.";
  downloadGraphBtn.disabled = cachedGraphml.length === 0;
}

if (downloadGraphBtn) {
  downloadGraphBtn.addEventListener("click", () => {
    if (!cachedGraphml) {
      return;
    }
    const blob = new Blob([cachedGraphml], { type: "application/graphml+xml" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${cachedPlace.replace(/\s+/g, "_") || "graph"}.graphml`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(url), 0);
  });
}

async function deleteSelectedNode() {
  if (!createdNodeSelect) {
    return;
  }
  const nodeId = createdNodeSelect.value;
  if (!nodeId) {
    updateCreateNodeStatus("Chua chon node de xoa", true);
    return;
  }
  updateCreateNodeStatus(`Dang xoa node ${nodeId}...`);
  try {
    const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Xoa node that bai");
    }
    createdNodes = Array.isArray(data.nodes) ? data.nodes : [];
    renderCreatedNodes(createdNodes);
    updateCreatedNodeSelect();
    removeSelectionsUsingNode(nodeId);
    updateCreateNodeStatus(`Da xoa node ${nodeId}`);
  } catch (error) {
    const msg = (error && error.message) || "Xoa node that bai";
    updateCreateNodeStatus(msg, true);
    showError(msg);
  }
}

if (graphOnlyToggle) {
  graphOnlyToggle.addEventListener("change", () => {
    const container = map.getContainer();
    if (graphOnlyToggle.checked) {
      if (map.hasLayer(tileLayer)) {
        map.removeLayer(tileLayer);
      }
      container.classList.add("graph-only");
    } else {
      tileLayer.addTo(map);
      container.classList.remove("graph-only");
    }
  });
}

if (createdNodeSelect) {
  createdNodeSelect.addEventListener("change", () => {
    const nodeId = createdNodeSelect.value;
    const node = createdNodes.find((item) => String(item.id) === nodeId);
    if (!node) return;
    const lat = Number(node.lat);
    const lon = Number(node.lon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    const snapped = findNearestNode(L.latLng(lat, lon));
    setSelectionFromLatlng(snapped?.latlng || L.latLng(lat, lon), nodeId);
  });
}

if (deleteNodeBtn) {
  deleteNodeBtn.addEventListener("click", deleteSelectedNode);
}

if (createNodeBtn) {
  createNodeBtn.addEventListener("click", () => {
    setCreateNodeMode(!createNodeMode);
  });
}

loadMapBtn.addEventListener("click", loadMap);
runBtn.addEventListener("click", runPathfinding);

// kick off initial load
loadMap();
