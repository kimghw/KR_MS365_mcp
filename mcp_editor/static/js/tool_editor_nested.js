/* Tool Editor Nested - Nested Property Functions */

// ============================================================
// Nested Property Functions
// ============================================================

function toggleAllNestedCheckboxes(toolIndex, parentPropName, checked) {
    const checkboxes = document.querySelectorAll(
        `.nested-prop-checkbox[data-tool-index="${toolIndex}"][data-parent-prop="${parentPropName}"]`
    );
    checkboxes.forEach(cb => cb.checked = checked);
}

function updateNestedSelectAllState(toolIndex, parentPropName) {
    const checkboxes = document.querySelectorAll(
        `.nested-prop-checkbox[data-tool-index="${toolIndex}"][data-parent-prop="${parentPropName}"]`
    );
    const selectAllId = `nested-select-all-${toolIndex}-${parentPropName.replace(/[^a-zA-Z0-9]/g, '_')}`;
    const selectAllCheckbox = document.getElementById(selectAllId);

    if (selectAllCheckbox && checkboxes.length > 0) {
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);
        const someChecked = Array.from(checkboxes).some(cb => cb.checked);
        selectAllCheckbox.checked = allChecked;
        selectAllCheckbox.indeterminate = someChecked && !allChecked;
    }
}

function removeSelectedNestedProperties(toolIndex, parentPropName) {
    const checkboxes = document.querySelectorAll(
        `.nested-prop-checkbox[data-tool-index="${toolIndex}"][data-parent-prop="${parentPropName}"]:checked`
    );

    if (checkboxes.length === 0) {
        showNotification('No properties selected', 'warning');
        return;
    }

    const selectedProps = Array.from(checkboxes).map(cb => cb.dataset.nestedProp);

    if (confirm(`Remove ${selectedProps.length} nested properties?\n\n${selectedProps.join(', ')}`)) {
        const tool = tools[toolIndex];
        const toolName = tool.name;

        // Check if parent is in inputSchema or internalArgs
        let parentProp = tool.inputSchema.properties?.[parentPropName];
        let isInternal = false;

        if (!parentProp && internalArgs[toolName]?.[parentPropName]) {
            parentProp = internalArgs[toolName][parentPropName].original_schema;
            isInternal = true;
        }

        if (parentProp && parentProp.properties) {
            selectedProps.forEach(nestedPropName => {
                delete parentProp.properties[nestedPropName];

                // Remove from required array if present
                if (parentProp.required) {
                    parentProp.required = parentProp.required.filter(r => r !== nestedPropName);
                }
            });

            // Sync parent's default value with nested properties' defaults
            syncNestedPropertiesToDefault(toolIndex, parentPropName);

            showNotification(`Removed ${selectedProps.length} nested properties`, 'info');
            renderToolEditor(tool, toolIndex);
        }
    }
}

function removeNestedPropertyInline(toolIndex, parentPropName, nestedPropName) {
    if (confirm(`Remove nested property "${nestedPropName}" from "${parentPropName}"?`)) {
        const tool = tools[toolIndex];
        const toolName = tool.name;

        // Check if parent is in inputSchema or internalArgs
        let parentProp = tool.inputSchema.properties?.[parentPropName];
        let isInternal = false;

        if (!parentProp && internalArgs[toolName]?.[parentPropName]) {
            parentProp = internalArgs[toolName][parentPropName].original_schema;
            isInternal = true;
        }

        if (parentProp && parentProp.properties) {
            delete parentProp.properties[nestedPropName];

            // Remove from required array if present
            if (parentProp.required) {
                parentProp.required = parentProp.required.filter(r => r !== nestedPropName);
            }

            // Sync parent's default value with nested properties' defaults
            syncNestedPropertiesToDefault(toolIndex, parentPropName);

            showNotification(`Nested property "${nestedPropName}" removed`, 'info');
            renderToolEditor(tool, toolIndex);
        }
    }
}

