/* ============================================
   EduChat - Main Application Logic
   Light Genshin Theme - Collapsible Sidebar
   ============================================ */

const ELEMENT_COLORS = {
    pyro: '#E2604A', hydro: '#3A9FD4', electro: '#9B5FD4',
    dendro: '#5EA83F', cryo: '#52B5C4', anemo: '#53B89A', geo: '#C49934'
};

const ELEMENT_NAMES = {
    pyro: '火', hydro: '水', electro: '雷',
    dendro: '草', cryo: '冰', anemo: '风', geo: '岩'
};

const TYPE_ICONS = { study: '📖', review: '🔄', homework: '📝', exam: '🌀' };
const TYPE_COLORS = { study: '#3A9FD4', review: '#9B5FD4', homework: '#C49934', exam: '#E2604A' };

// ============ Global State ============
const state = {
    courses: [],
    currentCourseId: null,
    currentSessionId: null,
    memory: null,
    sidebarCollapsed: false,
    chatMode: 'normal',
    isStreaming: false,
    pendingFiles: [],
    settings: null,
    stateSaveTimer: null,
    modelGroups: [],
    toolList: [],
    activeTools: ['google_search', 'code_execution', 'url_context'],
    currentModel: 'gemini-2.5-flash',
    reviewPoint: '',
};

// ============ API Helpers ============
async function apiGet(url) {
    const res = await fetch(url);
    return res.json();
}

async function apiPost(url, data) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

async function apiPut(url, data) {
    const res = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

async function apiDelete(url) {
    const res = await fetch(url, { method: 'DELETE' });
    return res.json();
}

// ============ State Persistence ============
function saveState() {
    clearTimeout(state.stateSaveTimer);
    state.stateSaveTimer = setTimeout(() => {
        apiPost('/api/state', {
            current_course_id: state.currentCourseId,
            current_session_id: state.currentSessionId,
            sidebar_collapsed: state.sidebarCollapsed,
            chat_mode: state.chatMode,
        }).catch(() => {});
    }, 300);
}

async function restoreState() {
    try {
        const res = await apiGet('/api/state');
        if (res.success && res.data) {
            const s = res.data;
            if (s.current_course_id) state.currentCourseId = s.current_course_id;
            if (s.current_session_id) state.currentSessionId = s.current_session_id;
            if (s.sidebar_collapsed) state.sidebarCollapsed = s.sidebar_collapsed;
            if (s.chat_mode) state.chatMode = s.chat_mode;
        }
    } catch (e) { console.warn('Failed to restore state', e); }
}

// ============ Courses ============
async function loadCourses() {
    const res = await apiGet('/api/courses');
    if (res.success) {
        state.courses = res.data;
        renderCourseTabs();
    }
}

function renderCourseTabs() {
    const container = document.getElementById('courseTabs');
    container.innerHTML = state.courses.map(c => {
        const color = ELEMENT_COLORS[c.element] || ELEMENT_COLORS.pyro;
        return `
        <div class="course-tab ${c.id === state.currentCourseId ? 'active' : ''}" data-id="${c.id}">
            <span class="tab-dot" style="background:${color}"></span>
            <span class="tab-name">${escapeHtml(c.name)}</span>
            <button class="tab-close" data-id="${c.id}" title="关闭">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>`;
    }).join('');

    updateCourseTabScrollButtons();
    // Scroll active tab into view
    const activeTab = container.querySelector('.course-tab.active');
    if (activeTab) activeTab.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
}

function updateCourseTabScrollButtons() {
    const container = document.getElementById('courseTabs');
    const leftBtn = document.getElementById('courseTabScrollLeft');
    const rightBtn = document.getElementById('courseTabScrollRight');
    if (!container || !leftBtn || !rightBtn) return;
    const hasOverflow = container.scrollWidth > container.clientWidth + 2;
    leftBtn.style.display = hasOverflow && container.scrollLeft > 2 ? 'flex' : 'none';
    rightBtn.style.display = hasOverflow && container.scrollLeft < container.scrollWidth - container.clientWidth - 2 ? 'flex' : 'none';
}

async function deleteCourse(courseId) {
    const course = state.courses.find(c => c.id === courseId);
    const name = course ? course.name : '此课程';
    state._pendingDeleteCourseId = courseId;
    document.getElementById('deleteCourseMsg').textContent = `确定要移除课程「${name}」吗？`;
    openModal('deleteCourseModal');
    startDeleteCountdown();
}

async function executeRemoveCourse() {
    const courseId = state._pendingDeleteCourseId;
    if (!courseId) return;
    clearDeleteCountdown();
    closeModal('deleteCourseModal');
    const res = await apiDelete(`/api/courses/${courseId}`);
    if (res.success) {
        state.courses = state.courses.filter(c => c.id !== courseId);
        if (state.currentCourseId === courseId) {
            state.currentCourseId = state.courses.length ? state.courses[0].id : null;
            state.currentSessionId = null;
        }
        renderCourseTabs();
        if (state.currentCourseId) {
            await Promise.all([loadCurrentSession(), loadMemory(), loadReferences()]);
        } else {
            document.getElementById('chatMessages').innerHTML = '';
        }
        updateChatUI();
        saveState();
        showToast('课程已移除（数据已保留，可在继承中使用）', 'success');
    }
    state._pendingDeleteCourseId = null;
}

let _deleteCountdownTimer = null;
function startDeleteCountdown() {
    clearDeleteCountdown();
    const btn = document.getElementById('confirmDeleteCourseBtn');
    let remaining = 3;
    btn.disabled = true;
    btn.style.opacity = '0.5';
    btn.style.cursor = 'not-allowed';
    btn.textContent = `确认移除 (${remaining}s)`;
    _deleteCountdownTimer = setInterval(() => {
        remaining--;
        if (remaining > 0) {
            btn.textContent = `确认移除 (${remaining}s)`;
        } else {
            clearDeleteCountdown();
            btn.disabled = false;
            btn.style.opacity = '';
            btn.style.cursor = '';
            btn.textContent = '确认移除';
        }
    }, 1000);
}
function clearDeleteCountdown() {
    if (_deleteCountdownTimer) {
        clearInterval(_deleteCountdownTimer);
        _deleteCountdownTimer = null;
    }
}

async function switchCourse(courseId) {
    state.currentCourseId = courseId;
    state.currentSessionId = null;
    // 退出特殊模式
    state.chatMode = 'normal';
    state.reviewPoint = '';
    updateModeIndicator();
    renderCourseTabs();
    await Promise.all([loadCurrentSession(), loadMemory(), loadReferences()]);
    updateChatUI();
    saveState();
}

// ============ Sessions (Single Session Per Course) ============
async function loadCurrentSession() {
    if (!state.currentCourseId) { state.currentSessionId = null; return; }
    const res = await apiGet(`/api/sessions/${state.currentCourseId}/current`);
    if (res.success) {
        state.currentSessionId = res.data.id;
        await loadMessages(state.currentSessionId);
    }
}

// ============ Messages ============
async function loadMessages(sessionId) {
    const res = await apiGet(`/api/messages/${sessionId}`);
    if (res.success) renderMessages(res.data);
    updateChatUI();
}

function renderMessages(messages) {
    const container = document.getElementById('chatMessages');
    const el = state.courses.find(c => c.id === state.currentCourseId);
    const elColor = el ? ELEMENT_COLORS[el.element] || ELEMENT_COLORS.pyro : ELEMENT_COLORS.pyro;

    container.innerHTML = messages.map(m => {
        const isUser = m.role === 'user';
        const att = (isUser && m.attachments && m.attachments.length > 0)
            ? `<div class="msg-attachments">${m.attachments.map(name => {
                const ext = name.split('.').pop().toLowerCase();
                const isImg = ['jpg','jpeg','png','gif','webp','bmp'].includes(ext);
                return `<span class="msg-attach-tag${isImg ? ' img-tag' : ''}"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${isImg
                    ? '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>'
                    : '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>'
                }</svg> ${escapeHtml(name)}</span>`;
            }).join('')}</div>` : '';
        return `
        <div class="message ${isUser ? 'user-message' : 'ai-message'}">
            <div class="message-avatar"${isUser ? ` style="background:${elColor}22;border-color:${elColor}44"` : ''}>
                ${isUser ? '👤' : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>`}
            </div>
            <div class="message-content">
                <div class="message-bubble ${isUser ? 'user-bubble' : 'ai-bubble'}"${isUser ? ` style="background:${elColor}12;border-color:${elColor}33"` : ''}>
                    ${isUser ? escapeHtml(m.content) : renderMarkdown(m.content)}
                </div>
                ${att}
            </div>
        </div>`;
    }).join('');

    container.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
    container.querySelectorAll('.message-bubble').forEach(el => {
        renderMathInElement(el, {
            delimiters: [
                { left: '$$', right: '$$', display: true },
                { left: '$', right: '$', display: false },
                { left: '\\[', right: '\\]', display: true },
                { left: '\\(', right: '\\)', display: false },
            ],
            throwOnError: false,
        });
    });
    // Render LaTeX in quiz blocks from history
    container.querySelectorAll('.quiz-q-text, .quiz-option-text').forEach(el => {
        renderMathInElement(el, {
            delimiters: [{ left: '$', right: '$', display: false }],
            throwOnError: false,
        });
    });
    // Determine which quiz cards have been answered by checking if a "我的答案" user message follows
    const allMessages = container.querySelectorAll('.message');
    const answeredQuizParents = new Set();
    allMessages.forEach((msg, idx) => {
        if (msg.classList.contains('user-message')) {
            const bubble = msg.querySelector('.message-bubble');
            if (bubble && bubble.textContent.includes('我的答案：')) {
                // Look backwards to find the preceding AI message with a quiz card
                for (let j = idx - 1; j >= 0; j--) {
                    const prev = allMessages[j];
                    if (prev.classList.contains('ai-message') && prev.querySelector('.quiz-card')) {
                        prev.querySelectorAll('.quiz-card').forEach(c => answeredQuizParents.add(c.id));
                        break;
                    }
                }
            }
        }
    });
    container.querySelectorAll('.quiz-card').forEach(card => {
        if (answeredQuizParents.has(card.id)) {
            card.classList.add('quiz-submitted');
            card.querySelectorAll('input, textarea').forEach(el => el.disabled = true);
            const btn = card.querySelector('.quiz-submit-btn');
            if (btn) { btn.disabled = true; btn.innerHTML = '<span class="quiz-submitted-text">✓ 已提交</span>'; }
        } else {
            // Keep quiz interactive — start timers (wrap in parent so querySelectorAll finds it)
            initQuizTimers(card.parentElement || container);
        }
    });

    // Hide step-complete cards that appear in the same message as unanswered quizzes
    container.querySelectorAll('.message.ai-message').forEach(msg => {
        const quizCards = msg.querySelectorAll('.quiz-card');
        const stepCards = msg.querySelectorAll('.step-complete-card');
        if (quizCards.length > 0 && stepCards.length > 0) {
            const hasUnanswered = Array.from(quizCards).some(c => !answeredQuizParents.has(c.id));
            if (hasUnanswered) {
                stepCards.forEach(sc => sc.style.display = 'none');
            }
        }
    });

    // Add retry buttons to historical error messages (⚠️ AI 响应错误 or ⚠️ ...)
    const allMsgs = container.querySelectorAll('.message');
    allMsgs.forEach((msg, idx) => {
        if (!msg.classList.contains('ai-message')) return;
        const bubble = msg.querySelector('.message-bubble');
        if (!bubble) return;
        const text = bubble.textContent.trim();
        if (!text.startsWith('⚠️') || text.length > 200) return;
        let userText = '';
        for (let j = idx - 1; j >= 0; j--) {
            const prev = allMsgs[j];
            if (prev.classList.contains('user-message')) {
                const ub = prev.querySelector('.message-bubble');
                if (ub) userText = ub.textContent.trim();
                break;
            }
        }
        if (!userText) return;
        const errMsg = escapeHtml(text.replace(/^⚠️\s*/, ''));
        const retryId = 'hist-err-' + idx;
        bubble.innerHTML =
            `<div class="error-retry-card" id="${retryId}" style="padding:12px 16px;background:rgba(212,90,74,0.06);border:1px solid rgba(212,90,74,0.2);border-radius:10px">` +
            `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">` +
            `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--error)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>` +
            `<span style="font-weight:600;color:var(--error);font-size:13px">⚠️ ${errMsg}</span></div>` +
            `<div style="display:flex;gap:8px;margin-top:8px">` +
            `<button class="quick-btn retry-btn" data-id="${retryId}" style="border-color:var(--gold);color:var(--text-gold);font-weight:500;cursor:pointer;padding:4px 14px">` +
            `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> 重试</button>` +
            `</div></div>`;
        bubble.querySelector('.retry-btn').addEventListener('click', () => {
            msg.remove();
            _doSendStream(userText, [], true);
        });
    });

    scrollToBottom();
}

function renderMarkdown(text) {
    if (!text) return '';
    const renderer = new marked.Renderer();
    const origCode = renderer.code.bind(renderer);
    renderer.code = function({ text: code, lang }) {
        // 交互式练习题块
        if (lang === 'quiz_block') {
            try {
                const questions = JSON.parse(code);
                return renderQuizBlock(questions);
            } catch (e) {
                return `<pre><code>${escapeHtml(code)}</code></pre>`;
            }
        }
        // 代码执行工具 - 执行的代码
        if (lang && lang.startsWith('exec_') && lang !== 'exec_output' && lang !== 'exec_error') {
            const actualLang = lang.replace('exec_', '');
            const escaped = escapeHtml(code);
            return `<div class="code-exec-block">
                <div class="code-exec-header"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>代码执行 · ${actualLang}</span></div>
                <pre class="code-exec-code"><code class="language-${actualLang}">${escaped}</code></pre>
            </div>`;
        }
        // 代码执行工具 - 执行结果
        if (lang === 'exec_output') {
            const escaped = escapeHtml(code);
            return `<div class="code-exec-result">
                <div class="code-exec-result-header"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg><span>运行结果</span></div>
                <pre class="code-exec-output">${escaped}</pre>
            </div>`;
        }
        // 代码执行工具 - 执行错误
        if (lang === 'exec_error') {
            const escaped = escapeHtml(code);
            return `<div class="code-exec-result code-exec-result-error">
                <div class="code-exec-result-header"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg><span>执行错误</span></div>
                <pre class="code-exec-output">${escaped}</pre>
            </div>`;
        }
        // 默认代码块
        if (origCode) return origCode({ text: code, lang });
        const escaped = escapeHtml(code);
        const langClass = lang ? ` class="language-${lang}"` : '';
        return `<pre><code${langClass}>${escaped}</code></pre>`;
    };
    marked.setOptions({ renderer, breaks: true, gfm: true });
    return marked.parse(text);
}

// ============ Interactive Quiz Block ============
let _quizIdCounter = 0;
function renderQuizBlock(questions) {
    const qid = `quiz_${++_quizIdCounter}_${Date.now()}`;
    const typeLabels = { choice: '选择题', fill: '填空题', short_answer: '简答题' };
    const diffLabels = { easy: '基础', medium: '中等', hard: '挑战' };
    const diffColors = { easy: 'var(--success)', medium: 'var(--warning)', hard: 'var(--error)' };

    let html = `<div class="quiz-card" id="${qid}" data-quiz='${JSON.stringify(questions).replace(/&/g,"&amp;").replace(/'/g,"&#39;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}'>`;
    html += `<div class="quiz-header"><div class="quiz-header-left"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><span>练习题</span><span class="quiz-count">${questions.length} 题</span></div><div class="quiz-timer" id="${qid}_timer">00:00</div></div>`;

    questions.forEach((q, i) => {
        const diff = q.difficulty || 'medium';
        html += `<div class="quiz-question" data-qid="${q.id}">`;
        html += `<div class="quiz-q-header"><span class="quiz-q-num">第${i + 1}题</span><span class="quiz-q-type">${typeLabels[q.type] || q.type}</span><span class="quiz-q-diff" style="color:${diffColors[diff]}">${diffLabels[diff] || diff}</span></div>`;
        html += `<div class="quiz-q-text">${q.question}</div>`;

        if (q.type === 'choice' && q.options) {
            html += `<div class="quiz-options">`;
            q.options.forEach((opt, oi) => {
                const letter = String.fromCharCode(65 + oi);
                html += `<label class="quiz-option" data-letter="${letter}"><input type="radio" name="${qid}_q${q.id}" value="${letter}"><span class="quiz-option-letter">${letter}</span><span class="quiz-option-text">${opt.replace(/^[A-D]\.\s*/, '')}</span></label>`;
            });
            html += `</div>`;
        } else if (q.type === 'fill') {
            html += `<div class="quiz-fill"><input type="text" class="quiz-fill-input" data-qid="${q.id}" placeholder="输入答案..." autocomplete="off"></div>`;
        } else {
            html += `<div class="quiz-short"><textarea class="quiz-short-input" data-qid="${q.id}" placeholder="输入你的解答..." rows="3"></textarea></div>`;
        }

        if (q.hint) {
            html += `<div class="quiz-hint-toggle" onclick="this.nextElementSibling.classList.toggle('show')">💡 查看提示</div><div class="quiz-hint">${q.hint}</div>`;
        }
        html += `</div>`;
    });

    html += `<div class="quiz-footer"><button class="quiz-submit-btn" onclick="submitQuiz('${qid}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>提交答案</button></div>`;
    html += `</div>`;
    return html;
}

