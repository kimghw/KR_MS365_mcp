/**
 * MCP Tool Editor - Actions Module
 * Handles all user actions and event handlers
 *
 * This module contains all functions that handle user interactions,
 * form submissions, and UI state changes.
 * All hardcoded values have been removed and replaced with dynamic references.
 */

// ===== Tool Selection Actions =====

/**
 * Select a tool for editing
 * @param {number} index - Tool index to select
 */
function selectTool(index) {
    MCPEditor.state.currentToolIndex = index;

    if (window.MCPEditorUI) {
        if (window.MCPEditorUI.renderToolList) {
            window.MCPEditorUI.renderToolList();
        }
        if (window.renderToolEditor) {
            renderToolEditor(MCPEditor.state.tools[index], index);
        }
    }
}

/**
 * Add a new tool
 */
function addNewTool() {
    const newTool = {
        name: 'new_tool_' + Date.now(),
        description: 'New tool description',
        mcp_service: '',
        inputSchema: {
            type: 'object',
            properties: {},
            required: []
        }
    };

    MCPEditor.state.tools.push(newTool);

    if (window.MCPEditorUI && window.MCPEditorUI.renderToolList) {
        window.MCPEditorUI.renderToolList();
    }

    selectTool(MCPEditor.state.tools.length - 1);
}

// ===== Tool Field Update Actions =====

/**
 * Update a tool field
 * @param {number} index - Tool index
 * @param {string} field - Field name
 * @param {*} value - New value
 */
function updateToolField(index, field, value) {
    const tool = MCPEditor.state.tools[index];
    if (!tool) return;

    tool[field] = value;
}

/**
 * Update MCP service for a tool
 * @param {number} index - Tool index
 * @param {string} value - Service name
 */
function updateMcpService(index, value) {
    updateToolField(index, 'mcp_service', value);

    if (window.applySignatureDefaults) {
        applySignatureDefaults(index, value);
    }

    if (window.renderToolEditor) {
        renderToolEditor(MCPEditor.state.tools[index], index);
    }
}

// ===== Property Management Actions =====

/**
 * Update a property field
 */
function updatePropertyField(index, propName, field, value) {
    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;

    // Check if this property is internal
    const isInternal = !tool.inputSchema.properties[propName] &&
                       MCPEditor.state.internalArgs[toolName]?.[propName];

    if (isInternal) {
        // Update original_schema in internalArgs
        if (!MCPEditor.state.internalArgs[toolName][propName].original_schema) {
            MCPEditor.state.internalArgs[toolName][propName].original_schema = {};
        }
        MCPEditor.state.internalArgs[toolName][propName].original_schema[field] = value;

        // Update main internal arg fields
        if (field === 'description') {
            MCPEditor.state.internalArgs[toolName][propName].description = value;
        }
        if (field === 'type') {
            if (!MCPEditor.state.internalArgs[toolName][propName].original_schema?.baseModel) {
                MCPEditor.state.internalArgs[toolName][propName].type = value;
            }
        }
        if (field === 'targetParam') {
            if (value) {
                MCPEditor.state.internalArgs[toolName][propName].targetParam = value;
            } else {
                delete MCPEditor.state.internalArgs[toolName][propName].targetParam;
            }
        }
    } else {
        // Normal signature property - update inputSchema
        if (!tool.inputSchema.properties[propName]) {
            tool.inputSchema.properties[propName] = {};
        }
        tool.inputSchema.properties[propName][field] = value;
    }

    // If targetParam changed, update service method params display
    if (field === 'targetParam' && window.loadAndDisplayServiceMethodParams) {
        loadAndDisplayServiceMethodParams(index);
    }
}

/**
 * Set property destination (signature vs internal)
 */
