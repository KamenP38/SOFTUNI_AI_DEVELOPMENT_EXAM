// Unit checks for the real request controller, not a browser/visual simulation.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const {runInNewContext} = require('node:vm');
const source = readFileSync(join(__dirname, 'static/booking/booking.js'), 'utf8');
const settle = () => new Promise(setImmediate);

function controller() {
    const events = {}, requests = [], replacements = [], history = [];
    const status = {}, retry = {addEventListener: (_, handler) => { retry.click = handler; }};
    const refresh = {dataset: {loading: 'loading', ready: 'ready', error: 'error'},
        querySelector: (selector) => selector === '[role="status"]' ? status : retry};
    const inputs = {customer_name: {value: 'Synthetic Draft'}, phone: {value: '0888123456'}, email: {value: ''}};
    const form = {action: 'http://example.test/book/',
        values: {lang: 'en', service: '1', barber: '2', date: '2030-01-08'}, focus() {}};
    function content(name) {
        const item = {name, style: {}, details: true, times: true,
            getBoundingClientRect: () => ({height: 400}), contains: () => false,
            setAttribute() {}, removeAttribute() {},
            replaceWith(next) { current = next; replacements.push(next.name); },
            querySelector(selector) {
                if (selector === '#visit-selection') return form;
                if (selector === '.auto-refresh-note') return {};
                if (selector === '#details') return item.details ? {remove() { item.details = false; }, focus() {}, scrollIntoView() {}} : null;
                if (selector === '[data-booking-times]') return {replaceChildren() { item.times = false; }};
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
        addEventListener: (event, handler) => { events[event] = handler; }, scrollTo() {}};
    const fetch = (url, options) => new Promise((resolve, reject) => {
        requests.push({url: new URL(url), options, reject,
            finish(name) { resolve({ok: true, redirected: false, text: async () => name}); }});
    });
    runInNewContext(source, {document, window, fetch, URL, URLSearchParams,
        FormData: class { constructor() { return Object.entries(form.values); } },
        DOMParser: class { parseFromString(name) { return {getElementById: () => content(name)}; } }});
    return {requests, replacements, status, retry, history, inputs, form,
        get current() { return current; },
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
    app.inputs.phone.value = '';
    app.requests[1].finish('latest');
    await settle();
    assert.deepEqual(app.replacements, ['latest']);
    assert.equal(app.status.textContent, 'ready');
    assert.equal(app.inputs.phone.value, '0888123456');
    assert.equal(app.history.length, 1);
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
});
