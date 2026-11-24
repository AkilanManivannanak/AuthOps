-- Row-level security for the run store on Postgres (Neon).
-- Every session row belongs to one healthcare provider. The application sets the tenant once
-- per connection or transaction:  SET app.tenant_id = 'clinic-123';
-- and Postgres itself refuses to return or change another provider's rows, even for a buggy query.

ALTER TABLE runs  ADD COLUMN IF NOT EXISTS tenant TEXT NOT NULL DEFAULT 'default';
ALTER TABLE runs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs  FORCE ROW LEVEL SECURITY;
ALTER TABLE steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE steps FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS runs_tenant ON runs;
CREATE POLICY runs_tenant ON runs
  USING (tenant = current_setting('app.tenant_id', true))
  WITH CHECK (tenant = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS steps_tenant ON steps;
CREATE POLICY steps_tenant ON steps
  USING (EXISTS (SELECT 1 FROM runs r WHERE r.run_id = steps.run_id
                 AND r.tenant = current_setting('app.tenant_id', true)));
