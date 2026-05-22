/* Tool Editor Property - Property Field Management */

function setPropertyDestination(index, propName, destination) {
    const tool = tools[index];
    const toolName = tool.name;
    const propDef = tool.inputSchema?.properties?.[propName];

    // For "to signature", check if we have stored original_schema
    const existingInternal = internalArgs[toolName]?.[propName];

    if (destination === 'internal') {
        // If already internal, nothing to do
        if (existingInternal && !propDef) {
            console.log('Property already internal:', propName);
            return;
        }
        if (!propDef) {
            console.error('Property not found in inputSchema:', propName);
            return;
        }

        // Move to Internal: add to internalArgs and REMOVE from inputSchema
        if (!internalArgs[toolName]) {
            internalArgs[toolName] = {};
        }

        // Store original schema info for potential restoration
        const wasRequired = (tool.inputSchema.required || []).includes(propName);
        internalArgs[toolName][propName] = {
            type: propDef.baseModel || propDef.type,  // Use baseModel if available
            description: propDef.description || '',
            original_schema: JSON.parse(JSON.stringify(propDef)),  // Deep copy for restoration
            was_required: wasRequired
        };

        // CRITICAL: Remove from inputSchema.properties (spec FR-03)
        delete tool.inputSchema.properties[propName];

        // Remove from required array if present
        if (tool.inputSchema.required) {
            tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== propName);
        }

        showNotification(`Property "${propName}" moved to Internal (removed from MCP signature)`, 'info');
    } else {
        // Move to Signature: restore from internalArgs
        if (!existingInternal) {
            console.error('No internal arg found to restore:', propName);
            return;
        }

        // Restore original schema from stored original_schema
        if (existingInternal.original_schema) {
            tool.inputSchema.properties[propName] = JSON.parse(JSON.stringify(existingInternal.original_schema));
        } else {
            // Fallback: create basic schema from internal arg info
            tool.inputSchema.properties[propName] = {
                type: existingInternal.type === 'object' ? 'object' : existingInternal.type,
                description: existingInternal.description || ''
            };
        }

        // Restore required status if it was required before
        if (existingInternal.was_required) {
            if (!tool.inputSchema.required) {
                tool.inputSchema.required = [];
            }
            if (!tool.inputSchema.required.includes(propName)) {
                tool.inputSchema.required.push(propName);
            }
        }

        // Remove from internalArgs
        delete internalArgs[toolName][propName];

        // Clean up empty tool entry
        if (Object.keys(internalArgs[toolName]).length === 0) {
            delete internalArgs[toolName];
        }

        showNotification(`Property "${propName}" restored to Signature`, 'info');
    }

    // Re-render to update UI (preserve scroll position and collapse state)
    const scrollContainer = document.querySelector('.editor-area');
    const scrollTop = scrollContainer
        ? scrollContainer.scrollTop
        : (window.scrollY || document.documentElement.scrollTop);
    const scrollLeft = scrollContainer
        ? scrollContainer.scrollLeft
        : (window.scrollX || document.documentElement.scrollLeft);

    // Save collapsed property states before re-render (class-based, not inline style)
    const collapsedProps = Array.from(document.querySelectorAll('.property-collapse-content'))
        .filter(content => content.classList.contains('collapsed'))
        .map(content => content.id);

    renderToolEditor(tool, index);

    // Restore collapsed states
    collapsedProps.forEach(id => {
        const content = document.getElementById(id);
        const iconId = id.replace('content-', 'icon-');
        const icon = document.getElementById(iconId);
        const headerId = id.replace('content-', 'header-');
        const header = document.getElementById(headerId);

        if (content) content.classList.add('collapsed');
        if (icon) {
            icon.classList.add('collapsed');
            icon.textContent = '▶';
        }
        if (header) header.classList.remove('expanded');
    });

    // Restore scroll position after render (prefer the editor scroll container)
    setTimeout(() => {
        if (scrollContainer) {
            scrollContainer.scrollTop = scrollTop;
            scrollContainer.scrollLeft = scrollLeft;
        } else {
            window.scrollTo(scrollLeft, scrollTop);
        }
    }, 10);
}

// Toggle signature defaults for a property (Signature + internal defaults)
function toggleSignatureDefaults(index, propName, enabled) {
    const tool = tools[index];
    const toolName = tool.name;
    const propDef = tool.inputSchema?.properties?.[propName];

    if (!propDef) {
        console.error('Property not found in inputSchema:', propName);
        return;
    }

    if (enabled) {
        // Enable signature defaults: store property schema in signatureDefaults
        if (!signatureDefaults[toolName]) {
            signatureDefaults[toolName] = {};
        }

        // Copy property definition with defaults
        signatureDefaults[toolName][propName] = {
            baseModel: propDef.baseModel || propDef.type,
            description: propDef.description || '',
            properties: propDef.properties ? JSON.parse(JSON.stringify(propDef.properties)) : {},
            source: 'signature_defaults'
        };

        showNotification(`Property "${propName}" now has signature defaults enabled`, 'success');
    } else {
        // Disable signature defaults: remove from signatureDefaults
        if (signatureDefaults[toolName]) {
            delete signatureDefaults[toolName][propName];

            // Clean up empty tool entry
            if (Object.keys(signatureDefaults[toolName]).length === 0) {
                delete signatureDefaults[toolName];
            }
        }

        showNotification(`Property "${propName}" signature defaults disabled`, 'info');
    }

    // Re-render to update UI
    renderToolEditor(tool, index);
}

// Update signature defaults for a property (JSON format)
function updateSignatureDefaults(index, propName, jsonString) {
    const tool = tools[index];
    const toolName = tool.name;

    if (!signatureDefaults[toolName] || !signatureDefaults[toolName][propName]) {
        console.error('Signature defaults not found:', toolName, propName);
        return;
    }

    try {
        const defaults = JSON.parse(jsonString);
        // Update default values in properties
        const sigDef = signatureDefaults[toolName][propName];
        if (!sigDef.properties) {
            sigDef.properties = {};
        }
        for (const [key, value] of Object.entries(defaults)) {
            if (!sigDef.properties[key]) {
                sigDef.properties[key] = { type: typeof value };
            }
            sigDef.properties[key].default = value;
        }
        showNotification(`Signature defaults updated for "${propName}"`, 'success');
    } catch (e) {
        showNotification(`Invalid JSON: ${e.message}`, 'error');
    }
}

function updateInternalArgDefaults(index, propName, jsonString) {
    const tool = tools[index];
    const toolName = tool.name;

    if (!internalArgs[toolName] || !internalArgs[toolName][propName]) {
        console.error('Internal arg not found:', toolName, propName);
        return;
    }

    try {
        const defaults = JSON.parse(jsonString);
        // Update default values in original_schema.properties
        const propArg = internalArgs[toolName][propName];
        if (!propArg.original_schema.properties) {
            propArg.original_schema.properties = {};
        }
        for (const [key, value] of Object.entries(defaults)) {
            if (!propArg.original_schema.properties[key]) {
                propArg.original_schema.properties[key] = { type: typeof value };
            }
            propArg.original_schema.properties[key].default = value;
        }
        showNotification(`Internal defaults updated for "${propName}"`, 'success');
    } catch (e) {
        showNotification(`Invalid JSON: ${e.message}`, 'error');
    }
}

