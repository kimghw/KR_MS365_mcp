/* Tool Editor Server - MCP Server Control Functions */

// Current selected protocol for server control
let serverControlProtocol = 'stream';

// ===== MCP Server Control Functions =====
function serverProfileParam() {
    // Use serverControlProfile and serverControlProtocol for server operations
    let params = [];
    if (serverControlProfile) {
        params.push(`profile=${encodeURIComponent(serverControlProfile)}`);
    }
    if (serverControlProtocol) {
        params.push(`protocol=${encodeURIComponent(serverControlProtocol)}`);
    }
    return params.length > 0 ? '?' + params.join('&') : '';
}

function populateServerProfileSelector() {
    const select = document.getElementById('serverProfileSelect');
    if (!select) return;

    // Clear existing options except the first placeholder
    select.innerHTML = '<option value="">Select profile...</option>';

    // Add all profiles as options
    profiles.forEach(profile => {
        const option = document.createElement('option');
        option.value = profile;
        option.textContent = profile;
        if (profile === serverControlProfile) {
            option.selected = true;
        }
        select.appendChild(option);
    });
}

function onServerProfileChange() {
    const select = document.getElementById('serverProfileSelect');
    if (!select) return;

    serverControlProfile = select.value;
    console.log('Server control profile changed to:', serverControlProfile);

    // Update the profile display in serverInfo
    const profileValue = document.getElementById('profileValue');
    if (profileValue) {
        profileValue.textContent = serverControlProfile || 'default';
    }

    // Update available protocols for this profile
    updateAvailableProtocols();

    // Check status with new profile
    checkServerStatus();
}

function onServerProtocolChange() {
    const select = document.getElementById('serverProtocolSelect');
    if (!select) return;

    serverControlProtocol = select.value;
    console.log('Server control protocol changed to:', serverControlProtocol);

    // Update the protocol display
    const protocolValue = document.getElementById('protocolValue');
    if (protocolValue) {
        protocolValue.textContent = serverControlProtocol.toUpperCase();
    }

    // Check status with new protocol
    checkServerStatus();
}

async function updateAvailableProtocols() {
    const select = document.getElementById('serverProtocolSelect');
    if (!select || !serverControlProfile) return;

    try {
        const response = await fetch(`/api/server/dashboard`);
        const data = await response.json();

        if (data.profiles) {
            const profileData = data.profiles.find(p => p.profile === serverControlProfile);
            if (profileData && profileData.available_protocols) {
                // Update protocol options based on available protocols
                const availableProtocols = profileData.available_protocols;

                // Update option availability
                Array.from(select.options).forEach(option => {
                    const protocol = option.value;
                    if (availableProtocols.includes(protocol)) {
                        option.disabled = false;
                        option.textContent = protocol.toUpperCase();
                    } else {
                        option.disabled = true;
                        option.textContent = protocol.toUpperCase() + ' (N/A)';
                    }
                });

                // If current selection is not available, switch to first available
                if (!availableProtocols.includes(serverControlProtocol) && availableProtocols.length > 0) {
                    serverControlProtocol = availableProtocols[0];
                    select.value = serverControlProtocol;
                }
            }
        }
    } catch (error) {
        console.error('Error updating available protocols:', error);
    }
}

