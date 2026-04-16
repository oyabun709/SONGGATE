"use client";

/**
 * OrgActivator — silently ensures an organization is active in the Clerk
 * client session whenever the dashboard is loaded.
 *
 * Problem: auth() on the server can see orgId from the cookie, but
 * getToken() on the client issues a fresh short-lived JWT that only includes
 * org_id if setActive({ organization }) was explicitly called client-side.
 * If the session was loaded without going through org-selection (e.g. a
 * returning user, SSO, or after a browser refresh) the JWT comes back without
 * org_id even though the user is a member of an org.
 *
 * This component detects that state and calls setActive with the first
 * available membership so that subsequent getToken() calls include org_id.
 */

import { useEffect } from "react";
import { useOrganization, useOrganizationList } from "@clerk/nextjs";

export function OrgActivator() {
  const { organization, isLoaded: orgLoaded } = useOrganization();
  const { userMemberships, setActive, isLoaded: listLoaded } = useOrganizationList({
    userMemberships: { infinite: false },
  });

  useEffect(() => {
    if (!orgLoaded || !listLoaded) return;
    // Already have an active org — nothing to do.
    if (organization) return;
    const memberships = userMemberships?.data ?? [];
    // No orgs available — backend personal-org fallback will handle it.
    if (memberships.length === 0) return;

    // Silently activate the first org so getToken() includes org_id.
    setActive({ organization: memberships[0].organization.id }).catch(() => {
      window.location.href = "/org-selection";
    });
  }, [orgLoaded, listLoaded, organization, userMemberships, setActive]);

  return null;
}
