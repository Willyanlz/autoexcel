const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000/api' : '/api';

// --- Elements ---
const dropZoneExcel = document.getElementById('dropZoneExcel');
const dropZoneImages = document.getElementById('dropZoneImages');
const excelFileInput = document.getElementById('excelFile');
const imageFilesInput = document.getElementById('imageFiles');
const excelFileName = document.getElementById('excelFileName');
const imageFileNames = document.getElementById('imageFileNames');
const uploadForm = document.getElementById('uploadForm');
const ocrModeSection = document.getElementById('ocrModeSection');
const aiSettings = document.getElementById('aiSettings');
const apiKeyInput = document.getElementById('apiKeyInput');
const modelInput = document.getElementById('modelInput');
const btnModeOcr = document.getElementById('btnModeOcr');
const btnModeAi = document.getElementById('btnModeAi');

const step1 = document.getElementById('step-1');
const step2 = document.getElementById('step-2');
const btnBack = document.getElementById('btnBack');
const btnProcess = document.getElementById('btnProcess');
const btnAddFormat = document.getElementById('btnAddFormat');
const formatsContainer = document.getElementById('formatsContainer');

const loadingOverlay = document.getElementById('loadingOverlay');
const loadingText = document.getElementById('loadingText');
const loadingSubtext = document.getElementById('loadingSubtext');

let selectedExcelFile = null;
let analysisData = null;
let currentMode = 'ocr';
let formatCounter = 0;

// --- Init: load saved settings ---
(function init() {
    const savedKey = localStorage.getItem('autoexcel_api_key');
    const savedModel = localStorage.getItem('autoexcel_model');
    const savedMode = localStorage.getItem('autoexcel_mode');
    if (savedKey) apiKeyInput.value = savedKey;
    if (savedModel) modelInput.value = savedModel;
    if (savedMode) {
        currentMode = savedMode;
        updateModeUI();
    }
})();

// --- Drop Zone setup ---
function setupDropZone(zone, input, cb) {
    ['dragenter','dragover','dragleave','drop'].forEach(e =>
        zone.addEventListener(e, ev => { ev.preventDefault(); ev.stopPropagation(); }, false));
    ['dragenter','dragover'].forEach(e =>
        zone.addEventListener(e, () => zone.classList.add('dragover'), false));
    ['dragleave','drop'].forEach(e =>
        zone.addEventListener(e, () => zone.classList.remove('dragover'), false));
    zone.addEventListener('drop', e => { input.files = e.dataTransfer.files; cb(); });
    zone.addEventListener('click', () => input.click());
    input.addEventListener('change', cb);
}

setupDropZone(dropZoneExcel, excelFileInput, () => {
    if (excelFileInput.files.length) {
        excelFileName.textContent = excelFileInput.files[0].name;
        excelFileName.style.color = 'var(--primary)';
        excelFileName.style.fontWeight = '600';
    }
});

setupDropZone(dropZoneImages, imageFilesInput, () => {
    const c = imageFilesInput.files.length;
    if (c) {
        imageFileNames.textContent = `${c} imagem(ns) selecionada(s)`;
        imageFileNames.style.color = 'var(--success)';
        imageFileNames.style.fontWeight = '600';
        ocrModeSection.style.display = 'block';
    } else {
        imageFileNames.textContent = 'Nenhuma imagem';
        imageFileNames.style.color = 'var(--text-secondary)';
        ocrModeSection.style.display = 'none';
    }
});

// --- Mode toggle ---
btnModeOcr.addEventListener('click', () => { currentMode = 'ocr'; updateModeUI(); });
btnModeAi.addEventListener('click', () => { currentMode = 'ai'; updateModeUI(); });

function updateModeUI() {
    btnModeOcr.classList.toggle('active', currentMode === 'ocr');
    btnModeAi.classList.toggle('active', currentMode === 'ai');
    aiSettings.style.display = currentMode === 'ai' ? 'block' : 'none';
    localStorage.setItem('autoexcel_mode', currentMode);
}

