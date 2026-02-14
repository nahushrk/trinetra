import pytest
from playwright.sync_api import expect

@pytest.mark.playwright
def test_homepage_loads(page, base_url):
    # Visit homepage and verify content
    response = page.goto(base_url, wait_until="networkidle")
    assert response.ok, f"Failed to load homepage: {response.status}"
    
    # Verify core elements
    expect(page).to_have_title("Trinetra")
    expect(page.locator('[data-test-id="search-bar"]')).to_be_visible()
    expect(page.locator('[data-test-id="search-input"]')).to_be_visible()
