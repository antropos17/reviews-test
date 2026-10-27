CREATE TABLE feedback_private.seals(
  repo_id BIGINT PRIMARY KEY REFERENCES feedback_private.repositories(id),
  activated_at BIGINT NOT NULL, removed_at BIGINT, removed_rating DOUBLE PRECISION,
  activated_by BIGINT NOT NULL REFERENCES feedback_private.users(id)
);
ALTER TABLE feedback_private.seals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON feedback_private.seals FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON feedback_private.seals TO feedback_service;
GRANT SELECT ON feedback_private.seals TO feedback_backup;
CREATE POLICY seals_service ON feedback_private.seals TO feedback_service USING (true) WITH CHECK (true);
CREATE POLICY seals_backup ON feedback_private.seals FOR SELECT TO feedback_backup USING (true);
