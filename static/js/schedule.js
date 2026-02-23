/* ============================================
   EduChat - Schedule Page Logic
   Genshin Impact Light Theme (Teyvat Parchment)
   ============================================ */

const ELEMENT_COLORS = {
    pyro: '#E2604A', hydro: '#3A9FD4', electro: '#9B5FD4',
    dendro: '#5EA83F', cryo: '#52B5C4', anemo: '#53B89A', geo: '#C49934'
};
const TYPE_COLORS = { study: '#3A9FD4', review: '#9B5FD4', homework: '#C49934', exam: '#E2604A' };
const TYPE_ICONS = { study: '📖', review: '🔄', homework: '📝', exam: '🌀' };
const TYPE_CLASSES = { study: 'study-event', review: 'review-event', homework: 'homework-event', exam: 'exam-event' };
const DAYS = ['日', '一', '二', '三', '四', '五', '六'];

const schedState = {
    view: 'week',
    currentDate: new Date(),
    events: [],
    courses: [],
    filterType: 'all',
    filterCourse: 'all',
    editingEvent: null,
};

// ============ API ============
async function apiGet(url) { return (await fetch(url)).json(); }
async function apiPost(url, data) {
    return (await fetch(url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) })).json();
}
async function apiPut(url, data) {
    return (await fetch(url, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) })).json();
}
async function apiDelete(url) { return (await fetch(url, { method: 'DELETE' })).json(); }

function showToast(msg) {
    let toast = document.getElementById('schedToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'schedToast';
        toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--gold-gradient-btn);color:#fff;padding:10px 24px;border-radius:20px;font-size:13px;font-weight:500;z-index:9999;opacity:0;transition:all .3s ease;box-shadow:var(--shadow-gold);pointer-events:none;';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(-50%) translateY(0)';
    });
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-50%) translateY(20px)';
    }, 2500);
}

// ============ Data Loading ============
async function loadData() {
    const [schedRes, courseRes] = await Promise.all([
        apiGet('/api/schedule'),
        apiGet('/api/courses'),
    ]);
    if (schedRes.success) schedState.events = schedRes.data;
    if (courseRes.success) schedState.courses = courseRes.data;
    renderFilters();
    renderCalendar();
}

// ============ State Persistence ============
async function restoreScheduleState() {
    try {
        const res = await apiGet('/api/state');
        if (res.success && res.data) {
            if (res.data.schedule_view) schedState.view = res.data.schedule_view;
            if (res.data.schedule_date) schedState.currentDate = new Date(res.data.schedule_date);
        }
    } catch (_) {}
}

function saveScheduleState() {
    fetch('/api/state', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
            schedule_view: schedState.view,
            schedule_date: schedState.currentDate.toISOString(),
        }),
    }).catch(() => {});
}

// ============ Modal Helpers ============
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('active');
}
function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
}

// ============ Rendering ============
function renderFilters() {
    const courseFilters = document.getElementById('courseFilters');
    courseFilters.innerHTML = `<button class="filter-chip active" data-course="all">全部课程</button>` +
        schedState.courses.map(c => `
            <button class="filter-chip" data-course="${c.id}">
                <span class="chip-dot" style="background:${ELEMENT_COLORS[c.element] || '#C49934'}"></span>
                ${c.name}
            </button>
        `).join('');

    courseFilters.querySelectorAll('.filter-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            courseFilters.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            schedState.filterCourse = chip.dataset.course;
            renderCalendar();
        });
    });

    // Course select in event modal
    const sel = document.getElementById('eventCourseSelect');
    if (sel) {
        sel.innerHTML = schedState.courses.map(c =>
            `<option value="${c.id}">${c.name}</option>`
        ).join('');
    }
}

function renderCalendar() {
    updateTitle();
    // Expand recurring events for the current view range
    const range = getViewDateRange();
    schedState._expandedEvents = expandRecurringEvents(range.start, range.end);
    if (schedState.view === 'week') renderWeekView();
    else renderMonthView();
}

function updateTitle() {
    const d = schedState.currentDate;
    const title = document.getElementById('calendarTitle');
    if (schedState.view === 'month') {
        title.textContent = `${d.getFullYear()}年${d.getMonth() + 1}月`;
    } else {
        const weekStart = getWeekStart(d);
        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekEnd.getDate() + 6);
        title.textContent = `${weekStart.getMonth() + 1}月${weekStart.getDate()}日 - ${weekEnd.getMonth() + 1}月${weekEnd.getDate()}日`;
    }
}

function getWeekStart(date) {
    const d = new Date(date);
    const day = d.getDay();
    d.setDate(d.getDate() - day);
    d.setHours(0, 0, 0, 0);
    return d;
}

