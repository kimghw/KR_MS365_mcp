/* Tool Editor Tools - Loading, Saving, Profiles, Templates, Backups, Generator */

// Load tools on page load
window.onload = function() {
    console.log('[DEBUG] window.onload triggered');
    console.log('[DEBUG] Calling loadProfiles()...');
    loadProfiles();  // This will call loadGraphTypesProperties() after profile is loaded
    initDebugIndexing();
    console.log('[DEBUG] Calling checkServerStatus()...');
    checkServerStatus();
    // Auto-refresh server status every 5 seconds
    setInterval(checkServerStatus, 5000);
    console.log('[DEBUG] window.onload completed');
};

function loadTemplateSources() {
    // Load available template files (current, backups, other profiles)
    const profileQuery = profileParam();
    fetch(`/api/template-sources${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            templateSources = data.sources || [];
            renderTemplateSourceSelector();
        })
        .catch(error => {
            console.error('Error loading template sources:', error);
            templateSources = [];
            renderTemplateSourceSelector();
        });
}

function renderTemplateSourceSelector() {
    const select = document.getElementById('templateSource');
    if (!select) return;

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
        saveLabel.textContent = originalProfile || 'default';
    }
}

function loadFromSelectedTemplate() {
    const select = document.getElementById('templateSource');
    const statusEl = document.getElementById('templateLoadStatus');
    const sourcePath = select ? select.value : '';

    if (!sourcePath) {
        // Load from current template (default behavior)
        loadTools();
        return;
    }

    if (statusEl) {
        statusEl.textContent = 'Loading...';
        statusEl.style.color = '#666';
    }

    fetch('/api/template-sources/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: sourcePath })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            tools = data.tools;
            currentToolIndex = -1;
            renderToolList();

            if (statusEl) {
                statusEl.textContent = `✓ Loaded ${data.count} tools`;
                statusEl.style.color = '#34c759';
                setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000);
            }

            showNotification(`Loaded ${data.count} tools from template. Save will update "${originalProfile || 'default'}"`, 'success');

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
            showNotification(`Error: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error loading template:', error);
        if (statusEl) {
            statusEl.textContent = '✗ Failed';
            statusEl.style.color = '#ff3b30';
        }
        showNotification('Failed to load template', 'error');
    });
}

function loadMcpServices() {
    // Load MCP services for current profile
    const profileQuery = originalProfile ? `?profile=${encodeURIComponent(originalProfile)}` : '';

    fetch(`/api/mcp-services${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            window.mcpServiceDetails = data.services_with_signatures || [];
            // Use service names from services_with_signatures (these match mcp_service.name)
            // Fall back to data.services if services_with_signatures is empty
            if (window.mcpServiceDetails.length > 0) {
                window.mcpServices = window.mcpServiceDetails.map(svc => svc.name).filter(Boolean);
            } else {
                window.mcpServices = data.services || [];
            }
            // Store grouping info for merged profiles
            window.mcpServiceGroups = data.groups || {};
            window.mcpServiceIsMerged = data.is_merged || false;
            window.mcpServiceSourceProfiles = data.source_profiles || [];

            console.log('MCP Services loaded:', window.mcpServices, 'from profile:', originalProfile || 'default');
            console.log('MCP Service details loaded:', window.mcpServiceDetails);
            console.log('MCP Service groups:', window.mcpServiceGroups, 'is_merged:', window.mcpServiceIsMerged);

            if (currentToolIndex >= 0) {
                renderToolEditor(tools[currentToolIndex], currentToolIndex);
            }
        })
        .catch(error => {
            console.error('Error loading MCP services:', error);
            window.mcpServices = [];
            window.mcpServiceDetails = [];
            window.mcpServiceGroups = {};
            window.mcpServiceIsMerged = false;
            window.mcpServiceSourceProfiles = [];
        });
}

function loadTools() {
    console.log('[DEBUG] loadTools() called');
    const profileQuery = profileParam();
    fetch(`/api/tools${profileQuery}`)
        .then(response => {
            console.log('[DEBUG] Response received:', response.status, response.ok);
            return response.json();
        })
        .then(data => {
            console.log('[DEBUG] Data received:', data);
            const loadedTools = data.tools || data;
            tools = loadedTools;
            // Load internal args, signature defaults, and file mtimes from new API response format
            internalArgs = data.internal_args || {};
            signatureDefaults = data.signature_defaults || {};
            fileMtimes = data.file_mtimes || {};
            console.log('[DEBUG] tools variable set, tools.length:', tools.length);
            console.log('[DEBUG] internalArgs loaded:', Object.keys(internalArgs).length, 'tools');
            console.log('[DEBUG] signatureDefaults loaded:', Object.keys(signatureDefaults).length, 'tools');
            console.log('[DEBUG] Calling renderToolList()...');
            renderToolList();
            console.log('[DEBUG] renderToolList() completed');
            showNotification(`Tools loaded (${currentProfile || 'default'})`, 'success');
        })
        .catch(error => {
            console.error('[ERROR] Error loading tools:', error);
            showNotification('Failed to load tools', 'error');
        });
}

// Load graph types properties for current profile
function loadGraphTypesProperties() {
    const profileQuery = originalProfile ? `?profile=${encodeURIComponent(originalProfile)}` : '';
    return fetch(`/api/graph-types-properties${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            window.graphTypesProperties = data;
            window.hasTypesFile = data.has_types || false;
            window.typesName = data.types_name || 'types';
            console.log('Loaded graph types properties:', data, 'hasTypes:', window.hasTypesFile, 'typesName:', window.typesName);
            return data;
        })
        .catch(error => {
            console.error('Error loading graph types properties:', error);
            window.graphTypesProperties = null;
            window.hasTypesFile = false;
            window.typesName = 'types';
            return null;
        });
}

