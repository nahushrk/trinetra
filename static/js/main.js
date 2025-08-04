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

    // Get data from data attributes
    const contentDiv = document.getElementById('content');
    const stlFilesData = contentDiv ? contentDiv.getAttribute('data-stl-files') : null;
    let initialStlFiles = [];
    if (stlFilesData) {
        try {
            // Check if stlFilesData is already an object (not a string)
            if (typeof stlFilesData === 'object') {
                initialStlFiles = stlFilesData.folders || stlFilesData;
            } else {
                // Try to parse as JSON
                const parsedData = JSON.parse(stlFilesData);
                initialStlFiles = parsedData.folders || parsedData;
            }
        } catch (e) {
            console.error('Error parsing STL files data:', e);
        }
    }

    loadSTLFiles(initialStlFiles);

    // Sort by and sort order change
    const sortBySelect = document.getElementById('sort-by');
    const sortOrderSelect = document.getElementById('sort-order');
    
    if (sortBySelect) {
        sortBySelect.addEventListener('change', function() {
            refreshCurrentView();
        });
    }
    
    if (sortOrderSelect) {
        sortOrderSelect.addEventListener('change', function() {
            refreshCurrentView();
        });
    }
}

let uploadStartTime = null;
let uploadTimerInterval = null;

function showUploadModal() {
    const modal = document.getElementById('upload-modal');
    const progressFill = document.getElementById('upload-progress-fill');
    const progressText = document.getElementById('upload-progress-text');
    const status = document.getElementById('upload-status');
    const timer = document.getElementById('upload-timer');
    
    modal.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Preparing upload...';
    status.textContent = 'Ready to upload';
    status.className = 'upload-status info';
    timer.textContent = '00:00';
    
    // Reset timer variables
    uploadStartTime = null;
    if (uploadTimerInterval) {
        clearInterval(uploadTimerInterval);
        uploadTimerInterval = null;
    }
}

function hideUploadModal() {
    const modal = document.getElementById('upload-modal');
    modal.style.display = 'none';
    
    // Clear timer interval
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

function updateUploadProgress(percent, text, statusType = 'info', statusText = null) {
    const progressFill = document.getElementById('upload-progress-fill');
    const progressText = document.getElementById('upload-progress-text');
    const status = document.getElementById('upload-status');
    
    progressFill.style.width = percent + '%';
    progressText.textContent = text;
    
    if (statusText) {
        status.textContent = statusText;
        status.className = `upload-status ${statusType}`;
    }
}

async function checkFolderExists(folderName) {
    const response = await fetch('/check_folder_exists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_name: folderName })
    });
    const data = await response.json();
    return data.exists;
}

