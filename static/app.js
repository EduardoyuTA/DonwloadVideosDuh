const toast = document.getElementById("toast");
const toastMsg = document.getElementById("toastMsg");
const pasteBtn = document.getElementById("pasteBtn");
const formatChoiceInput = document.getElementById("formatChoice");
const downloadModeInput = document.getElementById("downloadMode");
const modeTabs = document.querySelectorAll(".mode-tab");
const modeAlert = document.getElementById("modeAlert");
const formatTabs = document.querySelectorAll(".tab");
const formatHelp = document.getElementById("formatHelp");
const qualityHelp = document.getElementById("qualityHelp");
const qualitySelect = document.getElementById("quality_choice");
const qualityOptionsData = document.getElementById("qualityOptionsData");
const appConfigData = document.getElementById("appConfigData");
const videoOptionCard = document.getElementById("videoOptionCard");
const mirrorVideoCheckbox = document.getElementById("mirror_video");
const mirrorFileSuffix = document.getElementById("mirrorFileSuffix");
const musicOptionCard = document.getElementById("musicOptionCard");
const bpmIntroCheckbox = document.getElementById("add_bpm_intro");
const outputDirInput = document.getElementById("output_dir");
const videoUrlInput = document.getElementById("video_url");
const downloadForm = document.getElementById("download-form");
const submitButton = downloadForm ? downloadForm.querySelector(".download-btn") : null;

const previewPanel = document.getElementById("previewPanel");
const previewPlatform = document.getElementById("previewPlatform");
const previewThumb = document.getElementById("previewThumb");
const previewThumbFallback = document.getElementById("previewThumbFallback");
const previewTitle = document.getElementById("previewTitle");
const previewUploader = document.getElementById("previewUploader");
const previewDuration = document.getElementById("previewDuration");
const previewSelection = document.getElementById("previewSelection");
const previewSize = document.getElementById("previewSize");

const jobsList = document.getElementById("jobsList");
const jobsEmpty = document.getElementById("jobsEmpty");
const queueCount = document.getElementById("queueCount");

const historyList = document.getElementById("historyList");
const historyEmpty = document.getElementById("historyEmpty");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");

const STORAGE_KEY = "videoflow-preferences-v5";
const TERMINAL_STATUSES = new Set(["completed", "failed"]);
const canMirrorVideos = mirrorVideoCheckbox?.dataset.available === "true";
const appConfig = (() => {
  if (!appConfigData) {
    return {};
  }

  try {
    const parsed = JSON.parse(appConfigData.textContent || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
})();
const isHostedMode = appConfig.hosted_mode === true;
const isLocalYoutubeAvailable = appConfig.local_youtube_available === true;
const qualityOptionsByFormat = (() => {
  if (!qualityOptionsData) {
    return {};
  }

  try {
    const parsed = JSON.parse(qualityOptionsData.textContent || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
})();
const defaultQualityChoices = Object.fromEntries(
  Object.entries(qualityOptionsByFormat).map(([format, options]) => [
    format,
    Array.isArray(options) && options.length ? options[0].value : "best",
  ]),
);

const state = {
  preview: null,
  previewKey: null,
  previewTimer: null,
  previewRequestId: 0,
  jobStatuses: new Map(),
  qualityChoices: { ...defaultQualityChoices },
  addBpmIntro: false,
  mirrorVideo: false,
  downloadMode: downloadModeInput ? downloadModeInput.value : "online",
};

function buildRestartRequiredMessage(featureLabel) {
  return `O backend atual ainda nao reconhece a opcao "${featureLabel}". Feche a janela antiga do servidor e inicie o app novamente.`;
}

function ensurePreviewSupportsRequestedOptions(payload, preview) {
  if (
    payload.mirror_video &&
    !(
      preview?.mirror_video === true ||
      String(preview?.selection_summary || "").includes("Video espelhado")
    )
  ) {
    throw new Error(buildRestartRequiredMessage("Espelhar video"));
  }

  if (
    payload.add_bpm_intro &&
    !(
      preview?.add_bpm_intro === true ||
      String(preview?.selection_summary || "").includes("Contagem BPM 75")
    )
  ) {
    throw new Error(
      buildRestartRequiredMessage("Adicionar contagem inicial BPM 75"),
    );
  }
}

function ensureJobSupportsRequestedOptions(payload, job) {
  if (payload.mirror_video && job?.mirror_video !== true) {
    throw new Error(buildRestartRequiredMessage("Espelhar video"));
  }

  if (payload.add_bpm_intro && job?.add_bpm_intro !== true) {
    throw new Error(
      buildRestartRequiredMessage("Adicionar contagem inicial BPM 75"),
    );
  }
}

function showToast(message) {
  if (!toast || !toastMsg) {
    return;
  }

  toastMsg.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.classList.remove("show");
  }, 2800);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const urlInTextPattern =
  /(https?:\/\/[^\s<>'"`]+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s<>'"`]*)?)/i;
const trailingUrlPunctuationPattern = /[.,;:!?\])}]+$/;

function normalizeVideoUrl(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue) {
    return "";
  }

  const match = rawValue.match(urlInTextPattern);
  let candidate = (match ? match[0] : rawValue)
    .trim()
    .replace(trailingUrlPunctuationPattern, "");

  if (candidate.startsWith("//")) {
    return `https:${candidate}`;
  }

  try {
    const url = new URL(candidate);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return candidate;
    }
  } catch {
    // A proxima etapa tenta tratar links colados sem o protocolo.
  }

  if (/^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/:?#]|$)/i.test(candidate)) {
    return `https://${candidate}`;
  }

  return candidate;
}

