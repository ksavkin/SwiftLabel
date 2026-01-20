/**
 * SwiftLabel - Frontend Application
 *
 * Keyboard-first image classification tool.
 * All primary actions are accessible via keyboard shortcuts.
 *
 * @fileoverview Main application logic for SwiftLabel frontend
 * @version 1.0.0
 */

'use strict';

/* ============================================
   TYPE DEFINITIONS (JSDoc)
   ============================================ */

/**
 * @typedef {Object} ImageInfo
 * @property {string} id - Image identifier (relative path)
 * @property {string} filename - Just the filename without path
 * @property {number|null} label - Class index (0-9) or null if unlabeled
 * @property {string|null} class_name - Class name or null if unlabeled
 * @property {boolean} marked_for_deletion - Whether marked for deletion
 */

/**
 * @typedef {Object} SessionState
 * @property {string} version - Session format version
 * @property {string} working_directory - Absolute path to images
 * @property {string[]} classes - Ordered list of class names
 * @property {ImageInfo[]} images - All images in working directory
 * @property {number} current_index - Currently viewed image index
 * @property {Object[]} staged_changes - Pending uncommitted changes
 * @property {Object[]} undo_stack - Stack of undoable actions
 */

/**
 * @typedef {Object} Stats
 * @property {number} total_images - Total image count
 * @property {number} labeled_count - Labeled image count
 * @property {number} unlabeled_count - Unlabeled image count
 * @property {number} deleted_count - Deleted image count
 * @property {Object.<string, number>} per_class - Count per class name
 * @property {number} progress_percent - Progress as percentage
 */

/**
 * @typedef {Object} WSMessage
 * @property {string} type - Message type
 * @property {Object} [payload] - Message payload
 */

/**
 * @typedef {Object} PreviewSummary
 * @property {number} total_changes - Total pending changes
 * @property {Array} moves - Files to move
 * @property {Array} deletes - Files to delete
 * @property {string[]} warnings - Warnings
 */


/* ============================================
   CONFIGURATION
   ============================================ */

/** @type {Object} Application configuration */
const CONFIG = {
    /** Base URL for API calls */
    API_BASE: '/api',

    /** WebSocket URL */
    WS_URL: `ws://${window.location.host}/ws`,

    /** Number of images to prefetch ahead */
    PREFETCH_COUNT: 3,

    /** Maximum images to keep in cache */
    CACHE_MAX_SIZE: 10,

    /** Toast notification duration (ms) */
    TOAST_DURATION: 3000,

    /** WebSocket reconnect delays (ms) - exponential backoff */
    WS_RECONNECT_DELAYS: [1000, 2000, 4000, 8000, 16000, 30000],

    /** WebSocket heartbeat interval (ms) */
    WS_HEARTBEAT_INTERVAL: 30000,

    /** Timeout for gg (go to first) double-key combo (ms) */
    DOUBLE_KEY_TIMEOUT: 300,
};


/* ============================================
   MAIN APPLICATION CLASS
   ============================================ */

/**
 * Main SwiftLabel application class.
 * Manages state, WebSocket connection, keyboard handling, and UI updates.
 */
class SwiftLabelApp {
    constructor() {
        // ========== STATE ==========

        /** @type {SessionState|null} Current session state */
        this.session = null;

        /** @type {ImageInfo|null} Currently displayed image */
        this.currentImage = null;

        /** @type {Stats|null} Current statistics */
        this.stats = null;

        // ========== IMAGE CACHE ==========

        /** @type {Map<string, HTMLImageElement>} Image cache (LRU) */
        this.imageCache = new Map();

        /** @type {Set<string>} Images currently being prefetched */
        this.prefetchingImages = new Set();

        // ========== WEBSOCKET ==========

        /** @type {WebSocket|null} WebSocket connection */
        this.ws = null;

        /** @type {number} Current reconnect attempt */
        this.wsReconnectAttempt = 0;

        /** @type {number|null} Reconnect timeout ID */
        this.wsReconnectTimeout = null;

        /** @type {number|null} Heartbeat interval ID */
        this.wsHeartbeatInterval = null;

        // ========== UI STATE ==========

        /** @type {string|null} Currently open overlay ('help'|'stats'|'commit'|null) */
        this.activeOverlay = null;

        /** @type {boolean} Whether commit modal is in confirmation mode */
        this.commitPending = false;

        /** @type {PreviewSummary|null} Cached commit preview */
        this.commitPreview = null;

        // ========== KEYBOARD STATE ==========

        /** @type {boolean} Filter mode active (after pressing F) */
        this.filterMode = false;

        /** @type {string|null} Last key pressed (for combos like gg) */
        this.lastKey = null;

        /** @type {number|null} Timeout for key combo */
        this.keyComboTimeout = null;

        // ========== v2: FOLDER NAVIGATION ==========

        /** @type {string} Current subfolder path */
        this.currentFolder = '';

        /** @type {Array} Available subfolders */
        this.subfolders = [];

        /** @type {boolean} Whether dataset has subfolders */
        this.hasFolders = false;

        // ========== v2: FORMAT DETECTION ==========

        /** @type {string} Detected annotation format */
        this.detectedFormat = 'unknown';

        // ========== v2: CHANGE TRACKING ==========

        /** @type {number} User changes count */
        this.userChangesCount = 0;

        /** @type {boolean} Whether any changes pending */
        this.hasChanges = false;

        // ========== DOM REFERENCES ==========
        this.cacheDOM();

        // ========== INITIALIZATION ==========
        this.init();
    }


    /* ==========================================
       INITIALIZATION
       ========================================== */

