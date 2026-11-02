// Unit checks for the real request controller, not a browser/visual simulation.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');
const source = readFileSync(join(__dirname, 'static/booking/booking.js'), 'utf8');
const settle = () => new Promise(setImmediate);

function controller({reducedMotion = false} = {}) {
    const events = {}, requests = [], replacements = [], history = [], focuses = [], scrolls = [];
    const status = {}, retry = {addEventListener: (_, handler) => { retry.click = handler; }};
    const refresh = {dataset: {loading: 'loading', ready: 'ready', error: 'error'},
        querySelector: (selector) => selector === '[role="status"]' ? status : retry};
    const inputs = {customer_name: {value: 'Synthetic Draft'}, phone: {value: '0888123456'}, email: {value: ''}};
    const form = {action: 'http://example.test/book/',
        values: {lang: 'en', service: '1', barber: '2', date: '2030-01-08'}, focus() {}};
    function content(name, {details = true, times = true} = {}) {
        const heading = (id) => ({
            focus(options) { focuses.push({id, ...options}); events.focusin(); },
            scrollIntoView(options) { scrolls.push({id, ...options}); },
        });
        const item = {name, style: {}, details, times,
            getBoundingClientRect: () => ({height: 400}), contains: (element) => element.owner === item,
            setAttribute() {}, removeAttribute() {},
            replaceWith(next) { current = next; replacements.push(next.name); },
            querySelectorAll() {
                return ['service', 'barber', 'date'].map((name) => ({dataset: {filter: name},
                    set value(value) { form.values[name] = value; }}));
            },
            querySelector(selector) {
                if (selector === '#visit-selection') return form;
                if (selector === '.auto-refresh-note') return {};
                if (selector === '#details') return item.details ? {remove() { item.details = false; }, focus() {}, scrollIntoView() {}} : null;
                if (selector === '[data-booking-times]') return {replaceChildren() { item.times = false; }};
                if (selector === '[data-booking-time]') return item.times ? {} : null;
                if (selector === '#time-selection-heading') return heading('times');
                if (selector === '#details-heading') return item.details ? heading('details') : null;
                const field = selector.match(/^#details \[name="(\w+)"\]$/)?.[1];
                return field && item.details ? inputs[field] : null;
            }};
        return item;
    }
    let current = content('initial');
    const document = {body: {}, activeElement: null,
        getElementById: (id) => id === 'booking-content' ? current : refresh,
        querySelectorAll: () => [], addEventListener: (event, handler) => { events[event] = handler; }};
    document.activeElement = document.body;
    const window = {fetch: true, location: {href: 'http://example.test/book/?lang=en'},
        history: {pushState(_, __, url) { history.push(url.href); window.location.href = url.href; }},
        addEventListener: (event, handler) => { events[event] = handler; }, scrollTo() {},
        matchMedia: () => ({matches: reducedMotion})};
    const fetch = (url, options) => new Promise((resolve, reject) => {
        requests.push({url: new URL(url), options, reject,
            finish(name, state) { resolve({ok: true, redirected: false, text: async () => ({name, state})}); }});
    });
    runInNewContext(source, {document, window, fetch, URL, URLSearchParams,
        FormData: class { constructor() { return Object.entries(form.values); } },
        DOMParser: class { parseFromString({name, state}) { return {getElementById: () => content(name, state)}; } }});
    return {requests, replacements, status, retry, history, inputs, form, focuses, scrolls,
        get current() { return current; },
        moveFocus() { document.activeElement = {}; events.focusin(); },
        back() { events.popstate(); },
        apply() { events.submit({target: {id: 'visit-selection'}, preventDefault() {}}); },
        click(kind) {
            const link = {owner: current, dataset: kind === 'clear' ? {clearFilter: 'service'} : {},
                href: 'http://example.test/book/?lang=en&service=1&barber=2&date=2030-01-08&time=10:00#details',
                hasAttribute: () => kind === 'reset'};
            events.click({target: {closest: () => link}, button: 0, preventDefault() {}});
        },
        change(service) {
            form.values.service = service;
            events.change({target: {matches: () => true}});
        }};
}

test('rapid changes clear stale confirmation immediately and serialize/coalesce GETs', async () => {
    const app = controller();
    const original = app.current;
    app.change('1');
    assert.equal(original.details, false);
    assert.equal(original.times, false);
    app.change('2');
    app.change('3');
    assert.equal(app.requests.length, 1);
    assert.equal(app.requests[0].options.credentials, 'same-origin');
    app.requests[0].finish('obsolete');
    await settle();
    assert.equal(app.requests.length, 2);
    assert.equal(app.requests[1].url.searchParams.get('service'), '3');
    assert.deepEqual(app.replacements, []);
    assert.deepEqual(app.scrolls, []);
    app.inputs.phone.value = '';
    app.requests[1].finish('latest');
    await settle();
    assert.deepEqual(app.replacements, ['latest']);
    assert.equal(app.status.textContent, 'ready');
    assert.equal(app.inputs.phone.value, '0888123456');
    assert.equal(app.history.length, 1);
    assert.deepEqual(app.scrolls, [{id: 'times', block: 'start', behavior: 'smooth'}]);
    for (const request of app.requests) {
        assert.equal(request.url.searchParams.has('phone'), false);
        assert.equal(request.url.searchParams.has('customer_name'), false);
    }
});

test('failed refresh keeps old times and confirmation removed, retry restores saved draft', async () => {
    const app = controller();
    app.change('4');
    app.requests[0].reject(new Error('Synthetic offline response'));
    await settle();
    assert.equal(app.status.textContent, 'error');
    assert.equal(app.retry.hidden, false);
    assert.equal(app.current.details, false);
    assert.equal(app.current.times, false);
    assert.deepEqual(app.history, []);
    assert.deepEqual(app.scrolls, []);
    app.retry.click();
    assert.equal(app.requests.length, 2);
    assert.equal(app.requests[1].url.href, app.requests[0].url.href);
    assert.equal(app.retry.hidden, true);
    app.inputs.customer_name.value = '';
    app.requests[1].finish('retried');
    await settle();
    assert.equal(app.inputs.customer_name.value, 'Synthetic Draft');
    assert.equal(app.status.textContent, 'ready');
    assert.deepEqual(app.replacements, ['retried']);
    assert.equal(app.scrolls[0].id, 'times');
});

test('completed filters guide to available times, then time selection guides to details', async () => {
    const app = controller();
    app.moveFocus(); // Focus activity before the request must not suppress guidance.
    app.apply();
    app.requests[0].finish('complete', {times: true, details: false});
    await settle();
    assert.deepEqual(app.focuses, [{id: 'times', preventScroll: true}]);
    app.click('time');
    app.requests[1].finish('selected-time', {times: true, details: true});
    await settle();
    assert.deepEqual(app.focuses, [{id: 'times', preventScroll: true}, {id: 'details', preventScroll: true}]);
    assert.deepEqual(app.scrolls, [
        {id: 'times', block: 'start', behavior: 'smooth'},
        {id: 'details', block: 'start', behavior: 'smooth'},
    ]);
});

test('partial or unavailable responses do not guide to empty steps', async () => {
    const app = controller();
    app.change('1');
    app.requests[0].finish('partial', {times: false, details: false});
    await settle();
    app.click('time');
    app.requests[1].finish('stale-time', {times: true, details: false});
    await settle();
    assert.deepEqual(app.scrolls, []);
    assert.deepEqual(app.focuses, []);
});

test('clear, reset and history refreshes do not advance even when response has times', async () => {
    for (const action of ['clear', 'reset', 'back']) {
        const app = controller();
        if (action === 'back') app.back();
        else app.click(action);
        app.requests[0].finish(action, {times: true, details: true});
        await settle();
        assert.deepEqual(app.scrolls, [], action);
        assert.deepEqual(app.focuses, [], action);
    }
});

test('moving focus while waiting suppresses automatic advance', async () => {
    for (const action of ['filters', 'time']) {
        const app = controller();
        if (action === 'time') app.click('time');
        else app.change('1');
        app.moveFocus();
        app.requests[0].finish('complete');
        await settle();
        assert.equal(app.status.textContent, 'ready');
        assert.deepEqual(app.scrolls, [], action);
        assert.deepEqual(app.focuses, [], action);
    }
});

test('reduced motion keeps guided focus and uses instant scrolling for both steps', async () => {
    const app = controller({reducedMotion: true});
    app.change('1');
    app.requests[0].finish('complete');
    await settle();
    app.click('time');
    app.requests[1].finish('selected-time');
    await settle();
    assert.deepEqual(app.scrolls, [
        {id: 'times', block: 'start', behavior: 'instant'},
        {id: 'details', block: 'start', behavior: 'instant'},
    ]);
});