function isValidUrl(value) {
  try {
    const url = new URL(normalizeVideoUrl(value));
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function getUrlHostname(value) {
  try {
    return new URL(normalizeVideoUrl(value)).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function isYoutubeUrl(value) {
  const hostname = getUrlHostname(value);
  return hostname === "youtu.be" || hostname.endsWith(".youtube.com");
}

function getModeValidationMessage(payload = currentPayload()) {
  if (!isValidUrl(payload.video_url)) {
    return "";
  }

  if (payload.download_mode === "online" && isYoutubeUrl(payload.video_url)) {
    return "Modo Online nao baixa links do YouTube. Selecione Downloads YouTube no app local do PC.";
  }

  if (payload.download_mode === "youtube" && !isLocalYoutubeAvailable) {
    return "Downloads YouTube precisam do app local rodando no PC. Abra o iniciar_app.bat e use esse modo por la.";
  }

  if (payload.download_mode === "youtube" && !isYoutubeUrl(payload.video_url)) {
    return "O modo Downloads YouTube aceita apenas links do YouTube.";
  }

  if (
    isHostedMode &&
    payload.mirror_video &&
    payload.format_choice !== "mp3" &&
    !["720", "480"].includes(payload.quality_choice)
  ) {
    return "No modo online, o espelhamento fica estavel apenas em 720p ou 480p. Escolha uma dessas qualidades ou use o app local para espelhar em qualidade maior.";
  }

  return "";
}

function modeHelperMessage(mode = state.downloadMode) {
  if (mode === "youtube") {
    return isLocalYoutubeAvailable
      ? "Modo YouTube local ativo: o download roda neste PC e entra no historico do app."
      : "Modo YouTube disponivel apenas no app local do PC. No site online, use links diretos que nao sejam YouTube.";
  }

  return "Modo Online ativo: use links diretos e plataformas permitidas. YouTube fica separado no modo local.";
}

function renderModeAlert(message = modeHelperMessage()) {
  if (!modeAlert) {
    return;
  }

  modeAlert.hidden = !message;
  modeAlert.textContent = message;
}

function formatLocalDate(isoDate) {
  if (!isoDate) {
    return "--";
  }

  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) {
    return isoDate;
  }

  return parsed.toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function currentPayload() {
  const activeFormat = formatChoiceInput ? formatChoiceInput.value : "mp4";
  return {
    video_url: normalizeVideoUrl(videoUrlInput ? videoUrlInput.value : ""),
    output_dir: !isHostedMode && outputDirInput ? outputDirInput.value.trim() : "",
    download_mode: downloadModeInput ? downloadModeInput.value : state.downloadMode,
    format_choice: activeFormat,
    quality_choice: qualitySelect ? qualitySelect.value : "best",
    mirror_video:
      activeFormat !== "mp3" && mirrorVideoCheckbox
        ? mirrorVideoCheckbox.checked
        : false,
    add_bpm_intro:
      activeFormat === "mp3" && bpmIntroCheckbox ? bpmIntroCheckbox.checked : false,
  };
}

function getQualityOptions(format) {
  const options = qualityOptionsByFormat[format];
  if (Array.isArray(options) && options.length) {
    return options;
  }

  return Array.isArray(qualityOptionsByFormat.mp4)
    ? qualityOptionsByFormat.mp4
    : [];
}

function pickQualityValue(format, preferredValue = null) {
  const options = getQualityOptions(format);
  const allowedValues = new Set(options.map((option) => option.value));
  const fallbackValue = state.qualityChoices[format];
  const selectedValue = preferredValue || fallbackValue;

  if (selectedValue && allowedValues.has(selectedValue)) {
    return selectedValue;
  }

  return options[0] ? options[0].value : "best";
}

function getPreviewKey(payload = currentPayload()) {
  return [
    payload.video_url,
    payload.format_choice,
    payload.download_mode,
    payload.quality_choice,
    payload.mirror_video,
    payload.add_bpm_intro,
  ].join("|");
}

function savePreferences() {
  if (!window.localStorage) {
    return;
  }

  const payload = currentPayload();
  state.qualityChoices[payload.format_choice] = payload.quality_choice;
  const preferenceData = {
    format_choice: payload.format_choice,
    download_mode: payload.download_mode,
    quality_choice: payload.quality_choice,
    quality_choices: state.qualityChoices,
    add_bpm_intro: state.addBpmIntro,
    mirror_video: state.mirrorVideo,
  };

  if (!isHostedMode) {
    preferenceData.output_dir = payload.output_dir;
  }

  localStorage.setItem(STORAGE_KEY, JSON.stringify(preferenceData));
}

function loadPreferences() {
  if (!window.localStorage) {
    syncFormatState(formatChoiceInput ? formatChoiceInput.value : "mp4");
    syncDownloadModeState(state.downloadMode);
    return;
  }

  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      syncFormatState(formatChoiceInput ? formatChoiceInput.value : "mp4");
      syncDownloadModeState(state.downloadMode);
      return;
    }

    const data = JSON.parse(raw);
    if (data.quality_choices && typeof data.quality_choices === "object") {
      Object.entries(data.quality_choices).forEach(([format, quality]) => {
        if (typeof quality === "string") {
          state.qualityChoices[format] = quality;
        }
      });
    }
    if (
      !isHostedMode &&
      outputDirInput &&
      typeof data.output_dir === "string" &&
      data.output_dir
    ) {
      outputDirInput.value = data.output_dir;
    }
    if (typeof data.add_bpm_intro === "boolean") {
      state.addBpmIntro = data.add_bpm_intro;
      if (bpmIntroCheckbox) {
        bpmIntroCheckbox.checked = data.add_bpm_intro;
      }
    }
    if (typeof data.mirror_video === "boolean") {
      state.mirrorVideo = data.mirror_video;
      if (mirrorVideoCheckbox) {
        mirrorVideoCheckbox.checked = data.mirror_video;
      }
    }
    if (typeof data.download_mode === "string") {
      state.downloadMode = data.download_mode;
    }

    const initialFormat =
      typeof data.format_choice === "string"
        ? data.format_choice
        : formatChoiceInput
          ? formatChoiceInput.value
          : "mp4";

    if (
      typeof data.quality_choice === "string" &&
      (!data.quality_choices || typeof data.quality_choices !== "object")
    ) {
      state.qualityChoices[initialFormat] = data.quality_choice;
    }

    if (typeof data.format_choice === "string") {
      syncFormatState(data.format_choice);
      syncDownloadModeState(state.downloadMode);
      return;
    }
  } catch {
    // Ignora preferencias corrompidas e segue com o default.
  }

  syncFormatState(formatChoiceInput ? formatChoiceInput.value : "mp4");
  syncDownloadModeState(state.downloadMode);
}

function setPreviewLoading() {
  if (!previewPanel) {
    return;
  }

  previewPanel.hidden = false;
  previewPanel.classList.add("is-loading");
  previewPanel.classList.remove("is-error");
  previewPlatform.textContent = "Analisando link";
  previewTitle.textContent = "Buscando metadados do video...";
  previewUploader.textContent =
    "Titulo, thumbnail, plataforma e estimativa de tamanho aparecem em instantes.";
  previewDuration.textContent = "--";
  previewSelection.textContent = "--";
  previewSize.textContent = "--";
  previewThumb.hidden = true;
  previewThumb.removeAttribute("src");
  previewThumbFallback.hidden = false;
}

function clearPreview() {
  state.preview = null;
  state.previewKey = null;

  if (!previewPanel) {
    return;
  }

  previewPanel.hidden = true;
  previewPanel.classList.remove("is-loading", "is-error");
}

function renderPreview(preview) {
  if (!previewPanel) {
    return;
  }

  previewPanel.hidden = false;
  previewPanel.classList.remove("is-loading", "is-error");
  previewPlatform.textContent = preview.platform_label || "Link";
  previewTitle.textContent = preview.title || "Video";
  previewUploader.textContent =
    preview.uploader || "Origem nao identificada";
  previewDuration.textContent = preview.duration_label || "Duracao indisponivel";
  previewSelection.textContent = preview.selection_summary || "--";
  previewSize.textContent =
    preview.filesize_estimate_label || "Tamanho aproximado indisponivel";

  if (preview.thumbnail_url) {
    previewThumb.src = preview.thumbnail_url;
    previewThumb.hidden = false;
    previewThumbFallback.hidden = true;
  } else {
    previewThumb.hidden = true;
    previewThumb.removeAttribute("src");
    previewThumbFallback.hidden = false;
  }
}

function renderPreviewError(message) {
  if (!previewPanel) {
    return;
  }

  previewPanel.hidden = false;
  previewPanel.classList.remove("is-loading");
  previewPanel.classList.add("is-error");
  previewPlatform.textContent = "Preview indisponivel";
  previewTitle.textContent = "Nao foi possivel analisar esse link agora.";
  previewUploader.textContent = message;
  previewDuration.textContent = "--";
  previewSelection.textContent = "--";
  previewSize.textContent = "--";
  previewThumb.hidden = true;
  previewThumb.removeAttribute("src");
  previewThumbFallback.hidden = false;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.error || "Nao foi possivel concluir essa operacao.");
  }

  return payload;
}

