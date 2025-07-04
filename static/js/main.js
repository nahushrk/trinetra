let canvas, renderer;
let scenes = [];
const observerOptions = {
    root: null,
    rootMargin: '0px',
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

    loadSTLFiles(stlFiles);
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