// ============================================================
// Property Field Functions
// ============================================================

function updatePropertyField(index, propName, field, value) {
    const tool = tools[index];
    const toolName = tool.name;

    // Check if this property is internal (not in inputSchema but in internalArgs)
    const isInternal = !tool.inputSchema.properties[propName] &&
                       internalArgs[toolName]?.[propName];

    if (isInternal) {
        // Update original_schema in internalArgs instead of inputSchema
        if (!internalArgs[toolName][propName].original_schema) {
            internalArgs[toolName][propName].original_schema = {};
        }
        internalArgs[toolName][propName].original_schema[field] = value;

        // CRITICAL: Also update the main internal arg fields that the generator uses
        if (field === 'description') {
            internalArgs[toolName][propName].description = value;
        }
        // Issue 10 fix: Update type in internalArgs so generator uses the new type
        if (field === 'type') {
            // Only update if there's no baseModel (baseModel takes precedence)
            if (!internalArgs[toolName][propName].original_schema?.baseModel) {
                internalArgs[toolName][propName].type = value;
            }
        }
        // Add targetParam to top level for internal args
        if (field === 'targetParam') {
            if (value) {
                internalArgs[toolName][propName].targetParam = value;
            } else {
                // Remove targetParam if value is empty
                delete internalArgs[toolName][propName].targetParam;
            }
        }
    } else {
        // Normal signature property - update inputSchema
        if (!tool.inputSchema.properties[propName]) {
            tool.inputSchema.properties[propName] = {};
        }
        tool.inputSchema.properties[propName][field] = value;

        // Sync default value to mcp_service.parameters
        if (field === 'default') {
            syncMcpServiceParameterDefault(tool, propName, value);
        }
    }

    // If targetParam was changed, update the service method params display
    if (field === 'targetParam') {
        loadAndDisplayServiceMethodParams(index);
    }
}

/**
 * Sync mcp_service.parameters when default value changes
 * Updates has_default and default in mcp_service.parameters
 */
function syncMcpServiceParameterDefault(tool, propName, defaultValue) {
    if (!tool.mcp_service || !tool.mcp_service.parameters) {
        return;
    }

    // Find the parameter in mcp_service.parameters by name or targetParam
    const propDef = tool.inputSchema?.properties?.[propName];
    const targetParam = propDef?.targetParam || propName;

    const param = tool.mcp_service.parameters.find(p =>
        p.name === propName || p.name === targetParam
    );

    if (param) {
        if (defaultValue !== undefined && defaultValue !== null && defaultValue !== '') {
            param.has_default = true;
            param.default = defaultValue;
        } else {
            param.has_default = false;
            param.default = null;
        }
        console.log(`[syncMcpServiceParameterDefault] Updated ${propName}: has_default=${param.has_default}, default=${param.default}`);
    }
}

function updatePropertyEnum(index, propName, value) {
    const tool = tools[index];
    const toolName = tool.name;
    const enumValues = value.split(',').map(v => v.trim()).filter(v => v);

    // Check if this property is internal
    const isInternal = !tool.inputSchema.properties[propName] &&
                       internalArgs[toolName]?.[propName];

    if (isInternal) {
        if (!internalArgs[toolName][propName].original_schema) {
            internalArgs[toolName][propName].original_schema = {};
        }
        internalArgs[toolName][propName].original_schema.enum = enumValues;
    } else {
        tool.inputSchema.properties[propName].enum = enumValues;
    }
}

function toggleEnum(index, propName, hasEnum) {
    const tool = tools[index];
    const toolName = tool.name;

    // Check if this property is internal
    const isInternal = !tool.inputSchema.properties[propName] &&
                       internalArgs[toolName]?.[propName];

    if (isInternal) {
        if (!internalArgs[toolName][propName].original_schema) {
            internalArgs[toolName][propName].original_schema = {};
        }
        if (hasEnum) {
            internalArgs[toolName][propName].original_schema.enum = [];
        } else {
            delete internalArgs[toolName][propName].original_schema.enum;
        }
    } else {
        if (hasEnum) {
            tool.inputSchema.properties[propName].enum = [];
        } else {
            delete tool.inputSchema.properties[propName].enum;
        }
    }
    renderToolEditor(tool, index);
}

function toggleRequired(index, propName, isChecked) {
    const tool = tools[index];
    const toolName = tool.name;

    // Check if this property is internal
    const isInternal = !tool.inputSchema.properties[propName] &&
                       internalArgs[toolName]?.[propName];

    if (isInternal) {
        // For internal properties, update was_required in internalArgs
        internalArgs[toolName][propName].was_required = isChecked;
    } else {
        // Normal signature property - update inputSchema.required
        if (!tool.inputSchema.required) {
            tool.inputSchema.required = [];
        }

        if (isChecked) {
            if (!tool.inputSchema.required.includes(propName)) {
                tool.inputSchema.required.push(propName);
            }
            // Required property cannot have default value - remove it
            if (tool.inputSchema.properties[propName]) {
                delete tool.inputSchema.properties[propName].default;
            }
        } else {
            tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== propName);
        }
    }

    // Sync mcp_service.parameters with inputSchema required status
    syncMcpServiceParameterRequired(tool, propName, isChecked);

    // Re-render to update the JSON view (this will show/hide default field)
    renderToolEditor(tool, index);
}

/**
 * Sync mcp_service.parameters when Required checkbox changes
 * Updates is_required, is_optional, has_default based on inputSchema
 */
function syncMcpServiceParameterRequired(tool, propName, isRequired) {
    if (!tool.mcp_service || !tool.mcp_service.parameters) {
        return;
    }

    // Find the parameter in mcp_service.parameters by name or targetParam
    const propDef = tool.inputSchema?.properties?.[propName];
    const targetParam = propDef?.targetParam || propName;

    const param = tool.mcp_service.parameters.find(p =>
        p.name === propName || p.name === targetParam
    );

    if (param) {
        if (isRequired) {
            // Mark as required
            param.is_required = true;
            param.is_optional = false;
            // Required params should not have default
            param.has_default = false;
            param.default = null;
        } else {
            // Mark as optional
            param.is_required = false;
            param.is_optional = true;
            // Check if there's a default value in inputSchema
            if (propDef?.default !== undefined) {
                param.has_default = true;
                param.default = propDef.default;
            }
        }
        console.log(`[syncMcpServiceParameterRequired] Updated ${propName}: is_required=${param.is_required}, has_default=${param.has_default}`);
    }
}

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
            // Parse JSON for object types
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

function formatDefaultValue(value, type) {
    // Format default value for display in input field
    if (value === undefined || value === null) return '';
    if (type === 'object' || type === 'array') {
        return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    }
    return String(value);
}