function toggleNestedRequired(toolIndex, parentPropName, nestedPropName, isChecked) {
    const tool = tools[toolIndex];
    const toolName = tool.name;
    const internalArg = internalArgs[toolName]?.[parentPropName];
    const isInternal = !tool.inputSchema.properties[parentPropName] && internalArg;
    let parentProp = tool.inputSchema.properties[parentPropName];

    if (isInternal) {
        if (!internalArg.original_schema) {
            internalArg.original_schema = {type: 'object', properties: {}, required: []};
        }
        parentProp = internalArg.original_schema;
    }

    if (parentProp) {
        if (!parentProp.required) {
            parentProp.required = [];
        }

        if (isChecked) {
            if (!parentProp.required.includes(nestedPropName)) {
                parentProp.required.push(nestedPropName);
            }
        } else {
            parentProp.required = parentProp.required.filter(r => r !== nestedPropName);
        }

        // Auto-check parent property as required if any nested property is required
        if (parentProp.required.length > 0) {
            if (!tool.inputSchema.required) {
                tool.inputSchema.required = [];
            }
            if (!tool.inputSchema.required.includes(parentPropName)) {
                tool.inputSchema.required.push(parentPropName);
            }
        } else {
            // Uncheck parent if no nested properties are required
            if (tool.inputSchema.required) {
                tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== parentPropName);
            }
        }

        renderToolEditor(tool, toolIndex);
    }
}

function updateNestedPropertyType(toolIndex, parentPropName, nestedPropName, newType) {
    const tool = tools[toolIndex];
    const toolName = tool.name;
    const internalArg = internalArgs[toolName]?.[parentPropName];
    const isInternal = !tool.inputSchema.properties[parentPropName] && internalArg;
    let parentProp = tool.inputSchema.properties[parentPropName];

    if (isInternal) {
        if (!internalArg.original_schema) {
            internalArg.original_schema = {type: 'object', properties: {}, required: []};
        }
        parentProp = internalArg.original_schema;
    }

    if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
        parentProp.properties[nestedPropName].type = newType;
        // Clear type-specific properties when type changes
        delete parentProp.properties[nestedPropName].items;
        delete parentProp.properties[nestedPropName].enum;
        delete parentProp.properties[nestedPropName].properties;
    }
}

function updateNestedPropertyDescription(toolIndex, parentPropName, nestedPropName, description) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        // Update original_schema.properties in internalArgs
        const internalArg = internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            internalArg.original_schema.properties[nestedPropName].description = description;
        }
    } else {
        // Normal signature property - update inputSchema
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            parentProp.properties[nestedPropName].description = description;
        }
    }
}

function updateNestedPropertyDefault(toolIndex, parentPropName, nestedPropName, defaultValue) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        // Update original_schema.properties in internalArgs
        const internalArg = internalArgs[toolName][parentPropName];
        // Ensure original_schema and properties structure exists
        if (!internalArg.original_schema) {
            internalArg.original_schema = { type: 'object', properties: {} };
        }
        if (!internalArg.original_schema.properties) {
            internalArg.original_schema.properties = {};
        }
        if (!internalArg.original_schema.properties[nestedPropName]) {
            internalArg.original_schema.properties[nestedPropName] = { type: 'string' };
        }
        if (defaultValue === undefined) {
            delete internalArg.original_schema.properties[nestedPropName].default;
        } else {
            internalArg.original_schema.properties[nestedPropName].default = defaultValue;
        }
    } else {
        // Normal signature property - update inputSchema
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            if (defaultValue === undefined) {
                delete parentProp.properties[nestedPropName].default;
            } else {
                parentProp.properties[nestedPropName].default = defaultValue;
            }
        }
    }

    // Sync parent's default value with nested properties' defaults
    syncNestedPropertiesToDefault(toolIndex, parentPropName);
}

function updateNestedPropertyFormat(toolIndex, parentPropName, nestedPropName, format) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        // Update original_schema.properties in internalArgs
        const internalArg = internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            if (format) {
                internalArg.original_schema.properties[nestedPropName].format = format;
            } else {
                delete internalArg.original_schema.properties[nestedPropName].format;
            }
        }
    } else {
        // Normal signature property - update inputSchema
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            if (format) {
                parentProp.properties[nestedPropName].format = format;
            } else {
                delete parentProp.properties[nestedPropName].format;
            }
        }
    }
}

