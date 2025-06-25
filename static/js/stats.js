// stats.js: Render GitHub-style activity calendar for 3D print activity

// Color levels for print counts
function getDayLevel(count) {
    if (count === 0) return 0;
    if (count === 1) return 1;
    if (count <= 4) return 2;
    if (count <= 9) return 3;
    return 4;
}

function buildActivityCalendar(activityData) {
    const calendar = document.getElementById('activity-calendar');
    if (!calendar) return;
    calendar.innerHTML = '';

    // Prepare date mapping
    const daysInWeek = 7;
    const weeks = 52;
    const totalSquares = daysInWeek * weeks;

    // Find the start date (first key in activityData)
    const dateKeys = Object.keys(activityData);
    if (dateKeys.length === 0) return;
    const startDate = new Date(dateKeys[0]);
    const today = new Date();

    // Find the weekday of the start date (0=Monday, 6=Sunday)
    let startDay = startDate.getDay();
    // Convert JS getDay (0=Sunday) to (0=Monday)
    startDay = (startDay + 6) % 7;

    // Build grid: columns=weeks, rows=days
    let grid = document.createElement('div');
    grid.className = 'calendar-grid';

    // For each week (column)
    let date = new Date(startDate);
    let squareId = 1;
    for (let col = 0; col < weeks; col++) {
        for (let row = 0; row < daysInWeek; row++) {
            // Calculate the date for this square
            // The first column may start mid-week
            let cellDate = new Date(startDate);
            cellDate.setDate(startDate.getDate() + (col * daysInWeek + row) - startDay);
            let dateStr = cellDate.toISOString().slice(0, 10);
            let count = activityData[dateStr] || 0;
            let level = getDayLevel(count);

            let dayDiv = document.createElement('div');
            dayDiv.className = 'calendar-day day-level-' + level;
            dayDiv.id = squareId;
            dayDiv.setAttribute('data-date', dateStr);
            dayDiv.setAttribute('title', `${dateStr}: ${count} print${count === 1 ? '' : 's'}`);
            if (dateStr === today.toISOString().slice(0, 10)) {
                dayDiv.classList.add('day-current');
            }
            grid.appendChild(dayDiv);
            squareId++;
        }
    }
    calendar.appendChild(grid);
}

document.addEventListener('DOMContentLoaded', function() {
    if (typeof activityData !== 'undefined') {
        buildActivityCalendar(activityData);
    }
}); 