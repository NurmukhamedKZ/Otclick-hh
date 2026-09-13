import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const ANON_KEY_COOKIE = "otclick-supabase-anon-key";
const GOOGLE_AUTH_COOKIE = "otclick-google-auth-enabled";

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!anonKey) {
    throw new Error("SUPABASE_ANON_KEY runtime environment variable is required");
  }

  function withRuntimeConfig(nextResponse: NextResponse) {
    // The Supabase anon key is intentionally public. Exposing it through a
    // first-party cookie lets one prebuilt Next.js image work with per-install
    // JWT/anon keys instead of baking CI values into browser bundles.
    nextResponse.cookies.set(ANON_KEY_COOKIE, anonKey!, {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
    });
    nextResponse.cookies.set(
      GOOGLE_AUTH_COOKIE,
      process.env.GOOGLE_AUTH_ENABLED === "true" ? "true" : "false",
      { httpOnly: false, sameSite: "lax", path: "/" },
    );
    return nextResponse;
  }

  const supabase = createServerClient(
    process.env.SUPABASE_URL ?? "http://kong:8000",
    anonKey,
    {
      cookieOptions: { name: "sb-otclick-auth-token" },
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const path = request.nextUrl.pathname;
  // Белый список публичного, а не чёрный список приватного: новая страница под
  // (app)/ защищена по умолчанию, а не пока о ней не вспомнят здесь.
  const isPublic = path === "/" || path.startsWith("/auth");
  const isProtected = !isPublic;
  const isAuthPage = path === "/auth";

  if (path === "/login" || path === "/signup" || path === "/filters") {
    const url = request.nextUrl.clone();
    url.pathname = path === "/filters" ? "/dashboard" : "/auth";
    return withRuntimeConfig(NextResponse.redirect(url));
  }

  if (!user && isProtected) {
    const url = request.nextUrl.clone();
    url.pathname = "/auth";
    return withRuntimeConfig(NextResponse.redirect(url));
  }

  if (user && isAuthPage) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    return withRuntimeConfig(NextResponse.redirect(url));
  }

  return withRuntimeConfig(response);
}