async function requestPreview({ force = false, silent = false } = {}) {
  const payload = currentPayload();
  if (!isValidUrl(payload.video_url)) {
    if (!silent) {
      clearPreview();
    }
    return null;
  }

  const modeMessage = getModeValidationMessage(payload);
  if (modeMessage) {
    state.preview = null;
    state.previewKey = null;
    renderPreviewError(modeMessage);
    renderModeAlert(modeMessage);
    if (!silent) {
      showToast(modeMessage);
    }
    return null;
  }

  renderModeAlert(modeHelperMessage(payload.download_mode));

  const previewKey = getPreviewKey(payload);
  if (!force && state.previewKey === previewKey && state.preview) {
    renderPreview(state.preview);
    return state.preview;
  }

  const requestId = ++state.previewRequestId;
  setPreviewLoading();

  try {
    const data = await fetchJson("/api/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (requestId !== state.previewRequestId) {
      return null;
    }

    ensurePreviewSupportsRequestedOptions(payload, data.preview);
    state.preview = data.preview;
    state.previewKey = previewKey;
    renderPreview(data.preview);
    return data.preview;
  } catch (error) {
    if (requestId !== state.previewRequestId) {
      return null;
    }

    state.preview = null;
    state.previewKey = null;
    renderPreviewError(error.message);
    if (!silent) {
      showToast(error.message);
    }
    return null;
  }
}

