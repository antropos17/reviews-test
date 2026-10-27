CREATE TABLE feedback_private.security_concerns (
  repo_id BIGINT NOT NULL REFERENCES feedback_private.repositories(id),
  author_id BIGINT NOT NULL REFERENCES feedback_private.users(id),
  revision BIGINT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  evidence_url TEXT, PRIMARY KEY(repo_id,author_id)
);
ALTER TABLE feedback_private.security_concerns ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON feedback_private.security_concerns FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON feedback_private.security_concerns TO feedback_service;
GRANT SELECT ON feedback_private.security_concerns TO feedback_backup;
CREATE POLICY concerns_service ON feedback_private.security_concerns TO feedback_service USING (true) WITH CHECK (true);
CREATE POLICY concerns_backup ON feedback_private.security_concerns FOR SELECT TO feedback_backup USING (true);
