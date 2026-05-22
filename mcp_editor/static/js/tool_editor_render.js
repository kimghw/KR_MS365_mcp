/* Tool Editor Render - Tool List and Editor Rendering */

// ============================================================
// Utility Functions for HTML Attribute Escaping
// ============================================================

/**
 * Escape a string for safe use in HTML attributes
 * Handles quotes, ampersands, and other special characters
 */
function escapeHtmlAttr(str) {
    if (str === undefined || str === null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * Format a nested property's default value for display in an input field
 * Arrays of strings are displayed as comma-separated values for easier editing
 * Complex arrays/objects use JSON format
 * @param {*} value - The default value
 * @param {string} type - The property type
 * @returns {string} - Formatted string for display
 */
function formatNestedDefaultValue(value, type) {
    if (value === undefined || value === null) return '';

    if (type === 'array') {
        if (Array.isArray(value)) {
            // Check if all items are simple strings (no commas, no quotes needed)
            const allSimpleStrings = value.every(item =>
                typeof item === 'string' && !item.includes(',') && !item.includes('"')
            );
            if (allSimpleStrings && value.length > 0) {
                // Display as comma-separated for easier editing
                return value.join(', ');
            }
            // For complex arrays, use JSON format
            return JSON.stringify(value);
        }
        // If it's already a string (shouldn't happen but handle it)
        return String(value);
    }

    if (type === 'object') {
        if (typeof value === 'object') {
            return JSON.stringify(value);
        }
        return String(value);
    }

    // For primitive types, just convert to string
    return String(value);
}

function renderToolList() {
    console.log('[DEBUG] renderToolList() called');
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
        toolItem.setAttribute('data-tool-index', index);
        toolItem.setAttribute('draggable', 'true');
        if (index === currentToolIndex) {
            toolItem.classList.add('active');
        }
        toolItem.onclick = (e) => {
            // Don't select if clicking drag handle
            if (e.target.classList.contains('drag-handle')) return;
            selectTool(index);
        };

        // Drag and drop events
        toolItem.ondragstart = (e) => handleToolDragStart(e, index);
        toolItem.ondragend = handleToolDragEnd;
        toolItem.ondragover = handleToolDragOver;
        toolItem.ondragleave = handleToolDragLeave;
        toolItem.ondrop = (e) => handleToolDrop(e, index);

        // Get service method info
        const serviceName = typeof tool.mcp_service === 'string'
            ? tool.mcp_service
            : tool.mcp_service?.name;
        const serviceMethodHtml = serviceName
            ? `<div style="margin-top: 5px; font-size: 11px; color: var(--primary-color); font-weight: 500;">
                <span style="color: #666;">Service:</span> ${serviceName}
               </div>`
            : '';

        // Check for service-only required parameters (need to be added as Signature or Internal)
        const serviceOnlyParams = getServiceOnlyParams(tool);
        const warningBadgeHtml = serviceOnlyParams.length > 0
            ? `<span class="warning-badge" title="Needs config: ${serviceOnlyParams.join(', ')}"
                style="position: absolute; top: 8px; right: 8px; background: #dc3545; color: white;
                       font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 10px;
                       display: flex; align-items: center; gap: 3px;">
                <span style="font-size: 12px;">⚠</span>${serviceOnlyParams.length}
               </span>`
            : '';

        toolItem.innerHTML = `
            <span class="drag-handle" title="Drag to reorder">⋮⋮</span>
            ${warningBadgeHtml}
            <h3>${tool.name}</h3>
            <p>${tool.description}</p>
            ${serviceMethodHtml}
        `;
        toolList.appendChild(toolItem);
        console.log(`[DEBUG] Tool ${index} appended to DOM`);
    });
    console.log('[DEBUG] forEach loop completed, total tools:', tools.length);
}

function selectTool(index) {
    currentToolIndex = index;
    renderToolList();
    renderToolEditor(tools[index], index);
}

