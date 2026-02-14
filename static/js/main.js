let canvas, renderer;
let scenes = [];
const observerOptions = {
    root: null,
    rootMargin: '50px',  // Only trigger when 50px of the element is visible
    threshold: 0.1
};

init();

function init() {
    canvas = document.getElementById('c');
    const searchInput = document.getElementById('search-input');
    const uploadButton = document.getElementById('upload-button');
    const fileInput = document.getElementById('file-input');

    // Search only on Enter key
    searchInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            performSearch(searchInput.value);
        }
    });

    // Upload button click
    uploadButton.addEventListener('click', (e) => {
        e.preventDefault();
        fileInput.click();
    });

    fileInput.addEventListener('change', (event) => {
        const files = event.target.files;
        if (files.length > 0) {
            uploadFiles(files);
        }
    });

    // Upload modal close button
    const uploadModalClose = document.getElementById('upload-modal-close');
    uploadModalClose.addEventListener('click', () => {
        hideUploadModal();
    });

    // Close modal when clicking outside
    const uploadModal = document.getElementById('upload-modal');
    uploadModal.addEventListener('click', (e) => {
        if (e.target === uploadModal) {
            hideUploadModal();
        }
    });
    const urlParams = new URLSearchParams(window.location.search);
    if (searchInput && urlParams.has('filter')) {
        searchInput.value = urlParams.get('filter') || '';
    }

    // Initialize sort/filter dropdowns
    if (typeof initSortFilterDropdowns !== 'undefined') {
        initSortFilterDropdowns();
    }
}

let uploadStartTime = null;
let uploadTimerInterval = null;
const supportedUploadExtensions = ['.zip', '.stl', '.3mf', '.gcode'];

function showUploadModal() {
    const modal = document.getElementById('upload-modal');
    const progressFill = document.getElementById('upload-progress-fill');
    const progressText = document.getElementById('upload-progress-text');
    const status = document.getElementById('upload-status');
    const statusLog = document.getElementById('upload-status-log');
    const timer = document.getElementById('upload-timer');

    modal.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Preparing upload...';
    status.textContent = 'Ready to upload';
    status.className = 'upload-status info';
    statusLog.innerHTML = '';
    timer.textContent = '00:00';

    uploadStartTime = null;
    if (uploadTimerInterval) {
        clearInterval(uploadTimerInterval);
        uploadTimerInterval = null;
    }
}

function hideUploadModal() {
    const modal = document.getElementById('upload-modal');
    modal.style.display = 'none';

    if (uploadTimerInterval) {
        clearInterval(uploadTimerInterval);
        uploadTimerInterval = null;
    }
}