function setPropertyDestination(index, propName, destination) {
    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;
    const propDef = tool.inputSchema?.properties?.[propName];
    const existingInternal = MCPEditor.state.internalArgs[toolName]?.[propName];

    if (destination === 'internal') {
        // Move to Internal
        if (existingInternal && !propDef) {
            console.log('Property already internal:', propName);
            return;
        }
        if (!propDef) {
            console.error('Property not found in inputSchema:', propName);
            return;
        }

        if (!MCPEditor.state.internalArgs[toolName]) {
            MCPEditor.state.internalArgs[toolName] = {};
        }

        const wasRequired = (tool.inputSchema.required || []).includes(propName);
        MCPEditor.state.internalArgs[toolName][propName] = {
            type: propDef.baseModel || propDef.type,
            description: propDef.description || '',
            original_schema: JSON.parse(JSON.stringify(propDef)),
            was_required: wasRequired
        };

        // Remove from inputSchema
        delete tool.inputSchema.properties[propName];
        if (tool.inputSchema.required) {
            tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== propName);
        }

        MCPEditor.showNotification(`Property "${propName}" moved to Internal (removed from MCP signature)`, 'info');
    } else {
        // Move to Signature
        if (!existingInternal) {
            console.error('No internal arg found to restore:', propName);
            return;
        }

        // Restore from internalArgs
        if (existingInternal.original_schema) {
            tool.inputSchema.properties[propName] = JSON.parse(JSON.stringify(existingInternal.original_schema));
        } else {
            tool.inputSchema.properties[propName] = {
                type: existingInternal.type === 'object' ? 'object' : existingInternal.type,
                description: existingInternal.description || ''
            };
        }

        // Restore required status
        if (existingInternal.was_required) {
            if (!tool.inputSchema.required) {
                tool.inputSchema.required = [];
            }
            if (!tool.inputSchema.required.includes(propName)) {
                tool.inputSchema.required.push(propName);
            }
        }

        delete MCPEditor.state.internalArgs[toolName][propName];
        if (Object.keys(MCPEditor.state.internalArgs[toolName]).length === 0) {
            delete MCPEditor.state.internalArgs[toolName];
        }

        MCPEditor.showNotification(`Property "${propName}" restored to Signature`, 'info');
    }

    // Re-render
    if (window.renderToolEditor) {
        renderToolEditor(tool, index);
    }
}

/**
 * Toggle required status for a property
 */
function toggleRequired(index, propName, isChecked) {
    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[propName] &&
                       MCPEditor.state.internalArgs[toolName]?.[propName];

    if (isInternal) {
        MCPEditor.state.internalArgs[toolName][propName].was_required = isChecked;
    } else {
        if (!tool.inputSchema.required) {
            tool.inputSchema.required = [];
        }

        if (isChecked) {
            if (!tool.inputSchema.required.includes(propName)) {
                tool.inputSchema.required.push(propName);
            }
            // Required property cannot have default value
            if (tool.inputSchema.properties[propName]) {
                delete tool.inputSchema.properties[propName].default;
            }
        } else {
            tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== propName);
        }
    }

    if (window.renderToolEditor) {
        renderToolEditor(tool, index);
    }
}

/**
 * Remove a property
 */
function removeProperty(index, propName) {
    if (!confirm(`Remove property "${propName}"?`)) return;

    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;

    // Remove from inputSchema
    delete tool.inputSchema.properties[propName];
    if (tool.inputSchema.required) {
        tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== propName);
    }

    // Remove from internalArgs
    if (MCPEditor.state.internalArgs[toolName]?.[propName]) {
        delete MCPEditor.state.internalArgs[toolName][propName];
        if (Object.keys(MCPEditor.state.internalArgs[toolName]).length === 0) {
            delete MCPEditor.state.internalArgs[toolName];
        }
        MCPEditor.showNotification(`Property "${propName}" removed from both schema and internal args`, 'info');
    }

    if (window.renderToolEditor) {
        renderToolEditor(tool, index);
    }
}

/**
 * Rename a schema property
 */
