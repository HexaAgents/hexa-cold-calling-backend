-- Expose auth.users via an RPC function accessible with the service role key.
-- This avoids the GoTrue admin API which can be rejected in hosted environments.
CREATE OR REPLACE FUNCTION get_auth_users()
RETURNS TABLE(id UUID, email TEXT, raw_user_meta_data JSONB)
LANGUAGE sql
SECURITY DEFINER
AS $$
  SELECT id, email::TEXT, raw_user_meta_data
  FROM auth.users
  ORDER BY created_at ASC;
$$;
