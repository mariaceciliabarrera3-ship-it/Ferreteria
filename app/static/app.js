// FerreGest AR — utilidades compartidas
//
// ARQ-01 (XSS almacenado): los datos que vienen de la base (nombres de
// productos, clientes, códigos, marcas) se insertan como TEXTO, nunca como
// HTML. Dos herramientas:
//   * escapeHtml(s)  -> convierte & < > " ' en entidades (para los pocos casos
//                       donde todavía haga falta armar un string de HTML).
//   * el(tag, attrs, ...hijos) -> crea nodos con textContent (lo preferido).
// Queda prohibido concatenar datos de la base dentro de innerHTML.

const HTML_ESCAPES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};

function escapeHtml(value){
  return String(value === null || value === undefined ? '' : value)
    .replace(/[&<>"']/g, c => HTML_ESCAPES[c]);
}

/**
 * Crea un elemento de forma segura.
 * el('div', {class:'pos-item', 'data-id': 7}, 'texto', nodo)
 * Los atributos se asignan con setAttribute (nunca se interpola HTML) y los
 * hijos de tipo string se insertan con textContent.
 */
function el(tag, attrs, ...children){
  const node = document.createElement(tag);
  if(attrs){
    for(const [k, v] of Object.entries(attrs)){
      if(v === null || v === undefined || v === false) continue;
      node.setAttribute(k, String(v));
    }
  }
  for(const child of children){
    if(child === null || child === undefined) continue;
    node.appendChild(typeof child === 'string' || typeof child === 'number'
      ? document.createTextNode(String(child))
      : child);
  }
  return node;
}

function csrfToken(){
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.content : '';
}
async function apiPost(url, data){
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type':'application/json','X-CSRF-Token': csrfToken()},
    body: JSON.stringify(data || {})
  });
  const body = await res.json().catch(()=>({}));
  if(!res.ok){ throw new Error(body.error || ('Error ' + res.status)); }
  return body;
}
function moneyAR(v){
  const n = Number(v||0);
  return '$ ' + n.toLocaleString('es-AR',{minimumFractionDigits:2, maximumFractionDigits:2});
}
function qtyAR(v){
  const n = Number(v||0);
  if(Number.isInteger(n)) return String(n);
  return n.toLocaleString('es-AR',{maximumFractionDigits:4});
}
function toast(msg, isErr){
  let elm = document.createElement('div');
  elm.className = 'flash ' + (isErr ? 'flash-error' : 'flash-ok');
  elm.style.position='fixed'; elm.style.bottom='18px'; elm.style.right='18px';
  elm.style.zIndex='99'; elm.style.maxWidth='380px'; elm.style.boxShadow='0 8px 30px rgba(0,0,0,.2)';
  elm.textContent = msg;
  document.body.appendChild(elm);
  setTimeout(()=>elm.remove(), 4200);
}

// Búsqueda global (barra superior) — resultados construidos con nodos DOM.
(function(){
  const input = document.getElementById('global-search');
  const box = document.getElementById('global-results');
  if(!input) return;
  let t = null;

  function clearBox(){
    box.textContent = '';
    box.classList.add('hidden');
  }

  function resultRow(href, icon, strongText, restText){
    const a = el('a', {href});
    a.appendChild(document.createTextNode(icon + ' '));
    a.appendChild(el('strong', null, strongText));   // textContent: nunca ejecuta HTML
    if(restText) a.appendChild(document.createTextNode(' ' + restText));
    return a;
  }

  input.addEventListener('input', ()=>{
    clearTimeout(t);
    const q = input.value.trim();
    if(q.length < 2){ box.classList.add('hidden'); return; }
    t = setTimeout(async ()=>{
      try{
        const res = await fetch('/api/buscar?q=' + encodeURIComponent(q));
        const data = await res.json();
        box.textContent = '';                       // limpia sin interpretar HTML
        (data.productos || []).forEach(p=>{
          box.appendChild(resultRow(
            '/productos?q=' + encodeURIComponent(p.code),
            '\u{1F4E6}',
            p.description,
            '\u00B7 ' + p.code + ' \u00B7 stock ' + qtyAR(p.stock) + ' ' + p.base_unit));
        });
        (data.clientes || []).forEach(c=>{
          box.appendChild(resultRow('/clientes/' + c.id, '\u{1F464}',
                                    c.name, c.doc || ''));
        });
        if(!box.childElementCount){
          box.appendChild(el('a', {href: '#'}, 'Sin resultados'));
        }
        box.classList.remove('hidden');
      }catch(e){ /* la búsqueda es secundaria: no interrumpe la navegación */ }
    }, 220);
  });
  document.addEventListener('click', e=>{
    if(!box.contains(e.target) && e.target !== input) box.classList.add('hidden');
  });
})();