function renderWeekView() {
    const grid = document.getElementById('calendarGrid');
    const weekStart = getWeekStart(schedState.currentDate);
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // Week header
    let headerHtml = '<div class="week-header">';
    for (let i = 0; i < 7; i++) {
        const d = new Date(weekStart);
        d.setDate(d.getDate() + i);
        const isToday = d.getTime() === today.getTime();
        headerHtml += `<div class="week-day-header ${isToday ? 'today' : ''}">
            周${DAYS[i]}
            <span class="week-date ${isToday ? 'today-date' : ''}">${d.getDate()}</span>
        </div>`;
    }
    headerHtml += '</div>';

    // Week body
    let bodyHtml = '<div class="week-body">';
    for (let i = 0; i < 7; i++) {
        const d = new Date(weekStart);
        d.setDate(d.getDate() + i);
        const dateStr = formatDateKey(d);
        const isToday = d.getTime() === today.getTime();
        const dayEvents = getFilteredEvents(dateStr);

        bodyHtml += `<div class="week-day-col ${isToday ? 'today-col' : ''}">
            ${dayEvents.map(e => renderEventCard(e)).join('')}
        </div>`;
    }
    bodyHtml += '</div>';

    grid.innerHTML = headerHtml + bodyHtml;
    bindEventClicks();
}

function renderMonthView() {
    const grid = document.getElementById('calendarGrid');
    const year = schedState.currentDate.getFullYear();
    const month = schedState.currentDate.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startDay = firstDay.getDay();
    const totalDays = lastDay.getDate();
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    let html = '<div class="month-header">';
    for (let i = 0; i < 7; i++) {
        html += `<div class="month-header-cell">周${DAYS[i]}</div>`;
    }
    html += '</div><div class="month-body">';

    const totalCells = Math.ceil((startDay + totalDays) / 7) * 7;
    for (let i = 0; i < totalCells; i++) {
        const dayNum = i - startDay + 1;
        const d = new Date(year, month, dayNum);
        const isCurrentMonth = dayNum >= 1 && dayNum <= totalDays;
        const isToday = d.getTime() === today.getTime();
        const dateStr = formatDateKey(d);
        const dayEvents = isCurrentMonth ? getFilteredEvents(dateStr) : [];

        html += `<div class="month-cell ${isToday ? 'today' : ''} ${!isCurrentMonth ? 'other-month' : ''}">
            <div class="cell-date">${d.getDate()}</div>
            ${dayEvents.slice(0, 3).map(e => renderEventCard(e)).join('')}
            ${dayEvents.length > 3 ? `<div style="font-size:10px;color:var(--text-muted);padding:0 4px">+${dayEvents.length - 3} 更多</div>` : ''}
        </div>`;
    }
    html += '</div>';
    grid.innerHTML = html;
    bindEventClicks();
}

function renderEventCard(event) {
    const type = event.type || 'study';
    const icon = TYPE_ICONS[type] || '📖';
    const typeClass = TYPE_CLASSES[type] || 'study-event';
    const time = event.datetime ? new Date(event.datetime).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
    const isCompleted = !!event.completed;
    const completedClass = isCompleted ? ' event-completed' : '';
    const completedIcon = isCompleted ? '✅' : icon;
    const repeatMap = { daily: '日', weekdays: '工作日', weekly: '周', biweekly: '双周', monthly: '月' };
    const repeatTag = event.repeat && repeatMap[event.repeat] ? `<span class="repeat-tag" title="周期: ${repeatMap[event.repeat]}">🔁</span>` : '';
    const virtualClass = event._virtual ? ' virtual-event' : '';
    const eventId = event._virtual ? event._originalId : event.id;
    const isReview = event.type === 'review' && !isCompleted;
    const showDelete = !event._virtual && !isReview;
    const showPostpone = !event._virtual && isReview;
    const deleteBtn = showDelete ? `<button class="cal-event-delete" data-del-id="${event.id}" data-del-course="${event.course_id}" title="删除">×</button>` : '';
    const postponeBtn = showPostpone ? `<button class="cal-event-postpone" data-del-id="${event.id}" data-del-course="${event.course_id}" title="顺延到下一个记忆点">⏭</button>` : '';
    return `<div class="cal-event ${typeClass}${completedClass}${virtualClass}" data-event-id="${eventId}" data-course-id="${event.course_id}" ${isCompleted ? 'data-completed="true"' : ''} ${event._virtual ? 'data-virtual="true"' : ''}>
        ${deleteBtn}${postponeBtn}
        <div class="cal-event-icon">${completedIcon}</div>
        <div class="cal-event-info">
            <span class="cal-event-title">${event.title || ''}${repeatTag}${isCompleted ? ' <span class="completed-tag">已完成</span>' : ''}</span>
            ${time ? `<span class="cal-event-time">${time}</span>` : ''}
        </div>
    </div>`;
}

