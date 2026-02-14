import pytest
from playwright.sync_api import expect

@pytest.mark.playwright
def test_folder_view_page_loads(page, base_url):
    """Test basic page load with correct title and no errors"""
    response = page.goto(f"{base_url}/folder/test_folder", wait_until="networkidle")
    assert response.ok, f"Failed to load folder view page: {response.status}"
    expect(page).to_have_title("test_folder - Trinetra")
    
    # Verify key elements are present
    expect(page.locator('[data-test-id="folder-name"]')).to_have_text("test_folder")
    expect(page.locator('[data-test-id="delete-folder-btn"]')).to_be_visible()
    expect(page.locator('[data-test-id="download-folder-btn"]')).to_be_visible()

@pytest.mark.playwright
def test_file_sections_visibility(page, base_url):
    """Test visibility of file sections based on available files"""
    page.goto(f"{base_url}/folder/test_folder", wait_until="networkidle")
    
    # Verify STL section is visible (only one mocked in conftest)
    expect(page.locator('[data-test-id="stl-section"]')).to_be_visible()
    expect(page.locator('[data-test-id="3d-canvas"]')).to_be_visible()

@pytest.mark.playwright
def test_empty_folder_view(page, base_url):
    """Test behavior when folder has no files"""
    # Empty folder case is implicitly tested by not having other sections visible
    page.goto(f"{base_url}/folder/test_folder", wait_until="networkidle")
    expect(page.locator('[data-test-id="gcode-section"]')).not_to_be_visible()
    expect(page.locator('[data-test-id="image-section"]')).not_to_be_visible()
    expect(page.locator('[data-test-id="pdf-section"]')).not_to_be_visible()

@pytest.mark.playwright
def test_folder_actions(page, base_url):
    """Test folder action buttons"""
    page.goto(f"{base_url}/folder/test_folder", wait_until="networkidle")
    
    # Verify buttons exist and are clickable
    delete_btn = page.locator('[data-test-id="delete-folder-btn"]')
    download_btn = page.locator('[data-test-id="download-folder-btn"]')
    
    expect(delete_btn).to_be_visible()
    expect(download_btn).to_be_visible()
    
    # Test delete button logs click
    with page.expect_console_message(lambda msg: msg.text == "Delete clicked"):
        delete_btn.click()
    
    # Test download functionality
    with page.expect_console_message(lambda msg: msg.text == "Download clicked"):
        with page.expect_download() as download_info:
            download_btn.click()
    
    download = download_info.value
    assert download.suggested_filename == "test_folder.zip"

@pytest.mark.playwright
def test_responsive_layout(page, base_url):
    """Test responsive behavior at different viewports"""
    # Mobile view
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{base_url}/folder/test_folder", wait_until="networkidle")
    
    # Verify mobile-specific behavior
    expect(page.locator('[data-test-id="folder-name"]')).to_be_visible()
    expect(page.locator('[data-test-id="delete-folder-btn"]')).to_be_visible()
    expect(page.locator('[data-test-id="download-folder-btn"]')).to_be_visible()
    
    # Tablet view
    page.set_viewport_size({"width": 768, "height": 1024})
    expect(page.locator('[data-test-id="folder-name"]')).to_be_visible()