function submitQuiz(quizId) {
    const card = document.getElementById(quizId);
    if (!card) return;
    const btn = card.querySelector('.quiz-submit-btn');
    if (btn.disabled) return;

    let questions;
    try { questions = JSON.parse(card.dataset.quiz); } catch { return; }

    const answers = [];
    let allAnswered = true;

    questions.forEach(q => {
        let ans = '';
        if (q.type === 'choice') {
            const checked = card.querySelector(`input[name="${quizId}_q${q.id}"]:checked`);
            ans = checked ? checked.value : '';
        } else if (q.type === 'fill') {
            const input = card.querySelector(`.quiz-fill-input[data-qid="${q.id}"]`);
            ans = input ? input.value.trim() : '';
        } else {
            const ta = card.querySelector(`.quiz-short-input[data-qid="${q.id}"]`);
            ans = ta ? ta.value.trim() : '';
        }
        if (!ans) allAnswered = false;
        answers.push({ id: q.id, question: q.question, type: q.type, answer: ans, knowledge_point: q.knowledge_point || '' });
    });

    if (!allAnswered) {
        // Highlight unanswered
        const unanswered = answers.filter(a => !a.answer);
        if (unanswered.length > 0) {
            const firstEmpty = card.querySelector(`.quiz-question[data-qid="${unanswered[0].id}"]`);
            if (firstEmpty) { firstEmpty.classList.add('quiz-q-shake'); setTimeout(() => firstEmpty.classList.remove('quiz-q-shake'), 600); firstEmpty.scrollIntoView({behavior:'smooth', block:'center'}); }
        }
        return;
    }

    // Disable button and inputs
    btn.disabled = true;
    btn.innerHTML = '<span class="quiz-submitted-text">✓ 已提交</span>';
    card.querySelectorAll('input, textarea').forEach(el => el.disabled = true);
    card.classList.add('quiz-submitted');

    // Build message from answers
    let msg = '我的答案：\n';
    answers.forEach((a, i) => {
        const label = a.type === 'choice' ? a.answer : a.answer;
        msg += `${i + 1}. ${label}\n`;
    });
    msg += '\n请批改这些题目。';

    // Send as user message
    const input = document.getElementById('chatInput');
    input.value = msg;
    sendMessage();
}

// ============ Quiz Timers ============
const _quizTimers = {};
function initQuizTimers(container) {
    container.querySelectorAll('.quiz-card').forEach(card => {
        const id = card.id;
        if (!id || _quizTimers[id]) return;
        const timerEl = card.querySelector('.quiz-timer');
        if (!timerEl) return;
        const start = Date.now();
        _quizTimers[id] = setInterval(() => {
            const elapsed = Math.floor((Date.now() - start) / 1000);
            const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const s = String(elapsed % 60).padStart(2, '0');
            timerEl.textContent = `${m}:${s}`;
            if (card.classList.contains('quiz-submitted')) {
                clearInterval(_quizTimers[id]);
                delete _quizTimers[id];
            }
        }, 1000);
    });
}

// ============ Result Card Renderers ============
function renderHomeworkResultCard(data) {
    const pct = data.score || 0;
    const total = data.total_questions || 0;
    const correct = data.correct || 0;
    const color = pct >= 80 ? 'var(--success)' : pct >= 60 ? 'var(--warning)' : 'var(--error)';
    let html = `<div class="result-card homework-result-card" style="--result-color:${color}">`;
    html += `<div class="result-card-header"><div class="result-card-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div><span class="result-card-title">作业批改报告</span></div>`;
    html += `<div class="result-card-body">`;
    html += `<div class="result-score-ring"><svg width="80" height="80" viewBox="0 0 80 80"><circle cx="40" cy="40" r="34" fill="none" stroke="rgba(180,146,58,0.1)" stroke-width="6"/><circle cx="40" cy="40" r="34" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${2*Math.PI*34}" stroke-dashoffset="${2*Math.PI*34*(1-pct/100)}" transform="rotate(-90 40 40)" style="transition:stroke-dashoffset 1s ease"/></svg><div class="result-score-text"><span class="result-score-num">${pct}</span><span class="result-score-unit">分</span></div></div>`;
    html += `<div class="result-stats"><div class="result-stat"><span class="result-stat-val">${total}</span><span class="result-stat-label">总题数</span></div><div class="result-stat"><span class="result-stat-val" style="color:var(--success)">${correct}</span><span class="result-stat-label">正确</span></div><div class="result-stat"><span class="result-stat-val" style="color:var(--error)">${total - correct}</span><span class="result-stat-label">错误</span></div></div>`;
    if (data.weak_points && data.weak_points.length) {
        html += `<div class="result-weak"><span class="result-weak-label">薄弱知识点</span><div class="result-weak-tags">${data.weak_points.map(w => `<span class="result-weak-tag">${escapeHtml(w)}</span>`).join('')}</div></div>`;
    }
    if (data.feedback) {
        html += `<div class="result-feedback">${escapeHtml(data.feedback)}</div>`;
    }
    html += `</div></div>`;
    return html;
}

function renderExamResultCard(data) {
    const total = data.total_score || 100;
    const score = data.student_score || 0;
    const pct = Math.round(score / total * 100);
    const color = pct >= 80 ? 'var(--success)' : pct >= 60 ? 'var(--warning)' : 'var(--error)';
    let html = `<div class="result-card exam-result-card" style="--result-color:${color}">`;
    html += `<div class="result-card-header"><div class="result-card-icon" style="color:var(--element-pyro)"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg></div><span class="result-card-title">考试分析报告</span></div>`;
    html += `<div class="result-card-body">`;
    html += `<div class="result-score-ring"><svg width="80" height="80" viewBox="0 0 80 80"><circle cx="40" cy="40" r="34" fill="none" stroke="rgba(180,146,58,0.1)" stroke-width="6"/><circle cx="40" cy="40" r="34" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${2*Math.PI*34}" stroke-dashoffset="${2*Math.PI*34*(1-pct/100)}" transform="rotate(-90 40 40)" style="transition:stroke-dashoffset 1s ease"/></svg><div class="result-score-text"><span class="result-score-num">${score}</span><span class="result-score-unit">/${total}</span></div></div>`;
    html += `<div class="result-stats">`;
    if (data.strong_topics && data.strong_topics.length) {
        html += `<div class="result-topics"><span class="result-topic-label" style="color:var(--success)">✦ 强项</span>${data.strong_topics.map(t => `<span class="result-topic-tag strong">${escapeHtml(t)}</span>`).join('')}</div>`;
    }
    if (data.weak_topics && data.weak_topics.length) {
        html += `<div class="result-topics"><span class="result-topic-label" style="color:var(--error)">✦ 薄弱</span>${data.weak_topics.map(t => `<span class="result-topic-tag weak">${escapeHtml(t)}</span>`).join('')}</div>`;
    }
    html += `</div>`;
    if (data.recommendations && data.recommendations.length) {
        html += `<div class="result-recommendations">${data.recommendations.map(r => `<div class="result-rec-item">→ ${escapeHtml(r)}</div>`).join('')}</div>`;
    }
    html += `</div></div>`;
    return html;
}

function renderStepCompleteCard(stepTitle) {
    return `<div class="step-complete-card"><div class="step-complete-icon">✦</div><div class="step-complete-text"><span class="step-complete-label">教学步骤完成</span><span class="step-complete-title">${escapeHtml(stepTitle)}</span></div><div class="step-complete-sparkles"><span>✧</span><span>✦</span><span>✧</span></div></div>`;
}

function renderReviewCompleteCard(pointName, quality) {
    const labels = ['完全忘记', '几乎忘记', '依稀记得', '需要提示', '基本记住', '完美回忆'];
    const colors = ['var(--error)', 'var(--error)', 'var(--warning)', 'var(--warning)', 'var(--success)', 'var(--success)'];
    const stars = '★'.repeat(quality) + '☆'.repeat(5 - quality);
    return `<div class="review-complete-card"><div class="review-complete-header"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg><span>复习完成</span></div><div class="review-complete-body"><div class="review-complete-point">${escapeHtml(pointName)}</div><div class="review-complete-stars" style="color:${colors[quality]}">${stars}</div><div class="review-complete-label" style="color:${colors[quality]}">${labels[quality] || ''}</div></div></div>`;
}

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
}

// ============ Chat (Send + SSE) ============
function _classifyError(err, response) {
    if (response && response.status === 429) return { type: 'rate_limit', msg: 'API 请求频率超限，请稍后再试' };
    if (response && response.status === 401) return { type: 'auth', msg: 'API 密钥无效或已过期，请检查设置' };
    if (response && response.status === 503) return { type: 'unavailable', msg: '模型服务暂时不可用，请稍后重试' };
    if (response && response.status >= 500) return { type: 'server', msg: `服务器错误 (${response.status})` };
    const m = (err && err.message || '').toLowerCase();
    if (m.includes('timeout') || m.includes('timed out')) return { type: 'timeout', msg: '请求超时，AI 响应时间过长' };
    if (m.includes('abort')) return { type: 'abort', msg: '请求已取消' };
    if (m.includes('network') || m.includes('failed to fetch') || m.includes('net::')) return { type: 'network', msg: '网络连接失败，请检查网络' };
    return { type: 'unknown', msg: err ? err.message : '未知错误' };
}

function _appendErrorWithRetry(errInfo, retryFn, aiContent) {
    const id = 'err-' + Date.now();
    const partial = aiContent ? `<div style="margin-bottom:8px;padding:8px 12px;background:var(--bg-warm);border-radius:8px;border-left:3px solid var(--gold);font-size:12px;color:var(--text-secondary)">⚡ 已接收的部分内容已保留在上方</div>` : '';
    const el = appendMessage('assistant',
        `${partial}<div class="error-retry-card" id="${id}" style="padding:12px 16px;background:rgba(212,90,74,0.06);border:1px solid rgba(212,90,74,0.2);border-radius:10px">` +
        `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">` +
        `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--error)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>` +
        `<span style="font-weight:600;color:var(--error);font-size:13px">⚠️ ${escapeHtml(errInfo.msg)}</span></div>` +
        `<div style="display:flex;gap:8px;margin-top:8px">` +
        `<button class="quick-btn retry-btn" data-id="${id}" style="border-color:var(--gold);color:var(--text-gold);font-weight:500;cursor:pointer;padding:4px 14px">` +
        `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> 重试</button>` +
        `</div></div>`
    );
    el.querySelector('.retry-btn').addEventListener('click', () => {
        el.remove();
        retryFn();
    });
    scrollToBottom();
}

async function sendMessage() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text && state.pendingFiles.length === 0) return;
    if (state.isStreaming) return;
    if (!state.currentCourseId) return;

    if (!state.currentSessionId) {
        await loadCurrentSession();
        if (!state.currentSessionId) return;
    }

    state.isStreaming = true;
    document.getElementById('sendBtn').disabled = true;

    const savedFiles = [...state.pendingFiles];
    state.pendingFiles = [];
    updateFilePreview();

    // Show user message with attachment tags
    const fileNames = savedFiles.map(f => f.name);
    const msgEl = appendMessage('user', text, fileNames);
    input.value = '';
    input.style.height = 'auto';

    // Show upload progress if files exist
    let progressEl = null;
    if (savedFiles.length > 0) {
        progressEl = _showUploadProgress(msgEl, fileNames);
    }

    await _doSendStream(text, savedFiles, false, progressEl);
}

function _showUploadProgress(msgEl, fileNames) {
    const bubble = msgEl.querySelector('.message-bubble');
    const el = document.createElement('div');
    el.className = 'upload-progress-bar';
    el.innerHTML = `
        <div class="upload-progress-icon">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        </div>
        <div class="upload-progress-info">
            <span class="upload-progress-text">上传中... ${fileNames.length} 个文件</span>
            <div class="upload-progress-track"><div class="upload-progress-fill"></div></div>
        </div>`;
    bubble.after(el);
    // Animate progress
    const fill = el.querySelector('.upload-progress-fill');
    let progress = 0;
    const timer = setInterval(() => {
        progress = Math.min(progress + Math.random() * 15 + 5, 90);
        fill.style.width = progress + '%';
    }, 300);
    el._timer = timer;
    el._fill = fill;
    return el;
}

function _completeUploadProgress(progressEl) {
    if (!progressEl) return;
    clearInterval(progressEl._timer);
    progressEl._fill.style.width = '100%';
    progressEl.querySelector('.upload-progress-text').textContent = '✓ 上传完成';
    progressEl.classList.add('upload-complete');
    setTimeout(() => {
        progressEl.style.opacity = '0';
        setTimeout(() => progressEl.remove(), 300);
    }, 1500);
}

async function _doSendStream(text, files, isRetry, progressEl) {
    if (isRetry) {
        state.isStreaming = true;
        document.getElementById('sendBtn').disabled = true;
    }

    const formData = new FormData();
    formData.append('course_id', state.currentCourseId);
    formData.append('session_id', state.currentSessionId);
    formData.append('message', text);
    formData.append('mode', state.chatMode);
    formData.append('tools', JSON.stringify(state.activeTools || []));
    if (state.reviewPoint) {
        formData.append('review_point', state.reviewPoint);
    }
    for (const f of files) {
        formData.append('files', f);
    }

    const typingEl = appendTypingIndicator();
    let aiContent = '';
    let aiEl = null;
    let response = null;

    try {
        response = await fetch('/api/chat', { method: 'POST', body: formData });

        // Files have been uploaded to server at this point
        _completeUploadProgress(progressEl);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6);
                try {
                    const data = JSON.parse(jsonStr);
                    if (data.type === 'chunk') {
                        if (typingEl && typingEl.parentNode) typingEl.remove();
                        if (!aiEl) {
                            aiEl = appendMessage('assistant', '');
                        }
                        aiContent += data.content;
                        const bubble = aiEl.querySelector('.message-bubble');
                        bubble.innerHTML = renderMarkdown(aiContent);
                        bubble.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
                        renderMathInElement(bubble, {
                            delimiters: [
                                { left: '$$', right: '$$', display: true },
                                { left: '$', right: '$', display: false },
                            ],
                            throwOnError: false,
                        });
                        bubble.querySelectorAll('.quiz-q-text, .quiz-option-text, .quiz-fill-input').forEach(el => {
                            renderMathInElement(el, {
                                delimiters: [{ left: '$', right: '$', display: false }],
                                throwOnError: false,
                            });
                        });
                        initQuizTimers(bubble);
                        scrollToBottom();
                    } else if (data.type === 'session_title') {
                        // handled elsewhere
                    } else if (data.type === 'error') {
                        if (typingEl && typingEl.parentNode) typingEl.remove();
                        const errInfo = { type: 'api', msg: data.content };
                        _appendErrorWithRetry(errInfo, () => _doSendStream(text, files, true), aiContent);
                        state.isStreaming = false;
                        document.getElementById('sendBtn').disabled = false;
                        return;
                    } else if (data.type === 'review_completed') {
                        state.chatMode = 'normal';
                        state.reviewPoint = '';
                        document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === 'normal'));
                        updateModeIndicator();
                        saveState();
                        if (aiEl) {
                            const bubble = aiEl.querySelector('.message-bubble');
                            bubble.insertAdjacentHTML('afterend', renderReviewCompleteCard(data.point_name || '', data.quality || 3));
                        }
                    } else if (data.type === 'homework_result') {
                        if (aiEl) {
                            const bubble = aiEl.querySelector('.message-bubble');
                            bubble.insertAdjacentHTML('afterend', renderHomeworkResultCard(data.data));
                            scrollToBottom();
                        }
                    } else if (data.type === 'exam_result') {
                        if (aiEl) {
                            const bubble = aiEl.querySelector('.message-bubble');
                            bubble.insertAdjacentHTML('afterend', renderExamResultCard(data.data));
                            scrollToBottom();
                        }
                    } else if (data.type === 'step_complete') {
                        if (aiEl) {
                            const bubble = aiEl.querySelector('.message-bubble');
                            bubble.insertAdjacentHTML('afterend', renderStepCompleteCard(data.step_title));
                            scrollToBottom();
                        }
                    } else if (data.type === 'done') {
                        if (typingEl && typingEl.parentNode) typingEl.remove();
                        loadMemory();
                    }
                } catch (e) { /* ignore parse errors */ }
            }
        }
    } catch (e) {
        if (typingEl && typingEl.parentNode) typingEl.remove();
        const errInfo = _classifyError(e, response);
        _appendErrorWithRetry(errInfo, () => _doSendStream(text, files, true), aiContent);
    }

    state.isStreaming = false;
    document.getElementById('sendBtn').disabled = false;
}