// Expand recurring events into virtual instances within a date range
function expandRecurringEvents(startDate, endDate) {
    const expanded = [];
    const startStr = formatDateKey(startDate);
    const endStr = formatDateKey(endDate);

    for (const e of schedState.events) {
        const eDate = (e.datetime || e.date || '').slice(0, 10);
        // Always include the original event if it falls in range
        if (eDate >= startStr && eDate <= endStr) {
            expanded.push(e);
        }

        // Expand recurring events
        if (!e.repeat || e.repeat === 'none') continue;

        const totalCount = e.repeat_count || REPEAT_DEFAULTS[e.repeat]?.default || 4;
        const maxCount = Math.max(totalCount - 1, 0); // subtract 1 for the original event
        const baseDate = new Date(eDate + 'T00:00:00');
        const baseTime = e.datetime ? e.datetime.slice(10) : '';
        let cursor = new Date(baseDate);
        let generated = 0;

        for (let safety = 0; safety < 500 && generated < maxCount; safety++) {
            // Advance cursor
            if (e.repeat === 'weekdays') {
                cursor.setDate(cursor.getDate() + 1);
                // Skip weekends (0=Sun, 6=Sat)
                while (cursor.getDay() === 0 || cursor.getDay() === 6) {
                    cursor.setDate(cursor.getDate() + 1);
                }
            } else if (e.repeat === 'daily') {
                cursor.setDate(cursor.getDate() + 1);
            } else if (e.repeat === 'weekly') {
                cursor.setDate(cursor.getDate() + 7);
            } else if (e.repeat === 'biweekly') {
                cursor.setDate(cursor.getDate() + 14);
            } else if (e.repeat === 'monthly') {
                cursor.setMonth(cursor.getMonth() + 1);
            } else {
                break;
            }

            const cursorStr = formatDateKey(cursor);
            if (cursorStr === eDate) continue;

            generated++;
            if (cursorStr > endStr) continue; // count but don't render
            if (cursorStr < startStr) continue;

            expanded.push({
                ...e,
                _virtual: true,
                _originalId: e.id,
                _originalDate: eDate,
                date: cursorStr,
                datetime: baseTime ? cursorStr + baseTime : '',
            });
        }
    }
    return expanded;
}

// Get the date range for the current calendar view
function getViewDateRange() {
    if (schedState.view === 'week') {
        const start = getWeekStart(schedState.currentDate);
        const end = new Date(start);
        end.setDate(end.getDate() + 6);
        return { start, end };
    } else {
        const year = schedState.currentDate.getFullYear();
        const month = schedState.currentDate.getMonth();
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        // Include surrounding days shown in the grid
        const start = new Date(firstDay);
        start.setDate(start.getDate() - firstDay.getDay());
        const totalCells = Math.ceil((firstDay.getDay() + lastDay.getDate()) / 7) * 7;
        const end = new Date(start);
        end.setDate(end.getDate() + totalCells - 1);
        return { start, end };
    }
}

function getFilteredEvents(dateStr) {
    // Use pre-expanded events (set during renderCalendar)
    const events = schedState._expandedEvents || schedState.events;
    return events.filter(e => {
        const eDate = (e.datetime || e.date || '').slice(0, 10);
        if (eDate !== dateStr) return false;
        if (schedState.filterType !== 'all' && e.type !== schedState.filterType) return false;
        if (schedState.filterCourse !== 'all' && e.course_id !== schedState.filterCourse) return false;
        return true;
    });
}

function formatDateKey(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function bindEventClicks() {
    // Bind delete buttons (for non-review events)
    document.querySelectorAll('.cal-event-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            const eventId = btn.dataset.delId;
            const courseId = btn.dataset.delCourse;
            if (!eventId || !courseId) return;
            const event = schedState.events.find(ev => ev.id === eventId);
            const title = event ? event.title : '此日程';
            const isRepeat = event && event.repeat && event.repeat !== 'none';
            showDeleteConfirm(eventId, courseId, title, isRepeat);
        });
    });
    // Bind postpone buttons (for review events)
    document.querySelectorAll('.cal-event-postpone').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            const eventId = btn.dataset.delId;
            const courseId = btn.dataset.delCourse;
            if (!eventId || !courseId) return;
            const event = schedState.events.find(ev => ev.id === eventId);
            const title = event ? event.title : '此复习';
            showPostponeConfirm(eventId, courseId, title);
        });
    });
    // Bind event card clicks
    document.querySelectorAll('.cal-event').forEach(el => {
        if (el.dataset.completed === 'true') {
            el.style.cursor = 'default';
            return;
        }
        el.addEventListener('click', () => {
            const eventId = el.dataset.eventId;
            const event = schedState.events.find(e => e.id === eventId);
            if (!event) return;
            if (event.type === 'review') {
                showReviewConfirm(event);
            } else if (event.type === 'study') {
                showStudyConfirm(event);
            } else if (event.type === 'homework' || event.type === 'exam') {
                showHwExamConfirm(event);
            } else {
                openEditEventModal(event);
            }
        });
    });
}