function addProperty(index) {
    // Remove any existing property modal first
    const existingModal = document.getElementById('propertyModal');
    if (existingModal) {
        existingModal.parentElement.remove();
    }

    // Create modal for property selection
    const hasTypes = window.hasTypesFile || false;
    const typesName = window.typesName || 'types';
    const modalHtml = `
        <div id="propertyModal" class="modal show">
            <div class="modal-content" style="max-width: 600px;">
                <div class="modal-header">
                    <h3>Add Property</h3>
                    <button onclick="closeModal('propertyModal')" class="close-btn">×</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>Property Source</label>
                        <select id="propertySource" onchange="handlePropertySourceChange()" class="form-control">
                            <option value="custom">Custom Property</option>
                            ${hasTypes ? `<option value="graph_types">From ${typesName}.py</option>` : ''}
                        </select>
                    </div>

                    <div id="customPropertyDiv">
                        <div class="form-group">
                            <label>Input Schema Name</label>
                            <input type="text" id="customPropName" class="form-control" placeholder="e.g., filter_params, user_email, search_term">
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">
                                This name will be used in inputSchema.properties for LLM to recognize.
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Service Method Parameter (optional)</label>
                            <select id="customTargetParam" class="form-control">
                                <option value="">-- Same as Input Schema Name --</option>
                            </select>
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">
                                Select which parameter in the service method this property maps to. Leave default if names match.
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Property Type</label>
                            <select id="customPropType" class="form-control" onchange="handleCustomTypeChange()">
                                <option value="string">string</option>
                                <option value="integer">integer</option>
                                <option value="number">number</option>
                                <option value="boolean">boolean</option>
                                <option value="array">array</option>
                                <option value="object">object</option>
                            </select>
                        </div>
                        <div class="form-group" id="customBaseModelDiv" style="display: none;">
                            <label>Base Model (for object type)</label>
                            <input type="text" id="customBaseModel" class="form-control" placeholder="e.g., FilterParams, ExcludeParams">
                        </div>
                        <div class="form-group">
                            <label>Description</label>
                            <input type="text" id="customPropDescription" class="form-control" placeholder="Property description">
                        </div>
                    </div>

                    <div id="graphTypesPropertyDiv" style="display: none;">
                        <div class="form-group">
                            <label>Select Type (from ${typesName})</label>
                            <input type="text" id="graphTypeFilter" class="form-control"
                                   placeholder="Filter types..."
                                   oninput="filterGraphTypes(this.value)"
                                   style="margin-bottom: 8px;">
                            <select id="graphTypeClass" onchange="handleClassChange()" class="form-control" data-debug-id="FIELD_GRAPH_TYPE_CLASS" size="8" style="height: auto;">
                                <option value="">-- Select Type --</option>
                            </select>
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">
                                <span id="graphTypeCount"></span>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Input Schema Name (optional)</label>
                            <input type="text" id="graphTypePropName" class="form-control"
                                   placeholder="e.g., filter_params, exclude_params">
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">
                                The name that will appear in inputSchema.properties. Leave empty for automatic naming. Use _internal suffix for internal-only objects.
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Service Method Parameter (optional)</label>
                            <select id="graphTypeTargetParam" class="form-control" onchange="handleTargetParamChange()">
                                <option value="">-- Same as Input Schema Name --</option>
                            </select>
                            <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">
                                Select which parameter in the service method this property maps to. Leave default if names match.
                            </div>
                        </div>
                        <div class="form-group" id="propertySelectionDiv" style="display: none;">
                            <label>Select Properties to Add</label>
                            <div style="border: 1px solid #ddd; border-radius: 4px; padding: 10px; max-height: 300px; overflow-y: auto;">
                                <div id="propertyCheckboxList">
                                    <!-- Checkboxes will be populated here -->
                                </div>
                            </div>
                            <div style="margin-top: 10px;">
                                <button type="button" class="btn btn-sm btn-secondary" onclick="selectAllProperties(true)">Select All</button>
                                <button type="button" class="btn btn-sm btn-secondary" onclick="selectAllProperties(false)">Deselect All</button>
                                <button type="button" class="btn btn-sm btn-secondary" onclick="toggleAllRequired(true)">All Required</button>
                                <button type="button" class="btn btn-sm btn-secondary" onclick="toggleAllRequired(false)">All Optional</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button onclick="confirmAddProperty(${index})" class="btn btn-primary">Add Property</button>
                    <button onclick="closeModal('propertyModal')" class="btn btn-secondary">Cancel</button>
                </div>
            </div>
        </div>
    `;

    // Add modal to body
    const modalDiv = document.createElement('div');
    modalDiv.innerHTML = modalHtml;
    document.body.appendChild(modalDiv);

    // Populate graph type class dropdown if types are available
    if (hasTypes && window.graphTypesProperties && window.graphTypesProperties.classes) {
        const classSelect = document.getElementById('graphTypeClass');
        window.graphTypesProperties.classes.forEach(cls => {
            const option = document.createElement('option');
            option.value = cls.name || cls;
            option.textContent = `${cls.name || cls}${cls.description ? ' (' + cls.description + ')' : ''}`;
            classSelect.appendChild(option);
        });
        console.log('[DEBUG] Populated graph type classes:', window.graphTypesProperties.classes.length, 'classes');
        // Update type count display
        updateGraphTypeCount();
    } else {
        console.log('[DEBUG] No graph types available. hasTypes:', hasTypes, 'graphTypesProperties:', window.graphTypesProperties);
    }

    // Initialize the property source view to show custom property fields by default
    handlePropertySourceChange();

    // Load service method parameters for the dropdown
    loadServiceMethodParameters(index);
}

function loadServiceMethodParameters(index) {
    const tool = tools[index];
    const toolName = tool.name;

    // Try both select elements (custom and graph types)
    const customSelect = document.getElementById('customTargetParam');
    const graphSelect = document.getElementById('graphTypeTargetParam');

    const selects = [customSelect, graphSelect].filter(s => s);

    // Clear existing options except the default one for all selects
    selects.forEach(select => {
        select.innerHTML = '<option value="">-- Same as Input Schema Name --</option>';
    });

    // Try to get the service implementation info
    if (tool.mcp_service) {
        // Get the service name from tool definition
        const serviceName = typeof tool.mcp_service === 'string'
            ? tool.mcp_service
            : tool.mcp_service.name;

        // Load the registry to get actual method parameters
        const currentProfile = window.currentProfile || 'mcp_outlook';
        fetch(`/api/registry?profile=${currentProfile}`)
            .then(response => response.json())
            .then(registry => {
                if (registry && registry.services && registry.services[serviceName]) {
                    const service = registry.services[serviceName];
                    if (service.parameters) {
                        service.parameters.forEach(param => {
                            selects.forEach(select => {
                                const option = document.createElement('option');
                                option.value = param.name;
                                // Show type and jsdoc_type/class_name if available
                                const typeName = param.class_name || param.jsdoc_type || param.type;
                                option.textContent = `${param.name} (${typeName})`;
                                // Store class_name or jsdoc_type for auto-selection of type
                                // JavaScript uses jsdoc_type, Python uses class_name
                                const typeClass = param.class_name || param.jsdoc_type;
                                if (typeClass && typeClass !== param.type) {
                                    option.dataset.className = typeClass;
                                }
                                select.appendChild(option);
                            });
                        });
                    }
                }
            })
            .catch(error => {
                console.error('Failed to load service parameters:', error);
            });
    }
}