function appendMessage(role, content, attachments) {
    const container = document.getElementById('chatMessages');
    const el = state.courses.find(c => c.id === state.currentCourseId);
    const elColor = el ? ELEMENT_COLORS[el.element] || ELEMENT_COLORS.pyro : ELEMENT_COLORS.pyro;

    const isUser = role === 'user';
    const attachHtml = (isUser && attachments && attachments.length > 0)
        ? `<div class="msg-attachments">${attachments.map(name => {
            const ext = name.split('.').pop().toLowerCase();
            const isImg = ['jpg','jpeg','png','gif','webp','bmp'].includes(ext);
            return `<span class="msg-attach-tag${isImg ? ' img-tag' : ''}">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${isImg
                    ? '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>'
                    : '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>'
                }</svg>
                ${escapeHtml(name)}</span>`;
        }).join('')}</div>` : '';
    const div = document.createElement('div');
    div.className = `message ${isUser ? 'user-message' : 'ai-message'}`;
    div.innerHTML = `
        <div class="message-avatar"${isUser ? ` style="background:${elColor}22;border-color:${elColor}44"` : ''}>
            ${isUser ? '👤' : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>`}
        </div>
        <div class="message-content">
            <div class="message-bubble ${isUser ? 'user-bubble' : 'ai-bubble'}"${isUser ? ` style="background:${elColor}12;border-color:${elColor}33"` : ''}>
                ${isUser ? escapeHtml(content) : renderMarkdown(content)}
            </div>
            ${attachHtml}
        </div>`;
    container.appendChild(div);
    scrollToBottom();
    return div;
}

function appendTypingIndicator() {
    const container = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `
        <div class="message-avatar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
        </div>
        <div class="message-content">
            <div class="message-bubble ai-bubble">
                <div style="display:flex;gap:4px;padding:8px">
                    <span style="width:8px;height:8px;border-radius:50%;background:var(--gold);animation:typing 1.4s infinite"></span>
                    <span style="width:8px;height:8px;border-radius:50%;background:var(--gold);animation:typing 1.4s infinite 0.2s"></span>
                    <span style="width:8px;height:8px;border-radius:50%;background:var(--gold);animation:typing 1.4s infinite 0.4s"></span>
                </div>
            </div>
        </div>`;
    container.appendChild(div);
    scrollToBottom();
    return div;
}

// ============ Memory ============
async function loadMemory() {
    if (!state.currentCourseId) { state.memory = null; return; }
    const res = await apiGet(`/api/memory/${state.currentCourseId}`);
    if (res.success) {
        state.memory = res.data;
        renderMemory();
    }
}

function renderMemory() {
    if (!state.memory) return;
    const m = state.memory;
    const course = state.courses.find(c => c.id === state.currentCourseId);
    const elColor = course ? ELEMENT_COLORS[course.element] || ELEMENT_COLORS.pyro : ELEMENT_COLORS.pyro;
    const elName = course ? ELEMENT_NAMES[course.element] || '' : '';

    // Course indicator badge
    const indicator = document.getElementById('memoryCourseIndicator');
    if (indicator && course) {
        indicator.style.background = `${elColor}11`;
        indicator.style.color = elColor;
        indicator.style.border = `1px solid ${elColor}33`;
        indicator.textContent = `${elName}元素 · ${course.name}`;
    }

    // Course Info
    const ci = m.course_info || {};
    const hasInstruction = !!ci.description;
    const instrBtn = `<div class="memory-field">
            <span class="field-label">自定义指令</span>
            <button class="instruction-edit-btn" onclick="openInstructionEditor()" title="${hasInstruction ? '编辑自定义指令' : '添加自定义指令'}">
                ${hasInstruction
                    ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg> 编辑`
                    : `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> 添加`}
            </button>
           </div>`;
   document.getElementById('courseInfoDisplay').innerHTML = `
        <div class="memory-field">
            <span class="field-label">课程</span>
            <span class="field-value">${ci.name || '未设置'}</span>
        </div>
        ${instrBtn}
        <div class="memory-field">
            <span class="field-label">元素属性</span>
            <span class="field-value">${elName} · ${ci.subject || course?.name || ''}</span>
        </div>
    `;

    // Progress
    const lp = m.learning_progress || {};
    const mastery = lp.mastery_level || 0;
    const circle = document.getElementById('progressCircle');
    const circumference = 2 * Math.PI * 42;
    circle.style.strokeDasharray = circumference;
    circle.style.strokeDashoffset = circumference * (1 - mastery / 100);
    document.getElementById('progressText').textContent = `${mastery}%`;
    document.getElementById('progressDetails').innerHTML = `
        <div class="progress-phase">当前阶段：${lp.current_phase || '未知'}</div>
        <div class="progress-topic">正在学习：${lp.current_topic || '未知'}</div>
    `;

    // Knowledge Points
    const kps = m.knowledge_points || [];
    const kpBadge = document.getElementById('kpCountBadge');
    if (kpBadge) kpBadge.textContent = kps.length > 0 ? `${kps.length} 个知识点` : '';

    const kpContainer = document.getElementById('knowledgeDisplay');
    // 清理旧的展开按钮
    kpContainer.parentElement.querySelectorAll('.card-expand-btn').forEach(b => b.remove());
    kpContainer.classList.remove('kp-list-collapsible', 'kp-list-expanded');
    if (kps.length === 0) {
        kpContainer.innerHTML = '<div style="font-size:11px;color:var(--text-muted)">暂无知识点数据，与 AI 对话后自动生成</div>';
    } else {
        kpContainer.innerHTML = kps.map(kp => {
            const score = kp.mastery || 0;
            const cls = score >= 80 ? 'good' : score >= 50 ? 'medium' : 'weak';
            return `
            <div class="kp-item">
                <div class="kp-info">
                    <span class="kp-name">${escapeHtml(kp.name)}</span>
                    <span class="kp-chapter">${kp.chapter || ''}</span>
                </div>
                <div class="kp-bar-wrap">
                    <div class="kp-bar" style="width:${score}%">
                        <div class="kp-bar-fill ${cls}" style="width:${score}%"></div>
                    </div>
                    <span class="kp-score ${cls}">${score}</span>
                </div>
            </div>`;
        }).join('');

        // Check for weak points to show review hint
        const weakCount = kps.filter(kp => (kp.mastery || 0) < 50).length;
        if (weakCount > 0) {
            kpContainer.innerHTML += `
            <div class="kp-review-hint">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                ${weakCount} 个命之座待激活（遗忘曲线提示复习）
            </div>`;
        }

        // 折叠逻辑：知识点超过6个时限高
        if (kps.length > 6) {
            kpContainer.classList.add('kp-list-collapsible');
            kpContainer.classList.remove('kp-list-expanded');
            const kpToggle = document.createElement('button');
            kpToggle.className = 'card-expand-btn';
            kpToggle.innerHTML = `<span class="expand-text">展开全部 ${kps.length} 个知识点</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
            kpToggle.addEventListener('click', () => {
                const expanded = kpContainer.classList.toggle('kp-list-expanded');
                kpContainer.classList.toggle('kp-list-collapsible', !expanded);
                kpToggle.innerHTML = expanded
                    ? `<span class="expand-text">收起</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 15 12 9 18 15"/></svg>`
                    : `<span class="expand-text">展开全部 ${kps.length} 个知识点</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
            });
            kpContainer.after(kpToggle);
        }
    }

    // Teaching Plan
    const tp = m.teaching_plan || {};
    const planEl = document.getElementById('planDisplay');
    // 清理旧的展开按钮
    planEl.parentElement.querySelectorAll('.card-expand-btn').forEach(b => b.remove());
    if (tp.steps && tp.steps.length > 0) {
        // Build kp mastery lookup
        const kpMap = {};
        (m.knowledge_points || []).forEach(kp => { kpMap[kp.name] = kp.mastery || 0; });

        const completedCount = tp.steps.filter(s => typeof s === 'object' ? s.status === 'mastered' : false).length;
        const totalCount = tp.steps.length;
        const progressPct = totalCount > 0 ? Math.round(completedCount / totalCount * 100) : 0;

        planEl.innerHTML =
            (tp.direction ? `<div class="plan-direction">${escapeHtml(tp.direction)}</div>` : '') +
            `<div class="plan-progress-bar"><div class="plan-progress-fill" style="width:${progressPct}%"></div><span class="plan-progress-text">${completedCount}/${totalCount} 步完成</span></div>` +
            '<div class="plan-steps">' +
            tp.steps.map((s, i) => {
                // Support both old string format and new object format
                if (typeof s === 'string') {
                    const stepIdx = tp.current_step || 0;
                    const dotCls = i < stepIdx ? 'completed' : i === stepIdx ? 'current' : '';
                    return `<div class="step-item"><span class="step-dot ${dotCls}"></span><span class="step-text">${escapeHtml(s)}</span></div>`;
                }
                const title = s.title || '?';
                const status = s.status || 'not_started';
                const linkedKps = s.linked_kps || [];
                const threshold = s.mastery_threshold || 60;
                const dotCls = status === 'mastered' ? 'completed' : status === 'in_progress' ? 'current' : status === 'needs_review' ? 'needs-review' : '';

                // Build linked KP tags with mini mastery bars
                let kpHtml = '';
                if (linkedKps.length > 0) {
                    kpHtml = '<div class="step-kps">' + linkedKps.map(kn => {
                        const mVal = kpMap[kn] || 0;
                        const barCls = mVal >= threshold ? 'good' : mVal > 0 ? 'medium' : 'empty';
                        return `<span class="step-kp-tag ${barCls}" title="${kn}: ${mVal}% (达标线${threshold}%)"><span class="step-kp-bar" style="width:${mVal}%"></span>${escapeHtml(kn)}</span>`;
                    }).join('') + '</div>';
                }

                const statusLabel = {mastered: '已掌握', in_progress: '学习中', needs_review: '需巩固', not_started: ''}[status] || '';

                const kpNames = linkedKps.map(kn => escapeHtml(kn)).join(',');
                return `<div class="step-item ${status} step-clickable" data-step-index="${i}" data-step-title="${escapeHtml(title)}" data-step-status="${status}" data-step-kps="${kpNames}" title="点击开始学习此步骤">
                    <span class="step-dot ${dotCls}"></span>
                    <div class="step-content">
                        <span class="step-row">
                            <span class="step-text">${escapeHtml(title)}</span>
                            ${statusLabel && status !== 'not_started' ? `<span class="step-status-label ${status}">${statusLabel}</span>` : ''}
                            <button class="step-quiz-btn" data-step-title="${escapeHtml(title)}" data-step-kps="${kpNames}" data-step-status="${status}" title="该步骤章节测验">✦</button>
                        </span>
                        ${kpHtml}
                    </div>
                </div>`;
            }).join('') +
            '</div>';

        // 折叠逻辑：步骤超过5个时限高，自动滚动到当前步骤
        const stepsContainer = planEl.querySelector('.plan-steps');
        if (stepsContainer && tp.steps.length > 5) {
            stepsContainer.classList.add('plan-steps-collapsible');
            stepsContainer.classList.remove('plan-steps-expanded');
            // 添加展开/收起按钮
            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'card-expand-btn';
            toggleBtn.innerHTML = `<span class="expand-text">展开全部 ${tp.steps.length} 个步骤</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
            toggleBtn.addEventListener('click', () => {
                const expanded = stepsContainer.classList.toggle('plan-steps-expanded');
                stepsContainer.classList.toggle('plan-steps-collapsible', !expanded);
                toggleBtn.innerHTML = expanded
                    ? `<span class="expand-text">收起</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 15 12 9 18 15"/></svg>`
                    : `<span class="expand-text">展开全部 ${tp.steps.length} 个步骤</span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
            });
            stepsContainer.after(toggleBtn);

            // 自动滚动到当前步骤
            requestAnimationFrame(() => {
                const currentStep = stepsContainer.querySelector('.step-item.in_progress') || stepsContainer.querySelector('.step-item.needs_review');
                if (currentStep) {
                    currentStep.scrollIntoView({ block: 'center', behavior: 'instant' });
                }
            });
        }

        // 绑定步骤点击事件
        planEl.querySelectorAll('.step-clickable').forEach(stepEl => {
            stepEl.addEventListener('click', () => {
                const title = stepEl.dataset.stepTitle;
                const status = stepEl.dataset.stepStatus;
                if (title) startStepLearning(title, status);
            });
        });

        // 绑定测验按钮点击事件
        planEl.querySelectorAll('.step-quiz-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const title = btn.dataset.stepTitle;
                const kps = btn.dataset.stepKps;
                const status = btn.dataset.stepStatus;
                if (title) startStepQuiz(title, kps, status);
            });
        });
    } else {
        planEl.innerHTML = '<div style="font-size:11px;color:var(--text-muted)">暂无教学计划</div>';
    }

    // Schedule Preview
    const schedule = m.schedule || [];
    const spEl = document.getElementById('schedulePreview');
    // 清理旧的展开按钮
    spEl.parentElement.querySelectorAll('.card-expand-btn').forEach(b => b.remove());
    spEl.classList.remove('schedule-list-collapsible', 'schedule-list-expanded');

    const upcoming = schedule.filter(e => {
        const d = e.datetime || e.date;
        return d && new Date(d) >= new Date();
    });

    if (upcoming.length === 0) {
        spEl.innerHTML = '<div style="font-size:11px;color:var(--text-muted)">暂无近期日程</div>';
    } else {
        spEl.innerHTML = upcoming.map(e => {
            const type = e.type || 'study';
            const typeColor = TYPE_COLORS[type] || TYPE_COLORS.study;
            return `
            <label class="schedule-item">
                <span class="sched-type-icon" style="background:${typeColor}11;color:${typeColor}">
                    ${TYPE_ICONS[type] || '📖'}
                </span>
                <div class="schedule-info">
                    <span class="schedule-title">${escapeHtml(e.title || '学习')}</span>
                    <span class="schedule-time">${formatDate(e.datetime || e.date)}</span>
                </div>
            </label>`;
        }).join('');

        // 折叠逻辑：日程超过4条时限高
        if (upcoming.length > 4) {
            spEl.classList.add('schedule-list-collapsible');
            const schedToggle = document.createElement('button');
            schedToggle.className = 'card-expand-btn';
            schedToggle.innerHTML = `<span class="expand-text">展开全部 ${upcoming.length} 条日程</span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
            schedToggle.addEventListener('click', () => {
                const expanded = spEl.classList.toggle('schedule-list-expanded');
                spEl.classList.toggle('schedule-list-collapsible', !expanded);
                schedToggle.innerHTML = expanded
                    ? `<span class="expand-text">收起</span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>`
                    : `<span class="expand-text">展开全部 ${upcoming.length} 条日程</span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
            });
            spEl.after(schedToggle);
        }
    }
}

// ============ Summary Preview ============
async function showSummaryPreview(filename) {
    // 创建或获取弹窗
    let overlay = document.getElementById('summaryPreviewOverlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'summaryPreviewOverlay';
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="summary-preview-modal">
                <div class="summary-preview-header">
                    <div class="summary-preview-title-wrap">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>
                        <span class="summary-preview-title">摘要预览</span>
                    </div>
                    <div class="summary-preview-meta" id="summaryPreviewMeta"></div>
                    <button class="summary-preview-close" id="summaryPreviewClose">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </div>
                <div class="summary-preview-filename" id="summaryPreviewFilename"></div>
                <div class="summary-preview-body" id="summaryPreviewBody">
                    <div class="summary-loading">加载中...</div>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeSummaryPreview();
        });
        document.getElementById('summaryPreviewClose').addEventListener('click', closeSummaryPreview);
    }

    // 显示弹窗
    overlay.classList.add('active');
    document.getElementById('summaryPreviewFilename').textContent = filename;
    document.getElementById('summaryPreviewMeta').textContent = '';
    document.getElementById('summaryPreviewBody').innerHTML = '<div class="summary-loading"><div class="summary-loading-spinner"></div>正在加载摘要...</div>';

    try {
        const res = await fetch(`/api/references/${encodeURIComponent(state.currentCourseId)}/summary/${encodeURIComponent(filename)}`);
        const data = await res.json();
        if (data.success) {
            const d = data.data;
            const metaText = d.is_raw_text
                ? `原文内容 · ${d.raw_text_length} 字`
                : `原文 ${d.raw_text_length} 字 → 摘要 ${d.summary_length} 字${d.created_at ? ' · ' + new Date(d.created_at).toLocaleString() : ''}`;
            document.getElementById('summaryPreviewMeta').textContent = metaText;
            // 简易 Markdown 渲染
            document.getElementById('summaryPreviewBody').innerHTML =
                '<div class="summary-content">' + renderSummaryMarkdown(d.summary) + '</div>';
        } else {
            document.getElementById('summaryPreviewBody').innerHTML =
                `<div class="summary-empty">${data.error || '未找到摘要'}</div>`;
        }
    } catch (e) {
        document.getElementById('summaryPreviewBody').innerHTML =
            '<div class="summary-empty">加载失败，请检查网络连接</div>';
    }
}

function closeSummaryPreview() {
    const overlay = document.getElementById('summaryPreviewOverlay');
    if (overlay) overlay.classList.remove('active');
}

function renderSummaryMarkdown(text) {
    if (!text) return '<em>暂无内容</em>';
    // 简易 Markdown → HTML（处理标题、加粗、列表、代码块、LaTeX）
    let html = escapeHtml(text);
    // 代码块
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    // 标题（h1-h4）
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // 加粗
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // LaTeX 块公式
    html = html.replace(/\$\$(.+?)\$\$/gs, '<div class="math-block">$$$$1$$</div>');
    // LaTeX 行内公式
    html = html.replace(/\$(.+?)\$/g, '<span class="math-inline">$$$1$</span>');
    // 无序列表
    html = html.replace(/^(\s*)[-*] (.+)$/gm, (m, indent, content) => {
        const level = Math.floor(indent.length / 4);
        return `<li class="summary-li level-${level}">${content}</li>`;
    });
    // 有序列表
    html = html.replace(/^\d+\. (.+)$/gm, '<li class="summary-li summary-li-ordered">$1</li>');
    // 换行
    html = html.replace(/\n/g, '<br>');
    // 清理多余 br
    html = html.replace(/<br>(<h[1-4]>)/g, '$1');
    html = html.replace(/(<\/h[1-4]>)<br>/g, '$1');
    html = html.replace(/<br>(<li )/g, '$1');
    html = html.replace(/(<\/li>)<br>/g, '$1');
    html = html.replace(/<br>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<br>/g, '$1');
    html = html.replace(/<br>(<div class="math-block">)/g, '$1');
    html = html.replace(/(<\/div>)<br>/g, '$1');
    return html;
}

// ============ References ============
async function loadReferences() {
    if (!state.currentCourseId) return;
    const res = await apiGet(`/api/references/${state.currentCourseId}`);
    if (res.success) renderReferences(res.data);
}

function renderReferences(refs) {
    const list = document.getElementById('referencesList');
    const badge = document.getElementById('refCountBadge');
    const actionsBar = document.getElementById('refActionsBar');
    // 清理旧的展开按钮
    list.parentElement.querySelectorAll('.card-expand-btn').forEach(b => b.remove());
    list.classList.remove('ref-list-collapsible', 'ref-list-expanded');

    if (badge) badge.textContent = refs.length > 0 ? `${refs.length} 份圣遗物` : '';

    if (refs.length === 0) {
        list.innerHTML = '<div style="font-size:11px;color:var(--text-muted);text-align:center;padding:12px">暂无参考资料</div>';
        if (actionsBar) actionsBar.style.display = 'none';
        return;
    }

    // 显示操作栏
    if (actionsBar) actionsBar.style.display = 'flex';

    list.innerHTML = refs.map(r => {
        const ext = (r.name || '').split('.').pop().toLowerCase();
        const isImg = ['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext);
        const isAudio = ['mp3', 'wav', 'ogg'].includes(ext);
        const isTxt = ['txt', 'md'].includes(ext);
        const iconCls = isImg ? 'img' : isAudio ? 'audio' : 'pdf';
        const hasSummary = r.has_summary;
        const summaryBadge = hasSummary
            ? `<span class="ref-summary-badge ref-summary-ok ref-view-summary" data-name="${escapeHtml(r.name)}" title="点击查看摘要 (${r.summary_length}字)">✓ 已解析</span>`
            : isTxt
                ? `<span class="ref-summary-badge ref-summary-txt ref-view-summary" data-name="${escapeHtml(r.name)}" title="点击查看内容">文本</span>`
                : `<span class="ref-summary-badge ref-summary-pending" title="点击解析按钮提取内容">未解析</span>`;
        const processBtn = (!hasSummary && !isTxt)
            ? `<button class="ref-process-btn" data-name="${escapeHtml(r.name)}" title="解析内容"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/><polyline points="21 3 21 12 12 12"/></svg></button>`
            : '';
        return `
        <div class="ref-file-item${hasSummary ? ' ref-parsed' : ''}">
            <label class="ref-checkbox-wrap">
                <input type="checkbox" class="ref-checkbox" data-name="${escapeHtml(r.name)}">
                <span class="ref-checkbox-custom"></span>
            </label>
            <div class="ref-file-icon ${iconCls}">
                ${isImg ?
                    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>` :
                  isAudio ?
                    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>` :
                    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`
                }
            </div>
            <div class="ref-file-info">
                <a class="ref-file-name" href="/api/references/${encodeURIComponent(state.currentCourseId)}/file/${encodeURIComponent(r.name)}" target="_blank" style="color:var(--text-primary);text-decoration:none;cursor:pointer" onmouseover="this.style.color='var(--text-gold)'" onmouseout="this.style.color='var(--text-primary)'">${escapeHtml(r.name)}</a>
                <span class="ref-file-meta">${formatSize(r.size)} ${summaryBadge}</span>
            </div>
            ${processBtn}
            <button class="ref-file-delete" data-name="${escapeHtml(r.name)}" title="移除">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>`;
    }).join('');

    // 删除按钮事件
    list.querySelectorAll('.ref-file-delete').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('删除此参考资料？')) return;
            await apiDelete(`/api/references/${state.currentCourseId}/${encodeURIComponent(btn.dataset.name)}`);
            loadReferences();
        });
    });

    // 解析按钮事件
    list.querySelectorAll('.ref-process-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const name = btn.dataset.name;
            btn.disabled = true;
            btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="ref-spin"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>';
            btn.title = '解析中...';
            try {
                const res = await fetch(`/api/references/${state.currentCourseId}/process/${encodeURIComponent(name)}`, { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    loadReferences();
                } else {
                    alert(data.error || '解析失败');
                    btn.disabled = false;
                    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/><polyline points="21 3 21 12 12 12"/></svg>';
                }
            } catch (e) {
                alert('解析请求失败');
                btn.disabled = false;
            }
        });
    });

    // 查看摘要事件
    list.querySelectorAll('.ref-view-summary').forEach(badge => {
        badge.addEventListener('click', (e) => {
            e.stopPropagation();
            showSummaryPreview(badge.dataset.name);
        });
    });

    // 多选框状态管理
    const checkboxes = list.querySelectorAll('.ref-checkbox');
    const selectAllCb = document.getElementById('refSelectAll');
    const selectedCountEl = document.getElementById('refSelectedCount');
    const generateBtn = document.getElementById('generatePlanBtn');

    function updateRefSelection() {
        const checked = list.querySelectorAll('.ref-checkbox:checked');
        const total = checkboxes.length;
        const count = checked.length;

        if (selectedCountEl) {
            selectedCountEl.textContent = count > 0 ? `已选 ${count}/${total}` : '';
        }
        if (generateBtn) {
            generateBtn.disabled = count === 0;
        }
        if (selectAllCb) {
            selectAllCb.checked = count === total && total > 0;
            selectAllCb.indeterminate = count > 0 && count < total;
        }
        // 选中的文件项高亮
        list.querySelectorAll('.ref-file-item').forEach(item => {
            const cb = item.querySelector('.ref-checkbox');
            item.classList.toggle('ref-selected', cb && cb.checked);
        });
    }

    checkboxes.forEach(cb => {
        cb.addEventListener('change', updateRefSelection);
    });

    if (selectAllCb) {
        selectAllCb.onchange = () => {
            checkboxes.forEach(cb => { cb.checked = selectAllCb.checked; });
            updateRefSelection();
        };
    }

    if (generateBtn) {
        generateBtn.onclick = () => {
            const selected = Array.from(list.querySelectorAll('.ref-checkbox:checked'))
                .map(cb => cb.dataset.name);
            if (selected.length > 0) generatePlanFromRefs(selected);
        };
    }

    // "全部解析"按钮
    const processAllBtn = document.getElementById('processAllRefsBtn');
    if (processAllBtn) {
        // 如果所有资料都已解析或都是txt，隐藏按钮
        const hasUnparsed = refs.some(r => {
            const ext = (r.name || '').split('.').pop().toLowerCase();
            return !r.has_summary && !['txt', 'md'].includes(ext);
        });
        processAllBtn.style.display = hasUnparsed ? '' : 'none';
        processAllBtn.onclick = async () => {
            processAllBtn.disabled = true;
            processAllBtn.textContent = '解析中...';
            try {
                const res = await fetch(`/api/references/${state.currentCourseId}/process-all`, { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    loadReferences();
                } else {
                    alert(data.error || '批量解析失败');
                }
            } catch (e) {
                alert('批量解析请求失败');
            }
            processAllBtn.disabled = false;
            processAllBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/><polyline points="21 3 21 12 12 12"/></svg> 全部解析';
        };
    }

    updateRefSelection();

    // 折叠逻辑：参考资料超过4个时限高
    if (refs.length > 4) {
        list.classList.add('ref-list-collapsible');
        const refToggle = document.createElement('button');
        refToggle.className = 'card-expand-btn';
        refToggle.innerHTML = `<span class="expand-text">展开全部 ${refs.length} 份资料</span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
        refToggle.addEventListener('click', () => {
            const expanded = list.classList.toggle('ref-list-expanded');
            list.classList.toggle('ref-list-collapsible', !expanded);
            refToggle.innerHTML = expanded
                ? `<span class="expand-text">收起</span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>`
                : `<span class="expand-text">展开全部 ${refs.length} 份资料</span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`;
        });
        list.after(refToggle);
    }
}

async function uploadReference(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`/api/references/${state.currentCourseId}`, { method: 'POST', body: formData });
    const data = await res.json();
    if (data.success) {
        loadReferences();
        // 上传后后台会自动触发解析，5秒后刷新一次看摘要状态
        setTimeout(() => loadReferences(), 5000);
        // 大文件可能需要更长时间，15秒后再刷一次
        const ext = (file.name || '').split('.').pop().toLowerCase();
        if (['pdf', 'mp3', 'wav', 'ogg'].includes(ext)) {
            setTimeout(() => loadReferences(), 15000);
        }
    }
    else alert(data.error || '上传失败');
}

// ============ Generate Plan from References ============
async function generatePlanFromRefs(selectedFileNames) {
    if (!state.currentCourseId) return;
    if (state.isStreaming) return;

    if (!state.currentSessionId) {
        await loadCurrentSession();
        if (!state.currentSessionId) return;
    }

    // 构建带文件名列表的消息
    const fileList = selectedFileNames.map(n => {
        // 去掉 uuid 前缀，显示原始文件名
        const displayName = n.replace(/^[a-f0-9]{8}_/, '');
        return `「${displayName}」`;
    }).join('、');

    const message = `请根据以下参考资料生成一份详细的教学计划：${fileList}。

上面的「参考资料上下文」中包含了这些资料的完整摘要内容（知识结构、章节、知识点、公式、例题等），请基于这些摘要的实际内容来制定计划，不要只根据文件名猜测。

请仔细分析摘要中的知识点和章节结构，然后：
1. 提取核心知识点，按章节组织
2. 按照由浅入深、循序渐进的原则设计教学步骤
3. 每个步骤要关联具体的知识点（细粒度拆分）
4. 设定合理的掌握度阈值

请先展示完整的教学计划方案让我确认，包括：
- 教学目标
- 教学步骤（每步的标题、关联知识点、难度）
- 建议的学习顺序和时间安排

等我确认后再正式更新到教学计划中。`;

    const input = document.getElementById('chatInput');
    input.value = message;
    await sendMessage();
}

// ============ UI Update ============
function updateChatUI() {
    const hasC = !!state.currentCourseId;
    const hasS = !!state.currentSessionId;
    const emptyState = document.getElementById('emptyState');
    const chatMessages = document.getElementById('chatMessages');
    const chatInputArea = document.getElementById('chatInputArea');

    emptyState.style.display = hasC ? 'none' : 'flex';
    chatMessages.style.display = hasC ? 'flex' : 'none';
    chatInputArea.style.display = hasC ? 'block' : 'none';

    if (!hasS && hasC) {
        chatMessages.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px;font-size:13px">正在加载对话...</div>';
    }
}

function updateFilePreview() {
    const container = document.getElementById('filePreview');
    if (state.pendingFiles.length === 0) {
        container.style.display = 'none';
        return;
    }
    container.style.display = 'flex';
    container.innerHTML = state.pendingFiles.map((f, i) => `
        <div class="preview-item preview-file">
            <div class="preview-file-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <span class="preview-file-name">${escapeHtml(f.name)}</span>
            <button class="preview-remove" data-idx="${i}" title="移除">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>
    `).join('');
    container.querySelectorAll('.preview-remove').forEach(btn => {
        btn.addEventListener('click', () => {
            state.pendingFiles.splice(parseInt(btn.dataset.idx), 1);
            updateFilePreview();
        });
    });
}

// ============ Model & Tool Selection ============
async function loadModels() {
    const res = await apiGet('/api/models');
    if (res.success) {
        state.modelGroups = res.data.models || [];
        state.toolList = res.data.tools || [];
        populateModelSelects();
        renderModelSelector();
        renderToolToggles();
    }
}

function populateModelSelects() {
    document.querySelectorAll('.model-select').forEach(sel => {
        sel.innerHTML = '';
        state.modelGroups.forEach(g => {
            const optgroup = document.createElement('optgroup');
            optgroup.label = g.group;
            g.models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = m.name;
                opt.title = m.desc;
                optgroup.appendChild(opt);
            });
            sel.appendChild(optgroup);
        });
        sel.value = state.currentModel;
    });
}

function renderModelSelector() {
    const dropdown = document.getElementById('modelDropdown');
    if (!dropdown) return;
    const allModels = state.modelGroups.flatMap(g => g.models);
    const cur = allModels.find(m => m.id === state.currentModel);
    document.getElementById('currentModelName').textContent = cur ? cur.name : state.currentModel;

    dropdown.innerHTML = state.modelGroups.map(g => `
        <div class="model-group">
            <div class="model-group-label">${g.group}</div>
            ${g.models.map(m => `
                <div class="model-option ${m.id === state.currentModel ? 'active' : ''}" data-id="${m.id}">
                    <div class="model-option-name">${m.name}</div>
                    <div class="model-option-desc">${m.desc}</div>
                    <div class="model-option-tags">${(m.tags||[]).map(t =>
                        `<span class="model-tag">${t}</span>`).join('')}</div>
                </div>
            `).join('')}
        </div>
    `).join('');

    dropdown.querySelectorAll('.model-option').forEach(opt => {
        opt.addEventListener('click', () => {
            state.currentModel = opt.dataset.id;
            renderModelSelector();
            closeModelDropdown();
            syncModelToSettings();
        });
    });
}

function renderToolToggles() {
    const container = document.getElementById('toolToggles');
    if (!container) return;
    const TOOL_ICONS = {
        search: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
        code: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
        link: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
    };
    container.innerHTML = state.toolList.map(t => {
        const active = state.activeTools.includes(t.id);
        return `<button class="tool-toggle ${active ? 'active' : ''}" data-id="${t.id}" title="${t.desc}">
            ${TOOL_ICONS[t.icon] || ''}
            <span>${t.name}</span>
        </button>`;
    }).join('');

    container.querySelectorAll('.tool-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            const idx = state.activeTools.indexOf(id);
            if (idx >= 0) state.activeTools.splice(idx, 1);
            else state.activeTools.push(id);
            renderToolToggles();
        });
    });
}

function toggleModelDropdown() {
    const dd = document.getElementById('modelDropdown');
    dd.classList.toggle('open');
}
function closeModelDropdown() {
    document.getElementById('modelDropdown')?.classList.remove('open');
}

function syncModelToSettings() {
    document.querySelectorAll('.model-select').forEach(sel => { sel.value = state.currentModel; });
    const gc = gatherGeminiConfig();
    apiPost('/api/settings/gemini', gc);
}

// ============ Settings ============
async function loadSettings() {
    const res = await apiGet('/api/settings');
    if (res.success) {
        state.settings = res.data;
        populateSettings();
    }
}

function populateSettings() {
    if (!state.settings) return;
    const gc = state.settings.gemini_config || {};
    const ic = state.settings.imessage_config || {};

    // Update global model state from settings
    state.currentModel = gc.model || 'gemini-2.5-flash';
    state.activeTools = gc.tools || [];

    document.querySelectorAll('.conn-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.mode === gc.connection_mode);
    });
    document.querySelectorAll('.conn-panel').forEach(p => {
        p.classList.toggle('active', p.dataset.panel === gc.connection_mode);
    });

    document.getElementById('aiStudioKey').value = gc.api_key || '';
    document.querySelectorAll('.model-select').forEach(sel => { sel.value = state.currentModel; });
    document.getElementById('vertexProject').value = gc.vertex_project || '';
    document.getElementById('vertexLocation').value = gc.vertex_location || 'us-central1';
    document.getElementById('openaiKey').value = gc.openai_api_key || '';
    document.getElementById('openaiBaseUrl').value = gc.openai_base_url || 'https://generativelanguage.googleapis.com/v1beta/openai/';
    document.getElementById('customKey').value = gc.custom_api_key || '';
    document.getElementById('customBaseUrl').value = gc.custom_base_url || '';
    document.getElementById('customBackend').value = gc.custom_backend || 'openai';

    // Refresh model selector & tool toggles
    renderModelSelector();
    renderToolToggles();

    document.getElementById('imessageEnabled').checked = ic.enabled || false;
    document.getElementById('smtpHost').value = ic.smtp_host || '';
    document.getElementById('smtpPort').value = ic.smtp_port || 587;
    document.getElementById('smtpUser').value = ic.smtp_user || '';
    document.getElementById('smtpPass').value = ic.smtp_pass || '';
    document.getElementById('toEmail').value = ic.to_email || '';
    document.getElementById('imessageFields').style.display = ic.enabled ? 'block' : 'none';

    // Update Gemini status
    if (gc.api_key || gc.openai_api_key || gc.custom_api_key) {
        const statusEl = document.getElementById('geminiStatus');
        statusEl.querySelector('.status-dot')?.classList.add('online');
    }
}

function gatherGeminiConfig() {
    const mode = document.querySelector('.conn-tab.active')?.dataset.mode || 'ai_studio';
    const panelMap = { ai_studio: 'aiStudioModel', vertex_ai: 'vertexModel', openai_compat: 'openaiModel', custom_endpoint: 'customModel' };
    const selEl = document.getElementById(panelMap[mode]);
    const model = selEl ? selEl.value : state.currentModel;
    state.currentModel = model;

    return {
        connection_mode: mode,
        model: model,
        tools: state.activeTools || [],
        api_key: document.getElementById('aiStudioKey').value,
        vertex_project: document.getElementById('vertexProject').value,
        vertex_location: document.getElementById('vertexLocation').value,
        openai_api_key: document.getElementById('openaiKey').value,
        openai_base_url: document.getElementById('openaiBaseUrl').value,
        custom_api_key: document.getElementById('customKey').value,
        custom_base_url: document.getElementById('customBaseUrl').value,
        custom_backend: document.getElementById('customBackend').value,
    };
}

function gatherImessageConfig() {
    return {
        enabled: document.getElementById('imessageEnabled').checked,
        smtp_host: document.getElementById('smtpHost').value,
        smtp_port: parseInt(document.getElementById('smtpPort').value) || 587,
        smtp_user: document.getElementById('smtpUser').value,
        smtp_pass: document.getElementById('smtpPass').value,
        to_email: document.getElementById('toEmail').value,
    };
}

async function saveSettings() {
    const gc = gatherGeminiConfig();
    const ic = gatherImessageConfig();
    await Promise.all([
        apiPost('/api/settings/gemini', gc),
        apiPost('/api/settings/imessage', ic),
    ]);
    state.settings = { gemini_config: gc, imessage_config: ic };
    closeModal('settingsModal');
    showToast('设置已保存', 'success');
}

async function testConnection() {
    const gc = gatherGeminiConfig();
    const statusEl = document.getElementById('connectionStatus');
    statusEl.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#999"></span> 测试中...';
    const res = await apiPost('/api/settings/test-gemini', gc);
    if (res.success) {
        statusEl.innerHTML = '<span style="width:8px;height:8px;border-radius:50%;background:#5EA83F;box-shadow:0 0 6px rgba(94,168,63,0.5)"></span> 已连接';
        document.getElementById('geminiStatus').querySelector('.status-dot')?.classList.add('online');
    } else {
        statusEl.innerHTML = `<span style="width:8px;height:8px;border-radius:50%;background:#999"></span> ${res.message || '连接失败'}`;
        document.getElementById('geminiStatus').querySelector('.status-dot')?.classList.remove('online');
    }
}

async function testImessage() {
    const btn = document.getElementById('testImessageBtn');
    const oldHTML = btn.innerHTML;
    btn.innerHTML = '发送中...';
    btn.disabled = true;
    try {
        const ic = gatherImessageConfig();
        ic.enabled = true;
        const res = await apiPost('/api/settings/test-imessage', ic);
        if (res.success) {
            showToast('测试邮件已发送，请检查收件邮箱', 'success');
        } else {
            showToast(res.message || '发送失败', 'error');
        }
    } catch (e) {
        showToast('发送失败: ' + e.message, 'error');
    } finally {
        btn.innerHTML = oldHTML;
        btn.disabled = false;
    }
}

// ============ Modal Helpers ============
function openModal(id) {
    document.getElementById(id).classList.add('active');
}
function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// ============ Section Collapse ============
window.toggleSection = function(id) {
    const body = document.getElementById(id + '-body');
    if (body) {
        body.classList.toggle('collapsed');
        const chevron = body.previousElementSibling?.querySelector('.chevron');
        if (chevron) chevron.classList.toggle('rotated');
    }
};

// ============ Course Management ============
let _inheritSelected = new Set();
let _allHistoryCourses = [];  // All courses including archived ones

async function showCreateCourseModal() {
    document.getElementById('courseNameInput').value = '';
    document.getElementById('courseDescInput').value = '';
    document.querySelectorAll('.color-swatch').forEach(d => d.classList.remove('active'));
    document.querySelector('.color-swatch[data-element="pyro"]')?.classList.add('active');
    _inheritSelected.clear();
    document.getElementById('inheritPreview').style.display = 'none';
    document.getElementById('inheritPreview').innerHTML = '';
    openModal('courseModal');
    document.getElementById('courseNameInput').focus();
    // Load all history courses (including archived)
    const res = await apiGet('/api/courses/all-history');
    _allHistoryCourses = res.success ? res.data : [];
    _renderInheritSourceList();
}

function _renderInheritSourceList() {
    const container = document.getElementById('inheritSourceList');
    const courses = _allHistoryCourses || [];
    if (courses.length === 0) {
        container.innerHTML = '<div class="inherit-source-empty">暂无可继承的课程</div>';
        return;
    }

    const elementColors = {
        pyro: '#E2604A', hydro: '#3A9FD4', electro: '#9B5FD4', dendro: '#5EA83F',
        cryo: '#52B5C4', anemo: '#53B89A', geo: '#C49934'
    };
    const elementNames = {
        pyro: '火', hydro: '水', electro: '雷', dendro: '草',
        cryo: '冰', anemo: '风', geo: '岩'
    };

    const checkSvg = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    const trashSvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';

    // Sort: active courses first, then archived
    const sorted = [...courses].sort((a, b) => (a.archived === b.archived ? 0 : a.archived ? 1 : -1));

    container.innerHTML = sorted.map(c => {
        const color = elementColors[c.element] || '#C49934';
        const elName = elementNames[c.element] || '';
        const sel = _inheritSelected.has(c.id);
        const archivedTag = c.archived ? '<span style="font-size:9px;color:var(--text-muted);background:rgba(60,50,36,0.06);padding:1px 6px;border-radius:8px;margin-left:4px">已移除</span>' : '';
        const stats = c.archive_stats || {};
        const hasData = (stats.scores || 0) + (stats.reviews || 0) + (stats.questions || 0) + (stats.kp_snapshots || 0) > 0;
        const statsHtml = hasData ? `<span style="font-size:9px;color:var(--text-muted);margin-left:auto">${stats.scores||0}成绩 ${stats.kp_snapshots||0}快照</span>` : '';
        const purgeBtn = `<button class="inherit-purge-btn" onclick="event.stopPropagation();purgeHistoryCourse('${c.id}','${escapeHtml(c.name)}')" title="永久删除">${trashSvg}</button>`;
        return `<div class="inherit-source-item ${sel ? 'selected' : ''}" data-id="${c.id}" onclick="toggleInheritSource('${c.id}')">
            <div class="inherit-source-check">${sel ? checkSvg : ''}</div>
            <div class="inherit-source-dot" style="background:${color};color:${color}"></div>
            <span class="inherit-source-name">${escapeHtml(c.name)}</span>
            ${archivedTag}
            <span class="inherit-source-meta">${elName}元素</span>
            ${statsHtml}
            ${purgeBtn}
        </div>`;
    }).join('');
}

window.toggleInheritSource = async function(courseId) {
    if (_inheritSelected.has(courseId)) {
        _inheritSelected.delete(courseId);
    } else {
        _inheritSelected.add(courseId);
    }
    _renderInheritSourceList();
    await _updateInheritPreview();
};

window.purgeHistoryCourse = async function(courseId, courseName) {
    // Show purge confirmation inside the inherit list area
    const container = document.getElementById('inheritSourceList');
    const item = container.querySelector(`[data-id="${courseId}"]`);
    if (!item) return;

    // Replace item with confirmation UI
    const origHtml = item.outerHTML;
    item.outerHTML = `<div class="inherit-source-item" style="background:rgba(212,90,74,0.06);border-color:rgba(212,90,74,0.3);flex-direction:column;align-items:stretch;gap:8px;cursor:default" data-id="${courseId}">
        <div style="font-size:12px;color:var(--error);font-weight:600;text-align:center">⚠ 永久删除「${courseName}」？</div>
        <div style="font-size:10px;color:var(--text-secondary);text-align:center;line-height:1.4">将删除该课程的所有文件、会话记录和学习档案数据，此操作不可恢复！</div>
        <div style="display:flex;gap:8px;justify-content:center">
            <button class="reminder-btn secondary" style="font-size:11px;padding:4px 16px" onclick="event.stopPropagation();_cancelPurge('${courseId}')">取消</button>
            <button class="reminder-btn" style="font-size:11px;padding:4px 16px;background:linear-gradient(135deg,#b22222,#D45A4A);color:#fff;border:none" onclick="event.stopPropagation();_executePurge('${courseId}')">永久删除</button>
        </div>
    </div>`;
};

window._cancelPurge = function(courseId) {
    _renderInheritSourceList();
};

window._executePurge = async function(courseId) {
    try {
        const res = await apiDelete(`/api/courses/${courseId}/purge`);
        if (res.success) {
            _inheritSelected.delete(courseId);
            _allHistoryCourses = _allHistoryCourses.filter(c => c.id !== courseId);
            // Also remove from active courses if present
            state.courses = state.courses.filter(c => c.id !== courseId);
            if (state.currentCourseId === courseId) {
                state.currentCourseId = state.courses.length ? state.courses[0].id : null;
                state.currentSessionId = null;
            }
            renderCourseTabs();
            _renderInheritSourceList();
            await _updateInheritPreview();
            showToast('课程已永久删除', 'success');
        } else {
            showToast(res.error || '删除失败', 'error');
            _renderInheritSourceList();
        }
    } catch (err) {
        console.error('Purge failed:', err);
        showToast('删除失败：' + err.message, 'error');
        _renderInheritSourceList();
    }
};

async function _updateInheritPreview() {
    const preview = document.getElementById('inheritPreview');
    if (_inheritSelected.size === 0) {
        preview.style.display = 'none';
        preview.innerHTML = '';
        return;
    }

    preview.style.display = 'block';
    preview.innerHTML = '<div style="text-align:center;padding:8px"><span style="font-size:11px;color:var(--text-muted)">加载预览...</span></div>';

    try {
        let totalKps = 0, avgMastery = 0;
        let strongKps = [], weakKps = [];
        let sourceNames = [];
        let profileNotes = [];

        for (const cid of _inheritSelected) {
            const res = await apiGet(`/api/archive/${cid}/inherit-preview`);
            if (!res.success) continue;
            const d = res.data;
            sourceNames.push(d.course_name);
            totalKps += d.kp_count;
            avgMastery += d.avg_mastery * d.kp_count;

            for (const kp of (d.kp_summary || [])) {
                if (kp.mastery >= 80) strongKps.push(kp);
                else if (kp.mastery < 50 && kp.interaction_depth >= 1) weakKps.push(kp);
            }
            const sp = d.student_profile || {};
            if (sp.learning_style) profileNotes.push(sp.learning_style);
            if (sp.notes) profileNotes.push(sp.notes);
        }

        if (totalKps > 0) avgMastery = Math.round(avgMastery / totalKps);

        const strongHtml = strongKps.length > 0
            ? `<div style="margin-top:6px"><span style="font-size:10px;color:var(--success);font-weight:600">已掌握:</span> ${strongKps.slice(0,8).map(kp => `<span class="inherit-kp-tag good">${escapeHtml(kp.name)} ${kp.mastery}%</span>`).join('')}</div>`
            : '';
        const weakHtml = weakKps.length > 0
            ? `<div style="margin-top:4px"><span style="font-size:10px;color:var(--error);font-weight:600">薄弱项:</span> ${weakKps.slice(0,8).map(kp => `<span class="inherit-kp-tag weak">${escapeHtml(kp.name)} ${kp.mastery}%</span>`).join('')}</div>`
            : '';
        const profileHtml = profileNotes.length > 0
            ? `<div style="margin-top:6px;font-size:10px;color:var(--text-secondary);line-height:1.4">学生特点: ${escapeHtml(profileNotes.join('; '))}</div>`
            : '';

        preview.innerHTML = `
            <div class="inherit-preview-title">◆ 能力档案预览</div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:6px">以下信息将作为学生画像提供给 AI，新课程的知识点和题库从空白开始。</div>
            <div class="inherit-preview-stats">
                <span class="inherit-preview-stat">来源: <strong>${sourceNames.join(', ')}</strong></span>
                <span class="inherit-preview-stat">先修知识点: <strong>${totalKps}</strong></span>
                <span class="inherit-preview-stat">平均掌握度: <strong>${avgMastery}%</strong></span>
            </div>
            ${strongHtml}${weakHtml}${profileHtml}
        `;
    } catch (e) {
        preview.innerHTML = '<div style="font-size:11px;color:var(--error);padding:8px">预览加载失败</div>';
    }
}

async function createCourse() {
    const name = document.getElementById('courseNameInput').value.trim();
    if (!name) return;
    const element = document.querySelector('.color-swatch.active')?.dataset.element || 'pyro';
    const desc = document.getElementById('courseDescInput').value.trim();

    const payload = { name, element, description: desc };
    if (_inheritSelected.size > 0) {
        payload.inherit_from = Array.from(_inheritSelected);
    }

    const btn = document.getElementById('createCourseBtn');
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span style="display:flex;align-items:center;gap:6px"><span style="width:12px;height:12px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite"></span>创建中...</span>';

    try {
        const res = await apiPost('/api/courses', payload);
        if (res.success) {
            closeModal('courseModal');
            await loadCourses();
            switchCourse(res.data.id);
            if (res.data.inherited) {
                showToast(`已导入 ${res.data.source_courses?.join(', ')} 的学习档案 (${res.data.prior_kp_count} 个先修知识点)`, 'success');
            }
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = origText;
    }
}

// ============ Memory Edit ============
function openMemoryEditor() {
    if (!state.memory) return;
    document.getElementById('memoryEditArea').value = JSON.stringify(state.memory, null, 2);
    openModal('memoryEditModal');
}

async function saveMemoryEdit() {
    try {
        const data = JSON.parse(document.getElementById('memoryEditArea').value);
        await apiPost(`/api/memory/${state.currentCourseId}`, data);
        closeModal('memoryEditModal');
        await loadMemory();
        showToast('记忆文件已更新', 'success');
    } catch (e) {
        alert('JSON 格式错误: ' + e.message);
    }
}

// ============ Custom Instruction Edit ============
window.openInstructionEditor = function() {
    if (!state.currentCourseId) return;
    const current = state.memory?.course_info?.description || '';
    document.getElementById('instructionEditArea').value = current;
    openModal('instructionEditModal');
};

async function saveInstruction() {
    if (!state.currentCourseId) return;
    const instruction = document.getElementById('instructionEditArea').value.trim();
    const res = await apiPut(`/api/courses/${state.currentCourseId}`, { description: instruction });
    if (res.success) {
        closeModal('instructionEditModal');
        await loadMemory();
        showToast('自定义指令已更新', 'success');
    } else {
        alert(res.error || '保存失败');
    }
}

// ============ Notifications ============
let _reminderSSE = null;
function initReminderSSE() {
    if (_reminderSSE) { try { _reminderSSE.close(); } catch(_) {} }
    const evtSource = new EventSource('/api/reminders/stream');
    _reminderSSE = evtSource;
    evtSource.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'heartbeat') return;
            showNotification(data);
        } catch (_) {}
    };
    evtSource.onerror = () => {
        try { evtSource.close(); } catch(_) {}
        _reminderSSE = null;
        setTimeout(initReminderSSE, 5000);
    };
}

function _hideAreaIfEmpty(area) {
    if (!area.children.length) {
        area.style.transform = 'translateX(400px)';
        area.style.opacity = '0';
        area.style.pointerEvents = 'none';
    }
}

function _removeNotification(el) {
    const area = el.closest('#notificationArea');
    el.remove();
    if (area) _hideAreaIfEmpty(area);
}

function showNotification(data) {
    const area = document.getElementById('notificationArea');
    area.style.cssText = 'position:fixed;top:70px;right:16px;z-index:200;display:flex;flex-direction:column;gap:8px;max-width:360px;transform:none;opacity:1;pointer-events:auto';

    const div = document.createElement('div');
    div.style.cssText = 'background:rgba(255,253,245,0.96);border:1px solid rgba(180,146,58,0.4);border-radius:14px;padding:14px 16px;box-shadow:0 4px 30px rgba(212,168,83,0.18),0 8px 32px rgba(60,50,36,0.1);animation:slideInRight 0.3s ease;position:relative;overflow:hidden';

    if (data.type === 'schedule') {
        div.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                <span style="font-size:14px">📅</span>
                <span style="font-size:13px;font-weight:500;color:var(--gold-dark);flex:1">${data.course_name} - 日程提醒</span>
                <button onclick="_removeNotification(this.closest('[style]'))" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px">✕</button>
            </div>
            <div style="font-size:12px;color:var(--text-secondary)">${data.event?.title || '学习任务'} 将在 ${data.minutes_until} 分钟后开始</div>`;
    } else if (data.type === 'review') {
        div.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                <span style="font-size:14px">📚</span>
                <span style="font-size:13px;font-weight:500;color:var(--gold-dark);flex:1">${data.course_name} - 每日委托</span>
                <button onclick="_removeNotification(this.closest('[style]'))" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px">✕</button>
            </div>
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">有 ${data.count} 个知识点需要复习</div>
            <a href="/schedule" class="init-course-btn" style="width:auto;padding:6px 14px;font-size:12px;text-decoration:none;display:inline-flex">查看日程</a>`;
    }
    area.appendChild(div);
    setTimeout(() => { div.remove(); _hideAreaIfEmpty(area); }, 15000);

    if (Notification.permission === 'granted') {
        new Notification(`EduChat - ${data.course_name || ''}`, {
            body: data.type === 'schedule' ? `${data.event?.title} 即将开始` : `${data.count} 个知识点需复习`,
        });
    }
}

function showToast(msg, type = 'info') {
    const area = document.getElementById('notificationArea');
    area.style.cssText = 'position:fixed;top:70px;right:16px;z-index:200;display:flex;flex-direction:column;gap:8px;max-width:360px;transform:none;opacity:1;pointer-events:auto';

    const div = document.createElement('div');
    div.style.cssText = 'background:rgba(255,253,245,0.96);border:1px solid rgba(180,146,58,0.4);border-radius:14px;padding:14px 16px;box-shadow:0 4px 30px rgba(212,168,83,0.18);animation:slideInRight 0.3s ease';
    div.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:13px;font-weight:500;color:var(--gold-dark);flex:1">${msg}</span>
            <button onclick="_removeNotification(this.closest('[style]'))" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px">✕</button>
        </div>`;
    area.appendChild(div);
    setTimeout(() => { div.remove(); _hideAreaIfEmpty(area); }, 3000);
}

// ============ Helpers ============
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}




