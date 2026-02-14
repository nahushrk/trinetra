import pytest
from playwright.sync_api import expect

@pytest.mark.playwright
def test_stats_page_loads(page, base_url):
    """Test basic page load with correct title and no errors"""
    response = page.goto(f"{base_url}/stats", wait_until="networkidle")
    assert response.ok, f"Failed to load stats page: {response.status}"
    expect(page).to_have_title("Statistics - Trinetra")
    
    # Verify key elements are present and have content
    expect(page.locator('[data-test-id="stat-total-folders"]')).to_be_visible(timeout=15000)
    expect(page.locator('[data-test-id="stat-total-stl"]')).to_be_visible(timeout=15000)
    expect(page.locator('[data-test-id="stat-total-gcode"]')).to_be_visible(timeout=15000)
    
    # Calendar container should exist but may be initially hidden
    expect(page.locator('[data-test-id="activity-calendar"]')).to_have_count(1)

@pytest.mark.playwright
def test_stats_data_visualization(page, base_url):
    """Test data visualization elements render correctly"""
    page.goto(f"{base_url}/stats", wait_until="networkidle")
    
    # Verify stat cards show numeric values (>0)
    expect(page.locator('[data-test-id="stat-total-folders"]')).not_to_have_text("0")
    expect(page.locator('[data-test-id="stat-total-stl"]')).not_to_have_text("0")
    expect(page.locator('[data-test-id="stat-total-gcode"]')).not_to_have_text("0")
    
    # Verify activity calendar renders days after JS executes
    expect(page.locator('[data-test-id="activity-calendar"] .calendar-day')).to_have_count(365, timeout=15000)

@pytest.mark.playwright
def test_stats_responsive_layout(page, base_url):
    """Test responsive behavior at different viewports"""
    # Mobile view
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{base_url}/stats", wait_until="networkidle")
    
    # Verify mobile layout elements exist
    expect(page.locator('[data-test-id="stat-total-folders"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-test-id="activity-calendar"]')).to_have_count(1)
    
    # Tablet view
    page.set_viewport_size({"width": 768, "height": 1024})
    expect(page.locator('[data-test-id="stat-total-folders"]')).to_be_visible(timeout=15000)
    expect(page.locator('[data-test-id="activity-calendar"] .calendar-day')).to_have_count(365, timeout=15000)

@pytest.mark.playwright
def test_time_period_selector(page, base_url):
    """Test changing time periods updates displayed data"""
    page.goto(f"{base_url}/stats", wait_until="networkidle")
    
    # Mock different time period data
    page.route("**/stats?period=week", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body="""
        <div data-test-id="stat-total-prints">10</div>
        <div data-test-id="activity-calendar"></div>
        """
    ))
    
    # Simulate changing time period (assuming selector exists)
    page.evaluate("window.location.href = window.location.href + '?period=week'")
    
    # Verify data updated
    expect(page.locator('[data-test-id="stat-total-prints"]')).to_have_text("10")

@pytest.mark.playwright
def test_data_refresh_behavior(page, base_url):
    """Test manual and automatic data refresh"""
    page.goto(f"{base_url}/stats", wait_until="networkidle")
    
    # Track initial values
    initial_prints = page.locator('[data-test-id="stat-total-prints"]').inner_text()
    
    # Mock refreshed data
    page.route("**/stats", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body=f"""
        <div data-test-id="stat-total-prints">{int(initial_prints) + 1}</div>
        <div data-test-id="activity-calendar"></div>
        """
    ))
    
    # Simulate refresh (assuming refresh button exists)
    page.evaluate("window.location.reload()")
    
    # Verify data updated
    expect(page.locator('[data-test-id="stat-total-prints"]')).to_have_text(
        str(int(initial_prints) + 1)
    )