function updateNestedPropertyEnum(toolIndex, parentPropName, nestedPropName, enumString) {
    const tool = tools[toolIndex];
    const toolName = tool.name;
    const enumValues = enumString.split(',').map(v => v.trim()).filter(v => v);

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        // Update original_schema.properties in internalArgs
        const internalArg = internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            if (enumValues.length > 0) {
                internalArg.original_schema.properties[nestedPropName].enum = enumValues;
            } else {
                delete internalArg.original_schema.properties[nestedPropName].enum;
            }
        }
    } else {
        // Normal signature property - update inputSchema
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            if (enumValues.length > 0) {
                parentProp.properties[nestedPropName].enum = enumValues;
            } else {
                delete parentProp.properties[nestedPropName].enum;
            }
        }
    }
}

function toggleNestedEnum(toolIndex, parentPropName, nestedPropName, hasEnum) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        // Update original_schema.properties in internalArgs
        const internalArg = internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            if (hasEnum) {
                internalArg.original_schema.properties[nestedPropName].enum = [];
            } else {
                delete internalArg.original_schema.properties[nestedPropName].enum;
            }
            renderToolEditor(tool, toolIndex);
        }
    } else {
        // Normal signature property - update inputSchema
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            if (hasEnum) {
                parentProp.properties[nestedPropName].enum = [];
            } else {
                delete parentProp.properties[nestedPropName].enum;
            }
            renderToolEditor(tool, toolIndex);
        }
    }
}

function updateNestedPropertyItems(toolIndex, parentPropName, nestedPropName, itemType) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        // Update original_schema.properties in internalArgs
        const internalArg = internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            internalArg.original_schema.properties[nestedPropName].items = { type: itemType };
        }
    } else {
        // Normal signature property - update inputSchema
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            parentProp.properties[nestedPropName].items = { type: itemType };
        }
    }
}

function addNewTool() {
    const newTool = {
        name: 'new_tool_' + Date.now(),
        description: 'New tool description',
        mcp_service: '',  // Add mcp_service field
        inputSchema: {
            type: 'object',
            properties: {},
            required: []
        }
    };
    tools.push(newTool);
    renderToolList();
    selectTool(tools.length - 1);
}

function deleteTool(index) {
    if (confirm(`Delete tool "${tools[index].name}"?`)) {
        const profileQuery = profileParam();
        fetch(`/api/tools/${index}${profileQuery}`, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(data.message + (data.backup ? ` (Backup: ${data.backup})` : ''), 'success');
                tools.splice(index, 1);
                currentToolIndex = -1;
                renderToolList();
                document.getElementById('editorContent').innerHTML = `
                    <div style="text-align: center; padding: 50px; color: var(--text-secondary);">
                        Select a tool from the left sidebar to edit
                    </div>
                `;
            } else {
                showNotification(`Error deleting tool: ${data.error}`, 'error');
            }
        })
        .catch(error => {
            console.error('Error deleting tool:', error);
            showNotification('Failed to delete tool', 'error');
        });
    }
}

