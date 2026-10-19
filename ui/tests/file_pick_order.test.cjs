// Run with: node ui/tests/file_pick_order.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(path.join(__dirname, '../templates/ui3/base.html'), 'utf8');
const start = src.indexOf('// file-pick-order:start');
const end = src.indexOf('// file-pick-order:end');
assert.ok(start > 0 && end > start);
const chunk = src.slice(start, end);

function checkbox(className, data, parent) {
  const node = {
    parent: parent || null,
    checked: false,
    classList: {
      contains(name) { return className.split(/\s+/).includes(name); },
    },
    getAttribute(name) {
      if (name === 'data-rel') return data.rel || null;
      if (name === 'data-name') return data.name || null;
      if (name === 'data-picker-job') return data.job || null;
      if (name === 'data-picker-shared') return data.shared || null;
      return null;
    },
    closest(sel) {
      if (sel !== '[data-picker-job]') return null;
      let current = this;
      while (current) {
        if (current.getAttribute && current.getAttribute('data-picker-job')) return current;
        current = current.parent;
      }
      return null;
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  return node;
}

function listRoot(nodes) {
  return {
    querySelector(sel) {
      if (sel === 'input.upload-opt, input.result-opt') {
        return nodes.find((node) => node.classList.contains('upload-opt') || node.classList.contains('result-opt')) || null;
      }
      return null;
    },
    querySelectorAll(sel) {
      const checkedOnly = sel.includes(':checked');
      const wantUpload = sel.includes('upload-opt');
      const wantResult = sel.includes('result-opt');
      return nodes.filter((node) => {
        const upload = node.classList.contains('upload-opt');
        const result = node.classList.contains('result-opt');
        if (wantUpload && wantResult) return upload || result;
        if (wantUpload && !upload) return false;
        if (wantResult && !result) return false;
        if (checkedOnly && !node.checked) return false;
        return true;
      });
    },
  };
}

function names(boxes, attr) {
  return Array.from(boxes).map((box) => box.getAttribute(attr)).join(',');
}

const context = { window: {} };
vm.runInNewContext('window.ui3 = {\n' + chunk + '\n};', context);
const ui3 = context.window.ui3;

const uploads = ['a.fq', 'b.fq', 'c.fq'].map((rel) => checkbox('checkbox checkbox-sm upload-opt', { rel }));
const uploadRoot = listRoot(uploads);
function pickUpload(rel) {
  const box = uploads.find((node) => node.getAttribute('data-rel') === rel);
  box.checked = true;
  ui3.noteFilePick(box);
}

pickUpload('c.fq');
pickUpload('a.fq');
pickUpload('b.fq');
assert.equal(names(ui3.checkedInPickOrder(uploadRoot, 'input.upload-opt'), 'data-rel'), 'c.fq,a.fq,b.fq');

uploads.find((node) => node.getAttribute('data-rel') === 'a.fq').checked = false;
ui3.noteFilePick(uploads.find((node) => node.getAttribute('data-rel') === 'a.fq'));
assert.equal(names(ui3.checkedInPickOrder(uploadRoot, 'input.upload-opt'), 'data-rel'), 'c.fq,b.fq');

pickUpload('a.fq');
assert.equal(names(ui3.checkedInPickOrder(uploadRoot, 'input.upload-opt'), 'data-rel'), 'c.fq,b.fq,a.fq');

const filtered = ['b.fq', 'c.fq'].map((rel) => checkbox('checkbox checkbox-sm upload-opt', { rel }));
const filteredRoot = listRoot(filtered);
ui3.restoreFilePicks(filteredRoot);
assert.deepEqual(filtered.map((node) => [node.getAttribute('data-rel'), node.checked]), [
  ['b.fq', true],
  ['c.fq', true],
]);
assert.equal(names(ui3.checkedInPickOrder(filteredRoot, 'input.upload-opt'), 'data-rel'), 'c.fq,b.fq');

ui3.clearFilePicks();
const job = { getAttribute(name) { return name === 'data-picker-job' ? '9' : name === 'data-picker-shared' ? '0' : null; } };
const results = ['read_1.fq', 'read_2.fq', 'sample.bam'].map((name) => checkbox('checkbox checkbox-sm result-opt', { name }, job));
const resultRoot = listRoot(results);
function pickResult(name) {
  const box = results.find((node) => node.getAttribute('data-name') === name);
  box.checked = true;
  ui3.noteFilePick(box);
}
pickResult('sample.bam');
pickResult('read_2.fq');
pickResult('read_1.fq');
assert.equal(
  names(ui3.checkedInPickOrder(resultRoot, 'input.result-opt'), 'data-name'),
  'sample.bam,read_2.fq,read_1.fq',
);

const otherJob = { getAttribute(name) { return name === 'data-picker-job' ? '4' : '0'; } };
const other = checkbox('checkbox checkbox-sm result-opt', { name: 'sample.bam' }, otherJob);
const otherRoot = listRoot([other]);
ui3.restoreFilePicks(otherRoot);
assert.equal(other.checked, false);

const sameRoot = listRoot([
  checkbox('checkbox checkbox-sm result-opt', { name: 'read_1.fq' }, job),
  checkbox('checkbox checkbox-sm result-opt', { name: 'read_2.fq' }, job),
]);
ui3.restoreFilePicks(sameRoot);
assert.equal(sameRoot.querySelectorAll('input.result-opt')[0].checked, true);
assert.equal(sameRoot.querySelectorAll('input.result-opt')[1].checked, true);
assert.equal(names(ui3.checkedInPickOrder(sameRoot, 'input.result-opt'), 'data-name'), 'read_2.fq,read_1.fq');

console.log('File pickers keep checkbox order across insert and list refresh.');
