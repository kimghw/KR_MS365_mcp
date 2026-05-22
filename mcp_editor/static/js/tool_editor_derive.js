/**
 * 파생 서버 및 도구 이동 관련 기능
 */

// 파생 서버 생성
async function deriveProfile(baseProfile, newName, port) {
  const response = await fetch('/api/profiles/derive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      base_profile: baseProfile,
      new_profile_name: newName,
      port: port
    })
  });
  return response.json();
}

// 형제 프로필 조회
async function getSiblingProfiles(profile) {
  const response = await fetch(`/api/profiles/${profile}/siblings`);
  return response.json();
}

// 프로필 가족 관계 조회
async function getProfileFamily(profile) {
  const response = await fetch(`/api/profiles/${profile}/family`);
  return response.json();
}

// 도구 이동
async function moveTools(sourceProfile, targetProfile, toolIndices, mode) {
  const response = await fetch('/api/tools/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_profile: sourceProfile,
      target_profile: targetProfile,
      tool_indices: toolIndices,
      mode: mode
    })
  });
  return response.json();
}

// 이동 가능 여부 검증
async function validateMove(sourceProfile, targetProfile, toolIndices) {
  const response = await fetch('/api/tools/validate-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_profile: sourceProfile,
      target_profile: targetProfile,
      tool_indices: toolIndices
    })
  });
  return response.json();
}

// 이동 가능한 도구 목록 조회
async function getMovableTools(sourceProfile, targetProfile) {
  const response = await fetch(`/api/tools/movable?source=${sourceProfile}&target=${targetProfile}`);
  return response.json();
}

// 파생 서버 생성 모달 표시
function showDeriveModal(baseProfile) {
  // 기존 모달 사용 또는 새 모달 생성
  const modal = document.getElementById('derive-modal');
  if (modal) {
    document.getElementById('derive-base').value = baseProfile;
    modal.style.display = 'flex';
  }
}

// 파생 서버 생성 확인
async function confirmDerive() {
  const baseProfile = document.getElementById('derive-base').value;
  const newName = document.getElementById('derive-name').value.trim();
  const port = parseInt(document.getElementById('derive-port').value) || 8092;

  if (!newName) {
    alert('새 프로필 이름을 입력하세요.');
    return;
  }

  try {
    const result = await deriveProfile(baseProfile, newName, port);
    if (result.success) {
      alert(`파생 서버 '${newName}'가 생성되었습니다.`);
      document.getElementById('derive-modal').style.display = 'none';
      // 프로필 목록 새로고침
      if (typeof loadProfiles === 'function') {
        loadProfiles();
      }
    } else {
      alert('오류: ' + result.error);
    }
  } catch (e) {
    alert('오류: ' + e.message);
  }
}

// 모달 닫기
function closeDeriveModal() {
  document.getElementById('derive-modal').style.display = 'none';
}

function closeMoveModal() {
  document.getElementById('move-modal').style.display = 'none';
}

// 도구 이동 대화상자 열기 (체크박스 모드 활성화)
function openMoveToolsDialog() {
  // 도구 선택 모드 활성화
  window.toolSelectMode = !window.toolSelectMode;

  const btn = document.querySelector('[data-debug-id="BTN_MOVE_TOOLS"]');

  if (window.toolSelectMode) {
    // 선택 모드 활성화 - 버튼 스타일 변경
    if (btn) {
      btn.style.background = '#db2777';
      btn.style.color = 'white';
      btn.innerHTML = '<span class="material-icons" style="font-size: 16px;">check_circle</span> 선택 완료';
    }

    // 도구 목록에 체크박스 추가
    addToolCheckboxes();

    // 안내 메시지
    if (typeof showNotification === 'function') {
      showNotification('이동할 도구를 선택한 후 "선택 완료" 버튼을 클릭하세요', 'info');
    }
  } else {
    // 선택 모드 비활성화 - 선택된 도구로 이동 모달 표시
    if (btn) {
      btn.style.background = '#fce7f3';
      btn.style.color = '#db2777';
      btn.innerHTML = '<span class="material-icons" style="font-size: 16px;">drive_file_move</span> 도구 이동';
    }

    // 선택된 도구 인덱스 수집
    const selectedIndices = getSelectedToolIndices();

    if (selectedIndices.length === 0) {
      if (typeof showNotification === 'function') {
        showNotification('이동할 도구를 선택하세요', 'warning');
      } else {
        alert('이동할 도구를 선택하세요');
      }
      // 선택 모드 다시 활성화
      window.toolSelectMode = true;
      if (btn) {
        btn.style.background = '#db2777';
        btn.style.color = 'white';
        btn.innerHTML = '<span class="material-icons" style="font-size: 16px;">check_circle</span> 선택 완료';
      }
      return;
    }

    // 체크박스 제거
    removeToolCheckboxes();

    // 이동 모달 표시
    showMoveToolsModal(window.currentProfile, selectedIndices);
  }
}