function checkServerStatus() {
    const profileQuery = serverProfileParam();
    fetch(`/api/server/status${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            updateServerStatusUI(data);
        })
        .catch(error => {
            console.error('Error checking server status:', error);
            updateServerStatusUI({ running: false, error: error.message });
        });
}

function updateServerStatusUI(status) {
    const statusIndicator = document.getElementById('statusIndicator');
    const statusText = document.getElementById('statusText');
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    const btnRestart = document.getElementById('btnRestart');
    const pidInfo = document.getElementById('pidInfo');
    const pidValue = document.getElementById('pidValue');
    const profileValue = document.getElementById('profileValue');

    // Get current protocol label
    const protocolLabel = serverControlProtocol ? serverControlProtocol.toUpperCase() : 'STREAM';

    if (status.running) {
        // Server is running
        statusIndicator.style.background = '#28a745';
        statusText.textContent = `${protocolLabel} Running`;
        statusText.style.color = '#28a745';
        btnStart.disabled = true;
        btnStop.disabled = false;
        btnRestart.disabled = false;

        // Show PID info if available
        if (status.pid) {
            pidInfo.style.display = 'block';
            pidValue.textContent = status.pid;
        } else {
            pidInfo.style.display = 'none';
        }
    } else {
        // Server is stopped
        statusIndicator.style.background = '#dc3545';
        statusText.textContent = `${protocolLabel} Stopped`;
        statusText.style.color = '#dc3545';
        btnStart.disabled = false;
        btnStop.disabled = true;
        btnRestart.disabled = true;
        pidInfo.style.display = 'none';
    }

    // Update profile info
    if (profileValue && status.profile) {
        profileValue.textContent = status.profile;
    }
}

function startServer() {
    const profileQuery = serverProfileParam();
    const btnStart = document.getElementById('btnStart');
    const statusText = document.getElementById('statusText');
    const protocolLabel = serverControlProtocol ? serverControlProtocol.toUpperCase() : 'STREAM';

    btnStart.disabled = true;
    statusText.textContent = `${protocolLabel} Starting...`;
    statusText.style.color = '#ffc107';

    fetch(`/api/server/start${profileQuery}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(`${protocolLabel} server started successfully`, 'success');
                checkServerStatus();
            } else {
                showToast(`Failed to start ${protocolLabel} server: ` + (data.error || 'Unknown error'), 'error');
                btnStart.disabled = false;
                statusText.textContent = `${protocolLabel} Stopped`;
                statusText.style.color = '#dc3545';
            }
        })
        .catch(error => {
            showToast(`Error starting ${protocolLabel} server: ` + error.message, 'error');
            btnStart.disabled = false;
            statusText.textContent = `${protocolLabel} Stopped`;
            statusText.style.color = '#dc3545';
        });
}

function stopServer() {
    const profileQuery = serverProfileParam();
    const btnStop = document.getElementById('btnStop');
    const statusText = document.getElementById('statusText');
    const protocolLabel = serverControlProtocol ? serverControlProtocol.toUpperCase() : 'STREAM';

    btnStop.disabled = true;
    statusText.textContent = `${protocolLabel} Stopping...`;
    statusText.style.color = '#ffc107';

    fetch(`/api/server/stop${profileQuery}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: false })
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(`${protocolLabel} server stopped successfully`, 'success');
                checkServerStatus();
            } else {
                showToast(`Failed to stop ${protocolLabel} server: ` + (data.error || 'Unknown error'), 'error');
                btnStop.disabled = false;
                checkServerStatus();
            }
        })
        .catch(error => {
            showToast(`Error stopping ${protocolLabel} server: ` + error.message, 'error');
            btnStop.disabled = false;
            checkServerStatus();
        });
}

function restartServer() {
    const profileQuery = serverProfileParam();
    const btnRestart = document.getElementById('btnRestart');
    const statusText = document.getElementById('statusText');
    const protocolLabel = serverControlProtocol ? serverControlProtocol.toUpperCase() : 'STREAM';

    btnRestart.disabled = true;
    statusText.textContent = `${protocolLabel} Restarting...`;
    statusText.style.color = '#ffc107';

    fetch(`/api/server/restart${profileQuery}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(`${protocolLabel} server restarted successfully`, 'success');
                checkServerStatus();
            } else {
                showToast(`Failed to restart ${protocolLabel} server: ` + (data.error || 'Unknown error'), 'error');
                btnRestart.disabled = false;
                checkServerStatus();
            }
        })
        .catch(error => {
            showToast(`Error restarting ${protocolLabel} server: ` + error.message, 'error');
            btnRestart.disabled = false;
            checkServerStatus();
        });
}
// ===== End of MCP Server Control Functions =====