function showDeleteConfirm(eventId, courseId, title, isRepeat) {
    const modal = document.getElementById('deleteConfirmModal');
    const titleEl = document.getElementById('deleteConfirmTitle');
    const descEl = document.getElementById('deleteConfirmDesc');

    titleEl.textContent = `确定删除「${title}」？`;
    descEl.textContent = isRepeat ? '这是一个周期性日程，删除后所有未来重复也会一并移除' : '删除后不可恢复';

    modal.classList.add('active');

    const confirmBtn = document.getElementById('deleteConfirmBtn');
    const cancelBtn = document.getElementById('deleteCancelBtn');
    const closeBtn = document.getElementById('closeDeleteConfirmBtn');

    const newConfirmBtn = confirmBtn.cloneNode(true);
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newCloseBtn = closeBtn.cloneNode(true);
    confirmBtn.replaceWith(newConfirmBtn);
    cancelBtn.replaceWith(newCancelBtn);
    closeBtn.replaceWith(newCloseBtn);

    const closeModalFn = () => modal.classList.remove('active');

    newCancelBtn.addEventListener('click', closeModalFn);
    newCloseBtn.addEventListener('click', closeModalFn);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModalFn(); }, { once: true });

    newConfirmBtn.addEventListener('click', async () => {
        closeModalFn();
        await apiDelete(`/api/schedule/${courseId}/${eventId}`);
        await loadData();
    });
}

function showPostponeConfirm(eventId, courseId, title) {
    const modal = document.getElementById('deleteConfirmModal');
    const titleEl = document.getElementById('deleteConfirmTitle');
    const descEl = document.getElementById('deleteConfirmDesc');

    titleEl.textContent = `顺延「${title}」？`;
    descEl.textContent = '将根据遗忘曲线自动推算到下一个最佳记忆点，届时会再次提醒复习';

    modal.classList.add('active');

    const confirmBtn = document.getElementById('deleteConfirmBtn');
    const cancelBtn = document.getElementById('deleteCancelBtn');
    const closeBtn = document.getElementById('closeDeleteConfirmBtn');

    const newConfirmBtn = confirmBtn.cloneNode(true);
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newCloseBtn = closeBtn.cloneNode(true);
    confirmBtn.replaceWith(newConfirmBtn);
    cancelBtn.replaceWith(newCancelBtn);
    closeBtn.replaceWith(newCloseBtn);

    // 按钮文案改为"顺延"
    newConfirmBtn.textContent = '顺延';

    const closeModalFn = () => {
        modal.classList.remove('active');
        newConfirmBtn.textContent = '确认删除';
    };

    newCancelBtn.addEventListener('click', closeModalFn);
    newCloseBtn.addEventListener('click', closeModalFn);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModalFn(); }, { once: true });

    newConfirmBtn.addEventListener('click', async () => {
        closeModalFn();
        const res = await apiDelete(`/api/schedule/${courseId}/${eventId}`);
        if (res && res.postponed && res.data) {
            const newDate = new Date(res.data.next_review);
            const dateStr = newDate.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
            showToast(`已顺延到 ${dateStr}`);
        }
        await loadData();
    });
}

function showReviewConfirm(event) {
    const pointName = (event.title || '').replace(/^复习:\s*/, '');
    const modal = document.getElementById('reviewConfirmModal');
    const titleEl = document.getElementById('reviewConfirmTitle');
    const descEl = document.getElementById('reviewConfirmDesc');

    titleEl.textContent = `确认开始复习「${pointName}」？`;
    descEl.textContent = '将跳转到聊天页面并开始该知识点的复习对话';

    modal.classList.add('active');

    const startBtn = document.getElementById('reviewStartBtn');
    const cancelBtn = document.getElementById('reviewCancelBtn');
    const closeBtn = document.getElementById('closeReviewConfirmBtn');

    // 清除旧事件避免重复绑定
    const newStartBtn = startBtn.cloneNode(true);
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newCloseBtn = closeBtn.cloneNode(true);
    startBtn.replaceWith(newStartBtn);
    cancelBtn.replaceWith(newCancelBtn);
    closeBtn.replaceWith(newCloseBtn);

    const closeModal = () => modal.classList.remove('active');

    newCancelBtn.addEventListener('click', closeModal);
    newCloseBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); }, { once: true });

    newStartBtn.addEventListener('click', () => {
        closeModal();
        window.location.href = `/?course=${encodeURIComponent(event.course_id)}&review_point=${encodeURIComponent(pointName)}`;
    });
}