// 도구 목록에 체크박스 추가
function addToolCheckboxes() {
  const toolItems = document.querySelectorAll('.tool-item');

  toolItems.forEach((item, index) => {
    // 이미 체크박스가 있으면 스킵
    if (item.querySelector('.tool-select')) return;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'tool-select';
    checkbox.dataset.toolIndex = index;
    checkbox.style.cssText = 'position: absolute; left: 8px; top: 50%; transform: translateY(-50%); width: 18px; height: 18px; cursor: pointer; z-index: 10;';
    checkbox.onclick = (e) => e.stopPropagation();

    // 상대 위치 지정을 위해 스타일 추가
    item.style.position = 'relative';
    item.style.paddingLeft = '36px';

    item.insertBefore(checkbox, item.firstChild);
  });
}

// 체크박스 제거
function removeToolCheckboxes() {
  const checkboxes = document.querySelectorAll('.tool-select');
  checkboxes.forEach(cb => {
    const item = cb.parentElement;
    if (item) {
      item.style.paddingLeft = '';
    }
    cb.remove();
  });
}

// 선택된 도구 인덱스 가져오기
function getSelectedToolIndices() {
  const indices = [];
  document.querySelectorAll('.tool-select:checked').forEach(cb => {
    indices.push(parseInt(cb.dataset.toolIndex));
  });
  return indices;
}

// 도구 이동 확인 (수정된 버전)
async function confirmMoveTools() {
  const sourceProfile = window.currentProfile;
  const targetProfile = document.getElementById('move-target').value;
  const mode = document.querySelector('input[name="move-mode"]:checked')?.value || 'move';

  if (!targetProfile) {
    alert('대상 프로필을 선택하세요.');
    return;
  }

  // 선택된 도구 인덱스 - 저장된 값 사용
  const selectedIndices = window.selectedToolIndices || [];

  if (selectedIndices.length === 0) {
    alert('이동할 도구를 선택하세요.');
    return;
  }

  try {
    const result = await moveTools(sourceProfile, targetProfile, selectedIndices, mode);
    if (result.success) {
      alert(`${result.moved_tools.length}개 도구가 ${mode === 'move' ? '이동' : '복사'}되었습니다.`);
      document.getElementById('move-modal').style.display = 'none';
      window.selectedToolIndices = [];
      // 도구 목록 새로고침
      if (typeof loadTools === 'function') {
        loadTools();
      }
    } else {
      alert('오류: ' + result.error);
    }
  } catch (e) {
    alert('오류: ' + e.message);
  }
}

// 도구 이동 모달 표시 (수정된 버전)
async function showMoveToolsModal(sourceProfile, selectedIndices) {
  const modal = document.getElementById('move-modal');
  if (!modal) return;

  // 선택된 인덱스 저장
  window.selectedToolIndices = selectedIndices;

  // 형제 프로필 로드
  try {
    const familyData = await getProfileFamily(sourceProfile);
    const siblings = familyData.derived || [];
    if (familyData.base && familyData.base !== sourceProfile) {
      siblings.unshift(familyData.base);
    }

    // 자신 제외
    const targets = siblings.filter(p => p !== sourceProfile);

    // 타겟 선택 드롭다운 업데이트
    const targetSelect = document.getElementById('move-target');
    if (targets.length > 0) {
      targetSelect.innerHTML = '<option value="">-- 대상 프로필 선택 --</option>' +
        targets.map(t => `<option value="${t}">${t}</option>`).join('');
    } else {
      targetSelect.innerHTML = '<option value="">파생된 프로필이 없습니다</option>';
    }
  } catch (e) {
    console.error('Failed to load profile family:', e);
    // 에러 시 전체 프로필 로드 시도
    try {
      const response = await fetch('/api/profiles');
      const profiles = await response.json();
      const targetSelect = document.getElementById('move-target');
      const targets = profiles.filter(p => p !== sourceProfile);
      targetSelect.innerHTML = '<option value="">-- 대상 프로필 선택 --</option>' +
        targets.map(t => `<option value="${t}">${t}</option>`).join('');
    } catch (e2) {
      console.error('Failed to load profiles:', e2);
    }
  }

  // 선택된 도구 수 표시
  document.getElementById('selected-count').textContent = selectedIndices.length;

  modal.style.display = 'flex';
}

