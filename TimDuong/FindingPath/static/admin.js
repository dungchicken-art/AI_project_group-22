const INITIAL_VIEW = [20.9945, 105.8155];
const INITIAL_ZOOM = 15;

let nodeFeatures = [];
let selectedA = null;
let selectedB = null;

const loginCard = document.getElementById("login-card");
const controlsCard = document.getElementById("controls-card");
const penaltiesCard = document.getElementById("penalties-card");
const forbiddenCard = document.getElementById("forbidden-card");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");
const usernameInput = document.getElementById("username-input");
const passwordInput = document.getElementById("password-input");
const loginError = document.getElementById("login-error");
const adminError = document.getElementById("admin-error");
const selectedNodeAEl = document.getElementById("selected-node-a");
const selectedCoordsAEl = document.getElementById("selected-coords-a");
const selectedNodeBEl = document.getElementById("selected-node-b");
const selectedCoordsBEl = document.getElementById("selected-coords-b");
const graphMetaEl = document.getElementById("graph-meta");
const kindSelect = document.getElementById("kind-select");
const multiplierInput = document.getElementById("multiplier-input");
const savePenaltyBtn = document.getElementById("save-penalty-btn");
const penaltyListEl = document.getElementById("penalty-list");
const penaltyCountEl = document.getElementById("penalty-count");
const forbiddenListEl = document.getElementById("forbidden-list");
const forbiddenCountEl = document.getElementById("forbidden-count");
const saveForbiddenBtn = document.getElementById("save-forbidden-btn");

usernameInput.value = usernameInput.value || "admin";
multiplierInput.value = multiplierInput.value || "2";
document.body.classList.add("unauth");

const map = L.map("admin-map", {
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
});

const penalizedLayer = L.geoJSON(null, {
  style: (feature) => {
    const multiplier = feature?.properties?.penalty_multiplier || 1;
    const intensity = Math.min(multiplier / 4, 1);
    return {
      color: "#e65100",
      weight: 4,
      opacity: 0.3 + 0.5 * intensity,
      dashArray: "5 4",
    };
  },
  onEachFeature: (feature, layer) => {
    const props = feature?.properties || {};
    const mult = props.penalty_multiplier ? Number(props.penalty_multiplier).toFixed(2) : "1.00";
    const name = props.name || "Canh";
    layer.bindTooltip(`${name}\nx${mult}`);
  },
});

const nodeLayer = L.geoJSON(null, {
  pointToLayer: (feature, latlng) =>
    L.circleMarker(latlng, {
      radius: 4,
      weight: 1,
      color: "#0f9d58",
      fillColor: "#0f9d58",
      fillOpacity: 0.9,
    }),
  onEachFeature: (feature, layer) => {
    const id = feature?.properties?.id;
    layer.bindTooltip(`Node ${id}`);
  },
});

const forbiddenLayer = L.geoJSON(null, {
  style: () => ({
    color: "#d32f2f",
    weight: 4,
    opacity: 0.9,
  }),
});

edgeLayer.addTo(map);
penalizedLayer.addTo(map);
forbiddenLayer.addTo(map);
nodeLayer.addTo(map);

let markerA = null;
let markerB = null;
let selectionLine = null;
let previewPath = [];
let forbiddenEdges = [];

function featureCollection(features) {
  if (!Array.isArray(features) || features.length === 0) {
    return null;
  }
  return { type: "FeatureCollection", features };
}

function clearError(box) {
  if (!box) return;
  box.hidden = true;
  box.textContent = "";
}

function showError(box, message) {
  if (!box) return;
  box.hidden = false;
  box.textContent = message;
}

async function fetchJson(url, options = {}) {
  const opts = { ...options };
  opts.headers = opts.headers || {};
  if (opts.body && !opts.headers["Content-Type"]) {
    opts.headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Yeu cau that bai");
  }
  return data;
}