function renameSchemaProperty(index, oldName, newName, inputElement) {
    newName = newName.trim();

    if (oldName === newName) return;

    if (!newName) {
        MCPEditor.showNotification('Property name cannot be empty', 'error');
        inputElement.value = oldName;
        return;
    }

    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(newName)) {
        MCPEditor.showNotification('Property name must start with a letter or underscore and contain only alphanumeric characters and underscores', 'error');
        inputElement.value = oldName;
        return;
    }

    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;

    if (tool.inputSchema.properties[newName] && newName !== oldName) {
        MCPEditor.showNotification(`Property "${newName}" already exists`, 'error');
        inputElement.value = oldName;
        return;
    }

    const isInternal = !tool.inputSchema.properties[oldName] && MCPEditor.state.internalArgs[toolName]?.[oldName];

    if (isInternal) {
        if (MCPEditor.state.internalArgs[toolName]?.[oldName]) {
            MCPEditor.state.internalArgs[toolName][newName] = MCPEditor.state.internalArgs[toolName][oldName];
            delete MCPEditor.state.internalArgs[toolName][oldName];
        }
    } else {
        if (tool.inputSchema.properties[oldName]) {
            tool.inputSchema.properties[newName] = tool.inputSchema.properties[oldName];
            delete tool.inputSchema.properties[oldName];

            if (tool.inputSchema.required) {
                const reqIndex = tool.inputSchema.required.indexOf(oldName);
                if (reqIndex !== -1) {
                    tool.inputSchema.required[reqIndex] = newName;
                }
            }
        }
    }

    inputElement.dataset.originalName = newName;

    if (window.renderToolEditor) {
        renderToolEditor(tool, index);
    }

    MCPEditor.showNotification(`Property renamed from "${oldName}" to "${newName}"`, 'success');
}

/**
 * Update property enum values
 */
function updatePropertyEnum(index, propName, value) {
    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;
    const enumValues = value.split(',').map(v => v.trim()).filter(v => v);

    const isInternal = !tool.inputSchema.properties[propName] &&
                       MCPEditor.state.internalArgs[toolName]?.[propName];

    if (isInternal) {
        if (!MCPEditor.state.internalArgs[toolName][propName].original_schema) {
            MCPEditor.state.internalArgs[toolName][propName].original_schema = {};
        }
        MCPEditor.state.internalArgs[toolName][propName].original_schema.enum = enumValues;
    } else {
        tool.inputSchema.properties[propName].enum = enumValues;
    }
}

/**
 * Toggle enum for a property
 */
function toggleEnum(index, propName, hasEnum) {
    const tool = MCPEditor.state.tools[index];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[propName] &&
                       MCPEditor.state.internalArgs[toolName]?.[propName];

    if (isInternal) {
        if (!MCPEditor.state.internalArgs[toolName][propName].original_schema) {
            MCPEditor.state.internalArgs[toolName][propName].original_schema = {};
        }
        if (hasEnum) {
            MCPEditor.state.internalArgs[toolName][propName].original_schema.enum = [];
        } else {
            delete MCPEditor.state.internalArgs[toolName][propName].original_schema.enum;
        }
    } else {
        if (hasEnum) {
            tool.inputSchema.properties[propName].enum = [];
        } else {
            delete tool.inputSchema.properties[propName].enum;
        }
    }

    if (window.renderToolEditor) {
        renderToolEditor(tool, index);
    }
}

// ===== Nested Property Actions =====

/**
 * Toggle all nested checkboxes
 */
function toggleAllNestedCheckboxes(toolIndex, parentPropName, checked) {
    const checkboxes = document.querySelectorAll(
        `.nested-prop-checkbox[data-tool-index="${toolIndex}"][data-parent-prop="${parentPropName}"]`
    );
    checkboxes.forEach(cb => cb.checked = checked);
}

/**
 * Update nested select all state
 */
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

/**
 * Remove selected nested properties
 */
function removeSelectedNestedProperties(toolIndex, parentPropName) {
    const checkboxes = document.querySelectorAll(
        `.nested-prop-checkbox[data-tool-index="${toolIndex}"][data-parent-prop="${parentPropName}"]:checked`
    );

    if (checkboxes.length === 0) {
        MCPEditor.showNotification('No properties selected', 'warning');
        return;
    }

    const selectedProps = Array.from(checkboxes).map(cb => cb.dataset.nestedProp);

    if (!confirm(`Remove ${selectedProps.length} nested properties?\n\n${selectedProps.join(', ')}`)) {
        return;
    }

    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    let parentProp = tool.inputSchema.properties?.[parentPropName];

    if (!parentProp && MCPEditor.state.internalArgs[toolName]?.[parentPropName]) {
        parentProp = MCPEditor.state.internalArgs[toolName][parentPropName].original_schema;
    }

    if (parentProp && parentProp.properties) {
        selectedProps.forEach(nestedPropName => {
            delete parentProp.properties[nestedPropName];

            if (parentProp.required) {
                parentProp.required = parentProp.required.filter(r => r !== nestedPropName);
            }
        });

        MCPEditor.showNotification(`Removed ${selectedProps.length} nested properties`, 'info');

        if (window.renderToolEditor) {
            renderToolEditor(tool, toolIndex);
        }
    }
}

