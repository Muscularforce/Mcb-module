import sqlite3

db_path = 'mcb-to-notion-sync/webapp/backend/mcb.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get entries
cursor.execute('SELECT entry_type, subject, teacher, date, summary, attachment_url FROM entries')
rows = cursor.fetchall()

sql_statements = []
for r in rows:
    entry_type, subject, teacher, date, summary, attachment_url = r
    
    # Escape single quotes for SQL
    subj_esc = subject.replace("'", "''") if subject else ''
    teach_esc = teacher.replace("'", "''") if teacher else ''
    sum_esc = summary.replace("'", "''") if summary else ''
    
    if attachment_url:
        att_esc = "'" + attachment_url.replace("'", "''") + "'"
    else:
        att_esc = 'NULL'
    
    sql = f"INSERT INTO public.entries (entry_type, subject, teacher, date, summary, attachment_url) VALUES ('{entry_type}', '{subj_esc}', '{teach_esc}', '{date}', '{sum_esc}', {att_esc});"
    sql_statements.append(sql)

# Print or write to file
with open('mcb-to-notion-sync/webapp/supabase_seed.sql', 'w', encoding='utf-8') as f:
    f.write('\n'.join(sql_statements))

print(f"Generated {len(sql_statements)} INSERT statements in webapp/supabase_seed.sql")
conn.close()