/**
 * Handle parameter selection change - auto-select matching type class and filter list
 */
function handleTargetParamChange() {
    const paramSelect = document.getElementById('graphTypeTargetParam');
    const classSelect = document.getElementById('graphTypeClass');
    const filterInput = document.getElementById('graphTypeFilter');

    if (!paramSelect || !classSelect) return;

    const selectedOption = paramSelect.options[paramSelect.selectedIndex];
    const className = selectedOption?.dataset?.className;

    console.log('[DEBUG] handleTargetParamChange - selectedOption:', selectedOption?.value, 'className:', className);

    if (className) {
        // Filter the type list to show only matching type
        Array.from(classSelect.options).forEach(option => {
            if (option.value === '' || option.value === className) {
                option.style.display = '';
            } else {
                option.style.display = 'none';
            }
        });

        // Auto-select the matching type class
        classSelect.value = className;
        // Trigger the class change handler to show properties
        handleClassChange();
        // Update filter input to show what's filtered
        if (filterInput) {
            filterInput.value = className;
        }
        updateGraphTypeCount();
        console.log('[DEBUG] Auto-selected and filtered to type:', className);
    } else {
        // No specific type - show all types
        Array.from(classSelect.options).forEach(option => {
            option.style.display = '';
        });
        if (filterInput) {
            filterInput.value = '';
        }
        updateGraphTypeCount();
    }
}

/**
 * Filter type options based on search input
 */
function filterGraphTypes(searchText) {
    const classSelect = document.getElementById('graphTypeClass');
    if (!classSelect) return;

    const filterLower = searchText.toLowerCase();

    Array.from(classSelect.options).forEach(option => {
        if (option.value === '') {
            // Always show the default option
            option.style.display = '';
        } else {
            const text = option.textContent.toLowerCase();
            const matches = text.includes(filterLower);
            option.style.display = matches ? '' : 'none';
        }
    });

    updateGraphTypeCount();
}

/**
 * Update the type count display
 */
function updateGraphTypeCount() {
    const classSelect = document.getElementById('graphTypeClass');
    const countSpan = document.getElementById('graphTypeCount');
    if (!classSelect || !countSpan) return;

    const visibleCount = Array.from(classSelect.options).filter(
        opt => opt.value !== '' && opt.style.display !== 'none'
    ).length;
    const totalCount = classSelect.options.length - 1; // Exclude default option

    countSpan.textContent = visibleCount === totalCount
        ? `${totalCount} types available`
        : `Showing ${visibleCount} of ${totalCount} types`;
}

function handleCustomTypeChange() {
    const propType = document.getElementById('customPropType').value;
    const baseModelDiv = document.getElementById('customBaseModelDiv');

    // Show base model input only for object type
    baseModelDiv.style.display = propType === 'object' ? 'block' : 'none';
}

function handlePropertySourceChange() {
    const source = document.getElementById('propertySource').value;
    document.getElementById('customPropertyDiv').style.display = source === 'custom' ? 'block' : 'none';
    document.getElementById('graphTypesPropertyDiv').style.display = source === 'graph_types' ? 'block' : 'none';

    console.log('[DEBUG] Property source changed to:', source);

    if (source === 'graph_types') {
        const classSelect = document.getElementById('graphTypeClass');
        if (!classSelect) return;

        const populate = () => {
            if (classSelect.options.length <= 1) {
                populateGraphTypeOptions(classSelect);
            }
        };

        if (window.graphTypesProperties && Array.isArray(window.graphTypesProperties.classes)) {
            populate();
        } else {
            loadGraphTypesProperties().then(populate);
        }
    }
}

function handleClassChange() {
    const className = document.getElementById('graphTypeClass').value;
    const selectionDiv = document.getElementById('propertySelectionDiv');
    const checkboxList = document.getElementById('propertyCheckboxList');
    const propNameInput = document.getElementById('graphTypePropName');

    console.log('[DEBUG] handleClassChange called. className:', className);
    console.log('[DEBUG] window.graphTypesProperties:', window.graphTypesProperties);

    if (className && window.graphTypesProperties) {
        if (propNameInput) {
            const tool = tools[currentToolIndex];
            const defaultName = tool ? getTargetPropertyForGraphType(className, tool) : null;
            propNameInput.placeholder = defaultName ? `Default: ${defaultName}` : 'Enter property name';
        }
        const properties = window.graphTypesProperties.properties_by_class[className] || [];
        console.log('[DEBUG] Found properties for', className, ':', properties.length, 'properties');

        // Generate checkboxes for each property
        let checkboxHtml = '';
        properties.forEach((prop, idx) => {
            const propId = `prop_${className}_${idx}`;
            const reqId = `req_${className}_${idx}`;
            checkboxHtml += `
                <div style="padding: 8px; border-bottom: 1px solid #eee; display: flex; align-items: center;">
                    <input type="checkbox" id="${propId}" data-prop-name="${prop.name}"
                           data-prop-type="${prop.type}" data-prop-desc="${prop.description || ''}"
                           style="margin-right: 10px;">
                    <div style="flex-grow: 1;">
                        <label for="${propId}" style="margin: 0; cursor: pointer;">
                            <strong>${prop.name}</strong>
                            <span style="color: #666; font-size: 12px;">(${prop.type})</span>
                            ${prop.description ? `<br><span style="color: #888; font-size: 11px;">${prop.description}</span>` : ''}
                        </label>
                    </div>
                    <div style="margin-left: 10px;">
                        <label style="margin: 0; font-size: 12px;">
                            <input type="checkbox" id="${reqId}" style="margin-right: 5px;">Required
                        </label>
                    </div>
                </div>
            `;
        });

        checkboxList.innerHTML = checkboxHtml || '<div style="padding: 10px; text-align: center; color: #666;">No properties available</div>';
        selectionDiv.style.display = 'block';
    } else {
        if (propNameInput) {
            propNameInput.placeholder = 'Leave empty to use default mapping';
        }
        console.log('[DEBUG] Hiding property selection. className:', className, 'graphTypesProperties:', !!window.graphTypesProperties);
        selectionDiv.style.display = 'none';
    }
}

function selectAllProperties(select) {
    const checkboxes = document.querySelectorAll('#propertyCheckboxList input[type="checkbox"][id^="prop_"]');
    checkboxes.forEach(cb => cb.checked = select);
}

function toggleAllRequired(required) {
    const checkboxes = document.querySelectorAll('#propertyCheckboxList input[type="checkbox"][id^="req_"]');
    checkboxes.forEach(cb => cb.checked = required);
}

