// Punto de venta FerreGest AR
//
// ARQ-01 (XSS almacenado): este archivo construía el listado de productos, el
// carrito y los medios de pago concatenando datos de la base dentro de
// `innerHTML`. Una descripción como `<img src=x onerror=alert(1)>` se guardaba
// en el producto y se ejecutaba en el navegador de quien vendiera. Ahora todo
// se arma con nodos DOM y `textContent` (helpers `el()` y `escapeHtml()` de
// app.js). La lógica de búsqueda, el diseño y los `data-*` no cambian.
const cart = [];   // {product_id, description, unit, units:[{unit,factor}], qty, unit_price, discount}
let totals = {subtotal:0, discount:0, tax:0, total:0};
const selMethods = new Set(['efectivo']);
const PAY_NAMES = {efectivo:'Efectivo',transferencia:'Transferencia',debito:'Débito',
                   credito:'Crédito',cuenta_corriente:'Cuenta corriente'};

function findProduct(id){ return window.PRODUCT_CACHE.find(p=>p.id===id); }

async function searchProducts(q){
  const box = document.getElementById('pos-results');
  if(!q || q.trim().length < 1){ box.textContent=''; return; }
  try{
    const res = await fetch('/api/productos?q=' + encodeURIComponent(q.trim()));
    const rows = await res.json();
    window.PRODUCT_CACHE = rows;
    if(rows.length === 1 && (rows[0].code === q.trim() || rows[0].barcode === q.trim())){
      addToCart(rows[0]); document.getElementById('pos-q').value=''; box.textContent=''; return;
    }
    box.textContent = '';
    if(!rows.length){
      box.appendChild(el('div', {class:'empty'}, 'Sin resultados'));
      return;
    }
    rows.forEach(p=>{
      const meta = document.createElement('span');
      meta.className = 'code';
      meta.textContent = p.code + (p.barcode ? ' · ' + p.barcode : '') + (p.brand ? ' · ' + p.brand : '');
      const left = el('div', null, el('strong', null, p.description), document.createElement('br'), meta);
      const right = el('div', {class:'stock right'},
        document.createTextNode(moneyAR(p.sale_price)),
        document.createElement('br'),
        document.createTextNode('stock ' + qtyAR(p.stock) + ' ' + p.base_unit));
      const item = el('div', {class:'pos-item', 'data-id': p.id}, left, right);
      item.addEventListener('click', ()=>{
        addToCart(p);
        document.getElementById('pos-q').value=''; box.textContent='';
        document.getElementById('pos-q').focus();
      });
      box.appendChild(item);
    });
  }catch(e){ toast('Error buscando productos: '+e.message, true); }
}

function addToCart(p){
  const defUnit = p.default_sale_unit || p.base_unit;
  const existing = cart.find(l=>l.product_id===p.id && l.unit===defUnit);
  if(existing){ existing.qty = round4(existing.qty + 1); renderCart(); return; }
  cart.push({
    product_id: p.id, description: p.description, unit: defUnit,
    units: p.units, qty: 1,
    unit_price: Number(p.sale_price), discount: 0
  });
  renderCart();
}
function round4(x){ return Math.round(x*10000)/10000; }

function renderCart(){
  const body = document.getElementById('cart-body');
  if(!cart.length){
    body.textContent = '';
    const td = el('td', {colspan: '7', class: 'empty'}, 'Agregue productos con el buscador.');
    body.appendChild(el('tr', null, td));
    quote(); return;
  }
  body.textContent = '';
  cart.forEach((l,i)=>{
    const select = el('select', {'data-i': i, 'data-f': 'unit'});
    (l.units || []).forEach(u=>{
      const opt = el('option', {value: u.unit}, u.unit);
      if(u.unit === l.unit) opt.selected = true;
      select.appendChild(opt);
    });
    const tr = el('tr', null,
      el('td', null, l.description),                                  // texto plano
      el('td', null, select),
      el('td', {class:'num'}, el('input', {class:'qty-input', 'data-i': i,
        'data-f':'qty', inputmode:'decimal', value: l.qty})),
      el('td', {class:'num'}, el('input', {class:'price-input', 'data-i': i,
        'data-f':'unit_price', inputmode:'decimal', value: l.unit_price})),
      el('td', {class:'num'}, el('input', {class:'price-input', 'data-i': i,
        'data-f':'discount', inputmode:'decimal', value: l.discount})),
      el('td', {class:'num', 'data-sub': i}, moneyAR(l.qty*l.unit_price - l.discount)),
      el('td', null, el('button', {class:'btn sm danger', 'data-del': i,
        type:'button', title:'Quitar'}, '✕'))
    );
    body.appendChild(tr);
  });
  body.querySelectorAll('input,select').forEach(element=>{
    element.addEventListener('change', ()=>{
      const i = Number(element.dataset.i), f = element.dataset.f;
      let v = element.value.replace(',','.');
      if(f==='unit'){ cart[i].unit = v; }
      else { v = Math.max(0, Number(v)||0); cart[i][f] = f==='qty' ? round4(v) : v; }
      renderCart();
    });
  });
  body.querySelectorAll('[data-del]').forEach(element=>{
    element.addEventListener('click', ()=>{ cart.splice(Number(element.dataset.del),1); renderCart(); });
  });
  quote();
}

