document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('config-form');
    const saveStatus = document.getElementById('save-status');
    let baseConfig = {};
    let mergedConfig = {};

    function fetchConfig() {
        fetch('/api/config')
            .then(res => res.json())
            .then(data => {
                baseConfig = data.base || {};
                mergedConfig = data.merged || {};
                renderForm();
            })
            .catch(error => {
                console.error('Error fetching config:', error);
                saveStatus.textContent = 'Error loading config';
            });
    }

    function renderForm() {
        const tableBody = document.getElementById('config-table-body');
        tableBody.innerHTML = '';
        
        Object.keys(mergedConfig).forEach(key => {
            const value = mergedConfig[key];
            const baseValue = baseConfig[key];
            const isOverridden = value !== baseValue;
            
            let inputHtml = '';
            if (typeof value === 'boolean') {
                inputHtml = `<input type="checkbox" class="form-check-input" name="${key}" ${value ? 'checked' : ''} />`;
            } else if (typeof value === 'number') {
                inputHtml = `<input type="number" class="form-control" name="${key}" value="${value}" />`;
            } else {
                inputHtml = `<input type="text" class="form-control" name="${key}" value="${value}" />`;
            }
            
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${key}</td>
                <td>${inputHtml}</td>
                <td>${isOverridden ? '<span class="badge badge-warning">Overridden</span>' : '<span class="badge badge-secondary">Base</span>'}</td>
            `;
            tableBody.appendChild(row);
        });
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        const formData = new FormData(form);
        const newValues = {};
        
        // Collect all form values
        Object.keys(mergedConfig).forEach(key => {
            let val;
            if (typeof mergedConfig[key] === 'boolean') {
                val = form.elements[key].checked;
            } else {
                val = formData.get(key);
                if (val === null || val === '') return;
                if (typeof mergedConfig[key] === 'number') {
                    val = Number(val);
                }
            }
            newValues[key] = val;
        });
        
        // Calculate what's different from base config
        const override = {};
        Object.keys(newValues).forEach(key => {
            if (newValues[key] !== baseConfig[key]) {
                override[key] = newValues[key];
            }
        });
        
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(override)
        })
        .then(res => res.json())
        .then(data => {
            saveStatus.textContent = 'Saved successfully!';
            setTimeout(() => saveStatus.textContent = '', 3000);
            fetchConfig(); // Refresh to show updated state
        })
        .catch(error => {
            console.error('Error saving config:', error);
            saveStatus.textContent = 'Error saving config';
        });
    });

    fetchConfig();
}); 