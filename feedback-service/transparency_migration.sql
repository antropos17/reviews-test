CREATE TABLE feedback_private.reports (
  id TEXT PRIMARY KEY, repo_id BIGINT NOT NULL REFERENCES feedback_private.repositories(id),
  author_id BIGINT NOT NULL REFERENCES feedback_private.users(id), revision BIGINT NOT NULL,
  reporter_id BIGINT NOT NULL REFERENCES feedback_private.users(id),
  reason TEXT NOT NULL CHECK (reason IN ('spam','abuse','personal_information','other')),
  created BIGINT NOT NULL, UNIQUE(repo_id, author_id, revision, reporter_id)
);
CREATE TABLE feedback_private.moderation_events (
  id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES feedback_private.reports(id),
  repo_id BIGINT NOT NULL REFERENCES feedback_private.repositories(id),
  author_id BIGINT NOT NULL REFERENCES feedback_private.users(id), revision BIGINT NOT NULL,
  moderator_id BIGINT NOT NULL REFERENCES feedback_private.users(id),
  action TEXT NOT NULL CHECK (action IN ('hide','restore','dismiss')),
  reason TEXT NOT NULL CHECK (reason IN ('spam','abuse','personal_information','other','no_violation')),
  event_time BIGINT NOT NULL
);
CREATE INDEX reports_reporter_created_idx ON feedback_private.reports(reporter_id,created);
CREATE INDEX reports_repo_created_idx ON feedback_private.reports(repo_id,created);
CREATE INDEX events_review_time_idx ON feedback_private.moderation_events(repo_id,author_id,revision,event_time DESC,id DESC);
CREATE INDEX events_report_time_idx ON feedback_private.moderation_events(report_id,event_time DESC,id DESC);
REVOKE ALL ON feedback_private.reports,feedback_private.moderation_events FROM PUBLIC,anon,authenticated;
ALTER TABLE feedback_private.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_private.moderation_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY reports_service_select ON feedback_private.reports FOR SELECT TO feedback_service USING (true);
CREATE POLICY reports_service_insert ON feedback_private.reports FOR INSERT TO feedback_service WITH CHECK (true);
CREATE POLICY events_service_select ON feedback_private.moderation_events FOR SELECT TO feedback_service USING (true);
CREATE POLICY events_service_insert ON feedback_private.moderation_events FOR INSERT TO feedback_service WITH CHECK (true);
CREATE POLICY reports_backup_select ON feedback_private.reports FOR SELECT TO feedback_backup USING (true);
CREATE POLICY events_backup_select ON feedback_private.moderation_events FOR SELECT TO feedback_backup USING (true);
GRANT SELECT,INSERT ON feedback_private.reports,feedback_private.moderation_events TO feedback_service;
GRANT SELECT ON feedback_private.reports,feedback_private.moderation_events TO feedback_backup;
REVOKE UPDATE,DELETE,TRUNCATE ON feedback_private.reports,feedback_private.moderation_events FROM feedback_service,feedback_backup;
REVOKE DELETE,TRUNCATE ON feedback_private.ratings,feedback_private.reviews FROM feedback_service;