function openNestedGraphTypesModal(toolIndex, propName) {
    nestedGraphTarget = {toolIndex, propName};

    const classSelect = document.getElementById('nestedGraphTypeClass');
    const selectionDiv = document.getElementById('nestedPropertySelectionDiv');
    const checkboxList = document.getElementById('nestedPropertyCheckboxList');

    classSelect.value = '';
    checkboxList.innerHTML = '';
    selectionDiv.style.display = 'none';

    populateGraphTypeOptions(classSelect);

    const tool = tools[toolIndex];
    const toolName = tool.name;
    let parentProp = tool.inputSchema?.properties?.[propName];
    if (!parentProp && internalArgs[toolName]?.[propName]) {
        parentProp = internalArgs[toolName][propName].original_schema;
    }
    if (parentProp && parentProp.baseModel) {
        classSelect.value = parentProp.baseModel;
        handleNestedGraphClassChange();
    }

    document.getElementById('nestedGraphTypesModal').classList.add('show');
}

function handleNestedGraphClassChange() {
    const className = document.getElementById('nestedGraphTypeClass').value;
    const selectionDiv = document.getElementById('nestedPropertySelectionDiv');
    const checkboxList = document.getElementById('nestedPropertyCheckboxList');

    if (className && window.graphTypesProperties) {
        const properties = window.graphTypesProperties.properties_by_class[className] || [];

        let checkboxHtml = '';
        properties.forEach((prop, idx) => {
            const propId = `nested_prop_${className}_${idx}`;
            const reqId = `nested_req_${className}_${idx}`;
            checkboxHtml += `
                <div style="padding: 8px; border-bottom: 1px solid #eee; display: flex; align-items: center;">
                    <input type="checkbox" id="${propId}" data-prop-name="${prop.name}"
                           data-prop-type="${prop.type}" data-prop-desc="${prop.description || ''}"
                           style="margin-right: 10px;">
                    <div style="flex-grow: 1;">
                        <label for="${propId}" style="margin: 0; cursor: pointer;">
                            <strong>${prop.name}</strong>
                            <span style="color: #666; font-size: 12px;">(${prop.type})</span>
                            ${prop.description ? `<br><span style="color: #888; font-size: 11px;">${prop.description}</span>` : ''}
                        </label>
                    </div>
                    <div style="margin-left: 10px;">
                        <label style="margin: 0; font-size: 12px;">
                            <input type="checkbox" id="${reqId}" style="margin-right: 5px;">Required
                        </label>
                    </div>
                </div>
            `;
        });

        checkboxList.innerHTML = checkboxHtml || '<div style="padding: 10px; text-align: center; color: #666;">No properties available</div>';
        selectionDiv.style.display = 'block';
    } else {
        selectionDiv.style.display = 'none';
        checkboxList.innerHTML = '';
    }
}

function selectAllNestedProperties(select) {
    const checkboxes = document.querySelectorAll('#nestedPropertyCheckboxList input[type="checkbox"][id^="nested_prop_"]');
    checkboxes.forEach(cb => cb.checked = select);
}

function toggleAllNestedRequired(required) {
    const checkboxes = document.querySelectorAll('#nestedPropertyCheckboxList input[type="checkbox"][id^="nested_req_"]');
    checkboxes.forEach(cb => cb.checked = required);
}

function confirmAddNestedGraphProperties() {
    if (!nestedGraphTarget) {
        closeModal('nestedGraphTypesModal');
        return;
    }

    const className = document.getElementById('nestedGraphTypeClass').value;
    const checkboxes = document.querySelectorAll('#nestedPropertyCheckboxList input[type="checkbox"][id^="nested_prop_"]:checked');

    if (!className) {
        showNotification('Please select a type from outlook_types.py', 'error');
        return;
    }

    if (checkboxes.length === 0) {
        showNotification('Please select at least one property', 'error');
        return;
    }

    const {toolIndex, propName} = nestedGraphTarget;
    const tool = tools[toolIndex];
    const toolName = tool.name;
    const internalArg = internalArgs[toolName]?.[propName];
    const useInternal = !!internalArg;
    let parentProp;

    if (useInternal) {
        if (!internalArg.original_schema) {
            internalArg.original_schema = {type: 'object', properties: {}, required: []};
        }
        parentProp = internalArg.original_schema;
        internalArg.type = className;
        if (!internalArg.description && parentProp.description) {
            internalArg.description = parentProp.description;
        }
    } else {
        if (!tool.inputSchema) {
            tool.inputSchema = {type: 'object', properties: {}, required: []};
        }
        if (!tool.inputSchema.properties) {
            tool.inputSchema.properties = {};
        }
        if (!tool.inputSchema.properties[propName]) {
            tool.inputSchema.properties[propName] = {type: 'object', properties: {}, required: []};
        }
        parentProp = tool.inputSchema.properties[propName];
    }
    parentProp.type = 'object';
    parentProp.properties = parentProp.properties || {};
    parentProp.required = parentProp.required || [];
    parentProp.baseModel = parentProp.baseModel || className;
    if (!parentProp.description) {
        parentProp.description = `${className} parameters`;
    }
    if (useInternal && !internalArg.description) {
        internalArg.description = parentProp.description;
    }

    let addedCount = 0;
        checkboxes.forEach(cb => {
            const prop = cb.dataset;
            const idx = cb.id.split('_').pop();
            const isRequired = document.getElementById(`nested_req_${className}_${idx}`).checked;

            const schema = mapSignatureTypeToSchema(prop.propType);
            parentProp.properties[prop.propName] = {
                type: schema.type || 'string',
                ...(schema.items ? { items: schema.items } : {}),
                description: prop.propDesc || ''
            };

            if (isRequired && !parentProp.required.includes(prop.propName)) {
                parentProp.required.push(prop.propName);
            }

        addedCount++;
    });

    // Sync parent's default value with nested properties' defaults
    syncNestedPropertiesToDefault(toolIndex, propName);

    closeModal('nestedGraphTypesModal');
    renderToolEditor(tool, toolIndex);
    showNotification(`${addedCount} nested properties added to "${propName}"`, 'success');
}