async function uploadFiles(files) {
    // Validate files are zip files
    for (const file of files) {
        if (!file.name.toLowerCase().endsWith('.zip')) {
            updateUploadProgress(0, 'Upload failed', 'error', 'Only ZIP files are allowed.');
            return;
        }
    }
    showUploadModal();
    // First, always send with conflict_action=check
    const formData = new FormData();
    for (const file of files) {
        formData.append('file', file);
    }
    formData.append('conflict_action', 'check');
    updateUploadProgress(10, 'Checking for conflicts...', 'info', 'Checking for folder conflicts...');
    // Send the check request
    const response = await fetch('/upload', {
        method: 'POST',
        body: formData
    });
    const data = await response.json();
    if (data.ask_user) {
        // There are conflicts, show dialog
        const conflictDialog = document.getElementById('upload-conflict-dialog');
        conflictDialog.style.display = 'block';
        document.getElementById('upload-modal-close').style.pointerEvents = 'none';
        // Show the list of conflicts as a <ul>
        const conflictList = data.conflicts.map(f => `<li>${f}</li>`).join('');
        conflictDialog.querySelector('strong').innerHTML = `Folder Conflict:<br>Conflicting folders:<ul style='color:#dc3545; margin: 0 0 0 1em;'>${conflictList}</ul>`;
        return new Promise((resolve) => {
            const stopBtn = document.getElementById('upload-stop-btn');
            const skipBtn = document.getElementById('upload-skip-btn');
            const overwriteBtn = document.getElementById('upload-overwrite-btn');
            function cleanup() {
                conflictDialog.style.display = 'none';
                document.getElementById('upload-modal-close').style.pointerEvents = '';
                stopBtn.removeEventListener('click', onStop);
                skipBtn.removeEventListener('click', onSkip);
                overwriteBtn.removeEventListener('click', onOverwrite);
            }
            function onStop() {
                cleanup();
                hideUploadModal();
                resolve();
            }
            function onSkip() {
                cleanup();
                actuallyUploadFiles(files, 'skip');
                resolve();
            }
            function onOverwrite() {
                cleanup();
                actuallyUploadFiles(files, 'overwrite');
                resolve();
            }
            stopBtn.addEventListener('click', onStop);
            skipBtn.addEventListener('click', onSkip);
            overwriteBtn.addEventListener('click', onOverwrite);
        });
    } else if (data.success) {
        // No conflicts, upload already done, show results
        updateUploadProgress(100, 'Upload complete!', 'success', 'Files uploaded successfully!');
        if (uploadTimerInterval) {
            clearInterval(uploadTimerInterval);
            uploadTimerInterval = null;
        }
        let resultText = 'Upload Results:<br>';
        data.results.forEach(result => {
            if (result.status === 'success') {
                resultText += `✓ ${result.filename} - ${result.folder_name}`;
                if (result.folder_existed) {
                    resultText += ' (overwritten)';
                }
                resultText += '<br>';
            } else if (result.status === 'skipped') {
                resultText += `⏭️ ${result.filename} - ${result.folder_name} (skipped)<br>`;
            } else {
                resultText += `✗ ${result.filename} - Error: ${result.error}<br>`;
            }
        });
        const status = document.getElementById('upload-status');
        status.innerHTML = resultText;
        status.className = 'upload-status success';
    } else {
        // Some other error
        updateUploadProgress(0, 'Upload failed', 'error', data.error || 'Upload failed');
        if (uploadTimerInterval) {
            clearInterval(uploadTimerInterval);
            uploadTimerInterval = null;
        }
    }
}

function actuallyUploadFiles(files, conflictAction) {
    if (!files || files.length === 0) return;
    showUploadModal();
    const formData = new FormData();
    for (const file of files) {
        formData.append('file', file);
    }
    formData.append('conflict_action', conflictAction);
    updateUploadProgress(10, 'Uploading files...', 'info', 'Uploading files to server...');
    startUploadTimer();
    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateUploadProgress(100, 'Upload complete!', 'success', 'Files uploaded successfully!');
            if (uploadTimerInterval) {
                clearInterval(uploadTimerInterval);
                uploadTimerInterval = null;
            }
            let resultText = 'Upload Results:<br>';
            data.results.forEach(result => {
                if (result.status === 'success') {
                    resultText += `✓ ${result.filename} - ${result.folder_name}`;
                    if (result.folder_existed) {
                        resultText += ' (overwritten)';
                    }
                    resultText += '<br>';
                } else if (result.status === 'skipped') {
                    resultText += `⏭️ ${result.filename} - ${result.folder_name} (skipped)<br>`;
                } else {
                    resultText += `✗ ${result.filename} - Error: ${result.error}<br>`;
                }
            });
            const status = document.getElementById('upload-status');
            status.innerHTML = resultText;
            status.className = 'upload-status success';
        } else {
            updateUploadProgress(0, 'Upload failed', 'error', data.error || 'Upload failed');
            if (uploadTimerInterval) {
                clearInterval(uploadTimerInterval);
                uploadTimerInterval = null;
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        updateUploadProgress(0, 'Upload failed', 'error', 'An error occurred during upload');
        if (uploadTimerInterval) {
            clearInterval(uploadTimerInterval);
            uploadTimerInterval = null;
        }
    });
}

function loadSTLFiles(folders) {
    clearScenes();
    const content = document.getElementById('content');

    folders.forEach(folder => {
        const folderName = folder['folder_name'];
        const topLevelFolder = folder['top_level_folder'];
        const files = folder['files'];

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

        folderContainer.appendChild(rowContainer);
        content.appendChild(folderContainer);
    });

    renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true});
    renderer.setClearColor(0xffffff, 1);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setAnimationLoop(animate);
}

function performSearch(searchTerm) {
    fetch(`/search?q=${encodeURIComponent(searchTerm)}`)
        .then(response => response.json())
        .then(data => {
            loadSTLFiles(data.stl_files);
            updateMetadata(data.metadata.matches);
        });
}

