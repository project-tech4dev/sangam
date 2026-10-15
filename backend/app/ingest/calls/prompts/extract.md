You read one page from a funder's website and list the open calls for proposals on it.

A call is an invitation for organisations to apply for money by a stated date: a call for proposals,
a request for proposals, an expression of interest, a grant edition with an application window.

These are not calls, so leave them out:
- a programme description, a list of past partners or grantees, an annual report;
- a procurement tender for goods or services (facility management, audits, printing, consultancy);
- a job, fellowship for individuals, or internship;
- a form that is open all year with no closing date.

For each call:
- `title`: as the page prints it.
- `deadline`: the last date to apply, YYYY-MM-DD. A call whose closing date has passed is still listed
  with that date. If only a month or year is given, or no date at all, leave it null.
- `url`: the link to the call itself when the page gives one, else null.
- `amount_min`, `amount_max`: the grant band in rupees as plain numbers (₹25 lakh is 2500000, ₹1 crore
  is 10000000). Null when not stated. Never convert from another currency.
- `states`: Indian states or union territories the call is limited to. Empty when it is open across India
  or does not say.
- `domains`: one or more of: education, health, livelihoods, environment, others.
- `themes`: codes from the list below that the call names, at most three. Empty when none fits.
- `eligibility`: who may apply, one short line per requirement, as the page states it.

Only what the page says. Do not infer a deadline, an amount or a place.

Theme codes:
{themes}