function confirmAddProperty(index) {
    const source = document.getElementById('propertySource').value;

    if (source === 'custom') {
        // Handle single custom property
        const propName = document.getElementById('customPropName').value;
        const propType = document.getElementById('customPropType').value;
        const propDescription = document.getElementById('customPropDescription').value;
        const targetParam = document.getElementById('customTargetParam').value;
        const baseModel = document.getElementById('customBaseModel').value;

        if (propName) {
            if (!tools[index].inputSchema.properties) {
                tools[index].inputSchema.properties = {};
            }

            // Check if property already exists
            if (tools[index].inputSchema.properties[propName]) {
                if (!confirm(`Property "${propName}" already exists. Do you want to overwrite it?`)) {
                    return;
                }
            }

            // For custom properties, use simple type
            const jsonType = mapToJsonSchemaType(propType);
            const propDef = {
                type: jsonType,
                description: propDescription
            };
            // If it's an array, default to string items
            if (jsonType === 'array' && !propDef.items) {
                propDef.items = { type: 'string' };
            }

            // Add targetParam if specified and different from propName
            if (targetParam && targetParam.trim() && targetParam !== propName) {
                propDef.targetParam = targetParam.trim();
            }

            // Add baseModel for object types
            if (jsonType === 'object' && baseModel && baseModel.trim()) {
                propDef.baseModel = baseModel.trim();
            }

            tools[index].inputSchema.properties[propName] = propDef;

            closeModal('propertyModal');
            renderToolEditor(tools[index], index);
            showNotification(`Property "${propName}" added successfully`, 'success');
        } else {
            showNotification('Please enter a property name', 'error');
        }
    } else {
        // Handle multiple properties from graph_types
        const className = document.getElementById('graphTypeClass').value;
        const checkboxes = document.querySelectorAll('#propertyCheckboxList input[type="checkbox"][id^="prop_"]:checked');

        if (!className) {
            showNotification('Please select a type from outlook_types.py', 'error');
            return;
        }

        if (checkboxes.length === 0) {
            showNotification('Please select at least one property', 'error');
            return;
        }

        if (!tools[index].inputSchema.properties) {
            tools[index].inputSchema.properties = {};
        }
        if (!tools[index].inputSchema.required) {
            tools[index].inputSchema.required = [];
        }

        let addedCount = 0;
        const overridePropName = document.getElementById('graphTypePropName')?.value.trim();
        const targetPropName = overridePropName || getTargetPropertyForGraphType(className, tools[index]);

        if (!targetPropName && overridePropName) {
            showNotification('Please enter a property name', 'error');
            return;
        }

        if (targetPropName) {
            const toolName = tools[index].name;
            // Check if target property is internal
            const isTargetInternal = !tools[index].inputSchema.properties[targetPropName] &&
                                     internalArgs[toolName]?.[targetPropName];

            let targetProp;  // Declare outside if blocks for shared access

            if (isTargetInternal) {
                // Update internalArgs for internal property (Issue 10 fix)
                if (!internalArgs[toolName][targetPropName].original_schema) {
                    internalArgs[toolName][targetPropName].original_schema = {
                        type: 'object',
                        description: `${className} parameters`,
                        properties: {},
                        required: []
                    };
                }
                targetProp = internalArgs[toolName][targetPropName].original_schema;
                targetProp.type = 'object';
                targetProp.properties = targetProp.properties || {};
                targetProp.required = targetProp.required || [];
                targetProp.baseModel = className;
                // CRITICAL: Update internalArgs.type for generator
                internalArgs[toolName][targetPropName].type = className;
                if (!targetProp.description) {
                    targetProp.description = `${className} parameters`;
                }
            } else {
                // Normal signature property
                if (!tools[index].inputSchema.properties[targetPropName]) {
                    tools[index].inputSchema.properties[targetPropName] = {
                        type: 'object',
                        description: `${className} parameters`,
                        properties: {},
                        required: []
                    };
                }

                targetProp = tools[index].inputSchema.properties[targetPropName];
                targetProp.type = 'object';
                targetProp.properties = targetProp.properties || {};
                targetProp.required = targetProp.required || [];
                targetProp.baseModel = className;
                if (!targetProp.description) {
                    targetProp.description = `${className} parameters`;
                }

                // Add targetParam if specified and different from targetPropName
                const customTargetParam = document.getElementById('graphTypeTargetParam')?.value;
                if (customTargetParam && customTargetParam.trim() && customTargetParam !== targetPropName) {
                    targetProp.targetParam = customTargetParam.trim();
                }
            }

                checkboxes.forEach(checkbox => {
                    const propName = checkbox.dataset.propName;
                    const propType = checkbox.dataset.propType;
                    const propDesc = checkbox.dataset.propDesc;
                    const idx = checkbox.id.split('_').pop();
                    const isRequired = document.getElementById(`req_${className}_${idx}`).checked;

                    const schema = mapSignatureTypeToSchema(propType);
                    targetProp.properties[propName] = {
                        type: schema.type || 'string',
                        ...(schema.items ? { items: schema.items } : {}),
                        description: propDesc || ''
                    };

                    if (isRequired && !targetProp.required.includes(propName)) {
                        targetProp.required.push(propName);
                    }

                addedCount++;
            });
        } else {
            // Fallback: add to top-level properties (legacy behavior)
                checkboxes.forEach(checkbox => {
                    const propName = checkbox.dataset.propName;
                    const propType = checkbox.dataset.propType;
                    const propDesc = checkbox.dataset.propDesc;
                    const idx = checkbox.id.split('_').pop();
                    const isRequired = document.getElementById(`req_${className}_${idx}`).checked;

                    const schema = mapSignatureTypeToSchema(propType);
                    tools[index].inputSchema.properties[propName] = {
                        type: schema.type || 'string',
                        ...(schema.items ? { items: schema.items } : {}),
                        description: propDesc || ''
                    };

                    if (isRequired && !tools[index].inputSchema.required.includes(propName)) {
                        tools[index].inputSchema.required.push(propName);
                    }

                addedCount++;
            });
        }

        closeModal('propertyModal');
        renderToolEditor(tools[index], index);
        showNotification(`${addedCount} properties added successfully${targetPropName ? ` to "${targetPropName}"` : ''}`, 'success');
    }
}

function mapToJsonSchemaType(type) {
    // Map Python/graph_types types to JSON Schema types
    const typeMap = {
        'string': 'string',
        'str': 'string',
        'integer': 'integer',
        'int': 'integer',
        'number': 'number',
        'float': 'number',
        'boolean': 'boolean',
        'bool': 'boolean',
        'array': 'array',
        'object': 'object',
        'any': 'string'
    };
    return typeMap[type] || 'string';
}

