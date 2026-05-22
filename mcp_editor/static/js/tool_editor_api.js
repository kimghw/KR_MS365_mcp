/**
 * MCP Tool Editor - API Module
 * Handles all fetch/API calls and data operations
 *
 * This module contains all functions that interact with backend APIs.
 * All hardcoded values have been removed and replaced with dynamic references.
 */

// ===== Template Management API =====

/**
 * Load available template sources (current, backups, other profiles)
 */
async function loadTemplateSources() {
    const profileQuery = profileParam();
    try {
        const response = await fetch(`/api/template-sources${profileQuery}`);
        const data = await response.json();
        MCPEditor.state.templateSources = data.sources || [];

        if (window.MCPEditorUI && window.MCPEditorUI.renderTemplateSourceSelector) {
            window.MCPEditorUI.renderTemplateSourceSelector();
        }
    } catch (error) {
        console.error('Error loading template sources:', error);
        MCPEditor.state.templateSources = [];
        if (window.MCPEditorUI && window.MCPEditorUI.renderTemplateSourceSelector) {
            window.MCPEditorUI.renderTemplateSourceSelector();
        }
    }
}

/**
 * Load tools from selected template source
 */
async function loadFromSelectedTemplate() {
    const select = document.getElementById('templateSource');
    const statusEl = document.getElementById('templateLoadStatus');
    const sourcePath = select ? select.value : '';

    if (!sourcePath) {
        // Load from current template (default behavior)
        await MCPEditor.loadTools();
        return;
    }

    if (statusEl) {
        statusEl.textContent = 'Loading...';
        statusEl.style.color = '#666';
    }

    try {
        const response = await fetch('/api/template-sources/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: sourcePath })
        });

        const data = await response.json();

        if (data.success) {
            MCPEditor.state.tools = data.tools;
            MCPEditor.state.currentToolIndex = -1;

            if (window.MCPEditorUI && window.MCPEditorUI.renderToolList) {
                window.MCPEditorUI.renderToolList();
            }

            if (statusEl) {
                statusEl.textContent = `✓ Loaded ${data.count} tools`;
                statusEl.style.color = '#34c759';
                setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
            }

            MCPEditor.showNotification(
                `Loaded ${data.count} tools from template. Save will update "${MCPEditor.state.originalProfile || 'default'}"`,
                'success'
            );

            // Clear editor
            const editorContent = document.getElementById('editorContent');
            if (editorContent) {
                editorContent.innerHTML = `
                    <div style="text-align: center; padding: 50px; color: var(--text-secondary);">
                        <p>Loaded ${data.count} tools from: ${sourcePath.split('/').pop()}</p>
                        <p style="font-size: 12px; margin-top: 10px;">Select a tool from the left sidebar to edit</p>
                    </div>
                `;
            }
        } else {
            if (statusEl) {
                statusEl.textContent = '✗ Failed';
                statusEl.style.color = '#ff3b30';
            }
            MCPEditor.showNotification(`Error: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error loading template:', error);
        if (statusEl) {
            statusEl.textContent = '✗ Failed';
            statusEl.style.color = '#ff3b30';
        }
        MCPEditor.showNotification('Failed to load template', 'error');
    }
}

// ===== MCP Services API =====

/**
 * Load MCP services for current profile
 */
async function loadMcpServices() {
    const profileQuery = MCPEditor.state.originalProfile
        ? `?profile=${encodeURIComponent(MCPEditor.state.originalProfile)}`
        : '';

    try {
        const response = await fetch(`/api/mcp-services${profileQuery}`);
        const data = await response.json();

        console.log('Raw MCP services API response:', data);

        window.mcpServiceDetails = data.services_with_signatures || [];

        // Use service names from services_with_signatures
        if (window.mcpServiceDetails.length > 0) {
            window.mcpServices = window.mcpServiceDetails.map(svc => svc.name).filter(Boolean);
        } else {
            window.mcpServices = data.services || [];
        }

        console.log('MCP Services loaded:', window.mcpServices, 'from profile:', MCPEditor.state.originalProfile || 'default');
        console.log('MCP Service details loaded:', window.mcpServiceDetails);

        if (window.mcpServiceDetails.length > 0) {
            console.log('First service detail example:', window.mcpServiceDetails[0]);
        }

        if (MCPEditor.state.currentToolIndex >= 0 && window.renderToolEditor) {
            renderToolEditor(MCPEditor.state.tools[MCPEditor.state.currentToolIndex], MCPEditor.state.currentToolIndex);
        }
    } catch (error) {
        console.error('Error loading MCP services:', error);
        window.mcpServices = [];
        window.mcpServiceDetails = [];
    }
}

/**
 * Load graph types properties for current profile
 */
async function loadGraphTypesProperties() {
    const profileQuery = MCPEditor.state.originalProfile
        ? `?profile=${encodeURIComponent(MCPEditor.state.originalProfile)}`
        : '';

    try {
        const response = await fetch(`/api/graph-types-properties${profileQuery}`);
        const data = await response.json();

        window.graphTypesProperties = data;
        window.hasTypesFile = data.has_types || false;
        window.typesName = data.types_name || 'types';

        console.log('Loaded graph types properties:', data, 'hasTypes:', window.hasTypesFile, 'typesName:', window.typesName);
        return data;
    } catch (error) {
        console.error('Error loading graph types properties:', error);
        window.graphTypesProperties = null;
        window.hasTypesFile = false;
        window.typesName = 'types';
        return null;
    }
}

// ===== Generator API =====

/**
 * Load generator defaults for current profile
 */
async function loadGeneratorDefaults() {
    const profileQuery = profileParam();

    try {
        const response = await fetch(`/api/server-generator/defaults${profileQuery}`);
        const data = await response.json();

        MCPEditor.state.generatorModules = data.modules || [];
        MCPEditor.state.generatorFallback = data.fallback || {};

        if (window.MCPEditorUI && window.MCPEditorUI.renderGeneratorOptions) {
            window.MCPEditorUI.renderGeneratorOptions();
        }
    } catch (error) {
        console.error('Error loading generator defaults:', error);
        MCPEditor.state.generatorModules = [];
        MCPEditor.state.generatorFallback = {};
    }
}

/**
 * Run server generation
 */
async function runServerGeneration() {
    const profileQuery = profileParam();
    const payload = {
        module: document.getElementById('generatorModule')?.value || null,
        tools_path: document.getElementById('generatorToolsPath')?.value || '',
        template_path: document.getElementById('generatorTemplatePath')?.value || '',
        output_path: document.getElementById('generatorOutputPath')?.value || ''
    };

    try {
        const response = await fetch(`/api/server-generator${profileQuery}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        const resultEl = document.getElementById('generatorResult');

        if (response.status >= 200 && response.status < 300 && data.success) {
            MCPEditor.showNotification(`Generated server at ${data.output_path}`, 'success');
            if (resultEl) resultEl.textContent = `Output: ${data.output_path} (${data.tool_count} tools)`;
        } else {
            const message = data.error || 'Failed to generate server';
            MCPEditor.showNotification(message, 'error');
            if (resultEl) resultEl.textContent = message;
        }
    } catch (error) {
        console.error('Error generating server:', error);
        MCPEditor.showNotification('Failed to generate server', 'error');
    }
}

// ===== File Browser API =====

/**
 * Browse files in a directory
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

        // Update path input
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
                         onclick="navigateToDir('${data.current_path}/${dir}', '${inputId}', '${extension}')">
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
                         onclick="selectFile('${filePath}', '${inputId}')">
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

// ===== Project Creation API =====

/**
 * Create new MCP project
 */
async function createNewProject() {
    const name = document.getElementById('newProjectName')?.value.trim();
    if (!name) {
        MCPEditor.showNotification('Project name is required', 'error');
        return;
    }

    const mcpPath = document.getElementById('newProjectMcpPath')?.value.trim()
        || `../mcp_${name.toLowerCase().replace(/\s+/g, '_')}/mcp_server`;
    const port = parseInt(document.getElementById('newProjectPort')?.value) || 8091;
    const createMcp = document.getElementById('newProjectCreateMcp')?.checked;

    try {
        const response = await fetch('/api/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                mcp_server_path: mcpPath,
                port: port,
                create_mcp_structure: createMcp
            })
        });

        const result = await response.json();
        if (result.error) {
            MCPEditor.showNotification(result.error, 'error');
            return;
        }

        MCPEditor.showNotification(`Project "${result.profile}" created successfully!`, 'success');
        if (window.closeNewProjectModal) closeNewProjectModal();

        // Reload profiles and switch to new one
        MCPEditor.state.profiles.push(result.profile);
        MCPEditor.state.currentProfile = result.profile;

        if (window.MCPEditorUI) {
            if (window.MCPEditorUI.renderProfileTabs) window.MCPEditorUI.renderProfileTabs();
        }

        await MCPEditor.loadTools();
        await loadGeneratorDefaults();
    } catch (error) {
        MCPEditor.showNotification('Failed to create project: ' + error.message, 'error');
    }
}