// ========================================
// MCP 서버 삭제 관련 함수들
// ========================================

// 삭제할 프로필 이름 저장
let deleteTargetProfile = null;

// 프로필 상세 정보 조회
async function getProfileInfo(profile) {
  const response = await fetch(`/api/profiles/${profile}/info`);
  return response.json();
}

// MCP 서버 삭제 API 호출
async function deleteMcpServer(profileName, confirmText) {
  const response = await fetch('/api/delete-mcp-server', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      profile_name: profileName,
      confirm: confirmText
    })
  });
  return response.json();
}

// 삭제 모달 표시
async function showDeleteServerModal(profile) {
  if (!profile) {
    if (typeof showNotification === 'function') {
      showNotification('삭제할 프로필을 선택하세요', 'warning');
    } else {
      alert('삭제할 프로필을 선택하세요');
    }
    return;
  }

  const modal = document.getElementById('delete-server-modal');
  if (!modal) return;

  deleteTargetProfile = profile;

  // 프로필 정보 로드
  try {
    const info = await getProfileInfo(profile);

    // 보호된 프로필 확인
    if (info.is_protected) {
      if (typeof showNotification === 'function') {
        showNotification(`'${profile}'는 보호된 프로필입니다. 삭제할 수 없습니다.`, 'error');
      } else {
        alert(`'${profile}'는 보호된 프로필입니다. 삭제할 수 없습니다.`);
      }
      return;
    }

    // 모달 내용 업데이트
    document.getElementById('delete-target-profile').textContent = profile;

    // 삭제될 항목 업데이트
    const deleteList = document.getElementById('delete-items-list');
    deleteList.innerHTML = `
      <li><code>mcp_editor/mcp_${profile}/</code> (웹에디터 정의)</li>
      <li><code>mcp_${profile}/mcp_server/</code> (생성된 서버)</li>
      <li><code>registry_${profile}.json</code> (레지스트리)</li>
      <li><code>editor_config.json</code>에서 프로필 항목</li>
    `;

    // 유지될 항목 업데이트
    const keepList = document.getElementById('keep-items-list');
    if (info.paths && info.paths.service_files && info.paths.service_files.length > 0) {
      keepList.innerHTML = info.paths.service_files
        .map(f => `<li><code>mcp_${profile}/${f}</code></li>`)
        .join('');
    } else {
      keepList.innerHTML = `
        <li><code>${profile}_service.py</code> (서비스 로직)</li>
        <li><code>${profile}_types.py</code> (타입 정의)</li>
        <li>기타 서비스 파일들</li>
      `;
    }

    // 확인 코드 업데이트
    const confirmCode = `DELETE ${profile}`;
    document.getElementById('delete-confirm-code').textContent = confirmCode;
    document.getElementById('delete-confirm-input').value = '';
    document.getElementById('delete-confirm-input').placeholder = confirmCode;
    document.getElementById('delete-confirm-error').style.display = 'none';
    document.getElementById('delete-confirm-btn').disabled = true;

    // 입력 이벤트 리스너 추가
    const input = document.getElementById('delete-confirm-input');
    input.oninput = function() {
      const isValid = this.value === confirmCode;
      document.getElementById('delete-confirm-btn').disabled = !isValid;

      if (this.value && !isValid) {
        document.getElementById('delete-confirm-error').textContent =
          `입력값이 일치하지 않습니다. "${confirmCode}"를 정확히 입력하세요.`;
        document.getElementById('delete-confirm-error').style.display = 'block';
      } else {
        document.getElementById('delete-confirm-error').style.display = 'none';
      }
    };

    modal.style.display = 'flex';

  } catch (e) {
    console.error('Failed to load profile info:', e);
    if (typeof showNotification === 'function') {
      showNotification('프로필 정보를 불러올 수 없습니다: ' + e.message, 'error');
    } else {
      alert('프로필 정보를 불러올 수 없습니다: ' + e.message);
    }
  }
}