function renderToolEditor(tool, index) {
    const editorContent = document.getElementById('editorContent');

    const properties = tool.inputSchema?.properties || {};
    const required = tool.inputSchema?.required || [];

    // Helper to check if property is internal
    const getToolInternalArgs = () => internalArgs[tool.name] || {};
    const isPropertyInternal = (propName) => {
        const toolInternalArgs = getToolInternalArgs();
        return propName in toolInternalArgs;
    };

    // Check if property is MCP service parameter
    const normalizeMcpPropName = (propName) => {
        if (propName && propName.endsWith('_internal')) {
            return propName.slice(0, -'_internal'.length);
        }
        return propName;
    };

    const isPropertyMcpParam = (propName) => {
        if (!tool.mcp_service) {
            return false;
        }

        const serviceName = typeof tool.mcp_service === 'object'
            ? tool.mcp_service?.name
            : tool.mcp_service;
        if (!serviceName) {
            return false;
        }

        const serviceDetail = window.mcpServiceDetails
            ? window.mcpServiceDetails.find(svc => svc.name === serviceName)
            : null;
        const parameters = (serviceDetail && Array.isArray(serviceDetail.parameters))
            ? serviceDetail.parameters
            : (typeof tool.mcp_service === 'object' ? tool.mcp_service.parameters : null);
        if (!Array.isArray(parameters)) {
            return false;
        }

        const normalizedName = normalizeMcpPropName(propName);
        return parameters.some(param => {
            if (!param) {
                return false;
            }
            if (typeof param === 'string') {
                return param === normalizedName;
            }
            return param.name === normalizedName;
        });
    };

    // CRITICAL: Merge properties from inputSchema AND internalArgs
    // This ensures internal-only properties remain visible and editable
    const toolInternalArgs = getToolInternalArgs();
    const allPropertyNames = new Set([
        ...Object.keys(properties),
        ...Object.keys(toolInternalArgs)
    ]);

    let propertiesHtml = '';
    for (const propName of allPropertyNames) {
        // Get propDef from inputSchema if it exists, otherwise reconstruct from internalArgs
        const isInternal = isPropertyInternal(propName);
        let propDef;
        if (properties[propName]) {
            propDef = properties[propName];
        } else if (isInternal && toolInternalArgs[propName].original_schema) {
            // Use stored original_schema for display (but don't modify inputSchema)
            propDef = toolInternalArgs[propName].original_schema;
        } else if (isInternal) {
            // Fallback: create minimal schema from internal arg info
            propDef = {
                type: toolInternalArgs[propName].type || 'object',
                description: toolInternalArgs[propName].description || ''
            };
        } else {
            continue; // Skip if neither in properties nor internal
        }
        // Original loop logic below uses propName and propDef
        const isRequired = required.includes(propName);
        // isInternal already set above
        const isMcpParam = isPropertyMcpParam(propName);
        const hasSignatureDefaults = !isInternal && signatureDefaults[tool.name]?.[propName];
        const propId = `prop-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}`;
        propertiesHtml += `
            <div class="property-collapsible" data-internal="${isInternal}">
                <div class="property-collapse-header" onclick="togglePropertyCollapse('${propId}')" id="header-${propId}"
                     style="${isInternal ? 'border-left: 3px solid var(--warning-color);' : ''}">
                    <div style="display: flex; align-items: center;">
                        <span class="collapse-icon" id="icon-${propId}">▼</span>
                        <input type="text" value="${propName}"
                               id="propname-${propId}"
                               data-original-name="${propName}"
                               style="font-size: 15px; color: #333; font-weight: bold; border: 1px solid transparent; background: transparent; padding: 2px 6px; border-radius: 4px; min-width: 100px;"
                               onfocus="this.style.borderColor='var(--primary-color)'; this.style.background='white';"
                               onblur="renameSchemaProperty(${index}, this.dataset.originalName, this.value, this); this.style.borderColor='transparent'; this.style.background='transparent';"
                               onkeypress="if(event.key === 'Enter') { this.blur(); }"
                               onclick="event.stopPropagation();">
                        <span style="margin-left: 12px; font-size: 12px; color: #666; background: #f0f0f0; padding: 2px 8px; border-radius: 4px;">${propDef.type}</span>
                        ${isInternal ? '<span style="margin-left: 8px; font-size: 10px; color: white; background: var(--warning-color); padding: 2px 6px; border-radius: 4px; font-weight: 600;">INTERNAL</span>' : ''}
                        ${hasSignatureDefaults ? '<span style="margin-left: 8px; font-size: 10px; color: white; background: var(--success-color); padding: 2px 6px; border-radius: 4px; font-weight: 600;">DEFAULTS</span>' : ''}
                        ${isMcpParam ? `<span style="margin-left: 8px; font-size: 10px; color: white; background: ${isInternal ? 'var(--warning-color)' : 'var(--primary-color)'}; padding: 2px 6px; border-radius: 4px; font-weight: 600;">MCP</span>` : ''}
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px;" onclick="event.stopPropagation();">
                        ${propDef.type === 'object' ? `
                        <button class="btn btn-sm"
                                style="background: ${propDef.baseModel ? 'var(--success-color)' : 'var(--primary-color)'}; color: white; padding: 4px 12px; border-radius: 980px; font-size: 11px;"
                                onclick="showBaseModelSelector(${index}, '${propName}')">
                            ${propDef.baseModel || 'Select BaseModel'}
                        </button>
                        ` : `
                        <!-- Inline default value for non-object types -->
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="font-size: 10px; color: var(--text-secondary);">default:</span>
                            ${propDef.type === 'boolean' ? `
                            <button type="button"
                                    style="padding: 2px 6px; font-size: 10px; border-radius: 3px; cursor: pointer; transition: all 0.2s;
                                           ${propDef.default === false ? 'background: #ffebee; color: #c62828; border: 1px solid #ef9a9a;' : 'background: #f5f5f5; color: #666; border: 1px solid #ddd;'}"
                                    onclick="event.stopPropagation(); updatePropertyField(${index}, '${propName}', 'default', false); renderToolEditor(tools[${index}], ${index});">
                                F
                            </button>
                            <button type="button"
                                    style="padding: 2px 6px; font-size: 10px; border-radius: 3px; cursor: pointer; transition: all 0.2s;
                                           ${propDef.default === true ? 'background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7;' : 'background: #f5f5f5; color: #666; border: 1px solid #ddd;'}"
                                    onclick="event.stopPropagation(); updatePropertyField(${index}, '${propName}', 'default', true); renderToolEditor(tools[${index}], ${index});">
                                T
                            </button>
                            ${propDef.default !== undefined ? `
                            <button type="button" title="Clear default"
                                    style="padding: 2px 4px; font-size: 10px; border-radius: 3px; cursor: pointer; background: transparent; color: #999; border: none;"
                                    onclick="event.stopPropagation(); updatePropertyField(${index}, '${propName}', 'default', undefined); renderToolEditor(tools[${index}], ${index});">
                                <span class="material-icons" style="font-size: 12px;">close</span>
                            </button>` : ''}
                            ` : `
                            <input type="text"
                                   id="inline-default-${propId}"
                                   style="font-size: 10px; padding: 2px 6px; border: 1px solid var(--border-color); border-radius: 4px; background: white; width: 160px;"
                                   placeholder="(none)"
                                   value="${propDef.default !== undefined ? String(propDef.default).replace(/"/g, '&quot;') : ''}"
                                   onclick="event.stopPropagation();"
                                   onchange="event.stopPropagation(); updatePropertyField(${index}, '${propName}', 'default', parseDefaultValue(this.value, '${propDef.type}')); renderToolEditor(tools[${index}], ${index});">
                            `}
                        </div>
                        <!-- Inline targetParam selector for non-object types -->
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="font-size: 10px; color: var(--text-secondary);">param:</span>
                            <select class="form-control"
                                    id="inline-targetparam-${propId}"
                                    style="font-size: 10px; padding: 2px 4px; width: 100px; height: 22px;"
                                    onclick="event.stopPropagation();"
                                    onchange="event.stopPropagation(); updatePropertyField(${index}, '${propName}', 'targetParam', this.value || undefined)">
                                <option value="">= ${propName}</option>
                            </select>
                        </div>
                        `}
                        <label style="display: flex; align-items: center; cursor: pointer; margin: 0;">
                            <input type="checkbox" ${isRequired ? 'checked' : ''}
                                   onchange="toggleRequired(${index}, '${propName}', this.checked)"
                                   style="margin-right: 6px;">
                            <span style="color: ${isRequired ? 'var(--danger-color)' : 'var(--text-secondary)'}; font-size: 13px; font-weight: 500;">Required</span>
                        </label>
                        <button class="btn btn-icon btn-sm" onclick="removeProperty(${index}, '${propName}')"><span class="material-icons">close</span></button>
                    </div>
                </div>
                <div class="property-collapse-content" id="content-${propId}">
                <div style="display: flex; gap: 10px; margin-bottom: 8px; align-items: center; flex-wrap: wrap;">
                    <span style="font-size: 11px; color: var(--text-secondary);">Dest:</span>
                    <label style="display: flex; align-items: center; cursor: pointer; padding: 4px 10px; border: 2px solid ${!isInternal ? 'var(--primary-color)' : 'var(--border-color)'}; border-radius: 5px; background: ${!isInternal ? 'rgba(0, 113, 227, 0.1)' : 'white'};">
                        <input type="radio" name="dest-${propId}" value="signature" ${!isInternal ? 'checked' : ''}
                               onchange="setPropertyDestination(${index}, '${propName}', 'signature')" style="margin-right: 4px;">
                        <span style="font-size: 11px; font-weight: 500;">Signature</span>
                    </label>
                    <label style="display: flex; align-items: center; cursor: pointer; padding: 4px 10px; border: 2px solid ${isInternal ? 'var(--warning-color)' : 'var(--border-color)'}; border-radius: 5px; background: ${isInternal ? 'rgba(255, 159, 10, 0.1)' : 'white'};">
                        <input type="radio" name="dest-${propId}" value="internal" ${isInternal ? 'checked' : ''}
                               onchange="setPropertyDestination(${index}, '${propName}', 'internal')" style="margin-right: 4px;">
                        <span style="font-size: 11px; font-weight: 500;">Internal</span>
                    </label>
                    ${!isInternal && propDef.type === 'object' ? `
                    <label style="display: flex; align-items: center; cursor: pointer; padding: 4px 10px; border: 2px solid ${hasSignatureDefaults ? 'var(--success-color)' : 'var(--border-color)'}; border-radius: 5px; background: ${hasSignatureDefaults ? 'rgba(52, 199, 89, 0.1)' : 'white'}; margin-left: 4px;">
                        <input type="checkbox" ${hasSignatureDefaults ? 'checked' : ''}
                               onchange="toggleSignatureDefaults(${index}, '${propName}', this.checked)" style="margin-right: 4px;">
                        <span style="font-size: 11px; font-weight: 500; color: ${hasSignatureDefaults ? 'var(--success-color)' : 'var(--text-secondary)'};">Use Defaults</span>
                    </label>
                    ` : ''}
                    <span style="font-size: 11px; color: var(--text-secondary); margin-left: 8px;">Type:</span>
                    <select class="form-control" style="width: auto; padding: 4px 8px; font-size: 11px;"
                            onchange="updatePropertyField(${index}, '${propName}', 'type', this.value); renderToolEditor(tools[${index}], ${index});">
                        <option value="string" ${propDef.type === 'string' ? 'selected' : ''}>string</option>
                        <option value="number" ${propDef.type === 'number' ? 'selected' : ''}>number</option>
                        <option value="integer" ${propDef.type === 'integer' ? 'selected' : ''}>integer</option>
                        <option value="boolean" ${propDef.type === 'boolean' ? 'selected' : ''}>boolean</option>
                        <option value="array" ${propDef.type === 'array' ? 'selected' : ''}>array</option>
                        <option value="object" ${propDef.type === 'object' ? 'selected' : ''}>object</option>
                    </select>
                </div>
                <div class="form-group" style="margin-bottom: 8px;">
                    <label style="font-size: 11px;">Service Method Parameter</label>
                    <select class="form-control" style="font-size: 12px;"
                            id="targetparam-${propId}"
                            onchange="updatePropertyField(${index}, '${propName}', 'targetParam', this.value || undefined)">
                        <option value="">-- Same as Input Schema Name (${propName}) --</option>
                    </select>
                    <div style="font-size: 10px; color: var(--text-secondary); margin-top: 4px;">
                        Maps this property to a specific service method parameter. Leave default if names match.
                    </div>
                </div>
                <div class="form-group" style="margin-bottom: 8px;">
                    <label style="font-size: 11px;">Description</label>
                    <input class="form-control" style="font-size: 12px;"
                           value="${(propDef.description || '').replace(/"/g, '&quot;')}"
                           onchange="updatePropertyField(${index}, '${propName}', 'description', this.value)">
                </div>
                ${propDef.type !== 'object' ? `
                <div class="form-group" id="default-value-group-${propId}">
                    <label style="font-size: 11px;">Default Value ${propDef.type === 'array' ? '(JSON)' : ''}</label>
                    ${propDef.type === 'array' ? `
                    <textarea class="form-control" style="font-family: monospace; font-size: 12px; min-height: 120px; padding: 6px 8px;"
                              placeholder='["item1", "item2"]'
                              onchange="updatePropertyField(${index}, '${propName}', 'default', parseDefaultValue(this.value, '${propDef.type}'))">${propDef.default !== undefined ? (typeof propDef.default === 'string' ? propDef.default : JSON.stringify(propDef.default, null, 2)) : ''}</textarea>
                    ` : `
                    <input class="form-control" style="font-size: 12px; padding: 6px 8px; height: 30px;"
                           value="${propDef.default !== undefined ? propDef.default : ''}"
                           placeholder="Optional default value"
                           onchange="updatePropertyField(${index}, '${propName}', 'default', parseDefaultValue(this.value, '${propDef.type}'))">
                    `}
                </div>
                ` : ''}
                ${propDef.enum ? `
                <div class="form-group">
                    <label>Enum Values (comma-separated)</label>
                    <input class="form-control" value="${propDef.enum.join(', ')}"
                           onchange="updatePropertyEnum(${index}, '${propName}', this.value)">
                </div>
                ` : ''}
                ${propDef.type === 'array' ? `
                <div class="form-group">
                    <label>Array Item Type</label>
                    <select class="form-control"
                            onchange="updatePropertyField(${index}, '${propName}', 'items', {type: this.value})">
                        <option value="string" ${propDef.items?.type === 'string' ? 'selected' : ''}>string</option>
                        <option value="number" ${propDef.items?.type === 'number' ? 'selected' : ''}>number</option>
                        <option value="integer" ${propDef.items?.type === 'integer' ? 'selected' : ''}>integer</option>
                        <option value="boolean" ${propDef.items?.type === 'boolean' ? 'selected' : ''}>boolean</option>
                        <option value="object" ${propDef.items?.type === 'object' ? 'selected' : ''}>object</option>
                    </select>
                </div>
                ` : ''}
                ${propDef.type === 'object' && propDef.properties ? `
                <div class="form-group">
                    <label style="display: flex; justify-content: space-between; align-items: center;">
                        <span>Nested Properties</span>
                        <div style="display: flex; gap: 6px; align-items: center;">
                            <!-- Tab buttons -->
                            <div style="display: flex; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden;">
                                <button type="button" id="tab-gui-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}"
                                        class="nested-tab-btn active"
                                        style="padding: 4px 12px; font-size: 10px; font-weight: 600; background: var(--primary-color); color: white; border: none; cursor: pointer; transition: all 0.2s;"
                                        onclick="switchNestedTab(${index}, '${propName}', 'gui')">
                                    GUI
                                </button>
                                <button type="button" id="tab-json-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}"
                                        class="nested-tab-btn"
                                        style="padding: 4px 12px; font-size: 10px; font-weight: 600; background: #f5f5f5; color: #666; border: none; border-left: 1px solid var(--border-color); cursor: pointer; transition: all 0.2s;"
                                        onclick="switchNestedTab(${index}, '${propName}', 'json')">
                                    JSON
                                </button>
                            </div>
                            <label style="font-size: 10px; color: var(--text-secondary); display: flex; align-items: center; margin: 0; cursor: pointer;">
                                <input type="checkbox" id="nested-select-all-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}"
                                       onchange="toggleAllNestedCheckboxes(${index}, '${propName}', this.checked)"
                                       style="margin-right: 3px; transform: scale(0.9);">
                                All
                            </label>
                            <button class="btn btn-icon btn-sm" style="padding: 4px; color: var(--danger-color); background: rgba(255, 59, 48, 0.1); border-radius: 4px; transition: all 0.2s;"
                                    onmouseover="this.style.background='rgba(255, 59, 48, 0.2)'"
                                    onmouseout="this.style.background='rgba(255, 59, 48, 0.1)'"
                                    onclick="removeSelectedNestedProperties(${index}, '${propName}')"
                                    title="Delete selected properties">
                                <span class="material-icons" style="font-size: 16px;">delete</span>
                            </button>
                        </div>
                    </label>
                    <!-- JSON Editor Tab (hidden by default) -->
                    <div id="nested-json-editor-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}" class="nested-tab-content" style="display: none; margin-top: 8px;">
                        <textarea id="nested-json-textarea-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}"
                                  style="width: 100%; min-height: 250px; font-family: monospace; font-size: 11px; padding: 8px; border: 1px solid #90caf9; border-radius: 4px; background: #fafafa;"
                                  placeholder='{"propertyName": {"type": "string", "default": "value", "description": "설명"}}'
                                  onchange="markNestedJsonDirty(${index}, '${propName}')"></textarea>
                        <div style="display: flex; gap: 8px; margin-top: 8px; align-items: center;">
                            <button type="button" class="btn btn-sm" style="background: var(--success-color); color: white; padding: 4px 12px; border-radius: 4px; font-size: 11px;"
                                    onclick="applyNestedJsonEdit(${index}, '${propName}')">
                                <span class="material-icons" style="font-size: 12px; vertical-align: middle;">check</span> Apply & Sync to GUI
                            </button>
                            <button type="button" class="btn btn-sm" style="background: #fff3e0; color: #ef6c00; padding: 4px 12px; border-radius: 4px; font-size: 11px;"
                                    onclick="copyNestedJsonToClipboard(${index}, '${propName}')">
                                <span class="material-icons" style="font-size: 12px; vertical-align: middle;">content_copy</span> Copy
                            </button>
                            <span id="nested-json-status-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}" style="font-size: 10px; color: var(--text-secondary); margin-left: auto;"></span>
                        </div>
                    </div>
                    <!-- GUI Tab (shown by default) -->
                    <div id="nested-gui-editor-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}" class="nested-tab-content" style="margin-top: 8px;">
                    <div style="padding: 12px; background: var(--bg-color); border-left: 3px solid ${propDef.baseModel ? 'var(--success-color)' : 'var(--primary-color)'}; border-radius: var(--radius-sm);">
                        ${Object.entries(propDef.properties).map(([nestedPropName, nestedProp]) => {
                            const nestedIsRequired = propDef.required && propDef.required.includes(nestedPropName);
                            const nestedPropId = `nested-${index}-${propName}-${nestedPropName}`.replace(/[^a-zA-Z0-9-]/g, '_');
                            // Generate default value display for header
                            const defaultDisplay = nestedProp.default !== undefined ?
                                (nestedProp.type === 'boolean' ? (nestedProp.default ? 'true' : 'false') : String(nestedProp.default)) : '';
                            const hasDefault = nestedProp.default !== undefined;

                            return `
                            <div class="nested-prop-collapsible" style="margin-bottom: 6px; background: white; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden;">
                                <div class="nested-prop-header" onclick="toggleNestedPropCollapse('${nestedPropId}')"
                                     style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; cursor: pointer; background: #fafafa;">
                                    <div style="display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0;">
                                        <input type="checkbox" class="nested-prop-checkbox"
                                               data-tool-index="${index}" data-parent-prop="${propName}" data-nested-prop="${nestedPropName}"
                                               onclick="event.stopPropagation(); updateNestedSelectAllState(${index}, '${propName}')"
                                               style="margin: 0; flex-shrink: 0; width: 14px;">
                                        <span class="nested-collapse-icon" id="nested-icon-${nestedPropId}" style="font-size: 10px; color: var(--text-secondary); flex-shrink: 0; width: 10px;">▶</span>
                                        <strong style="color: var(--text-primary); font-size: 12px; flex-shrink: 0; width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${nestedPropName}">${nestedPropName}</strong>
                                        <select style="font-size: 10px; padding: 2px 4px; border: 1px solid var(--border-color); border-radius: 4px; background: white; flex-shrink: 0; width: 70px;"
                                                onclick="event.stopPropagation();"
                                                onchange="event.stopPropagation(); updateNestedPropertyType(${index}, '${propName}', '${nestedPropName}', this.value); renderToolEditor(tools[${index}], ${index});">
                                            <option value="string" ${nestedProp.type === 'string' ? 'selected' : ''}>string</option>
                                            <option value="number" ${nestedProp.type === 'number' ? 'selected' : ''}>number</option>
                                            <option value="integer" ${nestedProp.type === 'integer' ? 'selected' : ''}>integer</option>
                                            <option value="boolean" ${nestedProp.type === 'boolean' ? 'selected' : ''}>boolean</option>
                                            <option value="array" ${nestedProp.type === 'array' ? 'selected' : ''}>array</option>
                                            <option value="object" ${nestedProp.type === 'object' ? 'selected' : ''}>object</option>
                                        </select>
                                        <span style="font-size: 9px; color: ${nestedIsRequired ? 'var(--danger-color)' : 'transparent'}; font-weight: 600; flex-shrink: 0; width: 24px;">${nestedIsRequired ? 'REQ' : ''}</span>
                                        <!-- Default value inline display/edit - fixed width -->
                                        <div style="display: flex; align-items: center; gap: 4px; flex-shrink: 0; width: 140px;" onclick="event.stopPropagation();">
                                            <span style="font-size: 9px; color: var(--text-secondary); flex-shrink: 0; width: 38px;">default:</span>
                                            ${nestedProp.type === 'boolean' ? `
                                            <button type="button"
                                                    style="padding: 1px 6px; font-size: 9px; border-radius: 3px; cursor: pointer; transition: all 0.2s;
                                                           ${nestedProp.default === false ? 'background: #ffebee; color: #c62828; border: 1px solid #ef9a9a;' : 'background: #f5f5f5; color: #666; border: 1px solid #ddd;'}"
                                                    onclick="event.stopPropagation(); updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', false); renderToolEditor(tools[${index}], ${index});">
                                                F
                                            </button>
                                            <button type="button"
                                                    style="padding: 1px 6px; font-size: 9px; border-radius: 3px; cursor: pointer; transition: all 0.2s;
                                                           ${nestedProp.default === true ? 'background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7;' : 'background: #f5f5f5; color: #666; border: 1px solid #ddd;'}"
                                                    onclick="event.stopPropagation(); updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', true); renderToolEditor(tools[${index}], ${index});">
                                                T
                                            </button>
                                            ${hasDefault ? `
                                            <button type="button" title="Clear default"
                                                    style="padding: 1px 3px; font-size: 9px; border-radius: 3px; cursor: pointer; background: transparent; color: #999; border: none;"
                                                    onclick="event.stopPropagation(); updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', undefined); renderToolEditor(tools[${index}], ${index});">
                                                <span class="material-icons" style="font-size: 10px;">close</span>
                                            </button>` : ''}
                                            ` : `
                                            <input type="text"
                                                   style="font-size: 10px; padding: 2px 4px; border: 1px solid var(--border-color); border-radius: 4px; background: white; width: 80px;"
                                                   placeholder="(none)"
                                                   value="${escapeHtmlAttr(formatNestedDefaultValue(nestedProp.default, nestedProp.type))}"
                                                   onclick="event.stopPropagation();"
                                                   onchange="event.stopPropagation(); updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', parseDefaultValue(this.value, '${nestedProp.type}')); renderToolEditor(tools[${index}], ${index});">
                                            `}
                                        </div>
                                        <!-- Description inline - flex to fill remaining space -->
                                        <div style="display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;" onclick="event.stopPropagation();">
                                            <span style="font-size: 9px; color: var(--text-secondary); flex-shrink: 0; width: 28px;">desc:</span>
                                            <input type="text"
                                                   style="font-size: 10px; padding: 2px 4px; border: 1px solid var(--border-color); border-radius: 4px; background: white; flex: 1; min-width: 60px;"
                                                   placeholder="(none)"
                                                   value="${(nestedProp.description || '').replace(/"/g, '&quot;')}"
                                                   onclick="event.stopPropagation();"
                                                   onchange="event.stopPropagation(); updateNestedPropertyDescription(${index}, '${propName}', '${nestedPropName}', this.value);">
                                        </div>
                                    </div>
                                    <div style="display: flex; gap: 6px; align-items: center; flex-shrink: 0;" onclick="event.stopPropagation();">
                                        <label style="display: flex; align-items: center; margin: 0; cursor: pointer;">
                                            <input type="checkbox" ${nestedIsRequired ? 'checked' : ''}
                                                   onchange="toggleNestedRequired(${index}, '${propName}', '${nestedPropName}', this.checked)"
                                                   style="margin-right: 2px; transform: scale(0.8);">
                                            <span style="color: ${nestedIsRequired ? 'var(--danger-color)' : 'var(--text-secondary)'}; font-size: 10px;">Req</span>
                                        </label>
                                        <button class="btn btn-icon btn-sm" style="padding: 4px; color: var(--text-secondary); border-radius: 4px; transition: all 0.2s;"
                                                onmouseover="this.style.background='rgba(0,0,0,0.05)'; this.style.color='var(--danger-color)'"
                                                onmouseout="this.style.background='transparent'; this.style.color='var(--text-secondary)'"
                                                onclick="removeNestedPropertyInline(${index}, '${propName}', '${nestedPropName}')"><span class="material-icons" style="font-size: 16px;">delete_outline</span></button>
                                    </div>
                                </div>
                                <div class="nested-prop-content collapsed" id="nested-content-${nestedPropId}" style="padding: 10px; display: none;">
                                    <input class="form-control" style="font-size: 11px; margin-bottom: 6px; padding: 5px;"
                                           placeholder="Description"
                                           value="${(nestedProp.description || '').replace(/"/g, '&quot;')}"
                                           onchange="updateNestedPropertyDescription(${index}, '${propName}', '${nestedPropName}', this.value)">
                                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                                        ${nestedProp.type === 'boolean' ? `
                                        <div>
                                            <label style="font-size: 9px; color: var(--text-secondary); text-transform: uppercase;">Default Value</label>
                                            <div style="display: flex; gap: 8px; margin-top: 4px;">
                                                <button type="button"
                                                        style="flex: 1; padding: 6px 12px; font-size: 12px; border-radius: 6px; cursor: pointer; transition: all 0.2s;
                                                               ${nestedProp.default === false ? 'background: #ffebee; color: #c62828; border: 2px solid #ef5350;' : 'background: #f5f5f5; color: #666; border: 1px solid #ddd;'}"
                                                        onclick="updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', false); renderToolEditor(tools[${index}], ${index});">
                                                    false
                                                </button>
                                                <button type="button"
                                                        style="flex: 1; padding: 6px 12px; font-size: 12px; border-radius: 6px; cursor: pointer; transition: all 0.2s;
                                                               ${nestedProp.default === true ? 'background: #e8f5e9; color: #2e7d32; border: 2px solid #66bb6a;' : 'background: #f5f5f5; color: #666; border: 1px solid #ddd;'}"
                                                        onclick="updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', true); renderToolEditor(tools[${index}], ${index});">
                                                    true
                                                </button>
                                                <button type="button" title="Clear default"
                                                        style="padding: 6px 10px; font-size: 12px; border-radius: 6px; cursor: pointer; background: #fff3e0; color: #ef6c00; border: 1px solid #ffb74d;"
                                                        onclick="updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', undefined); renderToolEditor(tools[${index}], ${index});">
                                                    <span class="material-icons" style="font-size: 14px;">clear</span>
                                                </button>
                                            </div>
                                        </div>
                                        ` : `
                                        <div>
                                            <label style="font-size: 9px; color: var(--text-secondary); text-transform: uppercase;">Default ${nestedProp.type === 'array' ? '<span style="font-weight: normal; text-transform: none;">(comma separated)</span>' : ''}</label>
                                            <input class="form-control" style="font-size: 11px; padding: 5px;"
                                                   placeholder="${nestedProp.type === 'array' ? 'value1, value2' : 'default value'}"
                                                   value="${escapeHtmlAttr(formatNestedDefaultValue(nestedProp.default, nestedProp.type))}"
                                                   onchange="updateNestedPropertyDefault(${index}, '${propName}', '${nestedPropName}', parseDefaultValue(this.value, '${nestedProp.type}'))">
                                        </div>
                                        `}
                                        ${(nestedProp.type === 'string' || nestedProp.type === 'number' || nestedProp.type === 'integer') ? `
                                        <div>
                                            <label style="font-size: 9px; color: var(--text-secondary); text-transform: uppercase;">Format</label>
                                            <input class="form-control" style="font-size: 11px; padding: 5px;"
                                                   placeholder="date, email, uri"
                                                   value="${nestedProp.format || ''}"
                                                   onchange="updateNestedPropertyFormat(${index}, '${propName}', '${nestedPropName}', this.value)">
                                        </div>
                                        ` : '<div></div>'}
                                    </div>
                                    ${nestedProp.type === 'string' ? `
                                    <div style="margin-top: 6px;">
                                        <label style="font-size: 9px; color: var(--text-secondary); display: flex; align-items: center; text-transform: uppercase;">
                                            <input type="checkbox" ${nestedProp.enum ? 'checked' : ''}
                                                   onchange="toggleNestedEnum(${index}, '${propName}', '${nestedPropName}', this.checked)"
                                                   style="margin-right: 4px; transform: scale(0.8);">
                                            Has Enum
                                        </label>
                                        ${nestedProp.enum ? `
                                        <input class="form-control" style="font-size: 11px; padding: 5px; margin-top: 4px;"
                                               placeholder="Comma-separated values"
                                               value="${nestedProp.enum.join(', ')}"
                                               onchange="updateNestedPropertyEnum(${index}, '${propName}', '${nestedPropName}', this.value)">
                                        ` : ''}
                                    </div>
                                    ` : ''}
                                    ${nestedProp.type === 'array' ? `
                                    <div style="margin-top: 6px;">
                                        <label style="font-size: 9px; color: var(--text-secondary); text-transform: uppercase;">Array Item Type</label>
                                        <select class="form-control" style="font-size: 11px; padding: 5px;"
                                                onchange="updateNestedPropertyItems(${index}, '${propName}', '${nestedPropName}', this.value)">
                                            <option value="string" ${nestedProp.items?.type === 'string' ? 'selected' : ''}>string</option>
                                            <option value="number" ${nestedProp.items?.type === 'number' ? 'selected' : ''}>number</option>
                                            <option value="integer" ${nestedProp.items?.type === 'integer' ? 'selected' : ''}>integer</option>
                                            <option value="boolean" ${nestedProp.items?.type === 'boolean' ? 'selected' : ''}>boolean</option>
                                            <option value="object" ${nestedProp.items?.type === 'object' ? 'selected' : ''}>object</option>
                                        </select>
                                    </div>
                                    ` : ''}
                                </div>
                            </div>
                            `;
                        }).join('')}
                        ${window.hasTypesFile ? `
                        <button class="btn btn-secondary btn-sm" style="margin-top: 8px; font-size: 11px; padding: 4px 10px;"
                                onclick="openNestedGraphTypesModal(${index}, '${propName}')">
                            <span class="material-icons" style="font-size: 14px;">add</span> Add nested properties
                        </button>` : ''}
                    </div>
                    </div><!-- Close GUI Tab container -->
                </div>
                ` : propDef.type === 'object' ? `
                <div class="form-group">
                    <label>Nested Properties</label>
                    <div style=" padding: 20px; background: var(--bg-color); border-radius: var(--radius-sm);">
                        <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 12px;">No nested properties defined</div>
                        ${window.hasTypesFile ? `
                        <button class="btn btn-secondary btn-sm"
                                onclick="openNestedGraphTypesModal(${index}, '${propName}')">
                            <span class="material-icons">add</span> Add nested properties
                        </button>` : ''}
                    </div>
                </div>
                ` : ''}
                ${propDef.type === 'string' ? `
                <div class="form-group">
                    <label style="display: flex; align-items: center;">
                        <input type="checkbox" ${propDef.enum ? 'checked' : ''}
                               onchange="toggleEnum(${index}, '${propName}', this.checked)"
                               style="margin-right: 8px;">
                        Has Enum Values
                    </label>
                    ${propDef.enum ? `
                    <input class="form-control" value="${propDef.enum.join(', ')}"
                           placeholder="Enter comma-separated values"
                           onchange="updatePropertyEnum(${index}, '${propName}', this.value)">
                    ` : ''}
                </div>
                ` : ''}
                </div>
            </div>
        `;
    }

    editorContent.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
            <h2 style="font-size: 20px; font-weight: 600;">Edit Tool: ${tool.name}</h2>
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-secondary btn-sm" data-debug-id="BTN_VIEW_JSON" onclick="openRawJsonModal(${index})" style="display: flex; align-items: center; gap: 4px;">
                    <span class="material-icons" style="font-size: 16px;">code</span> View JSON
                </button>
                <button class="btn btn-danger btn-sm" data-debug-id="BTN_TOOL_DELETE" onclick="deleteTool(${index})">Delete Tool</button>
            </div>
        </div>

        <div style="display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 8px;">
            <div class="form-group" style="flex: 1; min-width: 240px; margin-bottom: 0;">
                <label>Tool Name</label>
                <input class="form-control" id="toolName" data-debug-id="FIELD_TOOL_NAME" value="${tool.name}"
                       onchange="updateToolField(${index}, 'name', this.value)">
            </div>
            <div class="form-group" style="flex: 1; min-width: 260px; margin-bottom: 0;">
                <label>MCP Service Method ${window.mcpServiceIsMerged ? '<span style="font-size: 10px; color: #6c757d;">(Merged)</span>' : ''}</label>
                <select class="form-control" id="mcpService" data-debug-id="FIELD_TOOL_SERVICE"
                        onchange="updateMcpService(${index}, this.value)">
                    <option value="">-- Select MCP Service Method --</option>
                    ${(() => {
                        const currentService = typeof tool.mcp_service === 'object' ? tool.mcp_service?.name : tool.mcp_service;
                        // If merged profile with groups, render optgroups
                        if (window.mcpServiceIsMerged && window.mcpServiceGroups && Object.keys(window.mcpServiceGroups).length > 1) {
                            return Object.entries(window.mcpServiceGroups).map(([className, services]) => {
                                const optionsHtml = services.map(service =>
                                    `<option value="${service}" ${currentService === service ? 'selected' : ''}>${service}</option>`
                                ).join('');
                                return `<optgroup label="${className}">${optionsHtml}</optgroup>`;
                            }).join('');
                        }
                        // Default flat list
                        return window.mcpServices ? window.mcpServices.map(service =>
                            `<option value="${service}" ${currentService === service ? 'selected' : ''}>${service}</option>`
                        ).join('') : '';
                    })()}
                </select>
            </div>
        </div>

        ${(() => {
            const serviceName = typeof tool.mcp_service === 'string'
                ? tool.mcp_service
                : tool.mcp_service?.name;

            if (serviceName) {
                return `
                <div style="background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; padding: 12px; margin-bottom: 16px;">
                    <div style="font-size: 12px; font-weight: 600; color: #495057; margin-bottom: 8px;">
                        Service Method Parameters:
                    </div>
                    <div id="serviceMethodParams" style="font-size: 11px; color: #6c757d;">
                        Loading parameters...
                    </div>
                </div>`;
            }
            return '';
        })()}

        <div class="form-group">
            <label>Description</label>
            <textarea class="form-control" id="toolDescription" data-debug-id="FIELD_TOOL_DESCRIPTION"
                      style="height: 60px; padding: 6px 8px; resize: vertical;"
                      onchange="updateToolField(${index}, 'description', this.value)">${tool.description}</textarea>
        </div>

        <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <label style="margin: 0;">Input Schema Properties</label>
                <div>
                    <button class="btn btn-sm btn-secondary" data-debug-id="BTN_PROP_EXPAND_ALL" onclick="expandAllProperties()" style="margin-right: 8px;">
                        ▼ Expand All
                    </button>
                    <button class="btn btn-sm btn-secondary" data-debug-id="BTN_PROP_COLLAPSE_ALL" onclick="collapseAllProperties()">
                        ▶ Collapse All
                    </button>
                </div>
            </div>
            <div class="properties-container">
                ${propertiesHtml}
                <button class="add-button" data-debug-id="BTN_PROP_ADD" onclick="addProperty(${index})">
                    <span class="material-icons">add</span> Add Property
                </button>
            </div>
        </div>
    `;

    // Load and display service method parameters
    loadAndDisplayServiceMethodParams(index);

    // Load service method parameters for each existing property's targetParam dropdown
    loadTargetParamsForExistingProperties(index);
}

function loadTargetParamsForExistingProperties(index) {
    const tool = tools[index];
    const serviceName = typeof tool.mcp_service === 'string'
        ? tool.mcp_service
        : tool.mcp_service?.name;

    if (!serviceName) return;

    const currentProfile = window.currentProfile || 'mcp_outlook';
    fetch(`/api/registry?profile=${currentProfile}`)
        .then(response => response.json())
        .then(registry => {
            if (registry && registry.services && registry.services[serviceName]) {
                const service = registry.services[serviceName];
                if (service.parameters) {
                    // Combine both inputSchema properties and internal args
                    const allProperties = {};

                    // Add inputSchema properties
                    if (tool.inputSchema?.properties) {
                        Object.entries(tool.inputSchema.properties).forEach(([propName, propDef]) => {
                            allProperties[propName] = propDef;
                        });
                    }

                    // Add internal args
                    const toolInternalArgs = internalArgs[tool.name] || {};
                    Object.entries(toolInternalArgs).forEach(([propName, propDef]) => {
                        allProperties[propName] = propDef;
                    });

                    // Update each property's targetParam dropdown (both original and inline)
                    Object.entries(allProperties).forEach(([propName, propDef]) => {
                        const propId = `prop-${index}-${propName.replace(/[^a-zA-Z0-9]/g, '_')}`;

                        // Get both dropdown IDs (original in content area and inline in header)
                        const selectIds = [`targetparam-${propId}`, `inline-targetparam-${propId}`];

                        selectIds.forEach(selectId => {
                            const select = document.getElementById(selectId);

                            if (select) {
                                // Clear existing options except the first one
                                const isInline = selectId.startsWith('inline-');
                                select.innerHTML = isInline
                                    ? `<option value="">= ${propName}</option>`
                                    : `<option value="">-- Same as Input Schema Name (${propName}) --</option>`;

                                // Add service method parameters as options
                                service.parameters.forEach(param => {
                                    const displayType = param.class_name || param.type || '';
                                    const option = document.createElement('option');
                                    option.value = param.name;
                                    option.textContent = isInline ? param.name : `${param.name} (${displayType})`;
                                    if (propDef.targetParam === param.name) {
                                        option.selected = true;
                                    }
                                    select.appendChild(option);
                                });
                            }
                        });
                    });
                }
            }
        })
        .catch(error => {
            console.error('Failed to load target params for existing properties:', error);
        });
}

function loadAndDisplayServiceMethodParams(index) {
    const tool = tools[index];
    const serviceName = typeof tool.mcp_service === 'string'
        ? tool.mcp_service
        : tool.mcp_service?.name;

    const paramsDiv = document.getElementById('serviceMethodParams');
    if (!paramsDiv || !serviceName) return;

    // Load registry to get method parameters
    const currentProfile = window.currentProfile || '_default';
    fetch(`/api/registry?profile=${currentProfile}`)
        .then(response => response.json())
        .then(registry => {
            if (registry && registry.services && registry.services[serviceName]) {
                const service = registry.services[serviceName];

                let paramsHtml = '';

                // Show handler information
                if (service.handler) {
                    paramsHtml += `
                        <div style="margin-bottom: 8px;">
                            <strong>Class:</strong> ${service.handler.class_name || 'N/A'}<br>
                            <strong>Method:</strong> ${service.handler.method || serviceName}<br>
                            <strong>Module:</strong> ${service.handler.module_path || 'N/A'}
                        </div>
                    `;
                }

                // Show parameters and check coverage
                if (service.parameters && service.parameters.length > 0) {
                    const schemaProperties = tool.inputSchema?.properties || {};
                    const toolInternalArgs = internalArgs[tool.name] || {};

                    // Get all properties from both schema and internal args
                    const allDefinedProps = new Set([
                        ...Object.keys(schemaProperties),
                        ...Object.keys(toolInternalArgs)
                    ]);

                    paramsHtml += '<div style="margin-top: 8px;"><strong>Parameters:</strong></div>';
                    paramsHtml += '<ul style="margin: 4px 0; padding-left: 20px;">';

                    let unconfiguredParams = [];

                    service.parameters.forEach(param => {
                        // Check if this parameter is defined in schema or internal args
                        let isDefined = false;
                        let definedWhere = '';

                        // Check direct match
                        if (allDefinedProps.has(param.name)) {
                            isDefined = true;
                            if (schemaProperties[param.name]) {
                                definedWhere = '✓ Signature';
                            } else if (toolInternalArgs[param.name]) {
                                definedWhere = '✓ Internal';
                            }
                        } else {
                            // Check targetParam mappings
                            for (const [propName, propDef] of Object.entries(schemaProperties)) {
                                if (propDef.targetParam === param.name) {
                                    isDefined = true;
                                    definedWhere = `✓ Signature (via ${propName})`;
                                    break;
                                }
                            }
                        }

                        const isOptional = typeof param.is_optional === 'boolean'
                            ? param.is_optional
                            : (typeof param.is_required === 'boolean' ? !param.is_required : false);
                        const isRequired = typeof param.is_required === 'boolean' ? param.is_required : !isOptional;
                        const defaultVal = param.has_default && param.default !== null
                            ? ` = ${JSON.stringify(param.default)}`
                            : '';
                        const displayType = param.class_name || param.type || '';

                        const statusColor = isDefined ? '#28a745' : (isRequired ? '#dc3545' : '#ffc107');
                        const statusIcon = isDefined ? '✓' : (isRequired ? '✗' : '○');
                        const statusText = isDefined ? definedWhere : (isRequired ? 'Needs Config' : 'Internal Candidate');

                        if (!isDefined && isRequired) {
                            unconfiguredParams.push(param.name);
                        }

                        paramsHtml += `
                            <li>
                                <code>${param.name}: ${displayType}${defaultVal}</code>
                                ${isRequired ? '<span style="color: #dc3545;"> *</span>' : ''}
                                <span style="margin-left: 10px; color: ${statusColor}; font-weight: 600;">
                                    ${statusIcon} ${statusText}
                                </span>
                            </li>`;
                    });
                    paramsHtml += '</ul>';

                    // Show warning for unconfigured required parameters
                    if (unconfiguredParams.length > 0) {
                        paramsHtml += `
                            <div style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 8px; margin-top: 8px;">
                                <strong style="color: #856404;">⚠️ Required Parameters Need Config:</strong>
                                <ul style="margin: 4px 0 0 0; padding-left: 20px;">
                                    ${unconfiguredParams.map(p => `<li style="color: #856404;">${p}</li>`).join('')}
                                </ul>
                                <div style="margin-top: 8px;">
                                    <button class="btn btn-sm btn-warning" onclick="addToSignature(${index}, ${JSON.stringify(unconfiguredParams).replace(/"/g, '&quot;')})">
                                        Add to Signature
                                    </button>
                                </div>
                            </div>`;
                    }
                } else {
                    paramsHtml += '<div style="margin-top: 8px;">No parameters defined</div>';
                }

                paramsDiv.innerHTML = paramsHtml;
            } else {
                paramsDiv.innerHTML = 'Service method not found in registry';
            }
        })
        .catch(error => {
            console.error('Failed to load service method params:', error);
            paramsDiv.innerHTML = 'Failed to load parameters';
        });
}

function addToSignature(index, params) {
    const tool = tools[index];

    if (!tool.inputSchema) {
        tool.inputSchema = { properties: {}, required: [] };
    }
    if (!tool.inputSchema.properties) {
        tool.inputSchema.properties = {};
    }

    // Add each parameter to inputSchema (Signature)
    params.forEach(paramName => {
        // Add to schema properties
        tool.inputSchema.properties[paramName] = {
            type: 'string',  // Default type, should be updated based on actual parameter type
            description: `Auto-added parameter for ${paramName}`
        };

        // Add to required if not already there
        if (!tool.inputSchema.required) {
            tool.inputSchema.required = [];
        }
        if (!tool.inputSchema.required.includes(paramName)) {
            tool.inputSchema.required.push(paramName);
        }
    });

    // Re-render the editor
    renderToolEditor(tool, index);
    showNotification(`Added ${params.length} parameter(s) to Signature`, 'success');
}

// Add parameters directly to Internal (without touching inputSchema)
function addAsInternal(index, paramsInfo) {
    const tool = tools[index];
    const toolName = tool.name;

    // Initialize internalArgs for this tool if needed
    if (!internalArgs[toolName]) {
        internalArgs[toolName] = {};
    }

    // Helper to extract baseModel from type strings like "Optional[SelectParams]"
    function extractBaseModel(typeStr) {
        if (!typeStr) return null;
        // Match patterns like Optional[SelectParams], List[str], etc.
        const match = typeStr.match(/(?:Optional|List|Dict|Set)\[([^\]]+)\]/);
        if (match) {
            const inner = match[1];
            // Only treat as baseModel if it's a class-like identifier (PascalCase)
            return /^[A-Z][a-zA-Z0-9]*$/.test(inner) ? inner : null;
        }
        // If no wrapper, check if it's a class name (capitalized)
        if (/^[A-Z][a-zA-Z0-9]*$/.test(typeStr)) {
            return typeStr;
        }
        return null;
    }

    // Add each parameter directly to internalArgs
    paramsInfo.forEach(paramInfo => {
        const paramName = paramInfo.name;
        const displayType = paramInfo.class_name || paramInfo.type || 'string';
        const baseModel = paramInfo.class_name || extractBaseModel(paramInfo.type);
        const isOptional = typeof paramInfo.is_optional === 'boolean'
            ? paramInfo.is_optional
            : (typeof paramInfo.is_required === 'boolean' ? !paramInfo.is_required : false);
        const wasRequired = typeof paramInfo.is_required === 'boolean' ? paramInfo.is_required : !isOptional;

        // Create internal arg entry with service metadata
        internalArgs[toolName][paramName] = {
            type: baseModel || displayType,
            description: paramInfo.description || `Service parameter: ${paramName}`,
            original_schema: {
                type: baseModel ? 'object' : mapToJsonSchemaType(displayType),
                description: paramInfo.description || `Service parameter: ${paramName}`,
                targetParam: paramName,
                ...(baseModel ? { baseModel: baseModel } : {})
            },
            was_required: wasRequired,
            // Store default value if available
            ...(paramInfo.has_default && paramInfo.default !== undefined
                ? { default: paramInfo.default }
                : {})
        };
    });

    // Re-render the editor
    renderToolEditor(tool, index);
    showNotification(`Added ${paramsInfo.length} parameter(s) as Internal`, 'success');
}

function updateToolField(index, field, value) {
    const oldValue = tools[index][field];
    tools[index][field] = value;

    // If tool name is changed, update internal_args key as well
    if (field === 'name' && oldValue !== value) {
        if (internalArgs[oldValue]) {
            internalArgs[value] = internalArgs[oldValue];
            delete internalArgs[oldValue];
            console.log(`Updated internal_args key: "${oldValue}" → "${value}"`);
        }
    }

    renderToolList();
}

function updateMcpService(index, value) {
    updateToolField(index, 'mcp_service', value);
    applySignatureDefaults(index, value);
    renderToolEditor(tools[index], index);
}

// ============================================================
// Internal Args Functions
// ============================================================

function getInternalArgDefaults(propArg) {
    // Extract default values from original_schema.properties
    if (!propArg || !propArg.original_schema || !propArg.original_schema.properties) {
        return {};
    }
    const defaults = {};
    for (const [key, prop] of Object.entries(propArg.original_schema.properties)) {
        if (prop.default !== undefined) {
            defaults[key] = prop.default;
        }
    }
    return defaults;
}
