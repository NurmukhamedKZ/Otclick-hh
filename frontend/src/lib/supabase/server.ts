import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!anonKey) {
    throw new Error("SUPABASE_ANON_KEY runtime environment variable is required");
  }

  return createServerClient(
    process.env.SUPABASE_URL ?? "http://kong:8000",
    anonKey,
    {
      cookieOptions: { name: "sb-otclick-auth-token" },
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from Server Component — ignore. Middleware refreshes session.
          }
        },
      },
    },
  );
}
