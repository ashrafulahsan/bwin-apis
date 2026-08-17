"""The rows to be seeded, one module per domain.

Kept apart from the seeders that apply them because the two change for
different reasons and at different rates: the demo blog content is several
hundred lines of prose that an editor may rewrite without touching any logic,
while the code that files it under a taxonomy barely changes at all.

Specs only - no session, no service, nothing to run.
"""
