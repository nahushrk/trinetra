let canvas, renderer;
let scenes = [];
const observerOptions = {
    root: null,
    rootMargin: '0px',
    threshold: 0.1
};

let modal;
let modalImg;
let closeBtn;
let currentImageIndex = 0;
let imageSources = [];

init();

function init() {
    canvas = document.getElementById('c');

    if (stlFiles && stlFiles.length > 0) {
        loadSTLFiles(stlFiles);
    }
    if (gcodeFiles && gcodeFiles.length > 0) {
        loadGCodeFiles(gcodeFiles);
    }
    if (imageFiles && imageFiles.length > 0) {
        loadImages(imageFiles);
    }
    if (pdfFiles && pdfFiles.length > 0) {
        loadPDFs(pdfFiles);
    }

    // Initialize the renderer after loading the scenes
    renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true});
    renderer.setClearColor(0xffffff, 1);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setAnimationLoop(animate);

    // Get modal elements
    modal = document.getElementById('image-modal');
    modalImg = document.getElementById('modal-image');
    closeBtn = document.getElementsByClassName('close')[0];

    // Close the modal when the 'x' is clicked
    closeBtn.onclick = function () {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    };

    // Close the modal when clicking outside the image
    modal.onclick = function (event) {
        if (event.target === modal) {
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }
    };

    // Listen for keyboard events
    document.addEventListener('keydown', function (event) {
        if (modal.style.display === 'block') {
            if (event.key === 'Escape' || event.key === 'Esc') {
                modal.style.display = 'none';
                document.body.style.overflow = 'auto';
            } else if (event.key === 'ArrowLeft') {
                showPreviousImage();
            } else if (event.key === 'ArrowRight') {
                showNextImage();
            }
        }
    });

    // Event listeners for Delete and Download buttons
    const deleteBtn = document.getElementById('delete-folder-btn');
    const downloadBtn = document.getElementById('download-folder-btn');

    deleteBtn.addEventListener('click', function () {
        if (confirm('Are you sure you want to delete this folder? This action cannot be undone.')) {
            deleteFolder();
        }
    });

    downloadBtn.addEventListener('click', function () {
        downloadFolder();
    });
}

function deleteFolder() {
    fetch('/delete_folder', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({folder_name: folderName})
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('Folder deleted successfully.');
                window.location.href = '/';
            } else {
                alert('Error deleting folder: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('An error occurred while deleting the folder.');
        });
}

function downloadFolder() {
    window.location.href = '/download_folder?folder_name=' + encodeURIComponent(folderName);
}

function loadSTLFiles(files) {
    const content = document.getElementById('stl-content');

    const rowContainer = document.createElement('div');
    rowContainer.className = 'row';

    files.forEach(file => {
        const stlFile = file['file_name'];
        const relPath = file['rel_path'];

        const scene = new THREE.Scene();

        const containerElement = document.createElement('div');
        containerElement.className = 'list-item col-md-4';

        // Use shared STL item creation for consistent styling
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

    content.appendChild(rowContainer);
}

function loadImages(files) {
    const content = document.getElementById('image-content');

    const rowContainer = document.createElement('div');
    rowContainer.className = 'row';

    imageSources = [];

    files.forEach((file, index) => {
        const fileName = file['file_name'];
        const relPath = file['rel_path'];

        const containerElement = document.createElement('div');
        containerElement.className = 'other-item col-md-4';

        const descriptionElement = document.createElement('div');
        descriptionElement.className = 'file-name';
        descriptionElement.innerText = fileName;
        descriptionElement.style.fontSize = '0.875rem'; // Match shared styling
        descriptionElement.style.color = '#888'; // Match shared styling
        containerElement.appendChild(descriptionElement);

        const imgElement = document.createElement('img');
        imgElement.src = `/file/${encodeURIComponent(relPath)}`;
        imgElement.className = 'img-fluid';
        imgElement.style.cursor = 'pointer';

        imageSources.push(imgElement.src);

        imgElement.onclick = function () {
            currentImageIndex = index;
            modal.style.display = 'block';
            modalImg.src = imgElement.src;
            document.body.style.overflow = 'hidden';
        };

        containerElement.appendChild(imgElement);
        rowContainer.appendChild(containerElement);
    });

    content.appendChild(rowContainer);
}

function showPreviousImage() {
    if (currentImageIndex > 0) {
        currentImageIndex--;
    } else {
        currentImageIndex = imageSources.length - 1;
    }
    modalImg.src = imageSources[currentImageIndex];
}

function showNextImage() {
    if (currentImageIndex < imageSources.length - 1) {
        currentImageIndex++;
    } else {
        currentImageIndex = 0;
    }
    modalImg.src = imageSources[currentImageIndex];
}

function loadPDFs(files) {
    const content = document.getElementById('pdf-content');

    files.forEach(file => {
        const fileName = file['file_name'];
        const relPath = file['rel_path'];

        const containerElement = document.createElement('div');
        containerElement.className = 'pdf-item';

        const descriptionElement = document.createElement('div');
        descriptionElement.className = 'file-name';
        descriptionElement.innerText = fileName;
        descriptionElement.style.fontSize = '0.875rem'; // Match shared styling
        descriptionElement.style.color = '#888'; // Match shared styling
        containerElement.appendChild(descriptionElement);

        const iframe = document.createElement('iframe');
        iframe.src = `/file/${encodeURIComponent(relPath)}`;
        iframe.width = '100%';
        iframe.height = '800px'; // Adjust height as needed
        containerElement.appendChild(iframe);

        content.appendChild(containerElement);
    });
}

function loadGCodeFiles(files) {
    const content = document.getElementById('gcode-content');

    const rowContainer = document.createElement('div');
    rowContainer.className = 'row';

    files.forEach((file, index) => {
        const scene = new THREE.Scene();
        const containerElement = document.createElement('div');
        containerElement.className = 'gcode-item col-md-4';

        // Use the unified renderer to create the G-code item
        const gcodeItem = createGCodeItem(file, containerElement, scene, rowContainer);
        
        scenes.push(scene);

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    loadGCodeFile(gcodeItem.relPath, gcodeItem.basePath, scene, gcodeItem.controls, gcodeItem.camera);
                    observer.unobserve(containerElement);
                }
            });
        }, observerOptions);

        observer.observe(containerElement);
    });

    content.appendChild(rowContainer);
}

// Using shared functions from shared_3d_renderer.js
// updateSize and animate are now globally available 