async function quote(){
  if(!cart.length){
    totals = {subtotal:0,discount:0,tax:0,total:0};
    document.getElementById('t-subtotal').textContent = moneyAR(0);
    document.getElementById('t-discount').textContent = '-'+moneyAR(0);
    document.getElementById('t-tax').textContent = moneyAR(0);
    document.getElementById('t-total').textContent = moneyAR(0);
    renderPayAmounts(0); return;
  }
  try{
    const data = await apiPost('/api/cotizar', {items: cart});
    totals = data;
    document.getElementById('t-subtotal').textContent = moneyAR(data.subtotal);
    document.getElementById('t-discount').textContent = '-'+moneyAR(data.discount);
    document.getElementById('t-tax').textContent = moneyAR(data.tax);
    document.getElementById('t-total').textContent = moneyAR(data.total);
    const note = document.getElementById('tax-note');
    note.textContent = data.tax_lines && data.tax_lines.length
      ? 'Impuestos: ' + data.tax_lines.join(' · ')
      : 'Sin impuestos configurados (o todos inactivos).';
    renderPayAmounts(data.total);
  }catch(e){ /* cotización opcional */ }
}

function renderPayAmounts(total){
  const box = document.getElementById('pay-amounts');
  const methods = [...selMethods];
  if(!methods.length){ box.textContent=''; return; }
  const prev = {};
  box.querySelectorAll('[data-pm]').forEach(element=>{ prev[element.dataset.pm] = element.value; });
  box.textContent = '';
  methods.forEach((m,i)=>{
    const def = prev[m] !== undefined ? prev[m] : (i===0 ? total.toFixed(2) : '');
    // `value` se asigna por propiedad: aunque el usuario escriba comillas o
    // etiquetas, el navegador lo trata como texto y no como HTML.
    const input = el('input', {inputmode:'decimal', placeholder:'0,00', 'data-pm': m});
    input.value = def;
    box.appendChild(el('label', null, document.createTextNode(PAY_NAMES[m] + ' '), input));
  });
}

document.addEventListener('DOMContentLoaded', ()=>{
  window.PRODUCT_CACHE = [];
  const q = document.getElementById('pos-q');
  let t=null;
  q.addEventListener('input', ()=>{ clearTimeout(t); t=setTimeout(()=>searchProducts(q.value),180); });
  q.addEventListener('keydown', e=>{
    if(e.key==='Enter'){
      e.preventDefault();
      const first = document.querySelector('#pos-results .pos-item');
      if(first) first.click();
      else searchProducts(q.value);
    }
  });
  document.querySelectorAll('.pay-method').forEach(element=>{
    element.addEventListener('click', ()=>{
      const m = element.dataset.method;
      if(selMethods.has(m)) selMethods.delete(m); else selMethods.add(m);
      element.classList.toggle('on', selMethods.has(m));
      document.getElementById('transfer-panel').classList.toggle('hidden', !selMethods.has('transferencia'));
      renderPayAmounts(totals.total);
    });
  });
  document.getElementById('btn-bill').addEventListener('click', bill);
  quote();
});

async function bill(){
  const status = document.getElementById('pos-status');
  status.textContent = 'Procesando…';
  if(!cart.length){ status.textContent=''; toast('El carrito está vacío.', true); return; }
  const payments = [];
  const inputs = document.querySelectorAll('#pay-amounts [data-pm]');
  if(!inputs.length){ status.textContent=''; toast('Seleccione al menos un medio de pago.', true); return; }
  for(const element of inputs){
    const amount = Number((element.value||'0').replace(',','.'));
    if(!(amount > 0)){ status.textContent=''; toast('Complete los importes de pago.', true); return; }
    const method = element.dataset.pm;
    const pay = {method, amount: Math.round(amount*100)/100};
    if(method === 'transferencia'){
      pay.transfer = {
        bank: document.getElementById('tr-bank').value,
        reference: document.getElementById('tr-ref').value.trim(),
        informed: document.getElementById('tr-informed').checked,
        notes: ''
      };
    }
    payments.push(pay);
  }
  const payload = {
    customer_id: document.getElementById('sale-customer').value
      ? Number(document.getElementById('sale-customer').value) : null,
    items: cart.map(l=>({product_id:l.product_id, unit:l.unit, qty:l.qty,
                         unit_price:l.unit_price, discount:l.discount})),
    payments,
    notes: document.getElementById('sale-notes').value.trim(),
    allow_negative: document.getElementById('allow-negative').checked
  };
  try{
    const res = await apiPost('/api/ventas', payload);
    window.location.href = '/ventas/' + res.id + '?nueva=1';
  }catch(e){
    status.textContent = '';
    toast(e.message, true);
  }
}