function formatDate(isoStr) {
    if (!isoStr) return '';
    return new Date(isoStr).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

// ============ Event Listeners ============
document.addEventListener('DOMContentLoaded', async () => {
    await restoreState();
    await Promise.all([loadCourses(), loadSettings(), loadModels()]);

    if (state.currentCourseId) {
        const courseExists = state.courses.find(c => c.id === state.currentCourseId);
        if (courseExists) {
            renderCourseTabs();
            await Promise.all([loadCurrentSession(), loadMemory(), loadReferences()]);
        } else {
            state.currentCourseId = null;
        }
    }
    updateChatUI();

    // Sidebar state
    if (state.sidebarCollapsed) {
        document.getElementById('sidebar').classList.add('collapsed');
    }

    // Chat mode
    document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === state.chatMode);
    });
    updateModeIndicator();

    // Notification permission
    if (Notification.permission === 'default') {
        Notification.requestPermission();
    }

    // Start reminder SSE
    initReminderSSE();

    // Check for review mode from URL params
    const urlParams = new URLSearchParams(window.location.search);
    const reviewCourse = urlParams.get('course');
    const reviewPoint = urlParams.get('review_point');
    const urlAction = urlParams.get('action');
    if (reviewCourse && reviewPoint) {
        // Clean URL without reload
        window.history.replaceState({}, '', '/');
        // Start review flow
        startReviewFlow(reviewCourse, reviewPoint);
    } else if (reviewCourse && urlAction) {
        const eventTitle = urlParams.get('event_title') || '';
        const studyTopic = urlParams.get('study_topic') || '';
        const openUpload = urlParams.get('open_upload') === '1';
        window.history.replaceState({}, '', '/');
        startScheduleAction(reviewCourse, urlAction, eventTitle, studyTopic, openUpload);
    }

    // --- Click handlers ---
    // Model selector dropdown
    document.getElementById('modelSelectorBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleModelDropdown();
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#modelSelector')) closeModelDropdown();
    });

    // Course tabs: event delegation for dynamic tabs
    const courseTabsEl = document.getElementById('courseTabs');
    courseTabsEl.addEventListener('click', (e) => {
        const closeBtn = e.target.closest('.tab-close');
        if (closeBtn) {
            e.stopPropagation();
            deleteCourse(closeBtn.dataset.id);
            return;
        }
        const tab = e.target.closest('.course-tab');
        if (tab) {
            switchCourse(tab.dataset.id);
        }
    });
    courseTabsEl.addEventListener('scroll', updateCourseTabScrollButtons);
    window.addEventListener('resize', updateCourseTabScrollButtons);
    document.getElementById('courseTabScrollLeft').addEventListener('click', () => {
        courseTabsEl.scrollBy({ left: -160, behavior: 'smooth' });
        setTimeout(updateCourseTabScrollButtons, 350);
    });
    document.getElementById('courseTabScrollRight').addEventListener('click', () => {
        courseTabsEl.scrollBy({ left: 160, behavior: 'smooth' });
        setTimeout(updateCourseTabScrollButtons, 350);
    });

    document.getElementById('sidebarToggle').addEventListener('click', () => {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        document.getElementById('sidebar').classList.toggle('collapsed');
        saveState();
    });

    document.getElementById('addCourseBtn').addEventListener('click', showCreateCourseModal);
    document.getElementById('closeCourseModalBtn').addEventListener('click', () => closeModal('courseModal'));
    document.getElementById('createCourseBtn').addEventListener('click', createCourse);

    document.querySelectorAll('.color-swatch').forEach(dot => {
        dot.addEventListener('click', () => {
            document.querySelectorAll('.color-swatch').forEach(d => d.classList.remove('active'));
            dot.classList.add('active');
        });
    });

    // Settings
    document.getElementById('settingsBtn').addEventListener('click', () => {
        populateSettings();
        openModal('settingsModal');
    });
    document.getElementById('closeSettingsBtn').addEventListener('click', () => closeModal('settingsModal'));
    document.getElementById('saveSettingsBtn').addEventListener('click', saveSettings);
    document.getElementById('testConnectionBtn').addEventListener('click', testConnection);

    document.querySelectorAll('.conn-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.conn-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.conn-panel').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            document.querySelector(`.conn-panel[data-panel="${tab.dataset.mode}"]`).classList.add('active');
        });
    });

    document.getElementById('imessageEnabled').addEventListener('change', (e) => {
        document.getElementById('imessageFields').style.display = e.target.checked ? 'block' : 'none';
    });

    // Chat modes
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            state.chatMode = btn.dataset.mode;
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            updateModeIndicator();
            saveState();
        });
    });
    document.getElementById('modeCancelBtn')?.addEventListener('click', async () => {
        // 如果当前是复习模式，退出时自动完成复习（默认 quality=3）
        if (state.chatMode === 'review' && state.reviewPoint && state.currentCourseId) {
            try {
                await apiPost(`/api/review/${state.currentCourseId}/complete`, {
                    point_name: state.reviewPoint,
                    quality: 3,
                });
            } catch (_) {}
        }
        state.chatMode = 'normal';
        state.reviewPoint = '';
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === 'normal'));
        updateModeIndicator();
        saveState();
    });

    // Chat input
    const chatInput = document.getElementById('chatInput');
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
    });
    document.getElementById('sendBtn').addEventListener('click', sendMessage);

    // File uploads
    document.getElementById('chatFileInput').addEventListener('change', (e) => {
        for (const f of e.target.files) state.pendingFiles.push(f);
        updateFilePreview();
        e.target.value = '';
    });

    document.getElementById('refUploadInput').addEventListener('change', (e) => {
        for (const f of e.target.files) uploadReference(f);
        e.target.value = '';
    });

    // Drag & drop for references
    const dropZone = document.getElementById('refDropZone');
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.style.borderColor = 'var(--gold)'; dropZone.style.background = 'rgba(212,168,83,0.04)'; });
    dropZone.addEventListener('dragleave', () => { dropZone.style.borderColor = ''; dropZone.style.background = ''; });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '';
        dropZone.style.background = '';
        for (const f of e.dataTransfer.files) uploadReference(f);
    });

    // Drag & drop for chat input
    const inputWrapper = document.getElementById('inputWrapper');
    const dragOverlay = document.getElementById('dragOverlay');
    if (inputWrapper && dragOverlay) {
        inputWrapper.addEventListener('dragenter', (e) => { e.preventDefault(); dragOverlay.classList.add('active'); });
        inputWrapper.addEventListener('dragleave', (e) => { if (!inputWrapper.contains(e.relatedTarget)) dragOverlay.classList.remove('active'); });
        inputWrapper.addEventListener('dragover', (e) => { e.preventDefault(); });
        inputWrapper.addEventListener('drop', (e) => {
            e.preventDefault();
            dragOverlay.classList.remove('active');
            for (const f of e.dataTransfer.files) state.pendingFiles.push(f);
            updateFilePreview();
        });
    }

    // Ctrl+V paste images into chat input
    chatInput.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.kind === 'file') {
                const file = item.getAsFile();
                if (file) {
                    state.pendingFiles.push(file);
                    updateFilePreview();
                }
            }
        }
    });

    // Memory editor
    document.getElementById('editMemoryBtn').addEventListener('click', openMemoryEditor);
    document.getElementById('closeMemoryEditBtn').addEventListener('click', () => closeModal('memoryEditModal'));
    document.getElementById('saveMemoryEditBtn').addEventListener('click', saveMemoryEdit);

    // Instruction editor
    document.getElementById('closeInstructionEditBtn').addEventListener('click', () => closeModal('instructionEditModal'));
    document.getElementById('saveInstructionBtn').addEventListener('click', saveInstruction);

    // Remove course modal (soft delete)
    document.getElementById('closeDeleteCourseBtn').addEventListener('click', () => {
        state._pendingDeleteCourseId = null;
        clearDeleteCountdown();
        closeModal('deleteCourseModal');
    });
    document.getElementById('cancelDeleteCourseBtn').addEventListener('click', () => {
        state._pendingDeleteCourseId = null;
        clearDeleteCountdown();
        closeModal('deleteCourseModal');
    });
    document.getElementById('confirmDeleteCourseBtn').addEventListener('click', executeRemoveCourse);

    // Archive modal
    document.getElementById('closeArchiveBtn').addEventListener('click', () => closeModal('archiveModal'));

    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                if (overlay.id === 'deleteCourseModal') {
                    state._pendingDeleteCourseId = null;
                    clearDeleteCountdown();
                }
                overlay.classList.remove('active');
            }
        });
    });

    // Toggle password visibility
    document.querySelectorAll('.toggle-visibility').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = btn.parentElement.querySelector('input');
            if (input) input.type = input.type === 'password' ? 'text' : 'password';
        });
    });

    // beforeunload - sync state save
    window.addEventListener('beforeunload', () => {
        const data = JSON.stringify({
            current_course_id: state.currentCourseId,
            current_session_id: state.currentSessionId,
            sidebar_collapsed: state.sidebarCollapsed,
            chat_mode: state.chatMode,
        });
        navigator.sendBeacon('/api/state', new Blob([data], { type: 'application/json' }));
    });
});

