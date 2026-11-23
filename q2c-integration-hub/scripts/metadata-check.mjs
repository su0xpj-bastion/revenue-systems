// Org-free metadata checks:
//  1. Every *-meta.xml is well-formed XML.
//  2. Every custom name used in Apex or LWC (Foo__c, Foo__e, Foo__r, Object.Field__c) exists in
//     force-app/main/default/objects. A typo'd field otherwise only shows up at deploy time.
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, basename } from 'node:path';
import { XMLValidator } from 'fast-xml-parser';

const ROOT = 'force-app/main/default';

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const files = walk(ROOT);
let failed = 0;

for (const f of files.filter((p) => p.endsWith('.xml'))) {
  const res = XMLValidator.validate(readFileSync(f, 'utf8'));
  if (res !== true) {
    failed++;
    console.log(`✖ ${f}: ${res.err.msg} (line ${res.err.line})`);
  }
}

const objects = new Set(readdirSync(join(ROOT, 'objects')));
const fields = new Set();
const relationships = new Set();
for (const obj of objects) {
  const dir = join(ROOT, 'objects', obj, 'fields');
  if (!existsSync(dir)) continue;
  for (const f of readdirSync(dir)) {
    const api = f.replace('.field-meta.xml', '');
    fields.add(`${obj}.${api}`);
    fields.add(api);
    const rel = readFileSync(join(dir, f), 'utf8').match(/<relationshipName>(\w+)<\/relationshipName>/);
    if (rel) relationships.add(`${rel[1]}__r`);
  }
}

const code = files.filter((p) => /\.(cls|trigger|js|html)$/.test(p) && !p.includes('__tests__'));
const used = new Map();
for (const f of code) {
  const src = readFileSync(f, 'utf8');
  for (const m of src.matchAll(/\b([A-Z][A-Za-z0-9_]*?__[cer])\b(?:\.([A-Z][A-Za-z0-9_]*__c)\b)?/g)) {
    const [, name, child] = m;
    const key = child ? `${name}.${child}` : name;
    if (!used.has(key)) used.set(key, basename(f));
  }
}

let unknown = 0;
for (const [name, where] of used) {
  const [head, child] = name.split('.');
  let ok;
  if (head.endsWith('__r')) ok = relationships.has(head);
  else if (child) ok = objects.has(head) && fields.has(name);
  else ok = objects.has(head) || fields.has(head);
  if (!ok) {
    unknown++;
    console.log(`✖ ${name} (used in ${where}) is not defined in ${ROOT}/objects`);
  }
}

console.log(`${files.filter((p) => p.endsWith('.xml')).length} metadata files parsed; ${used.size} custom names checked; ${unknown} unknown`);
process.exit(failed || unknown ? 1 : 0);
