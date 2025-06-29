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

        const sceneElement = document.createElement('div');
        sceneElement.className = 'rendering';
        containerElement.appendChild(sceneElement);

        const descriptionElement = document.createElement('div');
        descriptionElement.innerText = stlFile;
        containerElement.appendChild(descriptionElement);

        const sizeElement = document.createElement('div');
        containerElement.appendChild(sizeElement);

        // Create buttons using shared function
        createFileActionButtons(containerElement, file, ['download', 'copy']);

        scene.userData.element = sceneElement;
        rowContainer.appendChild(containerElement);

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

        scenes.push(scene);

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    loadSTLFile(relPath, scene, controls, sizeElement, camera);
                    observer.unobserve(containerElement);
                }
            });
        }, observerOptions);

        observer.observe(containerElement);
    });

    content.appendChild(rowContainer);
}

function loadSTLFile(stlFile, scene, controls, sizeElement, camera) {
    const loader = new THREE.STLLoader();
    loader.load(`/stl/${encodeURIComponent(stlFile)}`, function (geometry) {
        const material = new THREE.MeshNormalMaterial({flatShading: true});
        const mesh = new THREE.Mesh(geometry, material);

        // Center the geometry and compute its bounding box
        geometry.center();
        geometry.computeBoundingBox();
        const bbox = geometry.boundingBox;
        const size = bbox.getSize(new THREE.Vector3());

        // Calculate the offset to place the bottom of the object at Z=0
        const zOffset = size.z / 2;

        // Position the mesh at (110, 110) in the XY plane and adjust Z position
        mesh.position.set(110, 110, zOffset);
        scene.add(mesh);

        // Add grid
        var grid = createPrinterGrid();
        scene.add(grid);

        // Set up camera and controls
        const center = new THREE.Vector3(110, 110, zOffset);
        const radius = Math.max(size.x, size.y, size.z) / 2;

        const fov = camera.fov * (Math.PI / 180);
        let distance = radius / Math.sin(fov / 2);
        distance *= 1.5;

        // Calculate tilt angle in radians
        const tiltAngle = THREE.Math.degToRad(30);

        // Position camera with a 30-degree tilt around the X-axis
        const cameraY = center.y - distance * Math.cos(tiltAngle);
        const cameraZ = center.z + distance * Math.sin(tiltAngle);
        camera.position.set(center.x, cameraY, cameraZ);

        camera.lookAt(center);

        controls.target.copy(center);
        controls.update();

        const sizeText = `Size: ${size.x.toFixed(2)} mm x ${size.y.toFixed(2)} mm x ${size.z.toFixed(2)} mm`;
        sizeElement.innerText = sizeText;
    });
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
        descriptionElement.innerText = fileName;
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
        descriptionElement.innerText = fileName;
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