// ===== Tool Management API =====

/**
 * Save a single tool
 * @param {number} index - Tool index to save
 */
async function saveTool(index) {
    const profileQuery = profileParam();
    const tool = MCPEditor.state.tools[index];

    try {
        const response = await fetch(`/api/tools/${index}${profileQuery}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(tool)
        });

        const data = await response.json();

        if (data.success) {
            MCPEditor.showNotification(`Tool "${tool.name}" saved successfully!`, 'success');
            return true;
        } else {
            MCPEditor.showNotification(`Error saving tool: ${data.error}`, 'error');
            return false;
        }
    } catch (error) {
        console.error('Error saving tool:', error);
        MCPEditor.showNotification('Failed to save tool', 'error');
        return false;
    }
}

/**
 * Delete a tool
 * @param {number} index - Tool index to delete
 */
async function deleteTool(index) {
    if (!confirm(`Delete tool "${MCPEditor.state.tools[index].name}"?`)) {
        return;
    }

    const profileQuery = profileParam();

    try {
        const response = await fetch(`/api/tools/${index}${profileQuery}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            MCPEditor.showNotification(
                data.message + (data.backup ? ` (Backup: ${data.backup})` : ''),
                'success'
            );
            MCPEditor.state.tools.splice(index, 1);
            MCPEditor.state.currentToolIndex = -1;

            if (window.MCPEditorUI && window.MCPEditorUI.renderToolList) {
                window.MCPEditorUI.renderToolList();
            }

            const editorContent = document.getElementById('editorContent');
            if (editorContent) {
                editorContent.innerHTML = `
                    <div style="text-align: center; padding: 50px; color: var(--text-secondary);">
                        Select a tool from the left sidebar to edit
                    </div>
                `;
            }
        } else {
            MCPEditor.showNotification(`Error deleting tool: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error deleting tool:', error);
        MCPEditor.showNotification('Failed to delete tool', 'error');
    }
}

/**
 * Save all tools
 */
async function saveTools() {
    console.log('[DEBUG] saveTools() called');

    const profileQuery = profileParam();
    const saveProfile = MCPEditor.state.originalProfile || 'default';
    const saveButton = document.querySelector('[data-debug-id="BTN_SAVE"]');
    const saveLabel = saveButton ? saveButton.innerHTML : '';

    // Use the save-all API to atomically save tools + internal_args
    const url = `/api/tools/save-all${profileQuery}`;
    const payload = {
        tools: MCPEditor.state.tools,
        internal_args: MCPEditor.state.internalArgs,
        file_mtimes: MCPEditor.state.fileMtimes
    };

    console.log('[DEBUG] Request URL:', url);
    console.log('[DEBUG] saveProfile:', saveProfile);

    let payloadJson = '';
    try {
        payloadJson = JSON.stringify(payload);
    } catch (error) {
        console.error('Error serializing save payload:', error);
        MCPEditor.showNotification(`Failed to serialize tools: ${error.message}`, 'error');
        return;
    }

    if (saveButton) {
        saveButton.disabled = true;
        saveButton.innerHTML = '<span class="material-icons">save</span> Saving...';
    }

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payloadJson
        });

        console.log('[DEBUG] Response status:', response.status);

        if (response.status === 409) {
            // Conflict detected
            const data = await response.json();
            console.log('[DEBUG] Conflict data:', data);
            MCPEditor.showNotification(`${data.message}. Please reload and try again.`, 'error');
            throw new Error('Conflict');
        }

        const data = await response.json();
        console.log('[DEBUG] Response data:', data);

        if (data.success) {
            const savedInfo = Array.isArray(data.saved) ? data.saved.join(', ') : 'files';
            MCPEditor.showNotification(`Saved: ${savedInfo} to "${saveProfile}"!`, 'success');
            // Reload to get fresh mtimes
            await MCPEditor.loadTools();
        } else {
            MCPEditor.showNotification(`Error saving: ${data.error || 'Unknown error'}`, 'error');
        }
    } catch (error) {
        console.error('[DEBUG] Error:', error);
        if (error.message !== 'Conflict') {
            MCPEditor.showNotification('Failed to save', 'error');
        }
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.innerHTML = saveLabel || '<span class="material-icons">save</span>';
        }
    }
}

/**
 * Validate tools
 */
async function validateTools() {
    const profileQuery = profileParam();

    try {
        const response = await fetch(`/api/tools/validate${profileQuery}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(MCPEditor.state.tools)
        });

        const data = await response.json();

        if (data.valid) {
            MCPEditor.showNotification('Tools are valid!', 'success');
        } else {
            MCPEditor.showNotification(`Validation error: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error validating tools:', error);
        MCPEditor.showNotification('Failed to validate tools', 'error');
    }
}

// ===== Backup Management API =====

/**
 * Show backups
 */
async function showBackups() {
    const profileQuery = profileParam();

    try {
        const response = await fetch(`/api/backups${profileQuery}`);
        const data = await response.json();

        const backupList = document.getElementById('backupList');
        if (!backupList) return;

        if (data.length === 0) {
            backupList.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No backups available</p>';
        } else {
            backupList.innerHTML = data.map(backup => `
                <div class="backup-item">
                    <div class="backup-info">
                        <div class="backup-name">${backup.filename}</div>
                        <div class="backup-date">${new Date(backup.modified).toLocaleString()}</div>
                    </div>
                    <div>
                        <button class="btn btn-secondary btn-sm" onclick="viewBackup('${backup.filename}')">View</button>
                        <button class="btn btn-primary btn-sm" onclick="restoreBackup('${backup.filename}')">Restore</button>
                    </div>
                </div>
            `).join('');
        }

        const modal = document.getElementById('backupModal');
        if (modal) modal.classList.add('show');
    } catch (error) {
        console.error('Error loading backups:', error);
        MCPEditor.showNotification('Failed to load backups', 'error');
    }
}

/**
 * View a backup
 */
async function viewBackup(filename) {
    const profileQuery = profileParam();

    try {
        const response = await fetch(`/api/backups/${filename}${profileQuery}`);
        const data = await response.json();
        alert(JSON.stringify(data, null, 2));
    } catch (error) {
        console.error('Error viewing backup:', error);
        MCPEditor.showNotification('Failed to view backup', 'error');
    }
}

/**
 * Restore a backup
 */
async function restoreBackup(filename) {
    if (!confirm(`Restore backup from ${filename}? Current state will be backed up first.`)) {
        return;
    }

    const profileQuery = profileParam();

    try {
        const response = await fetch(`/api/backups/${filename}/restore${profileQuery}`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.success) {
            MCPEditor.showNotification(
                `Backup restored successfully! Current state backed up as: ${data.current_backup}`,
                'success'
            );
            if (window.closeModal) closeModal('backupModal');
            await MCPEditor.loadTools();
        } else {
            MCPEditor.showNotification(`Error restoring backup: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error restoring backup:', error);
        MCPEditor.showNotification('Failed to restore backup', 'error');
    }
}

// ===== Utility Functions =====

/**
 * Get profile query parameter
 */
function profileParam() {
    // Always use originalProfile for saving operations
    const profileName = MCPEditor.state.originalProfile || MCPEditor.state.currentProfile;
    return profileName ? `?profile=${encodeURIComponent(profileName)}` : '';
}
