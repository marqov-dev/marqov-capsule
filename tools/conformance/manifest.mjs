// Internal manifest corpus reader, not a production capsule verifier.
import assert from 'node:assert/strict';
import { isMap, isScalar, parseDocument, visit, Parser } from 'yaml';

export const decode = bytes => new TextDecoder('utf-8', { fatal: true }).decode(bytes);

// Section 5: only the core tags may appear explicitly, and an explicitly
// tagged scalar is held to the same spelling the implicit rule accepts.
const CORE = 'tag:yaml.org,2002:';
const CORE_TAGS = new Set(['str', 'int', 'float', 'bool', 'null', 'map', 'seq'].map(t => CORE + t));
const INT = /^[-+]?[0-9]+$/;
const FLOAT = /^[-+]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[0-9]+[eE][-+]?[0-9]+)$/;

function checkTag(node) {
  if (!node.tag) return;
  assert(CORE_TAGS.has(node.tag), `tag outside the core set: ${node.tag}`);
  if (!isScalar(node)) return;
  const source = node.source ?? '';
  if (node.tag === CORE + 'int') {
    assert(INT.test(source), `not a decimal integer: ${source}`);
    node.value = BigInt(source);
  } else if (node.tag === CORE + 'float') {
    // The library resolves an explicit !!float through its .nan/.inf tag;
    // resolve it here from the source text instead.
    assert(FLOAT.test(source) || INT.test(source), `not a finite decimal float: ${source}`);
    node.value = Number(source);
  }
}

// Keep tabs in quoted and block-scalar content, but refuse syntax/plain
// tabs that PyYAML cannot parse. CST tokens distinguish these from comments.
function checkTokens(token) {
  if (!token || typeof token !== 'object') return;
  if (['space', 'scalar', 'directive'].includes(token.type)) {
    assert(!token.source.includes('\t'), 'tab in manifest syntax or plain scalar');
  }
  for (const value of Object.values(token)) {
    if (Array.isArray(value)) value.forEach(checkTokens);
    else if (value && typeof value === 'object') checkTokens(value);
  }
}

function checkEscapes(node) {
  if (!isScalar(node) || node.type !== 'QUOTE_DOUBLE') return;
  // Match complete escapes so a literal backslash before "uD800" is not
  // mistaken for an escaped surrogate. Python does not join surrogate escapes;
  // encode the Unicode scalar as a literal or \U0001F600 instead.
  const raw = node.srcToken.source;
  for (const match of raw.matchAll(/\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|[\s\S])/g)) {
    if (match[1] || match[2]) {
      const code = parseInt(match[1] ?? match[2], 16);
      assert(code < 0xd800 || code > 0xdfff, 'surrogate escape is not a Unicode scalar');
    }
  }
}

export function parse(text) {
  assert(!/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff\ufffe\uffff]/u.test(text),
    'forbidden raw manifest character; use a scalar escape');
  text = text.replace(/\r\n?/g, '\n');
  const document = parseDocument(text, {
    schema: 'core', intAsBigInt: true, uniqueKeys: true, keepSourceTokens: true,
    // Capsule's JSON-aligned profile leaves hex/octal and untagged .nan/.inf
    // as strings. Retain explicit YAML tags so nonfinite numbers are rejected.
    customTags: tags => tags.map(tag =>
      (tag.tag === 'tag:yaml.org,2002:int' && tag.format) ||
      (tag.tag === 'tag:yaml.org,2002:float' && tag.test?.test('.nan'))
        ? { ...tag, default: false } : tag),
  });
  assert.equal(document.errors.length, 0, document.errors.map(e => e.message).join('; '));
  assert.equal(document.warnings.length, 0, document.warnings.map(e => e.message).join('; '));
  assert(isMap(document.contents), 'a manifest must be a single mapping');
  let yamlDirective = false;
  const tagHandles = new Set();
  for (const token of new Parser().parse(text)) {
    checkTokens(token);
    if (token.type === 'directive') {
      const [name, argument] = token.source.trim().split(/ +/);
      if (name === '%YAML') {
        assert(!yamlDirective, 'duplicate YAML directive');
        yamlDirective = true;
      } else if (name === '%TAG') {
        assert(!tagHandles.has(argument), 'duplicate TAG handle');
        tagHandles.add(argument);
      }
    }
  }
  visit(document, { Node: (_key, node) => { checkTag(node); checkEscapes(node); } });
  return document.toJS({ mapAsMap: true, maxAliasCount: 0 });
}

// A string with an unpaired surrogate is not Unicode text and has no UTF-8 form.
const wellFormed = text => !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(text);

export function canonical(value) {
  if (value instanceof Map) {
    const entries = new Map();
    for (const [key, item] of value) {
      assert.equal(typeof key, 'string', 'non-string manifest key');
      assert(wellFormed(key), 'unpaired surrogate');
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
  if (typeof value === 'string') {
    assert(wellFormed(value), 'unpaired surrogate');
    value = value.normalize('NFC');
  }
  assert(value === null || ['string', 'number', 'boolean'].includes(typeof value), 'non-JSON value');
  return JSON.stringify(value); // ECMAScript number spelling, including -0 -> 0
}