// ---------- Study Confirm ----------
function showStudyConfirm(event) {
    const modal = document.getElementById('studyConfirmModal');
    const titleEl = document.getElementById('studyConfirmTitle');
    const descEl = document.getElementById('studyConfirmDesc');
    const topicInput = document.getElementById('studyTopicInput');

    titleEl.textContent = `开始学习「${event.title || ''}」？`;
    descEl.textContent = event.description || '将跳转到聊天页面并启动学习对话';
    topicInput.value = '';

    modal.classList.add('active');
    setTimeout(() => topicInput.focus(), 100);

    const startBtn = document.getElementById('studyStartBtn');
    const cancelBtn = document.getElementById('studyCancelBtn');
    const closeBtn = document.getElementById('closeStudyConfirmBtn');

    const newStartBtn = startBtn.cloneNode(true);
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newCloseBtn = closeBtn.cloneNode(true);
    startBtn.replaceWith(newStartBtn);
    cancelBtn.replaceWith(newCancelBtn);
    closeBtn.replaceWith(newCloseBtn);

    const closeFn = () => modal.classList.remove('active');
    newCancelBtn.addEventListener('click', closeFn);
    newCloseBtn.addEventListener('click', closeFn);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeFn(); }, { once: true });

    newStartBtn.addEventListener('click', async () => {
        const topic = document.getElementById('studyTopicInput').value.trim();
        closeFn();
        // Mark event completed
        await apiPut(`/api/schedule/${event.course_id}/${event.id}`, { completed: true, completed_at: new Date().toISOString() });
        // Jump to chat with study action
        const params = new URLSearchParams({
            course: event.course_id,
            action: 'study',
            event_title: event.title || '',
        });
        if (topic) params.set('study_topic', topic);
        window.location.href = `/?${params.toString()}`;
    });
}

// ---------- Homework / Exam Confirm ----------
function showHwExamConfirm(event) {
    const isHomework = event.type === 'homework';
    const modal = document.getElementById('hwExamConfirmModal');
    const headerEl = document.getElementById('hwExamModalHeader');
    const iconEl = document.getElementById('hwExamIcon');
    const titleEl = document.getElementById('hwExamConfirmTitle');
    const descEl = document.getElementById('hwExamConfirmDesc');

    headerEl.textContent = isHomework ? '✦ 派遣探索' : '✦ 深境螺旋';
    iconEl.textContent = isHomework ? '📝' : '🌀';
    iconEl.style.background = isHomework ? 'rgba(196,153,52,0.1)' : 'rgba(226,96,74,0.1)';
    titleEl.textContent = isHomework ? `提交作业「${event.title || ''}」？` : `提交考试「${event.title || ''}」？`;
    descEl.textContent = isHomework
        ? '可以拍照上传作业，或直接输入文字描述'
        : '可以拍照上传试卷，或直接输入文字描述';

    // Style the text button based on type
    const textBtn = document.getElementById('hwExamTextBtn');
    textBtn.style.background = isHomework
        ? 'linear-gradient(135deg,#A67D1F,#C49934,#D4A853)'
        : 'linear-gradient(135deg,#C44A3A,#E2604A,#E8796B)';

    modal.classList.add('active');

    const uploadBtn = document.getElementById('hwExamUploadBtn');
    const cancelBtn = document.getElementById('hwExamCancelBtn');
    const closeBtn = document.getElementById('closeHwExamConfirmBtn');

    const newUploadBtn = uploadBtn.cloneNode(true);
    const newTextBtn = textBtn.cloneNode(true);
    const newCancelBtn = cancelBtn.cloneNode(true);
    const newCloseBtn = closeBtn.cloneNode(true);
    uploadBtn.replaceWith(newUploadBtn);
    textBtn.replaceWith(newTextBtn);
    cancelBtn.replaceWith(newCancelBtn);
    closeBtn.replaceWith(newCloseBtn);

    const closeFn = () => modal.classList.remove('active');
    newCancelBtn.addEventListener('click', closeFn);
    newCloseBtn.addEventListener('click', closeFn);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeFn(); }, { once: true });

    const mode = isHomework ? 'homework_check' : 'exam_analysis';

    // Upload photo → jump to chat with file dialog auto-open
    newUploadBtn.addEventListener('click', async () => {
        closeFn();
        await apiPut(`/api/schedule/${event.course_id}/${event.id}`, { completed: true, completed_at: new Date().toISOString() });
        const params = new URLSearchParams({
            course: event.course_id,
            action: mode,
            event_title: event.title || '',
            open_upload: '1',
        });
        window.location.href = `/?${params.toString()}`;
    });

    // Text input → jump to chat in the mode
    newTextBtn.addEventListener('click', async () => {
        closeFn();
        await apiPut(`/api/schedule/${event.course_id}/${event.id}`, { completed: true, completed_at: new Date().toISOString() });
        const params = new URLSearchParams({
            course: event.course_id,
            action: mode,
            event_title: event.title || '',
        });
        window.location.href = `/?${params.toString()}`;
    });
}

