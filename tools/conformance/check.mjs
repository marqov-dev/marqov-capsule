// Independent checks of the published corpus, not a production capsule reader.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseDocument } from 'yaml';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../spec/v1/conformance');
const golden = resolve(root, 'golden');
const readJSON = path => JSON.parse(readFileSync(path, 'utf8'));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

function parse(text) {
  const document = parseDocument(text, {
    schema: 'core', intAsBigInt: true, uniqueKeys: true,
    // Capsule's JSON-aligned profile leaves hex/octal and untagged .nan/.inf
    // as strings. Retain explicit YAML tags so nonfinite numbers are rejected.
    customTags: tags => tags.map(tag =>
      (tag.tag === 'tag:yaml.org,2002:int' && tag.format) ||
      (tag.tag === 'tag:yaml.org,2002:float' && tag.test?.test('.nan'))
        ? { ...tag, default: false } : tag),
  });
  assert.equal(document.errors.length, 0, document.errors.map(e => e.message).join('; '));
  assert.equal(document.warnings.length, 0, document.warnings.map(e => e.message).join('; '));
  return document.toJS({ mapAsMap: true, maxAliasCount: 0 });
}

function canonical(value) {
  if (value instanceof Map) {
    const entries = new Map();
    for (const [key, item] of value) {
      assert.equal(typeof key, 'string', 'non-string manifest key');
      const normalized = key.normalize('NFC');
      assert(!entries.has(normalized), 'NFC key collision');
      entries.set(normalized, item);
    }
    // JS string sort compares UTF-16 code units. Serialize directly: object
    // property enumeration would reorder integer-looking keys numerically.
    return '{' + [...entries.keys()].sort().map(key =>
      JSON.stringify(key) + ':' + canonical(entries.get(key))).join(',') + '}';
  }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (typeof value === 'bigint') {
    assert(value >= -9007199254740991n && value <= 9007199254740991n, 'unsafe integer');
    return value.toString();
  }
  if (typeof value === 'number') assert(Number.isFinite(value), 'nonfinite number');
  if (typeof value === 'string') value = value.normalize('NFC');
  assert(value === null || ['string', 'number', 'boolean'].includes(typeof value), 'non-JSON value');
  return JSON.stringify(value); // ECMAScript number spelling, including -0 -> 0
}

function encodedPath(path) {
  return path.normalize('NFC').replaceAll('%', '%25').replaceAll('\\', '%5C')
    .replaceAll('\n', '%0A').replaceAll('\r', '%0D');
}
function checksums(files) {
  return files.map(({ path, bytes }) => ({ path: encodedPath(path), hash: digest(bytes) }))
    .sort((a, b) => Buffer.compare(Buffer.from(a.path), Buffer.from(b.path)))
    .map(({ path, hash }) => `sha256:${hash}  ${path}\n`).join('');
}
function payloadFiles(directory, current = directory) {
  return readdirSync(current, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(current, entry.name);
    if (entry.isDirectory()) return payloadFiles(directory, path);
    assert(entry.isFile(), 'corpus must contain only regular files');
    const name = relative(directory, path).split(sep).join('/');
    if (['capsule.yaml', '.checksums'].includes(name)) return [];
    return [{ path: name, bytes: readFileSync(path) }];
  });
}

let checked = 0;
for (const vector of readJSON(resolve(golden, 'expected.json'))) {
  const directory = resolve(root, vector.fixture);
  const manifest = parse(readFileSync(resolve(directory, 'capsule.yaml'), 'utf8'));
  const bytes = canonical(manifest);
  assert.equal(bytes, readFileSync(resolve(golden, vector.canonical_file), 'utf8'), vector.fixture);
  assert.equal('mqc:1:' + digest(bytes), vector.capsule_id, vector.fixture);
  if (vector.checksums_digest !== null) {
    const actual = readFileSync(resolve(directory, '.checksums'), 'utf8');
    assert.equal(checksums(payloadFiles(directory)), actual, vector.fixture + ' payload/checksum bytes');
    assert.equal('sha256:' + digest(actual), vector.checksums_digest);
    assert.equal(manifest.get('checksums_digest'), vector.checksums_digest);
  }
  checked++;
}
for (const vector of readJSON(resolve(golden, 'canonical-edge-cases.json'))) {
  if (vector.reject) assert.throws(() => canonical(parse(vector.yaml)), undefined, vector.name);
  else {
    const bytes = canonical(parse(vector.yaml));
    assert.equal(bytes, vector.canonical_utf8, vector.name);
    assert.equal('mqc:1:' + digest(bytes), vector.capsule_id, vector.name);
  }
  checked++;
}
for (const vector of readJSON(resolve(golden, 'checksum-path-cases.json'))) {
  const actual = checksums(vector.files.map(file => ({ path: file.path, bytes: Buffer.from(file.utf8) })));
  assert.equal(actual, vector.checksums_utf8, vector.name);
  assert.equal('sha256:' + digest(actual), vector.checksums_digest, vector.name);
  checked++;
}
console.log(`PASS: ${checked} independent Node/YAML canonicalization and checksum vectors`);
