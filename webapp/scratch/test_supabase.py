import os
from dotenv import load_dotenv

env_path = r"c:\Users\Jovan Fernandes\OneDrive\Documents\mcb  int\mcb-to-notion-sync\.env"
load_dotenv(env_path)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

print(f"URL: {supabase_url}")

try:
    from supabase import create_client
    supabase = create_client(supabase_url, supabase_key)
    res = supabase.table("entries").select("count").execute()
    print(f"Success! Data count: {res.data}")
except Exception as e:
    print(f"Error: {e}")
