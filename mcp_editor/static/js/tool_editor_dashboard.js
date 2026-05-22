/* Tool Editor Dashboard - MCP Server Dashboard Functions */

// Dashboard data cache
let dashboardData = null;

// ===== Dashboard Modal Functions =====

function openServerDashboard() {
    const modal = document.getElementById('server-dashboard-modal');
    if (modal) {
        modal.style.display = 'flex';
        refreshDashboard();
    }
}

function closeServerDashboard() {
    const modal = document.getElementById('server-dashboard-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// ===== Dashboard Data Functions =====

async function refreshDashboard() {
    const tbody = document.getElementById('dashboard-profiles-body');
    if (!tbody) return;

    // Show loading state
    tbody.innerHTML = `
        <tr>
            <td colspan="5" style="padding: 40px; text-align: center; color: #86868b;">
                <span class="material-icons" style="font-size: 32px; display: block; margin-bottom: 8px; animation: spin 1s linear infinite;">sync</span>
                로딩 중...
            </td>
        </tr>
    `;

    try {
        const response = await fetch('/api/server/dashboard');
        const data = await response.json();

        if (data.error) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="padding: 40px; text-align: center; color: #dc2626;">
                        <span class="material-icons" style="font-size: 32px; display: block; margin-bottom: 8px;">error</span>
                        오류: ${data.error}
                    </td>
                </tr>
            `;
            return;
        }

        dashboardData = data.profiles;
        renderDashboardTable(data.profiles);
        updatePortEditSelector(data.profiles);

        // Update last update time
        const now = new Date();
        document.getElementById('dashboard-last-update').textContent =
            `마지막 업데이트: ${now.toLocaleTimeString('ko-KR')}`;

    } catch (error) {
        console.error('Dashboard fetch error:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="padding: 40px; text-align: center; color: #dc2626;">
                    <span class="material-icons" style="font-size: 32px; display: block; margin-bottom: 8px;">error</span>
                    데이터를 불러올 수 없습니다: ${error.message}
                </td>
            </tr>
        `;
    }
}

function renderDashboardTable(profiles) {
    const tbody = document.getElementById('dashboard-profiles-body');
    if (!tbody || !profiles || profiles.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="padding: 40px; text-align: center; color: #86868b;">
                    <span class="material-icons" style="font-size: 32px; display: block; margin-bottom: 8px;">inbox</span>
                    등록된 프로필이 없습니다
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = profiles.map(profile => {
        // Protocol status badges
        const protocolsHtml = renderProtocolBadges(profile);

        // Relationship badge
        let relationHtml = '';
        if (profile.is_base) {
            relationHtml = `<span style="background: #e3f2fd; color: #1976d2; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">BASE</span>`;
            if (profile.derived_profiles && profile.derived_profiles.length > 0) {
                relationHtml += `<span style="color: #86868b; font-size: 11px; margin-left: 4px;">→ ${profile.derived_profiles.join(', ')}</span>`;
            }
        } else if (profile.is_reused || profile.base_profile) {
            relationHtml = `<span style="background: #fff3e0; color: #ef6c00; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">파생</span>`;
            if (profile.base_profile) {
                relationHtml += `<span style="color: #86868b; font-size: 11px; margin-left: 4px;">← ${profile.base_profile}</span>`;
            }
        } else {
            relationHtml = `<span style="color: #86868b; font-size: 11px;">-</span>`;
        }

        // Port edit button
        const portEditHtml = `
            <button onclick="showPortEdit('${profile.profile}')" class="btn btn-sm" style="padding: 4px 8px; background: #f5f5f5; color: #666; border: none; border-radius: 4px; cursor: pointer;" title="포트 변경">
                <span class="material-icons" style="font-size: 16px;">edit</span>
            </button>
        `;

        return `
            <tr style="border-bottom: 1px solid #f0f0f0;" onmouseover="this.style.background='#fafafa'" onmouseout="this.style.background='white'">
                <td style="padding: 12px 16px;">
                    <span style="font-weight: 600; color: #1d1d1f; cursor: pointer;" onclick="selectProfileFromDashboard('${profile.profile}')" title="이 프로필로 전환">${profile.profile}</span>
                </td>
                <td style="padding: 12px 16px;">
                    <code style="background: #f5f5f5; padding: 2px 6px; border-radius: 4px; font-size: 12px;">${profile.server_name}</code>
                </td>
                <td style="padding: 12px 16px;">
                    <span style="font-family: monospace; font-weight: 600; color: #0071e3;">${profile.port}</span>
                    ${portEditHtml}
                </td>
                <td style="padding: 12px 16px;">${protocolsHtml}</td>
                <td style="padding: 12px 16px;">${relationHtml}</td>
            </tr>
        `;
    }).join('');
}

function renderProtocolBadges(profile) {
    const protocols = profile.protocols || {};
    const protocolLabels = {
        'rest': 'REST',
        'stdio': 'STDIO',
        'stream': 'STREAM'
    };

    return ['rest', 'stdio', 'stream'].map(protocol => {
        const pStatus = protocols[protocol] || {};

        if (!pStatus.available) {
            // Protocol not available (no server file)
            return `<span style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: #f5f5f5; border-radius: 4px; margin: 2px; opacity: 0.5;">
                        <span style="font-size: 11px; color: #999;">${protocolLabels[protocol]}</span>
                        <span style="font-size: 10px; color: #ccc;">N/A</span>
                    </span>`;
        }

        if (pStatus.running) {
            // Running - show stop button
            return `<span style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: #e8f5e9; border-radius: 4px; margin: 2px;">
                        <span style="width: 6px; height: 6px; border-radius: 50%; background: #28a745;"></span>
                        <span style="font-size: 11px; font-weight: 600; color: #2e7d32;">${protocolLabels[protocol]}</span>
                        ${pStatus.pid ? `<span style="font-size: 10px; color: #86868b;">(${pStatus.pid})</span>` : ''}
                        <button onclick="dashboardStopServer('${profile.profile}', '${protocol}')" style="margin-left: 4px; padding: 2px 4px; background: #ffebee; color: #c62828; border: none; border-radius: 3px; cursor: pointer; font-size: 10px;" title="${protocolLabels[protocol]} 서버 중지">
                            <span class="material-icons" style="font-size: 12px;">stop</span>
                        </button>
                    </span>`;
        } else {
            // Stopped - show start button
            return `<span style="display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: #fafafa; border-radius: 4px; margin: 2px; border: 1px dashed #ddd;">
                        <span style="width: 6px; height: 6px; border-radius: 50%; background: #dc3545;"></span>
                        <span style="font-size: 11px; color: #666;">${protocolLabels[protocol]}</span>
                        <button onclick="dashboardStartServer('${profile.profile}', '${protocol}')" style="margin-left: 4px; padding: 2px 4px; background: #e8f5e9; color: #2e7d32; border: none; border-radius: 3px; cursor: pointer; font-size: 10px;" title="${protocolLabels[protocol]} 서버 시작">
                            <span class="material-icons" style="font-size: 12px;">play_arrow</span>
                        </button>
                    </span>`;
        }
    }).join('');
}

function updatePortEditSelector(profiles) {
    const select = document.getElementById('port-edit-profile');
    if (!select) return;

    select.innerHTML = '<option value="">-- 프로필 선택 --</option>';
    profiles.forEach(profile => {
        const option = document.createElement('option');
        option.value = profile.profile;
        option.textContent = `${profile.profile} (현재 포트: ${profile.port})`;
        option.dataset.serverName = profile.server_name;
        option.dataset.port = profile.port;
        select.appendChild(option);
    });

    // Add change handler
    select.onchange = function() {
        const selectedOption = this.options[this.selectedIndex];
        const serverInput = document.getElementById('port-edit-server');
        const portInput = document.getElementById('port-edit-value');

        if (selectedOption.value) {
            serverInput.value = selectedOption.dataset.serverName || '';
            portInput.value = selectedOption.dataset.port || '';
        } else {
            serverInput.value = '';
            portInput.value = '';
        }
    };
}

// ===== Port Edit Functions =====

function showPortEdit(profile) {
    const section = document.getElementById('port-edit-section');
    const select = document.getElementById('port-edit-profile');

    if (section && select) {
        section.style.display = 'block';
        select.value = profile;
        select.dispatchEvent(new Event('change'));

        // Scroll to section
        section.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

async function savePortChange() {
    const profileSelect = document.getElementById('port-edit-profile');
    const portInput = document.getElementById('port-edit-value');

    const profile = profileSelect.value;
    const port = parseInt(portInput.value, 10);

    if (!profile) {
        if (typeof showNotification === 'function') {
            showNotification('프로필을 선택하세요', 'warning');
        } else {
            alert('프로필을 선택하세요');
        }
        return;
    }

    if (!port || port < 1024 || port > 65535) {
        if (typeof showNotification === 'function') {
            showNotification('포트는 1024-65535 사이의 숫자여야 합니다', 'warning');
        } else {
            alert('포트는 1024-65535 사이의 숫자여야 합니다');
        }
        return;
    }

    try {
        const response = await fetch('/api/server/port', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile, port })
        });

        const result = await response.json();

        if (result.success) {
            if (typeof showNotification === 'function') {
                showNotification(`포트가 ${result.old_port}에서 ${result.new_port}로 변경되었습니다`, 'success');
            } else {
                alert(`포트가 ${result.old_port}에서 ${result.new_port}로 변경되었습니다`);
            }
            refreshDashboard();
        } else {
            if (typeof showNotification === 'function') {
                showNotification('포트 변경 실패: ' + result.error, 'error');
            } else {
                alert('포트 변경 실패: ' + result.error);
            }
        }
    } catch (error) {
        console.error('Port update error:', error);
        if (typeof showNotification === 'function') {
            showNotification('포트 변경 중 오류 발생: ' + error.message, 'error');
        } else {
            alert('포트 변경 중 오류 발생: ' + error.message);
        }
    }
}

// ===== Server Control Functions for Dashboard =====

async function dashboardStartServer(profile, protocol = 'stream') {
    const protocolLabels = { 'rest': 'REST', 'stdio': 'STDIO', 'stream': 'STREAM' };
    const protocolLabel = protocolLabels[protocol] || protocol.toUpperCase();

    try {
        const response = await fetch(`/api/server/start?profile=${encodeURIComponent(profile)}&protocol=${encodeURIComponent(protocol)}`, {
            method: 'POST'
        });
        const result = await response.json();

        if (result.success) {
            if (typeof showNotification === 'function') {
                showNotification(`${protocolLabel} 서버 '${profile}' 시작됨 (PID: ${result.pid})`, 'success');
            }
        } else {
            if (typeof showNotification === 'function') {
                showNotification(`${protocolLabel} 서버 시작 실패: ` + result.error, 'error');
            } else {
                alert(`${protocolLabel} 서버 시작 실패: ` + result.error);
            }
        }

        // Refresh after a delay to allow server to start
        setTimeout(refreshDashboard, 1500);

    } catch (error) {
        console.error('Start server error:', error);
        if (typeof showNotification === 'function') {
            showNotification(`${protocolLabel} 서버 시작 오류: ` + error.message, 'error');
        }
    }
}

async function dashboardStopServer(profile, protocol = 'stream') {
    const protocolLabels = { 'rest': 'REST', 'stdio': 'STDIO', 'stream': 'STREAM' };
    const protocolLabel = protocolLabels[protocol] || protocol.toUpperCase();

    try {
        const response = await fetch(`/api/server/stop?profile=${encodeURIComponent(profile)}&protocol=${encodeURIComponent(protocol)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: false })
        });
        const result = await response.json();

        if (result.success) {
            if (typeof showNotification === 'function') {
                showNotification(`${protocolLabel} 서버 '${profile}' 중지됨`, 'success');
            }
        } else {
            if (typeof showNotification === 'function') {
                showNotification(`${protocolLabel} 서버 중지 실패: ` + result.error, 'error');
            } else {
                alert(`${protocolLabel} 서버 중지 실패: ` + result.error);
            }
        }

        // Refresh after a delay
        setTimeout(refreshDashboard, 1000);

    } catch (error) {
        console.error('Stop server error:', error);
        if (typeof showNotification === 'function') {
            showNotification(`${protocolLabel} 서버 중지 오류: ` + error.message, 'error');
        }
    }
}

async function dashboardRestartServer(profile, protocol = 'stream') {
    const protocolLabels = { 'rest': 'REST', 'stdio': 'STDIO', 'stream': 'STREAM' };
    const protocolLabel = protocolLabels[protocol] || protocol.toUpperCase();

    try {
        const response = await fetch(`/api/server/restart?profile=${encodeURIComponent(profile)}&protocol=${encodeURIComponent(protocol)}`, {
            method: 'POST'
        });
        const result = await response.json();

        if (result.success) {
            if (typeof showNotification === 'function') {
                showNotification(`${protocolLabel} 서버 '${profile}' 재시작됨`, 'success');
            }
        } else {
            if (typeof showNotification === 'function') {
                showNotification(`${protocolLabel} 서버 재시작 실패: ` + result.error, 'error');
            } else {
                alert(`${protocolLabel} 서버 재시작 실패: ` + result.error);
            }
        }

        // Refresh after a delay
        setTimeout(refreshDashboard, 1500);

    } catch (error) {
        console.error('Restart server error:', error);
        if (typeof showNotification === 'function') {
            showNotification(`${protocolLabel} 서버 재시작 오류: ` + error.message, 'error');
        }
    }
}

// ===== Profile Selection from Dashboard =====

function selectProfileFromDashboard(profile) {
    // Close dashboard
    closeServerDashboard();

    // Switch to the profile in the main editor
    if (typeof switchProfile === 'function') {
        switchProfile(profile);
    } else if (typeof loadProfile === 'function') {
        loadProfile(profile);
    } else {
        // Fallback: try to find and click the profile tab
        const tabs = document.querySelectorAll('#profileTabs button, #profileTabs .profile-tab');
        for (const tab of tabs) {
            if (tab.textContent.includes(profile) || tab.dataset.profile === profile) {
                tab.click();
                break;
            }
        }
    }

    // Update server control profile
    if (typeof onServerProfileChange === 'function') {
        const serverSelect = document.getElementById('serverProfileSelect');
        if (serverSelect) {
            serverSelect.value = profile;
            onServerProfileChange();
        }
    }
}

// ===== Export Functions =====

window.openServerDashboard = openServerDashboard;
window.closeServerDashboard = closeServerDashboard;
window.refreshDashboard = refreshDashboard;
window.renderProtocolBadges = renderProtocolBadges;
window.showPortEdit = showPortEdit;
window.savePortChange = savePortChange;
window.dashboardStartServer = dashboardStartServer;
window.dashboardStopServer = dashboardStopServer;
window.dashboardRestartServer = dashboardRestartServer;
window.selectProfileFromDashboard = selectProfileFromDashboard;

// Add CSS for spin animation
const style = document.createElement('style');
style.textContent = `
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
`;
document.head.appendChild(style);