// --- Helpers ---
function showLoading(t, s) { loadingText.textContent = t; loadingSubtext.textContent = s || ''; loadingOverlay.style.display = 'flex'; }
function hideLoading() { loadingOverlay.style.display = 'none'; }
function showToast(type, msg) {
    const id = type === 'error' ? 'errorToast' : 'successToast';
    document.getElementById(type === 'error' ? 'errorMsg' : 'successMsg').textContent = msg;
    const t = document.getElementById(id); t.style.display = 'flex';
    setTimeout(() => t.style.display = 'none', 8000);
}
function closeToast(id) { document.getElementById(id).style.display = 'none'; }

function getSavedMapping(h) {
    const s = localStorage.getItem('autoexcel_mappings_v3');
    return s ? (JSON.parse(s)[h] || null) : null;
}
function saveAllMappings(m) {
    const s = localStorage.getItem('autoexcel_mappings_v3');
    let a = s ? JSON.parse(s) : {};
    localStorage.setItem('autoexcel_mappings_v3', JSON.stringify({ ...a, ...m }));
}

// ===================== STEP 1: Analyze =====================
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!excelFileInput.files || !excelFileInput.files.length) {
        showToast('error', 'Selecione uma planilha Excel.'); return;
    }
    selectedExcelFile = excelFileInput.files[0];
    const fd = new FormData();
    fd.append('excel', selectedExcelFile);

    const hasImages = imageFilesInput.files && imageFilesInput.files.length > 0;
    if (hasImages) {
        for (let i = 0; i < imageFilesInput.files.length; i++) fd.append('images', imageFilesInput.files[i]);
        fd.append('mode', currentMode);
        if (currentMode === 'ai') {
            const key = apiKeyInput.value.trim();
            const model = modelInput.value.trim();
            if (key) { fd.append('api_key', key); localStorage.setItem('autoexcel_api_key', key); }
            if (model) { fd.append('llm_model', model); localStorage.setItem('autoexcel_model', model); }
        }
    }

    showLoading(
        hasImages ? (currentMode === 'ai' ? 'IA lendo imagens...' : 'OCR lendo imagens...') : 'Analisando planilha...',
        hasImages ? 'Pode levar alguns segundos por imagem.' : 'Rápido!'
    );

    try {
        const res = await fetch(`${API_BASE}/analyze`, { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Erro');
        analysisData = data;
        renderStep2();
        step1.style.display = 'none'; step2.style.display = 'block';
        if (data.ocr_count > 0) showToast('success', `Detectados ${data.ocr_count} códigos nas imagens!`);
        if (data.ocr_errors?.length) showToast('error', data.ocr_errors[0]);
    } catch (err) { showToast('error', err.message); } finally { hideLoading(); }
});

btnBack.addEventListener('click', () => { step2.style.display = 'none'; step1.style.display = 'block'; });

// ===================== STEP 2: Render =====================
function renderStep2() {
    formatsContainer.innerHTML = '';
    formatCounter = 0;
    if (!analysisData?.formats?.length) {
        formatsContainer.innerHTML = '<p style="color:var(--text-secondary);text-align:center;">Nenhum formato encontrado. Adicione manualmente abaixo.</p>';
        return;
    }
    analysisData.formats.forEach(fmt => addFormatCard(fmt.header, fmt.codes));
}

