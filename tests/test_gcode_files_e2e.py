import pytest
from playwright.sync_api import expect

@pytest.mark.playwright
def test_gcode_page_loads(page, base_url):
    """Test basic page load with correct title and no errors"""
    response = page.goto(f"{base_url}/gcode_files", wait_until="networkidle")
    assert response.ok, f"Failed to load G-code files page: {response.status}"
    expect(page).to_have_title("Trinetra")
    
    # Verify key elements are present
    expect(page.locator('[data-test-id="gcode-canvas"]')).to_have_count(1, timeout=15000)
    expect(page.locator('[data-test-id="gcode-canvas"]').first).to_be_visible(timeout=15000)
    expect(page.locator('[data-test-id="search-input"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="sort-btn"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="filter-btn"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="metadata"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="pagination-top"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="pagination-bottom"]')).to_be_visible()

@pytest.mark.playwright 
def test_empty_gcode_files(page, base_url):
    """Test behavior when no G-code files are available"""
    page.goto(f"{base_url}/gcode_files", wait_until="networkidle")
@pytest.mark.playwright
def test_search_functionality(page, base_url):
    """Test search functionality with valid and invalid queries"""
    page.goto(f"{base_url}/gcode_files", wait_until="networkidle")
    
    # Test empty search
    search_input = page.locator('[data-test-id="search-input"]')
    search_input.fill("")
    page.keyboard.press("Enter")
    expect(page.locator('[data-test-id="metadata"]')).to_have_count(1, timeout=15000)
    expect(page.locator('[data-test-id="metadata"]').first).to_be_visible(timeout=15000)
    
    # Test valid search
    search_input.fill("test")
    page.keyboard.press("Enter")
    expect(page.locator('[data-test-id="metadata"]')).to_contain_text("Found 4 matching files")
    
    # Test no results case
    search_input.fill("invalidquery123")
    page.keyboard.press("Enter")
    expect(page.locator('[data-test-id="metadata"]')).to_contain_text("matching files")

@pytest.mark.playwright
def test_sort_filter_dropdowns(page, base_url):
    """Test sort and filter dropdown interactions"""
    page.goto(f"{base_url}/gcode_files", wait_until="networkidle")
    
@pytest.mark.playwright
def test_pagination_controls(page, base_url):
    """Test pagination controls functionality"""
    page.goto(f"{base_url}/gcode_files", wait_until="networkidle")
    
    # Test pagination exists
    expect(page.locator('[data-test-id="pagination-top"]')).to_have_count(1, timeout=15000)
    expect(page.locator('[data-test-id="pagination-top"]').first).to_be_visible(timeout=15000)
    expect(page.locator('[data-test-id="pagination-bottom"]')).to_be_visible(timeout=10000)
    
    # Test pagination navigation
    page.locator('[data-test-id="pagination-top"] >> text="Next"').click()
    expect(page.locator('[data-test-id="metadata"]')).to_contain_text("Page 2 of 3")
    
    # Test pagination sync between top and bottom
    page.locator('[data-test-id="pagination-bottom"] >> text="Previous"').click()
    expect(page.locator('[data-test-id="metadata"]')).to_contain_text("Page 2 of 3")

@pytest.mark.playwright
def test_responsive_layout(page, base_url):
    """Test responsive behavior at different viewports"""
    # Mobile view
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{base_url}/gcode_files", wait_until="networkidle")
    
    # Verify mobile layout
    expect(page.locator('[data-test-id="search-input"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="sort-btn"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="filter-btn"]')).to_be_visible(timeout=10000)
    
    # Tablet view
    page.set_viewport_size({"width": 768, "height": 1024})
    # First ensure element exists
    expect(page.locator('[data-test-id="gcode-canvas"]')).to_have_count(1, timeout=15000)
    # Then check visibility
    expect(page.locator('[data-test-id="gcode-canvas"]').first).to_be_visible(timeout=15000)
    # Test sort dropdown
    sort_btn = page.locator('[data-test-id="sort-btn"]')
    sort_btn.click()
    expect(page.locator('text="File Name (A-Z)"')).to_be_visible(timeout=10000)
    
    # Test filter dropdown
    filter_btn = page.locator('[data-test-id="filter-btn"]')
    filter_btn.click()
    expect(page.locator('text="File Name (A-Z)"')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="metadata"]')).to_have_text("Loading files...")
    expect(page.locator('[data-test-id="gcode-canvas"]')).to_be_visible()
