/**
 * MCP Tool Editor - Core Module
 * 핵심 상태 관리 및 초기화
 */

// 전역 상태 관리
window.MCPEditor = {
    // 상태 변수
    state: {
        tools: [],
        internalArgs: {},  // Internal args (hidden from MCP signature)
        fileMtimes: {},    // File modification times for conflict detection
        currentToolIndex: -1,
        nestedGraphTarget: null,
        currentProfile: '',
        profiles: [],
        profileDetails: {},  // Profile details (source_dir, base_mcp, etc.)
        generatorModules: [],
        generatorFallback: {},
        templateSources: [],  // Available template files (current, backups, other profiles)
        originalProfile: '',  // The profile that tools were originally loaded from (for saving)
        debugIndexEnabled: false,
        debugIndexObserver: null,
        debugIndexRefreshPending: false,
        debugMetadataDirty: true
    },

    // 설정 (하드코딩 제거)
    config: {
        defaultServer: null,  // API에서 로드
        typeSource: null,     // 'outlook_types.py' 대신 동적 로드
        templatePath: null    // 절대 경로 대신 동적 로드
    },

    // 초기화 함수
    async init() {
        console.log('[DEBUG] MCPEditor.init() started');

        // 설정 로드
        await this.loadConfig();

        // 프로파일 로드
        await this.loadProfiles();

        // 디버그 인덱싱 초기화
        this.initDebugIndexing();

        // 서버 상태 체크
        this.checkServerStatus();

        // 자동 새로고침 설정
        setInterval(() => this.checkServerStatus(), 5000);

        console.log('[DEBUG] MCPEditor.init() completed');
    },

    // 설정 로드 (하드코딩 제거)
    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            if (response.ok) {
                const config = await response.json();

                // 기본 서버 설정 (outlook 하드코딩 제거)
                this.config.defaultServer = config.defaultServer || null;

                // 타입 소스 설정 (outlook_types.py 하드코딩 제거)
                this.config.typeSource = config.typeSource || 'types.py';

                // 템플릿 경로 설정 (절대 경로 하드코딩 제거)
                this.config.templatePath = config.templatePath || 'templates/';

                console.log('[DEBUG] Config loaded:', this.config);
            }
        } catch (error) {
            console.warn('[DEBUG] Failed to load config, using defaults:', error);
            // API가 없을 경우 기본값 사용
            this.config.defaultServer = null;
            this.config.typeSource = 'types.py';
            this.config.templatePath = 'templates/';
        }
    },

    // 프로파일 로드
    async loadProfiles() {
        console.log('[DEBUG] Loading profiles...');
        try {
            const response = await fetch('/api/profiles');
            const data = await response.json();

            this.state.profiles = data.profiles || [];
            this.state.profileDetails = data.details || {};

            // 기본 서버 설정 (하드코딩 제거)
            if (!this.state.currentProfile && this.state.profiles.length > 0) {
                // config에서 기본 서버를 가져오거나, 첫 번째 프로파일 사용
                this.state.currentProfile = this.config.defaultServer || this.state.profiles[0];
            }

            // UI 업데이트는 UI 모듈에서 처리
            if (window.MCPEditorUI && window.MCPEditorUI.updateProfileSelector) {
                window.MCPEditorUI.updateProfileSelector();
            }

            // 툴 로드
            await this.loadTools();

        } catch (error) {
            console.error('[ERROR] Failed to load profiles:', error);
            this.showNotification('Failed to load profiles: ' + error.message, 'error');
        }
    },

    // 툴 로드
    async loadTools() {
        const profileQuery = this.profileParam();

        try {
            const response = await fetch(`/api/tools${profileQuery}`);
            const data = await response.json();

            this.state.tools = data.tools || [];
            this.state.internalArgs = data.internalArgs || {};
            this.state.fileMtimes = data.fileMtimes || {};
            this.state.generatorModules = data.generatorModules || [];
            this.state.generatorFallback = data.generatorFallback || {};

            // UI 업데이트
            if (window.MCPEditorUI && window.MCPEditorUI.renderTools) {
                window.MCPEditorUI.renderTools();
            }

            this.showNotification(`Loaded ${this.state.tools.length} tools`, 'success');

        } catch (error) {
            console.error('[ERROR] Failed to load tools:', error);
            this.showNotification('Failed to load tools: ' + error.message, 'error');
        }
    },

    // 서버 상태 체크
    async checkServerStatus() {
        try {
            const response = await fetch('/api/server-status');
            const data = await response.json();

            // UI 업데이트
            if (window.MCPEditorUI && window.MCPEditorUI.updateServerStatus) {
                window.MCPEditorUI.updateServerStatus(data);
            }

        } catch (error) {
            console.error('[ERROR] Failed to check server status:', error);
        }
    },

    // 디버그 인덱싱 초기화
    initDebugIndexing() {
        // 디버그 기능 구현
        console.log('[DEBUG] Debug indexing initialized');
    },

    // 유틸리티 함수
    profileParam() {
        return this.state.currentProfile ? `?profile=${encodeURIComponent(this.state.currentProfile)}` : '';
    },

    // 알림 표시
    showNotification(message, type = 'info') {
        if (window.MCPEditorUI && window.MCPEditorUI.showNotification) {
            window.MCPEditorUI.showNotification(message, type);
        } else {
            // 폴백: 콘솔 로그
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    },

    // 현재 서버 가져오기 (하드코딩 제거)
    getCurrentServer() {
        return this.state.currentProfile || this.config.defaultServer || this.state.profiles[0] || '';
    }
};

// 페이지 로드 시 초기화
window.onload = function() {
    MCPEditor.init();
};

// 전역 함수 호환성 (기존 코드와의 호환을 위해)
window.tools = MCPEditor.state.tools;
window.internalArgs = MCPEditor.state.internalArgs;
window.fileMtimes = MCPEditor.state.fileMtimes;
window.currentToolIndex = MCPEditor.state.currentToolIndex;
window.currentProfile = MCPEditor.state.currentProfile;
window.profiles = MCPEditor.state.profiles;

// 함수 래퍼 (기존 함수 호출 지원)
window.loadTools = () => MCPEditor.loadTools();
window.loadProfiles = () => MCPEditor.loadProfiles();
window.checkServerStatus = () => MCPEditor.checkServerStatus();
window.showNotification = (msg, type) => MCPEditor.showNotification(msg, type);