function loadProfiles() {
    fetch('/api/profiles')
        .then(response => response.json())
        .then(data => {
            profiles = data.profiles || [];
            currentProfile = data.active || (profiles[0] || '');
            window.currentProfile = currentProfile;  // Also update window scope
            originalProfile = currentProfile;  // Store original profile for saving
            serverControlProfile = currentProfile;  // Initialize server control profile
            renderProfileTabs();
            populateServerProfileSelector();  // Populate server profile dropdown
            loadTools();
            loadGeneratorDefaults();
            loadTemplateSources();  // Load available template sources
            loadMcpServices();  // Load MCP services for current profile
            loadGraphTypesProperties();  // Load graph types for current profile
        })
        .catch(error => {
            console.error('Error loading profiles:', error);
            profiles = [];
            currentProfile = '';
            window.currentProfile = '';  // Also update window scope
            originalProfile = '';
            serverControlProfile = '';
            renderProfileTabs();
            populateServerProfileSelector();
            loadTools();
            loadGeneratorDefaults();
            loadTemplateSources();
            loadMcpServices();
            loadGraphTypesProperties();
        });
}

function loadGeneratorDefaults() {
    const profileQuery = profileParam();
    fetch(`/api/server-generator/defaults${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            generatorModules = data.modules || [];
            generatorFallback = data.fallback || {};
            renderGeneratorOptions();
        })
        .catch(error => {
            console.error('Error loading generator defaults:', error);
            generatorModules = [];
            generatorFallback = {};
        });
}

function renderGeneratorOptions() {
    const select = document.getElementById('generatorModule');
    if (!select) return;

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
    applyGeneratorDefaults(defaultValue);
}

function applyGeneratorDefaults(moduleName) {
    const defaults = generatorModules.find(m => m.name === moduleName) || generatorFallback || {};
    const toolsInput = document.getElementById('generatorToolsPath');
    const templateInput = document.getElementById('generatorTemplatePath');
    const outputInput = document.getElementById('generatorOutputPath');

    if (toolsInput) toolsInput.value = defaults.tools_path || '';
    // Always use the universal template as default
    if (templateInput) templateInput.value = defaults.template_path || '/home/kimghw/Connector_auth/jinja/universal_server_template.jinja2';
    if (outputInput) outputInput.value = defaults.output_path || '';
}

function handleGeneratorModuleChange() {
    const select = document.getElementById('generatorModule');
    const moduleName = select ? select.value : '';
    applyGeneratorDefaults(moduleName);
}

// File selector function
function selectFilePath(inputId, extension) {
    showFileBrowser(inputId, extension);
}

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
        (currentValue.includes('/') ? currentValue.substring(0, currentValue.lastIndexOf('/')) : '/home/kimghw/Connector_auth') :
        getDefaultPath(inputId, '', extension).substring(0, getDefaultPath(inputId, '', extension).lastIndexOf('/'));

    modal.innerHTML = `
        <div class="modal-content" style="max-width: 700px;">
            <div class="modal-header">
                <h3>Select File</h3>
                <button class="btn btn-icon" onclick="closeFileBrowser()">✕</button>
            </div>
            <div class="modal-body">
                <div style="margin-bottom: 12px;">
                    <input type="text" id="fileBrowserPath" class="form-control"
                           placeholder="/home/kimghw/Connector_auth/..."
                           value="${initialPath}"
                           onkeypress="if(event.key==='Enter') browsePath('${inputId}', '${extension}')">
                    <div style="display: flex; gap: 8px; margin-top: 8px;">
                        <button class="btn btn-secondary" onclick="browsePath('${inputId}', '${extension}')">
                            <span class="material-icons" style="font-size: 16px;">refresh</span> Browse
                        </button>
                        <button class="btn btn-secondary" id="parentDirBtn" onclick="browseParent('${inputId}', '${extension}')" style="display:none;">
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
                <button class="btn btn-primary" onclick="applySelectedFile('${inputId}')" id="applyFileBtn" disabled>Apply</button>
                <button class="btn btn-secondary" onclick="closeFileBrowser()">Cancel</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // Auto-browse initial path
    browsePath(inputId, extension);
}

async function browsePath(inputId, extension) {
    const pathInput = document.getElementById('fileBrowserPath');
    const contentDiv = document.getElementById('fileBrowserContent');
    const parentBtn = document.getElementById('parentDirBtn');

    if (!pathInput || !contentDiv) return;

    const path = pathInput.value || '/home/kimghw/Connector_auth';

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

function navigateToDir(path, inputId, extension) {
    document.getElementById('fileBrowserPath').value = path;
    browsePath(inputId, extension);
}

function browseParent(inputId, extension) {
    const parentBtn = document.getElementById('parentDirBtn');
    const parentPath = parentBtn?.getAttribute('data-parent-path');
    if (parentPath) {
        document.getElementById('fileBrowserPath').value = parentPath;
        browsePath(inputId, extension);
    }
}

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

function applySelectedFile(inputId) {
    const selectedPath = document.getElementById('selectedFilePath')?.value;
    if (selectedPath) {
        document.getElementById(inputId).value = selectedPath;
    }
    closeFileBrowser();
}

function closeFileBrowser() {
    const modal = document.getElementById('fileBrowserModal');
    if (modal) modal.remove();
}

function getDefaultPath(inputId, fileName, extension) {
    // Provide smart defaults based on the input field
    const basePath = '/home/kimghw/Connector_auth';

    if (inputId === 'generatorToolsPath') {
        // Default for tool definitions
        const serverName = currentProfile || 'outlook';
        return `${basePath}/mcp_editor/mcp_${serverName}/tool_definition_templates.py`;
    } else if (inputId === 'generatorTemplatePath') {
        // Default for template - always use universal template
        return `${basePath}/jinja/universal_server_template.jinja2`;
    } else if (inputId === 'generatorOutputPath') {
        // Default for output
        const serverName = currentProfile || 'outlook';
        return `${basePath}/mcp_${serverName}/mcp_server/server.py`;
    }

    return `${basePath}/${fileName}`;
}

function openCreateProjectModal() {
    // Clear form
    document.getElementById('projectServiceName').value = '';
    document.getElementById('projectDescription').value = '';
    document.getElementById('projectPort').value = '8080';
    document.getElementById('projectAuthor').value = '';
    document.getElementById('projectIncludeTypes').checked = true;

    // Hide result
    const resultEl = document.getElementById('createProjectResult');
    resultEl.style.display = 'none';
    resultEl.textContent = '';

    document.getElementById('createProjectModal').classList.add('show');
}

function toggleReuseOptions() {
    const projectType = document.querySelector('input[name="projectType"]:checked').value;
    const newProjectOptions = document.getElementById('newProjectOptions');
    const reuseOptions = document.getElementById('reuseOptions');

    if (projectType === 'reuse') {
        newProjectOptions.style.display = 'none';
        reuseOptions.style.display = 'block';
        // Load available services
        loadAvailableServices();
    } else {
        newProjectOptions.style.display = 'block';
        reuseOptions.style.display = 'none';
    }
}

async function loadAvailableServices() {
    try {
        const response = await fetch('/api/available-services');
        const data = await response.json();

        const selectEl = document.getElementById('projectReuseService');
        selectEl.innerHTML = '<option value="">-- Select a service to reuse --</option>';

        if (data.services && data.services.length > 0) {
            data.services.forEach(service => {
                const option = document.createElement('option');
                option.value = service.name;
                option.textContent = `${service.display_name} (${service.source_dir})`;
                selectEl.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Failed to load available services:', error);
    }
}

function createNewProject() {
    const projectType = document.querySelector('input[name="projectType"]:checked').value;
    const port = parseInt(document.getElementById('projectPort').value) || 8080;

    const resultEl = document.getElementById('createProjectResult');
    resultEl.style.display = 'block';
    resultEl.style.backgroundColor = '#e3f2fd';
    resultEl.textContent = 'Creating project...';

    if (projectType === 'new') {
        // Original new project creation logic
        const serviceName = document.getElementById('projectServiceName').value.trim();
        const description = document.getElementById('projectDescription').value.trim();
        const author = document.getElementById('projectAuthor').value.trim();
        const includeTypes = document.getElementById('projectIncludeTypes').checked;

        if (!serviceName) {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'Service name is required';
            return;
        }

        if (!/^[a-zA-Z0-9_]+$/.test(serviceName)) {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'Service name can only contain letters, numbers, and underscores';
            return;
        }

        fetch('/api/create-mcp-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                service_name: serviceName,
                description: description,
                port: port,
                author: author,
                include_types: includeTypes
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                resultEl.style.backgroundColor = '#e8f5e9';
                resultEl.innerHTML = `
                    <strong>Success!</strong><br>
                    Created project: ${data.project_dir}<br>
                    Files created: ${data.created_files}<br><br>
                    <strong>Next steps:</strong><br>
                    1. Reload this page to see the new profile<br>
                    2. Select "${data.service_name}" from the profile tabs<br>
                    3. Start adding tools via the web editor
                `;
                setTimeout(() => { location.reload(); }, 3000);
            } else {
                resultEl.style.backgroundColor = '#ffebee';
                resultEl.textContent = 'Error: ' + (data.error || 'Unknown error occurred');
            }
        })
        .catch(error => {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'Error: ' + error.message;
        });

    } else if (projectType === 'reuse') {
        // Reuse existing service logic
        const existingService = document.getElementById('projectReuseService').value;
        const newProfileName = document.getElementById('projectNewProfileName').value.trim().toLowerCase();

        if (!existingService) {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'Please select an existing service to reuse';
            return;
        }

        if (!newProfileName) {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'New profile name is required';
            return;
        }

        if (!/^[a-zA-Z0-9_]+$/.test(newProfileName)) {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'Profile name can only contain letters, numbers, and underscores';
            return;
        }

        fetch('/api/create-mcp-project-reuse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                existing_service: existingService,
                new_profile_name: newProfileName,
                port: port
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                resultEl.style.backgroundColor = '#e8f5e9';
                resultEl.innerHTML = `
                    <strong>Success!</strong><br>
                    Created reused profile: ${data.profile_name}<br>
                    Editor directory: ${data.editor_dir}<br><br>
                    <strong>Next steps:</strong><br>
                    1. Reload this page to see the new profile<br>
                    2. Select "${data.profile_name}" from the profile tabs<br>
                    3. Edit tools (delete unwanted tools)<br>
                    4. Click "Generate Server" to create server files
                `;
                setTimeout(() => { location.reload(); }, 3000);
            } else {
                resultEl.style.backgroundColor = '#ffebee';
                resultEl.textContent = 'Error: ' + (data.error || 'Unknown error occurred');
            }
        })
        .catch(error => {
            resultEl.style.backgroundColor = '#ffebee';
            resultEl.textContent = 'Error: ' + error.message;
        });
    }
}

function openHelpModal() {
    document.getElementById('helpModal').classList.add('show');
}

function switchHelpTab(tabName) {
    // Hide all tab contents
    document.querySelectorAll('.help-tab-content').forEach(tab => {
        tab.style.display = 'none';
    });

    // Remove active class from all tab buttons
    document.querySelectorAll('.help-tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.color = '#86868b';
        btn.style.borderBottomColor = 'transparent';
    });

    // Show selected tab content
    if (tabName === 'structure') {
        document.getElementById('helpTabStructure').style.display = 'block';
    } else if (tabName === 'property-flow') {
        document.getElementById('helpTabPropertyFlow').style.display = 'block';
    }

    // Add active class to clicked button
    const activeBtn = document.querySelector(`.help-tab-btn[data-tab="${tabName}"]`);
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.color = '#0071e3';
        activeBtn.style.borderBottomColor = '#0071e3';
    }
}

