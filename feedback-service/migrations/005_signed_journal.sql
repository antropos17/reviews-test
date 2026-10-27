CREATE TABLE feedback_private.journal_events(
  seq BIGINT PRIMARY KEY, event_json TEXT NOT NULL, event_hash TEXT NOT NULL, signature TEXT NOT NULL
);
ALTER TABLE feedback_private.journal_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON feedback_private.journal_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON feedback_private.journal_events TO feedback_service;
GRANT SELECT ON feedback_private.journal_events TO feedback_backup;
REVOKE UPDATE,DELETE,TRUNCATE ON feedback_private.journal_events FROM feedback_service,feedback_backup;
CREATE POLICY journal_service_select ON feedback_private.journal_events FOR SELECT TO feedback_service USING (true);
CREATE POLICY journal_service_insert ON feedback_private.journal_events FOR INSERT TO feedback_service WITH CHECK (true);
CREATE POLICY journal_backup_select ON feedback_private.journal_events FOR SELECT TO feedback_backup USING (true);
