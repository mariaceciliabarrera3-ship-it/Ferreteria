-- FerreGest AR — Migración 002: límite de intentos de login persistente (ARQ-08)
--
-- Motivo: el contador de intentos fallidos vivía en un diccionario en memoria
-- del proceso. Eso significaba que (a) se perdía al reiniciar la aplicación y
-- (b) no se compartía entre workers, por lo que el límite real era
-- "8 intentos x worker", no 8 intentos. Con esta tabla el límite es global a la
-- instalación y sobrevive a los reinicios.
--
-- IDEMPOTENTE: se puede ejecutar más de una vez sin romper nada. No modifica
-- ninguna tabla existente, por eso no hace falta recrear la base.
-- IMPORTANTE: la migración 001_init.sql NO se edita (ya está aplicada en
-- instalaciones existentes). Toda corrección de esquema va en un archivo nuevo.

CREATE TABLE IF NOT EXISTS login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,          -- usuario al que se intentó ingresar
  at TEXT NOT NULL,                -- fecha/hora local (America/Argentina/Buenos_Aires)
  success INTEGER NOT NULL DEFAULT 0  -- 0 = fallido, 1 = correcto
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user
  ON login_attempts(username, at);

-- Registro de auditoría de los bloqueos por fuerza bruta (consulta rápida).
CREATE INDEX IF NOT EXISTS idx_audit_action
  ON audit_log(action, datetime);
