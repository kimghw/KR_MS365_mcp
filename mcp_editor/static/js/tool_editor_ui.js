/**
 * MCP Tool Editor - UI Module
 *
 * This module contains all UI rendering and interaction functions
 * for the MCP Tool Editor web interface.
 *
 * Dependencies:
 * - MCPEditor.state (from tool_editor_core.js)
 * - MCPEditor.config (from tool_editor_core.js)
 */

(function() {
    'use strict';

    // ============================================================================
    // TEMPLATE SOURCE SELECTOR
    // ============================================================================

    /**
     * Renders the template source selector dropdown
     * Shows current template, backups, and other profile templates
     */
    function renderTemplateSourceSelector() {
        const select = document.getElementById('templateSource');
        if (!select) return;

        const templateSources = MCPEditor.state.templateSources || [];

        select.innerHTML = '<option value="">-- Current Template --</option>';
        templateSources.forEach(source => {
            if (source.type === 'current') return; // Skip current, it's the default

            const opt = document.createElement('option');
            opt.value = source.path;

            // Format: "backup_20241217.py (5 tools)" or "outlook template (3 tools)"
            const dateStr = source.modified ? new Date(source.modified).toLocaleString() : '';
            let label = source.name;
            if (source.type === 'backup') {
                label = `📦 ${source.name}`;
            } else if (source.type === 'other_profile') {
                label = `📁 ${source.name}`;
            }
            opt.textContent = `${label} (${source.count} tools)`;
            opt.title = dateStr ? `Modified: ${dateStr}` : '';
            select.appendChild(opt);
        });

        // Update save target label
        const saveLabel = document.getElementById('saveTargetLabel');
        if (saveLabel) {
            saveLabel.textContent = MCPEditor.state.originalProfile || 'default';
        }
    }

    // ============================================================================
    // SERVER STATUS UI
    // ============================================================================

    /**
     * Updates the server status UI components
     * @param {Object} status - Server status object with running, pid, profile properties
     */
    function updateServerStatusUI(status) {
        const statusIndicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        const btnStart = document.getElementById('btnStart');
        const btnStop = document.getElementById('btnStop');
        const btnRestart = document.getElementById('btnRestart');
        const pidInfo = document.getElementById('pidInfo');
        const pidValue = document.getElementById('pidValue');
        const profileValue = document.getElementById('profileValue');

        if (status.running) {
            // Server is running
            statusIndicator.style.background = '#28a745';
            statusText.textContent = 'Running';
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
            statusText.textContent = 'Stopped';
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

    // ============================================================================
    // PROFILE TABS
    // ============================================================================

    /**
     * Check if a profile is protected (cannot be deleted)
     */
    function isProtectedProfile(profileName) {
        const protectedProfiles = ['outlook', 'calendar', 'file_handler'];
        return protectedProfiles.includes(profileName.toLowerCase());
    }

    /**
     * Delete a profile after confirmation
     */
    function deleteProfile(profileName) {
        if (isProtectedProfile(profileName)) {
            alert(`Cannot delete protected profile: ${profileName}`);
            return;
        }

        const confirmMsg = `Are you sure you want to delete profile "${profileName}"?\n\n` +
            `This will delete:\n` +
            `- mcp_editor/mcp_${profileName}/\n` +
            `- mcp_${profileName}/ (if exists)\n` +
            `- Profile from editor_config.json\n\n` +
            `This action cannot be undone!`;

        if (!confirm(confirmMsg)) {
            return;
        }

        fetch('/api/delete-mcp-profile', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile_name: profileName })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                alert(`Profile "${profileName}" deleted successfully.\n\nDeleted:\n${data.deleted_paths.join('\n')}`);
                location.reload();
            } else {
                alert('Delete failed: ' + data.error);
            }
        })
        .catch(error => {
            alert('Delete failed: ' + error.message);
        });
    }

    // Expose deleteProfile to global scope for onclick handlers
    window.deleteProfile = deleteProfile;

    /**
     * Renders the profile tabs UI
     * Shows all available profiles with the current one highlighted
     * Includes base MCP server info and delete button for non-protected profiles
     */
    function renderProfileTabs() {
        const tabContainer = document.getElementById('profileTabs');
        if (!tabContainer) return;

        const profiles = MCPEditor.state.profiles || [];
        const profileDetails = MCPEditor.state.profileDetails || {};
        const currentProfile = MCPEditor.state.currentProfile;

        tabContainer.innerHTML = '';
        if (!profiles || profiles.length === 0) {
            tabContainer.textContent = 'No profiles found (using default)';
        } else {
            profiles.filter(name => name && name.trim()).forEach((name, index) => {
                // Create a wrapper div for profile tab with delete button
                const tabWrapper = document.createElement('div');
                tabWrapper.style = 'display: inline-flex; flex-direction: column; align-items: center; gap: 2px; position: relative;';

                const btn = document.createElement('button');
                btn.className = 'btn btn-secondary';
                btn.setAttribute('data-debug-id', `PROFILE_${index + 1}`);
                btn.style = 'border-radius: 8px; padding: 10px 20px; font-size: 15px; min-width: 120px; text-align: center; font-weight: bold;';
                if (name === currentProfile) {
                    btn.style.background = 'var(--primary-color)';
                    btn.style.color = '#fff';
                }
                btn.textContent = name;
                btn.onclick = () => {
                    if (MCPEditor.switchProfile) {
                        MCPEditor.switchProfile(name);
                    }
                };
                tabWrapper.appendChild(btn);

                // Show base MCP server info below the button
                const details = profileDetails[name] || {};
                if (details.base_mcp) {
                    const baseMcpLabel = document.createElement('span');
                    baseMcpLabel.style = 'font-size: 10px; color: var(--text-secondary); margin-top: 2px;';
                    baseMcpLabel.textContent = details.base_mcp;
                    tabWrapper.appendChild(baseMcpLabel);
                }

                // Add delete button for non-protected profiles
                if (!isProtectedProfile(name)) {
                    const deleteBtn = document.createElement('button');
                    deleteBtn.className = 'btn btn-icon';
                    deleteBtn.style = 'position: absolute; top: -8px; right: -8px; width: 20px; height: 20px; border-radius: 50%; background: #ff3b30; color: white; font-size: 12px; padding: 0; line-height: 20px; text-align: center; border: 2px solid white; cursor: pointer; display: none;';
                    deleteBtn.textContent = '×';
                    deleteBtn.title = `Delete profile: ${name}`;
                    deleteBtn.onclick = (e) => {
                        e.stopPropagation();
                        deleteProfile(name);
                    };

                    // Show delete button on hover
                    tabWrapper.onmouseenter = () => { deleteBtn.style.display = 'block'; };
                    tabWrapper.onmouseleave = () => { deleteBtn.style.display = 'none'; };

                    tabWrapper.appendChild(deleteBtn);
                }

                tabContainer.appendChild(tabWrapper);
            });
        }
    }

    // ============================================================================
    // GENERATOR OPTIONS
    // ============================================================================

    /**
     * Renders the server generator options dropdown
     */
    function renderGeneratorOptions() {
        const select = document.getElementById('generatorModule');
        if (!select) return;

        const generatorModules = MCPEditor.state.generatorModules || [];
        const currentProfile = MCPEditor.state.currentProfile;

        select.innerHTML = '<option value="">Custom / Current Profile</option>';
        generatorModules.forEach(mod => {
            const opt = document.createElement('option');
            opt.value = mod.name;
            opt.textContent = mod.name;
            select.appendChild(opt);
        });

        // Prefer module matching current profile, fallback to first module
        let defaultValue = '';
        if (currentProfile) {
            // Try to find a module matching the active profile name
            const matchingModule = generatorModules.find(mod =>
                mod.name.toLowerCase() === currentProfile.toLowerCase() ||
                mod.name.toLowerCase().includes(currentProfile.toLowerCase()) ||
                currentProfile.toLowerCase().includes(mod.name.toLowerCase())
            );
            if (matchingModule) {
                defaultValue = matchingModule.name;
            }
        }
        // Fallback to first module if no profile match
        if (!defaultValue && generatorModules.length > 0) {
            defaultValue = generatorModules[0].name;
        }

        select.value = defaultValue;
        if (MCPEditor.applyGeneratorDefaults) {
            MCPEditor.applyGeneratorDefaults(defaultValue);
        }
    }

    // ============================================================================
    // TOOL LIST RENDERING
    // ============================================================================

    /**
     * Renders the tool list in the sidebar
     * Shows all tools with their names, descriptions, and service info
     */
    function renderToolList() {
        console.log('[DEBUG] renderToolList() called');

        const tools = MCPEditor.state.tools || [];
        const currentToolIndex = MCPEditor.state.currentToolIndex;

        console.log('[DEBUG] tools.length:', tools.length);
        console.log('[DEBUG] currentToolIndex:', currentToolIndex);

        const toolList = document.getElementById('toolList');
        if (!toolList) {
            console.error('[ERROR] toolList element not found!');
            return;
        }
        console.log('[DEBUG] toolList element found');

        console.log('[DEBUG] Clearing toolList.innerHTML');
        toolList.innerHTML = '';

        console.log('[DEBUG] Starting forEach loop...');
        tools.forEach((tool, index) => {
            console.log(`[DEBUG] Processing tool ${index}: ${tool.name}`);
            const toolItem = document.createElement('div');
            toolItem.className = 'tool-item';
            toolItem.setAttribute('data-debug-id', `TOOL_${index}`);
            if (index === currentToolIndex) {
                toolItem.classList.add('active');
            }
            toolItem.onclick = () => {
                if (MCPEditor.selectTool) {
                    MCPEditor.selectTool(index);
                }
            };

            // Get service method info
            const serviceName = typeof tool.mcp_service === 'string'
                ? tool.mcp_service
                : tool.mcp_service?.name;
            const serviceMethodHtml = serviceName
                ? `<div style="margin-top: 5px; font-size: 11px; color: var(--primary-color); font-weight: 500;">
                    <span style="color: #666;">Service:</span> ${serviceName}
                   </div>`
                : '';

            toolItem.innerHTML = `
                <h3>${tool.name}</h3>
                <p>${tool.description}</p>
                ${serviceMethodHtml}
            `;
            toolList.appendChild(toolItem);
            console.log(`[DEBUG] Tool ${index} appended to DOM`);
        });
        console.log('[DEBUG] forEach loop completed, total tools:', tools.length);
    }

    // ============================================================================
    // NOTIFICATIONS AND TOASTS
    // ============================================================================

    /**
     * Shows a notification message
     * @param {string} message - The message to display
     * @param {string} type - Type of notification (success, error, warning, info)
     */
    function showNotification(message, type) {
        console.log('[DEBUG] showNotification() called');
        console.log('[DEBUG] message:', message);
        console.log('[DEBUG] type:', type);

        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        document.body.appendChild(notification);

        console.log('[DEBUG] Notification element created and appended');
        console.log('[DEBUG] notification.className:', notification.className);
        console.log('[DEBUG] notification.textContent:', notification.textContent);

        setTimeout(() => {
            notification.remove();
            console.log('[DEBUG] Notification removed after 3 seconds');
        }, 3000);
    }

    /**
     * Alias for showNotification (for compatibility)
     */
    function showToast(message, type) {
        showNotification(message, type);
    }

    // ============================================================================
    // FILE BROWSER MODAL
    // ============================================================================

    /**
     * Shows the file browser modal
     * @param {string} inputId - ID of the input field to populate with selected file
     * @param {string} extension - File extension filter (e.g., 'py', 'jinja2')
     */
    function showFileBrowser(inputId, extension) {
        // Remove existing modal if any
        const existing = document.getElementById('fileBrowserModal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'fileBrowserModal';
        modal.className = 'modal show';

        // Get initial path from the input field or use default
        const currentValue = document.getElementById(inputId)?.value || '';
        const initialPath = currentValue ?
            (currentValue.includes('/') ? currentValue.substring(0, currentValue.lastIndexOf('/')) : MCPEditor.config.basePath || '.') :
            getDefaultPath(inputId, '', extension).substring(0, getDefaultPath(inputId, '', extension).lastIndexOf('/'));

        modal.innerHTML = `
            <div class="modal-content" style="max-width: 700px;">
                <div class="modal-header">
                    <h3>Select File</h3>
                    <button class="btn btn-icon" onclick="MCPEditor.UI.closeFileBrowser()">✕</button>
                </div>
                <div class="modal-body">
                    <div style="margin-bottom: 12px;">
                        <input type="text" id="fileBrowserPath" class="form-control"
                               placeholder="${MCPEditor.config.basePath || '.'}/..."
                               value="${initialPath}"
                               onkeypress="if(event.key==='Enter') MCPEditor.UI.browsePath('${inputId}', '${extension}')">
                        <div style="display: flex; gap: 8px; margin-top: 8px;">
                            <button class="btn btn-secondary" onclick="MCPEditor.UI.browsePath('${inputId}', '${extension}')">
                                <span class="material-icons" style="font-size: 16px;">refresh</span> Browse
                            </button>
                            <button class="btn btn-secondary" id="parentDirBtn" onclick="MCPEditor.UI.browseParent('${inputId}', '${extension}')" style="display:none;">
                                <span class="material-icons" style="font-size: 16px;">arrow_upward</span> Parent
                            </button>
                        </div>
                    </div>
                    <div id="fileBrowserContent" style="border: 1px solid var(--border-color);
                                                        border-radius: 4px; padding: 8px;
                                                        max-height: 400px; overflow-y: auto;
                                                        background: var(--bg-primary);">
                        <div style="text-align: center; color: var(--text-secondary); padding: 20px;">
                            Click "Browse" to load directory contents
                        </div>
                    </div>
                    <div style="margin-top: 12px;">
                        <input type="text" id="selectedFilePath" class="form-control"
                               placeholder="Selected file path will appear here" readonly>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-primary" onclick="MCPEditor.UI.applySelectedFile('${inputId}')" id="applyFileBtn" disabled>Apply</button>
                    <button class="btn btn-secondary" onclick="MCPEditor.UI.closeFileBrowser()">Cancel</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        // Auto-browse initial path
        browsePath(inputId, extension);
    }

    /**
     * Browses a directory path in the file browser
     * @param {string} inputId - ID of the input field
     * @param {string} extension - File extension filter
     */
    async function browsePath(inputId, extension) {
        const pathInput = document.getElementById('fileBrowserPath');
        const contentDiv = document.getElementById('fileBrowserContent');
        const parentBtn = document.getElementById('parentDirBtn');

        if (!pathInput || !contentDiv) return;

        const path = pathInput.value || MCPEditor.config.basePath || '.';

        contentDiv.innerHTML = '<div style="text-align: center; padding: 20px;">Loading...</div>';

        try {
            const response = await fetch('/api/browse-files', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, extension })
            });

            const data = await response.json();

            if (data.error) {
                contentDiv.innerHTML = `<div style="color: red; padding: 20px;">${data.error}</div>`;
                return;
            }

            // Update path input with actual path
            pathInput.value = data.current_path;

            // Show/hide parent button
            if (parentBtn) {
                parentBtn.style.display = data.parent_path ? 'inline-flex' : 'none';
                parentBtn.setAttribute('data-parent-path', data.parent_path || '');
            }

            // Build content HTML
            let html = '';

            // Add directories
            if (data.dirs && data.dirs.length > 0) {
                html += '<div style="margin-bottom: 12px;"><strong>Directories:</strong></div>';
                data.dirs.forEach(dir => {
                    html += `
                        <div style="padding: 4px 8px; cursor: pointer; display: flex; align-items: center; gap: 8px;"
                             onmouseover="this.style.background='var(--hover-bg)'"
                             onmouseout="this.style.background='transparent'"
                             onclick="MCPEditor.UI.navigateToDir('${data.current_path}/${dir}', '${inputId}', '${extension}')">
                            <span class="material-icons" style="font-size: 16px; color: #ffc107;">folder</span>
                            <span>${dir}/</span>
                        </div>
                    `;
                });
            }

            // Add files
            if (data.files && data.files.length > 0) {
                if (html) html += '<hr style="margin: 12px 0; border-color: var(--border-color);">';
                html += '<div style="margin-bottom: 12px;"><strong>Files:</strong></div>';
                data.files.forEach(file => {
                    const filePath = `${data.current_path}/${file}`;
                    html += `
                        <div style="padding: 4px 8px; cursor: pointer; display: flex; align-items: center; gap: 8px;"
                             onmouseover="this.style.background='var(--hover-bg)'"
                             onmouseout="this.style.background='transparent'"
                             onclick="MCPEditor.UI.selectFile('${filePath}', '${inputId}')">
                            <span class="material-icons" style="font-size: 16px; color: #2196f3;">insert_drive_file</span>
                            <span>${file}</span>
                        </div>
                    `;
                });
            } else if (!data.dirs || data.dirs.length === 0) {
                html = '<div style="text-align: center; color: var(--text-secondary); padding: 20px;">No files or directories found</div>';
            }

            contentDiv.innerHTML = html;

        } catch (error) {
            console.error('Error browsing files:', error);
            contentDiv.innerHTML = '<div style="color: red; padding: 20px;">Error loading directory</div>';
        }
    }

    /**
     * Navigates to a directory in the file browser
     */
    function navigateToDir(path, inputId, extension) {
        document.getElementById('fileBrowserPath').value = path;
        browsePath(inputId, extension);
    }

    /**
     * Navigates to parent directory in the file browser
     */
    function browseParent(inputId, extension) {
        const parentBtn = document.getElementById('parentDirBtn');
        const parentPath = parentBtn?.getAttribute('data-parent-path');
        if (parentPath) {
            document.getElementById('fileBrowserPath').value = parentPath;
            browsePath(inputId, extension);
        }
    }

    /**
     * Selects a file in the file browser
     */
    function selectFile(filePath, inputId) {
        const selectedInput = document.getElementById('selectedFilePath');
        const applyBtn = document.getElementById('applyFileBtn');

        if (selectedInput) {
            selectedInput.value = filePath;
        }
        if (applyBtn) {
            applyBtn.disabled = false;
        }
    }

    /**
     * Applies the selected file to the input field
     */
    function applySelectedFile(inputId) {
        const selectedPath = document.getElementById('selectedFilePath')?.value;
        if (selectedPath) {
            document.getElementById(inputId).value = selectedPath;
        }
        closeFileBrowser();
    }

    /**
     * Closes the file browser modal
     */
    function closeFileBrowser() {
        const modal = document.getElementById('fileBrowserModal');
        if (modal) modal.remove();
    }

    /**
     * Gets the default path for a given input field
     * @param {string} inputId - ID of the input field
     * @param {string} fileName - File name (optional)
     * @param {string} extension - File extension
     * @returns {string} Default path
     */
    function getDefaultPath(inputId, fileName, extension) {
        const basePath = MCPEditor.config.basePath || '.';
        const serverName = MCPEditor.getCurrentServer ? MCPEditor.getCurrentServer() : '';

        if (inputId === 'generatorToolsPath') {
            // Default for tool definitions
            return `${basePath}/mcp_editor/mcp_${serverName}/tool_definition_templates.py`;
        } else if (inputId === 'generatorTemplatePath') {
            // Default for template - always use universal template
            return `${basePath}/jinja/universal_server_template.jinja2`;
        } else if (inputId === 'generatorOutputPath') {
            // Default for output
            return `${basePath}/mcp_${serverName}/mcp_server/server.py`;
        }

        return `${basePath}/${fileName}`;
    }

    // ============================================================================
    // MODAL HELPERS
    // ============================================================================

    /**
     * Closes a modal by ID
     * @param {string} modalId - ID of the modal to close
     */
    function closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            if (modalId === 'propertyModal') {
                modal.parentElement.remove();
            } else {
                modal.classList.remove('show');
            }
        }
    }

    /**
     * Opens the server generator modal
     */
    function openGeneratorModal() {
        const generatorModules = MCPEditor.state.generatorModules || [];
        const generatorFallback = MCPEditor.state.generatorFallback || {};

        if (!generatorModules.length && !generatorFallback.tools_path) {
            if (MCPEditor.loadGeneratorDefaults) {
                MCPEditor.loadGeneratorDefaults();
            }
        }

        const moduleName = document.getElementById('generatorModule')?.value || '';
        if (MCPEditor.applyGeneratorDefaults) {
            MCPEditor.applyGeneratorDefaults(moduleName);
        }

        const resultEl = document.getElementById('generatorResult');
        if (resultEl) resultEl.textContent = '';

        const modal = document.getElementById('generatorModal');
        if (modal) modal.classList.add('show');
    }

    /**
     * Shows the new project modal
     */
    function showNewProjectModal() {
        // Remove existing modal if any
        const existing = document.getElementById('newProjectModal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'newProjectModal';
        modal.style = `
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5); display: flex; align-items: center;
            justify-content: center; z-index: 1000;
        `;
        modal.innerHTML = `
            <div style="background: var(--card-bg); padding: 24px; border-radius: 12px; width: 500px; max-width: 90%;">
                <h3 style="margin-top: 0; margin-bottom: 16px;">New Project</h3>
                <div class="form-group" style="margin-bottom: 12px;">
                    <label>Project Name *</label>
                    <input type="text" id="newProjectName" class="form-control" placeholder="e.g., calendar, teams, sharepoint">
                    <small style="color: var(--text-secondary);">Will be used as profile name (lowercase, underscores)</small>
                </div>
                <div class="form-group" style="margin-bottom: 12px;">
                    <label>MCP Server Path</label>
                    <input type="text" id="newProjectMcpPath" class="form-control" placeholder="../mcp_{name}/mcp_server">
                    <small style="color: var(--text-secondary);">Path to MCP server directory (relative to mcp_editor)</small>
                </div>
                <div class="form-group" style="margin-bottom: 12px;">
                    <label>Port</label>
                    <input type="number" id="newProjectPort" class="form-control" value="8091">
                </div>
                <div class="form-group" style="margin-bottom: 16px;">
                    <label style="display: flex; align-items: center; gap: 8px;">
                        <input type="checkbox" id="newProjectCreateMcp" checked>
                        Create MCP server directory structure
                    </label>
                </div>
                <div style="display: flex; gap: 12px; justify-content: flex-end;">
                    <button class="btn btn-secondary" onclick="MCPEditor.UI.closeNewProjectModal()">Cancel</button>
                    <button class="btn btn-primary" onclick="MCPEditor.createNewProject()">Create Project</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.onclick = (e) => { if (e.target === modal) closeNewProjectModal(); };
        document.getElementById('newProjectName').focus();
    }

    /**
     * Closes the new project modal
     */
    function closeNewProjectModal() {
        const modal = document.getElementById('newProjectModal');
        if (modal) modal.remove();
    }

    // ============================================================================
    // COLLAPSIBLE SECTIONS
    // ============================================================================

    /**
     * Toggles a property collapse section
     * @param {string} propId - Property ID
     */
    function togglePropertyCollapse(propId) {
        const content = document.getElementById(`content-${propId}`);
        const icon = document.getElementById(`icon-${propId}`);
        const header = document.getElementById(`header-${propId}`);

        if (content.classList.contains('collapsed')) {
            content.classList.remove('collapsed');
            icon.classList.remove('collapsed');
            icon.textContent = '▼';
            header.classList.add('expanded');
        } else {
            content.classList.add('collapsed');
            icon.classList.add('collapsed');
            icon.textContent = '▶';
            header.classList.remove('expanded');
        }
    }

    /**
     * Expands all property sections
     */
    function expandAllProperties() {
        const allProperties = document.querySelectorAll('.property-collapse-content');
        const allIcons = document.querySelectorAll('.property-collapse-header .collapse-icon');
        const allHeaders = document.querySelectorAll('.property-collapse-header');

        allProperties.forEach(prop => prop.classList.remove('collapsed'));
        allIcons.forEach(icon => { icon.classList.remove('collapsed'); icon.textContent = '▼'; });
        allHeaders.forEach(header => header.classList.add('expanded'));
    }

    /**
     * Collapses all property sections
     */
    function collapseAllProperties() {
        const allProperties = document.querySelectorAll('.property-collapse-content');
        const allIcons = document.querySelectorAll('.property-collapse-header .collapse-icon');
        const allHeaders = document.querySelectorAll('.property-collapse-header');

        allProperties.forEach(prop => prop.classList.add('collapsed'));
        allIcons.forEach(icon => { icon.classList.add('collapsed'); icon.textContent = '▶'; });
        allHeaders.forEach(header => header.classList.remove('expanded'));
    }

    // ============================================================================
    // GRAPH TYPE OPTIONS
    // ============================================================================

    /**
     * Populates graph type options in a select element
     * @param {HTMLSelectElement} selectEl - The select element to populate
     */
    function populateGraphTypeOptions(selectEl) {
        if (!selectEl || !window.graphTypesProperties || !Array.isArray(window.graphTypesProperties.classes)) {
            return;
        }
        const existing = Array.from(selectEl.options).map(opt => opt.value);
        window.graphTypesProperties.classes.forEach(cls => {
            const name = cls.name || '';
            if (!name || existing.includes(name)) {
                return;
            }
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            selectEl.appendChild(option);
        });
    }

    // ============================================================================
    // EXPORT PUBLIC API
    // ============================================================================

    // Create global MCPEditor namespace if it doesn't exist
    window.MCPEditor = window.MCPEditor || {};

    // Export UI functions
    window.MCPEditor.UI = {
        // Template and source selector
        renderTemplateSourceSelector,

        // Server status
        updateServerStatusUI,

        // Profile management
        renderProfileTabs,

        // Generator
        renderGeneratorOptions,
        openGeneratorModal,

        // Tool list
        renderToolList,
        renderTools: renderToolList,  // 별칭 추가 (호환성)

        // Notifications
        showNotification,
        showToast,

        // File browser
        showFileBrowser,
        browsePath,
        navigateToDir,
        browseParent,
        selectFile,
        applySelectedFile,
        closeFileBrowser,
        getDefaultPath,

        // Modals
        closeModal,
        showNewProjectModal,
        closeNewProjectModal,

        // Collapsible sections
        togglePropertyCollapse,
        expandAllProperties,
        collapseAllProperties,

        // Graph types
        populateGraphTypeOptions
    };

    console.log('[MCPEditor.UI] UI module loaded');

})();
