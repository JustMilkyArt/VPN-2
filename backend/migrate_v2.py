"""
Миграция БД v2: добавляет новые колонки в таблицу servers.
Запускать: python3 migrate_v2.py
"""
import sqlite3
import os

DB_PATH = "/opt/vpn-admin/vpn_admin.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Получаем текущие колонки
    cur.execute("PRAGMA table_info(servers)")
    existing = {row[1] for row in cur.fetchall()}
    print(f"Существующие колонки: {existing}")

    migrations = [
        ("setup_status",    "ALTER TABLE servers ADD COLUMN setup_status VARCHAR(20) NOT NULL DEFAULT 'not_started'"),
        ("ssh_private_key", "ALTER TABLE servers ADD COLUMN ssh_private_key TEXT"),
        ("eu_server_id",    "ALTER TABLE servers ADD COLUMN eu_server_id INTEGER REFERENCES servers(id)"),
    ]

    for col_name, sql in migrations:
        if col_name not in existing:
            print(f"Добавляю колонку: {col_name}")
            cur.execute(sql)
        else:
            print(f"Колонка {col_name} уже существует — пропускаю")

    conn.commit()
    conn.close()
    print("Миграция завершена.")

if __name__ == "__main__":
    migrate()
