// Parse every Apex class and trigger with the open-source Apex grammar.
// Catches syntax errors without an org. It does NOT resolve types: custom objects, fields and platform types
// are only checked by a real compile in a CPQ-enabled org.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { ApexErrorListener, ApexParserFactory } from '@apexdevtools/apex-parser';

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (name.endsWith('.cls') || name.endsWith('.trigger')) out.push(path);
  }
  return out;
}

class Collect extends ApexErrorListener {
  constructor() { super(); this.errors = []; }
  apexSyntaxError(line, column, msg) { this.errors.push(`${line}:${column} ${msg}`); }
}

let failed = 0;
const files = ["force-app"].flatMap((d) => walk(d));
for (const file of files) {
  const listener = new Collect();
  const { parser } = ApexParserFactory.createLexerAndParser(readFileSync(file, 'utf8'), listener);
  if (file.endsWith('.trigger')) parser.triggerUnit(); else parser.compilationUnit();
  if (listener.errors.length) {
    failed++;
    console.log(`✖ ${file}`);
    listener.errors.forEach((e) => console.log(`    ${e}`));
  } else {
    console.log(`✔ ${file}`);
  }
}
console.log(`\n${files.length - failed}/${files.length} Apex files parse`);
process.exit(failed ? 1 : 0);
