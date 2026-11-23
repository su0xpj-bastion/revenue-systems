// The Apex static resource must be byte-identical to vectors/pricing-vectors.json.
import { readFileSync } from 'node:fs';
const a = readFileSync('vectors/pricing-vectors.json');
const b = readFileSync('force-app-core/main/default/staticresources/PricingVectors.json');
if (!a.equals(b)) { console.error('PricingVectors static resource is out of sync with vectors/pricing-vectors.json'); process.exit(1); }
console.log('vectors in sync');
