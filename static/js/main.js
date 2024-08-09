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
    const uploadFileButton = document.getElementById('upload-file');
    const uploadDirectoryButton = document.getElementById('upload-directory');
    const fileInput = document.getElementById('file-input');
    const directoryInput = document.getElementById('directory-input');

    searchInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            performSearch(searchInput.value);
        }
    });

    uploadFileButton.addEventListener('click', (e) => {
        e.preventDefault();
        fileInput.click();
    });

    uploadDirectoryButton.addEventListener('click', (e) => {
        e.preventDefault();
        directoryInput.click();
    });

    fileInput.addEventListener('change', (event) => {
        const files = event.target.files;
        if (files.length > 0) {
            uploadFiles(files);
        }
    });

    directoryInput.addEventListener('change', (event) => {
        const files = event.target.files;
        if (files.length > 0) {
            uploadFiles(files);
        }
    });

    loadSTLFiles(stlFiles);
}

function uploadFiles(files) {
    const formData = new FormData();
    for (const file of files) {
        const relativePath = file.webkitRelativePath || file.name;
        formData.append('file', file, relativePath);
    }

    fetch('/upload', {
        method: 'POST',
        body: formData
    }).then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('Files uploaded successfully.');
                // Optionally, refresh the page or update the displayed files
            } else {
                alert('File upload failed.');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('An error occurred during file upload.');
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
        const folderIcon = document.createElement('i');
        folderIcon.className = 'bi bi-folder2-open'; // Bootstrap Icon class
        folderIcon.style.marginLeft = '10px';
        folderIcon.style.cursor = 'pointer';
        folderIcon.onclick = function () {
            window.open(`/folder/${encodeURIComponent(topLevelFolder)}`, '_blank');
        };
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

            const sceneElement = document.createElement('div');
            sceneElement.className = 'rendering';
            containerElement.appendChild(sceneElement);

            const descriptionElement = document.createElement('div');
            descriptionElement.innerText = stlFile;
            containerElement.appendChild(descriptionElement);

            const sizeElement = document.createElement('div');
            containerElement.appendChild(sizeElement);

            const downloadButton = document.createElement('button');
            downloadButton.innerText = 'Download STL';
            downloadButton.onclick = function () {
                window.location.href = `/stl/${encodeURIComponent(relPath)}`;
            };
            containerElement.appendChild(downloadButton);

            const copyButton = document.createElement('button');
            copyButton.innerText = 'Copy Path';
            copyButton.onclick = function () {
                fetch(`/copy_path/${encodeURIComponent(relPath)}`)
                    .then(response => response.json())
                    .then(data => {
                        navigator.clipboard.writeText(data.path)
                            .then(() => alert(`Copied path: ${data.path}`))
                            .catch(err => console.error('Failed to copy path: ', err));
                    });
            };
            containerElement.appendChild(copyButton);

            scene.userData.element = sceneElement;
            rowContainer.appendChild(containerElement);

            const camera = scene.userData.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
            const controls = scene.userData.controls = new THREE.OrbitControls(camera, sceneElement);
            controls.minDistance = 0.1;
            controls.maxDistance = 1000;
            controls.enablePan = true;
            controls.enableZoom = true;

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

        folderContainer.appendChild(rowContainer);
        content.appendChild(folderContainer);
    });

    renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true});
    renderer.setClearColor(0xffffff, 1);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setAnimationLoop(animate);
}

function loadSTLFile(stlFile, scene, controls, sizeElement, camera) {
    const loader = new THREE.STLLoader();
    loader.load(`/stl/${encodeURIComponent(stlFile)}`, function (geometry) {
        const material = new THREE.MeshNormalMaterial({flatShading: true});
        const mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);

        geometry.computeBoundingSphere();
        const boundingSphere = geometry.boundingSphere;
        const center = boundingSphere.center;
        const radius = boundingSphere.radius;

        geometry.center();

        const fov = camera.fov * (Math.PI / 180);
        let distance = radius / Math.sin(fov / 2);
        distance *= 1.5;

        camera.position.set(distance, distance, distance);
        camera.lookAt(center);

        controls.target.copy(center);
        controls.update();

        const size = new THREE.Vector3();
        geometry.boundingBox.getSize(size);
        const sizeText = `Size: ${size.x.toFixed(2)} mm x ${size.y.toFixed(2)} mm x ${size.z.toFixed(2)} mm`;
        sizeElement.innerText = sizeText;
    });
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
