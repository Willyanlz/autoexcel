document.addEventListener('DOMContentLoaded', () => {
    const pdfZone = document.getElementById('pdfZone');
    const pdfInput = document.getElementById('pdfInput');
    const pdfName = document.getElementById('pdfName');

    const imgZone = document.getElementById('imgZone');
    const imgInput = document.getElementById('imgInput');
    const imgName = document.getElementById('imgName');

    const excelZone = document.getElementById('excelZone');
    const excelInput = document.getElementById('excelInput');
    const excelName = document.getElementById('excelName');

    const submitBtn = document.getElementById('submitBtn');
    const form = document.getElementById('uploadForm');
    const errorMsg = document.getElementById('errorMsg');

    const mainContainer = document.getElementById('mainContainer');
    const resolveContainer = document.getElementById('resolveContainer');
    const resolveTableBody = document.querySelector('#resolveTable tbody');
    const resolveStats = document.getElementById('resolveStats');
    const resolveBtn = document.getElementById('resolveBtn');

    // Settings elements
    const settingsBtn = document.getElementById('settingsBtn');
    const settingsModal = document.getElementById('settingsModal');
    const closeSettings = document.getElementById('closeSettings');
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    const apiKeyInput = document.getElementById('apiKey');
    const llmModelInput = document.getElementById('llmModel');

    let currentExcelBase64 = null;
    let currentAmbiguities = [];

    // Load settings on init
    apiKeyInput.value = localStorage.getItem('autoexcel_api_key') || '';
    if (localStorage.getItem('autoexcel_model')) {
        llmModelInput.value = localStorage.getItem('autoexcel_model');
    }

    settingsBtn.addEventListener('click', () => {
        settingsModal.style.display = 'flex';
    });

    closeSettings.addEventListener('click', () => {
        settingsModal.style.display = 'none';
    });

    saveSettingsBtn.addEventListener('click', () => {
        localStorage.setItem('autoexcel_api_key', apiKeyInput.value.trim());
        localStorage.setItem('autoexcel_model', llmModelInput.value.trim());
        settingsModal.style.display = 'none';
        alert('Configurações salvas no navegador!');
    });

    function setupDropZone(zone, input, nameElement) {
        zone.addEventListener('click', () => input.click());

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('dragover');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            
            if (e.dataTransfer.files.length > 0) {
                input.files = e.dataTransfer.files;
                updateFileName(input, nameElement);
                checkFormValidity();
            }
        });

        input.addEventListener('change', () => {
            updateFileName(input, nameElement);
            checkFormValidity();
        });
    }

    function updateFileName(input, nameElement) {
        if (input.files.length > 1) {
            nameElement.textContent = `${input.files.length} arquivos selecionados`;
        } else if (input.files.length === 1) {
            nameElement.textContent = input.files[0].name;
        } else {
            nameElement.textContent = 'Nenhum arquivo';
        }
    }

    async function resizeImage(file, maxWidth = 1200, maxHeight = 1200) {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = function (e) {
                const img = new Image();
                img.onload = function () {
                    const canvas = document.createElement('canvas');
                    let width = img.width;
                    let height = img.height;

                    if (width > height) {
                        if (width > maxWidth) {
                            height = Math.round((height * maxWidth) / width);
                            width = maxWidth;
                        }
                    } else {
                        if (height > maxHeight) {
                            width = Math.round((width * maxHeight) / height);
                            height = maxHeight;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob((blob) => {
                        resolve(new File([blob], file.name, {
                            type: 'image/jpeg',
                            lastModified: Date.now()
                        }));
                    }, 'image/jpeg', 0.85);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }

    function checkFormValidity() {
        if (pdfInput.files.length > 0 && excelInput.files.length > 0 && imgInput.files.length > 0) {
            submitBtn.disabled = false;
        } else {
            submitBtn.disabled = true;
        }
    }

    setupDropZone(pdfZone, pdfInput, pdfName);
    setupDropZone(imgZone, imgInput, imgName);
    setupDropZone(excelZone, excelInput, excelName);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (!pdfInput.files.length || !excelInput.files.length || !imgInput.files.length) return;

        submitBtn.classList.add('loading');
        submitBtn.disabled = true;
        errorMsg.textContent = '';
        errorMsg.style.color = '#ef4444';

        // Update button text
        const setStatus = (txt) => {
            submitBtn.querySelector('span').textContent = txt;
        };

        setStatus('Carregando imagens e cache...');

        const cachedProducts = [];
        const uncachedImages = [];
        const imageMetadata = {}; // map filename to its cache key

        // 1. Process files, check client-side cache and resize if uncached
        for (let i = 0; i < imgInput.files.length; i++) {
            const file = imgInput.files[i];
            const cacheKey = `autoexcel_img_${file.name}_${file.size}_${file.lastModified}`;
            imageMetadata[file.name] = cacheKey;

            const cachedData = localStorage.getItem(cacheKey);
            if (cachedData) {
                try {
                    const parsed = JSON.parse(cachedData);
                    cachedProducts.push(...parsed);
                } catch {
                    localStorage.removeItem(cacheKey);
                    uncachedImages.push(file);
                }
            } else {
                uncachedImages.push(file);
            }
        }

        // 2. Resize uncached images on the fly
        const resizedImages = [];
        if (uncachedImages.length > 0) {
            setStatus(`Otimizando ${uncachedImages.length} imagem(ns)...`);
            for (const imgFile of uncachedImages) {
                const resized = await resizeImage(imgFile);
                resizedImages.push(resized);
            }
        }

        setStatus('Processando planilha e IA...');

        const formData = new FormData();
        formData.append('pdf', pdfInput.files[0]);
        formData.append('excel', excelInput.files[0]);
        formData.append('cached_products_json', JSON.stringify(cachedProducts));

        for (const img of resizedImages) {
            formData.append('images', img);
        }
        
        // Append API settings
        const apiKey = localStorage.getItem('autoexcel_api_key') || '';
        const model = localStorage.getItem('autoexcel_model') || 'google/gemini-2.5-flash';
        formData.append('api_key', apiKey);
        formData.append('llm_model', model);

        try {
            const response = await fetch('/api/process', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                let errDetail = '';
                try {
                    const errJson = await response.json();
                    errDetail = errJson.error || errJson.detail || JSON.stringify(errJson);
                } catch {
                    errDetail = await response.text();
                    // Strip HTML if Vercel returned a generic error page
                    if (errDetail.includes('<html') || errDetail.includes('<!DOCTYPE')) {
                        errDetail = `Erro do servidor (${response.status}). Possível timeout ou falha na API da IA.`;
                    }
                }
                throw new Error(errDetail);
            }

            const data = await response.json();

            // Store new extractions in local storage cache
            if (data.new_extracted_products && data.new_extracted_products.length > 0) {
                data.new_extracted_products.forEach(item => {
                    const cacheKey = imageMetadata[item.filename];
                    if (cacheKey && item.products) {
                        localStorage.setItem(cacheKey, JSON.stringify(item.products));
                    }
                });
            }
            
            if (data.pending_count > 0) {
                // Show resolution UI
                currentExcelBase64 = data.excel_base64;
                currentAmbiguities = data.ambiguous;
                
                mainContainer.style.display = 'none';
                resolveContainer.style.display = 'block';
                resolveStats.textContent = `Preenchidos automaticamente: ${data.success_count} | Pendências para revisar: ${data.pending_count}`;
                
                // Show warnings if any
                if (data.warnings && data.warnings.length > 0) {
                    resolveStats.textContent += '\n⚠️ ' + data.warnings.join('\n⚠️ ');
                }
                
                resolveTableBody.innerHTML = '';
                currentAmbiguities.forEach((amb) => {
                    const tr = document.createElement('tr');
                    
                    const tdCode = document.createElement('td');
                    tdCode.textContent = amb.codigo;
                    tr.appendChild(tdCode);
                    
                    const tdName = document.createElement('td');
                    tdName.textContent = amb.nome;
                    tr.appendChild(tdName);
                    
                    const tdSelect = document.createElement('td');
                    const select = document.createElement('select');
                    select.dataset.row = amb.row;
                    select.dataset.codigo = amb.codigo;
                    
                    // Default option
                    const optDefault = document.createElement('option');
                    optDefault.value = "";
                    optDefault.textContent = "-- Selecione a Variante --";
                    select.appendChild(optDefault);
                    
                    amb.opcoes.forEach(op => {
                        const option = document.createElement('option');
                        option.value = JSON.stringify({price: op.price, m2: op.m2});
                        option.textContent = `${op.desc} - R$ ${op.price}`;
                        select.appendChild(option);
                    });
                    
                    tdSelect.appendChild(select);
                    tr.appendChild(tdSelect);
                    
                    resolveTableBody.appendChild(tr);
                });

            } else {
                // No pending, download the excel directly from base64
                downloadExcel(data.excel_base64, 'Tabela_Final.xlsx');
                let msg = `✅ Sucesso! ${data.success_count} preenchidos. Nenhuma pendência.`;
                if (data.warnings && data.warnings.length > 0) {
                    msg += '\n⚠️ ' + data.warnings.join('\n⚠️ ');
                }
                errorMsg.textContent = msg;
                errorMsg.style.color = '#10b981';
            }

        } catch (error) {
            errorMsg.textContent = 'Erro na API: ' + error.message;
        } finally {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
            setStatus('Processar e Cruzar Dados');
        }
    });

    resolveBtn.addEventListener('click', async () => {
        const selects = document.querySelectorAll('#resolveTable select');
        const resolutions = [];
        
        selects.forEach(sel => {
            if (sel.value) {
                const val = JSON.parse(sel.value);
                resolutions.push({
                    codigo: sel.dataset.codigo,
                    row: parseInt(sel.dataset.row),
                    price: val.price,
                    m2: val.m2
                });
            }
        });

        if (resolutions.length === 0) {
            alert('Por favor, resolva pelo menos uma ambiguidade.');
            return;
        }

        resolveBtn.textContent = 'Gerando...';
        resolveBtn.disabled = true;

        try {
            const response = await fetch('/api/resolve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    resolutions: resolutions,
                    excel_base64: currentExcelBase64
                })
            });

            if (!response.ok) throw new Error('Erro ao salvar resoluções.');

            const blob = await response.blob();
            downloadBlob(blob, 'Tabela_Final.xlsx');
            
            // Reset state
            resolveContainer.style.display = 'none';
            mainContainer.style.display = 'block';

        } catch(e) {
            alert(e.message);
        } finally {
            resolveBtn.textContent = 'Confirmar e Baixar Excel';
            resolveBtn.disabled = false;
        }
    });

    function downloadExcel(base64Data, filename) {
        const binaryString = window.atob(base64Data);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        downloadBlob(blob, filename);
    }
    
    function downloadBlob(blob, filename) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    }
});