function schedulePreview(delay = 700) {
  clearTimeout(state.previewTimer);
  if (!videoUrlInput || !isValidUrl(videoUrlInput.value.trim())) {
    clearPreview();
    renderModeAlert(modeHelperMessage());
    return;
  }

  const payload = currentPayload();
  const modeMessage = getModeValidationMessage(payload);
  if (modeMessage) {
    renderPreviewError(modeMessage);
    renderModeAlert(modeMessage);
    return;
  }

  state.previewTimer = window.setTimeout(() => {
    requestPreview({ silent: true });
  }, delay);
}

function updateQualityHelp() {
  if (!qualityHelp || !qualitySelect) {
    return;
  }

  const selectedOption = qualitySelect.options[qualitySelect.selectedIndex];
  qualityHelp.textContent =
    selectedOption?.dataset.description ||
    "Escolha o preset que melhor combina com a qualidade final que voce quer.";
}

function syncMusicOptionState(format) {
  const isMusic = format === "mp3";

  if (musicOptionCard) {
    musicOptionCard.hidden = !isMusic;
  }

  if (!bpmIntroCheckbox) {
    return;
  }

  bpmIntroCheckbox.disabled = !isMusic;
  if (isMusic) {
    bpmIntroCheckbox.checked = state.addBpmIntro;
    return;
  }

  bpmIntroCheckbox.checked = false;
}