/**
 * Remove nested property inline
 */
function removeNestedPropertyInline(toolIndex, parentPropName, nestedPropName) {
    if (!confirm(`Remove nested property "${nestedPropName}" from "${parentPropName}"?`)) {
        return;
    }

    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    let parentProp = tool.inputSchema.properties?.[parentPropName];

    if (!parentProp && MCPEditor.state.internalArgs[toolName]?.[parentPropName]) {
        parentProp = MCPEditor.state.internalArgs[toolName][parentPropName].original_schema;
    }

    if (parentProp && parentProp.properties) {
        delete parentProp.properties[nestedPropName];

        if (parentProp.required) {
            parentProp.required = parentProp.required.filter(r => r !== nestedPropName);
        }

        MCPEditor.showNotification(`Nested property "${nestedPropName}" removed`, 'info');

        if (window.renderToolEditor) {
            renderToolEditor(tool, toolIndex);
        }
    }
}

/**
 * Toggle nested required status
 */
function toggleNestedRequired(toolIndex, parentPropName, nestedPropName, isChecked) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;
    const internalArg = MCPEditor.state.internalArgs[toolName]?.[parentPropName];
    const isInternal = !tool.inputSchema.properties[parentPropName] && internalArg;

    let parentProp = tool.inputSchema.properties[parentPropName];

    if (isInternal) {
        if (!internalArg.original_schema) {
            internalArg.original_schema = { type: 'object', properties: {}, required: [] };
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

        if (window.renderToolEditor) {
            renderToolEditor(tool, toolIndex);
        }
    }
}

/**
 * Update nested property type
 */
function updateNestedPropertyType(toolIndex, parentPropName, nestedPropName, newType) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;
    const internalArg = MCPEditor.state.internalArgs[toolName]?.[parentPropName];
    const isInternal = !tool.inputSchema.properties[parentPropName] && internalArg;

    let parentProp = tool.inputSchema.properties[parentPropName];

    if (isInternal) {
        if (!internalArg.original_schema) {
            internalArg.original_schema = { type: 'object', properties: {}, required: [] };
        }
        parentProp = internalArg.original_schema;
    }

    if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
        parentProp.properties[nestedPropName].type = newType;
        delete parentProp.properties[nestedPropName].items;
        delete parentProp.properties[nestedPropName].enum;
        delete parentProp.properties[nestedPropName].properties;
    }
}

/**
 * Update nested property description
 */
function updateNestedPropertyDescription(toolIndex, parentPropName, nestedPropName, description) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       MCPEditor.state.internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        const internalArg = MCPEditor.state.internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            internalArg.original_schema.properties[nestedPropName].description = description;
        }
    } else {
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            parentProp.properties[nestedPropName].description = description;
        }
    }
}

/**
 * Update nested property default value
 */
function updateNestedPropertyDefault(toolIndex, parentPropName, nestedPropName, defaultValue) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       MCPEditor.state.internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        const internalArg = MCPEditor.state.internalArgs[toolName][parentPropName];
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
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            if (defaultValue === undefined) {
                delete parentProp.properties[nestedPropName].default;
            } else {
                parentProp.properties[nestedPropName].default = defaultValue;
            }
        }
    }
}

/**
 * Update nested property format
 */
function updateNestedPropertyFormat(toolIndex, parentPropName, nestedPropName, format) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       MCPEditor.state.internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        const internalArg = MCPEditor.state.internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            if (format) {
                internalArg.original_schema.properties[nestedPropName].format = format;
            } else {
                delete internalArg.original_schema.properties[nestedPropName].format;
            }
        }
    } else {
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

/**
 * Update nested property enum
 */
function updateNestedPropertyEnum(toolIndex, parentPropName, nestedPropName, enumString) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;
    const enumValues = enumString.split(',').map(v => v.trim()).filter(v => v);

    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       MCPEditor.state.internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        const internalArg = MCPEditor.state.internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            if (enumValues.length > 0) {
                internalArg.original_schema.properties[nestedPropName].enum = enumValues;
            } else {
                delete internalArg.original_schema.properties[nestedPropName].enum;
            }
        }
    } else {
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

/**
 * Toggle nested enum
 */
function toggleNestedEnum(toolIndex, parentPropName, nestedPropName, hasEnum) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       MCPEditor.state.internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        const internalArg = MCPEditor.state.internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            if (hasEnum) {
                internalArg.original_schema.properties[nestedPropName].enum = [];
            } else {
                delete internalArg.original_schema.properties[nestedPropName].enum;
            }
            if (window.renderToolEditor) {
                renderToolEditor(tool, toolIndex);
            }
        }
    } else {
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            if (hasEnum) {
                parentProp.properties[nestedPropName].enum = [];
            } else {
                delete parentProp.properties[nestedPropName].enum;
            }
            if (window.renderToolEditor) {
                renderToolEditor(tool, toolIndex);
            }
        }
    }
}

