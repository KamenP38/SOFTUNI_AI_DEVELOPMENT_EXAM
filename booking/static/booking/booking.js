// Dates are presentation-only: availability and Sofia's booking window come
// from the server's select options, including explicitly unavailable stale values.
function enhanceDateCalendar(select, savedState = null) {
    const calendar = document.getElementById("date-calendar");
    if (!calendar || !select.dataset.minDate || !select.dataset.maxDate) return;

    const parseDate = (value) => new Date(`${value}T00:00:00Z`);
    const isoDate = (date) => date.toISOString().slice(0, 10);
    const addDays = (date, days) => new Date(date.getTime() + days * 86400000);
    const monthStart = (date, offset = 0) => new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + offset, 1));
    const mondayOffset = (date) => (date.getUTCDay() + 6) % 7;
    const min = parseDate(select.dataset.minDate);
    const max = parseDate(select.dataset.maxDate);
    const inWindow = (date) => date >= min && date <= max;
    const options = new Map(Array.from(select.options, (option) => [option.value, option]));
    const available = (value) => options.get(value)?.dataset.available === "true";
    const locale = document.documentElement.lang === "bg" ? "bg-BG" : "en-GB";
    const formatter = (options) => new Intl.DateTimeFormat(locale, {timeZone: "UTC", ...options});
    const fullDate = formatter({weekday: "long", day: "numeric", month: "long", year: "numeric"});
    const monthLabel = formatter({month: "long", year: "numeric"});
    const shortDay = formatter({weekday: "short"});
    const longDay = formatter({weekday: "long"});
    const body = calendar.querySelector("tbody");
    const previous = calendar.querySelector('[data-month-step="-1"]');
    const next = calendar.querySelector('[data-month-step="1"]');
    const selectedDate = parseDate(select.value);
    let focusedDate = inWindow(selectedDate) ? selectedDate : min;
    let month = monthStart(focusedDate);
    if (savedState) {
        const savedMonth = parseDate(savedState.month);
        const savedFocus = parseDate(savedState.focusedDate);
        if (savedMonth >= monthStart(min) && savedMonth <= monthStart(max)) {
            month = savedMonth;
            focusedDate = inWindow(savedFocus) ? savedFocus : (month < min ? min : month);
        }
    }

    // Explicit UTC dates avoid shifting calendar days in the visitor's timezone.
    for (let index = 0; index < 7; index += 1) {
        const day = addDays(new Date(Date.UTC(2026, 0, 5)), index);
        const heading = document.createElement("th");
        heading.scope = "col";
        heading.setAttribute("aria-label", longDay.format(day));
        heading.textContent = shortDay.format(day);
        calendar.querySelector("thead tr").append(heading);
    }
    calendar.querySelector("[data-calendar-selection]").textContent = options.get(select.value)?.textContent || "";

    function renderMonth(moveFocus = false) {
        calendar.dataset.month = isoDate(month);
        calendar.dataset.focusedDate = isoDate(focusedDate);
        calendar.querySelector("#calendar-month").textContent = monthLabel.format(month);
        previous.disabled = month <= monthStart(min);
        next.disabled = month >= monthStart(max);
        body.replaceChildren();
        const start = addDays(month, -mondayOffset(month));
        const monthEnd = addDays(monthStart(month, 1), -1);
        const cells = Math.ceil((mondayOffset(month) + monthEnd.getUTCDate()) / 7) * 7;
        let row;
        for (let index = 0; index < cells; index += 1) {
            if (index % 7 === 0) {
                row = document.createElement("tr");
                body.append(row);
            }
            const day = addDays(start, index);
            const value = isoDate(day);
            const cell = document.createElement("td");
            const button = document.createElement("button");
            const outside = !inWindow(day) || day.getUTCMonth() !== month.getUTCMonth();
            const selectable = !outside && available(value);
            button.type = "button";
            button.className = "calendar-day";
            button.textContent = day.getUTCDate();
            button.dataset.date = value;
            button.tabIndex = value === isoDate(focusedDate) ? 0 : -1;
            button.disabled = outside;
            button.setAttribute("aria-disabled", String(!selectable));
            button.setAttribute("aria-label", `${fullDate.format(day)}${selectable ? "" : ` — ${outside ? calendar.dataset.outside : calendar.dataset.unavailable}`}`);
            cell.setAttribute("aria-selected", String(value === select.value));
            if (value === select.value) button.classList.add("is-selected");
            if (value === select.dataset.minDate) button.setAttribute("aria-current", "date");
            if (outside) button.classList.add("is-outside");
            cell.append(button);
            row.append(cell);
        }
        if (moveFocus) body.querySelector('[tabindex="0"]').focus();
    }

    function focusDay(day) {
        focusedDate = day < min ? min : day > max ? max : day;
        month = monthStart(focusedDate);
        renderMonth(true);
    }

    calendar.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button || button.disabled) return;
        if (button.dataset.monthStep) {
            const target = monthStart(month, Number(button.dataset.monthStep));
            focusedDate = target < min ? min : target;
            month = monthStart(focusedDate);
            renderMonth();
            // At a boundary the clicked navigation button becomes disabled.
            if (button.disabled) body.querySelector('[tabindex="0"]').focus();
        } else if (button.dataset.date && button.getAttribute("aria-disabled") !== "true") {
            select.value = button.dataset.date;
            calendar.querySelector("[data-calendar-selection]").textContent = options.get(select.value)?.textContent || "";
            body.querySelectorAll("[data-date]").forEach((day) => {
                const selected = day.dataset.date === select.value;
                day.classList.toggle("is-selected", selected);
                day.parentElement.setAttribute("aria-selected", String(selected));
            });
            select.dispatchEvent(new Event("change", {bubbles: true}));
        }
    });
    body.addEventListener("focusin", (event) => {
        const button = event.target.closest("[data-date]");
        if (!button) return;
        focusedDate = parseDate(button.dataset.date);
        calendar.dataset.focusedDate = button.dataset.date;
        body.querySelectorAll("button").forEach((day) => { day.tabIndex = day === button ? 0 : -1; });
    });
    body.addEventListener("keydown", (event) => {
        const offsets = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
        let target;
        if (event.key in offsets) target = addDays(focusedDate, offsets[event.key]);
        else if (event.key === "Home") target = addDays(focusedDate, -mondayOffset(focusedDate));
        else if (event.key === "End") target = addDays(focusedDate, 6 - mondayOffset(focusedDate));
        else if (event.key === "PageUp" || event.key === "PageDown") {
            const first = monthStart(focusedDate, event.key === "PageUp" ? -1 : 1);
            const last = addDays(monthStart(first, 1), -1);
            target = addDays(first, Math.min(focusedDate.getUTCDate(), last.getUTCDate()) - 1);
        }
        if (target) {
            event.preventDefault();
            focusDay(target);
        }
    });
    renderMonth();
    select.hidden = true;
    calendar.hidden = false;
    const label = select.labels[0];
    if (label) {
        label.removeAttribute("for");
        label.id = "calendar-label";
        calendar.setAttribute("aria-labelledby", label.id);
    }
    if (!savedState && ["#date-calendar", `#${select.id}`].includes(window.location.hash)) {
        body.querySelector('[tabindex="0"]').focus();
    }
}

