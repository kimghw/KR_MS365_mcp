/* Tool Editor Debug - Debug Indexing Functions */

function initDebugIndexing() {
    ensureDebugOverlay();
    const saved = localStorage.getItem('mcp_debug_indexes') === '1';
    setDebugIndexState(saved);

    document.addEventListener('scroll', queueDebugIndexRefresh, true);
    window.addEventListener('resize', queueDebugIndexRefresh);
    document.addEventListener('mousemove', updateDebugTooltip);
}

function toggleDebugIndexes() {
    setDebugIndexState(!debugIndexEnabled);
}

function setDebugIndexState(enabled) {
    debugIndexEnabled = enabled;
    document.body.classList.toggle('debug-indexes', enabled);
    localStorage.setItem('mcp_debug_indexes', enabled ? '1' : '0');

    const toggle = document.getElementById('debugIndexToggle');
    if (toggle) {
        toggle.classList.toggle('btn-debug-active', enabled);
        toggle.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }

    if (enabled) {
        queueDebugIndexRefresh();
    } else {
        const overlay = document.getElementById('debug-overlay');
        if (overlay) {
            overlay.innerHTML = '';
        }
        hideDebugTooltip();
        updateDebugDuplicateBadge(0);
    }
}

function ensureDebugOverlay() {
    let overlay = document.getElementById('debug-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'debug-overlay';
        document.body.appendChild(overlay);
    }

    let tooltip = document.getElementById('debug-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'debug-tooltip';
        document.body.appendChild(tooltip);
    }

    if (!debugIndexObserver) {
        debugIndexObserver = new MutationObserver(() => {
            debugMetadataDirty = true;
            queueDebugIndexRefresh();
        });
        debugIndexObserver.observe(document.body, { childList: true, subtree: true });
    }

    return overlay;
}

function queueDebugIndexRefresh() {
    if (!debugIndexEnabled || debugIndexRefreshPending) {
        return;
    }

    debugIndexRefreshPending = true;
    requestAnimationFrame(() => {
        debugIndexRefreshPending = false;
        refreshDebugIndexes();
    });
}

function refreshDebugIndexes() {
    if (!debugIndexEnabled) {
        return;
    }

    const overlay = ensureDebugOverlay();
    overlay.innerHTML = '';

    const targets = getDebugTargets();
    const usedIds = new Set();
    const idCounts = new Map();
    const buttonCounter = { value: 1 };
    const fieldCounter = { value: 1 };

    targets.areas.forEach(target => {
        const explicitId = getExplicitDebugId(target);
        const isAuto = !explicitId;
        const labelText = explicitId || getNextAutoDebugId('a', usedIds, { value: 1 });
        registerDebugId(labelText, usedIds, idCounts, target);
        addDebugLabel(overlay, target, labelText, 'area', isAuto);
    });

    targets.buttons.forEach(target => {
        const explicitId = getExplicitDebugId(target);
        const isAuto = !explicitId;
        const labelText = explicitId || getNextAutoDebugId('', usedIds, buttonCounter);
        registerDebugId(labelText, usedIds, idCounts, target);
        addDebugLabel(overlay, target, labelText, 'button', isAuto);
    });

    targets.fields.forEach(target => {
        const explicitId = getExplicitDebugId(target);
        const isAuto = !explicitId;
        const labelText = explicitId || getNextAutoDebugId('f', usedIds, fieldCounter);
        registerDebugId(labelText, usedIds, idCounts, target);
        addDebugLabel(overlay, target, labelText, 'field', isAuto);
    });

    const duplicateCount = Array.from(idCounts.values()).filter(count => count > 1).length;
    updateDebugDuplicateBadge(duplicateCount);
    debugMetadataDirty = false;
}