function syncDownloadModeState(mode) {
  const normalizedMode = mode === "youtube" ? "youtube" : "online";
  state.downloadMode = normalizedMode;

  if (downloadModeInput) {
    downloadModeInput.value = normalizedMode;
  }

  modeTabs.forEach((tab) => {
    const isActive = tab.dataset.downloadMode === normalizedMode;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-pressed", isActive ? "true" : "false");
  });

  renderModeAlert(modeHelperMessage(normalizedMode));
}

function syncVideoOptionState(format) {
  const isVideo = format !== "mp3";

  if (mirrorFileSuffix) {
    mirrorFileSuffix.textContent = `_espelhado.${isVideo ? format : "mp4"}`;
  }

  if (videoOptionCard) {
    videoOptionCard.hidden = !isVideo;
  }

  if (!mirrorVideoCheckbox) {
    return;
  }

  const canEnable = isVideo && canMirrorVideos;
  mirrorVideoCheckbox.disabled = !canEnable;
  if (canEnable) {
    mirrorVideoCheckbox.checked = state.mirrorVideo;
    return;
  }

  mirrorVideoCheckbox.checked = false;
}

function renderQualityOptions(format, preferredValue = null) {
  if (!qualitySelect) {
    return;
  }

  const options = getQualityOptions(format);
  const nextValue = pickQualityValue(format, preferredValue);
  qualitySelect.innerHTML = "";

  options.forEach((option) => {
    const optionElement = document.createElement("option");
    optionElement.value = option.value;
    optionElement.textContent = option.label;
    optionElement.dataset.description = option.description || "";
    optionElement.selected = option.value === nextValue;
    qualitySelect.append(optionElement);
  });

  qualitySelect.value = nextValue;
  state.qualityChoices[format] = nextValue;
  updateQualityHelp();
}

function syncFormatState(format) {
  if (!formatChoiceInput) {
    return;
  }

  formatChoiceInput.value = format;

  formatTabs.forEach((tab) => {
    const isActive = tab.dataset.format === format;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-pressed", isActive ? "true" : "false");
  });

  const activeTab = Array.from(formatTabs).find(
    (tab) => tab.dataset.format === format,
  );
  if (activeTab && formatHelp) {
    formatHelp.textContent = activeTab.dataset.description || "";
  }

  renderQualityOptions(format);
  syncVideoOptionState(format);
  syncMusicOptionState(format);
}

function downloadActionMarkup(downloadUrl) {
  const safeUrl = escapeHtml(downloadUrl);
  return `<a class="file-action" href="${safeUrl}" download>Baixar arquivo</a>`;
}

function renderJobCard(job) {
  const progress = Math.max(0, Math.min(Number(job.progress_pct || 0), 100));
  const statusClass = job.status === "failed" ? "error" : "highlight";
  const queueLabel =
    job.status === "queued" && job.queue_position
      ? `Posicao ${job.queue_position}`
      : job.status_label || "Processando";

  return `
    <article class="job-card">
      <div class="job-head">
        <div class="job-title-wrap">
          <h4 class="job-title">${escapeHtml(job.title)}</h4>
          <div class="job-subtitle">${escapeHtml(job.platform_label || "Link")} - ${escapeHtml(job.selection_summary || "--")}</div>
        </div>

        <div class="job-pills">
          <span class="job-pill ${statusClass}">${escapeHtml(queueLabel)}</span>
          ${
            job.error
              ? `<span class="job-pill error">${escapeHtml(job.error)}</span>`
              : ""
          }
        </div>
      </div>

      <div class="job-progress">
        <div class="job-progress-bar" style="width: ${progress}%"></div>
      </div>

      <div class="job-metrics">
        <div class="job-metric">
          <span>Progresso</span>
          <strong>${progress.toFixed(0)}%</strong>
        </div>
        <div class="job-metric">
          <span>Transferido</span>
          <strong>${escapeHtml(job.downloaded_label || "--")} / ${escapeHtml(job.total_label || "--")}</strong>
        </div>
        <div class="job-metric">
          <span>Velocidade</span>
          <strong>${escapeHtml(job.speed_label || "--")}</strong>
        </div>
        <div class="job-metric">
          <span>ETA</span>
          <strong>${escapeHtml(job.eta_label || "--")}</strong>
        </div>
      </div>

      ${
        job.status === "completed" && job.download_url
          ? `<div class="job-actions">${downloadActionMarkup(job.download_url)}</div>`
          : ""
      }
    </article>
  `;
}