function saveTools() {
    console.log('[DEBUG] saveTools() called');
    console.log('[DEBUG] tools:', tools);
    console.log('[DEBUG] internalArgs:', internalArgs);
    console.log('[DEBUG] signatureDefaults:', signatureDefaults);
    console.log('[DEBUG] fileMtimes:', fileMtimes);

    const profileQuery = profileParam();
    const saveProfile = originalProfile || 'default';
    const saveButton = document.querySelector('[data-debug-id="BTN_SAVE"]');
    const saveLabel = saveButton ? saveButton.innerHTML : '';
    console.log('[DEBUG] profileQuery:', profileQuery);
    console.log('[DEBUG] saveProfile:', saveProfile);

    // Use the new save-all API to atomically save tools + internal_args + signature_defaults
    const url = `/api/tools/save-all${profileQuery}`;
    const payload = {
        tools: tools,
        internal_args: internalArgs,
        signature_defaults: signatureDefaults,  // Signature params with internal defaults
        file_mtimes: fileMtimes  // For conflict detection
    };

    console.log('[DEBUG] Request URL:', url);
    try {
        console.log('[DEBUG] Request payload:', JSON.stringify(payload, null, 2));
    } catch (error) {
        console.warn('[DEBUG] Request payload serialization failed:', error);
    }

    let payloadJson = '';
    try {
        payloadJson = JSON.stringify(payload);
    } catch (error) {
        console.error('Error serializing save payload:', error);
        showNotification(`Failed to serialize tools: ${error.message}`, 'error');
        return;
    }

    if (saveButton) {
        saveButton.disabled = true;
        saveButton.innerHTML = '<span class="material-icons">save</span> Saving...';
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: payloadJson
    })
    .then(response => {
        console.log('[DEBUG] Response status:', response.status);
        console.log('[DEBUG] Response headers:', response.headers);

        if (response.status === 409) {
            // Conflict detected
            return response.json().then(data => {
                console.log('[DEBUG] Conflict data:', data);
                showNotification(`${data.message}. Please reload and try again.`, 'error');
                throw new Error('Conflict');
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('[DEBUG] Response data:', data);

        if (data.success) {
            const savedInfo = Array.isArray(data.saved) ? data.saved.join(', ') : 'files';
            showNotification(`Saved: ${savedInfo} to "${saveProfile}"!`, 'success');
            // Update file mtimes after successful save
            loadTools();  // Reload to get fresh mtimes
        } else {
            showNotification(`Error saving: ${data.error || 'Unknown error'}`, 'error');
        }
    })
    .catch(error => {
        console.error('[DEBUG] Catch block error:', error);
        if (error.message !== 'Conflict') {
            console.error('Error saving:', error);
            showNotification('Failed to save', 'error');
        }
    })
    .finally(() => {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.innerHTML = saveLabel || '<span class="material-icons">save</span>';
        }
    });
}

function validateTools() {
    const profileQuery = profileParam();
    fetch(`/api/tools/validate${profileQuery}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(tools)
    })
    .then(response => response.json())
    .then(data => {
        if (data.valid) {
            showNotification('Tools are valid!', 'success');
        } else {
            showNotification(`Validation error: ${data.error}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error validating tools:', error);
        showNotification('Failed to validate tools', 'error');
    });
}

