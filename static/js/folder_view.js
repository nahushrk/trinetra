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

function updateSize() {
    const width = window.innerWidth;
    const height = window.innerHeight;

    if (canvas.width !== width || canvas.height !== height) {
        renderer.setSize(width, height, false);
    }
}

function loadGCodeFiles(files) {
    const content = document.getElementById('gcode-content');

    const rowContainer = document.createElement('div');
    rowContainer.className = 'row';

    files.forEach((file, index) => {
        const gcodeFile = file['file_name'];
        const relPath = file['rel_path'];
        const basePath = file['path'];
        const metadata = file['metadata'];

        const scene = new THREE.Scene();

        const containerElement = document.createElement('div');
        containerElement.className = 'gcode-item col-md-4';

        const sceneElement = document.createElement('div');
        sceneElement.className = 'rendering';
        containerElement.appendChild(sceneElement);

        const descriptionElement = document.createElement('div');
        descriptionElement.innerText = gcodeFile;
        containerElement.appendChild(descriptionElement);

        // Display metadata
        const metadataElement = document.createElement('div');
        metadataElement.className = 'metadata';
        let metadataContent = '';
        for (const [key, value] of Object.entries(metadata)) {
            metadataContent += `<strong>${key}:</strong> ${value}<br>`;
        }
        metadataElement.innerHTML = metadataContent;
        containerElement.appendChild(metadataElement);

        const downloadButton = document.createElement('button');
        downloadButton.innerText = 'Download G-code';
        downloadButton.onclick = function () {
            window.location.href = `/gcode/${encodeURIComponent(basePath)}/${encodeURIComponent(relPath)}`;
        };
        containerElement.appendChild(downloadButton);

        const copyButton = document.createElement('button');
        copyButton.innerText = 'Copy Path';
        copyButton.onclick = function () {
            fetch(`/copy_gcode_path/${encodeURIComponent(basePath)}/${encodeURIComponent(relPath)}`)
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

        const camera = new THREE.PerspectiveCamera(50, 1, 1, 10000);
        scene.userData.camera = camera;

        const controls = new THREE.OrbitControls(camera, sceneElement);
        controls.minDistance = 1;
        controls.maxDistance = 10000;
        controls.enablePan = true;
        controls.enableZoom = true;
        scene.userData.controls = controls;

        // Add ambient light
        scene.add(new THREE.AmbientLight(0x888888));

        // Add directional light
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
        directionalLight.position.set(0, 1, 0).normalize();
        scene.add(directionalLight);

        scenes.push(scene);

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    loadGCodeFile(relPath, basePath, scene, controls, camera);
                    observer.unobserve(containerElement);
                }
            });
        }, observerOptions);

        observer.observe(containerElement);
    });

    content.appendChild(rowContainer);
}

function loadGCodeFile(gcodeFile, basePath, scene, controls, camera) {
    fetch(`/gcode/${encodeURIComponent(basePath)}/${encodeURIComponent(gcodeFile)}`)
        .then(response => response.text())
        .then(text => {
            parseGCode(text, scene, controls, camera);
        });
}