function toggleAuthPanels(isAuthenticated) {
  loginCard.hidden = isAuthenticated;
  controlsCard.hidden = !isAuthenticated;
  penaltiesCard.hidden = !isAuthenticated;
   if (forbiddenCard) {
    forbiddenCard.hidden = !isAuthenticated;
  }
  logoutBtn.style.visibility = isAuthenticated ? "visible" : "hidden";
  document.body.classList.toggle("unauth", !isAuthenticated);
  document.body.classList.toggle("auth", isAuthenticated);
  if (isAuthenticated) {
    setTimeout(() => map.invalidateSize(), 50);
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
    const dist2 = dLat * dLat + dLng * dLng;
    if (dist2 < bestDist) {
      bestDist = dist2;
      best = { id: feature?.properties?.id, latlng: L.latLng(nLat, nLng) };
    }
  });
  return best;
}

function updateSelectionDisplay() {
  if (selectedA) {
    selectedNodeAEl.textContent = selectedA.id;
    selectedCoordsAEl.textContent = `${selectedA.latlng.lat.toFixed(6)}, ${selectedA.latlng.lng.toFixed(6)}`;
  } else {
    selectedNodeAEl.textContent = "Chua chon";
    selectedCoordsAEl.textContent = "--";
  }

  if (selectedB) {
    selectedNodeBEl.textContent = selectedB.id;
    selectedCoordsBEl.textContent = `${selectedB.latlng.lat.toFixed(6)}, ${selectedB.latlng.lng.toFixed(6)}`;
  } else {
    selectedNodeBEl.textContent = "Chua chon";
    selectedCoordsBEl.textContent = "--";
  }
}

function setPreviewPath(coords) {
  previewPath = [];
  if (!Array.isArray(coords)) return;
  coords.forEach((pair) => {
    if (!Array.isArray(pair) || pair.length < 2) return;
    const lat = Number(pair[0]);
    const lng = Number(pair[1]);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return;
    previewPath.push(L.latLng(lat, lng));
  });
}

function renderForbiddenList(list) {
  if (!forbiddenListEl || !forbiddenCountEl) return;
  forbiddenListEl.innerHTML = "";
  forbiddenCountEl.textContent = Array.isArray(list) ? list.length : 0;

  if (!Array.isArray(list) || list.length === 0) {
    const li = document.createElement("li");
    li.textContent = "Chưa có đường bị cấm.";
    forbiddenListEl.appendChild(li);
    forbiddenLayer.clearLayers();
    return;
  }

  const features = [];
  const edgesGeo = edgeLayer.toGeoJSON()?.features || [];

  list.forEach((item) => {
    const u = item.from || item.u || item[0];
    const v = item.to || item.v || item[1];
    if (!u || !v) return;
    const edge = edgesGeo.find(
      (f) =>
        f?.properties &&
        ((String(f.properties.from) === String(u) && String(f.properties.to) === String(v)) ||
          (String(f.properties.from) === String(v) && String(f.properties.to) === String(u)))
    );
    if (edge) {
      features.push(edge);
    }

    const li = document.createElement("li");
    li.textContent = `${u} ↔ ${v}`;
    const delBtn = document.createElement("button");
    delBtn.textContent = "Xóa";
    delBtn.className = "ghost";
    delBtn.addEventListener("click", () => deleteForbidden(item.id || `${u}--${v}`));
    li.appendChild(delBtn);
    forbiddenListEl.appendChild(li);
  });

  forbiddenLayer.clearLayers();
  const collection = featureCollection(features);
  if (collection) {
    forbiddenLayer.addData(collection);
  }
}

async function loadPreviewPath() {
  if (!selectedA || !selectedB) return;
  try {
    const data = await fetchJson(
      `/api/admin/preview?from=${encodeURIComponent(selectedA.id)}&to=${encodeURIComponent(selectedB.id)}`
    );
    setPreviewPath(data.path_coords);
  } catch (error) {
    setPreviewPath([]);
    showError(adminError, error.message);
  }
  refreshSelectionGraphics();
}