// ============ Step Learning Flow ============
async function startStepLearning(stepTitle, stepStatus) {
    if (!state.currentCourseId) return;
    if (state.isStreaming) return;

    // Ensure we have a session
    if (!state.currentSessionId) {
        await loadCurrentSession();
        if (!state.currentSessionId) return;
    }

    // Build appropriate message based on step status
    let message;
    if (stepStatus === 'mastered') {
        message = `我想复习一下「${stepTitle}」这个步骤的内容，帮我巩固一下吧`;
    } else if (stepStatus === 'in_progress' || stepStatus === 'needs_review') {
        message = `我们继续学习「${stepTitle}」吧`;
    } else {
        message = `我们开始学习「${stepTitle}」吧`;
    }

    // Set the message in input and send
    const input = document.getElementById('chatInput');
    input.value = message;
    await sendMessage();
}

// ============ Step Quiz Flow ============
async function startStepQuiz(stepTitle, kpNames, stepStatus) {
    if (!state.currentCourseId) return;
    if (state.isStreaming) return;

    if (!state.currentSessionId) {
        await loadCurrentSession();
        if (!state.currentSessionId) return;
    }

    const kpList = kpNames ? kpNames.split(',').filter(Boolean) : [];
    const kpStr = kpList.length > 0 ? kpList.map(k => `「${k}」`).join('、') : '';

    let message;
    if (stepStatus === 'not_started') {
        // 未开始学习：出预习摸底题，了解基础水平
        message = `请针对「${stepTitle}」这个步骤出一套预习摸底测验`;
        if (kpStr) message += `，涉及知识点：${kpStr}`;
        message += `。先出3-4道基础概念题，帮我了解自己对这部分内容的基础水平`;
    } else if (stepStatus === 'in_progress') {
        // 学习中：出阶段检测题，检验当前学习成果
        message = `我正在学习「${stepTitle}」，请出一套阶段检测题`;
        if (kpStr) message += `，覆盖知识点：${kpStr}`;
        message += `。请设计5道左右的题目，从易到难，包含概念理解和简单应用，帮我检验当前的学习掌握情况`;
    } else if (stepStatus === 'needs_review') {
        // 需巩固：出针对薄弱点的强化题
        message = `「${stepTitle}」这个步骤我还需要巩固，请出一套针对性强化测验`;
        if (kpStr) message += `，重点考察：${kpStr}`;
        message += `。请着重出我容易出错的题型，4-5道，帮助我查漏补缺`;
    } else if (stepStatus === 'mastered') {
        // 已掌握：出综合提升题，拔高和拓展
        message = `「${stepTitle}」我已基本掌握，请出一套综合提升测验`;
        if (kpStr) message += `，涵盖：${kpStr}`;
        message += `。请设计4-5道有一定难度的综合应用题和拓展题，帮助我进一步深化理解`;
    }

    const input = document.getElementById('chatInput');
    input.value = message;
    await sendMessage();
}