function ensureDebugMetadata() {
    if (!debugMetadataDirty) {
        return;
    }

    const targets = getDebugTargets();
    const usedIds = new Set();
    const buttonCounter = { value: 1 };
    const fieldCounter = { value: 1 };

    targets.areas.forEach(target => {
        const explicitId = getExplicitDebugId(target);
        const isAuto = !explicitId;
        const labelText = explicitId || getNextAutoDebugId('a', usedIds, { value: 1 });
        usedIds.add(labelText);
        applyDebugMetadata(target, labelText, isAuto);
    });

    targets.buttons.forEach(target => {
        const explicitId = getExplicitDebugId(target);
        const isAuto = !explicitId;
        const labelText = explicitId || getNextAutoDebugId('', usedIds, buttonCounter);
        usedIds.add(labelText);
        applyDebugMetadata(target, labelText, isAuto);
    });

    targets.fields.forEach(target => {
        const explicitId = getExplicitDebugId(target);
        const isAuto = !explicitId;
        const labelText = explicitId || getNextAutoDebugId('f', usedIds, fieldCounter);
        usedIds.add(labelText);
        applyDebugMetadata(target, labelText, isAuto);
    });

    debugMetadataDirty = false;
}

function getDebugTargets() {
    const buttons = Array.from(document.querySelectorAll('button')).filter(isValidDebugTarget);
    const fields = Array.from(document.querySelectorAll('input, textarea, select'))
        .filter(isTextLikeInput)
        .filter(isValidDebugTarget);
    const areas = [];
    const manualTargets = Array.from(document.querySelectorAll('[data-debug-id]')).filter(isValidDebugTarget);
    const buttonSet = new Set(buttons);
    const fieldSet = new Set(fields);

    manualTargets.forEach(target => {
        if (buttonSet.has(target) || fieldSet.has(target)) {
            return;
        }

        const debugId = target.getAttribute('data-debug-id');
        if (debugId && debugId.startsWith('AREA_')) {
            areas.push(target);
            return;
        }

        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
            fields.push(target);
            fieldSet.add(target);
        } else {
            buttons.push(target);
            buttonSet.add(target);
        }
    });

    return { buttons, fields, areas };
}

function getExplicitDebugId(target) {
    const manualId = target.getAttribute('data-debug-id');
    if (manualId && manualId.trim() && target.getAttribute('data-debug-auto') !== '1') {
        return manualId.trim();
    }

    const legacyId = target.getAttribute('data-fixed-debug-id');
    if (legacyId && legacyId.trim()) {
        return legacyId.trim();
    }

    return null;
}

function registerDebugId(labelText, usedIds, idCounts, target) {
    if (usedIds.has(labelText)) {
        console.warn(`[DebugIndex] Duplicate data-debug-id "${labelText}"`, target);
    }
    usedIds.add(labelText);
    idCounts.set(labelText, (idCounts.get(labelText) || 0) + 1);
}

function updateDebugDuplicateBadge(duplicateCount) {
    const badge = document.getElementById('debugDuplicateBadge');
    if (!badge) {
        return;
    }

    if (duplicateCount > 0) {
        badge.textContent = String(duplicateCount);
        badge.classList.add('visible');
        badge.setAttribute('aria-label', `Duplicate debug IDs: ${duplicateCount}`);
    } else {
        badge.textContent = '';
        badge.classList.remove('visible');
        badge.removeAttribute('aria-label');
    }
}

function getNextAutoDebugId(prefix, usedIds, counterRef) {
    let candidate = '';
    do {
        candidate = `${prefix}${counterRef.value}`;
        counterRef.value += 1;
    } while (usedIds.has(candidate));
    return candidate;
}

function isTextLikeInput(el) {
    if (!el || !el.tagName) {
        return false;
    }

    if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
        return true;
    }

    if (el.tagName !== 'INPUT') {
        return false;
    }

    const type = (el.getAttribute('type') || 'text').toLowerCase();
    return !['checkbox', 'radio', 'button', 'submit', 'reset', 'hidden', 'image', 'file', 'range', 'color'].includes(type);
}

function isValidDebugTarget(el) {
    if (!el || !(el instanceof Element)) {
        return false;
    }

    if (el.closest('#debug-overlay') || el.closest('#debug-tooltip')) {
        return false;
    }

    if (el.hasAttribute('data-debug-skip') || el.closest('[data-debug-skip="true"]')) {
        return false;
    }

    return true;
}

