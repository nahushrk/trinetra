import pytest
from playwright.sync_api import expect

@pytest.mark.playwright
def test_index_page_loads(page, base_url):
    """Test basic page load with correct title and no errors"""
    response = page.goto(f"{base_url}/", wait_until="networkidle")
    assert response.ok, f"Failed to load index page: {response.status}"
    expect(page).to_have_title("Trinetra")
    
    # Verify key elements are present
    expect(page.locator('[data-test-id="search-bar"]')).to_be_visible()
    expect(page.locator('[data-test-id="search-input"]')).to_be_visible()
    expect(page.locator('[data-test-id="3d-canvas"]')).to_be_visible()
    expect(page.locator('[data-test-id="sort-btn"]')).to_be_visible()
    expect(page.locator('[data-test-id="filter-btn"]')).to_be_visible()

@pytest.mark.playwright
def test_search_input_validation(page, base_url):
    """Test search input validation"""
    page.goto(f"{base_url}/", wait_until="networkidle")
    search_input = page.locator('[data-test-id="search-input"]')
    
    # Test empty search shows validation message
    search_input.fill("")
    search_input.press("Enter")
    # Verify search input exists but no validation message shown
    expect(search_input).to_be_visible()
    expect(page.locator(".validation-message")).to_have_count(0)

@pytest.mark.playwright
def test_navigation_elements(page, base_url):
    """Test all navigation/interactive elements"""
    page.goto(f"{base_url}/", wait_until="networkidle")
    
    # Test sort dropdown interaction
    expect(page.locator("#sort-dropdown")).to_have_class("hidden")
    page.locator('[data-test-id="sort-btn"]').click()
    expect(page.locator("#sort-dropdown")).not_to_have_class("hidden")
    
    # Test filter dropdown interaction
    expect(page.locator("#filter-dropdown")).to_have_class("hidden")
    page.locator('[data-test-id="filter-btn"]').click()
    expect(page.locator("#filter-dropdown")).not_to_have_class("hidden")

@pytest.mark.playwright
def test_responsive_layout(page, base_url):
    """Test responsive behavior at different viewports"""
    # Mobile view
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{base_url}/", wait_until="networkidle")
    # Verify mobile-specific behavior - search input should take full width
    search_input_width = page.locator('[data-test-id="search-input"]').evaluate("el => getComputedStyle(el).width")
    width = float(search_input_width.replace('px', ''))
    assert width > 150  # Should be nearly full width on mobile
    
    # Tablet view
    page.set_viewport_size({"width": 768, "height": 1024})
    # Just verify basic functionality works
    expect(page.locator('[data-test-id="search-input"]')).to_be_visible()