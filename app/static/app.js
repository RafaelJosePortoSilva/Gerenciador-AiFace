"use strict";

const MASK = "••••••••";
const state = {
  devices: [], meta: null, profiles: [], detail: null, selected: null,
  profile: null, categories: [], activeCategory: null, sending: false,
  firmwareTimer: null, firmwareFiles: []
};

function $id(id) { return document.getElementById(id); }

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function toast(message, isError = false) {
  const box = $id("toast");
  box.textContent = message;
  box.style.background = isError ? "#9b1c1c" : "#111827";
  box.classList.add("show");
  clearTimeout(box._timer);
  box._timer = setTimeout(() => box.classList.remove("show"), 5000);
}

function token() { return localStorage.getItem("aiface_token") || ""; }

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const t = token();
  if (t) headers["X-API-Token"] = t;
  const response = await fetch(path, { ...options, headers });
  let body;
  try { body = await response.json(); }
  catch { body = { detail: await response.text() }; }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body || {}) });
}

function badge(text, kind) { return `<span class="badge ${kind || ""}">${text}</span>`; }

function formatBytes(size) {
  if (!size && size !== 0) return "—";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

function renderDevices(items) {
  const tbody = $id("device-rows");
  tbody.innerHTML = "";
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="10">Nenhum equipamento cadastrado.</td></tr>';
    return;
  }
  for (const d of items) {
    const s = d.status || {};
    const status = s.signature ? badge("AiFace detectado", "ok")
      : s.reachable ? badge("Online (sem assinatura)", "bad")
      : badge("Offline", "bad");
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><input type="checkbox" class="dev-check" value="${esc(d.id)}" checked></td>
      <td>${esc(d.label || d.id)}</td>
      <td><code>${esc(d.host)}</code></td>
      <td>${esc(s.sn || "—")}</td>
      <td>${esc(d.firmware || s.firmware || "—")}</td>
      <td>${status}</td>
      <td>${d.users ?? "—"}</td>
      <td>${d.logs ?? "—"}</td>
      <td>${s.checked_at ? new Date(s.checked_at).toLocaleString("pt-BR") : "—"}</td>
      <td><button class="small" data-detail="${esc(d.id)}">Configurar</button></td>`;
    tbody.appendChild(row);
  }
  tbody.querySelectorAll("[data-detail]").forEach(btn => {
    btn.addEventListener("click", () => openDevice(btn.dataset.detail));
  });
}

async function loadDevices() {
  state.devices = await api("/api/devices");
  renderDevices(state.devices);
  const select = $id("detail-device");
  select.innerHTML = state.devices.map(d => `<option value="${esc(d.id)}">${esc(d.label || d.id)} (${esc(d.host)})</option>`).join("");
  if (state.selected && state.devices.some(d => d.id === state.selected)) select.value = state.selected;
  renderBulkDeviceList();
}

async function refreshStatus() {
  const btn = $id("btn-refresh");
  btn.disabled = true;
  btn.textContent = "Verificando...";
  try {
    const items = await post("/api/devices/refresh");
    state.devices = items;
    renderDevices(items);
    toast("Status atualizado.");
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Atualizar status"; }
}

function renderInfo(detail) {
  const info = detail.device || {};
  const probe = detail.probe || {};
  const devinfo = (detail.reg && detail.reg.devinfo) || {};
  const items = [
    ["Nome", devinfo.modelname], ["Serial", probe.sn || detail.reg?.sn], ["ID", devinfo.deviceid],
    ["Firmware", devinfo.firmware], ["IP", devinfo.curip || info.host], ["MAC", devinfo.mac],
    ["Rede", devinfo.netinuse === 2 ? "Wi-Fi" : devinfo.netinuse === 1 ? "Ethernet" : "—"],
    ["Hora", devinfo.time], ["Usuários", `${devinfo.useduser ?? "—"}/${devinfo.usersize ?? "—"}`],
    ["Logs", `${devinfo.usedlog ?? "—"}/${devinfo.logsize ?? "—"}`],
    ["Empresa", devinfo.companyname], ["CNPJ", devinfo.CNPJ]
  ];
  $id("detail-info").innerHTML = items.map(([k, v]) => `<div class="info-item"><span>${k}</span><strong>${esc(v ?? "—")}</strong></div>`).join("");
}

function fieldControl(field, value) {
  const id = `f-${field.name}`;
  const original = value == null ? "" : String(value);
  const secret = (state.meta?.secret_fields || []).includes(field.name);
  const attrs = `id="${id}" data-name="${esc(field.name)}" data-original="${esc(original)}"`;
  let control;

  if (field.options && field.options.length) {
    const opts = field.options.map(([v, label]) =>
      `<option value="${esc(v)}" ${String(v) === original ? "selected" : ""}>${esc(label)}</option>`
    ).join("");
    control = `<select ${attrs} data-type="number">${opts}</select>`;
  } else if (field.type === "boolean") {
    control = `<select ${attrs} data-type="number">
      <option value="0" ${original === "0" ? "selected" : ""}>Não</option>
      <option value="1" ${original === "1" ? "selected" : ""}>Sim</option></select>`;
  } else {
    const inputType = secret ? "password" : (field.type === "number" ? "number" : "text");
    const valueType = field.type === "number" ? "number" : "string";
    control = `<input ${attrs} data-type="${valueType}" type="${inputType}" value="${esc(original)}">`;
  }
  const hint = field.name === field.label ? "" : `<small>${esc(field.name)}</small>`;
  return `<div class="field" data-field="${esc(field.name)}"><label for="${id}">${esc(field.label || field.name)} ${hint}</label>${control}</div>`;
}

function bindFieldChanges(root) {
  root.querySelectorAll("input, select").forEach(el => {
    el.addEventListener("input", () => {
      el.closest(".field").classList.toggle("changed", el.value !== el.dataset.original);
    });
  });
}

function showCategory(key) {
  state.activeCategory = key;
  document.querySelectorAll(".cat-tab").forEach(btn => btn.classList.toggle("active", btn.dataset.category === key));
  document.querySelectorAll("#detail-editor .category").forEach(box => box.classList.toggle("active", box.dataset.category === key));
}

function renderCategories(target, detail) {
  const config = detail.config || {};
  state.categories = state.meta?.setting_categories || [];
  target.innerHTML = state.categories.map(cat => {
    const fields = (cat.fields || []).filter(f => Object.prototype.hasOwnProperty.call(config, f.name));
    const body = fields.length
      ? `<div class="editor">${fields.map(f => fieldControl(f, config[f.name])).join("")}</div>`
      : '<p class="msg">Nenhum campo deste grupo foi informado pelo equipamento.</p>';
    const missing = (cat.fields || [])
      .filter(f => !Object.prototype.hasOwnProperty.call(config, f.name))
      .map(f => f.name);
    const note = missing.length
      ? `<p class="hint">Não informados pelo equipamento: ${esc(missing.join(", "))}</p>`
      : "";
    return `<section class="category" data-category="${esc(cat.key)}">
      <div class="category-head">
        <h4>${esc(cat.label)}</h4>
        <button class="small cat-send" data-category="${esc(cat.key)}">Enviar para o Dispositivo</button>
      </div>${body}${note}</section>`;
  }).join("");

  bindFieldChanges(target);
  target.querySelectorAll(".cat-send").forEach(btn =>
    btn.addEventListener("click", () => applyCategory(btn.dataset.category)));

  $id("category-tabs").innerHTML = state.categories.map(cat =>
    `<button class="cat-tab" data-category="${esc(cat.key)}">${esc(cat.label)}</button>`).join("");
  $id("category-tabs").querySelectorAll(".cat-tab").forEach(btn =>
    btn.addEventListener("click", () => showCategory(btn.dataset.category)));

  const valid = state.categories.some(cat => cat.key === state.activeCategory);
  showCategory(valid ? state.activeCategory : state.categories[0]?.key);
}

function renderCompany(target, values) {
  const metas = Object.keys(values || {}).map(name => ({ name, label: name, type: "text" }));
  target.innerHTML = metas.map(meta => fieldControl(meta, values[meta.name])).join("");
  bindFieldChanges(target);
}

function collectFields(root, { onlyChanged = true, names = null } = {}) {
  const result = {};
  root.querySelectorAll(".field").forEach(field => {
    if (onlyChanged && !field.classList.contains("changed")) return;
    const name = field.dataset.field;
    if (names && !names.includes(name)) return;
    const el = field.querySelector("input, select");
    if (!el || el.value === MASK) return;
    result[name] = el.dataset.type === "number" ? Number(el.value) : el.value;
  });
  return result;
}

function diffTable(changes) {
  if (!changes || !changes.length) return "<p class='msg'>Nenhuma diferença.</p>";
  return `<table class="diff-table"><thead><tr><th>Campo</th><th>Atual</th><th>Novo</th></tr></thead><tbody>` +
    changes.map(c => `<tr class="changed"><td><code>${esc(c.field)}</code></td><td>${esc(c.before)}</td><td>${esc(c.after)}</td></tr>`).join("") +
    "</tbody></table>";
}

function renderDiff(target, changes) { target.innerHTML = diffTable(changes); }

async function openDevice(id, focus = true) {
  state.selected = id;
  $id("detail-device").value = id;
  $id("detail-msg").textContent = "Carregando...";
  try {
    const detail = await api(`/api/devices/${encodeURIComponent(id)}`);
    state.detail = detail;
    renderInfo(detail);
    renderCategories($id("detail-editor"), detail);
    renderCompany($id("company-editor"), detail.company);
    $id("detail-msg").textContent = detail.probe?.signature
      ? "Equipamento identificado. Use 'Prévia de todas as abas' ou 'Enviar todas as abas para o Dispositivo'."
      : "Assinatura não confirmada neste equipamento.";
    if (focus) switchSection("detail");
  } catch (e) {
    $id("detail-msg").textContent = e.message;
    toast(e.message, true);
  }
}

async function previewAll() {
  if (!state.selected) { toast("Selecione um equipamento.", true); return; }
  const fields = collectFields($id("detail-editor"), { onlyChanged: false });
  if (!Object.keys(fields).length) { toast("Nenhum campo disponível para prévia.", true); return; }
  try {
    const preview = await post(`/api/devices/${encodeURIComponent(state.selected)}/preview`, { fields });
    if ((preview.unknown_fields || []).length) {
      toast(`Campos não suportados: ${preview.unknown_fields.join(", ")}`, true);
      return;
    }
    let changes = [...(preview.changes || [])];
    const companyFields = collectFields($id("company-editor"), { onlyChanged: false });
    if (Object.keys(companyFields).length) {
      const company = await post(`/api/devices/${encodeURIComponent(state.selected)}/company`, {
        fields: companyFields, confirm: false
      });
      changes = changes.concat((company.changes || []).map(c => ({ ...c, field: `company.${c.field}` })));
    }
    $id("detail-msg").innerHTML = `<strong>Prévia de todas as abas</strong>` + diffTable(changes);
    toast("Prévia de todas as abas gerada.");
  } catch (e) { toast(e.message, true); }
}

async function sendFields(fields, label, includeCompany = false) {
  if (state.sending) return;
  if (!state.selected) { toast("Selecione um equipamento.", true); return; }
  if (!Object.keys(fields).length) { toast("Nenhum campo informado.", true); return; }
  state.sending = true;
  try {
    const preview = await post(`/api/devices/${encodeURIComponent(state.selected)}/preview`, { fields });
    if ((preview.unknown_fields || []).length) {
      toast(`Campos não suportados: ${preview.unknown_fields.join(", ")}`, true);
      return;
    }
    const settingChanges = preview.changes || [];
    let companyFields = {};
    let companyChanges = [];
    if (includeCompany) {
      companyFields = collectFields($id("company-editor"), { onlyChanged: false });
      if (Object.keys(companyFields).length) {
        const companyPreview = await post(`/api/devices/${encodeURIComponent(state.selected)}/company`, {
          fields: companyFields, confirm: false
        });
        companyChanges = (companyPreview.changes || []).map(c => ({ ...c, field: `company.${c.field}` }));
      }
    }
    const changes = [...settingChanges, ...companyChanges];
    if (!changes.length) { toast("Nenhuma alteração para enviar."); return; }
    $id("detail-msg").innerHTML = `<strong>${esc(label)}</strong>` + diffTable(changes);
    if (!confirm(`${label}: enviar ${changes.length} alteração(ões) para ${state.selected}?`)) return;

    const operator = $id("operator").value;
    if (settingChanges.length) {
      await post(`/api/devices/${encodeURIComponent(state.selected)}/apply`, {
        fields, confirm: true, operator
      });
    }
    if (companyChanges.length) {
      await post(`/api/devices/${encodeURIComponent(state.selected)}/company`, {
        fields: companyFields, confirm: true, operator
      });
    }
    toast(`${label}: ${changes.length} campo(s) enviados.`);
    $id("detail-msg").textContent = `${changes.length} campo(s) enviados para o dispositivo.`;
    await openDevice(state.selected, false);
  } catch (e) { toast(e.message, true); }
  finally { state.sending = false; }
}

function applyAll() {
  const fields = collectFields($id("detail-editor"), { onlyChanged: false });
  sendFields(fields, "Enviar todas as abas para o Dispositivo", true);
}

async function saveDeviceProfile() {
  if (!state.selected) { toast("Selecione um equipamento.", true); return; }
  const name = $id("save-profile-name").value.trim();
  if (!name) { toast("Informe o nome do modelo.", true); return; }
  const path = `/api/devices/${encodeURIComponent(state.selected)}/save-profile`;
  const payload = {
    name,
    description: $id("save-profile-desc").value.trim(),
    include_company: $id("save-profile-company").checked,
    operator: $id("operator").value,
    fields: collectFields($id("detail-editor"), { onlyChanged: false }),
    company: collectFields($id("company-editor"), { onlyChanged: false }),
    confirm: false
  };
  try {
    const preview = await post(path, payload);
    const entries = Object.entries(preview.fields || {});
    const sample = entries.slice(0, 12)
      .map(([key, value]) => `<code>${esc(key)}</code>: ${esc(value)}`).join("<br>") || "Nenhum campo";
    $id("save-profile-msg").innerHTML =
      `<strong>Prévia do modelo "${esc(preview.name)}"</strong><br>` +
      `${preview.fields_count} campo(s), ${preview.company_count} dado(s) da empresa.<br>${sample}` +
      (entries.length > 12 ? "<br>..." : "");
    if (!confirm(`Salvar ${preview.fields_count} campo(s) como modelo "${name}"?`)) return;
    payload.confirm = true;
    const saved = await post(path, payload);
    state.profiles = await api("/api/profiles");
    renderProfiles();
    selectProfile(saved.profile.name);
    $id("save-profile-msg").textContent = `Modelo "${saved.profile.name}" salvo.`;
    toast("Modelo salvo a partir do equipamento.");
  } catch (e) { toast(e.message, true); }
}

function applyCategory(key) {
  const box = document.querySelector(`#detail-editor .category[data-category="${key}"]`);
  if (!box) return;
  const cat = state.categories.find(c => c.key === key);
  sendFields(collectFields(box, { onlyChanged: false }), `Enviar para o Dispositivo — ${cat?.label || key}`);
}

async function diffProfile() {
  const p = $id("diff-profile").value;
  if (!state.selected || !p) { toast("Selecione equipamento e modelo.", true); return; }
  try {
    const r = await api(`/api/devices/${encodeURIComponent(state.selected)}/diff?profile=${encodeURIComponent(p)}`);
    renderDiff($id("diff-result"), r.changes);
  } catch (e) { toast(e.message, true); }
}

function setProgress(percent, text) {
  $id("firmware-progress-bar").style.width = `${Math.max(0, Math.min(100, Number(percent) || 0))}%`;
  $id("firmware-progress-text").textContent = text || "";
}

function localFirmwareForm(confirmSend, includeDescription = false) {
  const file = $id("firmware-file").files[0];
  if (!file) { toast("Selecione um arquivo .zip ou .pkg.", true); return null; }
  const form = new FormData();
  form.append("file", file);
  form.append("confirm", confirmSend ? "true" : "false");
  if (includeDescription) form.append("description", $id("firmware-description").value);
  else form.append("operator", $id("firmware-operator").value);
  return form;
}

function libraryFirmwareForm(confirmSend) {
  const firmwareId = $id("firmware-library").value;
  if (!firmwareId) { toast("Escolha um arquivo salvo na biblioteca.", true); return null; }
  const form = new FormData();
  form.append("firmware_id", firmwareId);
  form.append("confirm", confirmSend ? "true" : "false");
  form.append("operator", $id("firmware-operator").value);
  return form;
}

function firmwareSummary(r) {
  return `${esc(r.filename)} — ${esc(formatBytes(r.size))} — ${r.chunks} chunk(s) — ` +
    `MD5 <code>${esc(r.md5)}</code>. ${esc(r.message || "")}`;
}

async function loadFirmwareLibrary(selectedId = null) {
  state.firmwareFiles = await api("/api/firmware");
  const select = $id("firmware-library");
  select.innerHTML = '<option value="">— Nenhum —</option>' + state.firmwareFiles.map(f =>
    `<option value="${esc(f.id)}">${esc(f.filename)} — ${esc(formatBytes(f.size))}` +
    `${f.description ? " — " + esc(f.description) : ""}</option>`
  ).join("");
  if (selectedId && state.firmwareFiles.some(f => f.id === selectedId)) select.value = selectedId;
}

async function validateFirmware() {
  if (!state.selected) { toast("Selecione um equipamento.", true); return; }
  const form = localFirmwareForm(false);
  if (!form) return;
  try {
    const r = await api(`/api/devices/${encodeURIComponent(state.selected)}/firmware`, { method: "POST", body: form });
    $id("firmware-msg").innerHTML = firmwareSummary(r);
    setProgress(0, "Arquivo validado. Confirme o envio.");
  } catch (e) { toast(e.message, true); }
}

async function saveFirmwareLibrary() {
  const previewForm = localFirmwareForm(false, true);
  if (!previewForm) return;
  try {
    const preview = await api("/api/firmware", { method: "POST", body: previewForm });
    $id("firmware-library-msg").innerHTML = `Prévia: ${firmwareSummary(preview)}`;
    if (!confirm(`Salvar "${preview.filename}" (${formatBytes(preview.size)}) na biblioteca?`)) return;
    const confirmForm = localFirmwareForm(true, true);
    if (!confirmForm) return;
    const saved = await api("/api/firmware", { method: "POST", body: confirmForm });
    await loadFirmwareLibrary(saved.id);
    $id("firmware-library-msg").textContent = `Salvo: ${saved.filename} (MD5 ${saved.md5}).`;
    toast("Arquivo salvo na biblioteca.");
  } catch (e) { toast(e.message, true); }
}

async function pollFirmware(jobId) {
  try {
    const s = await api(`/api/devices/${encodeURIComponent(state.selected)}/firmware/jobs/${jobId}`);
    setProgress(s.percent || 0, `${s.status}: ${s.message} (${formatBytes(s.uploaded)} / ${formatBytes(s.total)})`);
    if (s.status === "done" || s.status === "error") {
      clearInterval(state.firmwareTimer);
      state.firmwareTimer = null;
      if (s.status === "done") {
        toast("Firmware enviado com sucesso.");
        $id("firmware-msg").textContent = `Concluído: ${s.filename} (MD5 ${s.md5}).`;
      } else {
        toast(s.message, true);
        $id("firmware-msg").textContent = s.message;
      }
    }
  } catch (e) {
    clearInterval(state.firmwareTimer);
    state.firmwareTimer = null;
    toast(e.message, true);
  }
}

function startFirmwareJob(r) {
  $id("firmware-msg").textContent = `Envio iniciado (job ${r.job_id}).`;
  setProgress(0, "Iniciando...");
  if (state.firmwareTimer) clearInterval(state.firmwareTimer);
  state.firmwareTimer = setInterval(() => pollFirmware(r.job_id), 700);
  pollFirmware(r.job_id);
}

async function uploadFirmware() {
  if (!state.selected) { toast("Selecione um equipamento.", true); return; }
  const file = $id("firmware-file").files[0];
  if (!file) { toast("Selecione um arquivo .zip ou .pkg.", true); return; }
  if (!confirm(`Enviar o firmware "${file.name}" para ${state.selected}? O equipamento pode reiniciar.`)) return;
  const form = localFirmwareForm(true);
  if (!form) return;
  try {
    const r = await api(`/api/devices/${encodeURIComponent(state.selected)}/firmware`, { method: "POST", body: form });
    startFirmwareJob(r);
  } catch (e) { toast(e.message, true); }
}

async function uploadSavedFirmware() {
  if (!state.selected) { toast("Selecione um equipamento.", true); return; }
  const path = `/api/devices/${encodeURIComponent(state.selected)}/firmware`;
  const previewForm = libraryFirmwareForm(false);
  if (!previewForm) return;
  try {
    const preview = await api(path, { method: "POST", body: previewForm });
    $id("firmware-msg").innerHTML = `Prévia: ${firmwareSummary(preview)}`;
    if (!confirm(`Enviar "${preview.filename}" para ${state.selected}? O equipamento pode reiniciar.`)) return;
    const form = libraryFirmwareForm(true);
    if (!form) return;
    const r = await api(path, { method: "POST", body: form });
    startFirmwareJob(r);
  } catch (e) { toast(e.message, true); }
}

async function deleteSavedFirmware() {
  const firmwareId = $id("firmware-library").value;
  if (!firmwareId) { toast("Escolha um arquivo salvo na biblioteca.", true); return; }
  const item = state.firmwareFiles.find(f => f.id === firmwareId);
  if (!confirm(`Excluir "${item?.filename || firmwareId}" da biblioteca?`)) return;
  try {
    const r = await api(`/api/firmware/${encodeURIComponent(firmwareId)}?confirm=true`, { method: "DELETE" });
    await loadFirmwareLibrary();
    $id("firmware-library-msg").textContent = `Excluído: ${r.filename}.`;
    toast("Arquivo excluído da biblioteca.");
  } catch (e) { toast(e.message, true); }
}

function renderProfiles() {
  const list = $id("profile-list");
  list.innerHTML = state.profiles.map(p => `<li data-profile="${esc(p.name)}" class="${state.profile === p.name ? "selected" : ""}">${esc(p.name)}<br><small>${esc(p.description || "")}</small></li>`).join("");
  list.querySelectorAll("li").forEach(li => li.addEventListener("click", () => selectProfile(li.dataset.profile)));
  const options = state.profiles.map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join("");
  $id("diff-profile").innerHTML = options;
  $id("bulk-profile").innerHTML = options;
}

function selectProfile(name) {
  const p = state.profiles.find(x => x.name === name);
  if (!p) return;
  state.profile = name;
  $id("profile-name").value = p.name;
  $id("profile-desc").value = p.description || "";
  $id("profile-json").value = JSON.stringify({ fields: p.fields || {}, company: p.company || {} }, null, 2);
  $id("profile-msg").textContent = "";
  renderProfiles();
}

async function saveProfile() {
  try {
    const doc = JSON.parse($id("profile-json").value || "{}");
    const p = {
      name: $id("profile-name").value.trim(), description: $id("profile-desc").value,
      fields: doc.fields || doc, company: doc.company || {}
    };
    await post("/api/profiles", p);
    state.profiles = await api("/api/profiles");
    selectProfile(p.name);
    toast("Modelo salvo.");
  } catch (e) { toast(e.message, true); }
}

async function deleteProfile() {
  const name = $id("profile-name").value.trim();
  if (!name || !confirm(`Excluir o modelo "${name}"?`)) return;
  try {
    await api(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" });
    state.profiles = await api("/api/profiles");
    state.profile = null;
    $id("profile-name").value = "";
    $id("profile-json").value = "";
    renderProfiles();
    toast("Modelo excluído.");
  } catch (e) { toast(e.message, true); }
}

function selectedDeviceIds() {
  return [...document.querySelectorAll(".dev-check:checked")].map(x => x.value);
}

function renderBulkDeviceList() {
  if (!state.devices.length) $id("bulk-result").innerHTML = "<p class='msg'>Cadastre equipamentos para aplicar em lote.</p>";
}

async function bulkApply(confirmApply) {
  const profile = $id("bulk-profile").value;
  if (!profile) { toast("Selecione um modelo.", true); return; }
  const ids = selectedDeviceIds();
  if (!ids.length) { toast("Selecione ao menos um equipamento na aba Equipamentos.", true); return; }
  if (confirmApply && !confirm(`Aplicar o modelo "${profile}" em ${ids.length} equipamento(s)?`)) return;
  try {
    const r = await post("/api/bulk/apply", {
      profile, device_ids: ids, confirm: confirmApply,
      include_company: $id("bulk-company").checked, operator: $id("bulk-operator").value
    });
    const rows = r.results.map(x => `<tr><td>${esc(x.device_id)}</td><td>${esc(x.host)}</td><td>${x.error ? badge("Erro", "bad") : x.applied ? badge("Aplicado", "ok") : badge("Prévia")}</td><td>${x.error ? esc(x.error) : (x.changes || []).map(c => `<code>${esc(c.field)}</code>: ${esc(c.before)} → ${esc(c.after)}`).join("<br>") || "Sem alterações"}</td></tr>`).join("");
    $id("bulk-result").innerHTML = `<table><thead><tr><th>Equipamento</th><th>IP</th><th>Resultado</th><th>Detalhes</th></tr></thead><tbody>${rows}</tbody></table>`;
    toast(confirmApply ? "Aplicação em lote concluída." : "Prévia gerada.");
  } catch (e) { toast(e.message, true); }
}

function showAddDevice() {
  const box = document.createElement("div");
  box.className = "panel";
  box.style.marginTop = "14px";
  box.innerHTML = `<h3>Novo equipamento</h3>
    <div class="row wrap">
      <label>ID <input id="new-id" placeholder="relogio-02"></label>
      <label>Nome <input id="new-label" placeholder="Relógio 02"></label>
      <label>IP <input id="new-host" placeholder="192.168.1.39"></label>
      <label>Porta <input id="new-port" type="number" value="80"></label>
      <label>Senha <input id="new-password" value="123"></label>
      <button id="new-save" class="primary">Salvar</button>
      <button id="new-cancel" class="ghost">Cancelar</button>
    </div>`;
  $id("sec-devices").appendChild(box);
  $id("new-cancel").onclick = () => box.remove();
  $id("new-save").onclick = async () => {
    try {
      await post("/api/devices", {
        id: $id("new-id").value.trim() || undefined,
        label: $id("new-label").value.trim(),
        host: $id("new-host").value.trim(),
        port: Number($id("new-port").value || 80),
        password: $id("new-password").value
      });
      box.remove();
      await loadDevices();
      toast("Equipamento cadastrado.");
    } catch (e) { toast(e.message, true); }
  };
}

async function loadHistory() {
  try {
    const items = await api("/api/history?limit=100");
    $id("history-rows").innerHTML = items.length ? items.map(h => `<tr>
      <td>${new Date(h.timestamp).toLocaleString("pt-BR")}</td><td>${esc(h.action)}</td>
      <td>${esc(h.host || "—")}</td><td>${esc(h.operator || "—")}</td>
      <td>${(h.changes || []).map(c => `<code>${esc(c.field)}</code>: ${esc(c.before)} → ${esc(c.after)}`).join("<br>") || esc(h.filename || "—")}</td>
    </tr>`).join("") : '<tr><td colspan="5">Nenhuma alteração registrada.</td></tr>';
  } catch (e) { toast(e.message, true); }
}

function switchSection(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.section === name));
  document.querySelectorAll(".section").forEach(s => s.classList.toggle("active", s.id === `sec-${name}`));
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
    switchSection(t.dataset.section);
    if (t.dataset.section === "history") loadHistory();
  }));
  $id("token").value = token();
  $id("token").addEventListener("change", e => {
    localStorage.setItem("aiface_token", e.target.value);
    toast("Token salvo neste navegador.");
  });
  $id("btn-refresh").onclick = refreshStatus;
  $id("btn-add-device").onclick = showAddDevice;
  $id("btn-load-config").onclick = () => openDevice($id("detail-device").value);
  $id("btn-preview").onclick = previewAll;
  $id("btn-apply-all").onclick = applyAll;
  $id("btn-save-device-profile").onclick = saveDeviceProfile;
  $id("btn-diff").onclick = diffProfile;
  $id("btn-firmware-preview").onclick = validateFirmware;
  $id("btn-firmware-save").onclick = saveFirmwareLibrary;
  $id("btn-firmware-upload").onclick = uploadFirmware;
  $id("btn-firmware-library-upload").onclick = uploadSavedFirmware;
  $id("btn-firmware-library-delete").onclick = deleteSavedFirmware;
  $id("btn-new-profile").onclick = () => {
    state.profile = null;
    $id("profile-name").value = "";
    $id("profile-desc").value = "";
    $id("profile-json").value = JSON.stringify({ fields: {}, company: {} }, null, 2);
    renderProfiles();
  };
  $id("btn-save-profile").onclick = saveProfile;
  $id("btn-delete-profile").onclick = deleteProfile;
  $id("btn-bulk-preview").onclick = () => bulkApply(false);
  $id("btn-bulk-apply").onclick = () => bulkApply(true);
}

async function init() {
  bindEvents();
  try {
    state.meta = await api("/api/meta");
    if (state.meta.auth_required && !token()) toast("Este servidor exige token API. Informe-o no topo.");
    [state.devices, state.profiles] = await Promise.all([api("/api/devices"), api("/api/profiles")]);
    renderDevices(state.devices);
    $id("detail-device").innerHTML = state.devices.map(d => `<option value="${esc(d.id)}">${esc(d.label || d.id)} (${esc(d.host)})</option>`).join("");
    renderProfiles();
    renderBulkDeviceList();
    await loadFirmwareLibrary();
    if (state.devices.length) await openDevice(state.devices[0].id, false);
  } catch (e) { toast(e.message, true); }
}

init();