function openGeneratorModal() {
    if (!generatorModules.length && !generatorFallback.tools_path) {
        loadGeneratorDefaults();
    }
    applyGeneratorDefaults(document.getElementById('generatorModule')?.value || '');
    const resultEl = document.getElementById('generatorResult');
    if (resultEl) resultEl.textContent = '';
    document.getElementById('generatorModal').classList.add('show');
}

function runServerGeneration() {
    const profileQuery = profileParam();
    const payload = {
        module: document.getElementById('generatorModule')?.value || null,
        tools_path: document.getElementById('generatorToolsPath')?.value || '',
        template_path: document.getElementById('generatorTemplatePath')?.value || '',
        output_path: document.getElementById('generatorOutputPath')?.value || ''
    };

    fetch(`/api/server-generator${profileQuery}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json().then(data => ({status: response.status, data})))
    .then(({status, data}) => {
        const resultEl = document.getElementById('generatorResult');
        if (status >= 200 && status < 300 && data.success) {
            showNotification(`Generated server at ${data.output_path}`, 'success');
            if (resultEl) resultEl.textContent = `Output: ${data.output_path} (${data.tool_count} tools)`;
            // Auto-close modal after 0.5 seconds on success
            setTimeout(() => {
                closeModal('generatorModal');
            }, 500);
        } else {
            const message = data.error || 'Failed to generate server';
            showNotification(message, 'error');
            if (resultEl) resultEl.textContent = message;
        }
    })
    .catch(error => {
        console.error('Error generating server:', error);
        showNotification('Failed to generate server', 'error');
    });
}

function renderProfileTabs() {
    const tabContainer = document.getElementById('profileTabs');
    if (!tabContainer) return;
    tabContainer.innerHTML = '';
    if (!profiles || profiles.length === 0) {
        tabContainer.textContent = 'No profiles found (using default)';
    } else {
        profiles.filter(name => name && name.trim()).forEach((name, index) => {
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
                currentProfile = name;
                window.currentProfile = name;  // Sync with window for delete button
                originalProfile = name;  // Update original profile when switching
                renderProfileTabs();
                loadTools();
                loadGeneratorDefaults();
                loadTemplateSources();  // Reload template sources for new profile
                loadMcpServices();  // Reload MCP services for new profile
                loadGraphTypesProperties();  // Reload types for new profile
                // Reset template selector to default
                const templateSelect = document.getElementById('templateSource');
                if (templateSelect) templateSelect.value = '';
            };
            tabContainer.appendChild(btn);
        });
    }
}

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
                <button class="btn btn-secondary" onclick="closeNewProjectModal()">Cancel</button>
                <button class="btn btn-primary" onclick="createNewProfileProject()">Create Project</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) closeNewProjectModal(); };
    document.getElementById('newProjectName').focus();
}

function closeNewProjectModal() {
    const modal = document.getElementById('newProjectModal');
    if (modal) modal.remove();
}

async function createNewProfileProject() {
    const name = document.getElementById('newProjectName').value.trim();
    if (!name) {
        showNotification('Project name is required', 'error');
        return;
    }

    const mcpPath = document.getElementById('newProjectMcpPath').value.trim() || `../mcp_${name.toLowerCase().replace(/\s+/g, '_')}/mcp_server`;
    const port = parseInt(document.getElementById('newProjectPort').value) || 8091;
    const createMcp = document.getElementById('newProjectCreateMcp').checked;

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
            showNotification(result.error, 'error');
            return;
        }

        showNotification(`Project "${result.profile}" created successfully!`, 'success');
        closeNewProjectModal();

        // Reload profiles and switch to new one
        profiles.push(result.profile);
        currentProfile = result.profile;
        window.currentProfile = result.profile;  // Also update window scope
        renderProfileTabs();
        loadTools();
        loadGeneratorDefaults();
    } catch (error) {
        showNotification('Failed to create project: ' + error.message, 'error');
    }
}

function profileParam() {
    // Always use originalProfile for saving operations
    // This ensures changes are saved to the profile where tools were loaded from,
    // even if MCP services are loaded from a different template source
    return originalProfile ? `?profile=${encodeURIComponent(originalProfile)}` : '';
}

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

// ========== Tool Service-Only Parameter Check ==========
function getServiceOnlyParams(tool) {
    // Check if tool has service-only required parameters (in service but not in inputSchema/internalArgs)
    // Guard against servicesInfo not being initialized yet
    if (!window.servicesInfo || typeof servicesInfo !== 'object') {
        return [];
    }

    const serviceName = typeof tool.mcp_service === 'string'
        ? tool.mcp_service
        : tool.mcp_service?.name;

    if (!serviceName || !servicesInfo[serviceName]) {
        return [];
    }

    const service = servicesInfo[serviceName];
    if (!service.parameters || service.parameters.length === 0) {
        return [];
    }

    const schemaProperties = tool.inputSchema?.properties || {};
    const toolInternalArgs = (window.internalArgs && internalArgs[tool.name]) || {};
    const allDefinedProps = new Set([
        ...Object.keys(schemaProperties),
        ...Object.keys(toolInternalArgs)
    ]);

    const serviceOnlyParams = [];

    service.parameters.forEach(param => {
        const isOptional = typeof param.is_optional === 'boolean'
            ? param.is_optional
            : (typeof param.is_required === 'boolean' ? !param.is_required : false);
        const isRequired = typeof param.is_required === 'boolean' ? param.is_required : !isOptional;
        if (!isRequired) return;

        let isDefined = false;

        // Check direct match
        if (allDefinedProps.has(param.name)) {
            isDefined = true;
        } else {
            // Check targetParam mappings
            for (const [propName, propDef] of Object.entries(schemaProperties)) {
                if (propDef.targetParam === param.name) {
                    isDefined = true;
                    break;
                }
            }
        }

        if (!isDefined) {
            serviceOnlyParams.push(param.name);
        }
    });

    return serviceOnlyParams;
}
// ========== End Tool Service-Only Parameter Check ==========

// ========== Tool Drag and Drop Functions ==========
let draggedToolIndex = null;

function handleToolDragStart(e, index) {
    draggedToolIndex = index;
    e.target.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', index);
}

function handleToolDragEnd(e) {
    e.target.classList.remove('dragging');
    document.querySelectorAll('.tool-item').forEach(item => {
        item.classList.remove('drag-over');
    });
    draggedToolIndex = null;
}

function handleToolDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const toolItem = e.target.closest('.tool-item');
    if (toolItem && !toolItem.classList.contains('dragging')) {
        // Remove drag-over from all items
        document.querySelectorAll('.tool-item').forEach(item => {
            item.classList.remove('drag-over');
        });
        toolItem.classList.add('drag-over');
    }
}

function handleToolDragLeave(e) {
    const toolItem = e.target.closest('.tool-item');
    if (toolItem) {
        toolItem.classList.remove('drag-over');
    }
}

function handleToolDrop(e, dropIndex) {
    e.preventDefault();
    const toolItem = e.target.closest('.tool-item');
    if (toolItem) {
        toolItem.classList.remove('drag-over');
    }

    if (draggedToolIndex === null || draggedToolIndex === dropIndex) {
        return;
    }

    // Reorder tools array
    const draggedTool = tools[draggedToolIndex];
    tools.splice(draggedToolIndex, 1);
    tools.splice(dropIndex, 0, draggedTool);

    // Update currentToolIndex if needed
    if (currentToolIndex === draggedToolIndex) {
        currentToolIndex = dropIndex;
    } else if (draggedToolIndex < currentToolIndex && dropIndex >= currentToolIndex) {
        currentToolIndex--;
    } else if (draggedToolIndex > currentToolIndex && dropIndex <= currentToolIndex) {
        currentToolIndex++;
    }

    // Re-render
    renderToolList();
    showNotification(`Moved "${draggedTool.name}" to position ${dropIndex + 1}`, 'success');

    // Mark as unsaved
    markUnsaved();
}

function markUnsaved() {
    // Add visual indicator that there are unsaved changes
    const saveButton = document.querySelector('[data-debug-id="BTN_SAVE"]');
    if (saveButton && !saveButton.classList.contains('unsaved')) {
        saveButton.classList.add('unsaved');
        saveButton.style.animation = 'pulse 1s infinite';
    }
}
// ========== End Tool Drag and Drop Functions ==========