function parseGCode(text, scene, controls, camera) {
    var lines = text.split('\n');
    var currentPosition = {x: 0, y: 0, z: 0};
    var previousPosition = {x: 0, y: 0, z: 0};
    var currentType = 'MAIN';
    var relative = false;

    var typeVertices = {}; // Object to hold vertices per type

    // Define the G-code types and their colors
    const typeColors = {
        'SUPPORT': 0x6666ff,     // Light blue
        'FILL': 0x00ff00,        // Green
        'SKIN': 0xffff00,        // Yellow
        'SKIRT': 0xff00ff,       // Magenta
        'WALL-INNER': 0x00ffff,  // Cyan
        'WALL-OUTER': 0xff0000,  // Red
        'MAIN': 0xff6666,        // Light red (default type)
    };

    // Initialize arrays for each type
    for (const type in typeColors) {
        typeVertices[type] = [];
    }

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();

        // Skip empty lines
        if (line === '') continue;

        // Comments
        if (line.startsWith(';')) {
            // Check for type change
            var typeMatch = line.match(/;TYPE:(.*)/);
            if (typeMatch) {
                var typeName = typeMatch[1].trim().toUpperCase();
                if (typeColors.hasOwnProperty(typeName)) {
                    currentType = typeName;
                } else {
                    currentType = 'MAIN';
                }
            }
            continue;
        }

        // Parse commands
        var tokens = line.split(/\s+/);
        var cmd = tokens[0];

        if (cmd === 'G90') {
            relative = false;
            continue;
        } else if (cmd === 'G91') {
            relative = true;
            continue;
        } else if (cmd === 'G1') {
            var x = currentPosition.x;
            var y = currentPosition.y;
            var z = currentPosition.z;
            var hasMovement = false;

            for (var j = 1; j < tokens.length; j++) {
                var token = tokens[j].trim();
                if (token.length === 0) continue;
                var letter = token[0].toUpperCase();
                var valueStr = token.slice(1);
                var value = parseFloat(valueStr);
                if (isNaN(value)) continue;

                if (letter === 'X') {
                    x = relative ? x + value : value;
                    hasMovement = true;
                } else if (letter === 'Y') {
                    y = relative ? y + value : value;
                    hasMovement = true;
                } else if (letter === 'Z') {
                    z = relative ? z + value : value;
                    hasMovement = true;
                }
            }

            previousPosition = {...currentPosition};
            currentPosition = {x: x, y: y, z: z};

            if (hasMovement) {
                if (isFinite(previousPosition.x) && isFinite(previousPosition.y) && isFinite(previousPosition.z) &&
                    isFinite(currentPosition.x) && isFinite(currentPosition.y) && isFinite(currentPosition.z)) {
                    var vertices = typeVertices[currentType];
                    vertices.push(previousPosition.x, previousPosition.y, previousPosition.z);
                    vertices.push(currentPosition.x, currentPosition.y, currentPosition.z);
                }
            }
        } else if (cmd === 'G0') {
            // Travel move, update position but don't add line segment
            var x = currentPosition.x;
            var y = currentPosition.y;
            var z = currentPosition.z;

            for (var j = 1; j < tokens.length; j++) {
                var token = tokens[j].trim();
                if (token.length === 0) continue;
                var letter = token[0].toUpperCase();
                var valueStr = token.slice(1);
                var value = parseFloat(valueStr);
                if (isNaN(value)) continue;

                if (letter === 'X') {
                    x = relative ? x + value : value;
                } else if (letter === 'Y') {
                    y = relative ? y + value : value;
                } else if (letter === 'Z') {
                    z = relative ? z + value : value;
                }
            }

            currentPosition = {x: x, y: y, z: z};
        } else {
            // Other commands are ignored
            continue;
        }
    }

    // Create materials and geometries per type
    for (const type in typeColors) {
        var vertices = typeVertices[type];
        if (vertices.length > 0) {
            var geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
            var material = new THREE.LineBasicMaterial({
                color: typeColors[type],
                // Make the material respond to lighting
                vertexColors: false,
            });
            var lines = new THREE.LineSegments(geometry, material);
            scene.add(lines);
        }
    }

    // Adjust lighting
    scene.add(new THREE.AmbientLight(0x404040)); // Soft ambient light
    var directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(1, 1, 1).normalize();
    scene.add(directionalLight);

    // Add grid
    var grid = createPrinterGrid();
    scene.add(grid);

    // Adjust camera and controls
    // Compute bounding box
    var bbox = new THREE.Box3().setFromObject(scene);
    var size = bbox.getSize(new THREE.Vector3());
    var center = bbox.getCenter(new THREE.Vector3());

    var maxDim = Math.max(size.x, size.y, size.z);
    var fov = camera.fov * (Math.PI / 180);
    var distance = maxDim / (2 * Math.tan(fov / 2));
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
}


function createPrinterGrid() {
    var geometry = new THREE.Geometry();

    var vertices = [
        // Bottom face
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(220, 0, 0),

        new THREE.Vector3(220, 0, 0),
        new THREE.Vector3(220, 220, 0),

        new THREE.Vector3(220, 220, 0),
        new THREE.Vector3(0, 220, 0),

        new THREE.Vector3(0, 220, 0),
        new THREE.Vector3(0, 0, 0),

        // Top face
        new THREE.Vector3(0, 0, 270),
        new THREE.Vector3(220, 0, 270),

        new THREE.Vector3(220, 0, 270),
        new THREE.Vector3(220, 220, 270),

        new THREE.Vector3(220, 220, 270),
        new THREE.Vector3(0, 220, 270),

        new THREE.Vector3(0, 220, 270),
        new THREE.Vector3(0, 0, 270),

        // Vertical edges
        new THREE.Vector3(0, 0, 0),
        new THREE.Vector3(0, 0, 270),

        new THREE.Vector3(220, 0, 0),
        new THREE.Vector3(220, 0, 270),

        new THREE.Vector3(220, 220, 0),
        new THREE.Vector3(220, 220, 270),

        new THREE.Vector3(0, 220, 0),
        new THREE.Vector3(0, 220, 270),
    ];

    geometry.vertices.push(...vertices);

    var material = new THREE.LineBasicMaterial({color: 0x000000});
    var wireframe = new THREE.LineSegments(geometry, material);

    return wireframe;
}
