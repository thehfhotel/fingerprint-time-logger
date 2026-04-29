// Link LINE Account Page JavaScript

(function() {
    'use strict';

    /**
     * Inline SVG fallback avatar (used when LINE picture URL is missing/broken).
     */
    const DEFAULT_AVATAR_SVG = 'data:image/svg+xml;utf8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
        '<circle cx="32" cy="32" r="32" fill="#e0e0e0"/>' +
        '<circle cx="32" cy="26" r="11" fill="#bdbdbd"/>' +
        '<path d="M10 58c4-12 14-18 22-18s18 6 22 18z" fill="#bdbdbd"/>' +
        '</svg>'
    );

    // DOM Elements
    const elements = {
        loadingSection: document.getElementById('loadingSection'),
        profileSection: document.getElementById('profileSection'),
        linkingSection: document.getElementById('linkingSection'),
        successSection: document.getElementById('successSection'),
        errorSection: document.getElementById('errorSection'),
        noJwtSection: document.getElementById('noJwtSection'),

        profilePicture: document.getElementById('profilePicture'),
        displayName: document.getElementById('displayName'),
        lineUserId: document.getElementById('lineUserId'),

        linkingForm: document.getElementById('linkingForm'),
        linkingCodeInput: document.getElementById('linkingCode'),
        submitButton: document.getElementById('submitButton'),

        errorTitle: document.getElementById('errorTitle'),
        errorMessage: document.getElementById('errorMessage'),
        retryButton: document.getElementById('retryButton')
    };

    // State
    let jwtToken = null;
    let lineProfile = null;

    /**
     * Initialize page
     */
    function init() {
        console.log('[Link LINE] Initializing page...');

        // Get JWT token from URL or localStorage
        jwtToken = getJWTToken();

        if (!jwtToken) {
            console.error('[Link LINE] No JWT token found');
            showNoJWTSection();
            return;
        }

        console.log('[Link LINE] JWT token found, verifying...');
        verifyAndLoadProfile();

        // Setup event listeners
        setupEventListeners();
    }

    /**
     * Get JWT token from URL parameters or localStorage
     */
    function getJWTToken() {
        // Check URL parameters first
        const urlParams = new URLSearchParams(window.location.search);
        const urlToken = urlParams.get('jwt');

        if (urlToken) {
            localStorage.setItem('line_jwt_token', urlToken);
            // Clean URL
            window.history.replaceState({}, document.title, window.location.pathname);
            return urlToken;
        }

        // Check localStorage
        return localStorage.getItem('line_jwt_token');
    }

    /**
     * Verify JWT token and load LINE profile
     */
    async function verifyAndLoadProfile() {
        try {
            showSection('loadingSection');

            const response = await fetch('/api/public/auth/line/verify-token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ token: jwtToken })
            });

            const data = await response.json();

            if (response.ok && data.valid) {
                // Check if account is already linked
                if (data.employee_badge) {
                    console.log('[Link LINE] Account already linked, redirecting to mobile check-in...');
                    window.location.href = '/qr-checkin/mobile';
                    return;
                }

                // Extract LINE profile from JWT payload
                const payload = data.payload;
                lineProfile = {
                    user_id: payload.line_user_id,
                    display_name: payload.display_name || 'ผู้ใช้ LINE',
                    picture_url: payload.picture_url || ''
                };
                console.log('[Link LINE] Profile loaded from JWT:', lineProfile);
                showProfileAndForm();
            } else {
                console.error('[Link LINE] Token verification failed:', data);
                showError('Token ไม่ถูกต้อง', data.detail || data.message || 'กรุณาเข้าสู่ระบบใหม่อีกครั้ง');
            }
        } catch (error) {
            console.error('[Link LINE] Error verifying token:', error);
            showError('เกิดข้อผิดพลาด', 'ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้');
        }
    }

    /**
     * Show profile and linking form
     */
    function showProfileAndForm() {
        // Display profile (with inline SVG fallback for missing/broken pictures)
        elements.profilePicture.src = lineProfile.picture_url || DEFAULT_AVATAR_SVG;
        elements.profilePicture.onerror = function() {
            this.onerror = null;
            this.src = DEFAULT_AVATAR_SVG;
        };
        elements.displayName.textContent = lineProfile.display_name;
        elements.lineUserId.textContent = `LINE ID: ${lineProfile.user_id}`;

        showSection('profileSection');
        showSection('linkingSection');
    }

    /**
     * Setup event listeners
     */
    function setupEventListeners() {
        // Form submission
        elements.linkingForm.addEventListener('submit', handleFormSubmit);

        // Code input validation
        elements.linkingCodeInput.addEventListener('input', function(e) {
            // Only allow numbers
            e.target.value = e.target.value.replace(/[^0-9]/g, '');

            // Auto-submit when 6 digits entered
            if (e.target.value.length === 6) {
                elements.submitButton.disabled = false;
            } else {
                elements.submitButton.disabled = true;
            }
        });

        // Retry button
        elements.retryButton.addEventListener('click', function() {
            elements.linkingCodeInput.value = '';
            showSection('profileSection');
            showSection('linkingSection');
            elements.linkingCodeInput.focus();
        });
    }

    /**
     * Handle form submission
     */
    async function handleFormSubmit(e) {
        e.preventDefault();

        const linkingCode = elements.linkingCodeInput.value.trim();

        if (linkingCode.length !== 6) {
            showError('รหัสไม่ถูกต้อง', 'กรุณากรอกรหัส 6 หลัก');
            return;
        }

        console.log('[Link LINE] Submitting linking code...');
        elements.submitButton.disabled = true;
        elements.submitButton.textContent = '⏳ กำลังเชื่อมต่อ...';

        try {
            const response = await fetch('/api/public/auth/line/link-account', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    jwt_token: jwtToken,  // Backend expects jwt_token field name
                    linking_code: linkingCode
                })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                console.log('[Link LINE] Linking successful:', data);

                // Update JWT token with new token that includes employee_badge
                if (data.token) {
                    jwtToken = data.token;
                    localStorage.setItem('line_jwt_token', data.token);
                    console.log('[Link LINE] JWT token updated with employee badge');
                }

                showSuccess();
            } else {
                console.error('[Link LINE] Linking failed:', data);
                showError('เชื่อมต่อไม่สำเร็จ', data.message || data.detail || 'กรุณาตรวจสอบรหัสและลองใหม่');
                elements.submitButton.disabled = false;
                elements.submitButton.textContent = '✅ เชื่อมต่อบัญชี';
            }
        } catch (error) {
            console.error('[Link LINE] Error linking account:', error);
            showError('เกิดข้อผิดพลาด', 'ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้');
            elements.submitButton.disabled = false;
            elements.submitButton.textContent = '✅ เชื่อมต่อบัญชี';
        }
    }

    /**
     * Show specific section and hide others
     */
    function showSection(sectionId) {
        const sections = ['loadingSection', 'profileSection', 'linkingSection',
                         'successSection', 'errorSection', 'noJwtSection'];

        sections.forEach(id => {
            const element = elements[id];
            if (element) {
                if (id === sectionId) {
                    element.style.display = 'block';
                } else if (id === 'profileSection' || id === 'linkingSection') {
                    // These can be shown together
                    if (sectionId !== 'loadingSection' && sectionId !== 'successSection'
                        && sectionId !== 'errorSection' && sectionId !== 'noJwtSection') {
                        // Keep visible
                    } else {
                        element.style.display = 'none';
                    }
                } else {
                    element.style.display = 'none';
                }
            }
        });
    }

    /**
     * Show no JWT section
     */
    function showNoJWTSection() {
        hideAllSections();
        elements.noJwtSection.style.display = 'block';
    }

    /**
     * Show success section
     */
    function showSuccess() {
        hideAllSections();
        elements.successSection.style.display = 'block';

        // Keep JWT token for persistent login (don't clear it)
        console.log('[Link LINE] Account linked successfully, keeping session');

        // Redirect to mobile check-in after brief success message
        setTimeout(() => {
            console.log('[Link LINE] Redirecting to mobile check-in...');
            window.location.href = '/qr-checkin/mobile';
        }, 2000);
    }

    /**
     * Show error section
     */
    function showError(title, message) {
        hideAllSections();
        elements.errorTitle.textContent = title;
        elements.errorMessage.textContent = message;
        elements.errorSection.style.display = 'block';
    }

    /**
     * Hide all sections
     */
    function hideAllSections() {
        const sections = ['loadingSection', 'profileSection', 'linkingSection',
                         'successSection', 'errorSection', 'noJwtSection'];
        sections.forEach(id => {
            if (elements[id]) {
                elements[id].style.display = 'none';
            }
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
