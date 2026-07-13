const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
    ? 'http://127.0.0.1:8000/api'
    : '/api';

// Elements
const dropZoneExcel = document.getElementById('dropZoneExcel');
const excelFileInput = document.getElementById('excelFile');
const excelFileName = document.getElementById('excelFileName');
const uploadForm = document.getElementById('uploadForm');

const step1 = document.getElementById('step-1');
const step2 = document.getElementById('step-2');
const btnBack = document.getElementById('btnBack');
const btnProcess = document.getElementById('btnProcess');
const formatsTableBody = document.getElementById('formatsTableBody');

const loadingOverlay = document.getElementById('loadingOverlay');
const loadingText = document.getElementById('loadingText');

let currentFormats = [];
let selectedExcelFile = null;

// Handle Drag and Drop for Excel
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZoneExcel.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZoneExcel.addEventListener(eventName, () => {
        dropZoneExcel.classList.add('dragover');
    }, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZoneExcel.addEventListener(eventName, () => {
        dropZoneExcel.classList.remove('dragover');
    }, false);
});

dropZoneExcel.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
        excelFileInput.files = files;
        updateFileName(excelFileInput, excelFileName);
    }
});

dropZoneExcel.addEventListener('click', () => {
    excelFileInput.click();
});

excelFileInput.addEventListener('change', () => {
    updateFileName(excelFileInput, excelFileName);
});

function updateFileName(input, displayElement) {
    if (input.files.length > 0) {
        displayElement.textContent = input.files[0].name;
        displayElement.style.color = 'var(--primary)';
        displayElement.style.fontWeight = '600';
    } else {
        displayElement.textContent = 'Nenhum arquivo selecionado';
        displayElement.style.color = 'var(--text-secondary)';
        displayElement.style.fontWeight = 'normal';
    }
}

function showLoading(text) {
    loadingText.textContent = text;
    loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    loadingOverlay.style.display = 'none';
}

function showError(msg) {
    document.getElementById('errorMsg').textContent = msg;
    const toast = document.getElementById('errorToast');
    toast.style.display = 'flex';
    setTimeout(() => {
        toast.style.display = 'none';
    }, 8000);
}

function closeToast(id) {
    document.getElementById(id).style.display = 'none';
}

// Memory: Load mappings from LocalStorage
function getSavedMapping(formatName) {
    const saved = localStorage.getItem('autoexcel_mappings');
    if (saved) {
        const mappings = JSON.parse(saved);
        return mappings[formatName] || null;
    }
    return null;
}

// Memory: Save all mappings to LocalStorage
function saveMappingsToStorage(mappingsObj) {
    const saved = localStorage.getItem('autoexcel_mappings');
    let allMappings = saved ? JSON.parse(saved) : {};
    
    // Merge new mappings
    allMappings = { ...allMappings, ...mappingsObj };
    localStorage.setItem('autoexcel_mappings', JSON.stringify(allMappings));
}

// Step 1: Extract Formats
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    if (!excelFileInput.files || excelFileInput.files.length === 0) {
        showError("Por favor, selecione uma planilha Excel.");
        return;
    }
    
    selectedExcelFile = excelFileInput.files[0];
    const formData = new FormData();
    formData.append('excel', selectedExcelFile);
    
    showLoading("Lendo planilha e buscando formatos...");
    
    try {
        const response = await fetch(`${API_BASE}/extract-formats`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!response.ok || data.error) {
            throw new Error(data.error || "Erro ao ler a planilha.");
        }
        
        currentFormats = data.formats;
        renderFormatsTable();
        
        step1.style.display = 'none';
        step2.style.display = 'block';
        
    } catch (err) {
        showError(err.message);
    } finally {
        hideLoading();
    }
});

// Go back to step 1
btnBack.addEventListener('click', () => {
    step2.style.display = 'none';
    step1.style.display = 'block';
});

// Render dynamic inputs
function renderFormatsTable() {
    formatsTableBody.innerHTML = '';
    
    if (currentFormats.length === 0) {
        formatsTableBody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-secondary);">Nenhum formato encontrado na planilha.</td></tr>';
        return;
    }
    
    currentFormats.forEach((format, index) => {
        const saved = getSavedMapping(format);
        const defaultPrice = saved ? saved.price : '';
        const defaultExtra = saved ? saved.extra : '';
        
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="font-weight: 600;">${format}</td>
            <td>
                <div class="input-group">
                    <span class="input-prefix">R$</span>
                    <input type="number" step="0.01" min="0" class="price-input" data-format="${format}" data-type="price" value="${defaultPrice}" placeholder="Ex: 12,70" required>
                </div>
            </td>
            <td>
                <div class="input-group">
                    <span class="input-prefix">+ R$</span>
                    <input type="number" step="0.01" min="0" class="extra-input" data-format="${format}" data-type="extra" value="${defaultExtra}" placeholder="Ex: 3,00" required>
                </div>
            </td>
        `;
        formatsTableBody.appendChild(tr);
    });
}

// Step 2: Generate Final Excel
btnProcess.addEventListener('click', async () => {
    // Collect data
    const mappings = {};
    let hasError = false;
    
    const priceInputs = document.querySelectorAll('.price-input');
    const extraInputs = document.querySelectorAll('.extra-input');
    
    priceInputs.forEach((input, i) => {
        const format = input.getAttribute('data-format');
        const priceVal = parseFloat(input.value);
        const extraVal = parseFloat(extraInputs[i].value);
        
        if (isNaN(priceVal) || isNaN(extraVal)) {
            hasError = true;
            input.style.borderColor = 'red';
        } else {
            input.style.borderColor = '';
            mappings[format] = {
                price: priceVal,
                extra: extraVal
            };
        }
    });
    
    if (hasError) {
        showError("Por favor, preencha todos os preços base e acréscimos com números válidos.");
        return;
    }
    
    // Save to LocalStorage memory
    saveMappingsToStorage(mappings);
    
    const formData = new FormData();
    formData.append('excel', selectedExcelFile);
    formData.append('mapping_json', JSON.stringify(mappings));
    
    showLoading("Preenchendo milhares de células magicamente...");
    
    try {
        const response = await fetch(`${API_BASE}/process-manual`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!response.ok || data.error) {
            throw new Error(data.error || "Erro ao processar planilha.");
        }
        
        // Download result
        const bytes = atob(data.excel_base64);
        const array = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) {
            array[i] = bytes.charCodeAt(i);
        }
        
        const blob = new Blob([array], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "Planilha_AutoExcel_Preenchida.xlsx";
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
        
        alert(`Sucesso! ${data.success_count} produtos precificados.\nTotal de produtos detectados: ${data.total_codes}`);
        
    } catch (err) {
        showError(err.message);
    } finally {
        hideLoading();
    }
});
