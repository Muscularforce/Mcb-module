import sqlite3

db_path = 'mcb-to-notion-sync/webapp/backend/mcb.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Delete query
query = """
DELETE FROM entries 
WHERE teacher IN (
  'John Doe', 
  'Jane Smith', 
  'Alan Turing', 
  'Rosalind Franklin', 
  'Ms. Charlotte', 
  'Mr. Gupta', 
  'Coach Williams', 
  'Dr. Feynman', 
  'Mr. Euler', 
  'Principal Smith'
) OR attachment_url = 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf';
"""

cursor.execute(query)
conn.commit()
print(f"Deleted {conn.total_changes} mock entries from local database.")
conn.close()
