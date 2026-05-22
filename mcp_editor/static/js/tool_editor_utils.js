/* Tool Editor Utils - Notifications, Modals, UI Helpers */

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

function toggleNestedPropCollapse(nestedPropId) {
    const content = document.getElementById(`nested-content-${nestedPropId}`);
    const icon = document.getElementById(`nested-icon-${nestedPropId}`);

    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.textContent = '▼';
    } else {
        content.style.display = 'none';
        icon.textContent = '▶';
    }
}

function openRawJsonModal(index) {
    const tool = tools[index];
    const modal = document.getElementById('rawJsonModal');
    const content = document.getElementById('rawJsonContent');

    if (content) {
        content.textContent = JSON.stringify(tool, null, 2);
    }

    if (modal) {
        modal.classList.add('show');
    }
}

function copyJsonToClipboard() {
    const content = document.getElementById('rawJsonContent');
    if (content) {
        const text = content.textContent;
        navigator.clipboard.writeText(text).then(() => {
            showNotification('JSON copied to clipboard', 'success');
        }).catch(err => {
            console.error('Failed to copy:', err);
            showNotification('Failed to copy to clipboard', 'error');
        });
    }
}

function expandAllProperties() {
    const allProperties = document.querySelectorAll('.property-collapse-content');
    const allIcons = document.querySelectorAll('.property-collapse-header .collapse-icon');
    const allHeaders = document.querySelectorAll('.property-collapse-header');

    allProperties.forEach(prop => prop.classList.remove('collapsed'));
    allIcons.forEach(icon => { icon.classList.remove('collapsed'); icon.textContent = '▼'; });
    allHeaders.forEach(header => header.classList.add('expanded'));
}

function collapseAllProperties() {
    const allProperties = document.querySelectorAll('.property-collapse-content');
    const allIcons = document.querySelectorAll('.property-collapse-header .collapse-icon');
    const allHeaders = document.querySelectorAll('.property-collapse-header');

    allProperties.forEach(prop => prop.classList.add('collapsed'));
    allIcons.forEach(icon => { icon.classList.add('collapsed'); icon.textContent = '▶'; });
    allHeaders.forEach(header => header.classList.remove('expanded'));
}
