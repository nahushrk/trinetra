// Unified G-code Renderer Module
// This module contains all G-code parsing and rendering logic
// Used by both folder_view.js and gcode_files.js

// Parse G-code and render it in a Three.js scene
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

// Create printer grid for visualization
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

// Load G-code file from server
function loadGCodeFile(gcodeFile, basePath, scene, controls, camera) {
    fetch(`/gcode/${encodeURIComponent(basePath)}/${encodeURIComponent(gcodeFile)}`)
        .then(response => response.text())
        .then(text => {
            parseGCode(text, scene, controls, camera);
        });
}

// Create a G-code item with rendering
function createGCodeItem(file, containerElement, scene, rowContainer) {
    const gcodeFile = file.file_name;
    const relPath = file.rel_path;
    const basePath = file.path || file.base_path;
    const metadata = file.metadata;

    const sceneElement = document.createElement('div');
    sceneElement.className = 'rendering';
    containerElement.appendChild(sceneElement);

    const descriptionElement = document.createElement('div');
    descriptionElement.className = 'file-name';
    descriptionElement.innerText = gcodeFile;
    descriptionElement.style.fontSize = '0.875rem'; // Make file name smaller
    descriptionElement.style.color = '#888'; // Match the CSS styling
    containerElement.appendChild(descriptionElement);

    // Display GCODE metadata in a contained section
    const gcodeMetadataElement = document.createElement('div');
    gcodeMetadataElement.className = 'gcode-metadata';
    
    if (Object.keys(metadata).length > 0) {
        gcodeMetadataElement.className = 'gcode-metadata metadata-loaded';
        let metadataContent = '<div class="metadata-header"><strong>File Information:</strong></div>';
        for (const [key, value] of Object.entries(metadata)) {
            metadataContent += `<div>${key}: ${value}</div>`;
        }
        gcodeMetadataElement.innerHTML = metadataContent;
    } else {
        gcodeMetadataElement.className = 'gcode-metadata metadata-none';
        gcodeMetadataElement.innerHTML = '<em>No metadata available</em>';
    }
    containerElement.appendChild(gcodeMetadataElement);

    // Add Moonraker statistics section
    const statsElement = document.createElement('div');
    statsElement.className = 'moonraker-stats';
    statsElement.innerHTML = '<em>Loading print statistics...</em>';
    containerElement.appendChild(statsElement);

    // Load Moonraker statistics
    loadMoonrakerStats(gcodeFile, statsElement);

    // Create buttons using shared function
    createFileActionButtons(containerElement, file, ['download', 'copy', 'queue']);

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

    return { scene, controls, camera, relPath, basePath };
}

