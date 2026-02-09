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

function setLibraryStatus(message, level) {
    const status = document.getElementById("library-history-status");
    status.className = `settings-status ${level}`;
    status.textContent = message;
}

function setBambuStatus(message, level) {
    const status = document.getElementById("bambu-settings-status");
    status.className = `settings-status ${level}`;
    status.textContent = message;
}

function setMoonrakerStatus(message, level) {
    const status = document.getElementById("moonraker-settings-status");
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

function toNonNegativeInteger(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 0) {
        return null;
    }
    return parsed;
}

document.addEventListener("DOMContentLoaded", () => {
    const presetSelect = document.getElementById("printer-preset");
    const saveButton = document.getElementById("save-printer-settings");
    const resetButton = document.getElementById("reset-printer-settings");

    const historyEnabled = document.getElementById("library-history-enabled");
    const historyTtl = document.getElementById("library-history-ttl");
    const saveLibraryButton = document.getElementById("save-library-history-settings");

    const bambuEnabled = document.getElementById("bambu-enabled");
    const bambuMode = document.getElementById("bambu-mode");
    const bambuRegion = document.getElementById("bambu-region");
    const bambuAccessToken = document.getElementById("bambu-access-token");
    const bambuRefreshToken = document.getElementById("bambu-refresh-token");
    const bambuSaveButton = document.getElementById("save-bambu-settings");

    const moonrakerEnabled = document.getElementById("moonraker-enabled");
    const moonrakerBaseUrl = document.getElementById("moonraker-base-url");
    const moonrakerSaveButton = document.getElementById("save-moonraker-settings");

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

    historyEnabled.checked = Boolean(initialLibraryHistorySettings && initialLibraryHistorySettings.enabled);
    historyTtl.value = Number(initialLibraryHistorySettings && initialLibraryHistorySettings.ttl_days || 180);

    saveLibraryButton.addEventListener("click", async () => {
        const ttlValue = toNonNegativeInteger(historyTtl.value);
        if (ttlValue === null) {
            setLibraryStatus("TTL must be a non-negative integer.", "error");
            return;
        }

        saveLibraryButton.disabled = true;
        setLibraryStatus("Saving library settings...", "info");
        try {
            const response = await fetch("/api/settings/library/history", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    enabled: historyEnabled.checked,
                    ttl_days: ttlValue,
                    cleanup_trigger: "refresh",
                }),
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to save library settings");
            }

            const history = data.history || {};
            historyEnabled.checked = Boolean(history.enabled);
            historyTtl.value = Number(history.ttl_days || 0);
            setLibraryStatus("Library settings saved.", "success");
        } catch (error) {
            setLibraryStatus(`Failed to save settings: ${error.message}`, "error");
        } finally {
            saveLibraryButton.disabled = false;
        }
    });

    const initialBambuSettings = (initialBambuIntegration && initialBambuIntegration.settings)
        ? initialBambuIntegration.settings
        : {};
    bambuEnabled.checked = Boolean(initialBambuIntegration && initialBambuIntegration.enabled);
    bambuMode.value = initialBambuSettings.mode || "cloud";
    bambuRegion.value = initialBambuSettings.region || "global";
    bambuAccessToken.value = initialBambuSettings.access_token || "";
    bambuRefreshToken.value = initialBambuSettings.refresh_token || "";

    const toggleBambuFields = () => {
        const disabled = !bambuEnabled.checked;
        bambuMode.disabled = disabled;
        bambuRegion.disabled = disabled;
        bambuAccessToken.disabled = disabled;
        bambuRefreshToken.disabled = disabled;
    };
    toggleBambuFields();

    bambuEnabled.addEventListener("change", toggleBambuFields);

    bambuSaveButton.addEventListener("click", async () => {
        const enabled = bambuEnabled.checked;
        const mode = (bambuMode.value || "cloud").trim().toLowerCase();
        const region = (bambuRegion.value || "global").trim().toLowerCase();
        const accessToken = bambuAccessToken.value.trim();
        const refreshToken = bambuRefreshToken.value.trim();

        if (mode !== "cloud") {
            setBambuStatus("Only cloud mode is available right now.", "error");
            return;
        }
        if (enabled && !accessToken) {
            setBambuStatus("Bambu access token is required when enabled.", "error");
            return;
        }

        bambuSaveButton.disabled = true;
        setBambuStatus("Saving integration settings...", "info");
        try {
            const response = await fetch("/api/settings/integrations/bambu", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    enabled,
                    mode,
                    region,
                    access_token: accessToken,
                    refresh_token: refreshToken,
                }),
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to save bambu integration");
            }

            const integration = data.integration || {};
            const settings = integration.settings || {};
            bambuEnabled.checked = Boolean(integration.enabled);
            bambuMode.value = settings.mode || "cloud";
            bambuRegion.value = settings.region || "global";
            bambuAccessToken.value = settings.access_token || "";
            bambuRefreshToken.value = settings.refresh_token || "";
            toggleBambuFields();
            setBambuStatus("Integration settings saved.", "success");
        } catch (error) {
            setBambuStatus(`Failed to save integration: ${error.message}`, "error");
        } finally {
            bambuSaveButton.disabled = false;
        }
    });

    const initialMoonrakerSettings = (initialMoonrakerIntegration && initialMoonrakerIntegration.settings)
        ? initialMoonrakerIntegration.settings
        : {};
    moonrakerEnabled.checked = Boolean(initialMoonrakerIntegration && initialMoonrakerIntegration.enabled);
    moonrakerBaseUrl.value = initialMoonrakerSettings.base_url || "";
    moonrakerBaseUrl.disabled = !moonrakerEnabled.checked;

    moonrakerEnabled.addEventListener("change", () => {
        moonrakerBaseUrl.disabled = !moonrakerEnabled.checked;
    });

    moonrakerSaveButton.addEventListener("click", async () => {
        const enabled = moonrakerEnabled.checked;
        const baseUrl = moonrakerBaseUrl.value.trim();

        if (enabled && !baseUrl) {
            setMoonrakerStatus("Moonraker URL is required when integration is enabled.", "error");
            return;
        }

        moonrakerSaveButton.disabled = true;
        setMoonrakerStatus("Saving integration settings...", "info");
        try {
            const response = await fetch("/api/settings/integrations/moonraker", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: enabled, base_url: baseUrl }),
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || "Failed to save moonraker integration");
            }

            const integration = data.integration || {};
            const settings = integration.settings || {};
            moonrakerEnabled.checked = Boolean(integration.enabled);
            moonrakerBaseUrl.value = settings.base_url || "";
            moonrakerBaseUrl.disabled = !moonrakerEnabled.checked;
            setMoonrakerStatus("Integration settings saved.", "success");
        } catch (error) {
            setMoonrakerStatus(`Failed to save integration: ${error.message}`, "error");
        } finally {
            moonrakerSaveButton.disabled = false;
        }
    });
});