// ============ Review Flow ============
async function startReviewFlow(courseId, pointName) {
    // Switch to the course (this also loads the single session)
    if (state.currentCourseId !== courseId) {
        await switchCourse(courseId);
    }
    // Ensure we have a session
    if (!state.currentSessionId) {
        await loadCurrentSession();
    }

    // Set review mode
    state.chatMode = 'review';
    state.reviewPoint = pointName;
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    updateModeIndicator();
    saveState();

    // Auto-send the trigger message in the existing session
    const input = document.getElementById('chatInput');
    input.value = `开始复习「${pointName}」`;
    await sendMessage();
}

// ============ Schedule Action Flow (study / homework / exam) ============
async function startScheduleAction(courseId, action, eventTitle, studyTopic, openUpload) {
    // Switch to course
    if (state.currentCourseId !== courseId) {
        await switchCourse(courseId);
    }
    if (!state.currentSessionId) {
        await loadCurrentSession();
    }

    if (action === 'study') {
        // Study mode: keep normal chatMode, auto-send study prompt
        state.chatMode = 'normal';
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === 'normal'));
        updateModeIndicator();
        saveState();

        const input = document.getElementById('chatInput');
        if (studyTopic) {
            input.value = `我想学习「${studyTopic}」，请开始教学`;
        } else {
            input.value = `开始学习「${eventTitle}」，请按照当前学习计划的进度继续教学`;
        }
        await sendMessage();

    } else if (action === 'homework_check' || action === 'exam_analysis') {
        // Set homework/exam mode
        state.chatMode = action;
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === action));
        updateModeIndicator();
        saveState();

        // Pre-fill default instruction (don't auto-send, let user review/edit)
        const input = document.getElementById('chatInput');
        const typeLabel = action === 'homework_check' ? '作业' : '考试';
        input.value = `这是我今天的${typeLabel}结果，帮我检查一下并且一起订正：`;
        input.focus();

        if (openUpload) {
            // Highlight the attach button to guide user to click it
            const attachBtn = document.querySelector('.attach-btn');
            if (attachBtn) {
                attachBtn.classList.add('attach-btn-pulse');
                setTimeout(() => attachBtn.classList.remove('attach-btn-pulse'), 4000);
            }
        }
    }
}

