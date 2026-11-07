-- FerreGest AR — Migración inicial (SQLite)
-- Todas las cantidades son REALES (admiten fracciones). Los importes se guardan
-- redondeados a 2 decimales desde la capa de servicio.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'vendedor',
  active INTEGER NOT NULL DEFAULT 1,
  perms TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS units (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  allows_fraction INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  cuit TEXT NOT NULL DEFAULT '',
  contact TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  payment_terms TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  doc TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  credit_limit REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taxes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  rate REAL NOT NULL,
  mode TEXT NOT NULL DEFAULT 'agregado',      -- 'agregado' | 'incluido'
  scope TEXT NOT NULL DEFAULT 'global',       -- 'global' | 'categoria' | 'producto'
  category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  active INTEGER NOT NULL DEFAULT 0,
  valid_from TEXT,
  valid_to TEXT,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  barcode TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL,
  brand TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id),
  supplier_id INTEGER REFERENCES suppliers(id),
  base_unit TEXT NOT NULL DEFAULT 'unidad',
  default_sale_unit TEXT NOT NULL DEFAULT 'unidad',
  cost_price REAL NOT NULL DEFAULT 0,
  avg_cost REAL NOT NULL DEFAULT 0,
  sale_price REAL NOT NULL DEFAULT 0,
  wholesale_price REAL NOT NULL DEFAULT 0,
  special_price REAL NOT NULL DEFAULT 0,
  stock REAL NOT NULL DEFAULT 0,
  stock_min REAL NOT NULL DEFAULT 0,
  stock_max REAL NOT NULL DEFAULT 0,
  location TEXT NOT NULL DEFAULT '',
  last_purchase_date TEXT,
  updated_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT NOT NULL DEFAULT '',
  tax_id INTEGER REFERENCES taxes(id)
);

CREATE TABLE IF NOT EXISTS unit_conversions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  unit TEXT NOT NULL,
  factor REAL NOT NULL,
  UNIQUE (product_id, unit)
);

CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  old_value REAL NOT NULL,
  new_value REAL NOT NULL,
  user_id INTEGER,
  changed_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS stock_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  datetime TEXT NOT NULL,
  type TEXT NOT NULL,             -- inventario_inicial, compra, venta, devolucion, anulacion, ajuste, rotura, perdida, inventario
  qty REAL NOT NULL,              -- delta con signo en unidades base
  stock_after REAL NOT NULL,
  user_id INTEGER,
  reason TEXT NOT NULL DEFAULT '',
  ref_type TEXT NOT NULL DEFAULT '',
  ref_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sm_product ON stock_movements(product_id, datetime);

CREATE TABLE IF NOT EXISTS transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER REFERENCES sales(id) ON DELETE SET NULL,
  customer_id INTEGER REFERENCES customers(id),
  bank TEXT NOT NULL DEFAULT '',
  destination TEXT NOT NULL DEFAULT '',      -- CBU/alias de destino configurable
  amount REAL NOT NULL,
  reference TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | informada | verificada | rechazada
  informed_at TEXT,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  created_by INTEGER,
  verified_by INTEGER,
  verified_at TEXT,
  verify_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_transfers_status ON transfers(status);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT NOT NULL UNIQUE,
  datetime TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  customer_id INTEGER REFERENCES customers(id),
  subtotal REAL NOT NULL DEFAULT 0,
  discount REAL NOT NULL DEFAULT 0,
  tax_total REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL DEFAULT 0,
  cost_total REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'activa',
  payment_status TEXT NOT NULL DEFAULT 'pagada',
  void_reason TEXT NOT NULL DEFAULT '',
  voided_by INTEGER,
  voided_at TEXT,
  notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sales_datetime ON sales(datetime);

CREATE TABLE IF NOT EXISTS sale_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id),
  description TEXT NOT NULL,
  unit TEXT NOT NULL,
  qty REAL NOT NULL,
  unit_price REAL NOT NULL,
  discount REAL NOT NULL DEFAULT 0,
  line_subtotal REAL NOT NULL,
  tax_breakdown TEXT NOT NULL DEFAULT '[]',
  tax_amount REAL NOT NULL DEFAULT 0,
  line_total REAL NOT NULL,
  cost_snapshot REAL NOT NULL DEFAULT 0,
  stock_delta REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  method TEXT NOT NULL,     -- efectivo | transferencia | debito | credito | cuenta_corriente
  amount REAL NOT NULL,
  transfer_id INTEGER REFERENCES transfers(id),
  created_at TEXT NOT NULL,
  user_id INTEGER
);

CREATE TABLE IF NOT EXISTS sale_returns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER NOT NULL REFERENCES sales(id),
  number TEXT NOT NULL UNIQUE,
  datetime TEXT NOT NULL,
  user_id INTEGER,
  total REAL NOT NULL DEFAULT 0,
  tax_total REAL NOT NULL DEFAULT 0,
  refund_method TEXT NOT NULL DEFAULT 'efectivo',
  reason TEXT NOT NULL DEFAULT '',
  cash_movement_id INTEGER REFERENCES cash_movements(id),
  ledger_id INTEGER REFERENCES customer_ledger(id)
);

