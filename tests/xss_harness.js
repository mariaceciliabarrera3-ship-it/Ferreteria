/**
 * FerreGest AR — arnés de pruebas ARQ-01 (XSS almacenado) sobre DOM real.
 *
 * Ejecuta `app/static/app.js` y `app/static/pos.js` dentro de un DOM mínimo
 * implementado en Node (sin dependencias externas) y verifica que los datos
 * hostiles que vienen de la base (descripción de producto, nombre de cliente,
 * código, marca, valor de un input) se inserten como TEXTO y no como HTML.
 *
 * La trampa clave: el DOM del arnés define `innerHTML` como un setter que
 * LANZA un error. Si algún archivo volviera a armar HTML por interpolación,
 * la prueba falla en lugar de pasar por costumbre.
 *
 * Uso:  node tests/js/xss_harness.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const BASE = path.resolve(__dirname, '..', '..');
const PAYLOAD = '<img src=x onerror=alert(1)>';
const PAYLOAD2 = '"><script>alert(2)</script>';

// ------------------------------------------------------------------ DOM mínimo
class TextNode {
  constructor(text) { this.nodeType = 3; this._text = String(text); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
}

class Element {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.value = '';
    this.checked = false;
    this.selected = false;
    this._classes = new Set();
    this._listeners = {};
    this.parentNode = null;
    const self = this;
    this.classList = {
      add: (c) => self._classes.add(c),
      remove: (c) => self._classes.delete(c),
      contains: (c) => self._classes.has(c),
      toggle: (c, on) => {
        if (on === undefined) { self._classes.has(c) ? self._classes.delete(c) : self._classes.add(c); }
        else { on ? self._classes.add(c) : self._classes.delete(c); }
      },
    };
  }
  get className() { return Array.from(this._classes).join(' '); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'class') this.className = v;
    if (k.startsWith('data-')) {
      const camel = k.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
      this.dataset[camel] = String(v);
    }
  }
  getAttribute(k) { return this.attributes[k]; }
  appendChild(node) {
    this.children.push(node);
    if (node && node.nodeType === 1) node.parentNode = this;
    return node;
  }
  remove() {
    if (!this.parentNode) return;
    const i = this.parentNode.children.indexOf(this);
    if (i >= 0) this.parentNode.children.splice(i, 1);
  }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type, extra) {
    const ev = Object.assign({ target: this, preventDefault() {}, type }, extra || {});
    (this._listeners[type] || []).forEach((fn) => fn(ev));
    return ev;
  }
  get textContent() { return this.children.map((c) => c.textContent).join(''); }
  set textContent(v) {
    this.children = [];
    if (v !== '' && v !== null && v !== undefined) this.children.push(new TextNode(v));
  }
  // TRAMPA ARQ-01: si el código vuelve a usar innerHTML, la prueba explota.
  set innerHTML(v) { throw new Error('innerHTML quedó prohibido por ARQ-01'); }
  get innerHTML() { return this.textContent; }
  get childElementCount() { return this.children.filter((c) => c.nodeType === 1).length; }
  contains(node) {
    if (node === this) return true;
    return this.children.some((c) => c.nodeType === 1 && c.contains(node));
  }
  querySelectorAll(selector) {
    const out = [];
    const walk = (node) => {
      node.children.forEach((c) => {
        if (c.nodeType === 1) {
          if (matches(c, selector)) out.push(c);
          walk(c);
        }
      });
    };
    walk(this);
    return out;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function matchesSimple(el, sel) {
  // soporta: tag, .clase, [attr], tag.clase, tag[attr], .a.b
  let m;
  if ((m = sel.match(/^([a-zA-Z0-9]+)/))) {
    if (el.tagName !== m[1].toUpperCase()) return false;
  }
  const cls = sel.match(/\.([-\w]+)/g);
  if (cls) {
    for (const c of cls) {
      if (!el._classes.has(c.slice(1))) return false;
    }
  }
  const attrs = sel.match(/\[([-\w]+)\]/g);
  if (attrs) {
    for (const a of attrs) {
      const name = a.slice(1, -1);
      if (!(name in el.attributes)) return false;
    }
  }
  return true;
}

function matches(el, selector) {
  // soporta selectores descendientes simples ("a b") y listas ("a, b")
  return selector.split(',').some((part) => {
    const chain = part.trim().split(/\s+/).filter(Boolean);
    if (!chain.length) return false;
    if (!matchesSimple(el, chain[chain.length - 1])) return false;
    let node = el.parentNode;
    for (let i = chain.length - 2; i >= 0; i--) {
      let found = false;
      while (node) {
        if (matchesSimple(node, chain[i])) { found = true; node = node.parentNode; break; }
        node = node.parentNode;
      }
      if (!found) return false;
    }
    return true;
  });
}

// ------------------------------------------------------------------ documento
const registry = {};
const IDS = ['global-search', 'global-results', 'pos-results', 'pos-q', 'cart-body',
  't-subtotal', 't-discount', 't-tax', 't-total', 'tax-note', 'pay-amounts',
  'transfer-panel', 'sale-customer', 'sale-notes', 'btn-bill', 'pos-status',
  'tr-bank', 'tr-ref', 'allow-negative'];
IDS.forEach((id) => { registry[id] = new Element(id === 'cart-body' ? 'tbody' : 'div'); });

const meta = new Element('meta');
meta.setAttribute('name', 'csrf-token');
meta.content = 'token-de-prueba';

const document = {
  createElement: (t) => new Element(t),
  createTextNode: (t) => new TextNode(t),
  getElementById: (id) => registry[id] || null,
  querySelector: (sel) => {
    if (sel === 'meta[name="csrf-token"]') return meta;
    if (sel === '#pos-results .pos-item') return registry['pos-results'].querySelector('.pos-item');
    return null;
  },
  querySelectorAll: (sel) => (sel === '.pay-method' ? [] : []),
  addEventListener: (type, fn) => { (document._l = document._l || {})[type] = fn; },
  dispatch: (type, extra) => {
    const ev = Object.assign({ target: document, preventDefault() {}, type }, extra || {});
    const fn = (document._l || {})[type];
    if (fn) fn(ev);
    return ev;
  },
  body: new Element('body'),
};
Object.defineProperty(document, 'innerHTML', { set() { throw new Error('innerHTML prohibido'); } });

// --------------------------------------------------------------- fetch stub
const MAL_PRODUCT = {
  id: 7, code: PAYLOAD2, barcode: '779', description: PAYLOAD, brand: '<b>marca</b>',
  base_unit: 'unidad', default_sale_unit: 'unidad', sale_price: 100, stock: 5,
  units: [{ unit: 'unidad', factor: 1 }],
};
const MAL_CLIENT = { id: 3, name: PAYLOAD, doc: PAYLOAD2 };

const fetchStub = async (url) => {
  if (url.startsWith('/api/buscar')) {
    return { ok: true, json: async () => ({ productos: [MAL_PRODUCT], clientes: [MAL_CLIENT] }) };
  }
  if (url.startsWith('/api/productos')) {
    return { ok: true, json: async () => [MAL_PRODUCT, { ...MAL_PRODUCT, id: 8, code: 'OTRO' }] };
  }
  if (url.startsWith('/api/cotizar')) {
    return { ok: true, json: async () => ({ subtotal: 100, discount: 0, tax: 0, total: 100, tax_lines: [] }) };
  }
  return { ok: false, status: 404, json: async () => ({}) };
};

// --------------------------------------------------------------- ejecución
const sandbox = {
  document, window: {}, console, setTimeout, clearTimeout,
  fetch: fetchStub, Element, TextNode, Math, Number, String, Object, Array, JSON,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const failures = [];
function check(name, cond, detail) {
  if (cond) { console.log('  ok  - ' + name); }
  else { failures.push(name + (detail ? ' :: ' + detail : '')); console.log('  FAIL- ' + name + (detail ? ' :: ' + detail : '')); }
}
function walkElements(node, fn) {
  node.children.forEach((c) => { if (c.nodeType === 1) { fn(c); walkElements(c, fn); } });
}
function hasTag(node, tag) {
  let found = false;
  walkElements(node, (el) => { if (el.tagName === tag.toUpperCase()) found = true; });
  return found;
}

function load(file) {
  const code = fs.readFileSync(path.join(BASE, 'app', 'static', file), 'utf8');
  vm.runInContext(code, sandbox, { filename: file });
}

(async function run() {
  console.log('ARQ-01 — XSS almacenado (arnés DOM en Node)');
  load('app.js');
  load('pos.js');
  document.dispatch('DOMContentLoaded');

  // --- 1) buscador global de la barra superior -----------------------------
  const input = registry['global-search'];
  const box = registry['global-results'];
  input.value = 'ca';
  input.dispatch('input');
  await new Promise((r) => setTimeout(r, 350));
  check('el buscador global muestra el payload como texto',
    box.textContent.includes(PAYLOAD), 'texto obtenido: ' + box.textContent);
  check('el buscador global no crea <img>', !hasTag(box, 'img'));
  check('el buscador global no crea <script>', !hasTag(box, 'script'));
  const strongs = box.querySelectorAll('strong');
  check('la descripción viaja en un <strong> con textContent',
    strongs.length >= 1 && strongs[0].textContent === PAYLOAD,
    strongs.length ? strongs[0].textContent : 'sin <strong>');
  check('el nombre del cliente viaja como texto', box.textContent.includes(PAYLOAD2));

  // --- 2) buscador del POS -------------------------------------------------
  const posBox = registry['pos-results'];
  await sandbox.searchProducts('taladro');
  check('el POS muestra el payload como texto', posBox.textContent.includes(PAYLOAD));
  check('el POS no crea <img>', !hasTag(posBox, 'img'));
  check('el POS no crea <script>', !hasTag(posBox, 'script'));
  const items = posBox.querySelectorAll('.pos-item');
  check('se renderizaron los renglones del POS', items.length === 2, 'n=' + items.length);
  check('el código hostil no generó atributos HTML',
    items.length === 2 && !hasTag(items[0], 'script'));

  // --- 3) carrito ----------------------------------------------------------
  // `cart` es una declaración const: no queda en el objeto global, pero sí en
  // el ámbito léxico del contexto (por eso se accede con runInContext).
  vm.runInContext('cart.length = 0;', sandbox);
  sandbox.addToCart(MAL_PRODUCT);
  const body = registry['cart-body'];
  check('el carrito muestra la descripción como texto', body.textContent.includes(PAYLOAD));
  check('el carrito no crea <img>', !hasTag(body, 'img'));
  const celdas = body.querySelectorAll('td');
  check('la primera celda del renglón es texto plano',
    celdas.length > 0 && celdas[0].textContent === PAYLOAD,
    celdas.length ? celdas[0].textContent : 'sin celdas');

  // --- 4) importes de pago (valor escrito por el usuario) ------------------
  registry['pay-amounts'].textContent = '';
  const previo = new Element('input');
  previo.setAttribute('data-pm', 'efectivo');
  previo.value = PAYLOAD2;
  registry['pay-amounts'].appendChild(previo);
  sandbox.renderPayAmounts(150);
  const payBox = registry['pay-amounts'];
  check('el valor del medio de pago se conserva como valor, no como HTML',
    payBox.querySelectorAll('input').length === 1 &&
    payBox.querySelectorAll('input')[0].value === PAYLOAD2,
    JSON.stringify(payBox.querySelectorAll('input').map((i) => i.value)));
  check('los medios de pago no crean <script>', !hasTag(payBox, 'script'));

  // --- 5) helpers disponibles ---------------------------------------------
  check('escapeHtml escapa & < > " \'',
    sandbox.escapeHtml('<b>&"\'</b>') === '&lt;b&gt;&amp;&quot;&#39;&lt;/b&gt;',
    sandbox.escapeHtml('<b>&"\'</b>'));

  if (failures.length) {
    console.log('\nRESULTADO: FIX — ' + failures.length + ' comprobación(es) fallaron.');
    process.exit(1);
  }
  console.log('\nRESULTADO: CONTINUE — ningún dato de la base se interpreta como HTML.');
  process.exit(0);
})().catch((e) => {
  console.log('\nRESULTADO: FIX — excepción en el arnés: ' + e.message);
  console.log(e.stack);
  process.exit(1);
});