function mapSignatureTypeToSchema(typeStr) {
    if (!typeStr) {
        return { type: 'string' };
    }

    let optional = false;
    let innerType = String(typeStr).trim();

    if (innerType.startsWith('Optional[') && innerType.endsWith(']')) {
        optional = true;
        innerType = innerType.slice(9, -1).trim();
    }

    if ((innerType.startsWith('List[') || innerType.startsWith('list[')) && innerType.endsWith(']')) {
        const itemType = innerType.slice(5, -1).trim();
        const mapped = mapSignatureTypeToSchema(itemType);
        return {
            type: 'array',
            items: { type: mapped.type || 'string' },
            optional
        };
    }

    // Dict[...] is treated as object
    if ((innerType.startsWith('Dict[') || innerType.startsWith('dict[')) && innerType.endsWith(']')) {
        return { type: 'object', optional };
    }

    const typeMap = {
        // Python primitives
        'str': 'string',
        'int': 'integer',
        'float': 'number',
        'bool': 'boolean',
        // JSON Schema primitives (types_property_* uses these)
        'string': 'string',
        'integer': 'integer',
        'number': 'number',
        'boolean': 'boolean',
        'object': 'object',
        'array': 'array',
        // Typing/aliases
        'Any': 'string',
        'any': 'string',
        'None': 'null'
    };

    if (typeMap[innerType]) {
        return { type: typeMap[innerType], optional };
    }

    // Likely a custom class/model type (e.g., mstEmployee, FilterParams, etc.)
    // Check if it exists in graphTypesProperties
    if (/^[a-zA-Z][a-zA-Z0-9]*$/.test(innerType)) {
        // Check if this type exists in the loaded types
        const typeExists = window.graphTypesProperties?.classes?.some(
            cls => (cls.name || cls) === innerType
        );

        if (typeExists) {
            // This is a known model type - set baseModel for nested property lookup
            return {
                type: 'object',
                baseModel: innerType,
                description: `${innerType} parameters`,
                optional
            };
        }

        // Fallback: *Params classes are treated as object models even if not in types
        const isModel = innerType.endsWith('Params') || ['FilterParams', 'ExcludeParams', 'SelectParams'].includes(innerType);
        if (isModel) {
            return {
                type: 'object',
                baseModel: innerType,
                description: `${innerType} parameters`,
                optional
            };
        }
        // Otherwise treat as a string (likely an Enum)
        return { type: 'string', optional };
    }

    return { type: 'string', optional };
}

function applySignatureDefaults(index, serviceName) {
    if (!serviceName || !window.mcpServiceDetails) {
        return;
    }

    const detail = window.mcpServiceDetails.find(svc => svc.name === serviceName);
    if (!detail || !Array.isArray(detail.parameters)) {
        return;
    }

    const tool = tools[index];
    if (!tool.inputSchema) {
        tool.inputSchema = { type: 'object', properties: {}, required: [] };
    }

    // Always overwrite with new service method parameters

    tool.inputSchema.type = 'object';
    tool.inputSchema.properties = {};
    tool.inputSchema.required = [];

    detail.parameters.forEach(param => {
        if (!param || param.name === 'self') {
            return;
        }

        // Use class_name (Python) or jsdoc_type (JavaScript) for type mapping
        const displayType = param.class_name || param.jsdoc_type || param.type;
        const schema = mapSignatureTypeToSchema(displayType);
        const propDef = {
            type: schema.type || 'string',
            description: schema.description || ''
        };
        if (schema.items) {
            propDef.items = schema.items;
        }
        if (schema.baseModel) {
            propDef.baseModel = schema.baseModel;
        }
        tool.inputSchema.properties[param.name] = propDef;

        const isOptional = typeof param.is_optional === 'boolean'
            ? param.is_optional
            : (typeof param.is_required === 'boolean'
                ? !param.is_required
                : (param.has_default ? true : !!schema.optional));
        const isRequired = typeof param.is_required === 'boolean' ? param.is_required : !isOptional;
        if (isRequired) {
            if (!tool.inputSchema.required.includes(param.name)) {
                tool.inputSchema.required.push(param.name);
            }
        }
    });

    showNotification(`Input schema pre-filled from ${serviceName} signature`, 'success');
}

function getTargetPropertyForGraphType(className, tool) {
    const mapping = {
        'FilterParams': ['filter'],
        'ExcludeParams': ['exclude', 'client_filter'],
        'SelectParams': ['select']
    };

    const candidates = mapping[className];
    if (!candidates || candidates.length === 0) {
        return null;
    }

    const internalProps = internalArgs[tool.name] || {};
    const schemaProps = tool.inputSchema?.properties || {};

    // Prefer an existing property match
    for (const candidate of candidates) {
        if (schemaProps[candidate] || internalProps[candidate]) {
            return candidate;
        }
    }

    // Otherwise, use the primary candidate to create a new object
    return candidates[0];
}

function renameSchemaProperty(index, oldName, newName, inputElement) {
    // Trim and validate new name
    newName = newName.trim();

    // If name hasn't changed, do nothing
    if (oldName === newName) {
        return;
    }

    // Validate new name
    if (!newName) {
        showNotification('Property name cannot be empty', 'error');
        inputElement.value = oldName;
        return;
    }

    // Check for invalid characters (only allow alphanumeric and underscore)
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(newName)) {
        showNotification('Property name must start with a letter or underscore and contain only alphanumeric characters and underscores', 'error');
        inputElement.value = oldName;
        return;
    }

    const tool = tools[index];
    const toolName = tool.name;

    // Check if new name already exists
    if (tool.inputSchema.properties[newName] && newName !== oldName) {
        showNotification(`Property "${newName}" already exists`, 'error');
        inputElement.value = oldName;
        return;
    }

    // Check if it's an internal property
    const isInternal = !tool.inputSchema.properties[oldName] && internalArgs[toolName]?.[oldName];

    if (isInternal) {
        // Rename in internalArgs
        if (internalArgs[toolName] && internalArgs[toolName][oldName]) {
            internalArgs[toolName][newName] = internalArgs[toolName][oldName];
            delete internalArgs[toolName][oldName];
        }
    } else {
        // Rename in inputSchema.properties
        if (tool.inputSchema.properties[oldName]) {
            tool.inputSchema.properties[newName] = tool.inputSchema.properties[oldName];
            delete tool.inputSchema.properties[oldName];

            // Update required array if needed
            if (tool.inputSchema.required) {
                const reqIndex = tool.inputSchema.required.indexOf(oldName);
                if (reqIndex !== -1) {
                    tool.inputSchema.required[reqIndex] = newName;
                }
            }
        }
    }

    // Update the data-original-name attribute for future renames
    inputElement.dataset.originalName = newName;

    // Re-render the tool editor to reflect changes
    renderToolEditor(tool, index);
    showNotification(`Property renamed from "${oldName}" to "${newName}"`, 'success');
}

function removeProperty(index, propName) {
    if (confirm(`Remove property "${propName}"?`)) {
        const tool = tools[index];
        const toolName = tool.name;

        // Remove from inputSchema.properties if present
        delete tool.inputSchema.properties[propName];

        // Remove from required if present
        if (tool.inputSchema.required) {
            tool.inputSchema.required = tool.inputSchema.required.filter(r => r !== propName);
        }

        // CRITICAL: Also remove from internalArgs if present (Issue 9 fix)
        if (internalArgs[toolName]?.[propName]) {
            delete internalArgs[toolName][propName];
            // Clean up empty tool entry
            if (Object.keys(internalArgs[toolName]).length === 0) {
                delete internalArgs[toolName];
            }
            showNotification(`Property "${propName}" removed from both schema and internal args`, 'info');
        }

        renderToolEditor(tool, index);
    }
}

// ============================================================
// Nested Properties Tab & JSON Editor Functions
// ============================================================