function updateModeIndicator() {
    const indicator = document.getElementById('modeIndicator');
    if (state.chatMode === 'normal') {
        indicator.style.display = 'none';
    } else {
        indicator.style.display = 'flex';
        const isHomework = state.chatMode === 'homework_check';
        const isExam = state.chatMode === 'exam_analysis';
        const isReview = state.chatMode === 'review';
        let text, color, bg, border;
        if (isReview) {
            text = `每日委托 · 复习「${state.reviewPoint || ''}」`;
            color = 'var(--element-electro, #9B5FD4)';
            bg = 'rgba(155,95,212,0.06)';
            border = '1px solid rgba(155,95,212,0.2)';
        } else if (isHomework) {
            text = '派遣探索 · 作业检查模式';
            color = 'var(--type-homework, #C49934)';
            bg = 'rgba(196,153,52,0.06)';
            border = '1px solid rgba(196,153,52,0.2)';
        } else {
            text = '深境螺旋 · 考试分析模式';
            color = 'var(--type-exam, #E2604A)';
            bg = 'rgba(226,96,74,0.06)';
            border = '1px solid rgba(226,96,74,0.2)';
        }
        indicator.style.background = bg;
        indicator.style.color = color;
        indicator.style.border = border;
        document.getElementById('modeIndicatorText').innerHTML = `
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${isReview ? '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>' : isHomework ? '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>' : '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'}</svg>
            ${text}`;
    }
}

// ============ Archive (学习档案) ============
let _archiveTab = 'overview';

window.openArchiveViewer = async function() {
    if (!state.currentCourseId) { showToast('请先选择课程', 'info'); return; }
    _archiveTab = 'overview';
    openModal('archiveModal');
    initArchiveTabs();
    await loadArchiveTab('overview');
};

function initArchiveTabs() {
    document.querySelectorAll('.archive-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === _archiveTab);
        tab.onclick = () => {
            _archiveTab = tab.dataset.tab;
            document.querySelectorAll('.archive-tab').forEach(t => t.classList.toggle('active', t === tab));
            loadArchiveTab(tab.dataset.tab);
        };
    });
}

async function loadArchiveTab(tab) {
    const content = document.getElementById('archiveContent');
    content.innerHTML = '<div class="archive-loading"><span style="display:flex;gap:4px;align-items:center"><span style="width:6px;height:6px;border-radius:50%;background:var(--gold);animation:typing 1.2s infinite"></span><span style="width:6px;height:6px;border-radius:50%;background:var(--gold);animation:typing 1.2s infinite 0.2s"></span><span style="width:6px;height:6px;border-radius:50%;background:var(--gold);animation:typing 1.2s infinite 0.4s"></span></span><span style="font-size:12px;color:var(--text-muted);margin-top:8px">加载中...</span></div>';
    try {
        if (tab === 'overview') await renderArchiveOverview(content);
        else if (tab === 'scores') await renderArchiveScores(content);
        else if (tab === 'reviews') await renderArchiveReviews(content);
        else if (tab === 'questions') await renderArchiveQuestions(content);
        else if (tab === 'snapshots') await renderArchiveSnapshots(content);
    } catch (e) {
        content.innerHTML = `<div class="archive-empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><p>加载失败: ${escapeHtml(e.message)}</p></div>`;
    }
}

async function renderArchiveOverview(el) {
    const cid = state.currentCourseId;
    const [statsRes, kpRes, memRes, qbRes] = await Promise.all([
        apiGet(`/api/archive/${cid}/stats`),
        apiGet(`/api/archive/${cid}/kp-snapshots?limit=100`),
        apiGet(`/api/memory/${cid}`),
        apiGet(`/api/question-bank/${cid}`),
    ]);
    const s = statsRes.data || {};
    const kpData = kpRes.data || [];
    const mem = memRes.data || {};
    const qb = qbRes.data || {};
    const sp = mem.student_profile || {};
    const qa = mem.quiz_analysis || {};
    const kps = mem.knowledge_points || [];
    const lp = mem.learning_progress || {};

    const fmt = d => d ? new Date(d).toLocaleDateString('zh-CN', {year:'numeric', month:'short', day:'numeric'}) : '—';

    // Compute real-time stats from memory
    const activeKps = kps.filter(k => k.interaction_depth > 0);
    const totalPractice = kps.reduce((sum, k) => sum + (k.practice_total || 0), 0);
    const totalCorrect = kps.reduce((sum, k) => sum + (k.practice_correct || 0), 0);
    const practiceAccuracy = totalPractice > 0 ? Math.round(totalCorrect / totalPractice * 100) : 0;
    const avgMastery = activeKps.length > 0 ? Math.round(activeKps.reduce((sum, k) => sum + (k.mastery || 0), 0) / activeKps.length) : 0;
    const reviewSchedule = mem.review_schedule || [];
    // Question bank stats (active + archived)
    const qbWrong = qb.wrong || 0;
    const qbTotal = qb.total || 0;
    const archivedQuestions = s.questions_count || 0;

    // Student profile card
    const hasProfile = sp.learning_style || sp.notes || (sp.difficulty_preference && sp.difficulty_preference !== 'medium');
    const diffMap = {'easy':'基础','medium':'适中','medium-hard':'中高','hard':'挑战'};
    let profileHtml = '';
    if (hasProfile) {
        profileHtml = `<div class="archive-profile-card">
            <div class="memory-card-title" style="margin-bottom:10px">冒险者档案 · 学生特点</div>
            <div class="archive-profile-items">
                ${sp.learning_style ? `<div class="archive-profile-item"><span class="archive-profile-label">学习风格</span><span class="archive-profile-value">${escapeHtml(sp.learning_style)}</span></div>` : ''}
                ${sp.difficulty_preference ? `<div class="archive-profile-item"><span class="archive-profile-label">难度偏好</span><span class="archive-profile-value">${escapeHtml(diffMap[sp.difficulty_preference] || sp.difficulty_preference)}</span></div>` : ''}
                ${sp.notes ? `<div class="archive-profile-item"><span class="archive-profile-label">特点备注</span><span class="archive-profile-value">${escapeHtml(sp.notes)}</span></div>` : ''}
            </div>
        </div>`;
    } else {
        profileHtml = `<div class="archive-profile-card" style="text-align:center;padding:16px">
            <div class="memory-card-title" style="margin-bottom:8px">冒险者档案 · 学生特点</div>
            <div style="font-size:11px;color:var(--text-muted)">AI 尚未记录学生特点，继续对话后将自动积累</div>
        </div>`;
    }

    // Quiz analysis card (strengths / weaknesses)
    let qaHtml = '';
    const strengths = qa.strengths || [];
    const weaknesses = qa.weaknesses || [];
    if (strengths.length > 0 || weaknesses.length > 0) {
        qaHtml = `<div class="archive-profile-card">
            <div class="memory-card-title" style="margin-bottom:10px">学习分析</div>
            <div style="display:flex;gap:16px;flex-wrap:wrap">
                ${strengths.length > 0 ? `<div style="flex:1;min-width:140px">
                    <div style="font-size:11px;color:var(--text-gold);font-weight:600;margin-bottom:6px">✦ 擅长领域</div>
                    <div style="display:flex;flex-wrap:wrap;gap:4px">${strengths.map(s => `<span class="tag-strong">${escapeHtml(s)}</span>`).join('')}</div>
                </div>` : ''}
                ${weaknesses.length > 0 ? `<div style="flex:1;min-width:140px">
                    <div style="font-size:11px;color:var(--error);font-weight:600;margin-bottom:6px">◇ 薄弱环节</div>
                    <div style="display:flex;flex-wrap:wrap;gap:4px">${weaknesses.map(w => `<span class="tag-weak">${escapeHtml(w)}</span>`).join('')}</div>
                </div>` : ''}
            </div>
        </div>`;
    }

    // Live knowledge points from memory (not just archive snapshots)
    let kpTrendHtml = '';
    const liveKps = kps.filter(k => k.interaction_depth > 0).sort((a, b) => (b.mastery || 0) - (a.mastery || 0));
    if (liveKps.length > 0) {
        kpTrendHtml = '<div style="margin-top:4px"><div class="memory-card-title" style="margin-bottom:8px">知识点掌握度（实时）</div><div class="archive-kp-trend">' +
            liveKps.slice(0, 15).map(kp => {
                const m = kp.mastery || 0;
                const cls = m >= 80 ? 'good' : m >= 50 ? 'medium' : 'weak';
                return `<div class="archive-kp-trend-item"><span class="archive-kp-trend-name">${escapeHtml(kp.name)}</span><div class="archive-kp-trend-bar"><div class="archive-kp-trend-fill ${cls}" style="width:${m}%"></div></div><span class="archive-kp-trend-val" style="color:var(--${cls === 'good' ? 'gold-dark' : cls === 'medium' ? 'element-hydro' : 'error'})">${m}</span></div>`;
            }).join('') + '</div></div>';
    } else if (kpData.length > 0) {
        // Fallback to archive snapshots
        const latestByKp = {};
        kpData.forEach(r => { if (!latestByKp[r.kp_name]) latestByKp[r.kp_name] = r; });
        const kpEntries = Object.values(latestByKp).sort((a, b) => (b.mastery || 0) - (a.mastery || 0));
        kpTrendHtml = '<div style="margin-top:4px"><div class="memory-card-title" style="margin-bottom:8px">知识点掌握度（归档快照）</div><div class="archive-kp-trend">' +
            kpEntries.slice(0, 15).map(kp => {
                const m = kp.mastery || 0;
                const cls = m >= 80 ? 'good' : m >= 50 ? 'medium' : 'weak';
                return `<div class="archive-kp-trend-item"><span class="archive-kp-trend-name">${escapeHtml(kp.kp_name)}</span><div class="archive-kp-trend-bar"><div class="archive-kp-trend-fill ${cls}" style="width:${m}%"></div></div><span class="archive-kp-trend-val" style="color:var(--${cls === 'good' ? 'gold-dark' : cls === 'medium' ? 'element-hydro' : 'error'})">${m}</span></div>`;
            }).join('') + '</div></div>';
    }

    // Archive stats section (only show if there's substantial archived data)
    const hasArchive = (s.scores_count || 0) + (s.reviews_count || 0) + (s.questions_count || 0) > 0;
    let archiveHtml = '';
    if (hasArchive) {
        archiveHtml = `
        <div style="margin-top:8px">
            <div class="memory-card-title" style="margin-bottom:8px">归档数据</div>
            <div class="archive-stats-grid">
                <div class="archive-stat-card">
                    <div class="archive-stat-value">${s.scores_count || 0}</div>
                    <div class="archive-stat-label">成绩记录</div>
                </div>
                <div class="archive-stat-card">
                    <div class="archive-stat-value">${s.reviews_count || 0}</div>
                    <div class="archive-stat-label">复习记录</div>
                </div>
                <div class="archive-stat-card">
                    <div class="archive-stat-value">${s.questions_count || 0}</div>
                    <div class="archive-stat-label">错题归档</div>
                </div>
                <div class="archive-stat-card">
                    <div class="archive-stat-value">${s.memory_snapshots_count || 0}</div>
                    <div class="archive-stat-label">记忆快照</div>
                </div>
            </div>
            <div class="archive-date-range">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                <span>数据范围：${fmt(s.earliest_date)} — ${fmt(s.latest_date)}</span>
                <span style="margin-left:auto;font-size:10px;color:var(--text-muted)">KP 快照 ${s.kp_snapshots_count || 0} 条</span>
            </div>
        </div>`;
    }

    el.innerHTML = `
        <div class="archive-stats-grid">
            <div class="archive-stat-card">
                <div class="archive-stat-value">${activeKps.length}</div>
                <div class="archive-stat-label">已学知识点</div>
            </div>
            <div class="archive-stat-card">
                <div class="archive-stat-value">${totalPractice}</div>
                <div class="archive-stat-label">练习题数</div>
            </div>
            <div class="archive-stat-card">
                <div class="archive-stat-value">${qbWrong}${archivedQuestions > 0 ? `<span style="font-size:10px;color:var(--text-muted)">+${archivedQuestions}</span>` : ''}</div>
                <div class="archive-stat-label">错题记录</div>
            </div>
            <div class="archive-stat-card">
                <div class="archive-stat-value">${totalPractice > 0 ? practiceAccuracy + '%' : '—'}</div>
                <div class="archive-stat-label">练习正确率</div>
            </div>
        </div>
        <div class="archive-date-range">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            <span>学习阶段：${escapeHtml(lp.current_phase || '—')}</span>
            <span style="margin-left:auto;font-size:10px;color:var(--text-muted)">待复习 ${reviewSchedule.length} 个知识点</span>
        </div>
        ${profileHtml}
        ${qaHtml}
        ${kpTrendHtml}
        ${archiveHtml}
    `;
}

async function renderArchiveScores(el) {
    const cid = state.currentCourseId;
    let filterKp = '';
    const render = async () => {
        const res = await apiGet(`/api/archive/${cid}/scores?kp=${encodeURIComponent(filterKp)}&limit=200`);
        const data = res.data || [];
        if (data.length === 0) {
            el.querySelector('.archive-table-wrap').innerHTML = '<div class="archive-empty"><p>暂无成绩记录</p></div>';
            return;
        }
        el.querySelector('.archive-table-wrap').innerHTML = `<table class="archive-table"><thead><tr><th>知识点</th><th>分数</th><th>来源</th><th>时间</th></tr></thead><tbody>${data.map(r => {
            const s = r.score || 0;
            const cls = s >= 80 ? 'good' : s >= 50 ? 'medium' : 'weak';
            return `<tr><td class="kp-cell">${escapeHtml(r.kp_name || '')}</td><td class="score-cell ${cls}">${s}</td><td>${escapeHtml(r.source || '')}</td><td class="time-cell">${fmtTime(r.archived_at)}</td></tr>`;
        }).join('')}</tbody></table>`;
    };

    el.innerHTML = `<div class="archive-filter-bar"><input class="archive-filter-input" placeholder="按知识点筛选..." id="archiveScoreFilter"></div><div class="archive-table-wrap"></div>`;
    await render();
    el.querySelector('#archiveScoreFilter').addEventListener('input', debounce(e => { filterKp = e.target.value.trim(); render(); }, 400));
}

