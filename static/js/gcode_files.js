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
        const gcodeFile = file.file_name;
        const relPath = file.rel_path;
        const basePath = file.base_path;
        const folderName = file.folder_name;
        const metadata = file.metadata;

        const scene = new THREE.Scene();

        const containerElement = document.createElement('div');
        containerElement.className = 'list-item col-md-4';

        const sceneElement = document.createElement('div');
        sceneElement.className = 'rendering';
        containerElement.appendChild(sceneElement);

        const descriptionElement = document.createElement('div');
        descriptionElement.innerHTML = `
            <strong>${gcodeFile}</strong>
            <br>
            <a href="/folder/${encodeURIComponent(folderName)}" class="folder-link">
                <i class="fas fa-folder"></i> ${folderName}
            </a>
        `;
        containerElement.appendChild(descriptionElement);

        const metadataElement = document.createElement('div');
        metadataElement.className = 'metadata';
        if (metadata && Object.keys(metadata).length > 0) {
            let metadataContent = '';
            for (const [key, value] of Object.entries(metadata)) {
                metadataContent += `<strong>${key}:</strong> ${value}<br>`;
            }
            metadataElement.innerHTML = metadataContent;
        }
        containerElement.appendChild(metadataElement);

        const downloadButton = document.createElement('button');
        downloadButton.innerText = 'Download G-code';
        downloadButton.className = 'btn btn-sm btn-primary';
        downloadButton.onclick = function () {
            window.location.href = `/gcode/${basePath}/${encodeURIComponent(relPath)}`;
        };
        containerElement.appendChild(downloadButton);

        const copyButton = document.createElement('button');
        copyButton.innerText = 'Copy Path';
        copyButton.className = 'btn btn-sm btn-secondary';
        copyButton.onclick = function () {
            fetch(`/copy_gcode_path/${basePath}/${encodeURIComponent(relPath)}`)
                .then(response => response.json())
                .then(data => {
                    navigator.clipboard.writeText(data.path)
                        .then(() => {
                            // Show a brief notification
                            const notification = document.createElement('div');
                            notification.className = 'alert alert-success';
                            notification.style.position = 'fixed';
                            notification.style.top = '20px';
                            notification.style.right = '20px';
                            notification.style.zIndex = '1000';
                            notification.textContent = 'Path copied to clipboard!';
                            document.body.appendChild(notification);
                            
                            setTimeout(() => {
                                document.body.removeChild(notification);
                            }, 2000);
                        })
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

// Load G-code file using the same code from folder_view.js
function loadGCodeFile(gcodeFile, basePath, scene, controls, camera) {
    fetch(`/gcode/${encodeURIComponent(basePath)}/${encodeURIComponent(gcodeFile)}`)
        .then(response => response.text())
        .then(text => {
            parseGCode(text, scene, controls, camera);
        });
}

// Parse G-code using the exact same code from folder_view.js
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

// Create printer grid (same as folder_view.js)
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

// Clear all scenes
function clearScenes() {
    scenes.forEach(scene => {
        if (scene.userData.element) {
            scene.userData.element.innerHTML = '';
        }
    });
    scenes = [];
}

// Handle window resize
function updateSize() {
    const width = window.innerWidth;
    const height = window.innerHeight;

    if (canvas.width !== width || canvas.height !== height) {
        renderer.setSize(width, height, false);
    }
}

// Animation loop
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