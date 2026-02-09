function getPresetById(presetId) {
    return (popularPrinters || []).find((preset) => preset.id === presetId) || null;
}

function findMatchingPresetId(volume) {
    const x = Number(volume.x);
    const y = Number(volume.y);
    const z = Number(volume.z);
    const matched = (popularPrinters || []).find(
        (preset) => Number(preset.x) === x && Number(preset.y) === y && Number(preset.z) === z
    );
    return matched ? matched.id : "custom";
}

function setVolumeInputs(volume) {
    document.getElementById("printer-x").value = Number(volume.x);
    document.getElementById("printer-y").value = Number(volume.y);
    document.getElementById("printer-z").value = Number(volume.z);
}

function setStatus(message, level) {
    const status = document.getElementById("settings-status");
    status.className = `settings-status ${level}`;
    status.textContent = message;
}

function readVolumeInputs() {
    const x = Number(document.getElementById("printer-x").value);
    const y = Number(document.getElementById("printer-y").value);
    const z = Number(document.getElementById("printer-z").value);
    return { x, y, z };
}

function isValidVolume(volume) {
    return Number.isFinite(volume.x) && Number.isFinite(volume.y) && Number.isFinite(volume.z)
        && volume.x > 0 && volume.y > 0 && volume.z > 0;
}

document.addEventListener("DOMContentLoaded", () => {
    const presetSelect = document.getElementById("printer-preset");
    const saveButton = document.getElementById("save-printer-settings");
    const resetButton = document.getElementById("reset-printer-settings");

    setVolumeInputs(initialPrinterVolume);
    presetSelect.value = findMatchingPresetId(initialPrinterVolume);

    presetSelect.addEventListener("change", () => {
        const preset = getPresetById(presetSelect.value);
        if (!preset) {
            return;
        }
        setVolumeInputs({ x: preset.x, y: preset.y, z: preset.z });
    });

    resetButton.addEventListener("click", () => {
        setVolumeInputs({ x: 220, y: 220, z: 270 });
        presetSelect.value = "custom";
        setStatus("Reset to default volume values. Click Save to persist.", "info");
    });

    saveButton.addEventListener("click", async () => {
        const volume = readVolumeInputs();
        if (!isValidVolume(volume)) {
            setStatus("Please enter valid positive dimensions.", "error");
            return;
        }

        const payload = {
            x: volume.x,
            y: volume.y,
            z: volume.z,
        };
        if (presetSelect.value !== "custom") {
            payload.preset_id = presetSelect.value;
        }

        saveButton.disabled = true;
        setStatus("Saving settings...", "info");
        try {
            const response = await fetch("/api/settings/printer_volume", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to save settings");
            }

            if (!window.TRINETRA_SETTINGS) {
                window.TRINETRA_SETTINGS = {};
            }
            window.TRINETRA_SETTINGS.printer_volume = data.printer_volume;

            setVolumeInputs(data.printer_volume);
            presetSelect.value = findMatchingPresetId(data.printer_volume);
            setStatus("Settings saved. Changes will apply to all 3D previews.", "success");
        } catch (error) {
            setStatus(`Failed to save settings: ${error.message}`, "error");
        } finally {
            saveButton.disabled = false;
        }
    });
});