    /**
     * Cache DOM element references for performance.
     * Called once during construction.
     */
    cacheDOM() {
        // Main elements
        this.dom = {
            // Image viewer
            currentImage: document.getElementById('current-image'),
            loadingSpinner: document.getElementById('loading-spinner'),
            deletedOverlay: document.getElementById('deleted-overlay'),
            currentFilename: document.getElementById('current-filename'),
            currentLabel: document.getElementById('current-label'),

            // Progress
            progressCounter: document.getElementById('progress-counter'),
            progressFill: document.getElementById('progress-fill'),
            progressPercent: document.getElementById('progress-percent'),

            // Action buttons
            classButtons: document.getElementById('class-buttons'),
            btnDelete: document.getElementById('btn-delete'),
            btnUndo: document.getElementById('btn-undo'),
            btnCommit: document.getElementById('btn-commit'),
            commitCount: document.getElementById('commit-count'),

            // Overlays
            helpOverlay: document.getElementById('help-overlay'),
            statsOverlay: document.getElementById('stats-overlay'),
            commitOverlay: document.getElementById('commit-overlay'),

            // Stats overlay elements
            statsProgressText: document.getElementById('stats-progress-text'),
            statsProgressFill: document.getElementById('stats-progress-fill'),
            distributionChart: document.getElementById('distribution-chart'),
            statsUnlabeled: document.getElementById('stats-unlabeled'),
            statsDeleted: document.getElementById('stats-deleted'),

            // Commit overlay elements
            commitTotal: document.getElementById('commit-total'),
            commitMoves: document.getElementById('commit-moves'),
            commitDeletes: document.getElementById('commit-deletes'),
            btnConfirmCommit: document.getElementById('btn-confirm-commit'),
            btnCancelCommit: document.getElementById('btn-cancel-commit'),

            // Notifications
            toastContainer: document.getElementById('toast-container'),
            connectionStatus: document.getElementById('connection-status'),

            // v2: Folder navigation
            folderNav: document.getElementById('folder-nav'),
            breadcrumbs: document.getElementById('breadcrumbs'),
            folderList: document.getElementById('folder-list'),
            hintFolders: document.getElementById('hint-folders'),
            hintFoldersDivider: document.getElementById('hint-folders-divider'),

            // v2: Format indicator
            formatIndicator: document.getElementById('format-indicator'),
            formatBadge: document.getElementById('format-badge'),

            // v2: Session resume modal
            sessionOverlay: document.getElementById('session-overlay'),
            sessionLabels: document.getElementById('session-labels'),
            sessionDeletions: document.getElementById('session-deletions'),
            btnResumeSession: document.getElementById('btn-resume-session'),
            btnFreshSession: document.getElementById('btn-fresh-session'),
        };
    }

    /**
     * Initialize the application.
     * Loads session, connects WebSocket, sets up event listeners.
     */
    async init() {
        try {
            // Check for pending session changes first
            const shouldProceed = await this.checkPendingSession();
            if (!shouldProceed) {
                // User is viewing the modal, wait for their choice
                return;
            }

            // Continue with normal initialization
            await this.completeInit();
        } catch (error) {
            console.error('[SwiftLabel] Initialization failed:', error);
            this.showToast('Failed to initialize application', 'error');
        }
    }

    /**
     * Check for pending session changes and show resume modal if needed.
     * @returns {Promise<boolean>} True if initialization should continue, false if waiting for user choice
     */
    async checkPendingSession() {
        try {
            const response = await fetch(`${CONFIG.API_BASE}/session/info`);
            const info = await response.json();

            if (info.has_pending_changes) {
                // Show the session resume modal
                this.showSessionModal(info.labels_count, info.deletions_count);
                return false; // Wait for user choice
            }
        } catch (error) {
            console.warn('[SwiftLabel] Could not check session info:', error);
        }
        return true; // Continue with initialization
    }

    /**
     * Show the session resume modal.
     * @param {number} labelsCount - Number of labeled images
     * @param {number} deletionsCount - Number of images marked for deletion
     */
    showSessionModal(labelsCount, deletionsCount) {
        this.dom.sessionLabels.textContent = labelsCount;
        this.dom.sessionDeletions.textContent = deletionsCount;
        this.dom.sessionOverlay.hidden = false;

        // Set up button handlers
        this.dom.btnResumeSession.onclick = async () => {
            this.dom.sessionOverlay.hidden = true;
            await this.completeInit();
        };

        this.dom.btnFreshSession.onclick = async () => {
            // Clear the session
            try {
                await fetch(`${CONFIG.API_BASE}/session/clear`, { method: 'POST' });
            } catch (error) {
                console.error('[SwiftLabel] Failed to clear session:', error);
            }
            this.dom.sessionOverlay.hidden = true;
            await this.completeInit();
            this.showToast('Started fresh session', 'success');
        };
    }

    /**
     * Complete initialization after session decision.
     */
    async completeInit() {
        // Load initial session state
        await this.loadSession();

        // Connect WebSocket for real-time updates
        this.connectWebSocket();

        // Set up keyboard event listener
        this.setupKeyboardHandler();

        // Set up button click handlers
        this.setupClickHandlers();

        // Initial UI render
        this.renderClassButtons();
        this.updateUI();

        // v2: Load format info and subfolders
        await this.loadFormatInfo();
        await this.loadSubfolders();
        await this.updateChangeCount();

        // Prefetch upcoming images
        this.prefetchImages();

        console.log('[SwiftLabel] Initialized successfully');
    }


    /* ==========================================
       API LAYER
       ========================================== */

