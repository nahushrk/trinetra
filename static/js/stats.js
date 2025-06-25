// Stats Page JavaScript
document.addEventListener('DOMContentLoaded', function() {
    generateActivityCalendar();
});

function generateActivityCalendar() {
    const calendarContainer = document.getElementById('activity-calendar');
    if (!calendarContainer || !activityData) return;

    // Clear existing content
    calendarContainer.innerHTML = '';

    // Create day labels (Mon, Wed, Fri)
    const dayLabels = ['Mon', 'Wed', 'Fri'];
    dayLabels.forEach(day => {
        const dayLabel = document.createElement('div');
        dayLabel.className = 'day-label';
        dayLabel.textContent = day;
        calendarContainer.appendChild(dayLabel);
    });

    // Create month labels
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    
    // Calculate which months should be shown based on the data
    const currentDate = new Date();
    const startDate = new Date(currentDate.getFullYear() - 1, currentDate.getMonth(), currentDate.getDate());
    
    let currentMonth = startDate.getMonth();
    let currentYear = startDate.getFullYear();
    
    while (currentYear < currentDate.getFullYear() || 
           (currentYear === currentDate.getFullYear() && currentMonth <= currentDate.getMonth())) {
        
        const monthLabel = document.createElement('div');
        monthLabel.className = 'month-label';
        monthLabel.textContent = months[currentMonth];
        calendarContainer.appendChild(monthLabel);
        
        // Move to next month
        currentMonth++;
        if (currentMonth >= 12) {
            currentMonth = 0;
            currentYear++;
        }
    }

    // Generate calendar days
    const currentDateStr = new Date().toISOString().split('T')[0];
    
    for (let week = 0; week < 7; week++) {
        for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
            // Skip weekends (Saturday = 5, Sunday = 6)
            if (dayOfWeek === 5 || dayOfWeek === 6) continue;
            
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day';
            
            // Calculate the date for this position
            const date = new Date(startDate);
            date.setDate(startDate.getDate() + (week * 7) + dayOfWeek);
            
            // Skip if date is in the future
            if (date > currentDate) {
                dayElement.style.visibility = 'hidden';
                calendarContainer.appendChild(dayElement);
                continue;
            }
            
            const dateStr = date.toISOString().split('T')[0];
            const printCount = activityData[dateStr] || 0;
            
            // Set activity level based on print count
            let level = 0;
            if (printCount > 0) {
                if (printCount <= 2) level = 1;
                else if (printCount <= 4) level = 2;
                else if (printCount <= 6) level = 3;
                else level = 4;
            }
            
            dayElement.className = `calendar-day day-level-${level}`;
            
            // Add current date border
            if (dateStr === currentDateStr) {
                dayElement.classList.add('day-current');
            }
            
            // Add tooltip data
            const formattedDate = date.toLocaleDateString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
            
            if (printCount > 0) {
                dayElement.setAttribute('data-date', `${formattedDate}: ${printCount} print${printCount > 1 ? 's' : ''}`);
            } else {
                dayElement.setAttribute('data-date', `${formattedDate}: No prints`);
            }
            
            calendarContainer.appendChild(dayElement);
        }
    }
} 