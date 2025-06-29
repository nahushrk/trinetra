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

function showUploadModal() {
    const modal = document.getElementById('upload-modal');
    const progressFill = document.getElementById('upload-progress-fill');
    const progressText = document.getElementById('upload-progress-text');
    const status = document.getElementById('upload-status');
    
    modal.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Preparing upload...';
    status.textContent = 'Ready to upload';
    status.className = 'upload-status info';
}

function hideUploadModal() {
    const modal = document.getElementById('upload-modal');
    modal.style.display = 'none';
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

function uploadFiles(files) {
    // Validate files are zip files
    for (const file of files) {
        if (!file.name.toLowerCase().endsWith('.zip')) {
            alert('Only ZIP files are allowed.');
            return;
        }
    }

    showUploadModal();
    
    const formData = new FormData();
    for (const file of files) {
        formData.append('file', file);
    }

    updateUploadProgress(10, 'Uploading files...', 'info', 'Uploading files to server...');

    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateUploadProgress(100, 'Upload complete!', 'success', 'Files uploaded successfully!');
            
            // Show results
            let resultText = 'Upload Results:\n';
            data.results.forEach(result => {
                if (result.status === 'success') {
                    resultText += `✓ ${result.filename} - ${result.folder_name}`;
                    if (result.folder_existed) {
                        resultText += ' (overwritten)';
                    }
                    resultText += '\n';
                } else {
                    resultText += `✗ ${result.filename} - Error: ${result.error}\n`;
                }
            });
            
            setTimeout(() => {
                alert(resultText);
                hideUploadModal();
                // Refresh the page to show new files
                window.location.reload();
            }, 2000);
        } else {
            updateUploadProgress(0, 'Upload failed', 'error', data.error || 'Upload failed');
            setTimeout(() => {
                hideUploadModal();
            }, 3000);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        updateUploadProgress(0, 'Upload failed', 'error', 'An error occurred during upload');
        setTimeout(() => {
            hideUploadModal();
        }, 3000);
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