function renderJobs(jobs) {
  const visibleJobs = jobs.filter(
    (job) => job.status !== "completed" || (isHostedMode && job.download_url),
  );
  const activeCount = visibleJobs.filter((job) =>
    ["queued", "starting", "downloading", "processing"].includes(job.status),
  ).length;

  if (queueCount) {
    queueCount.textContent =
      activeCount === 1 ? "1 download ativo" : `${activeCount} downloads ativos`;
  }

  if (jobsEmpty) {
    jobsEmpty.hidden = visibleJobs.length > 0;
  }

  if (jobsList) {
    jobsList.innerHTML = visibleJobs.map(renderJobCard).join("");
  }
}

function historyThumbMarkup(entry) {
  if (entry.thumbnail_url) {
    return `<img class="history-thumb" src="${escapeHtml(entry.thumbnail_url)}" alt="${escapeHtml(entry.title || "Thumbnail do video")}" />`;
  }

  return `
    <div class="history-thumb-fallback">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <polygon points="5 3 19 12 5 21 5 3"></polygon>
      </svg>
    </div>
  `;
}

function renderHistoryItem(entry) {
  const modeLabel =
    entry.download_mode === "youtube" ? "YouTube local" : "Online";
  const pathMarkup =
    !isHostedMode && entry.file_path
      ? `<div class="history-path">${escapeHtml(entry.file_path)}</div>`
      : "";
  const actionMarkup = entry.download_url
    ? `<div class="history-actions">${downloadActionMarkup(entry.download_url)}</div>`
    : "";

  return `
    <article class="history-item">
      <div class="history-head">
        ${historyThumbMarkup(entry)}
        <div class="history-copy">
          <h4 class="history-title">${escapeHtml(entry.title)}</h4>
          <p class="history-subtitle">${escapeHtml(entry.platform_label || "Link")} - ${escapeHtml(entry.selection_summary || "--")} - ${escapeHtml(modeLabel)}</p>
          <div class="history-meta">
            <span class="job-pill">${escapeHtml(entry.duration_label || "Duracao indisponivel")}</span>
            <span class="job-pill">${escapeHtml(formatLocalDate(entry.completed_at))}</span>
          </div>
          ${pathMarkup}
          ${actionMarkup}
        </div>
      </div>
    </article>
  `;
}

function renderHistory(entries) {
  if (historyEmpty) {
    historyEmpty.hidden = entries.length > 0;
  }

  if (historyList) {
    historyList.innerHTML = entries.map(renderHistoryItem).join("");
  }

  if (clearHistoryBtn) {
    clearHistoryBtn.disabled = entries.length === 0;
  }
}

async function refreshHistory() {
  try {
    const data = await fetchJson("/api/history", { method: "GET" });
    renderHistory(Array.isArray(data.history) ? data.history : []);
  } catch {
    // O historico e secundario; falha silenciosa evita ruido excessivo.
  }
}

async function handleClearHistory() {
  if (!clearHistoryBtn || clearHistoryBtn.disabled) {
    return;
  }

  const confirmed = window.confirm(
    "Limpar todo o historico de downloads? Os arquivos baixados nao serao apagados.",
  );
  if (!confirmed) {
    return;
  }

  clearHistoryBtn.disabled = true;
  clearHistoryBtn.dataset.originalText = clearHistoryBtn.textContent;
  clearHistoryBtn.textContent = "Limpando...";

  try {
    const data = await fetchJson("/api/history", { method: "DELETE" });
    renderHistory(Array.isArray(data.history) ? data.history : []);
    showToast("Historico limpo. Os arquivos baixados foram mantidos.");
  } catch (error) {
    showToast(error.message);
    await refreshHistory();
  } finally {
    clearHistoryBtn.textContent =
      clearHistoryBtn.dataset.originalText || "Limpar historico";
  }
}