function startUploadTimer() {
    uploadStartTime = Date.now();
    const timer = document.getElementById('upload-timer');

    uploadTimerInterval = setInterval(() => {
        const elapsed = Date.now() - uploadStartTime;
        const seconds = Math.floor(elapsed / 1000);
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;

        timer.textContent = `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }, 1000);
}

function stopUploadTimer() {
    if (uploadTimerInterval) {
        clearInterval(uploadTimerInterval);
        uploadTimerInterval = null;
    }
}

function updateUploadProgress(percent, text) {
    const progressFill = document.getElementById('upload-progress-fill');
    const progressText = document.getElementById('upload-progress-text');

    progressFill.style.width = percent + '%';
    progressText.textContent = text;
}

function setUploadSummary(statusType, summaryText) {
    const status = document.getElementById('upload-status');
    status.textContent = summaryText;
    status.className = `upload-status ${statusType}`;
}

function appendUploadLog(message, level = 'info') {
    const statusLog = document.getElementById('upload-status-log');
    const entry = document.createElement('div');
    entry.className = `upload-log-entry ${level}`;
    entry.textContent = message;
    statusLog.appendChild(entry);
    statusLog.scrollTop = statusLog.scrollHeight;
}

function getUploadExtension(filename) {
    const dotIndex = filename.lastIndexOf('.');
    return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : '';
}

function isSupportedUploadFile(filename) {
    return supportedUploadExtensions.includes(getUploadExtension(filename));
}

function formatBatchSummary(totalFiles, successCount, skippedCount, errorCount) {
    return `Batch finished: ${successCount} uploaded, ${skippedCount} skipped, ${errorCount} failed (total ${totalFiles}).`;
}

async function uploadSingleFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('conflict_action', 'skip');
    formData.append('refresh_index', 'false');

    let response;
    try {
        response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
    } catch (error) {
        return {
            status: 'error',
            filename: file.name,
            error: `Network error: ${error.message || 'upload request failed'}`
        };
    }

    let data = {};
    try {
        data = await response.json();
    } catch (error) {
        return {
            status: 'error',
            filename: file.name,
            error: 'Server returned an invalid response'
        };
    }

    if (!response.ok || !data.success) {
        return {
            status: 'error',
            filename: file.name,
            error: data.error || `Upload failed with status ${response.status}`
        };
    }

    const result = Array.isArray(data.results) ? data.results[0] : null;
    if (!result) {
        return {
            status: 'error',
            filename: file.name,
            error: 'Upload completed but returned no result entry'
        };
    }
    return result;
}

async function refreshIndexAfterBatchUpload() {
    const response = await fetch('/reload_index?mode=files', { method: 'POST' });
    let data = {};
    try {
        data = await response.json();
    } catch (error) {
        return { ok: false, error: 'Invalid reload response' };
    }
    return {
        ok: response.ok && data.success === true,
        error: data.error || null,
    };
}

async function uploadFiles(files) {
    const selectedFiles = Array.from(files || []);
    if (selectedFiles.length === 0) {
        return;
    }

    showUploadModal();

    for (const file of selectedFiles) {
        if (!isSupportedUploadFile(file.name)) {
            updateUploadProgress(0, 'Upload failed');
            setUploadSummary('error', 'Only ZIP, STL, 3MF, and GCODE files are allowed.');
            appendUploadLog(`[ERROR] ${file.name}: unsupported file type`, 'error');
            return;
        }
    }

    let successCount = 0;
    let skippedCount = 0;
    let errorCount = 0;
    const totalFiles = selectedFiles.length;

    setUploadSummary('info', `Uploading ${totalFiles} file(s)...`);
    startUploadTimer();

    for (let idx = 0; idx < selectedFiles.length; idx++) {
        const file = selectedFiles[idx];
        const current = idx + 1;

        updateUploadProgress(
            Math.round((idx / totalFiles) * 100),
            `Uploading ${current}/${totalFiles}: ${file.name}`
        );

        const result = await uploadSingleFile(file);
        const label = result.folder_name || result.filename || file.name;

        if (result.status === 'success') {
            successCount += 1;
            appendUploadLog(`[OK] ${result.filename} -> ${label}`, 'success');
        } else if (result.status === 'skipped') {
            skippedCount += 1;
            appendUploadLog(`[SKIP] ${result.filename}: skipped (name conflict)`, 'skipped');
        } else {
            errorCount += 1;
            appendUploadLog(`[ERROR] ${result.filename}: ${result.error || 'upload failed'}`, 'error');
        }

        setUploadSummary('info', formatBatchSummary(totalFiles, successCount, skippedCount, errorCount));
        updateUploadProgress(
            Math.round((current / totalFiles) * 90),
            `Processed ${current}/${totalFiles} files`
        );
    }

    updateUploadProgress(95, 'Refreshing library index...');
    try {
        const refreshResult = await refreshIndexAfterBatchUpload();
        if (refreshResult.ok) {
            appendUploadLog('Index refresh completed.', 'success');
            // Jump to first page so newly uploaded models are visible immediately.
            if (typeof loadPage === 'function') {
                loadPage(1);
            }
        } else {
            appendUploadLog(
                `Index refresh failed${refreshResult.error ? `: ${refreshResult.error}` : ''}. Data may be stale until next refresh.`,
                'error'
            );
            errorCount += 1;
        }
    } catch (error) {
        appendUploadLog(`Index refresh failed: ${error.message || 'unknown error'}`, 'error');
        errorCount += 1;
    }

    stopUploadTimer();
    updateUploadProgress(100, 'Upload complete');
    setUploadSummary(
        errorCount > 0 ? 'error' : 'success',
        formatBatchSummary(totalFiles, successCount, skippedCount, errorCount)
    );

    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.value = '';
    }
}

function loadSTLFiles(folders) {
    clearScenes();
    const content = document.getElementById('content');

    folders.forEach(folder => {
        const folderName = folder['folder_name'];
        const topLevelFolder = folder['top_level_folder'];
        const files = folder['files'];
        const threeMfProjects = folder['three_mf_projects'] || [];

        const folderContainer = document.createElement('div');
        folderContainer.className = 'folder-container';

        const folderHeader = document.createElement('h3');
        folderHeader.style.display = 'flex';
        folderHeader.style.alignItems = 'center';
        folderHeader.style.justifyContent = 'center';

        const folderTitle = document.createElement('span');
        folderTitle.innerText = folderName;
        folderHeader.appendChild(folderTitle);

        // Add folder icon
        const folderIcon = document.createElement('a');
        folderIcon.href = `/folder/${encodeURIComponent(topLevelFolder)}`;
        folderIcon.className = 'bi bi-folder2-open'; // Bootstrap Icon class
        folderIcon.style.marginLeft = '10px';
        folderIcon.style.cursor = 'pointer';
        folderIcon.style.textDecoration = 'none';
        folderIcon.style.color = 'inherit';
        folderHeader.appendChild(folderIcon);

        folderContainer.appendChild(folderHeader);

        // Create a row container
        const rowContainer = document.createElement('div');
        rowContainer.className = 'row';

        files.forEach(file => {
            const stlFile = file['file_name'];
            const relPath = file['rel_path'];

            const scene = new THREE.Scene();

            const containerElement = document.createElement('div');
            containerElement.className = 'list-item col-md-4';

            // Use shared STL item creation
            const stlItem = createSTLItem(file, containerElement, scene, rowContainer);
            scenes.push(scene);

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        // Using shared loadSTLFile function from shared_3d_renderer.js
                        loadSTLFile(relPath, scene, stlItem.controls, containerElement.querySelector('div:nth-child(3)'), stlItem.camera);
                        observer.unobserve(containerElement);
                    }
                });
            }, observerOptions);

            observer.observe(containerElement);
        });

        // Render 3MF plates in the same folder grid as STL files.
        threeMfProjects.forEach(project => {
            const plates = project['plates'] || [];
            plates.forEach(plate => {
                const scene = new THREE.Scene();
                const containerElement = document.createElement('div');
                containerElement.className = 'list-item col-md-4';

                const sceneElement = document.createElement('div');
                sceneElement.className = 'rendering';
                containerElement.appendChild(sceneElement);

                const descriptionElement = document.createElement('div');
                descriptionElement.className = 'file-name';
                const plateName = (plate.metadata || {}).plater_name || `Plate ${plate.index}`;
                descriptionElement.innerText = `${project.file_name} - ${plateName}`;
                descriptionElement.style.fontSize = '0.875rem';
                descriptionElement.style.color = '#888';
                containerElement.appendChild(descriptionElement);

                const sizeElement = document.createElement('div');
                containerElement.appendChild(sizeElement);

                const detailsElement = document.createElement('div');
                detailsElement.className = 'three-mf-key-values';

                const filamentType = ((plate.filaments || [])[0] || {}).type || '';
                const layerHeight = (project.project_settings || {}).layer_height || '';
                const sparseInfillDensity = (project.project_settings || {}).sparse_infill_density || '';
                const usageInfo = extractPlateUsageInfo(plate);

                const details = [];
                if (filamentType) details.push(`Material: ${filamentType}`);
                if (layerHeight) details.push(`Layer Height: ${layerHeight}`);
                if (sparseInfillDensity) details.push(`Infill: ${sparseInfillDensity}`);
                if (plate.instance_count !== null && plate.instance_count !== undefined) details.push(`Instances: ${plate.instance_count}`);
                if (usageInfo.printTime) details.push(`Time: ${usageInfo.printTime}`);
                if (usageInfo.weight) details.push(`Weight: ${usageInfo.weight}`);
                if (usageInfo.filamentUsed) details.push(`Filament: ${usageInfo.filamentUsed}`);
                if (details.length > 0) {
                    detailsElement.innerText = details.join(' | ');
                }
                containerElement.appendChild(detailsElement);

                const buttonContainer = document.createElement('div');
                buttonContainer.className = 'file-action-buttons';

                const openFolderBtn = document.createElement('button');
                openFolderBtn.className = 'file-action-btn download-stl';
                openFolderBtn.innerText = 'Open Folder';
                openFolderBtn.onclick = function () {
                    window.location.href = `/folder/${encodeURIComponent(topLevelFolder)}`;
                };
                buttonContainer.appendChild(openFolderBtn);

                containerElement.appendChild(buttonContainer);

                scene.userData.element = sceneElement;
                rowContainer.appendChild(containerElement);
                scenes.push(scene);

                const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
                scene.userData.camera = camera;

                const controls = new THREE.OrbitControls(camera, sceneElement);
                controls.minDistance = 0.1;
                controls.maxDistance = 1000;
                controls.enablePan = true;
                controls.enableZoom = true;
                scene.userData.controls = controls;

                scene.add(new THREE.HemisphereLight(0xaaaaaa, 0x444444, 1.5));
                const light = new THREE.DirectionalLight(0xffffff, 1);
                light.position.set(1, 1, 1).normalize();
                scene.add(light);

                const observer = new IntersectionObserver((entries) => {
                    entries.forEach(entry => {
                        if (!entry.isIntersecting) {
                            return;
                        }
                        const plateUrl = `/3mf_plate?file=${encodeURIComponent(project.rel_path)}&plate=${encodeURIComponent(plate.index)}`;
                        loadSTLFromUrl(
                            plateUrl,
                            scene,
                            controls,
                            sizeElement,
                            camera
                        );
                        observer.unobserve(containerElement);
                    });
                }, observerOptions);

                observer.observe(containerElement);
            });
        });

        folderContainer.appendChild(rowContainer);
        content.appendChild(folderContainer);
    });

    renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true});
    renderer.setClearColor(0xffffff, 1);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setAnimationLoop(animate);
}

function extractPlateUsageInfo(plate) {
    const sliceInfo = plate.slice_info || {};
    const filaments = plate.filaments || [];

    const printTime = sliceInfo.prediction || sliceInfo.estimated_time || sliceInfo.time || '';
    let weight = sliceInfo.weight || sliceInfo.total_weight || sliceInfo.filament_weight || '';

    let totalUsedG = 0;
    let totalUsedM = 0;
    filaments.forEach(filament => {
        const g = parseFloat(filament.used_g);
        const m = parseFloat(filament.used_m);
        if (!Number.isNaN(g)) {
            totalUsedG += g;
        }
        if (!Number.isNaN(m)) {
            totalUsedM += m;
        }
    });

    let filamentUsed = '';
    if (totalUsedG > 0 && totalUsedM > 0) {
        filamentUsed = `${totalUsedG.toFixed(2)}g / ${totalUsedM.toFixed(2)}m`;
    } else if (totalUsedG > 0) {
        filamentUsed = `${totalUsedG.toFixed(2)}g`;
    } else if (totalUsedM > 0) {
        filamentUsed = `${totalUsedM.toFixed(2)}m`;
    }

    if (!weight && totalUsedG > 0) {
        weight = `${totalUsedG.toFixed(2)}g`;
    }

    return {
        printTime: printTime,
        weight: weight,
        filamentUsed: filamentUsed,
    };
}

// View management functions
let currentView = 'paginated'; // 'infinite-scroll' or 'paginated'
let currentPage = 1;
let currentFilter = '';
const defaultSortBy = 'created_at';
const defaultSortOrder = 'desc';
let currentSortBy = defaultSortBy;
let currentSortOrder = defaultSortOrder;

// Initialize with paginated view
document.addEventListener('DOMContentLoaded', function() {
    // Show pagination controls
    const paginationControls = document.getElementById('pagination-controls');
    if (paginationControls) {
        paginationControls.style.display = 'flex';
    }
    
    const urlParams = new URLSearchParams(window.location.search);
    const initialPage = parseInt(urlParams.get('page')) || 1;
    loadPage(initialPage, {pushState: false});
});

function loadPage(page, options = {}) {
    const pushState = options.pushState !== false;
    currentPage = page;
    
    // Get filter and sort options
    const searchInput = document.getElementById('search-input');
    const sortBySelect = document.getElementById('sort-by');
    const sortOrderSelect = document.getElementById('sort-order');
    const urlParams = new URLSearchParams(window.location.search);
    
    const filterText = searchInput ? searchInput.value : '';
    const sortBy = sortBySelect ? sortBySelect.value : (urlParams.get('sort_by') || defaultSortBy);
    const sortOrder = sortOrderSelect ? sortOrderSelect.value : (urlParams.get('sort_order') || defaultSortOrder);
    
    // Get filter type from URL parameters
    const filterType = urlParams.get('filter_type') || 'all';
    
    // Update current values
    currentFilter = filterText;
    currentSortBy = sortBy;
    currentSortOrder = sortOrder;
    
    // Update URL without page reload
    if (pushState) {
        const newUrl = new URL(window.location);
        newUrl.searchParams.set('page', page);
        newUrl.searchParams.set('sort_by', sortBy);
        newUrl.searchParams.set('sort_order', sortOrder);
        newUrl.searchParams.set('filter_type', filterType);
        if (filterText) {
            newUrl.searchParams.set('filter', filterText);
        } else {
            newUrl.searchParams.delete('filter');
        }
        window.history.pushState({}, '', newUrl);
    }
    
    // Make API call
    const url = `/api/stl_files?page=${page}&filter=${encodeURIComponent(filterText)}&sort_by=${encodeURIComponent(sortBy)}&sort_order=${encodeURIComponent(sortOrder)}&filter_type=${encodeURIComponent(filterType)}`;
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            // Load files
            loadSTLFiles(data.folders);
            
            // Update metadata
            const metadataDiv = document.getElementById('metadata');
            if (metadataDiv) {
                metadataDiv.innerText = `Showing ${data.pagination.total_files} files in ${data.pagination.total_folders} folders (page ${data.pagination.page} of ${data.pagination.total_pages})`;
            }
            
            // Update pagination controls
            updatePaginationControls(data.pagination);
        })
        .catch(error => {
            console.error('Error loading page:', error);
            const metadataDiv = document.getElementById('metadata');
            if (metadataDiv) {
                metadataDiv.innerText = 'Error loading data';
            }
        });
}

function updatePaginationControls(pagination) {
    const paginationUl = document.getElementById('pagination');
    const paginationUlBottom = document.getElementById('pagination-bottom');
    if (!paginationUl && !paginationUlBottom) return;
    
    // Clear existing pagination
    if (paginationUl) paginationUl.innerHTML = '';
    if (paginationUlBottom) paginationUlBottom.innerHTML = '';
    
    // Function to add a pagination element to both top and bottom controls
    function addPaginationElement(element) {
        if (paginationUl) {
            // Create a new element for the top pagination
            const topElement = element.cloneNode(true);
            // Re-attach event listeners for the top element
            const topLink = topElement.querySelector('a');
            if (topLink && topLink.dataset.page) {
                topLink.addEventListener('click', function(e) {
                    e.preventDefault();
                    loadPage(parseInt(topLink.dataset.page));
                });
            }
            paginationUl.appendChild(topElement);
        }
        
        if (paginationUlBottom) {
            // Create a new element for the bottom pagination
            const bottomElement = element.cloneNode(true);
            // Re-attach event listeners for the bottom element
            const bottomLink = bottomElement.querySelector('a');
            if (bottomLink && bottomLink.dataset.page) {
                bottomLink.addEventListener('click', function(e) {
                    e.preventDefault();
                    loadPage(parseInt(bottomLink.dataset.page));
                });
            }
            paginationUlBottom.appendChild(bottomElement);
        }
    }
    
    // Function to create a pagination link
    function createPaginationLink(text, page) {
        const li = document.createElement('li');
        li.className = 'page-item';
        const link = document.createElement('a');
        link.className = 'page-link';
        link.href = '#';
        link.innerText = text;
        if (page !== null) {
            link.dataset.page = page; // Store page number in data attribute
        }
        li.appendChild(link);
        return li;
    }
    
    // Add first button
    if (pagination.page > 1) {
        const firstLi = createPaginationLink('First', 1);
        addPaginationElement(firstLi);
    }
    
    // Add previous button
    if (pagination.page > 1) {
        const prevLi = createPaginationLink('Previous', pagination.page - 1);
        addPaginationElement(prevLi);
    }
    
    // Add page numbers (show up to 5 pages around current page)
    const startPage = Math.max(1, pagination.page - 4);
    const endPage = Math.min(pagination.total_pages, pagination.page + 4);
    
    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement('li');
        pageLi.className = 'page-item' + (i === pagination.page ? ' active' : '');
        const pageLink = document.createElement('a');
        pageLink.className = 'page-link';
        pageLink.href = '#';
        pageLink.innerText = i;
        pageLink.dataset.page = i; // Store page number in data attribute
        pageLi.appendChild(pageLink);
        addPaginationElement(pageLi);
    }
    
    // Add next button
    if (pagination.page < pagination.total_pages) {
        const nextLi = createPaginationLink('Next', pagination.page + 1);
        addPaginationElement(nextLi);
    }
    
    // Add last button
    if (pagination.page < pagination.total_pages) {
        const lastLi = createPaginationLink('Last', pagination.total_pages);
        addPaginationElement(lastLi);
    }
}

function refreshCurrentView() {
    loadPage(1);
}

function performSearch(searchTerm) {
    currentFilter = searchTerm;
    loadPage(1);
}

// Handle browser back/forward buttons
window.addEventListener('popstate', function(event) {
    // Get page from URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const page = parseInt(urlParams.get('page')) || 1;
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.value = urlParams.get('filter') || '';
    }
    
    loadPage(page, {pushState: false});
});
