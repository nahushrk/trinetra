// G-code Files Page JavaScript
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
    
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase();
        const filteredFiles = gcodeFiles.filter(file => 
            file.file_name.toLowerCase().includes(query) ||
            file.folder_name.toLowerCase().includes(query)
        );
        
        displayGCodeFiles(filteredFiles);
        document.getElementById('metadata').textContent = `Showing ${filteredFiles.length} of ${gcodeFiles.length} files`;
    });

    displayGCodeFiles(gcodeFiles);
    
    // Initialize the renderer after loading the scenes
    renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true});
    renderer.setClearColor(0xffffff, 1);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setAnimationLoop(animate);
    
    // Update metadata
    document.getElementById('metadata').textContent = `Showing ${gcodeFiles.length} files`;
}

// Display G-code files in a 3-column responsive layout
function displayGCodeFiles(files) {
    clearScenes();
    const content = document.getElementById('content');
    content.innerHTML = '';

    if (files.length === 0) {
        content.innerHTML = '<p class="text-center text-muted">No G-code files found.</p>';
        return;
    }

    const rowContainer = document.createElement('div');
    rowContainer.className = 'row';

    files.forEach(file => {
        const scene = new THREE.Scene();
        const containerElement = document.createElement('div');
        containerElement.className = 'list-item col-md-4';

        // Create description element with folder link
        const descriptionElement = document.createElement('div');
        descriptionElement.innerHTML = `
            <strong>${file.file_name}</strong>
            <br>
            <a href="/folder/${encodeURIComponent(file.folder_name)}" class="folder-link">
                <i class="fas fa-folder"></i> ${file.folder_name}
            </a>
        `;
        containerElement.appendChild(descriptionElement);

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

function clearScenes() {
    const content = document.getElementById('content');
    while (content.firstChild) {
        content.removeChild(content.firstChild);
    }
    scenes = [];
}

function updateSize() {
    const width = window.innerWidth;
    const height = window.innerHeight;

    if (canvas.width !== width || canvas.height !== height) {
        renderer.setSize(width, height, false);
    }
}

function animate() {
    if (!renderer) return;
    updateSize();

    renderer.setClearColor(0xffffff);
    renderer.setScissorTest(false);
    renderer.clear();

    renderer.setClearColor(0xe0e0e0);
    renderer.setScissorTest(true);

    scenes.forEach(function (scene) {
        const element = scene.userData.element;
        const rect = element.getBoundingClientRect();

        if (rect.bottom < 0 || rect.top > renderer.domElement.clientHeight ||
            rect.right < 0 || rect.left > renderer.domElement.clientWidth) {
            return;
        }

        const width = rect.right - rect.left;
        const height = rect.bottom - rect.top;
        const left = rect.left;
        const bottom = renderer.domElement.clientHeight - rect.bottom;

        renderer.setViewport(left, bottom, width, height);
        renderer.setScissor(left, bottom, width, height);

        const camera = scene.userData.camera;

        camera.aspect = width / height;
        camera.updateProjectionMatrix();

        scene.userData.controls.update();

        renderer.render(scene, camera);
    });
}

window.addEventListener('resize', updateSize); 