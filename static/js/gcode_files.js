// G-code Files Page JavaScript
let canvas, renderer;
let scenes = [];
const observerOptions = {
    root: null,
    rootMargin: '50px',  // Only trigger when 50px of the element is visible
    threshold: 0.1
};

init();

function init() {
    canvas = document.getElementById('c');
    const searchInput = document.getElementById('search-input');
    
    // Search only on Enter key
    searchInput.addEventListener('keypress', function(event) {
        if (event.key === 'Enter') {
            performSearch(this.value);
        }
    });

    // Get data from data attributes
    const contentDiv = document.getElementById('content');
    const gcodeFilesData = contentDiv ? contentDiv.getAttribute('data-gcode-files') : null;
    let initialGcodeFiles = [];
    if (gcodeFilesData) {
        try {
            // Check if gcodeFilesData is already an object (not a string)
            if (typeof gcodeFilesData === 'object') {
                initialGcodeFiles = gcodeFilesData.files || gcodeFilesData;
            } else {
                // Try to parse as JSON
                const parsedData = JSON.parse(gcodeFilesData);
                initialGcodeFiles = parsedData.files || parsedData;
            }
        } catch (e) {
            console.error('Error parsing G-code files data:', e);
        }
    }

    displayGCodeFiles(initialGcodeFiles);
    
    // Initialize the renderer after loading the scenes
    renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true});
    renderer.setClearColor(0xffffff, 1);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setAnimationLoop(animate);
    
    // Update metadata
    const metadataDiv = document.getElementById('metadata');
    if (metadataDiv) {
        metadataDiv.textContent = `Showing ${initialGcodeFiles.length} files`;
    }

    // Initialize sort/filter dropdowns
    if (typeof initSortFilterDropdowns !== 'undefined') {
        initSortFilterDropdowns();
    }
}

function performSearch(searchTerm) {
    if (!searchTerm.trim()) {
        // For paginated view, reload first page
        loadPage(1);
        return;
    }

    fetch(`/search_gcode?q=${encodeURIComponent(searchTerm)}`)
        .then(response => response.json())
        .then(data => {
            displayGCodeFiles(data.gcode_files);
            document.getElementById('metadata').textContent = `Found ${data.metadata.matches} matching files`;
        })
        .catch(error => {
            console.error('Search error:', error);
            document.getElementById('metadata').textContent = 'Search failed';
        });
}

// Display G-code files in a 3-column responsive layout, with action buttons (Download, Copy Path, Add to Queue)
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
        containerElement.className = 'gcode-item col-md-4';

        // Use the unified renderer to create the G-code item
        const gcodeItem = createGCodeItem(file, containerElement, scene, rowContainer);
        scenes.push(scene);

        // Folder icon link (below the G-code view)
        const folderLink = document.createElement('a');
        folderLink.href = `/folder/${encodeURIComponent(file.folder_name)}`;
        folderLink.className = 'folder-link d-block text-center mt-2';
        folderLink.innerHTML = '<i class="fas fa-folder fa-2x"></i>';
        containerElement.appendChild(folderLink);

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

window.addEventListener('resize', updateSize);

// View management functions
let currentView = 'paginated'; // 'infinite-scroll' or 'paginated'
let currentPage = 1;
let currentFilter = '';
let currentSortBy = 'folder_name';
let currentSortOrder = 'asc';

// Initialize with paginated view
document.addEventListener('DOMContentLoaded', function() {
    // Show pagination controls
    const paginationControls = document.getElementById('pagination-controls');
    if (paginationControls) {
        paginationControls.style.display = 'flex';
    }
    
    // Load first page
    loadPage(1);
});

function loadPage(page) {
    currentPage = page;
    
    // Get filter and sort options
    const searchInput = document.getElementById('search-input');
    const sortBySelect = document.getElementById('sort-by');
    const sortOrderSelect = document.getElementById('sort-order');
    
    const filterText = searchInput ? searchInput.value : '';
    const sortBy = sortBySelect ? sortBySelect.value : 'folder_name';
    const sortOrder = sortOrderSelect ? sortOrderSelect.value : 'asc';
    
    // Get filter type from URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const filterType = urlParams.get('filter_type') || 'all';
    
    // Update current values
    currentFilter = filterText;
    currentSortBy = sortBy;
    currentSortOrder = sortOrder;
    
    // Update URL without page reload
    const newUrl = new URL(window.location);
    newUrl.searchParams.set('page', page);
    window.history.pushState({}, '', newUrl);
    
    // Make API call
    const url = `/api/gcode_files?page=${page}&filter=${encodeURIComponent(filterText)}&sort_by=${encodeURIComponent(sortBy)}&sort_order=${encodeURIComponent(sortOrder)}&filter_type=${encodeURIComponent(filterType)}`;
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            // Display files
            displayGCodeFiles(data.files);
            
            // Update metadata
            const metadataDiv = document.getElementById('metadata');
            if (metadataDiv) {
                metadataDiv.innerText = `Showing ${data.pagination.total_files} files (page ${data.pagination.page} of ${data.pagination.total_pages})`;
            }
            
            // Update pagination controls
            updatePaginationControls(data.pagination);
        })
        .catch(error => {
            console.error('Error loading page:', error);
            const metadataDiv = document.getElementById('metadata');
            if (metadataDiv) {
                metadataDiv.innerText = 'Error loading data';
            }
        });
}

