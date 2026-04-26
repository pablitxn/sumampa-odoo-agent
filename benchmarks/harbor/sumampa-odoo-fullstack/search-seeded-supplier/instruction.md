Exercise the Sumampa Odoo agent against the seeded Odoo integration stack.

The environment starts a Sumampa API sidecar, an Odoo 19 sidecar, and Odoo's
Postgres sidecar. No workspace edits are required for this task. The verifier
will call `POST /api/v1/messages` with the fixture under `/tests/fixtures`,
inspect the response, and write numeric rewards to `/logs/verifier/reward.json`.