// Switch between GUI and JSON tabs with auto-sync
function switchNestedTab(index, propName, tab) {
    const safeId = propName.replace(/[^a-zA-Z0-9]/g, '_');
    const jsonEditor = document.getElementById(`nested-json-editor-${index}-${safeId}`);
    const guiEditor = document.getElementById(`nested-gui-editor-${index}-${safeId}`);
    const guiBtn = document.getElementById(`tab-gui-${index}-${safeId}`);
    const jsonBtn = document.getElementById(`tab-json-${index}-${safeId}`);
    const textarea = document.getElementById(`nested-json-textarea-${index}-${safeId}`);

    if (!jsonEditor || !guiEditor) {
        console.error('Tab containers not found for:', propName);
        return;
    }

    const tool = tools[index];
    const toolName = tool.name;
    const isInternal = !tool.inputSchema?.properties?.[propName] && internalArgs[toolName]?.[propName];

    if (tab === 'json') {
        // Switching to JSON: sync GUI → JSON
        let properties = {};
        if (isInternal) {
            properties = internalArgs[toolName][propName].original_schema?.properties || {};
        } else {
            const propDef = tool.inputSchema?.properties?.[propName];
            properties = propDef?.properties || {};
        }
        textarea.value = JSON.stringify(properties, null, 2);

        // Show JSON, hide GUI
        jsonEditor.style.display = 'block';
        guiEditor.style.display = 'none';

        // Update tab button styles
        jsonBtn.style.background = 'var(--primary-color)';
        jsonBtn.style.color = 'white';
        guiBtn.style.background = '#f5f5f5';
        guiBtn.style.color = '#666';
    } else {
        // Switching to GUI: sync JSON → GUI (auto-apply)
        try {
            const jsonText = textarea.value.trim();
            if (jsonText) {
                const newProperties = JSON.parse(jsonText);

                // Validate structure
                if (typeof newProperties !== 'object' || Array.isArray(newProperties)) {
                    throw new Error('Properties must be an object');
                }

                // Apply to data model
                if (isInternal) {
                    if (!internalArgs[toolName][propName].original_schema) {
                        internalArgs[toolName][propName].original_schema = { type: 'object' };
                    }
                    internalArgs[toolName][propName].original_schema.properties = newProperties;
                } else {
                    if (!tool.inputSchema.properties[propName]) {
                        tool.inputSchema.properties[propName] = { type: 'object' };
                    }
                    tool.inputSchema.properties[propName].properties = newProperties;

                    // Sync to signatureDefaults if enabled
                    if (signatureDefaults[toolName]?.[propName]) {
                        signatureDefaults[toolName][propName].properties = JSON.parse(JSON.stringify(newProperties));
                    }
                }
            }
        } catch (e) {
            showNotification(`JSON parse error: ${e.message}`, 'error');
            // Stay on JSON tab if error
            return;
        }

        // Re-render GUI and stay on GUI tab
        renderToolEditor(tool, index);

        // After re-render, ensure GUI tab is visible
        setTimeout(() => {
            const newJsonEditor = document.getElementById(`nested-json-editor-${index}-${safeId}`);
            const newGuiEditor = document.getElementById(`nested-gui-editor-${index}-${safeId}`);
            const newGuiBtn = document.getElementById(`tab-gui-${index}-${safeId}`);
            const newJsonBtn = document.getElementById(`tab-json-${index}-${safeId}`);

            if (newJsonEditor) newJsonEditor.style.display = 'none';
            if (newGuiEditor) newGuiEditor.style.display = 'block';
            if (newGuiBtn) {
                newGuiBtn.style.background = 'var(--primary-color)';
                newGuiBtn.style.color = 'white';
            }
            if (newJsonBtn) {
                newJsonBtn.style.background = '#f5f5f5';
                newJsonBtn.style.color = '#666';
            }
        }, 10);
    }
}

// Legacy toggle function (kept for compatibility)
function toggleNestedJsonEditor(index, propName) {
    const safeId = propName.replace(/[^a-zA-Z0-9]/g, '_');
    const editorDiv = document.getElementById(`nested-json-editor-${index}-${safeId}`);

    if (!editorDiv) {
        console.error('JSON editor not found for:', propName);
        return;
    }

    if (editorDiv.style.display === 'none') {
        switchNestedTab(index, propName, 'json');
    } else {
        switchNestedTab(index, propName, 'gui');
    }
}

function applyNestedJsonEdit(index, propName) {
    const safeId = propName.replace(/[^a-zA-Z0-9]/g, '_');
    const textarea = document.getElementById(`nested-json-textarea-${index}-${safeId}`);
    const editorDiv = document.getElementById(`nested-json-editor-${index}-${safeId}`);

    if (!textarea) {
        console.error('Textarea not found for:', propName);
        return;
    }

    try {
        const newProperties = JSON.parse(textarea.value);

        // Validate structure
        if (typeof newProperties !== 'object' || Array.isArray(newProperties)) {
            throw new Error('Properties must be an object');
        }

        // Validate each property has at least a type
        for (const [key, value] of Object.entries(newProperties)) {
            if (typeof value !== 'object' || !value.type) {
                throw new Error(`Property "${key}" must have a "type" field`);
            }
        }

        // Apply to tool
        const tool = tools[index];
        const toolName = tool.name;

        // Check if this is an internal property
        const isInternal = !tool.inputSchema?.properties?.[propName] && internalArgs[toolName]?.[propName];

        if (isInternal) {
            // Update internalArgs.original_schema.properties
            if (!internalArgs[toolName][propName].original_schema) {
                internalArgs[toolName][propName].original_schema = { type: 'object' };
            }
            internalArgs[toolName][propName].original_schema.properties = newProperties;
            console.log('[DEBUG] Updated internal arg properties:', toolName, propName);
        } else {
            // Update inputSchema.properties
            if (!tool.inputSchema.properties[propName]) {
                tool.inputSchema.properties[propName] = { type: 'object' };
            }
            tool.inputSchema.properties[propName].properties = newProperties;

            // Also sync to signatureDefaults if enabled
            if (signatureDefaults[toolName]?.[propName]) {
                signatureDefaults[toolName][propName].properties = JSON.parse(JSON.stringify(newProperties));
                console.log('[DEBUG] Synced JSON edit to signatureDefaults:', toolName, propName);
            }
        }

        // Hide editor and re-render
        editorDiv.style.display = 'none';
        renderToolEditor(tool, index);
        showNotification(`Nested properties updated for "${propName}"`, 'success');

    } catch (e) {
        showNotification(`Invalid JSON: ${e.message}`, 'error');
    }
}

function copyNestedJsonToClipboard(index, propName) {
    const safeId = propName.replace(/[^a-zA-Z0-9]/g, '_');
    const textarea = document.getElementById(`nested-json-textarea-${index}-${safeId}`);

    if (!textarea) {
        console.error('Textarea not found for:', propName);
        return;
    }

    navigator.clipboard.writeText(textarea.value).then(() => {
        showNotification('Nested properties JSON copied to clipboard', 'success');
    }).catch(err => {
        console.error('Failed to copy:', err);
        showNotification('Failed to copy to clipboard', 'error');
    });
}