async function renderArchiveReviews(el) {
    const cid = state.currentCourseId;
    let filterKp = '';
    const render = async () => {
        const res = await apiGet(`/api/archive/${cid}/reviews?kp=${encodeURIComponent(filterKp)}&limit=200`);
        const data = res.data || [];
        if (data.length === 0) {
            el.querySelector('.archive-table-wrap').innerHTML = '<div class="archive-empty"><p>暂无复习记录</p></div>';
            return;
        }
        el.querySelector('.archive-table-wrap').innerHTML = `<table class="archive-table"><thead><tr><th>知识点</th><th>质量</th><th>掌握度</th><th>下次复习</th><th>时间</th></tr></thead><tbody>${data.map(r => {
            const q = r.quality ?? '';
            const m = r.mastery ?? '';
            return `<tr><td class="kp-cell">${escapeHtml(r.kp_name || '')}</td><td>${q}</td><td>${m}</td><td class="time-cell">${fmtTime(r.next_review)}</td><td class="time-cell">${fmtTime(r.archived_at)}</td></tr>`;
        }).join('')}</tbody></table>`;
    };

    el.innerHTML = `<div class="archive-filter-bar"><input class="archive-filter-input" placeholder="按知识点筛选..." id="archiveReviewFilter"></div><div class="archive-table-wrap"></div>`;
    await render();
    el.querySelector('#archiveReviewFilter').addEventListener('input', debounce(e => { filterKp = e.target.value.trim(); render(); }, 400));
}

async function renderArchiveQuestions(el) {
    const cid = state.currentCourseId;
    let filterKp = '';
    const render = async () => {
        const res = await apiGet(`/api/archive/${cid}/questions?kp=${encodeURIComponent(filterKp)}&limit=200`);
        const data = res.data || [];
        if (data.length === 0) {
            el.querySelector('.archive-table-wrap').innerHTML = '<div class="archive-empty"><p>暂无错题归档</p></div>';
            return;
        }
        el.querySelector('.archive-table-wrap').innerHTML = `<table class="archive-table"><thead><tr><th>知识点</th><th>题目</th><th>正确</th><th>时间</th></tr></thead><tbody>${data.map(r => {
            const correct = r.is_correct ? '<span style="color:var(--success)">✓</span>' : '<span style="color:var(--error)">✗</span>';
            return `<tr><td class="kp-cell">${escapeHtml(r.kp_name || '')}</td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(r.question || '')}">${escapeHtml(r.question || '').slice(0, 60)}</td><td>${correct}</td><td class="time-cell">${fmtTime(r.archived_at)}</td></tr>`;
        }).join('')}</tbody></table>`;
    };

    el.innerHTML = `<div class="archive-filter-bar"><input class="archive-filter-input" placeholder="按知识点筛选..." id="archiveQuestionFilter"></div><div class="archive-table-wrap"></div>`;
    await render();
    el.querySelector('#archiveQuestionFilter').addEventListener('input', debounce(e => { filterKp = e.target.value.trim(); render(); }, 400));
}

async function renderArchiveSnapshots(el) {
    const cid = state.currentCourseId;
    const res = await apiGet(`/api/archive/${cid}/memory-snapshots?limit=50`);
    const data = res.data || [];
    if (data.length === 0) {
        el.innerHTML = '<div class="archive-empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg><p>暂无记忆快照</p></div>';
        return;
    }

    const reasonLabels = { truncation: '数据归档', periodic: '定期快照', manual: '手动快照', init: '初始化' };
    el.innerHTML = '<div class="archive-snapshot-list">' + data.map(s => `
        <div class="archive-snapshot-item" data-id="${s.id}" onclick="viewSnapshot(${s.id})">
            <div class="archive-snapshot-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            </div>
            <div class="archive-snapshot-info">
                <div class="archive-snapshot-title">快照 #${s.id}</div>
                <div class="archive-snapshot-meta">${fmtTime(s.created_at)}</div>
            </div>
            <span class="archive-snapshot-reason">${reasonLabels[s.reason] || s.reason || '归档'}</span>
        </div>
    `).join('') + '</div>';
}

window.viewSnapshot = async function(snapshotId) {
    const content = document.getElementById('archiveContent');
    content.innerHTML = '<div class="archive-loading"><span style="display:flex;gap:4px;align-items:center"><span style="width:6px;height:6px;border-radius:50%;background:var(--gold);animation:typing 1.2s infinite"></span><span style="width:6px;height:6px;border-radius:50%;background:var(--gold);animation:typing 1.2s infinite 0.2s"></span><span style="width:6px;height:6px;border-radius:50%;background:var(--gold);animation:typing 1.2s infinite 0.4s"></span></span></div>';
    try {
        const res = await apiGet(`/api/archive/memory-snapshot/${snapshotId}`);
        const d = res.data;
        if (!d) throw new Error('快照不存在');
        const json = typeof d.snapshot_data === 'string' ? d.snapshot_data : JSON.stringify(d.snapshot_data, null, 2);
        content.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
                <button onclick="loadArchiveTab('snapshots')" style="background:none;border:1px solid var(--card-border);border-radius:6px;padding:4px 10px;font-size:11px;color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;gap:4px">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
                    返回列表
                </button>
                <span style="font-size:13px;font-weight:600;color:var(--gold-dark)">快照 #${d.id}</span>
                <span style="font-size:10px;color:var(--text-muted);margin-left:auto">${fmtTime(d.created_at)}</span>
            </div>
            <pre style="background:rgba(60,50,36,0.03);border:1px solid var(--glass-border);border-radius:8px;padding:14px;font-size:11px;font-family:'Consolas','Fira Code',monospace;color:var(--text-primary);overflow:auto;max-height:40vh;line-height:1.6;white-space:pre-wrap;word-break:break-word">${escapeHtml(json)}</pre>
        `;
    } catch (e) {
        content.innerHTML = `<div class="archive-empty"><p>加载快照失败: ${escapeHtml(e.message)}</p></div>`;
    }
};

window.exportArchive = async function() {
    if (!state.currentCourseId) return;
    try {
        const res = await apiGet(`/api/archive/${state.currentCourseId}/export`);
        if (res.success) {
            const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            const course = state.courses.find(c => c.id === state.currentCourseId);
            a.href = url;
            a.download = `archive_${course?.name || state.currentCourseId}_${new Date().toISOString().slice(0,10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
            showToast('档案已导出', 'success');
        }
    } catch (e) {
        showToast('导出失败: ' + e.message, 'error');
    }
};

/* ===== 导入档案 ===== */
let _pendingImportData = null;

window.triggerImportArchive = function() {
    const input = document.getElementById('importArchiveInput');
    input.value = '';
    input.click();
};

window.handleImportFile = function(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (!file.name.endsWith('.json')) {
        showToast('请选择 .json 格式的档案文件', 'error');
        return;
    }
    if (file.size > 50 * 1024 * 1024) {
        showToast('文件过大（最大 50MB）', 'error');
        return;
    }
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const data = JSON.parse(e.target.result);
            if (!data.course_id && !data.scores && !data.questions) {
                showToast('无效的档案文件格式', 'error');
                return;
            }
            _pendingImportData = data;
            _showImportConfirmDialog(data, file.name);
        } catch (err) {
            showToast('JSON 解析失败: ' + err.message, 'error');
        }
    };
    reader.readAsText(file);
};

function _showImportConfirmDialog(data, fileName) {
    const scoreCount = (data.scores || []).length;
    const reviewCount = (data.reviews || []).length;
    const questionCount = (data.questions || []).length;
    const kpCount = (data.kp_snapshots || []).length;
    const memCount = (data.memory_snapshots || []).length;
    const msgCount = (data.messages || []).length;
    const hasCurrentMem = !!data.current_memory;
    const exportedAt = data.exported_at ? new Date(data.exported_at).toLocaleDateString('zh-CN') : '未知';

    // 从多个来源提取课程信息
    let sourceCourse = '';
    let sourceElement = 'geo';
    // 优先: course_meta
    const meta = data.course_meta || {};
    if (meta.name) sourceCourse = meta.name;
    if (meta.element) sourceElement = meta.element;
    // 其次: current_memory
    if (!sourceCourse) {
        const ci = (data.current_memory || {}).course_info || {};
        if (ci.name) sourceCourse = ci.name;
        if (ci.element) sourceElement = ci.element;
    }
    // 再次: memory_snapshots
    if (!sourceCourse) {
        const snapshots = data.memory_snapshots || [];
        if (snapshots.length > 0) {
            const lastMem = snapshots[snapshots.length - 1].memory_json || {};
            const ci = lastMem.course_info || {};
            if (ci.name) sourceCourse = ci.name;
            if (ci.element) sourceElement = ci.element;
        }
    }
    if (!sourceCourse) sourceCourse = data.course_id || '未知';

    const hasCurrent = !!state.currentCourseId;
    const currentCourse = hasCurrent ? state.courses.find(c => c.id === state.currentCourseId) : null;
    const currentName = currentCourse ? currentCourse.name : '';

    // 有无实质数据
    const totalData = scoreCount + reviewCount + questionCount + kpCount + memCount + msgCount;
    const hasMemory = hasCurrentMem || memCount > 0;

    const elements = [
        {id:'pyro',name:'火',color:'var(--element-pyro)'}, {id:'hydro',name:'水',color:'var(--element-hydro)'},
        {id:'electro',name:'雷',color:'var(--element-electro)'}, {id:'dendro',name:'草',color:'var(--element-dendro)'},
        {id:'cryo',name:'冰',color:'var(--element-cryo)'}, {id:'anemo',name:'风',color:'var(--element-anemo)'},
        {id:'geo',name:'岩',color:'var(--element-geo)'}
    ];
    const elementPickerHtml = elements.map(el =>
        `<span class="import-element-dot${el.id === sourceElement ? ' active' : ''}" data-element="${el.id}" title="${el.name}" style="width:18px;height:18px;border-radius:50%;background:${el.color};display:inline-block;cursor:pointer;border:2px solid ${el.id === sourceElement ? 'var(--gold)' : 'transparent'};box-shadow:${el.id === sourceElement ? '0 0 6px ' + el.color : 'none'}" onclick="_selectImportElement('${el.id}')"></span>`
    ).join('');

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    overlay.id = 'importConfirmOverlay';
    overlay.innerHTML = `
        <div class="modal-content" style="max-width:480px;animation:fadeInUp 0.3s ease">
            <div class="modal-header">
                <span class="modal-title" style="font-family:'Cinzel','Inter',serif">Import Archive</span>
                <button class="modal-close" onclick="document.getElementById('importConfirmOverlay').remove()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
            </div>
            <div style="padding:16px 20px">
                <div style="font-size:11px;color:var(--text-muted);margin-bottom:12px">
                    文件: ${escapeHtml(fileName)} | 来源: ${escapeHtml(sourceCourse)} | 导出于: ${exportedAt}
                </div>
                <div class="memory-card" style="margin-bottom:14px;padding:12px">
                    <div class="memory-card-title" style="margin-bottom:8px">档案内容概览</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;color:var(--text-secondary)">
                        <span>成绩记录: <strong style="color:var(--text-primary)">${scoreCount}</strong> 条</span>
                        <span>复习记录: <strong style="color:var(--text-primary)">${reviewCount}</strong> 条</span>
                        <span>错题归档: <strong style="color:var(--text-primary)">${questionCount}</strong> 条</span>
                        <span>知识点快照: <strong style="color:var(--text-primary)">${kpCount}</strong> 条</span>
                        <span>记忆快照: <strong style="color:var(--text-primary)">${memCount}</strong> 条</span>
                        <span>聊天消息: <strong style="color:var(--text-primary)">${msgCount}</strong> 条</span>
                    </div>
                    ${hasMemory ? '<div style="margin-top:6px;font-size:10px;color:var(--success)">&#9670; 包含完整学习记忆，将恢复知识点、教学计划等</div>' : ''}
                </div>

                <div style="font-size:11px;color:var(--text-secondary);margin-bottom:10px">
                    ◆ 创建新课程的设置:
                </div>
                <div style="margin-bottom:12px">
                    <label style="font-size:10px;color:var(--text-muted);display:block;margin-bottom:4px">课程名称</label>
                    <input type="text" id="importCourseName" value="${escapeHtml(sourceCourse + ' (导入)')}" placeholder="输入课程名称"
                           style="width:100%;box-sizing:border-box;padding:8px 12px;border:1px solid var(--card-border);border-radius:8px;background:var(--card-bg);color:var(--text-primary);font-size:12px;outline:none"
                           onfocus="this.style.borderColor='var(--gold)';this.style.boxShadow='0 0 8px rgba(212,168,83,0.15)'"
                           onblur="this.style.borderColor='var(--card-border)';this.style.boxShadow='none'">
                </div>
                <div style="margin-bottom:14px">
                    <label style="font-size:10px;color:var(--text-muted);display:block;margin-bottom:6px">元素属性</label>
                    <div id="importElementPicker" style="display:flex;gap:6px;align-items:center">
                        ${elementPickerHtml}
                    </div>
                </div>

                <div class="diamond-sep" style="margin-bottom:14px"><span style="flex:1;height:1px;background:var(--card-border)"></span><span style="font-size:9px;color:var(--text-muted);padding:0 8px">导入方式</span><span style="flex:1;height:1px;background:var(--card-border)"></span></div>

                <div style="display:flex;flex-direction:column;gap:8px">
                    ${hasCurrent ? `
                    <button class="archive-action-btn" onclick="_executeImport(false)" style="width:100%;justify-content:center;padding:10px 16px">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
                        追加到当前课程「${escapeHtml(currentName)}」
                    </button>` : ''}
                    <button class="archive-action-btn primary" onclick="_executeImport(true)" style="width:100%;justify-content:center;padding:10px 16px">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
                        创建新课程并导入
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
}

let _importSelectedElement = '';

window._selectImportElement = function(elementId) {
    _importSelectedElement = elementId;
    const picker = document.getElementById('importElementPicker');
    if (!picker) return;
    picker.querySelectorAll('.import-element-dot').forEach(dot => {
        const isActive = dot.dataset.element === elementId;
        dot.classList.toggle('active', isActive);
        dot.style.border = isActive ? '2px solid var(--gold)' : '2px solid transparent';
        dot.style.boxShadow = isActive ? '0 0 6px currentColor' : 'none';
    });
};

window._executeImport = async function(createNew) {
    if (!_pendingImportData) return;
    const overlay = document.getElementById('importConfirmOverlay');
    if (overlay) {
        const btns = overlay.querySelectorAll('button:not(.modal-close)');
        btns.forEach(b => { b.disabled = true; b.style.opacity = '0.6'; });
        const content = overlay.querySelector('.modal-content > div:last-child');
        if (content) {
            const loading = document.createElement('div');
            loading.style.cssText = 'text-align:center;padding:8px;font-size:11px;color:var(--text-gold)';
            loading.textContent = '正在导入...';
            content.appendChild(loading);
        }
    }

    try {
        const body = {
            data: _pendingImportData,
            create_new: createNew,
        };
        if (createNew) {
            const nameInput = document.getElementById('importCourseName');
            if (nameInput && nameInput.value.trim()) {
                body.course_name = nameInput.value.trim();
            }
            if (_importSelectedElement) {
                body.course_element = _importSelectedElement;
            }
        }
        if (!createNew && state.currentCourseId) {
            body.target_course_id = state.currentCourseId;
        }
        const res = await apiPost('/api/archive/import', body);
        if (res.success) {
            showToast(res.message || '导入完成', 'success');
            if (overlay) overlay.remove();
            _pendingImportData = null;

            // 如果创建了新课程，刷新课程列表
            if (createNew && res.course_id) {
                await loadCourses();
                switchCourse(res.course_id);
            }
            // 刷新档案视图
            if (_archiveTab) {
                loadArchiveTab(_archiveTab);
            }
        } else {
            showToast('导入失败: ' + (res.error || '未知错误'), 'error');
            if (overlay) overlay.remove();
        }
    } catch (e) {
        showToast('导入失败: ' + e.message, 'error');
        if (overlay) overlay.remove();
    }
};

window.createManualSnapshot = async function() {
    if (!state.currentCourseId) return;
    try {
        const res = await apiPost(`/api/archive/${state.currentCourseId}/snapshot`, {});
        if (res.success) {
            showToast('快照已创建', 'success');
            if (_archiveTab === 'overview' || _archiveTab === 'snapshots') {
                loadArchiveTab(_archiveTab);
            }
        }
    } catch (e) {
        showToast('创建快照失败: ' + e.message, 'error');
    }
};

function fmtTime(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleDateString('zh-CN', { month:'short', day:'numeric' }) + ' ' + d.toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' });
}

function debounce(fn, ms) {
    let t;
    return function(...args) { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); };
}