function addFormatCard(header, codes) {
    const idx = formatCounter++;
    const saved = getSavedMapping(header);
    const dPrice = saved?.price ?? '';
    const dExtra = saved?.extra ?? '';

    const card = document.createElement('div');
    card.className = 'format-card';
    card.dataset.idx = idx;

    card.innerHTML = `
        <div class="format-card-header" onclick="toggleCard(this)">
            <div class="format-title">
                <i class="fas fa-cube"></i>
                <input type="text" class="header-edit-input" value="${header}" onclick="event.stopPropagation()" placeholder="Ex: FORMATO 58X58">
                <span class="badge">${codes?.length || 0} cód.</span>
            </div>
            <div class="format-actions">
                <button type="button" class="btn-icon btn-delete-format" onclick="event.stopPropagation(); removeFormat(this)" title="Remover Formato">
                    <i class="fas fa-trash"></i>
                </button>
                <i class="fas fa-chevron-down toggle-icon"></i>
            </div>
        </div>
        <div class="format-card-body">
            <div class="price-row">
                <div class="price-field">
                    <label>Preço Base</label>
                    <div class="input-group"><span class="input-prefix">R$</span>
                    <input type="number" step="0.01" min="0" class="price-input" value="${dPrice}" placeholder="Opcional"></div>
                </div>
                <div class="price-field">
                    <label>Acréscimo Fracionado</label>
                    <div class="input-group"><span class="input-prefix">+ R$</span>
                    <input type="number" step="0.01" min="0" class="extra-input" value="${dExtra}" placeholder="Opcional"></div>
                </div>
            </div>
            <div class="codes-section">
                <label class="field-label"><i class="fas fa-barcode"></i> Códigos de Produto</label>
                <div class="codes-list" id="codes-${idx}">
                    ${(codes || []).map(c => `
                        <div class="code-item">
                            <input type="text" class="code-input" value="${c}" placeholder="Código...">
                            <button type="button" class="btn-icon btn-remove" onclick="removeCode(this)" title="Remover"><i class="fas fa-trash-alt"></i></button>
                        </div>
                    `).join('')}
                </div>
                <button type="button" class="btn-add-code" onclick="addCode(${idx})">
                    <i class="fas fa-plus"></i> Adicionar Código
                </button>
            </div>
        </div>
    `;
    formatsContainer.appendChild(card);
}

function toggleCard(el) { el.closest('.format-card').classList.toggle('collapsed'); }

function addCode(idx) {
    const list = document.getElementById(`codes-${idx}`);
    const item = document.createElement('div');
    item.className = 'code-item';
    item.innerHTML = `<input type="text" class="code-input" value="" placeholder="Código...">
        <button type="button" class="btn-icon btn-remove" onclick="removeCode(this)" title="Remover"><i class="fas fa-trash-alt"></i></button>`;
    list.appendChild(item);
    item.querySelector('input').focus();
}

function removeCode(btn) { btn.closest('.code-item').remove(); }

function removeFormat(btn) {
    if (confirm('Remover este formato?')) btn.closest('.format-card').remove();
}

// Add new format manually
btnAddFormat.addEventListener('click', () => {
    addFormatCard('NOVO FORMATO', []);
    // Scroll to bottom
    formatsContainer.lastElementChild.scrollIntoView({ behavior: 'smooth' });
    // Focus on the header input
    const input = formatsContainer.lastElementChild.querySelector('.header-edit-input');
    input.select();
    input.focus();
});

// ===================== STEP 2: Process =====================
btnProcess.addEventListener('click', async () => {
    const mapping = {};
    const cards = document.querySelectorAll('.format-card');
    cards.forEach(card => {
        const idx = card.dataset.idx;
        const header = card.querySelector('.header-edit-input').value.trim().toUpperCase();
        if (!header) return;

        const priceVal = card.querySelector('.price-input').value.trim();
        const extraVal = card.querySelector('.extra-input').value.trim();
        const codeInputs = card.querySelectorAll(`#codes-${idx} .code-input`);
        const codes = [];
        codeInputs.forEach(inp => { const v = inp.value.trim(); if (v) codes.push(v); });

        mapping[header] = {
            price: priceVal !== '' ? parseFloat(priceVal) : null,
            extra: extraVal !== '' ? parseFloat(extraVal) : null,
            codes
        };
    });

    saveAllMappings(mapping);

    const fd = new FormData();
    fd.append('excel', selectedExcelFile);
    fd.append('mapping_json', JSON.stringify(mapping));

    showLoading('Gerando planilha final...', 'Preenchendo células magicamente...');

    try {
        const res = await fetch(`${API_BASE}/process`, { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || 'Erro');

        const bytes = atob(data.excel_base64);
        const arr = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const blob = new Blob([arr], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'Planilha_AutoExcel.xlsx';
        document.body.appendChild(a); a.click(); window.URL.revokeObjectURL(url); a.remove();

        showToast('success', `${data.success_count} de ${data.total_codes} produtos precificados!`);
    } catch (err) { showToast('error', err.message); } finally { hideLoading(); }
});
