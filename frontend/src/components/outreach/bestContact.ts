// Deterministic "best contact" selection — pure, no I/O, no new enrichment call. Both the scan
// coverage table (ContactCell) and the CRM lead drawer (LeadContacts) render ONE resolved contact
// line instead of a dense multi-contact cell, and they must resolve "who to ask for + the best
// number" identically, so the picker lives here and both read it.
//
// Fact-grounded, never invents (the 2026-08-08 design-fork ruling): it only chooses among the
// contacts already returned by enrichment. ~60% of small operators resolve to no named person —
// that's an honest empty state, not a gap to paper over.

export interface ContactLike {
  full_name?: string | null
  title?: string | null
  name_for_emails?: string | null
  email?: string | null
  email_status?: string | null
  email_is_generic?: boolean
  phone?: string | null
  phone_type?: string | null
  source?: string | null
  confidence?: number | null
  confidence_band?: 'high' | 'medium' | 'low' | null
}

export interface BestContact {
  // 'person'        → a named decision-maker was resolved.
  // 'business_only' → contacts exist but none names a person (business-name / scraped-email only).
  // 'none'          → no contacts at all (not enriched, or enrichment found nothing).
  kind: 'person' | 'business_only' | 'none'
  contact: ContactLike | null   // the chosen person (kind 'person'), else null
  name: string | null
  title: string | null
  phone: string | null          // the PERSON's own direct line when known (else null → use main line)
  email: string | null          // the person's email, or a scraped fallback email for business_only
}

// A person requires a real full_name. name_for_emails is an email-derived guess, not a confirmed
// person, so it does not by itself make a contact a "named person" here.
function isPerson(c: ContactLike): boolean {
  return !!(c.full_name && c.full_name.trim())
}

// Rank a named candidate: a title AND a direct phone is the most useful (matches the task's "prefer
// a contact with a full_name AND a title/phone"); a title outweighs a bare phone for "who to ask
// for". Deterministic — ties resolve to the earlier contact (stable input order).
function personScore(c: ContactLike): number {
  return (c.title ? 2 : 0) + (c.phone ? 1 : 0)
}

// Prefer a real, non-generic mailbox; fall back to any email (a generic info@ is still a usable
// fallback for a business with no named person).
function pickFallbackEmail(contacts: ContactLike[]): string | null {
  const real = contacts.find(c => c.email && !c.email_is_generic)
  if (real?.email) return real.email
  const any = contacts.find(c => c.email)
  return any?.email ?? null
}

export function pickBestContact(contacts: ContactLike[] | null | undefined): BestContact {
  const list = contacts ?? []
  if (list.length === 0) {
    return { kind: 'none', contact: null, name: null, title: null, phone: null, email: null }
  }

  const people = list.filter(isPerson)
  if (people.length > 0) {
    // Highest-scoring named person; stable on ties (reduce keeps the earlier one on equality).
    const best = people.reduce((a, b) => (personScore(b) > personScore(a) ? b : a))
    return {
      kind: 'person',
      contact: best,
      name: (best.full_name ?? '').trim() || null,
      title: best.title ?? null,
      phone: best.phone ?? null,
      email: best.email ?? null,
    }
  }

  // Contacts exist but none names a person — surface a scraped/generic email as the fallback.
  return {
    kind: 'business_only',
    contact: null,
    name: null,
    title: null,
    phone: null,
    email: pickFallbackEmail(list),
  }
}

// How many ADDITIONAL named people exist beyond the one shown — drives a quiet "+N more" hint so a
// caller knows the single line isn't hiding a bigger contact list without saying so.
export function additionalNamedCount(contacts: ContactLike[] | null | undefined): number {
  const people = (contacts ?? []).filter(isPerson)
  return people.length > 1 ? people.length - 1 : 0
}
