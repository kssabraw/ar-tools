// Merged suite: the Fan-out app now shares the suite's single Supabase client
// (one auth session across the whole app) instead of constructing its own.
export { supabase } from "../../lib/supabase";
