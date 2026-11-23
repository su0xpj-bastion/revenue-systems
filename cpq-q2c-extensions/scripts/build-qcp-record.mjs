// Writes the SBQQ__CustomScript__c record for the QCP as an `sf data import tree` file.
// CPQ runs the code as-is (no bundling), so `export` keywords are kept: CPQ's QCP loader expects ES module exports.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { LINE_FIELDS, QUOTE_FIELDS } from '../qcp/src/quote-calculator-plugin.js';

const code = readFileSync(new URL('../qcp/src/quote-calculator-plugin.js', import.meta.url), 'utf8');
mkdirSync('build', { recursive: true });
writeFileSync('build/qcp-record.json', JSON.stringify({
  records: [{
    attributes: { type: 'SBQQ__CustomScript__c', referenceId: 'QcpRef' },
    Name: 'Q2C Quote Calculator Plugin',
    SBQQ__Code__c: code,
    SBQQ__QuoteFields__c: QUOTE_FIELDS.join('\n'),
    SBQQ__QuoteLineFields__c: LINE_FIELDS.join('\n'),
  }],
}, null, 2));
console.log(`build/qcp-record.json: ${code.length} chars, ${QUOTE_FIELDS.length} quote fields, ${LINE_FIELDS.length} line fields`);
console.log('Load:  sf data import tree --files build/qcp-record.json --target-org <cpq-org>');
console.log('Then:  CPQ Settings → Plugins → Quote Calculator Plugin = "Q2C Quote Calculator Plugin"');