/**
 * Update nested property items type
 */
function updateNestedPropertyItems(toolIndex, parentPropName, nestedPropName, itemType) {
    const tool = MCPEditor.state.tools[toolIndex];
    const toolName = tool.name;

    const isInternal = !tool.inputSchema.properties[parentPropName] &&
                       MCPEditor.state.internalArgs[toolName]?.[parentPropName];

    if (isInternal) {
        const internalArg = MCPEditor.state.internalArgs[toolName][parentPropName];
        if (internalArg.original_schema?.properties?.[nestedPropName]) {
            internalArg.original_schema.properties[nestedPropName].items = { type: itemType };
        }
    } else {
        const parentProp = tool.inputSchema.properties[parentPropName];
        if (parentProp && parentProp.properties && parentProp.properties[nestedPropName]) {
            parentProp.properties[nestedPropName].items = { type: itemType };
        }
    }
}

// ===== UI Toggle Actions =====

/**
 * Toggle property collapse
 */
function togglePropertyCollapse(propId) {
    const content = document.getElementById(`content-${propId}`);
    const icon = document.getElementById(`icon-${propId}`);
    const header = document.getElementById(`header-${propId}`);

    if (!content || !icon || !header) return;

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
 * Toggle nested property collapse
 */
function toggleNestedPropCollapse(nestedPropId) {
    const content = document.getElementById(`nested-content-${nestedPropId}`);
    const icon = document.getElementById(`nested-icon-${nestedPropId}`);

    if (!content || !icon) return;

    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.textContent = '▼';
    } else {
        content.style.display = 'none';
        icon.textContent = '▶';
    }
}

/**
 * Toggle JSON view
 */
function toggleJsonView() {
    const viewer = document.getElementById('json-viewer');
    const icon = document.getElementById('json-collapse-icon');

    if (!viewer || !icon) return;

    if (viewer.classList.contains('collapsed')) {
        viewer.classList.remove('collapsed');
        icon.classList.remove('collapsed');
        icon.textContent = '▼';
    } else {
        viewer.classList.add('collapsed');
        icon.classList.add('collapsed');
        icon.textContent = '▶';
    }
}

/**
 * Expand all properties
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
 * Collapse all properties
 */
function collapseAllProperties() {
    const allProperties = document.querySelectorAll('.property-collapse-content');
    const allIcons = document.querySelectorAll('.property-collapse-header .collapse-icon');
    const allHeaders = document.querySelectorAll('.property-collapse-header');

    allProperties.forEach(prop => prop.classList.add('collapsed'));
    allIcons.forEach(icon => { icon.classList.add('collapsed'); icon.textContent = '▶'; });
    allHeaders.forEach(header => header.classList.remove('expanded'));
}

// ===== MCP Server Control Actions =====

/**
 * Start MCP server
 */