function applyDebugMetadata(target, labelText, isAuto) {
    if (!target || !labelText) {
        return;
    }

    if (isAuto) {
        target.setAttribute('data-debug-auto', '1');
        target.setAttribute('data-debug-auto-id', labelText);
        target.removeAttribute('data-debug-id');
    } else {
        target.removeAttribute('data-debug-auto');
        target.removeAttribute('data-debug-auto-id');
        target.setAttribute('data-debug-id', labelText);
    }

    const actions = getDebugActions(target);
    if (actions.length > 0) {
        target.setAttribute('data-debug-actions', actions.join('\n'));
    } else {
        target.removeAttribute('data-debug-actions');
    }
}

function addDebugLabel(overlay, target, labelText, kind, isAuto) {
    if (!target || !labelText) {
        return;
    }

    applyDebugMetadata(target, labelText, isAuto);

    const rect = target.getBoundingClientRect();
    if (!isRectVisible(rect)) {
        return;
    }

    const label = document.createElement('div');
    label.className = `debug-id-label ${kind}`;
    label.textContent = labelText;
    overlay.appendChild(label);
    positionDebugLabel(label, rect);
}

function getDebugActions(target) {
    const attributes = [
        'onclick',
        'onchange',
        'oninput',
        'onkeyup',
        'onkeydown',
        'onfocus',
        'onblur',
        'onmouseenter',
        'onmouseleave',
        'onmouseover',
        'onmouseout'
    ];

    const actions = [];
    attributes.forEach(attr => {
        const value = target.getAttribute(attr);
        if (value) {
            actions.push(`${attr}: ${value.trim().replace(/\s+/g, ' ')}`);
        }
    });

    return actions;
}

function isRectVisible(rect) {
    if (!rect) {
        return false;
    }

    if (rect.width < 1 && rect.height < 1) {
        return false;
    }

    return !(rect.bottom < 0 || rect.right < 0 || rect.top > window.innerHeight || rect.left > window.innerWidth);
}

function positionDebugLabel(label, rect) {
    const offset = 4;
    let left = rect.left + offset;
    let top = rect.top + offset;

    label.style.left = `${left}px`;
    label.style.top = `${top}px`;

    const labelRect = label.getBoundingClientRect();
    if (labelRect.right > window.innerWidth - 4) {
        left = window.innerWidth - labelRect.width - 4;
    }
    if (labelRect.bottom > window.innerHeight - 4) {
        top = window.innerHeight - labelRect.height - 4;
    }

    label.style.left = `${Math.max(4, left)}px`;
    label.style.top = `${Math.max(4, top)}px`;
}

function updateDebugTooltip(event) {
    if (!debugIndexEnabled) {
        ensureDebugMetadata();
    }

    const target = event.target instanceof Element
        ? event.target.closest('[data-debug-id], [data-debug-auto-id], [data-fixed-debug-id]')
        : null;
    if (!target || !isValidDebugTarget(target)) {
        hideDebugTooltip();
        return;
    }

    const debugId = getExplicitDebugId(target) || target.getAttribute('data-debug-auto-id');
    if (!debugId) {
        hideDebugTooltip();
        return;
    }

    const actions = target.getAttribute('data-debug-actions');
    const tooltip = document.getElementById('debug-tooltip');
    if (!tooltip) {
        return;
    }

    tooltip.textContent = actions ? `ID: ${debugId}\n${actions}` : `ID: ${debugId}`;
    tooltip.style.display = 'block';

    let left = event.clientX + 12;
    let top = event.clientY + 12;

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;

    const rect = tooltip.getBoundingClientRect();
    if (rect.right > window.innerWidth - 8) {
        left = window.innerWidth - rect.width - 8;
    }
    if (rect.bottom > window.innerHeight - 8) {
        top = window.innerHeight - rect.height - 8;
    }

    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
}

function hideDebugTooltip() {
    const tooltip = document.getElementById('debug-tooltip');
    if (tooltip) {
        tooltip.style.display = 'none';
        tooltip.textContent = '';
    }
}
