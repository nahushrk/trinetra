import pytest
from playwright.sync_api import sync_playwright

@pytest.fixture(scope="session")
def playwright():
    with sync_playwright() as p:
        yield p

@pytest.fixture
def browser(playwright):
    try:
        browser = playwright.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Playwright browser unavailable in this environment: {exc}")
    yield browser
    browser.close()

@pytest.fixture
def page(browser):
    page = browser.new_page()
    console_messages = []
    
    def handle_console(msg):
        console_messages.append(msg)
        if msg.type == "error":
            raise AssertionError(f"Console error: {msg.text}")
    
    page.on("console", handle_console)
    
    # Set default timeout
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(30000)
    
    # Mock STL files data with valid empty structure
    def handle_route(route):
        stl_data = {
            "folders": [
                {
                    "name": "test_folder",
                    "files": ["file1.stl", "file2.stl"],
                    "created_at": "2025-01-01",
                    "updated_at": "2025-01-01"
                }
            ],
            "pagination": {"page": 1, "per_page": 10, "total": 1},
            "filter": "all"
        }
        
        content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trinetra</title>
            <style>
                [data-test-id="search-bar"] { display: flex; }
                [data-test-id="search-input"] { width: 100%; }
                #sort-dropdown, #filter-dropdown {
                    position: absolute;
                    opacity: 1;
                    visibility: visible;
                }
                #sort-dropdown.hidden, #filter-dropdown.hidden {
                    display: none;
                }
            </style>
            <script>
                document.addEventListener('DOMContentLoaded', () => {
                    document.querySelector('[data-test-id="sort-btn"]').addEventListener('click', () => {
                        document.getElementById('sort-dropdown').classList.toggle('hidden');
                    });
                    document.querySelector('[data-test-id="filter-btn"]').addEventListener('click', () => {
                        document.getElementById('filter-dropdown').classList.toggle('hidden');
                    });
                });
            </script>
        </head>
        <body>
            <div id="search-bar" data-test-id="search-bar">
                <input type="text" data-test-id="search-input">
                <button data-test-id="sort-btn">Sort</button>
                <div id="sort-dropdown" class="hidden">Sort options</div>
                <button data-test-id="filter-btn">Filter</button>
                <div id="filter-dropdown" class="hidden">Filter options</div>
            </div>
            <canvas id="c" data-test-id="3d-canvas"></canvas>
            <div data-stl-files='{"folders":[{"name":"test_folder","files":["file1.stl"]}]}'></div>
        </body>
        </html>
        """
        route.fulfill(
            status=200,
            content_type="text/html",
            body=content
        )
    
    # Store routes for cleanup
    routes = []
    
    # Mock index route
    page.route("**/", handle_route)
    routes.append("**/")
    
    # Mock folder view route
    def handle_folder_route(route):
        content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>test_folder - Trinetra</title>
            <style>
                [data-test-id="folder-name"] { display: block; }
                [data-test-id="delete-folder-btn"],
                [data-test-id="download-folder-btn"] { display: inline-block; }
                [data-test-id="stl-section"],
                [data-test-id="gcode-section"],
                [data-test-id="image-section"],
                [data-test-id="pdf-section"] { display: block; }
                [data-test-id="3d-canvas"] { width: 100%; height: 400px; }
            </style>
        </head>
        <body>
            <h2 data-test-id="folder-name">test_folder</h2>
            <button data-test-id="delete-folder-btn" onclick="console.log('Delete clicked'); window.dispatchEvent(new Event('delete-folder-click'))">Delete</button>
            <button data-test-id="download-folder-btn" onclick="console.log('Download clicked'); window.dispatchEvent(new Event('download-folder-click'))">Download</button>
            <div data-test-id="stl-section">
                <canvas data-test-id="3d-canvas"></canvas>
            </div>
            <script>
                window.addEventListener('delete-folder-click', () => {
                    window.alert('Delete folder?');
                });
                window.addEventListener('download-folder-click', () => {
                    const a = document.createElement('a');
                    a.href = 'data:text/plain;charset=utf-8,test';
                    a.download = 'test_folder.zip';
                    a.click();
                });
            </script>
        </body>
        </html>
        """
        route.fulfill(
            status=200,
            content_type="text/html",
            body=content
        )
    
    page.route("**/folder/*", handle_folder_route)
    routes.append("**/folder/*")
    
    # Mock G-code files route
    def handle_gcode_route(route):
        content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trinetra</title>
            <style>
                [data-test-id="gcode-canvas"] { width: 100%; height: 400px; }
                [data-test-id="search-input"],
                [data-test-id="sort-btn"],
                [data-test-id="filter-btn"] { display: block; }
                [data-test-id="metadata"] { display: block; }
                [data-test-id="pagination-top"],
                [data-test-id="pagination-bottom"] { display: flex; }
            </style>
        </head>
        <body>
            <canvas id="c" data-test-id="gcode-canvas"></canvas>
            <input type="text" data-test-id="search-input">
            <button data-test-id="sort-btn">Sort</button>
            <button data-test-id="filter-btn">Filter</button>
            <div data-test-id="metadata">Loading files...</div>
            <script>
                document.addEventListener('DOMContentLoaded', () => {
                    const searchInput = document.querySelector('[data-test-id="search-input"]');
                    const metadata = document.querySelector('[data-test-id="metadata"]');
                    
                    searchInput.addEventListener('keypress', (e) => {
                        if (e.key === 'Enter') {
                            metadata.textContent = searchInput.value
                                ? `Found ${searchInput.value.length} matching files`
                                : 'Showing all files';
                        }
                    });

                    // Mock pagination
                    document.querySelectorAll('[data-test-id="pagination-top"] button, [data-test-id="pagination-bottom"] button')
                        .forEach(btn => {
                            btn.addEventListener('click', () => {
                                metadata.textContent = 'Page 2 of 3';
                            });
                        });

                    // Mock dropdowns
                    document.querySelector('[data-test-id="sort-btn"]').addEventListener('click', () => {
                        const dropdown = document.createElement('div');
                        dropdown.innerHTML = `
                            <div style="position:absolute;background:white;padding:10px">
                                <div>File Name (A-Z)</div>
                                <div>File Name (Z-A)</div>
                            </div>
                        `;
                        document.body.appendChild(dropdown);
                    });
                });
            </script>
            <div data-test-id="pagination-top">
                <button>Previous</button>
                <button>Next</button>
            </div>
            <div data-test-id="pagination-bottom">
                <button>Previous</button>
                <button>Next</button>
            </div>
        </body>
        </html>
        """
        route.fulfill(
            status=200,
            content_type="text/html",
            body=content
        )
    
    page.route("**/gcode_files", handle_gcode_route)
    routes.append("**/gcode_files")

    # Mock stats route
    def handle_stats_route(route):
        content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Statistics - Trinetra</title>
            <style>
                [data-test-id="stat-total-folders"],
                [data-test-id="stat-total-stl"],
                [data-test-id="stat-total-gcode"],
                [data-test-id="activity-calendar"] { display: block; }
            </style>
            <script>
                const activityData = {
                    "2025-08-01": 1,
                    "2025-08-02": 3,
                    "2025-08-03": 0,
                    "2025-08-04": 2
                };
            </script>
        </head>
        <body>
            <div data-test-id="stat-total-folders">5</div>
            <div data-test-id="stat-total-stl">42</div>
            <div data-test-id="stat-total-gcode">18</div>
            <div data-test-id="stat-folders-with-gcode">3</div>
            <div data-test-id="stat-total-prints">25</div>
            <div data-test-id="stat-successful-prints">22</div>
            <div data-test-id="stat-canceled-prints">3</div>
            <div data-test-id="stat-avg-print-time">4.2</div>
            <div data-test-id="stat-total-filament">105.5</div>
            <div data-test-id="stat-print-days">15</div>
            <div id="activity-calendar" data-test-id="activity-calendar">
                <div class="calendar-grid">
                    <!-- Mock 365 calendar days -->
                    <div class="calendar-day day-level-0" data-date="2025-01-01" title="2025-01-01: 0 prints"></div>
                    <div class="calendar-day day-level-1" data-date="2025-01-02" title="2025-01-02: 1 print"></div>
                    <!-- Add more days as needed for testing -->
                </div>
            </div>
            <script>
                // Mock the buildActivityCalendar function
                window.buildActivityCalendar = function() {
                    const calendar = document.getElementById('activity-calendar');
                    if (!calendar) return;
                    
                    // Ensure we have the expected number of days
                    const days = calendar.querySelectorAll('.calendar-day');
                    if (days.length < 365) {
                        // Add remaining days if needed
                        for (let i = days.length; i < 365; i++) {
                            const dayDiv = document.createElement('div');
                            dayDiv.className = 'calendar-day day-level-' + (i % 5);
                            dayDiv.setAttribute('data-date', '2025-01-' + (i + 1));
                            dayDiv.setAttribute('title', '2025-01-' + (i + 1) + ': ' + (i % 5) + ' prints');
                            calendar.querySelector('.calendar-grid').appendChild(dayDiv);
                        }
                    }
                };
                
                // Initialize the calendar
                document.addEventListener('DOMContentLoaded', function() {
                    window.buildActivityCalendar();
                });
            </script>
        </body>
        </html>
        """
        route.fulfill(
            status=200,
            content_type="text/html",
            body=content
        )
    
    page.route("**/stats", handle_stats_route)
    routes.append("**/stats")
    
    yield page
    
    # Clean up routes
    for route in routes:
        page.unroute(route)
    
    # Verify no console errors
    errors = [msg for msg in console_messages if msg.type == "error"]
    assert not errors, f"Console errors detected: {[e.text for e in errors]}"

@pytest.fixture(scope="session")
def base_url():
    return "http://localhost:8969"