function refreshSelectionGraphics() {
  if (markerA) {
    map.removeLayer(markerA);
    markerA = null;
  }
  if (markerB) {
    map.removeLayer(markerB);
    markerB = null;
  }
  if (selectionLine) {
    map.removeLayer(selectionLine);
    selectionLine = null;
  }

  if (selectedA) {
    markerA = L.circleMarker(selectedA.latlng, {
      radius: 8,
      weight: 2,
      color: "#0f9d58",
      fillColor: "#0f9d58",
      fillOpacity: 0.35,
    }).addTo(map);
  }

  if (selectedB) {
    markerB = L.circleMarker(selectedB.latlng, {
      radius: 8,
      weight: 2,
      color: "#1976d2",
      fillColor: "#1976d2",
      fillOpacity: 0.35,
    }).addTo(map);
  }

  if (selectedA && selectedB) {
    const pathLatLngs = Array.isArray(previewPath) && previewPath.length >= 2 ? previewPath : [selectedA.latlng, selectedB.latlng];
    selectionLine = L.polyline(pathLatLngs, {
      color: "#ef6c00",
      weight: 4,
      opacity: 0.8,
    }).addTo(map);
    selectionLine.bringToFront();
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

function renderNodes(features) {
  nodeLayer.clearLayers();
  const collection = featureCollection(features);
  if (collection) {
    nodeLayer.addData(collection);
    nodeLayer.bringToFront();
  }
}

function renderPenalizedEdges(features) {
  penalizedLayer.clearLayers();
  const collection = featureCollection(features);
  if (collection) {
    penalizedLayer.addData(collection);
    penalizedLayer.bringToFront();
  }
}

function renderPenalties(list) {
  penaltyListEl.innerHTML = "";
  const entries = Array.isArray(list) ? list : [];
  penaltyCountEl.textContent = entries.length;

  if (entries.length === 0) {
    penaltyListEl.innerHTML = `<li class="penalty-meta">Chua co node nao duoc gan he so.</li>`;
    return;
  }

  entries.forEach((penalty) => {
    const li = document.createElement("li");
    li.className = "penalty-item";
    const multiplier = Number(penalty.multiplier || 1).toFixed(2);
    const kind = penalty.kind || "flood";
    const edgeId = penalty.id || `${penalty.from}--${penalty.to}`;
    li.innerHTML = `
      <div>
        <div><strong>${penalty.from} -> ${penalty.to}</strong></div>
        <div class="penalty-meta">He so phat x${multiplier} • ${kind}</div>
      </div>
      <button class="remove-btn" type="button" data-edge="${edgeId}">Xoa</button>
    `;
    const removeBtn = li.querySelector("button");
    removeBtn.addEventListener("click", () => deletePenalty(edgeId));
    penaltyListEl.appendChild(li);
  });
}

function updateGraphMeta(stats) {
  if (!graphMetaEl) return;
  if (!stats) {
    graphMetaEl.textContent = "Dang tai ban do...";
    return;
  }
  const lengthKm = stats.total_length_m ? stats.total_length_m / 1000 : 0;
  const avgDegree = stats.average_degree ? Number(stats.average_degree) : 0;
  graphMetaEl.textContent = `${stats.node_count} node, ${stats.edge_count} canh, ${lengthKm.toFixed(2)} km, bc TB ${avgDegree.toFixed(
    1
  )}`;
}

async function loadAdminData() {
  clearError(adminError);
  try {
    const data = await fetchJson("/api/admin/load");
    nodeFeatures = Array.isArray(data.nodes) ? data.nodes : [];
    renderEdges(data.edges);
    renderNodes(data.nodes);
    renderPenalizedEdges(data.penalized_edges);
    renderPenalties(data.penalties);
    forbiddenEdges = Array.isArray(data.forbidden_edges)
      ? data.forbidden_edges.map((pair) => ({ from: pair[0], to: pair[1], id: `${pair[0]}--${pair[1]}` }))
      : [];
    renderForbiddenList(forbiddenEdges);
    updateGraphMeta(data.graph_stats);

    const bounds = L.latLngBounds(data.bounds.map(([lat, lon]) => [lat, lon]));
    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.05));
    } else if (Array.isArray(data.centroid)) {
      map.setView([data.centroid[0], data.centroid[1]], INITIAL_ZOOM);
    }
  } catch (error) {
    showError(adminError, error.message);
  }
}

async function handleLogin() {
  clearError(loginError);
  try {
    await fetchJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({
        username: usernameInput.value,
        password: passwordInput.value,
      }),
    });
    toggleAuthPanels(true);
    await loadAdminData();
  } catch (error) {
    showError(loginError, error.message);
  }
}