// ============ Event Modal ============

// ---- Custom DateTime Picker ----
const cdpState = { year: 0, month: 0, selectedDate: null, open: false };

function initDateTimePicker() {
    const display = document.getElementById('cdpDisplay');
    const dropdown = document.getElementById('cdpDropdown');
    const hourSel = document.getElementById('cdpHour');
    const minSel = document.getElementById('cdpMinute');

    // Populate hour/minute selects
    for (let h = 0; h < 24; h++) {
        const opt = document.createElement('option');
        opt.value = String(h).padStart(2, '0');
        opt.textContent = String(h).padStart(2, '0');
        hourSel.appendChild(opt);
    }
    for (let m = 0; m < 60; m += 5) {
        const opt = document.createElement('option');
        opt.value = String(m).padStart(2, '0');
        opt.textContent = String(m).padStart(2, '0');
        minSel.appendChild(opt);
    }

    // Default to current hour, nearest 5-min
    const now = new Date();
    hourSel.value = String(now.getHours()).padStart(2, '0');
    const nearMin = Math.ceil(now.getMinutes() / 5) * 5;
    minSel.value = String(nearMin >= 60 ? 55 : nearMin).padStart(2, '0');

    // Toggle dropdown
    display.addEventListener('click', (e) => {
        e.stopPropagation();
        if (cdpState.open) {
            closeDatePicker();
        } else {
            openDatePicker();
        }
    });

    // Navigation
    document.getElementById('cdpPrevMonth').addEventListener('click', (e) => {
        e.stopPropagation();
        cdpState.month--;
        if (cdpState.month < 0) { cdpState.month = 11; cdpState.year--; }
        renderPickerDays();
    });
    document.getElementById('cdpNextMonth').addEventListener('click', (e) => {
        e.stopPropagation();
        cdpState.month++;
        if (cdpState.month > 11) { cdpState.month = 0; cdpState.year++; }
        renderPickerDays();
    });

    // Today button
    document.getElementById('cdpTodayBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        const today = new Date();
        cdpState.year = today.getFullYear();
        cdpState.month = today.getMonth();
        cdpState.selectedDate = formatDateKey(today);
        renderPickerDays();
    });

    // Confirm button
    document.getElementById('cdpConfirmBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        confirmDatePicker();
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (cdpState.open && !e.target.closest('.custom-datetime-picker')) {
            closeDatePicker();
        }
    });

    // Prevent dropdown clicks from closing
    dropdown.addEventListener('click', (e) => { e.stopPropagation(); });
}

function openDatePicker() {
    const dropdown = document.getElementById('cdpDropdown');
    const display = document.getElementById('cdpDisplay');
    // If no date selected yet, default to today
    if (!cdpState.selectedDate) {
        const now = new Date();
        cdpState.year = now.getFullYear();
        cdpState.month = now.getMonth();
    } else {
        const parts = cdpState.selectedDate.split('-');
        cdpState.year = parseInt(parts[0]);
        cdpState.month = parseInt(parts[1]) - 1;
    }
    renderPickerDays();
    dropdown.classList.add('open');
    display.classList.add('active');
    cdpState.open = true;
}

function closeDatePicker() {
    document.getElementById('cdpDropdown').classList.remove('open');
    document.getElementById('cdpDisplay').classList.remove('active');
    cdpState.open = false;
}

function confirmDatePicker() {
    if (!cdpState.selectedDate) {
        // Auto-select today if nothing selected
        cdpState.selectedDate = formatDateKey(new Date());
    }
    const h = document.getElementById('cdpHour').value;
    const m = document.getElementById('cdpMinute').value;
    const dtValue = `${cdpState.selectedDate}T${h}:${m}`;
    document.getElementById('eventDateInput').value = dtValue;

    // Update display text
    const d = new Date(dtValue);
    const displayText = `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日 ${h}:${m}`;
    document.getElementById('cdpDisplayText').textContent = displayText;

    closeDatePicker();
}