function updatePaginationControls(pagination) {
    const paginationUl = document.getElementById('pagination');
    if (!paginationUl) return;
    
    // Clear existing pagination
    paginationUl.innerHTML = '';
    
    // Add first button
    if (pagination.page > 1) {
        const firstLi = document.createElement('li');
        firstLi.className = 'page-item';
        const firstLink = document.createElement('a');
        firstLink.className = 'page-link';
        firstLink.href = '#';
        firstLink.innerText = 'First';
        firstLink.addEventListener('click', function(e) {
            e.preventDefault();
            loadPage(1);
        });
        firstLi.appendChild(firstLink);
        paginationUl.appendChild(firstLi);
    }
    
    // Add previous button
    if (pagination.page > 1) {
        const prevLi = document.createElement('li');
        prevLi.className = 'page-item';
        const prevLink = document.createElement('a');
        prevLink.className = 'page-link';
        prevLink.href = '#';
        prevLink.innerText = 'Previous';
        prevLink.addEventListener('click', function(e) {
            e.preventDefault();
            loadPage(pagination.page - 1);
        });
        prevLi.appendChild(prevLink);
        paginationUl.appendChild(prevLi);
    }
    
    // Add page numbers (show up to 5 pages around current page)
    const startPage = Math.max(1, pagination.page - 2);
    const endPage = Math.min(pagination.total_pages, pagination.page + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement('li');
        pageLi.className = 'page-item' + (i === pagination.page ? ' active' : '');
        const pageLink = document.createElement('a');
        pageLink.className = 'page-link';
        pageLink.href = '#';
        pageLink.innerText = i;
        if (i !== pagination.page) {
            pageLink.addEventListener('click', function(e) {
                e.preventDefault();
                loadPage(i);
            });
        }
        pageLi.appendChild(pageLink);
        paginationUl.appendChild(pageLi);
    }
    
    // Add next button
    if (pagination.page < pagination.total_pages) {
        const nextLi = document.createElement('li');
        nextLi.className = 'page-item';
        const nextLink = document.createElement('a');
        nextLink.className = 'page-link';
        nextLink.href = '#';
        nextLink.innerText = 'Next';
        nextLink.addEventListener('click', function(e) {
            e.preventDefault();
            loadPage(pagination.page + 1);
        });
        nextLi.appendChild(nextLink);
        paginationUl.appendChild(nextLi);
    }
    
    // Add last button
    if (pagination.page < pagination.total_pages) {
        const lastLi = document.createElement('li');
        lastLi.className = 'page-item';
        const lastLink = document.createElement('a');
        lastLink.className = 'page-link';
        lastLink.href = '#';
        lastLink.innerText = 'Last';
        lastLink.addEventListener('click', function(e) {
            e.preventDefault();
            loadPage(pagination.total_pages);
        });
        lastLi.appendChild(lastLink);
        paginationUl.appendChild(lastLi);
    }
}

function refreshCurrentView() {
    if (currentView === 'paginated') {
        loadPage(1); // Reload first page with new sort/filter options
    } else {
        // For infinite scroll, we would normally reapply filters
        // But for now, we'll just reload with current settings
        performSearch(currentFilter);
    }
}

// Override performSearch to work with both views
function performSearch(searchTerm) {
    if (currentView === 'paginated') {
        // For paginated view, update filter and reload first page
        currentFilter = searchTerm;
        loadPage(1);
    } else {
        // For infinite scroll view, use existing search functionality
        if (!searchTerm.trim()) {
            // Get data from data attributes
            const contentDiv = document.getElementById('content');
            const gcodeFilesData = contentDiv ? contentDiv.getAttribute('data-gcode-files') : null;
            let initialGcodeFiles = [];
            if (gcodeFilesData) {
                try {
                    // Check if gcodeFilesData is already an object (not a string)
                    if (typeof gcodeFilesData === 'object') {
                        initialGcodeFiles = gcodeFilesData.files || gcodeFilesData;
                    } else {
                        // Try to parse as JSON
                        const parsedData = JSON.parse(gcodeFilesData);
                        initialGcodeFiles = parsedData.files || parsedData;
                    }
                } catch (e) {
                    console.error('Error parsing G-code files data:', e);
                }
            }
            displayGCodeFiles(initialGcodeFiles);
            const metadataDiv = document.getElementById('metadata');
            if (metadataDiv) {
                metadataDiv.textContent = `Showing ${initialGcodeFiles.length} files`;
            }
            return;
        }

        fetch(`/search_gcode?q=${encodeURIComponent(searchTerm)}`)
            .then(response => response.json())
            .then(data => {
                displayGCodeFiles(data.gcode_files);
                const metadataDiv = document.getElementById('metadata');
                if (metadataDiv) {
                    metadataDiv.textContent = `Found ${data.metadata.matches} matching files`;
                }
            })
            .catch(error => {
                console.error('Search error:', error);
                const metadataDiv = document.getElementById('metadata');
                if (metadataDiv) {
                    metadataDiv.textContent = 'Search failed';
                }
            });
    }
}

// Handle browser back/forward buttons
window.addEventListener('popstate', function(event) {
    // Get page from URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const page = parseInt(urlParams.get('page')) || 1;
    
    // Load the page
    loadPage(page);
});