function enhanceBooking() {
    let content = document.getElementById("booking-content");
    const refresh = document.getElementById("booking-refresh");
    if (!content || !refresh || !window.fetch) return;
    const status = refresh.querySelector('[role="status"]');
    const retry = refresh.querySelector("[data-booking-retry]");
    const draft = {};
    let pending = null;
    let running = false;
    let revision = 0;
    let failed = null;
    let focusVersion = 0;

    function initializeCalendar(state = null) {
        content.querySelector(".auto-refresh-note").hidden = false;
        const select = content.querySelector('[data-filter="date"]');
        if (select) enhanceDateCalendar(select, state);
    }

    function selectionURL() {
        const form = content.querySelector("#visit-selection");
        const url = new URL(form.action, window.location.href);
        url.search = new URLSearchParams(new FormData(form)).toString();
        url.hash = "visit-selection";
        return url;
    }

    function saveDraft() {
        for (const name of ["customer_name", "phone", "email"]) {
            const input = content.querySelector(`#details [name="${name}"]`);
            if (input) draft[name] = input.value;
        }
    }

    function clearTimes() {
        saveDraft();
        // Remove the old POST form immediately, even if the refresh later fails.
        content.querySelector("#details")?.remove();
        content.querySelector("[data-booking-times]")?.replaceChildren();
    }

    function focusSelector(element) {
        if (!element || !content.contains(element)) return null;
        if (element.dataset.date) return `[data-date="${element.dataset.date}"]`;
        if (element.dataset.monthStep) return `[data-month-step="${element.dataset.monthStep}"]`;
        if (element.dataset.clearFilter) return `[data-filter="${element.dataset.clearFilter}"]`;
        if (element.id) return `#${CSS.escape(element.id)}`;
        return "#visit-selection";
    }

    function updateLanguageLinks(url) {
        document.querySelectorAll(".lang-toggle a[lang]").forEach((link) => {
            const target = new URL(url);
            target.searchParams.set("lang", link.lang);
            link.href = target.href;
        });
    }

    function request(url, {history = true, resetCalendar = false, focus = null, nextStep = null} = {}) {
        pending = {url, history, resetCalendar, focus, nextStep, revision: ++revision};
        failed = null;
        content.style.minHeight = `${content.getBoundingClientRect().height}px`;
        clearTimes();
        refresh.hidden = false;
        retry.hidden = true;
        status.textContent = refresh.dataset.loading;
        content.setAttribute("aria-busy", "true");
        pending.focusVersion = focusVersion;
        void runRequests();
    }

    async function runRequests() {
        if (running) return;
        running = true;
        // GETs also save the session (language and issued booking nonces). Wait
        // for each response before the next GET, coalescing rapid filter changes.
        // Aborting a fetch would not cancel its server-side session write.
        while (pending) {
            const job = pending;
            pending = null;
            try {
                const response = await fetch(job.url, {
                    credentials: "same-origin", cache: "no-store",
                    headers: {Accept: "text/html"},
                });
                if (!response.ok || response.redirected) throw new Error("Availability response failed");
                const documentResult = new DOMParser().parseFromString(await response.text(), "text/html");
                const replacement = documentResult.getElementById("booking-content");
                if (!replacement?.querySelector("#visit-selection")) throw new Error("Missing booking content");
                if (job.revision !== revision) continue;

                const active = document.activeElement;
                const target = focusSelector(active) || (active === document.body || active === retry ? job.focus : null);
                // Changing a filter can complete the visit while focus remains on
                // that control. Advance only if the user has not focused elsewhere.
                const advance = job.focusVersion === focusVersion ? job.nextStep : null;
                const calendar = content.querySelector("#date-calendar");
                const calendarState = !job.resetCalendar && calendar ? {...calendar.dataset} : null;
                const scroll = {left: window.scrollX, top: window.scrollY, behavior: "instant"};
                content.replaceWith(replacement);
                content = replacement;
                initializeCalendar(calendarState);
                for (const [name, value] of Object.entries(draft)) {
                    const input = content.querySelector(`#details [name="${name}"]`);
                    if (input) input.value = value;
                }
                if (job.history && job.url.href !== window.location.href) {
                    window.history.pushState(null, "", job.url);
                }
                updateLanguageLinks(job.url);
                const nextHeading = advance === "details" ? content.querySelector("#details-heading") :
                    advance === "times" && content.querySelector("[data-booking-time]") ?
                        content.querySelector("#time-selection-heading") : null;
                if (target && !nextHeading) {
                    let element = content.querySelector(target);
                    if (element?.hidden || element?.disabled) element = null;
                    (element || content.querySelector("#visit-selection")).focus({preventScroll: true});
                }
                window.scrollTo(scroll);
                if (nextHeading) {
                    nextHeading.focus({preventScroll: true});
                    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                    nextHeading.scrollIntoView({block: "start", behavior: reducedMotion ? "instant" : "smooth"});
                }
                status.textContent = refresh.dataset.ready;
                content.removeAttribute("aria-busy");
            } catch (error) {
                if (job.revision !== revision) continue;
                clearTimes();
                failed = job;
                status.textContent = refresh.dataset.error;
                retry.hidden = false;
                content.removeAttribute("aria-busy");
            }
        }
        running = false;
    }

    // Delegate to the stable document because each successful GET replaces the
    // form. Ordinary links/forms remain fully usable when enhancement is absent.
    document.addEventListener("focusin", () => { focusVersion += 1; });
    document.addEventListener("change", (event) => {
        if (!event.target.matches("#visit-selection [data-filter]")) return;
        request(selectionURL(), {focus: focusSelector(document.activeElement), nextStep: "times"});
    });
    document.addEventListener("submit", (event) => {
        if (event.target.id !== "visit-selection") return;
        event.preventDefault();
        request(selectionURL(), {focus: "#visit-selection", nextStep: "times"});
    });
    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[data-clear-filter], a[data-reset-filters], a[data-booking-time]");
        if (!link || !content.contains(link) || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        const clear = link.dataset.clearFilter;
        const reset = link.hasAttribute("data-reset-filters");
        if (clear || reset) {
            content.querySelectorAll("#visit-selection [data-filter]").forEach((field) => {
                if (reset || field.dataset.filter === clear) field.value = "";
            });
            request(selectionURL(), {resetCalendar: reset || clear === "date", focus: "#visit-selection"});
        } else {
            request(new URL(link.href), {focus: "#visit-selection", nextStep: "details"});
        }
    });
    retry.addEventListener("click", () => {
        if (failed) request(failed.url, {...failed, focus: "#visit-selection"});
    });
    window.addEventListener("popstate", () => {
        request(new URL(window.location.href), {history: false, resetCalendar: true, focus: "#visit-selection"});
    });
    refresh.hidden = false;
    initializeCalendar();
}

enhanceBooking();
