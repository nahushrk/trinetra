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
    if (!canvas) {
        // 3MF-only folders may not render the STL section template block.
        // Create a shared background canvas so all 3D sections can render.
        canvas = document.createElement('canvas');
        canvas.id = 'c';
        canvas.className = 'd-block mx-auto';
        canvas.setAttribute('data-test-id', '3d-canvas');
        document.body.appendChild(canvas);
    }

    if (stlFiles && stlFiles.length > 0) {
        loadSTLFiles(stlFiles);
    }
    if (gcodeFiles && gcodeFiles.length > 0) {
        loadGCodeFiles(gcodeFiles);
    }
    if (threeMfProjects && threeMfProjects.length > 0) {
        loadThreeMfProjects(threeMfProjects);
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

function loadThreeMfProjects(projects) {
    const content = document.getElementById('three-mf-content');
    if (!content) {
        return;
    }

    projects.forEach(project => {
        const projectContainer = document.createElement('div');
        projectContainer.className = 'three-mf-project mb-4';

        const title = document.createElement('h4');
        title.className = 'mb-2';
        title.innerText = project.file_name;
        projectContainer.appendChild(title);

        if (project.error) {
            const errorElement = document.createElement('div');
            errorElement.className = 'alert alert-warning';
            errorElement.innerText = `Unable to parse 3MF project: ${project.error}`;
            projectContainer.appendChild(errorElement);
            content.appendChild(projectContainer);
            return;
        }

        const metadataWrapper = document.createElement('div');
        metadataWrapper.className = 'three-mf-metadata mb-3';

        const modelMeta = project.model_metadata || {};
        const settingsMeta = project.project_settings || {};

        if (Object.keys(modelMeta).length > 0) {
            const modelMetaTitle = document.createElement('div');
            modelMetaTitle.className = 'metadata-header';
            modelMetaTitle.innerText = 'Model Metadata';
            metadataWrapper.appendChild(modelMetaTitle);
            metadataWrapper.appendChild(createKeyValueTable(modelMeta));
        }

        if (Object.keys(settingsMeta).length > 0) {
            const settingsTitle = document.createElement('div');
            settingsTitle.className = 'metadata-header mt-2';
            settingsTitle.innerText = 'Project Settings';
            metadataWrapper.appendChild(settingsTitle);
            metadataWrapper.appendChild(createKeyValueTable(settingsMeta));
        }

        if (metadataWrapper.children.length > 0) {
            projectContainer.appendChild(metadataWrapper);
        }

        const rowContainer = document.createElement('div');
        rowContainer.className = 'row';

        const plates = project.plates || [];
        plates.forEach(plate => {
            const scene = new THREE.Scene();
            scenes.push(scene);

            const containerElement = document.createElement('div');
            containerElement.className = 'list-item col-md-4';

            const sceneElement = document.createElement('div');
            sceneElement.className = 'rendering';
            containerElement.appendChild(sceneElement);

            const titleElement = document.createElement('div');
            titleElement.className = 'file-name';
            titleElement.style.fontSize = '0.875rem';
            titleElement.style.color = '#888';
            const plateName = (plate.metadata || {}).plater_name || `Plate ${plate.index}`;
            titleElement.innerText = plateName;
            containerElement.appendChild(titleElement);

            const sizeElement = document.createElement('div');
            containerElement.appendChild(sizeElement);

            const plateInfo = document.createElement('div');
            plateInfo.className = 'three-mf-plate-info';
            const usageInfo = extractPlateUsageInfo(plate);
            plateInfo.appendChild(
                createKeyValueTable({
                    plate: `#${plate.index}`,
                    plate_name: (plate.metadata || {}).plater_name || '',
                    instance_count: plate.instance_count,
                    print_time: usageInfo.printTime,
                    weight: usageInfo.weight,
                    filament_used: usageInfo.filamentUsed,
                })
            );

            const filaments = plate.filaments || [];
            if (filaments.length > 0) {
                const filamentTitle = document.createElement('div');
                filamentTitle.className = 'metadata-header mt-2';
                filamentTitle.innerText = 'Filaments';
                plateInfo.appendChild(filamentTitle);
                filaments.forEach(filament => {
                    const compactFilament = pickFields(filament, [
                        'type',
                        'color',
                        'used_g',
                        'used_m',
                        'id'
                    ]);
                    plateInfo.appendChild(createKeyValueTable(compactFilament));
                });
            }
            containerElement.appendChild(plateInfo);

            const buttonContainer = document.createElement('div');
            buttonContainer.className = 'file-action-buttons';

            const projectDownloadBtn = document.createElement('button');
            projectDownloadBtn.className = 'file-action-btn download-stl';
            projectDownloadBtn.innerText = 'Download 3MF';
            projectDownloadBtn.onclick = function () {
                window.location.href = `/stl/${encodeURIComponent(project.rel_path)}`;
            };
            buttonContainer.appendChild(projectDownloadBtn);

            const plateDownloadBtn = document.createElement('button');
            plateDownloadBtn.className = 'file-action-btn download-stl';
            plateDownloadBtn.innerText = 'Download Plate STL';
            plateDownloadBtn.onclick = function () {
                const url = `/3mf_plate?file=${encodeURIComponent(project.rel_path)}&plate=${encodeURIComponent(plate.index)}`;
                window.location.href = url;
            };
            buttonContainer.appendChild(plateDownloadBtn);

            containerElement.appendChild(buttonContainer);
            rowContainer.appendChild(containerElement);

            const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
            scene.userData.camera = camera;
            scene.userData.element = sceneElement;

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

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (!entry.isIntersecting) {
                        return;
                    }
                    const plateUrl = `/3mf_plate?file=${encodeURIComponent(project.rel_path)}&plate=${encodeURIComponent(plate.index)}`;
                    loadSTLFromUrl(
                        plateUrl,
                        scene,
                        controls,
                        sizeElement,
                        camera
                    );
                    observer.unobserve(containerElement);
                });
            }, observerOptions);

            observer.observe(containerElement);
        });

        projectContainer.appendChild(rowContainer);
        content.appendChild(projectContainer);
    });
}

