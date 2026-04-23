import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

const isPublicRoute = createRouteMatcher([
  "/",              // marketing landing page
  "/demo(.*)",      // public demo experience (no login required)
  "/pitch(.*)",     // investor/partner pitch deck (public)
  "/onboarding(.*)", // self-guided onboarding (unauthenticated demo)
  "/share(.*)",     // public analytics share links
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/api/webhooks(.*)",
  "/api/health",
]);

const isOrgSelectionRoute = createRouteMatcher(["/org-selection(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  // Explicit pathname guard — covers cases where createRouteMatcher
  // doesn't match the base path without a trailing slash in Clerk v6
  if (req.nextUrl.pathname.startsWith("/demo")) return NextResponse.next();

  if (isPublicRoute(req)) return NextResponse.next();

  const { userId, orgId } = await auth();

  // Not signed in → send to sign-in, preserving the intended destination
  if (!userId) {
    const signInUrl = new URL("/sign-in", req.url);
    signInUrl.searchParams.set("redirect_url", req.url);
    return NextResponse.redirect(signInUrl);
  }

  // Signed in but no active organization → force org selection
  // (let the org-selection page itself pass through so we don't loop)
  if (!orgId && !isOrgSelectionRoute(req)) {
    return NextResponse.redirect(new URL("/org-selection", req.url));
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