// Load Moonraker statistics for a G-code file
function loadMoonrakerStats(filename, statsElement) {
    fetch(`/moonraker_stats/${encodeURIComponent(filename)}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.stats) {
                const stats = data.stats;
                const avgDurationHours = Math.floor(stats.avg_duration / 3600);
                const avgDurationMinutes = Math.floor((stats.avg_duration % 3600) / 60);
                
                let statsContent = '<div class="stats-header"><strong>Print Statistics:</strong></div>';
                statsContent += `<div>Total prints: ${stats.total_prints}</div>`;
                statsContent += `<div>Successful: ${stats.successful_prints}</div>`;
                statsContent += `<div>Canceled: ${stats.canceled_prints}</div>`;
                
                if (stats.avg_duration > 0) {
                    statsContent += `<div>Avg duration: ${avgDurationHours}h ${avgDurationMinutes}m</div>`;
                }
                
                if (stats.most_recent_print) {
                    const recentDate = new Date(stats.most_recent_print * 1000);
                    statsContent += `<div>Last printed: ${recentDate.toLocaleDateString()}</div>`;
                }
                
                statsElement.innerHTML = statsContent;
                statsElement.className = 'moonraker-stats stats-loaded';
            } else {
                statsElement.innerHTML = '<em>No print history available</em>';
                statsElement.className = 'moonraker-stats stats-none';
            }
        })
        .catch(error => {
            console.error('Error loading Moonraker stats:', error);
            statsElement.innerHTML = '<em>Failed to load print statistics</em>';
            statsElement.className = 'moonraker-stats stats-error';
        });
}

// Shared button creation function
function createFileActionButtons(containerElement, fileData, buttonTypes = ['download', 'copy', 'queue']) {
    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'file-action-buttons';
    containerElement.appendChild(buttonContainer);

    // Download button
    if (buttonTypes.includes('download')) {
        const downloadButton = document.createElement('button');
        const isGcode = fileData.file_name && fileData.file_name.toLowerCase().endsWith('.gcode');
        downloadButton.className = `file-action-btn ${isGcode ? 'download-gcode' : 'download-stl'}`;
        downloadButton.innerHTML = `<i class="fas fa-download"></i> Download ${isGcode ? 'G-code' : 'STL'}`;
        downloadButton.onclick = function () {
            if (isGcode) {
                window.location.href = `/gcode/${encodeURIComponent(fileData.basePath || fileData.path)}/${encodeURIComponent(fileData.rel_path || fileData.relPath || '')}`;
            } else {
                window.location.href = `/stl/${encodeURIComponent(fileData.rel_path || fileData.relPath || '')}`;
            }
        };
        buttonContainer.appendChild(downloadButton);
    }

    // Copy Path button
    if (buttonTypes.includes('copy')) {
        const copyButton = document.createElement('button');
        copyButton.className = 'file-action-btn copy-path';
        copyButton.innerHTML = '<i class="fas fa-copy"></i> Copy Path';
        copyButton.onclick = function () {
            const endpoint = fileData.file_name && fileData.file_name.toLowerCase().endsWith('.gcode') 
                ? `/copy_gcode_path/${encodeURIComponent(fileData.basePath || fileData.path)}/${encodeURIComponent(fileData.relPath)}`
                : `/copy_path/${encodeURIComponent(fileData.relPath)}`;
            
            fetch(endpoint)
                .then(response => response.json())
                .then(data => {
                    navigator.clipboard.writeText(data.path)
                        .then(() => {
                            // Show success feedback
                            const originalText = copyButton.innerHTML;
                            copyButton.innerHTML = '<i class="fas fa-check"></i> Copied!';
                            copyButton.classList.add('success');
                            setTimeout(() => {
                                copyButton.innerHTML = originalText;
                                copyButton.classList.remove('success');
                            }, 2000);
                        })
                        .catch(err => console.error('Failed to copy path: ', err));
                });
        };
        buttonContainer.appendChild(copyButton);
    }

    // Add to Queue button (only for GCODE files)
    if (buttonTypes.includes('queue') && fileData.file_name && fileData.file_name.toLowerCase().endsWith('.gcode')) {
        const addToQueueButton = document.createElement('button');
        addToQueueButton.className = 'file-action-btn add-to-queue';
        addToQueueButton.innerHTML = '<i class="fas fa-plus"></i> Add to Queue';
        addToQueueButton.onclick = function () {
            addToQueueButton.disabled = true;
            addToQueueButton.classList.add('loading');
            addToQueueButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Adding...';
            
            fetch('/api/add_to_queue', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    filenames: [fileData.relPath],
                    reset: false
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.result === 'ok' || data.result === 'success' || data.job_ids) {
                    addToQueueButton.classList.remove('loading');
                    addToQueueButton.classList.add('success');
                    addToQueueButton.innerHTML = '<i class="fas fa-check"></i> Added!';
                    setTimeout(() => {
                        addToQueueButton.innerHTML = '<i class="fas fa-plus"></i> Add to Queue';
                        addToQueueButton.classList.remove('success');
                        addToQueueButton.disabled = false;
                    }, 2000);
                } else {
                    throw new Error(data.error || 'Unknown error');
                }
            })
            .catch(error => {
                addToQueueButton.classList.remove('loading');
                addToQueueButton.classList.add('error');
                addToQueueButton.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Error!';
                alert('Failed to add to queue: ' + error.message);
                setTimeout(() => {
                    addToQueueButton.innerHTML = '<i class="fas fa-plus"></i> Add to Queue';
                    addToQueueButton.classList.remove('error');
                    addToQueueButton.disabled = false;
                }, 2000);
            });
        };
        buttonContainer.appendChild(addToQueueButton);
    }

    return buttonContainer;
}

// Shared STL rendering functions
function createSTLItem(file, containerElement, scene, rowContainer) {
    const stlFile = file.file_name;
    const relPath = file.rel_path;

    const sceneElement = document.createElement('div');
    sceneElement.className = 'rendering';
    containerElement.appendChild(sceneElement);

    const descriptionElement = document.createElement('div');
    descriptionElement.className = 'file-name';
    descriptionElement.innerText = stlFile;
    descriptionElement.style.fontSize = '0.875rem'; // Make file name smaller
    descriptionElement.style.color = '#888'; // Match the CSS styling
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

    return { scene, controls, camera, relPath };
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

        const sizeText = `(${size.x.toFixed(2)} x ${size.y.toFixed(2)} x ${size.z.toFixed(2)}) mm`;
        sizeElement.innerText = sizeText;
        sizeElement.style.fontSize = '0.875rem'; // Match file name size
        sizeElement.style.color = '#888'; // Match file name color
        sizeElement.style.fontFamily = 'sans-serif'; // Match file name font
        sizeElement.style.textAlign = 'center'; // Match file name alignment
        sizeElement.style.marginTop = '0.5em'; // Match file name margin
        sizeElement.style.wordWrap = 'break-word'; // Match file name word wrap
        sizeElement.style.overflowWrap = 'break-word'; // Match file name overflow wrap
        sizeElement.style.hyphens = 'auto'; // Match file name hyphens
        sizeElement.style.maxWidth = '100%'; // Match file name max width
        sizeElement.style.padding = '0 5px'; // Match file name padding
    });
}

// Shared animation and utility functions
function clearScenes() {
    const content = document.getElementById('content');
    if (content) {
        while (content.firstChild) {
            content.removeChild(content.firstChild);
        }
    }
    scenes = [];
}

function updateSize() {
    const width = window.innerWidth;
    const height = window.innerHeight;

    if (canvas && canvas.width !== width || canvas.height !== height) {
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

// Make functions globally available
window.createPrinterGrid = createPrinterGrid;
window.createSTLItem = createSTLItem;
window.createGCodeItem = createGCodeItem;
window.createFileActionButtons = createFileActionButtons;
window.loadSTLFile = loadSTLFile;
window.loadGCodeFile = loadGCodeFile;
window.loadMoonrakerStats = loadMoonrakerStats;
window.clearScenes = clearScenes;
window.updateSize = updateSize;
window.animate = animate; 