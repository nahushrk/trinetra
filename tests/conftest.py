import pytest
from playwright.sync_api import sync_playwright

@pytest.fixture(scope="session")
def playwright():
    with sync_playwright() as p:
        yield p

@pytest.fixture
def browser(playwright):
    browser = playwright.chromium.launch(headless=True)
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
    
    page.route("**/", handle_route)
    
    yield page
    
    # Log all console messages for debugging
    if console_messages:
        print("\nConsole messages during test:")
        for msg in console_messages:
            print(f"  {msg.type.upper()}: {msg.text}")

@pytest.fixture(scope="session")
def base_url():
    return "http://localhost:8969"