function showBackups() {
    const profileQuery = profileParam();
    fetch(`/api/backups${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            const backupList = document.getElementById('backupList');
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
            document.getElementById('backupModal').classList.add('show');
        })
        .catch(error => {
            console.error('Error loading backups:', error);
            showNotification('Failed to load backups', 'error');
        });
}

function viewBackup(filename) {
    const profileQuery = profileParam();
    fetch(`/api/backups/${filename}${profileQuery}`)
        .then(response => response.json())
        .then(data => {
            alert(JSON.stringify(data, null, 2));
        })
        .catch(error => {
            console.error('Error viewing backup:', error);
            showNotification('Failed to view backup', 'error');
        });
}

function restoreBackup(filename) {
    if (confirm(`Restore backup from ${filename}? Current state will be backed up first.`)) {
        const profileQuery = profileParam();
        fetch(`/api/backups/${filename}/restore${profileQuery}`, {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(`Backup restored successfully! Current state backed up as: ${data.current_backup}`, 'success');
                closeModal('backupModal');
                loadTools();
            } else {
                showNotification(`Error restoring backup: ${data.error}`, 'error');
            }
        })
        .catch(error => {
            console.error('Error restoring backup:', error);
            showNotification('Failed to restore backup', 'error');
        });
    }
}

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

// ============================================================
// Sync Nested Properties with Default Value
// ============================================================

/**
 * Synchronize the parent property's default value with its nested properties' defaults
 * When a nested property default changes, update the parent's default JSON accordingly
 */
function syncNestedPropertiesToDefault(toolIndex, parentPropName) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Check if this is an internal property
    const isInternal = !tool.inputSchema.properties?.[parentPropName] &&
                       internalArgs[toolName]?.[parentPropName];

    let propDef;
    if (isInternal) {
        propDef = internalArgs[toolName][parentPropName].original_schema;
    } else {
        propDef = tool.inputSchema.properties?.[parentPropName];
    }

    if (!propDef || propDef.type !== 'object' || !propDef.properties) {
        return;
    }

    // Build default value from nested properties' defaults
    const defaultObj = {};
    let hasAnyDefault = false;

    for (const [nestedName, nestedProp] of Object.entries(propDef.properties)) {
        if (nestedProp.default !== undefined) {
            defaultObj[nestedName] = nestedProp.default;
            hasAnyDefault = true;
        }
    }

    // Update parent's default value
    if (hasAnyDefault) {
        propDef.default = defaultObj;
    } else {
        delete propDef.default;
    }

    // Update the appropriate location
    if (isInternal) {
        internalArgs[toolName][parentPropName].original_schema = propDef;
    } else {
        tool.inputSchema.properties[parentPropName] = propDef;
    }
}

// ============================================================
// Copy/Paste Nested Properties Functions
// ============================================================

/**
 * Copy nested properties structure from JSON default value to clipboard
 * This exports the nested properties as a JSON schema that can be pasted to another property
 */
function copyNestedFromDefault(toolIndex, propName) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Get property definition
    let propDef = tool.inputSchema.properties?.[propName];
    if (!propDef && internalArgs[toolName]?.[propName]) {
        propDef = internalArgs[toolName][propName].original_schema;
    }

    if (!propDef || propDef.type !== 'object') {
        showNotification('Property must be of type object', 'warning');
        return;
    }

    // Build nested properties schema from existing nested properties
    const nestedSchema = {
        properties: {},
        required: []
    };

    if (propDef.properties) {
        for (const [nestedName, nestedProp] of Object.entries(propDef.properties)) {
            nestedSchema.properties[nestedName] = {
                type: nestedProp.type || 'string',
                description: nestedProp.description || ''
            };
            if (nestedProp.default !== undefined) {
                nestedSchema.properties[nestedName].default = nestedProp.default;
            }
            if (nestedProp.enum) {
                nestedSchema.properties[nestedName].enum = nestedProp.enum;
            }
            if (nestedProp.format) {
                nestedSchema.properties[nestedName].format = nestedProp.format;
            }
            if (nestedProp.items) {
                nestedSchema.properties[nestedName].items = nestedProp.items;
            }
        }
        if (propDef.required && propDef.required.length > 0) {
            nestedSchema.required = [...propDef.required];
        }
    }

    // Also check if there's a default JSON value and try to infer schema from it
    if (propDef.default && typeof propDef.default === 'object' && !Array.isArray(propDef.default)) {
        for (const [key, value] of Object.entries(propDef.default)) {
            if (!nestedSchema.properties[key]) {
                // Infer type from default value
                let inferredType = typeof value;
                if (inferredType === 'object') {
                    inferredType = Array.isArray(value) ? 'array' : 'object';
                }
                nestedSchema.properties[key] = {
                    type: inferredType,
                    description: '',
                    default: value
                };
            }
        }
    }

    if (Object.keys(nestedSchema.properties).length === 0) {
        showNotification('No nested properties to copy', 'warning');
        return;
    }

    const jsonStr = JSON.stringify(nestedSchema, null, 2);

    navigator.clipboard.writeText(jsonStr).then(() => {
        showNotification(`Copied ${Object.keys(nestedSchema.properties).length} nested properties to clipboard`, 'success');
    }).catch(err => {
        console.error('Failed to copy:', err);
        // Fallback: show in alert
        prompt('Copy this JSON (Ctrl+C):', jsonStr);
    });
}

/**
 * Paste nested properties from clipboard JSON to a property
 * This imports a JSON schema as nested properties
 */
async function pasteNestedFromClipboard(toolIndex, propName) {
    const tool = tools[toolIndex];
    const toolName = tool.name;

    // Get property definition
    let propDef = tool.inputSchema.properties?.[propName];
    let isInternal = false;

    if (!propDef && internalArgs[toolName]?.[propName]) {
        propDef = internalArgs[toolName][propName].original_schema;
        isInternal = true;
    }

    if (!propDef || propDef.type !== 'object') {
        showNotification('Property must be of type object', 'warning');
        return;
    }

    let clipboardText;
    try {
        clipboardText = await navigator.clipboard.readText();
    } catch (err) {
        // Fallback: prompt for input
        clipboardText = prompt('Paste nested properties JSON:');
        if (!clipboardText) return;
    }

    let nestedSchema;
    try {
        nestedSchema = JSON.parse(clipboardText);
    } catch (err) {
        showNotification('Invalid JSON in clipboard', 'error');
        return;
    }

    // Validate structure
    if (!nestedSchema.properties || typeof nestedSchema.properties !== 'object') {
        // Try to interpret as a simple object with property values
        if (typeof nestedSchema === 'object' && !Array.isArray(nestedSchema)) {
            // Convert simple object to schema
            const convertedSchema = { properties: {}, required: [] };
            for (const [key, value] of Object.entries(nestedSchema)) {
                if (typeof value === 'object' && value !== null && value.type) {
                    // Already a schema definition
                    convertedSchema.properties[key] = value;
                } else {
                    // Infer from value
                    let inferredType = typeof value;
                    if (inferredType === 'object') {
                        inferredType = Array.isArray(value) ? 'array' : 'object';
                    }
                    convertedSchema.properties[key] = {
                        type: inferredType,
                        description: '',
                        default: value
                    };
                }
            }
            nestedSchema = convertedSchema;
        } else {
            showNotification('Invalid nested properties schema format', 'error');
            return;
        }
    }

    const propCount = Object.keys(nestedSchema.properties).length;
    if (propCount === 0) {
        showNotification('No properties found in pasted JSON', 'warning');
        return;
    }

    // Confirm before overwriting
    const existingCount = propDef.properties ? Object.keys(propDef.properties).length : 0;
    let confirmMsg = `Import ${propCount} nested properties?`;
    if (existingCount > 0) {
        confirmMsg = `Import ${propCount} nested properties?\nThis will merge with existing ${existingCount} properties.`;
    }

    if (!confirm(confirmMsg)) return;

    // Initialize properties if not exist
    if (!propDef.properties) {
        propDef.properties = {};
    }
    if (!propDef.required) {
        propDef.required = [];
    }

    // Merge nested properties
    for (const [nestedName, nestedProp] of Object.entries(nestedSchema.properties)) {
        propDef.properties[nestedName] = {
            type: nestedProp.type || 'string',
            description: nestedProp.description || ''
        };
        if (nestedProp.default !== undefined) {
            propDef.properties[nestedName].default = nestedProp.default;
        }
        if (nestedProp.enum) {
            propDef.properties[nestedName].enum = nestedProp.enum;
        }
        if (nestedProp.format) {
            propDef.properties[nestedName].format = nestedProp.format;
        }
        if (nestedProp.items) {
            propDef.properties[nestedName].items = nestedProp.items;
        }
    }

    // Add required properties
    if (nestedSchema.required && Array.isArray(nestedSchema.required)) {
        for (const reqProp of nestedSchema.required) {
            if (!propDef.required.includes(reqProp) && propDef.properties[reqProp]) {
                propDef.required.push(reqProp);
            }
        }
    }

    // Update the appropriate location
    if (isInternal) {
        internalArgs[toolName][propName].original_schema = propDef;
    } else {
        tool.inputSchema.properties[propName] = propDef;
    }

    // Sync parent's default value with nested properties' defaults
    syncNestedPropertiesToDefault(toolIndex, propName);

    showNotification(`Imported ${propCount} nested properties`, 'success');
    renderToolEditor(tool, toolIndex);
}
