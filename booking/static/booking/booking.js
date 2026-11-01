// Dates are presentation-only: availability and Sofia's booking window come
// from the server's select options, including explicitly unavailable stale values.
function enhanceDateCalendar(select) {
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
            select.dispatchEvent(new Event("change", {bubbles: true}));
        }
    });
    body.addEventListener("focusin", (event) => {
        const button = event.target.closest("[data-date]");
        if (!button) return;
        focusedDate = parseDate(button.dataset.date);
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
    if (["#date-calendar", `#${select.id}`].includes(window.location.hash)) {
        body.querySelector('[tabindex="0"]').focus();
    }
}

// The GET form contains no time: changing a filter always clears the old slot.
const visitSelection = document.getElementById("visit-selection");
if (visitSelection) {
    document.querySelector(".auto-refresh-note").hidden = false;
    visitSelection.querySelectorAll("[data-filter]").forEach((field) => {
        field.addEventListener("change", () => {
            // Carry the focus target through this navigation without storing data.
            const target = field.hidden && field.dataset.filter === "date" ? "date-calendar" : field.id;
            visitSelection.action = `${window.location.pathname}#${target}`;
            visitSelection.requestSubmit();
        });
    });
    const dateSelect = visitSelection.querySelector('[data-filter="date"]');
    if (dateSelect) enhanceDateCalendar(dateSelect);
}