function renderPickerDays() {
    const container = document.getElementById('cdpDays');
    const titleEl = document.getElementById('cdpMonthTitle');
    const year = cdpState.year;
    const month = cdpState.month;

    titleEl.textContent = `${year}年${month + 1}月`;

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startDay = firstDay.getDay();
    const totalDays = lastDay.getDate();
    const today = formatDateKey(new Date());

    let html = '';
    // Fill leading blanks from previous month
    const prevLast = new Date(year, month, 0).getDate();
    for (let i = startDay - 1; i >= 0; i--) {
        const day = prevLast - i;
        html += `<button type="button" class="cdp-day other-month" data-date="">${day}</button>`;
    }
    // Current month days
    for (let d = 1; d <= totalDays; d++) {
        const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        const isToday = dateStr === today ? ' today' : '';
        const isSelected = dateStr === cdpState.selectedDate ? ' selected' : '';
        html += `<button type="button" class="cdp-day${isToday}${isSelected}" data-date="${dateStr}">${d}</button>`;
    }
    // Trailing blanks
    const totalCells = Math.ceil((startDay + totalDays) / 7) * 7;
    for (let i = 1; i <= totalCells - startDay - totalDays; i++) {
        html += `<button type="button" class="cdp-day other-month" data-date="">${i}</button>`;
    }

    container.innerHTML = html;

    // Bind day clicks
    container.querySelectorAll('.cdp-day:not(.other-month)').forEach(btn => {
        btn.addEventListener('click', () => {
            cdpState.selectedDate = btn.dataset.date;
            renderPickerDays();
        });
    });
}

function setDatePickerValue(datetimeStr) {
    if (!datetimeStr) {
        cdpState.selectedDate = null;
        document.getElementById('eventDateInput').value = '';
        document.getElementById('cdpDisplayText').textContent = '点击选择日期时间';
        const now = new Date();
        document.getElementById('cdpHour').value = String(now.getHours()).padStart(2, '0');
        const nearMin = Math.ceil(now.getMinutes() / 5) * 5;
        document.getElementById('cdpMinute').value = String(nearMin >= 60 ? 55 : nearMin).padStart(2, '0');
        return;
    }
    const dt = datetimeStr.slice(0, 16); // "YYYY-MM-DDTHH:MM"
    const datePart = dt.slice(0, 10);
    const timePart = dt.slice(11);
    cdpState.selectedDate = datePart;
    document.getElementById('eventDateInput').value = dt;

    const h = timePart ? timePart.slice(0, 2) : '08';
    const rawM = timePart ? parseInt(timePart.slice(3, 5)) : 0;
    const m5 = Math.round(rawM / 5) * 5;
    document.getElementById('cdpHour').value = h;
    document.getElementById('cdpMinute').value = String(m5 >= 60 ? 55 : m5).padStart(2, '0');

    const d = new Date(datePart + 'T00:00:00');
    document.getElementById('cdpDisplayText').textContent = `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日 ${h}:${String(m5 >= 60 ? 55 : m5).padStart(2,'0')}`;
}

// ---- Radio Group helpers ----

