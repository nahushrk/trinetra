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
  
    const today     = new Date();
    const todayStr  = today.toISOString().slice(0,10);
  
    // 1. Compute the raw 365-day window ending today:
    const rawStart = new Date(today);
    rawStart.setDate(rawStart.getDate() - 364);
  
    // 2. Back-pad to the Sunday on or before rawStart:
    const pad = rawStart.getDay();                // 0=Sunday…6=Saturday
    const startDate = new Date(rawStart);
    startDate.setDate(rawStart.getDate() - pad);
  
    // 3. Build the grid
    const grid = document.createElement('div');
    grid.className = 'calendar-grid';
  
    // 4. Loop day-by-day from startDate up through today
    const cellDate = new Date(startDate);
    while (cellDate <= today) {
      const dateStr = cellDate.toISOString().slice(0,10);
      const count   = activityData[dateStr] || 0;
      const level   = getDayLevel(count);
  
      const dayDiv = document.createElement('div');
      dayDiv.className = `calendar-day day-level-${level}`;
      dayDiv.setAttribute('data-date', dateStr);
      dayDiv.setAttribute(
        'title',
        `${dateStr}: ${count} print${count===1?'':'s'}`
      );
      if (dateStr === todayStr) {
        dayDiv.classList.add('day-current');
      }
      grid.appendChild(dayDiv);
  
      cellDate.setDate(cellDate.getDate() + 1);
    }
  
    calendar.appendChild(grid);
  }

document.addEventListener('DOMContentLoaded', function() {
    if (typeof activityData !== 'undefined') {
        buildActivityCalendar(activityData);
    }
}); 