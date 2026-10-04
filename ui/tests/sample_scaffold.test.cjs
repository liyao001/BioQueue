// Run with: node ui3/tests/sample_scaffold.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = name => fs.readFileSync(path.join(__dirname, '../templates/ui3/', name), 'utf8');
// HTMX retains the triggering event for delayed requests; window.event does not.
const requestHandlers = [...read('jobs/new.html').matchAll(/hx-on::config-request="([^"]+)"/g)];
assert.equal(requestHandlers.length, 2);
for (const [, handler] of requestHandlers) {
  for (const [id, force] of [['id_protocol', 1], ['id_input_file', 0], ['id_sample_sheet', 0], [null, 0]]) {
    const event = {detail: {triggeringEvent: id ? {target: {id}} : undefined, parameters: {}}};
    vm.runInNewContext(handler, {event});
    assert.equal(event.detail.parameters.force, force);
  }
}
const validationSource = read('base.html').split('validateJsonField: function (field, kind) {')[1].split('      appendTokens:')[0];
const validate = vm.runInNewContext('(function (field, kind) {' + validationSource.trim().replace(/,$/, '') + ')');
const field = {
  value: '', nextElementSibling: {}, setAttribute() {},
  setCustomValidity(value) { this.error = value; },
  dispatchEvent(event) { this.lastEvent = event.type; },
};
for (const value of ['[{', '{}', '[1]', '[null]', '[[]]']) {
  field.value = value;
  validate(field, 'samples');
  assert.ok(field.error);
  assert.equal(field.nextElementSibling.textContent, field.error);
}
for (const value of ['', '[]', '[{"name":"rep1"}]']) {
  field.value = value;
  validate(field, 'samples');
  assert.equal(field.error, '');
}
for (const value of ['{', '[]', 'null']) {
  field.value = value;
  validate(field, 'template');
  assert.ok(field.error);
}
field.value = '{"pipeline":[]}';
validate(field, 'template');
assert.equal(field.error, ''); // Structure is validated by the server.

const section = {classList: {toggle(name, value) { section.hidden = value; }}};
const required = {};
const protocol = {dispatchEvent(event) { this.lastEvent = event.type; }};
const context = {
  document: {getElementById(id) { return {id_sample_sheet: field, 'sample-fields': section, 'sample-required': required, id_protocol: protocol}[id]; }},
  ui3: {validateJsonField: validate}, Event: class {constructor(type) {this.type = type;}},
};
const template = read('jobs/_sample_scaffold.html').split('<script>')[1].split('</script>')[0];
function refresh(value, active = true, force = false) {
  vm.runInNewContext(template
    .replace('{{ samples_active|yesno:"true,false" }}', String(active))
    .replace('{{ force|yesno:"true,false" }}', String(force))
    .replace('"{{ samples_value|escapejs }}"', JSON.stringify(value))
    .replaceAll('{{ samples_required|escapejs }}', 'condition'), context);
}
const one = '[{"name":"rep1","condition":""}]';
const two = '[{"name":"rep1","condition":""},{"name":"rep2","condition":""}]';
refresh(one, true, true);
assert.equal(field.value, one);
assert.equal(field.disabled, false);
assert.equal(section.hidden, false);
assert.equal(protocol.lastEvent, 'samples-ready');
refresh(two);
assert.equal(field.value, two);
field.value = '[{"name":"custom","condition":"treated"}]';
refresh(one);
assert.equal(field.value, '[{"name":"custom","condition":"treated"}]');
field.value = '[{';
refresh(two);
assert.equal(field.value, '[{'); // Do not replace in-progress edits.
refresh('', false, true);
assert.equal(field.disabled, true);
assert.equal(section.hidden, true);
assert.equal(field.error, '');
console.log('Sample scaffold visibility, prefilling, edit preservation, and JSON validation pass.');