// 삭제 모달 닫기
function closeDeleteServerModal() {
  const modal = document.getElementById('delete-server-modal');
  if (modal) {
    modal.style.display = 'none';
  }
  deleteTargetProfile = null;
}

// 삭제 확인
async function confirmDeleteServer() {
  if (!deleteTargetProfile) {
    alert('삭제할 프로필이 지정되지 않았습니다.');
    return;
  }

  const confirmInput = document.getElementById('delete-confirm-input').value;
  const expectedConfirm = `DELETE ${deleteTargetProfile}`;

  if (confirmInput !== expectedConfirm) {
    document.getElementById('delete-confirm-error').textContent =
      `입력값이 일치하지 않습니다. "${expectedConfirm}"를 정확히 입력하세요.`;
    document.getElementById('delete-confirm-error').style.display = 'block';
    return;
  }

  // 삭제 버튼 비활성화 (중복 클릭 방지)
  const btn = document.getElementById('delete-confirm-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="material-icons" style="font-size: 18px;">hourglass_empty</span> 삭제 중...';

  try {
    const result = await deleteMcpServer(deleteTargetProfile, confirmInput);

    if (result.success) {
      closeDeleteServerModal();

      // 성공 메시지
      const message = `MCP 서버 '${deleteTargetProfile}'가 삭제되었습니다.\n\n` +
        `삭제된 항목:\n${result.deleted_paths.map(p => '  - ' + p).join('\n')}\n\n` +
        (result.kept_paths.length > 0
          ? `유지된 항목:\n${result.kept_paths.map(p => '  - ' + p).join('\n')}`
          : '');

      if (typeof showNotification === 'function') {
        showNotification(`MCP 서버 '${deleteTargetProfile}'가 삭제되었습니다.`, 'success');
      }

      // 상세 정보는 콘솔에 출력
      console.log('Delete result:', result);

      // 프로필 목록 새로고침
      if (typeof loadProfiles === 'function') {
        await loadProfiles();
      }

      // 다른 프로필로 전환
      setTimeout(() => {
        if (typeof loadProfiles === 'function') {
          location.reload();
        }
      }, 1500);

    } else {
      alert('삭제 오류: ' + result.error);
      btn.disabled = false;
      btn.innerHTML = '<span class="material-icons" style="font-size: 18px;">delete_forever</span> 삭제';
    }

  } catch (e) {
    console.error('Delete failed:', e);
    alert('삭제 중 오류가 발생했습니다: ' + e.message);
    btn.disabled = false;
    btn.innerHTML = '<span class="material-icons" style="font-size: 18px;">delete_forever</span> 삭제';
  }
}

// 전역 함수로 내보내기
window.deriveProfile = deriveProfile;
window.getSiblingProfiles = getSiblingProfiles;
window.getProfileFamily = getProfileFamily;
window.moveTools = moveTools;
window.validateMove = validateMove;
window.showDeriveModal = showDeriveModal;
window.showMoveToolsModal = showMoveToolsModal;
window.confirmDerive = confirmDerive;
window.confirmMoveTools = confirmMoveTools;
window.openMoveToolsDialog = openMoveToolsDialog;
window.addToolCheckboxes = addToolCheckboxes;
window.removeToolCheckboxes = removeToolCheckboxes;
window.getSelectedToolIndices = getSelectedToolIndices;

// 삭제 관련 함수 내보내기
window.showDeleteServerModal = showDeleteServerModal;
window.closeDeleteServerModal = closeDeleteServerModal;
window.confirmDeleteServer = confirmDeleteServer;
window.getProfileInfo = getProfileInfo;
window.deleteMcpServer = deleteMcpServer;

// ========================================
// MCP 서버 병합 관련 함수들
// ========================================

// 병합 모달 표시
async function showMergeServersModal() {
  const modal = document.getElementById('mergeServersModal');
  if (!modal) return;

  // 프로필 목록 로드
  try {
    const response = await fetch('/api/profiles');
    const data = await response.json();
    const profiles = data.profiles || [];

    // 프로필 체크박스 생성 (merged 프로필 제외)
    const container = document.getElementById('mergeSourceProfiles');
    if (container) {
      container.innerHTML = profiles
        .filter(p => {
          // merged 프로필 필터링 (is_merged 또는 이름에 merged 포함)
          return p && !p.includes('merged') && !p.includes('_test');
        })
        .map(profile => `
          <label style="display: flex; align-items: center; gap: 6px; padding: 6px 12px; background: white; border-radius: 4px; cursor: pointer; border: 1px solid #ddd;">
            <input type="checkbox" class="merge-profile-checkbox" value="${profile}">
            <span>${profile}</span>
          </label>
        `).join('');
    }

    // 결과 영역 초기화
    const resultEl = document.getElementById('mergeServersResult');
    if (resultEl) {
      resultEl.style.display = 'none';
      resultEl.textContent = '';
    }

    // 입력 필드 초기화
    document.getElementById('mergeServerName').value = '';
    document.getElementById('mergeServerPort').value = '8090';
    document.getElementById('mergePrefixMode').value = 'auto';
    document.getElementById('mergeProtocol').value = 'all';

    modal.classList.add('show');
  } catch (e) {
    console.error('Failed to load profiles for merge:', e);
    if (typeof showNotification === 'function') {
      showNotification('프로필 목록 로드 실패', 'error');
    }
  }
}

// 병합 실행
async function executeMergeServers() {
  const name = document.getElementById('mergeServerName').value.trim();
  const port = parseInt(document.getElementById('mergeServerPort').value) || 8090;
  const prefixMode = document.getElementById('mergePrefixMode').value;
  const protocol = document.getElementById('mergeProtocol').value;

  // 선택된 프로필 수집
  const selectedProfiles = [];
  document.querySelectorAll('.merge-profile-checkbox:checked').forEach(cb => {
    selectedProfiles.push(cb.value);
  });

  const resultEl = document.getElementById('mergeServersResult');

  // 유효성 검사
  if (!name) {
    resultEl.style.display = 'block';
    resultEl.style.backgroundColor = '#ffebee';
    resultEl.textContent = '병합 서버 이름을 입력하세요.';
    return;
  }

  if (!/^[a-zA-Z0-9_]+$/.test(name)) {
    resultEl.style.display = 'block';
    resultEl.style.backgroundColor = '#ffebee';
    resultEl.textContent = '서버 이름은 영문, 숫자, 언더스코어만 사용 가능합니다.';
    return;
  }

  if (selectedProfiles.length < 2) {
    resultEl.style.display = 'block';
    resultEl.style.backgroundColor = '#ffebee';
    resultEl.textContent = '병합할 프로필을 2개 이상 선택하세요.';
    return;
  }

  resultEl.style.display = 'block';
  resultEl.style.backgroundColor = '#e3f2fd';
  resultEl.innerHTML = '<span class="material-icons" style="font-size: 14px; vertical-align: middle; animation: spin 1s linear infinite;">sync</span> 서버 병합 중...';

  try {
    const response = await fetch('/api/merge-servers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        sources: selectedProfiles,
        port: port,
        prefix_mode: prefixMode,
        protocol: protocol
      })
    });

    const data = await response.json();

    if (data.success) {
      resultEl.style.backgroundColor = '#e8f5e9';
      resultEl.innerHTML = `
        <strong>병합 완료!</strong><br>
        생성된 서버: mcp_${name}<br>
        도구 수: ${data.tool_count || 'N/A'}<br>
        서비스 수: ${data.service_count || 'N/A'}<br><br>
        <strong>다음 단계:</strong><br>
        1. 페이지를 새로고침하여 새 프로필 확인<br>
        2. "${name}" 탭에서 도구 편집<br>
        3. "Generate Server"로 서버 코드 생성
      `;

      // 3초 후 자동 새로고침
      setTimeout(() => {
        location.reload();
      }, 3000);
    } else {
      resultEl.style.backgroundColor = '#ffebee';
      resultEl.textContent = '오류: ' + (data.error || '알 수 없는 오류');
    }
  } catch (e) {
    console.error('Merge failed:', e);
    resultEl.style.backgroundColor = '#ffebee';
    resultEl.textContent = '병합 실패: ' + e.message;
  }
}

// 병합 관련 함수 내보내기
window.showMergeServersModal = showMergeServersModal;
window.executeMergeServers = executeMergeServers;
