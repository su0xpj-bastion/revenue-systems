// The Apex tests read the SyncVectors static resource; Python reads vectors/sync-vectors.json.
// They must be byte-identical or the two runtimes could pass against different rules.
import { readFileSync } from 'node:fs';

const a = readFileSync('vectors/sync-vectors.json', 'utf8');
const b = readFileSync('force-app/main/default/staticresources/SyncVectors.json', 'utf8');
if (a !== b) {
  console.error('✖ vectors/sync-vectors.json and the SyncVectors static resource differ. Copy one over the other.');
  process.exit(1);
}
console.log('✔ vectors in sync');