async function startServer() {
    const profileQuery = profileParam();
    const btnStart = document.getElementById('btnStart');
    const statusText = document.getElementById('statusText');

    if (btnStart) btnStart.disabled = true;
    if (statusText) {
        statusText.textContent = 'Starting...';
        statusText.style.color = '#ffc107';
    }

    try {
        const response = await fetch(`/api/server/start${profileQuery}`, { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            MCPEditor.showNotification('Server started successfully', 'success');
            await MCPEditor.checkServerStatus();
        } else {
            MCPEditor.showNotification('Failed to start server: ' + (data.error || 'Unknown error'), 'error');
            if (btnStart) btnStart.disabled = false;
            if (statusText) {
                statusText.textContent = 'Stopped';
                statusText.style.color = '#dc3545';
            }
        }
    } catch (error) {
        MCPEditor.showNotification('Error starting server: ' + error.message, 'error');
        if (btnStart) btnStart.disabled = false;
        if (statusText) {
            statusText.textContent = 'Stopped';
            statusText.style.color = '#dc3545';
        }
    }
}

/**
 * Stop MCP server
 */
async function stopServer() {
    const profileQuery = profileParam();
    const btnStop = document.getElementById('btnStop');
    const statusText = document.getElementById('statusText');

    if (btnStop) btnStop.disabled = true;
    if (statusText) {
        statusText.textContent = 'Stopping...';
        statusText.style.color = '#ffc107';
    }

    try {
        const response = await fetch(`/api/server/stop${profileQuery}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: false })
        });

        const data = await response.json();

        if (data.success) {
            MCPEditor.showNotification('Server stopped successfully', 'success');
            await MCPEditor.checkServerStatus();
        } else {
            MCPEditor.showNotification('Failed to stop server: ' + (data.error || 'Unknown error'), 'error');
            if (btnStop) btnStop.disabled = false;
            await MCPEditor.checkServerStatus();
        }
    } catch (error) {
        MCPEditor.showNotification('Error stopping server: ' + error.message, 'error');
        if (btnStop) btnStop.disabled = false;
        await MCPEditor.checkServerStatus();
    }
}

/**
 * Restart MCP server
 */
async function restartServer() {
    const profileQuery = profileParam();
    const btnRestart = document.getElementById('btnRestart');
    const statusText = document.getElementById('statusText');

    if (btnRestart) btnRestart.disabled = true;
    if (statusText) {
        statusText.textContent = 'Restarting...';
        statusText.style.color = '#ffc107';
    }

    try {
        const response = await fetch(`/api/server/restart${profileQuery}`, { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            MCPEditor.showNotification('Server restarted successfully', 'success');
            await MCPEditor.checkServerStatus();
        } else {
            MCPEditor.showNotification('Failed to restart server: ' + (data.error || 'Unknown error'), 'error');
            if (btnRestart) btnRestart.disabled = false;
            await MCPEditor.checkServerStatus();
        }
    } catch (error) {
        MCPEditor.showNotification('Error restarting server: ' + error.message, 'error');
        if (btnRestart) btnRestart.disabled = false;
        await MCPEditor.checkServerStatus();
    }
}

// ===== Generator Actions =====

/**
 * Handle generator module change
 */
function handleGeneratorModuleChange() {
    const select = document.getElementById('generatorModule');
    const moduleName = select ? select.value : '';

    if (window.applyGeneratorDefaults) {
        applyGeneratorDefaults(moduleName);
    }
}

/**
 * Apply generator defaults
 */
function applyGeneratorDefaults(moduleName) {
    const defaults = MCPEditor.state.generatorModules.find(m => m.name === moduleName)
        || MCPEditor.state.generatorFallback
        || {};

    const toolsInput = document.getElementById('generatorToolsPath');
    const templateInput = document.getElementById('generatorTemplatePath');
    const outputInput = document.getElementById('generatorOutputPath');

    if (toolsInput) toolsInput.value = defaults.tools_path || '';
    if (templateInput) templateInput.value = defaults.template_path || '';
    if (outputInput) outputInput.value = defaults.output_path || '';
}

/**
 * Open generator modal
 */
function openGeneratorModal() {
    if (!MCPEditor.state.generatorModules.length && !MCPEditor.state.generatorFallback.tools_path) {
        loadGeneratorDefaults();
    }

    const moduleName = document.getElementById('generatorModule')?.value || '';
    applyGeneratorDefaults(moduleName);

    const resultEl = document.getElementById('generatorResult');
    if (resultEl) resultEl.textContent = '';

    const modal = document.getElementById('generatorModal');
    if (modal) modal.classList.add('show');
}

// ===== File Browser Actions =====

/**
 * Select file path
 */
function selectFilePath(inputId, extension) {
    if (window.showFileBrowser) {
        showFileBrowser(inputId, extension);
    }
}

/**
 * Navigate to directory
 */
function navigateToDir(path, inputId, extension) {
    const pathInput = document.getElementById('fileBrowserPath');
    if (pathInput) pathInput.value = path;
    if (window.browsePath) browsePath(inputId, extension);
}

/**
 * Browse parent directory
 */
function browseParent(inputId, extension) {
    const parentBtn = document.getElementById('parentDirBtn');
    const parentPath = parentBtn?.getAttribute('data-parent-path');

    if (parentPath) {
        const pathInput = document.getElementById('fileBrowserPath');
        if (pathInput) pathInput.value = parentPath;
        if (window.browsePath) browsePath(inputId, extension);
    }
}

/**
 * Select file
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
 * Apply selected file
 */
function applySelectedFile(inputId) {
    const selectedPath = document.getElementById('selectedFilePath')?.value;

    if (selectedPath) {
        const input = document.getElementById(inputId);
        if (input) input.value = selectedPath;
    }

    if (window.closeFileBrowser) closeFileBrowser();
}

/**
 * Close file browser
 */
function closeFileBrowser() {
    const modal = document.getElementById('fileBrowserModal');
    if (modal) modal.remove();
}

// ===== Modal Actions =====

/**
 * Close modal
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
 * Open create project modal
 */
function openCreateProjectModal() {
    // Clear form
    const projectServiceName = document.getElementById('projectServiceName');
    const projectDescription = document.getElementById('projectDescription');
    const projectPort = document.getElementById('projectPort');
    const projectAuthor = document.getElementById('projectAuthor');
    const projectIncludeTypes = document.getElementById('projectIncludeTypes');

    if (projectServiceName) projectServiceName.value = '';
    if (projectDescription) projectDescription.value = '';
    if (projectPort) projectPort.value = '8080';
    if (projectAuthor) projectAuthor.value = '';
    if (projectIncludeTypes) projectIncludeTypes.checked = true;

    // Hide result
    const resultEl = document.getElementById('createProjectResult');
    if (resultEl) {
        resultEl.style.display = 'none';
        resultEl.textContent = '';
    }

    const modal = document.getElementById('createProjectModal');
    if (modal) modal.classList.add('show');
}

/**
 * Show new project modal
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
                <button class="btn btn-secondary" onclick="closeNewProjectModal()">Cancel</button>
                <button class="btn btn-primary" onclick="createNewProject()">Create Project</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) closeNewProjectModal(); };

    const nameInput = document.getElementById('newProjectName');
    if (nameInput) nameInput.focus();
}

/**
 * Close new project modal
 */
function closeNewProjectModal() {
    const modal = document.getElementById('newProjectModal');
    if (modal) modal.remove();
}

// ===== Utility Functions =====

/**
 * Parse default value based on type
 */
function parseDefaultValue(value, type) {
    if (value === '' || value === undefined) return undefined;

    switch (type) {
        case 'integer':
            return parseInt(value, 10);
        case 'number':
            return parseFloat(value);
        case 'boolean':
            return value === 'true' || value === true;
        case 'object':
            if (typeof value === 'string') {
                try {
                    return JSON.parse(value);
                } catch (e) {
                    console.error('Invalid JSON for default value:', e.message);
                    return undefined;
                }
            }
            return value;
        case 'array':
            if (typeof value === 'string') {
                // JSON 형식이면 파싱
                if (value.trim().startsWith('[')) {
                    try {
                        return JSON.parse(value);
                    } catch (e) {
                        console.error('Invalid JSON for default value:', e.message);
                    }
                }
                // 콤마로 구분된 문자열이면 배열로 변환
                return value.split(',').map(s => s.trim()).filter(s => s);
            }
            return value;
        default:
            return value;
    }
}

/**
 * Format default value for display
 */
function formatDefaultValue(value, type) {
    if (value === undefined || value === null) return '';
    if (type === 'object' || type === 'array') {
        return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    }
    return String(value);
}

// ===== Compatibility Aliases =====
// These maintain backward compatibility with existing HTML onclick handlers

// Expose MCPEditor.state as global variables for compatibility
window.tools = MCPEditor.state.tools;
window.internalArgs = MCPEditor.state.internalArgs;
window.fileMtimes = MCPEditor.state.fileMtimes;
window.currentToolIndex = MCPEditor.state.currentToolIndex;
window.currentProfile = MCPEditor.state.currentProfile;
window.profiles = MCPEditor.state.profiles;