async function refreshJobs() {
  try {
    const data = await fetchJson("/api/jobs", { method: "GET" });
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];

    let shouldRefreshHistory = false;
    jobs.forEach((job) => {
      const previousStatus = state.jobStatuses.get(job.id);
      if (
        previousStatus &&
        previousStatus !== job.status &&
        TERMINAL_STATUSES.has(job.status)
      ) {
        shouldRefreshHistory = true;
        if (job.status === "completed") {
          if (isHostedMode && job.download_url) {
            showToast("Download concluido. Toque em Baixar arquivo.");
          } else {
            showToast(`Download concluido. Abrindo pasta: ${job.title}`);
          }
        } else if (job.status === "failed" && job.error) {
          showToast(`Falha no download: ${job.error}`);
        }
      }
      state.jobStatuses.set(job.id, job.status);
    });

    renderJobs(jobs);

    if (shouldRefreshHistory) {
      refreshHistory();
    }
  } catch {
    // Se o backend estiver reiniciando, o proximo polling recupera.
  }
}

async function handleDownloadSubmit(event) {
  event.preventDefault();
  const payload = currentPayload();

  if (!isValidUrl(payload.video_url)) {
    showToast("Cole um link valido com http:// ou https://.");
    if (videoUrlInput) {
      videoUrlInput.focus();
    }
    return;
  }

  if (videoUrlInput) {
    videoUrlInput.value = payload.video_url;
  }

  const modeMessage = getModeValidationMessage(payload);
  if (modeMessage) {
    renderPreviewError(modeMessage);
    renderModeAlert(modeMessage);
    showToast(modeMessage);
    return;
  }

  savePreferences();
  const preview =
    state.previewKey === getPreviewKey(payload) && state.preview
      ? state.preview
      : await requestPreview({ force: true, silent: false });

  if (!preview) {
    return;
  }

  if (submitButton) {
    submitButton.disabled = true;
    submitButton.dataset.originalText = submitButton.textContent;
    submitButton.textContent = "Adicionando...";
  }

  try {
    const data = await fetchJson("/api/downloads", {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        preview,
      }),
    });
    ensureJobSupportsRequestedOptions(payload, data.job || {});

    showToast("Download adicionado a fila.");
    await refreshJobs();
  } catch (error) {
    showToast(error.message);
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent =
        submitButton.dataset.originalText || "Iniciar download";
    }
  }
}

modeTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    syncDownloadModeState(tab.dataset.downloadMode || "online");
    savePreferences();
    schedulePreview(180);
  });
});

formatTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    syncFormatState(tab.dataset.format || "mp4");
    savePreferences();
    schedulePreview(180);
  });
});

if (qualitySelect) {
  qualitySelect.addEventListener("change", () => {
    const activeFormat = formatChoiceInput ? formatChoiceInput.value : "mp4";
    state.qualityChoices[activeFormat] = qualitySelect.value;
    updateQualityHelp();
    savePreferences();
    schedulePreview(180);
  });
}

if (outputDirInput) {
  outputDirInput.addEventListener("change", savePreferences);
}

if (bpmIntroCheckbox) {
  bpmIntroCheckbox.addEventListener("change", () => {
    state.addBpmIntro = bpmIntroCheckbox.checked;
    savePreferences();
    schedulePreview(180);
  });
}

if (mirrorVideoCheckbox) {
  mirrorVideoCheckbox.addEventListener("change", () => {
    state.mirrorVideo = mirrorVideoCheckbox.checked;
    savePreferences();
    schedulePreview(180);
  });
}

if (videoUrlInput) {
  videoUrlInput.addEventListener("input", () => {
    schedulePreview();
  });
  videoUrlInput.addEventListener("blur", () => {
    requestPreview({ silent: true });
  });
}

if (downloadForm) {
  downloadForm.addEventListener("submit", handleDownloadSubmit);
}

if (pasteBtn) {
  pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (videoUrlInput) {
        videoUrlInput.value = text;
      }
      showToast("Link colado com sucesso.");
      schedulePreview(120);
    } catch {
      if (videoUrlInput) {
        videoUrlInput.focus();
      }
      showToast("Nao foi possivel acessar a area de transferencia.");
    }
  });
}

if (clearHistoryBtn) {
  clearHistoryBtn.addEventListener("click", handleClearHistory);
}

loadPreferences();
refreshJobs();
refreshHistory();
window.setInterval(refreshJobs, 1500);
window.setInterval(refreshHistory, 12000);

if (videoUrlInput && isValidUrl(videoUrlInput.value.trim())) {
  schedulePreview(150);
}