CREATE TABLE IF NOT EXISTS sale_return_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  return_id INTEGER NOT NULL REFERENCES sale_returns(id) ON DELETE CASCADE,
  sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),
  product_id INTEGER NOT NULL REFERENCES products(id),
  qty REAL NOT NULL,
  unit_price REAL NOT NULL,
  tax_amount REAL NOT NULL DEFAULT 0,
  line_total REAL NOT NULL,
  stock_delta REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  datetime TEXT NOT NULL,
  type TEXT NOT NULL,            -- venta_credito | cobro | devolucion | ajuste
  description TEXT NOT NULL DEFAULT '',
  debit REAL NOT NULL DEFAULT 0,
  credit REAL NOT NULL DEFAULT 0,
  ref_type TEXT NOT NULL DEFAULT '',
  ref_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cl_customer ON customer_ledger(customer_id);

CREATE TABLE IF NOT EXISTS customer_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  datetime TEXT NOT NULL,
  amount REAL NOT NULL,
  method TEXT NOT NULL DEFAULT 'efectivo',
  user_id INTEGER,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT NOT NULL UNIQUE,
  supplier_id INTEGER REFERENCES suppliers(id),
  datetime TEXT NOT NULL,
  user_id INTEGER,
  status TEXT NOT NULL DEFAULT 'pendiente',   -- pendiente | parcial | recibida
  subtotal REAL NOT NULL DEFAULT 0,
  tax_total REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL DEFAULT 0,
  pay_method TEXT NOT NULL DEFAULT 'credito', -- efectivo | transferencia | credito
  received_at TEXT,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS purchase_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id),
  description TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT 'unidad',
  qty_ordered REAL NOT NULL,
  qty_received REAL NOT NULL DEFAULT 0,
  unit_cost REAL NOT NULL,
  line_total REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_receipts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  datetime TEXT NOT NULL,
  user_id INTEGER,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS receipt_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  receipt_id INTEGER NOT NULL REFERENCES purchase_receipts(id) ON DELETE CASCADE,
  purchase_item_id INTEGER NOT NULL REFERENCES purchase_items(id),
  qty REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  datetime TEXT NOT NULL,
  type TEXT NOT NULL,            -- compra_credito | pago | ajuste
  description TEXT NOT NULL DEFAULT '',
  debit REAL NOT NULL DEFAULT 0,   -- aumenta lo que debemos
  credit REAL NOT NULL DEFAULT 0,  -- reduce lo que debemos
  ref_type TEXT NOT NULL DEFAULT '',
  ref_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sl_supplier ON supplier_ledger(supplier_id);

CREATE TABLE IF NOT EXISTS supplier_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  datetime TEXT NOT NULL,
  amount REAL NOT NULL,
  method TEXT NOT NULL DEFAULT 'efectivo',
  user_id INTEGER,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cash_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opened_at TEXT NOT NULL,
  user_open INTEGER NOT NULL,
  initial REAL NOT NULL DEFAULT 0,
  closed_at TEXT,
  user_close INTEGER,
  counted REAL,
  expected REAL,
  diff REAL,
  status TEXT NOT NULL DEFAULT 'abierta',
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cash_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES cash_sessions(id),
  datetime TEXT NOT NULL,
  type TEXT NOT NULL,            -- ingreso | egreso
  concept TEXT NOT NULL,
  amount REAL NOT NULL,
  user_id INTEGER,
  ref_type TEXT NOT NULL DEFAULT '',
  ref_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cm_session ON cash_movements(session_id);

CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  datetime TEXT NOT NULL,
  concept TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  amount REAL NOT NULL,
  method TEXT NOT NULL DEFAULT 'efectivo',
  user_id INTEGER,
  from_cash INTEGER NOT NULL DEFAULT 1,
  cash_movement_id INTEGER REFERENCES cash_movements(id)
);

CREATE TABLE IF NOT EXISTS transfer_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bank TEXT NOT NULL,
  alias TEXT NOT NULL DEFAULT '',
  cbu TEXT NOT NULL DEFAULT '',
  holder TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tax_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tax_id INTEGER NOT NULL,
  action TEXT NOT NULL,
  old_json TEXT,
  new_json TEXT,
  user_id INTEGER,
  datetime TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  datetime TEXT NOT NULL,
  user_id INTEGER,
  username TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_datetime ON audit_log(datetime);

CREATE TABLE IF NOT EXISTS license_info (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  install_id TEXT NOT NULL,
  license_id TEXT NOT NULL DEFAULT '',
  client TEXT NOT NULL DEFAULT '',
  issued_at TEXT,
  expires_at TEXT,
  grace_days INTEGER NOT NULL DEFAULT 7,
  warn_days INTEGER NOT NULL DEFAULT 15,
  suspended INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '',
  last_check TEXT,
  updated_at TEXT NOT NULL
);
