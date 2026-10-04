// Run with: node ui3/tests/parameter_scaffold.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(
  path.join(__dirname, '../templates/ui3/jobs/_parameter_scaffold.html'), 'utf8'
).split('<script>')[1].split('</script>')[0];
const field = {value: ''};
const context = {document: {getElementById: () => field}};
function refresh(value, force = false) {
  const script = template
    .replace('"{{ value|escapejs }}"', JSON.stringify(value))
    .replace('{{ force|yesno:"true,false" }}', String(force));
  vm.runInNewContext(script, context);
}

refresh('UMI_LEN1=6;ADAPT1_1=ACGT;REQUIRED=;', true);
assert.equal(field.value, 'UMI_LEN1=6;ADAPT1_1=ACGT;REQUIRED=;');
field.value = 'UMI_LEN1=8;ADAPT1_1=ACGT;REQUIRED=/index;CUSTOM=a=b;';
const twoSamples = 'UMI_LEN1=6;ADAPT1_1=ACGT;REQUIRED=;UMI_LEN2=6;ADAPT2_1=TGCA;';
refresh(twoSamples);
assert.equal(field.value, 'UMI_LEN1=8;ADAPT1_1=ACGT;REQUIRED=/index;CUSTOM=a=b;UMI_LEN2=6;ADAPT2_1=TGCA;');
refresh(twoSamples);
assert.equal((field.value.match(/UMI_LEN2=/g) || []).length, 1);

// A sample field override/removal removes only untouched generated entries.
field.value = field.value.replace('ADAPT2_1=TGCA;', 'ADAPT2_1=USER;');
refresh('UMI_LEN1=6;ADAPT1_1=NEW;REQUIRED=;');
assert.equal(field.value, 'UMI_LEN1=8;ADAPT1_1=NEW;REQUIRED=/index;CUSTOM=a=b;ADAPT2_1=USER;');

// A deliberately cleared value remains empty, so the runner can use defaults.
field.value = field.value.replace('UMI_LEN1=8;', 'UMI_LEN1=;');
refresh('UMI_LEN1=6;ADAPT1_1=NEW;REQUIRED=;');
assert.ok(field.value.startsWith('UMI_LEN1=;'));
refresh('EXPR=a=b;ZERO=0;', true);
assert.equal(field.value, 'EXPR=a=b;ZERO=0;');
refresh('EXPR=a=b;ZERO=0;OTHER=x=y;');
assert.equal(field.value, 'EXPR=a=b;ZERO=0;OTHER=x=y;');
console.log('Parameter scaffold: defaults, overrides, sample changes, and protocol switching pass.');
