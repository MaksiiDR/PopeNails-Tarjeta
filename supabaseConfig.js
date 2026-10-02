// PopeNails Supabase Client Configuration
const SUPABASE_URL = 'https://ktmwjuamovupzwqifmct.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0bXdqdWFtb3Z1cHp3cWlmbWN0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYzNTk1NzQsImV4cCI6MjA5MTkzNTU3NH0.2QRU30TxLgokaE6nebURDOvxjhGEuq-NWVQSH2Rlkdg';

// Initialize Supabase Client
let supabaseClient = null;
function getSupabaseClient() {
  if (supabaseClient) return supabaseClient;
  if (window.supabase && typeof window.supabase.createClient === 'function') {
    supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    window.supabaseClient = supabaseClient;
  }
  return supabaseClient;
}

if (window.supabase) {
  getSupabaseClient();
}