function extractPlateUsageInfo(plate) {
    const sliceInfo = plate.slice_info || {};
    const filaments = plate.filaments || [];

    const printTime = sliceInfo.prediction || sliceInfo.estimated_time || sliceInfo.time || '';
    let weight = sliceInfo.weight || sliceInfo.total_weight || sliceInfo.filament_weight || '';

    let totalUsedG = 0;
    let totalUsedM = 0;
    filaments.forEach(filament => {
        const g = parseFloat(filament.used_g);
        const m = parseFloat(filament.used_m);
        if (!Number.isNaN(g)) {
            totalUsedG += g;
        }
        if (!Number.isNaN(m)) {
            totalUsedM += m;
        }
    });

    let filamentUsed = '';
    if (totalUsedG > 0 && totalUsedM > 0) {
        filamentUsed = `${totalUsedG.toFixed(2)}g / ${totalUsedM.toFixed(2)}m`;
    } else if (totalUsedG > 0) {
        filamentUsed = `${totalUsedG.toFixed(2)}g`;
    } else if (totalUsedM > 0) {
        filamentUsed = `${totalUsedM.toFixed(2)}m`;
    }

    if (!weight && totalUsedG > 0) {
        weight = `${totalUsedG.toFixed(2)}g`;
    }

    return {
        printTime: printTime,
        weight: weight,
        filamentUsed: filamentUsed,
    };
}

function pickFields(values, orderedKeys) {
    const out = {};
    orderedKeys.forEach(key => {
        if (values[key] !== null && values[key] !== undefined && values[key] !== '') {
            out[key] = values[key];
        }
    });
    return out;
}

function createKeyValueTable(values) {
    const wrapper = document.createElement('div');
    wrapper.className = 'three-mf-key-values';

    Object.entries(values).forEach(([key, value]) => {
        if (value === null || value === undefined || value === '') {
            return;
        }
        const line = document.createElement('div');
        line.className = 'three-mf-key-value-line';
        line.innerText = `${key}: ${value}`;
        wrapper.appendChild(line);
    });

    return wrapper;
}