async function saveForbidden() {
  if (!selectedA || !selectedB) {
    showError(adminError, "Chon 2 node can chan duong");
    return;
  }
  try {
    clearError(adminError);
    const payload = { from: selectedA.id, to: selectedB.id };
    const data = await fetchJson("/api/admin/forbidden", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    forbiddenEdges = Array.isArray(data.forbidden) ? data.forbidden : [];
    renderForbiddenList(
      forbiddenEdges.map((edge) => ({
        from: edge.from || edge[0],
        to: edge.to || edge[1],
        id: edge.id || `${edge.from || edge[0]}--${edge.to || edge[1]}`,
      }))
    );
    await loadPreviewPath();
  } catch (error) {
    showError(adminError, error.message || "Khong chan duong duoc");
  }
}

async function deleteForbidden(edgeId) {
  try {
    clearError(adminError);
    const data = await fetchJson(`/api/admin/forbidden/${encodeURIComponent(edgeId)}`, {
      method: "DELETE",
    });
    forbiddenEdges = Array.isArray(data.forbidden) ? data.forbidden : [];
    renderForbiddenList(
      forbiddenEdges.map((edge) => ({
        from: edge.from || edge[0],
        to: edge.to || edge[1],
        id: edge.id || `${edge.from || edge[0]}--${edge.to || edge[1]}`,
      }))
    );
    await loadPreviewPath();
  } catch (error) {
    showError(adminError, error.message || "Khong xoa duoc duong cam");
  }
}

async function handleLogout() {
  clearError(adminError);
  await fetchJson("/api/admin/logout", { method: "POST" });
  toggleAuthPanels(false);
  nodeFeatures = [];
  renderEdges([]);
  renderNodes([]);
  renderPenalizedEdges([]);
  renderPenalties([]);
  selectedA = null;
  selectedB = null;
  previewPath = [];
  refreshSelectionGraphics();
  updateSelectionDisplay();
}

async function savePenalty() {
  clearError(adminError);
  if (!selectedA || !selectedB) {
    showError(adminError, "Chọn 2 node liền kề trên bản đồ .");
    return;
  }

  const multiplier = Number(multiplierInput.value);
  if (!Number.isFinite(multiplier) || multiplier <= 0) {
    showError(adminError, "Hệ số phải lớn hơn 0.");
    return;
  }

  try {
    await fetchJson("/api/admin/penalties", {
      method: "POST",
      body: JSON.stringify({
        from: selectedA.id,
        to: selectedB.id,
        multiplier,
        kind: kindSelect.value,
      }),
    });
    await loadAdminData();
  } catch (error) {
    showError(adminError, error.message);
  }
}

async function deletePenalty(nodeId) {
  clearError(adminError);
  try {
    await fetchJson(`/api/admin/penalties/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
    await loadAdminData();
  } catch (error) {
    showError(adminError, error.message);
  }
}

async function bootstrap() {
  try {
    const status = await fetchJson("/api/admin/status");
    toggleAuthPanels(status.authenticated);
    if (status.authenticated) {
      await loadAdminData();
    }
  } catch (error) {
    toggleAuthPanels(false);
  }
}

map.on("click", async (event) => {
  if (controlsCard.hidden) {
    showError(adminError, "Đăng nhập để tùy chỉnh.");
    return;
  }
  const nearest = findNearestNode(event.latlng);
  if (!nearest || !nearest.id) {
    showError(adminError, "Không tìm thấy node gần đó. Thử lại trong khu vực có dữ liệu.");
    return;
  }
  clearError(adminError);
  if (!selectedA || (selectedA && selectedB)) {
    selectedA = nearest;
    selectedB = null;
    previewPath = [];
  } else if (!selectedB) {
    if (nearest.id === selectedA.id) {
      showError(adminError, "Hãy chọn node thứ hai khác node đầu.");
      return;
    }
    selectedB = nearest;
    await loadPreviewPath();
  }
  updateSelectionDisplay();
  refreshSelectionGraphics();
});

loginBtn.addEventListener("click", handleLogin);
logoutBtn.addEventListener("click", handleLogout);
savePenaltyBtn.addEventListener("click", savePenalty);
if (saveForbiddenBtn) {
  saveForbiddenBtn.addEventListener("click", saveForbidden);
}
passwordInput.addEventListener("keypress", (event) => {
  if (event.key === "Enter") {
    handleLogin();
  }
});

bootstrap();