// Single-select radio group helper
function initRadioGroup(groupId) {
    const group = document.getElementById(groupId);
    if (!group) return;
    group.addEventListener('click', (e) => {
        const opt = e.target.closest('.event-type-option');
        if (!opt) return;
        group.querySelectorAll('.event-type-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        // If this is the repeat group, toggle repeat count visibility
        if (groupId === 'eventRepeatGroup') {
            updateRepeatCountVisibility(opt.dataset.repeat);
        }
    });
}

// Default repeat counts per type
const REPEAT_DEFAULTS = {
    daily: { default: 7, hint: '次（建议 1~30）' },
    weekdays: { default: 10, hint: '次（建议 1~60）' },
    weekly: { default: 4, hint: '次（建议 1~52）' },
    biweekly: { default: 4, hint: '次（建议 1~26）' },
    monthly: { default: 3, hint: '次（建议 1~12）' },
};

function updateRepeatCountVisibility(repeatValue) {
    const group = document.getElementById('repeatCountGroup');
    if (!group) return;
    if (repeatValue && repeatValue !== 'none') {
        group.style.display = '';
        const cfg = REPEAT_DEFAULTS[repeatValue] || { default: 4, hint: '次' };
        document.getElementById('repeatCountInput').value = cfg.default;
        document.getElementById('repeatCountHint').textContent = cfg.hint;
    } else {
        group.style.display = 'none';
    }
}

function getRadioValue(groupId, attr) {
    const group = document.getElementById(groupId);
    const active = group?.querySelector('.event-type-option.active');
    return active ? active.dataset[attr] : null;
}

function setRadioValue(groupId, attr, value) {
    const group = document.getElementById(groupId);
    if (!group) return;
    group.querySelectorAll('.event-type-option').forEach(o => {
        o.classList.toggle('active', o.dataset[attr] === value);
    });
}

function openAddEventModal() {
    schedState.editingEvent = null;
    document.getElementById('eventModalTitle').textContent = '✦ 添加日程';
    document.getElementById('eventTitleInput').value = '';
    setRadioValue('eventTypeGroup', 'type', 'study');
    setRadioValue('eventRepeatGroup', 'repeat', 'none');
    updateRepeatCountVisibility('none');
    setDatePickerValue('');
    document.getElementById('eventNoteInput').value = '';
    document.getElementById('deleteEventBtn').style.display = 'none';
    if (schedState.courses.length > 0) {
        document.getElementById('eventCourseSelect').value = schedState.courses[0].id;
    }
    openModal('eventModal');
}

function openEditEventModal(event) {
    schedState.editingEvent = event;
    document.getElementById('eventModalTitle').textContent = '✎ 编辑日程';
    document.getElementById('eventTitleInput').value = event.title || '';
    document.getElementById('eventCourseSelect').value = event.course_id || '';
    setRadioValue('eventTypeGroup', 'type', event.type || 'study');
    const repeatVal = event.repeat || 'none';
    setRadioValue('eventRepeatGroup', 'repeat', repeatVal);
    updateRepeatCountVisibility(repeatVal);
    if (repeatVal !== 'none' && event.repeat_count) {
        document.getElementById('repeatCountInput').value = event.repeat_count;
    }
    setDatePickerValue(event.datetime || '');
    document.getElementById('eventNoteInput').value = event.note || '';
    document.getElementById('deleteEventBtn').style.display = 'inline-block';
    openModal('eventModal');
}

async function saveEvent() {
    const courseId = document.getElementById('eventCourseSelect').value;
    const selectedType = getRadioValue('eventTypeGroup', 'type') || 'study';
    const selectedRepeat = getRadioValue('eventRepeatGroup', 'repeat') || 'none';
    const data = {
        title: document.getElementById('eventTitleInput').value.trim(),
        type: selectedType,
        datetime: document.getElementById('eventDateInput').value,
        date: document.getElementById('eventDateInput').value.slice(0, 10),
        note: document.getElementById('eventNoteInput').value.trim(),
    };
    if (selectedRepeat !== 'none') {
        data.repeat = selectedRepeat;
        const rc = parseInt(document.getElementById('repeatCountInput').value) || 4;
        data.repeat_count = Math.max(1, Math.min(rc, 365));
    }
    if (!data.title || !courseId) return;

    if (schedState.editingEvent) {
        await apiPut(`/api/schedule/${schedState.editingEvent.course_id}/${schedState.editingEvent.id}`, data);
    } else {
        await apiPost(`/api/schedule/${courseId}`, data);
    }
    closeModal('eventModal');
    await loadData();
}

async function deleteEvent() {
    if (!schedState.editingEvent) return;
    const ev = schedState.editingEvent;
    const isRepeat = ev.repeat && ev.repeat !== 'none';
    closeModal('eventModal');
    showDeleteConfirm(ev.id, ev.course_id, ev.title || '此日程', isRepeat);
}

// ============ Navigation ============
function navigate(direction) {
    if (schedState.view === 'week') {
        schedState.currentDate.setDate(schedState.currentDate.getDate() + direction * 7);
    } else {
        schedState.currentDate.setMonth(schedState.currentDate.getMonth() + direction);
    }
    renderCalendar();
    saveScheduleState();
}

// ============ Init ============
document.addEventListener('DOMContentLoaded', async () => {
    await restoreScheduleState();
    await loadData();

    // View toggle
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === schedState.view);
        btn.addEventListener('click', () => {
            schedState.view = btn.dataset.view;
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderCalendar();
            saveScheduleState();
        });
    });

    // Type filters
    document.querySelectorAll('.filter-chip[data-type]').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.filter-chip[data-type]').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            schedState.filterType = chip.dataset.type;
            renderCalendar();
        });
    });

    // Navigation
    document.getElementById('prevBtn').addEventListener('click', () => navigate(-1));
    document.getElementById('nextBtn').addEventListener('click', () => navigate(1));

    // Event modal
    initRadioGroup('eventTypeGroup');
    initRadioGroup('eventRepeatGroup');
    initDateTimePicker();
    document.getElementById('addEventBtn').addEventListener('click', openAddEventModal);
    document.getElementById('closeEventModalBtn').addEventListener('click', () => {
        closeModal('eventModal');
    });
    document.getElementById('saveEventBtn').addEventListener('click', saveEvent);
    document.getElementById('deleteEventBtn').addEventListener('click', deleteEvent);

    // Close modal on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.classList.remove('active');
        });
    });

    // beforeunload
    window.addEventListener('beforeunload', () => {
        navigator.sendBeacon('/api/state', new Blob([JSON.stringify({
            schedule_view: schedState.view,
            schedule_date: schedState.currentDate.toISOString(),
        })], { type: 'application/json' }));
    });
});