function updateMetadata(matches) {
    const metadataDiv = document.getElementById('metadata');
    metadataDiv.innerText = `Number of matches: ${matches}`;
    metadataDiv.style.color = 'grey';
}

// View management functions
let currentView = 'paginated'; // 'infinite-scroll' or 'paginated'
let currentPage = 1;
let currentFilter = '';
let currentSortBy = 'folder_name';
let currentSortOrder = 'asc';

// Initialize with paginated view
document.addEventListener('DOMContentLoaded', function() {
    // Show pagination controls
    const paginationControls = document.getElementById('pagination-controls');
    if (paginationControls) {
        paginationControls.style.display = 'flex';
    }
    
    // Load first page
    loadPage(1);
});

function loadPage(page) {
    currentPage = page;
    
    // Get filter and sort options
    const searchInput = document.getElementById('search-input');
    const sortBySelect = document.getElementById('sort-by');
    const sortOrderSelect = document.getElementById('sort-order');
    
    const filterText = searchInput ? searchInput.value : '';
    const sortBy = sortBySelect ? sortBySelect.value : 'folder_name';
    const sortOrder = sortOrderSelect ? sortOrderSelect.value : 'asc';
    
    // Update current values
    currentFilter = filterText;
    currentSortBy = sortBy;
    currentSortOrder = sortOrder;
    
    // Make API call
    const url = `/api/stl_files?page=${page}&per_page=15&filter=${encodeURIComponent(filterText)}&sort_by=${encodeURIComponent(sortBy)}&sort_order=${encodeURIComponent(sortOrder)}`;
    
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
    if (!paginationUl) return;
    
    // Clear existing pagination
    paginationUl.innerHTML = '';
    
    // Add previous button
    if (pagination.page > 1) {
        const prevLi = document.createElement('li');
        prevLi.className = 'page-item';
        const prevLink = document.createElement('a');
        prevLink.className = 'page-link';
        prevLink.href = '#';
        prevLink.innerText = 'Previous';
        prevLink.addEventListener('click', function(e) {
            e.preventDefault();
            loadPage(pagination.page - 1);
        });
        prevLi.appendChild(prevLink);
        paginationUl.appendChild(prevLi);
    }
    
    // Add page numbers (show up to 5 pages around current page)
    const startPage = Math.max(1, pagination.page - 2);
    const endPage = Math.min(pagination.total_pages, pagination.page + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement('li');
        pageLi.className = 'page-item' + (i === pagination.page ? ' active' : '');
        const pageLink = document.createElement('a');
        pageLink.className = 'page-link';
        pageLink.href = '#';
        pageLink.innerText = i;
        if (i !== pagination.page) {
            pageLink.addEventListener('click', function(e) {
                e.preventDefault();
                loadPage(i);
            });
        }
        pageLi.appendChild(pageLink);
        paginationUl.appendChild(pageLi);
    }
    
    // Add next button
    if (pagination.page < pagination.total_pages) {
        const nextLi = document.createElement('li');
        nextLi.className = 'page-item';
        const nextLink = document.createElement('a');
        nextLink.className = 'page-link';
        nextLink.href = '#';
        nextLink.innerText = 'Next';
        nextLink.addEventListener('click', function(e) {
            e.preventDefault();
            loadPage(pagination.page + 1);
        });
        nextLi.appendChild(nextLink);
        paginationUl.appendChild(nextLi);
    }
}

function refreshCurrentView() {
    if (currentView === 'paginated') {
        loadPage(1); // Reload first page with new sort/filter options
    } else {
        // For infinite scroll, we would normally reapply filters
        // But for now, we'll just reload with current settings
        performSearch(currentFilter);
    }
}

// Override performSearch to work with both views
function performSearch(searchTerm) {
    if (currentView === 'paginated') {
        // For paginated view, update filter and reload first page
        currentFilter = searchTerm;
        loadPage(1);
    } else {
        // For infinite scroll view, use existing search functionality
        fetch(`/search?q=${encodeURIComponent(searchTerm)}`)
            .then(response => response.json())
            .then(data => {
                loadSTLFiles(data.stl_files);
                updateMetadata(data.metadata.matches);
            });
    }
}
