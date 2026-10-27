CREATE TABLE feedback_private.owner_replies (
  repo_id BIGINT NOT NULL REFERENCES feedback_private.repositories(id),
  author_id BIGINT NOT NULL REFERENCES feedback_private.users(id),
  owner_id BIGINT NOT NULL REFERENCES feedback_private.users(id),
  body TEXT NOT NULL, updated BIGINT NOT NULL,
  PRIMARY KEY(repo_id, author_id)
);
ALTER TABLE feedback_private.owner_replies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON feedback_private.owner_replies FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON feedback_private.owner_replies TO feedback_service;
GRANT SELECT ON feedback_private.owner_replies TO feedback_backup;
CREATE POLICY replies_service ON feedback_private.owner_replies TO feedback_service USING (true) WITH CHECK (true);
CREATE POLICY replies_backup ON feedback_private.owner_replies FOR SELECT TO feedback_backup USING (true);
ALTER TABLE feedback_private.moderation_events DROP CONSTRAINT moderation_events_reason_check;
ALTER TABLE feedback_private.moderation_events ADD CONSTRAINT moderation_events_reason_check CHECK
  (reason IN ('spam','abuse','personal_information','other','no_violation','harassment','personal_data','security_claim_no_evidence'));