    /**
     * Make an API request with error handling.
     * @param {string} endpoint - API endpoint (e.g., '/session')
     * @param {Object} [options] - Fetch options
     * @returns {Promise<Object>} Response data
     */
    async api(endpoint, options = {}) {
        const url = `${CONFIG.API_BASE}${endpoint}`;

        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.message || `API error: ${response.status}`);
        }

        return response.json();
    }

    /**
     * Load session state from the server.
     * @returns {Promise<void>}
     */
    async loadSession() {
        this.session = await this.api('/session');

        if (this.session.images.length > 0) {
            this.currentImage = this.session.images[this.session.current_index];
        }

        console.log('[SwiftLabel] Session loaded:', {
            images: this.session.images.length,
            classes: this.session.classes,
            currentIndex: this.session.current_index,
        });
    }

    /**
     * Load statistics from the server.
     * @returns {Promise<Stats>}
     */
    async loadStats() {
        this.stats = await this.api('/stats');
        return this.stats;
    }

    /**
     * Label the current image with a class.
     * Uses optimistic UI update for instant feedback.
     * @param {number} classIndex - Class index (0-9)
     */
    async labelImage(classIndex) {
        if (!this.currentImage) return;

        const imageId = this.currentImage.id;
        const className = this.session.classes[classIndex];

        // Optimistic update - update local state immediately
        this.currentImage.label = classIndex;
        this.currentImage.class_name = className;
        this.currentImage.marked_for_deletion = false;

        // Update UI immediately (sub-100ms response)
        this.updateImageInfo();
        this.updateClassButtonStates();
        this.flashButton(this.dom.classButtons.querySelector(`[data-class="${classIndex}"]`));

        // Advance to next image immediately
        this.navigateNext();

        // Send to server in background (don't await)
        this.sendWebSocketMessage({
            type: 'label',
            payload: { image_id: imageId, class_index: classIndex }
        });
    }

    /**
     * Mark the current image for deletion.
     * Uses optimistic UI update.
     */
    async deleteImage() {
        if (!this.currentImage) return;

        const imageId = this.currentImage.id;

        // Optimistic update
        this.currentImage.marked_for_deletion = true;
        this.currentImage.label = null;
        this.currentImage.class_name = null;

        // Update UI immediately
        this.updateImageInfo();
        this.updateDeletedOverlay();
        this.flashButton(this.dom.btnDelete);

        // Advance to next image
        this.navigateNext();

        // Send to server in background
        this.sendWebSocketMessage({
            type: 'delete',
            payload: { image_id: imageId }
        });
    }

    /**
     * Undo the last action.
     */
    async undoAction() {
        this.flashButton(this.dom.btnUndo);

        // Send undo request via WebSocket
        this.sendWebSocketMessage({ type: 'undo' });
    }

    /**
     * Get commit preview from the server.
     * @returns {Promise<PreviewSummary>}
     */
    async getCommitPreview() {
        this.commitPreview = await this.api('/changes/preview');
        return this.commitPreview;
    }

    /**
     * Execute commit of all staged changes.
     * @returns {Promise<Object>}
     */
    async executeCommit() {
        return this.api('/changes/commit', { method: 'POST' });
    }


    /* ==========================================
       WEBSOCKET CLIENT
       ========================================== */

    /**
     * Establish WebSocket connection with auto-reconnect.
     */
    connectWebSocket() {
        // Clear any existing reconnect timeout
        if (this.wsReconnectTimeout) {
            clearTimeout(this.wsReconnectTimeout);
            this.wsReconnectTimeout = null;
        }

        try {
            this.ws = new WebSocket(CONFIG.WS_URL);

            this.ws.onopen = () => {
                console.log('[WS] Connected');
                this.wsReconnectAttempt = 0;
                this.hideConnectionStatus();

                // Start heartbeat
                this.startHeartbeat();

                // Request full state sync
                this.sendWebSocketMessage({ type: 'sync' });
            };

            this.ws.onmessage = (event) => {
                this.handleWebSocketMessage(event);
            };

            this.ws.onclose = (event) => {
                console.log('[WS] Disconnected:', event.code, event.reason);
                this.stopHeartbeat();
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('[WS] Error:', error);
            };

        } catch (error) {
            console.error('[WS] Connection failed:', error);
            this.scheduleReconnect();
        }
    }

    /**
     * Schedule WebSocket reconnection with exponential backoff.
     */
    scheduleReconnect() {
        const delays = CONFIG.WS_RECONNECT_DELAYS;
        const delay = delays[Math.min(this.wsReconnectAttempt, delays.length - 1)];

        this.showConnectionStatus();

        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.wsReconnectAttempt + 1})`);

        this.wsReconnectTimeout = setTimeout(() => {
            this.wsReconnectAttempt++;
            this.connectWebSocket();
        }, delay);
    }

    /**
     * Start WebSocket heartbeat to keep connection alive.
     */
    startHeartbeat() {
        this.stopHeartbeat();

        this.wsHeartbeatInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.sendWebSocketMessage({ type: 'sync' });
            }
        }, CONFIG.WS_HEARTBEAT_INTERVAL);
    }

    /**
     * Stop WebSocket heartbeat.
     */
    stopHeartbeat() {
        if (this.wsHeartbeatInterval) {
            clearInterval(this.wsHeartbeatInterval);
            this.wsHeartbeatInterval = null;
        }
    }

    /**
     * Send a message through WebSocket.
     * @param {WSMessage} message - Message to send
     */
    sendWebSocketMessage(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('[WS] Cannot send - not connected');
        }
    }

    /**
     * Handle incoming WebSocket message.
     * @param {MessageEvent} event - WebSocket message event
     */
    handleWebSocketMessage(event) {
        try {
            /** @type {WSMessage} */
            const message = JSON.parse(event.data);

            switch (message.type) {
                case 'state_update':
                    this.handleStateUpdate(message.payload);
                    break;

                case 'image_labeled':
                    this.handleImageLabeled(message.payload);
                    break;

                case 'image_deleted':
                    this.handleImageDeleted(message.payload);
                    break;

                case 'undo_completed':
                    this.handleUndoCompleted(message.payload);
                    break;

                case 'changes_committed':
                    this.handleChangesCommitted(message.payload);
                    break;

                case 'error':
                    this.handleServerError(message.payload);
                    break;

                default:
                    console.log('[WS] Unknown message type:', message.type);
            }
        } catch (error) {
            console.error('[WS] Failed to parse message:', error);
        }
    }

    /**
     * Handle state_update message from server.
     * @param {Object} payload - State update payload
     */
    handleStateUpdate(payload) {
        // Update session state
        this.session.current_index = payload.current_index;

        // Update current image
        if (payload.current_image) {
            const index = this.session.images.findIndex(img => img.id === payload.current_image.id);
            if (index !== -1) {
                this.session.images[index] = payload.current_image;
            }
            this.currentImage = payload.current_image;
        }

        // Update UI
        this.updateUI();
        this.prefetchImages();
    }

    /**
     * Handle image_labeled message from server.
     * @param {Object} payload - Label payload
     */
    handleImageLabeled(payload) {
        // Update the image in our session
        const image = this.session.images.find(img => img.id === payload.image_id);
        if (image) {
            image.label = payload.class_index;
            image.class_name = payload.class_name;
            image.marked_for_deletion = false;
        }

        this.updateProgress();
        this.updateChangeCount();  // v2: refresh commit count
    }

    /**
     * Handle image_deleted message from server.
     * @param {Object} payload - Delete payload
     */
    handleImageDeleted(payload) {
        const image = this.session.images.find(img => img.id === payload.image_id);
        if (image) {
            image.marked_for_deletion = true;
            image.label = null;
            image.class_name = null;
        }

        this.updateProgress();
        this.updateChangeCount();  // v2: refresh commit count
    }

    /**
     * Handle undo_completed message from server.
     * @param {Object} payload - Undo payload
     */
    handleUndoCompleted(payload) {
        // Update the affected image
        const image = this.session.images.find(img => img.id === payload.image_id);
        if (image && payload.restored_state) {
            Object.assign(image, payload.restored_state);
        }

        // Navigate to the affected image
        const index = this.session.images.findIndex(img => img.id === payload.image_id);
        if (index !== -1) {
            this.navigateToIndex(index);
        }

        this.showToast(`Undid ${payload.undone_action} on ${payload.image_id}`, 'info');
        this.updateUI();
        this.updateChangeCount();  // v2: refresh commit count
    }

    /**
     * Handle changes_committed message from server.
     * @param {Object} payload - Commit result payload
     */
    handleChangesCommitted(payload) {
        // Reload session to get updated state
        this.loadSession().then(() => {
            this.updateUI();
            // Refresh the commit button count (should be 0 after commit)
            this.updateChangeCount();
        });

        this.showToast(
            `Committed: ${payload.moves_count} moved, ${payload.deletes_count} deleted`,
            payload.errors.length > 0 ? 'warning' : 'success'
        );

        this.closeOverlay();
    }

    /**
     * Handle error message from server.
     * @param {Object} payload - Error payload
     */
    handleServerError(payload) {
        console.error('[Server Error]', payload);
        this.showToast(payload.message || 'An error occurred', 'error');
    }


    /* ==========================================
       KEYBOARD HANDLER
       ========================================== */

    /**
     * Set up global keyboard event listener.
     */
    setupKeyboardHandler() {
        document.addEventListener('keydown', (event) => {
            this.handleKeyDown(event);
        });
    }

    /**
     * Handle keydown events.
     * @param {KeyboardEvent} event - Keyboard event
     */
    handleKeyDown(event) {
        // Ignore if typing in an input field
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
            return;
        }

        const key = event.key;

        // ========== OVERLAY HANDLING ==========

        // Escape always closes overlays
        if (key === 'Escape') {
            if (this.activeOverlay) {
                event.preventDefault();
                this.closeOverlay();
                return;
            }
        }

        // If an overlay is open, handle overlay-specific keys
        if (this.activeOverlay === 'commit') {
            if (key === 'Enter') {
                event.preventDefault();
                this.confirmCommit();
                return;
            }
            // Escape handled above
            return; // Block other keys while commit modal is open
        }

        // Help and stats overlays close on any key
        if (this.activeOverlay === 'help' || this.activeOverlay === 'stats') {
            event.preventDefault();
            this.closeOverlay();
            return;
        }

        // ========== FILTER MODE ==========

        if (this.filterMode) {
            event.preventDefault();
            if (key >= '0' && key <= '9') {
                this.applyFilter(parseInt(key, 10));
            }
            this.filterMode = false;
            return;
        }

        // ========== MAIN KEYBOARD SHORTCUTS ==========

        switch (key) {
            // ===== LABELING =====
            case '1': case '2': case '3': case '4': case '5':
            case '6': case '7': case '8': case '9':
                event.preventDefault();
                this.handleClassKey(parseInt(key, 10));
                break;

            case '0':
                event.preventDefault();
                this.handleClassKey(0);
                break;

            case 'd':
            case 'D':
                event.preventDefault();
                this.deleteImage();
                break;

            case 'u':
            case 'U':
                event.preventDefault();
                this.undoAction();
                break;

            // ===== NAVIGATION =====
            case 'ArrowLeft':
            case 'h':
            case 'H':
                event.preventDefault();
                this.navigatePrevious();
                break;

            case 'ArrowRight':
            case 'l':
            case 'L':
                event.preventDefault();
                this.navigateNext();
                break;

            case 'j':
            case 'J':
                event.preventDefault();
                this.navigateNext(); // vim: j = down = next
                break;

            case 'k':
            case 'K':
                event.preventDefault();
                this.navigatePrevious(); // vim: k = up = previous
                break;

            case 'g':
                event.preventDefault();
                this.handleGKey();
                break;

            case 'G':
                event.preventDefault();
                this.navigateToLastInFolder();
                break;

            case 'n':
            case 'N':
                event.preventDefault();
                this.navigateToNextUnlabeled();
                break;

            // ===== ACTIONS =====
            case 'Enter':
                event.preventDefault();
                this.showCommitModal();
                break;

            // ===== VIEWS =====
            case '?':
                event.preventDefault();
                this.toggleHelp();
                break;

            case 's':
            case 'S':
                event.preventDefault();
                this.toggleStats();
                break;

            case 'f':
            case 'F':
                event.preventDefault();
                this.filterMode = true;
                this.showToast('Filter mode: Press 1-9 for class, 0 to clear', 'info');
                break;

            // ===== v2: FOLDER NAVIGATION =====
            case 'Tab':
                if (this.hasFolders) {
                    event.preventDefault();
                    if (event.shiftKey) {
                        this.navigateToPrevFolder();
                    } else {
                        this.navigateToNextFolder();
                    }
                }
                break;

            case 'Backspace':
                if (this.currentFolder) {
                    event.preventDefault();
                    this.navigateToParentFolder();
                }
                break;

            default:
                // Unknown key - do nothing
                break;
        }
    }

    /**
     * Handle class assignment key (1-9, 0).
     * @param {number} keyNumber - Key number pressed (0-9)
     */
    handleClassKey(keyNumber) {
        // Convert key number to class index
        // Key 1 = class index 0, Key 2 = class index 1, etc.
        // Key 0 = class index 9 (or last class if fewer than 10)
        let classIndex;

        if (keyNumber === 0) {
            // Key 0: assign to last/other class
            classIndex = Math.min(9, this.session.classes.length - 1);
        } else {
            // Key 1-9: assign to class index 0-8
            classIndex = keyNumber - 1;
        }

        // Check if class exists
        if (classIndex >= this.session.classes.length) {
            this.showToast(`Class ${classIndex + 1} not defined`, 'warning');
            return;
        }

        this.labelImage(classIndex);
    }

    /**
     * Handle 'g' key for vim-style gg (go to first).
     */
    handleGKey() {
        // Check for gg combo
        if (this.lastKey === 'g') {
            // gg combo - go to first image in current folder
            clearTimeout(this.keyComboTimeout);
            this.lastKey = null;
            this.navigateToFirstInFolder();
        } else {
            // Start combo timer
            this.lastKey = 'g';
            this.keyComboTimeout = setTimeout(() => {
                this.lastKey = null;
            }, CONFIG.DOUBLE_KEY_TIMEOUT);
        }
    }

    /**
     * Navigate to first image in the current folder.
     */
    navigateToFirstInFolder() {
        if (!this.currentImage) return;
        
        const parentFolder = this.currentImage.id.substring(0, this.currentImage.id.lastIndexOf('/')) || '';
        
        // Find first image in same folder
        for (let i = 0; i < this.session.images.length; i++) {
            const imgFolder = this.session.images[i].id.substring(0, this.session.images[i].id.lastIndexOf('/')) || '';
            if (imgFolder === parentFolder) {
                this.navigateToIndex(i);
                return;
            }
        }
    }

    /**
     * Navigate to last image in the current folder.
     */
    navigateToLastInFolder() {
        if (!this.currentImage) return;
        
        const parentFolder = this.currentImage.id.substring(0, this.currentImage.id.lastIndexOf('/')) || '';
        
        // Find last image in same folder
        for (let i = this.session.images.length - 1; i >= 0; i--) {
            const imgFolder = this.session.images[i].id.substring(0, this.session.images[i].id.lastIndexOf('/')) || '';
            if (imgFolder === parentFolder) {
                this.navigateToIndex(i);
                return;
            }
        }
    }


    /* ==========================================
       NAVIGATION
       ========================================== */

    /**
     * Navigate to the next image.
     */
    navigateNext() {
        if (!this.session || this.session.images.length === 0) return;

        const nextIndex = Math.min(
            this.session.current_index + 1,
            this.session.images.length - 1
        );

        if (nextIndex !== this.session.current_index) {
            this.navigateToIndex(nextIndex);
        }
    }

    /**
     * Navigate to the previous image.
     */
    navigatePrevious() {
        if (!this.session || this.session.images.length === 0) return;

        const prevIndex = Math.max(this.session.current_index - 1, 0);

        if (prevIndex !== this.session.current_index) {
            this.navigateToIndex(prevIndex);
        }
    }

    /**
     * Navigate to a specific index.
     * @param {number} index - Target index
     */
    navigateToIndex(index) {
        if (!this.session || index < 0 || index >= this.session.images.length) return;

        // Check if we're crossing folder boundaries
        const oldImage = this.currentImage;
        const newImage = this.session.images[index];
        
        let newFolder = null;
        if (oldImage && newImage) {
            const oldFolder = oldImage.id.substring(0, oldImage.id.lastIndexOf('/')) || '';
            newFolder = newImage.id.substring(0, newImage.id.lastIndexOf('/')) || '';
            if (oldFolder === newFolder) {
                newFolder = null; // No change
            }
        }

        this.session.current_index = index;
        this.currentImage = newImage;

        this.updateUI();
        this.prefetchImages();

        // If we crossed folder boundaries, update server's folder context and refresh navigation
        if (newFolder !== null) {
            this.updateFolderContext(newFolder);
        }

        // Notify server of navigation
        this.sendWebSocketMessage({
            type: 'navigate',
            payload: { direction: 'index', index: index }
        });
    }

    /**
     * Update the server's folder context and refresh navigation UI.
     * Called when navigating by index crosses folder boundaries.
     * @param {string} folderPath - The new folder path
     */
    async updateFolderContext(folderPath) {
        try {
            await this.api('/navigate/folder', {
                method: 'POST',
                body: JSON.stringify({ folder_path: folderPath })
            });
            await this.loadSubfolders();
        } catch (error) {
            console.error('[SwiftLabel] Failed to update folder context:', error);
        }
    }

    /**
     * Navigate to the next unlabeled image.
     */
    navigateToNextUnlabeled() {
        if (!this.session) return;

        // Search from current position to end
        for (let i = this.session.current_index + 1; i < this.session.images.length; i++) {
            if (this.session.images[i].label === null && !this.session.images[i].marked_for_deletion) {
                this.navigateToIndex(i);
                return;
            }
        }

        // Search from beginning to current position
        for (let i = 0; i < this.session.current_index; i++) {
            if (this.session.images[i].label === null && !this.session.images[i].marked_for_deletion) {
                this.navigateToIndex(i);
                return;
            }
        }

        this.showToast('No unlabeled images remaining', 'info');
    }


    /* ==========================================
       FILTERING
       ========================================== */

    /**
     * Apply filter to show only specific class.
     * @param {number} classIndex - Class index to filter (0 = clear filter)
     */
    applyFilter(classIndex) {
        // TODO: Implement filtering logic
        // For v1, just show a message
        if (classIndex === 0) {
            this.showToast('Filter cleared', 'info');
        } else {
            const className = this.session.classes[classIndex - 1];
            if (className) {
                this.showToast(`Filter: showing only "${className}"`, 'info');
            }
        }
    }


    /* ==========================================
       IMAGE PREFETCHING
       ========================================== */

    /**
     * Prefetch upcoming images for faster display.
     */
    prefetchImages() {
        if (!this.session || this.session.images.length === 0) return;

        const currentIndex = this.session.current_index;

        // Prefetch next N images
        for (let i = 1; i <= CONFIG.PREFETCH_COUNT; i++) {
            const index = currentIndex + i;
            if (index < this.session.images.length) {
                this.prefetchImage(this.session.images[index].id);
            }
        }

        // Also prefetch previous image for back navigation
        if (currentIndex > 0) {
            this.prefetchImage(this.session.images[currentIndex - 1].id);
        }

        // Clean up old cache entries (LRU)
        this.cleanImageCache();
    }

    /**
     * Prefetch a single image.
     * @param {string} imageId - Image ID to prefetch
     */
    prefetchImage(imageId) {
        // Skip if already cached or being fetched
        if (this.imageCache.has(imageId) || this.prefetchingImages.has(imageId)) {
            return;
        }

        this.prefetchingImages.add(imageId);

        const img = new Image();
        img.onload = () => {
            this.imageCache.set(imageId, img);
            this.prefetchingImages.delete(imageId);
        };
        img.onerror = () => {
            this.prefetchingImages.delete(imageId);
        };
        img.src = `${CONFIG.API_BASE}/images/${encodeURIComponent(imageId)}`;
    }

    /**
     * Clean up image cache (LRU eviction).
     */
    cleanImageCache() {
        while (this.imageCache.size > CONFIG.CACHE_MAX_SIZE) {
            // Delete oldest entry (first key in Map)
            const oldestKey = this.imageCache.keys().next().value;
            this.imageCache.delete(oldestKey);
        }
    }

    /**
     * Get image URL for display.
     * @param {string} imageId - Image ID
     * @returns {string} Image URL
     */
    getImageUrl(imageId) {
        return `${CONFIG.API_BASE}/images/${encodeURIComponent(imageId)}`;
    }


    /* ==========================================
       UI UPDATES
       ========================================== */

    /**
     * Update all UI elements.
     */
    updateUI() {
        this.displayCurrentImage();
        this.updateImageInfo();
        this.updateProgress();
        this.updateClassButtonStates();
        this.updateDeletedOverlay();
        this.updateCommitCount();
    }

    /**
     * Display the current image.
     */
    displayCurrentImage() {
        if (!this.currentImage) {
            this.dom.currentImage.src = '';
            return;
        }

        const imageId = this.currentImage.id;
        const imageUrl = this.getImageUrl(imageId);

        // Show loading state
        this.dom.loadingSpinner.classList.add('visible');
        this.dom.currentImage.classList.add('loading');

        // Check cache first
        if (this.imageCache.has(imageId)) {
            this.dom.currentImage.src = this.imageCache.get(imageId).src;
            this.dom.loadingSpinner.classList.remove('visible');
            this.dom.currentImage.classList.remove('loading');
            this.dom.currentImage.classList.add('entering');
            setTimeout(() => this.dom.currentImage.classList.remove('entering'), 150);
        } else {
            // Load image
            this.dom.currentImage.onload = () => {
                this.dom.loadingSpinner.classList.remove('visible');
                this.dom.currentImage.classList.remove('loading');
                this.dom.currentImage.classList.add('entering');
                setTimeout(() => this.dom.currentImage.classList.remove('entering'), 150);
            };
            this.dom.currentImage.src = imageUrl;
        }
    }

    /**
     * Update image info display (filename, label).
     */
    updateImageInfo() {
        if (!this.currentImage) {
            this.dom.currentFilename.textContent = '—';
            this.dom.currentLabel.textContent = 'No images';
            this.dom.currentLabel.className = 'info__label';
            return;
        }

        // Calculate position within the current folder
        const currentPath = this.currentImage.id;
        const parentFolder = currentPath.substring(0, currentPath.lastIndexOf('/')) || '';
        
        // Find all images in the same folder
        const imagesInFolder = this.session.images.filter(img => {
            const imgFolder = img.id.substring(0, img.id.lastIndexOf('/')) || '';
            return imgFolder === parentFolder;
        });
        
        // Find position within folder
        const posInFolder = imagesInFolder.findIndex(img => img.id === currentPath) + 1;
        const totalInFolder = imagesInFolder.length;
        
        // Show filename with folder-relative position
        const folderName = parentFolder.split('/').pop() || 'root';
        this.dom.currentFilename.textContent = `${currentPath} (${posInFolder}/${totalInFolder} in ${folderName})`;

        // Label
        if (this.currentImage.marked_for_deletion) {
            this.dom.currentLabel.textContent = 'Marked for deletion';
            this.dom.currentLabel.className = 'info__label deleted';
        } else if (this.currentImage.label !== null) {
            const classIndex = this.currentImage.label;
            const className = this.currentImage.class_name || this.session.classes[classIndex];
            this.dom.currentLabel.textContent = `${className} (${classIndex + 1})`;
            this.dom.currentLabel.className = 'info__label labeled';
        } else {
            this.dom.currentLabel.textContent = 'Unlabeled';
            this.dom.currentLabel.className = 'info__label';
        }
    }

    /**
     * Update progress indicator.
     */
    updateProgress() {
        if (!this.session) return;

        // Calculate folder-relative progress (matching the image counter)
        let total, labeled, deleted;
        
        if (this.currentImage) {
            const parentFolder = this.currentImage.id.substring(0, this.currentImage.id.lastIndexOf('/')) || '';
            
            // Find all images in the same folder
            const imagesInFolder = this.session.images.filter(img => {
                const imgFolder = img.id.substring(0, img.id.lastIndexOf('/')) || '';
                return imgFolder === parentFolder;
            });
            
            total = imagesInFolder.length;
            labeled = 0;
            deleted = 0;
            for (const img of imagesInFolder) {
                if (img.marked_for_deletion) deleted++;
                else if (img.label !== null) labeled++;
            }
        } else {
            // Fallback to global if no current image
            total = this.session.images.length;
            labeled = 0;
            deleted = 0;
            for (const img of this.session.images) {
                if (img.marked_for_deletion) deleted++;
                else if (img.label !== null) labeled++;
            }
        }

        const processed = labeled + deleted;
        const percent = total > 0 ? Math.round((processed / total) * 100) : 0;

        // Update counter
        this.dom.progressCounter.textContent = `${processed}/${total}`;

        // Update bar
        this.dom.progressFill.style.width = `${percent}%`;

        // Update percent
        this.dom.progressPercent.textContent = `${percent}%`;
    }

    /**
     * Update class button active states.
     */
    updateClassButtonStates() {
        const buttons = this.dom.classButtons.querySelectorAll('.class-btn');

        buttons.forEach(btn => {
            const classIndex = parseInt(btn.dataset.class, 10);
            const isActive = this.currentImage &&
                             this.currentImage.label === classIndex &&
                             !this.currentImage.marked_for_deletion;
            btn.classList.toggle('active', isActive);
        });
    }

    /**
     * Update deleted overlay visibility.
     */
    updateDeletedOverlay() {
        const isDeleted = this.currentImage && this.currentImage.marked_for_deletion;
        this.dom.deletedOverlay.classList.toggle('visible', isDeleted);
    }

    /**
     * Update commit button count badge.
     */
    updateCommitCount() {
        // Use the cached userChangesCount from /api/changes/count
        // This shows actual pending changes, not all labeled images
        const count = this.userChangesCount || 0;
        const hasChanges = this.hasChanges || false;
        this.updateCommitButton(count, hasChanges);
    }

    /**
     * Render class buttons based on session classes.
     */
    renderClassButtons() {
        if (!this.session) return;

        this.dom.classButtons.innerHTML = '';

        this.session.classes.forEach((className, index) => {
            const keyNumber = index < 9 ? index + 1 : 0; // Keys 1-9, then 0
            const btn = document.createElement('button');
            btn.className = 'action-btn class-btn';
            btn.dataset.class = index.toString();
            btn.title = `Assign to ${className} (${keyNumber})`;
            btn.innerHTML = `<kbd>${keyNumber}</kbd> ${className}`;
            btn.addEventListener('click', () => this.labelImage(index));
            this.dom.classButtons.appendChild(btn);
        });
    }


    /* ==========================================
       OVERLAYS (Help, Stats, Commit)
       ========================================== */

    /**
     * Toggle help overlay.
     */
    toggleHelp() {
        if (this.activeOverlay === 'help') {
            this.closeOverlay();
        } else {
            this.openOverlay('help');
        }
    }

    /**
     * Toggle stats overlay.
     */
    async toggleStats() {
        if (this.activeOverlay === 'stats') {
            this.closeOverlay();
        } else {
            await this.loadStats();
            this.renderStats();
            this.openOverlay('stats');
        }
    }

    /**
     * Show commit confirmation modal.
     */
    async showCommitModal() {
        try {
            await this.getCommitPreview();

            if (this.commitPreview.total_changes === 0) {
                this.showToast('No changes to commit', 'info');
                return;
            }

            // Update modal content
            this.dom.commitTotal.textContent = this.commitPreview.total_changes;
            this.dom.commitMoves.textContent = this.commitPreview.moves.length;
            this.dom.commitDeletes.textContent = this.commitPreview.deletes.length;

            this.openOverlay('commit');
        } catch (error) {
            this.showToast('Failed to load commit preview', 'error');
        }
    }

    /**
     * Confirm and execute commit.
     */
    async confirmCommit() {
        if (this.activeOverlay !== 'commit') return;

        try {
            this.showToast('Committing changes...', 'info');
            await this.executeCommit();
            // handleChangesCommitted will close overlay and show result
        } catch (error) {
            this.showToast('Commit failed: ' + error.message, 'error');
            this.closeOverlay();
        }
    }

    /**
     * Open an overlay.
     * @param {'help'|'stats'|'commit'} overlayName - Overlay to open
     */
    openOverlay(overlayName) {
        // Close any existing overlay first
        this.closeOverlay();

        this.activeOverlay = overlayName;

        const overlayElement = {
            help: this.dom.helpOverlay,
            stats: this.dom.statsOverlay,
            commit: this.dom.commitOverlay,
        }[overlayName];

        if (overlayElement) {
            overlayElement.hidden = false;
        }
    }

    /**
     * Close the active overlay.
     */
    closeOverlay() {
        if (!this.activeOverlay) return;

        const overlayElement = {
            help: this.dom.helpOverlay,
            stats: this.dom.statsOverlay,
            commit: this.dom.commitOverlay,
        }[this.activeOverlay];

        if (overlayElement) {
            overlayElement.hidden = true;
        }

        this.activeOverlay = null;
    }

    /**
     * Render stats in the stats overlay.
     */
    renderStats() {
        if (!this.stats) return;

        // Progress
        const percent = this.stats.progress_percent.toFixed(1);
        this.dom.statsProgressText.textContent =
            `${this.stats.labeled_count}/${this.stats.total_images} (${percent}%)`;
        this.dom.statsProgressFill.style.width = `${percent}%`;

        // Distribution chart
        const total = this.stats.labeled_count || 1; // Avoid division by zero
        this.dom.distributionChart.innerHTML = '';

        let classIndex = 0;
        for (const [className, count] of Object.entries(this.stats.per_class)) {
            const rowPercent = ((count / total) * 100).toFixed(1);

            const row = document.createElement('div');
            row.className = 'distribution-row';
            row.dataset.class = classIndex.toString();
            row.innerHTML = `
                <span class="distribution-row__label">${className}</span>
                <div class="distribution-row__bar">
                    <div class="distribution-row__fill" style="width: ${rowPercent}%"></div>
                </div>
                <span class="distribution-row__count">${count}</span>
                <span class="distribution-row__percent">${rowPercent}%</span>
            `;
            this.dom.distributionChart.appendChild(row);
            classIndex++;
        }

        // Summary
        this.dom.statsUnlabeled.textContent = this.stats.unlabeled_count;
        this.dom.statsDeleted.textContent = this.stats.deleted_count;
    }


    /* ==========================================
       TOAST NOTIFICATIONS
       ========================================== */

    /**
     * Show a toast notification.
     * @param {string} message - Message to display
     * @param {'success'|'error'|'info'|'warning'} [type='info'] - Toast type
     */
    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.textContent = message;

        this.dom.toastContainer.appendChild(toast);

        // Auto-remove after duration
        setTimeout(() => {
            toast.classList.add('removing');
            setTimeout(() => toast.remove(), 200);
        }, CONFIG.TOAST_DURATION);
    }


    /* ==========================================
       CONNECTION STATUS
       ========================================== */

    /**
     * Show connection status indicator.
     */
    showConnectionStatus() {
        this.dom.connectionStatus.hidden = false;
    }

    /**
     * Hide connection status indicator.
     */
    hideConnectionStatus() {
        this.dom.connectionStatus.hidden = true;
    }


    /* ==========================================
       VISUAL FEEDBACK
       ========================================== */

    /**
     * Flash a button to indicate key press.
     * @param {HTMLElement|null} button - Button to flash
     */
    flashButton(button) {
        if (!button) return;

        button.classList.add('flash');
        setTimeout(() => button.classList.remove('flash'), 150);
    }


    /* ==========================================
       CLICK HANDLERS
       ========================================== */

    /**
     * Set up click event handlers for buttons.
     */
    setupClickHandlers() {
        // Delete button
        this.dom.btnDelete.addEventListener('click', () => this.deleteImage());

        // Undo button
        this.dom.btnUndo.addEventListener('click', () => this.undoAction());

        // Commit button
        this.dom.btnCommit.addEventListener('click', () => this.showCommitModal());

        // Commit modal buttons
        this.dom.btnConfirmCommit.addEventListener('click', () => this.confirmCommit());
        this.dom.btnCancelCommit.addEventListener('click', () => this.closeOverlay());

        // Overlay backdrop clicks to close
        document.querySelectorAll('.overlay__backdrop').forEach(backdrop => {
            backdrop.addEventListener('click', () => this.closeOverlay());
        });
    }


    /* ==========================================
       v2: FORMAT DETECTION
       ========================================== */

    /**
     * Load format info from server.
     * @returns {Promise<void>}
     */
    async loadFormatInfo() {
        try {
            const data = await this.api('/format');
            this.detectedFormat = data.format;
            this.updateFormatBadge(data.format, data.format_label);
        } catch (error) {
            console.error('[SwiftLabel] Failed to load format info:', error);
        }
    }

    /**
     * Update format badge UI.
     * @param {string} format - Format type
     * @param {string} label - Display label
     */
    updateFormatBadge(format, label) {
        if (!this.dom.formatIndicator || !this.dom.formatBadge) return;

        this.dom.formatIndicator.hidden = false;
        this.dom.formatBadge.textContent = label;
        this.dom.formatBadge.className = `format-badge format-badge--${format}`;
    }


    /* ==========================================
       v2: SUBFOLDER NAVIGATION
       ========================================== */

    /**
     * Load available subfolders from server.
     * @returns {Promise<void>}
     */
    async loadSubfolders() {
        try {
            const data = await this.api('/subfolders');
            this.subfolders = data.subfolders;
            this.hasFolders = data.has_subfolders;
            this.currentFolder = data.current_folder;
            this.renderFolderNav(data);
        } catch (error) {
            console.error('[SwiftLabel] Failed to load subfolders:', error);
        }
    }

    /**
     * Render folder navigation UI.
     * @param {Object} data - Subfolder data
     */
    renderFolderNav(data) {
        const nav = this.dom.folderNav;
        const breadcrumbsEl = this.dom.breadcrumbs;
        const folderList = this.dom.folderList;

        // Show nav if we have subfolders OR we're inside a subfolder (to navigate back)
        const showNav = data.has_subfolders || this.currentFolder;
        
        if (!nav || !showNav) {
            if (nav) nav.hidden = true;
            if (this.dom.hintFolders) this.dom.hintFolders.hidden = true;
            if (this.dom.hintFoldersDivider) this.dom.hintFoldersDivider.hidden = true;
            return;
        }

        nav.hidden = false;
        if (this.dom.hintFolders) this.dom.hintFolders.hidden = false;
        if (this.dom.hintFoldersDivider) this.dom.hintFoldersDivider.hidden = false;

        // Render breadcrumbs
        if (breadcrumbsEl) {
            breadcrumbsEl.innerHTML = '';
            const breadcrumbs = this.getBreadcrumbs();
            breadcrumbs.forEach((crumb, idx) => {
                const span = document.createElement('span');
                span.className = `breadcrumb${crumb.is_current ? ' breadcrumb--current' : ''}`;
                const btn = document.createElement('button');
                btn.className = 'breadcrumb__btn';
                btn.dataset.path = crumb.path;
                btn.textContent = (idx === 0 ? '📁 ' : '') + crumb.name;
                btn.addEventListener('click', () => this.navigateToFolder(crumb.path));
                span.appendChild(btn);
                breadcrumbsEl.appendChild(span);
            });
        }

        // Render folder buttons
        if (folderList) {
            folderList.innerHTML = '';
            data.subfolders.forEach(folder => {
                const btn = document.createElement('button');
                btn.className = `folder-btn${folder.path === this.currentFolder ? ' folder-btn--active' : ''}`;
                btn.dataset.path = folder.path;
                btn.innerHTML = `${folder.name} <span class="folder-btn__count">${folder.image_count}</span>`;
                btn.addEventListener('click', () => this.navigateToFolder(folder.path));
                folderList.appendChild(btn);
            });
        }
    }

    /**
     * Get breadcrumbs for current folder path.
     * @returns {Array} Breadcrumb objects
     */
    getBreadcrumbs() {
        const breadcrumbs = [{ path: '', name: 'root', is_current: !this.currentFolder }];
        if (this.currentFolder) {
            const parts = this.currentFolder.split('/');
            let accumulated = '';
            parts.forEach((part, idx) => {
                accumulated = accumulated ? `${accumulated}/${part}` : part;
                breadcrumbs.push({
                    path: accumulated,
                    name: part,
                    is_current: idx === parts.length - 1
                });
            });
        }
        return breadcrumbs;
    }

    /**
     * Navigate to a specific folder.
     * @param {string} folderPath - Target folder path
     */
    async navigateToFolder(folderPath) {
        try {
            const response = await this.api('/navigate/folder', {
                method: 'POST',
                body: JSON.stringify({ folder_path: folderPath })
            });

            if (response.success) {
                this.currentFolder = response.current_folder;
                
                // Reload session to get fresh image data
                await this.loadSession();
                await this.loadSubfolders();
                
                // Find first image in the selected folder and navigate to it
                const targetPrefix = folderPath ? folderPath + '/' : '';
                const firstImageIndex = this.session.images.findIndex(
                    img => folderPath === '' || img.id.startsWith(targetPrefix)
                );
                
                if (firstImageIndex !== -1) {
                    // Update current image and UI directly (don't use navigateToIndex 
                    // which would send another navigation message to server)
                    this.session.current_index = firstImageIndex;
                    this.currentImage = this.session.images[firstImageIndex];
                }
                
                this.updateUI();
                this.prefetchImages();
            }
        } catch (error) {
            console.error('[SwiftLabel] Failed to navigate folder:', error);
        }
    }

    /**
     * Navigate to next subfolder.
     */
    navigateToNextFolder() {
        if (!this.subfolders.length) return;
        const currentIdx = this.subfolders.findIndex(f => f.path === this.currentFolder);
        const nextIdx = (currentIdx + 1) % this.subfolders.length;
        this.navigateToFolder(this.subfolders[nextIdx].path);
    }

    /**
     * Navigate to previous subfolder.
     */
    navigateToPrevFolder() {
        if (!this.subfolders.length) return;
        const currentIdx = this.subfolders.findIndex(f => f.path === this.currentFolder);
        const prevIdx = currentIdx <= 0 ? this.subfolders.length - 1 : currentIdx - 1;
        this.navigateToFolder(this.subfolders[prevIdx].path);
    }

    /**
     * Navigate to parent folder.
     */
    navigateToParentFolder() {
        if (!this.currentFolder) return;
        const parent = this.currentFolder.split('/').slice(0, -1).join('/');
        this.navigateToFolder(parent);
    }


    /* ==========================================
       v2: CHANGE TRACKING
       ========================================== */

    /**
     * Update user changes count from server.
     * @returns {Promise<void>}
     */
    async updateChangeCount() {
        try {
            const data = await this.api('/changes/count');
            this.userChangesCount = data.user_changes_count;
            this.hasChanges = data.has_changes;
            this.updateCommitButton(data.user_changes_count, data.has_changes);
        } catch (error) {
            console.error('[SwiftLabel] Failed to load change count:', error);
        }
    }

    /**
     * Update commit button state and count.
     * @param {number} count - Changes count
     * @param {boolean} hasChanges - Whether changes pending
     */
    updateCommitButton(count, hasChanges) {
        if (!this.dom.btnCommit || !this.dom.commitCount) return;

        this.dom.commitCount.textContent = count;
        this.dom.btnCommit.disabled = !hasChanges;

        if (hasChanges) {
            this.dom.btnCommit.classList.add('commit-btn--has-changes');
        } else {
            this.dom.btnCommit.classList.remove('commit-btn--has-changes');
        }
    }
}


/* ============================================
   APPLICATION INITIALIZATION
   ============================================ */

// Initialize application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new SwiftLabelApp();
});