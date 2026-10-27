import tempfile
import hashlib
from contextlib import closing
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app import create_app


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status
    def json(self):
        return self.data
    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError('mock failure')


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.app = create_app({'TESTING': True, 'DATABASE': str(Path(self.temp.name) / 'test.sqlite'),
                               'GITHUB_CLIENT_ID': 'test', 'GITHUB_CLIENT_SECRET': 'test',
                               'BASE_URL': 'http://localhost', 'MODERATOR_IDS': '77,99'})
        self.client = self.app.test_client()
        self.created_at = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat().replace('+00:00', 'Z')
        def get(url, **kwargs):
            if url == 'https://api.github.com/user':
                return Response({'id': 42, 'login': 'alice', 'type': 'User', 'created_at': self.created_at})
            if url == 'https://api.github.com/repos/owner/project':
                return Response({'id': 7, 'full_name': 'owner/project', 'private': False, 'owner': {'id': 99}})
            return Response({}, 404)
        self.get_patcher = patch('app.requests.get', side_effect=get)
        self.post_patcher = patch('app.requests.post', return_value=Response({'access_token': 'fake'}))
        self.get_patcher.start(); self.post_patcher.start()

    def tearDown(self):
        self.post_patcher.stop(); self.get_patcher.stop(); self.temp.cleanup()

    def login(self):
        response = self.client.get('/auth/login?repo=owner/project')
        query = parse_qs(urlsplit(response.location).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        return self.client.get('/auth/callback?code=fake&state=' + query['state'][0])

    def state(self):
        response = self.client.get('/api/feedback?repo=owner/project')
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def write(self, action, body, csrf):
        return self.client.post('/api/' + action + '?repo=owner/project', json=body,
                                headers={'Origin': 'http://localhost', 'X-CSRF-Token': csrf})

    def act_as(self, user_id, login, created_at=None):
        token = 'session-' + str(user_id)
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('INSERT OR REPLACE INTO users VALUES (?,?,?)', (user_id, login, created_at or self.created_at))
            connection.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user_id, 'csrf-' + str(user_id), int(time.time()) + 3600))
            connection.commit()
        self.client.set_cookie('feedback_session', token)
        return 'csrf-' + str(user_id)

    def test_oauth_state_replay_and_csrf(self):
        self.assertEqual(self.client.get('/auth/callback?state=forged&code=x').status_code, 400)
        self.assertEqual(self.login().status_code, 302)
        state = self.state(); csrf = state['user']['csrf']
        self.assertEqual(self.write('rating', {'rating': 4}, 'wrong').status_code, 403)
        self.assertEqual(self.write('rating', {'rating': 4}, csrf).status_code, 200)
        self.assertEqual(self.state()['count'], 1)

    def test_rating_and_review_are_independent_and_repeated_vote_is_one(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.assertEqual(self.write('rating', {'rating': 4}, csrf).status_code, 200)
        self.assertEqual(self.write('review', {'body': '<script>test</script>'}, csrf).status_code, 200)
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('UPDATE ratings SET updated=?', (int(time.time()) - 10,))
            connection.commit()
        self.assertEqual(self.write('rating', {'rating': 5}, csrf).status_code, 200)
        result = self.state()
        self.assertEqual((result['count'], result['average']), (1, 5))
        self.assertEqual(result['reviews'][0]['body'], '<script>test</script>')

    def test_new_account_pending_without_approval(self):
        self.created_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat().replace('+00:00', 'Z')
        self.login(); user = self.state()['user']
        self.assertFalse(user['eligible'])
        self.assertTrue(self.write('rating', {'rating': 5}, user['csrf']).get_json()['pending'])
        self.assertEqual(self.state()['count'], 0)
        self.assertEqual(self.write('review', {'body': 'hello'}, user['csrf']).status_code, 200)
        self.assertEqual(self.state()['reviews'], [])

    def test_average_counts_only_eligible_accounts(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.assertEqual(self.write('rating', {'rating': 5}, csrf).status_code, 200)
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('INSERT INTO users VALUES (?,?,?)', (43, 'bob', self.created_at))
            connection.execute('INSERT INTO ratings VALUES (?,?,?,?)', (7, 43, 2, int(time.time())))
            connection.execute('INSERT INTO users VALUES (?,?,?)', (44, 'new', datetime.now(timezone.utc).isoformat()))
            connection.execute('INSERT INTO ratings VALUES (?,?,?,?)', (7, 44, 1, int(time.time())))
            connection.commit()
        result = self.state()
        self.assertEqual((result['count'], result['average']), (2, 3.5))

    def test_card_shows_only_eligible_feedback_and_escapes_review_text(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.assertEqual(self.write('rating', {'rating': 5}, csrf).status_code, 200)
        self.assertEqual(self.write('review', {'body': '<script>hello & goodbye</script>'}, csrf).status_code, 200)
        response = self.client.get('/card.svg?repo=owner/project')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')
        self.assertEqual(response.headers['Cache-Control'], 'no-cache')
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.data)
        self.assertIn('5.0 / 5', ''.join(root.itertext()))
        self.assertIn('<script>hello & goodbye</script>', ''.join(root.itertext()))
        self.assertNotIn(b'<script>', response.data)
        dark = self.client.get('/card.svg?repo=owner/project&theme=dark')
        self.assertIn(b'fill="#0d1117"', dark.data)
        self.assertIn(b'5.0 / 5', dark.data)

    def test_rate_limited_api_requires_matching_public_repository_page(self):
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('INSERT INTO repositories VALUES (?,?)', (7, 'owner/project'))
            connection.commit()
        page = Response({}, 200)
        page.text = ('<meta name="octolytics-dimension-repository_id" content="7">'
                     '<meta name="octolytics-dimension-user_id" content="99">'
                     '<meta name="octolytics-dimension-repository_nwo" content="owner/project">'
                     '<meta name="octolytics-dimension-repository_public" content="true">')
        def lookup(url, **kwargs):
            return page if url.startswith('https://github.com/') else Response({}, 403)
        with patch('app.requests.get', side_effect=lookup):
            self.assertEqual(self.client.get('/card.svg?repo=owner/project').status_code, 200)
            page.text = page.text.replace('content="7"', 'content="8"')
            self.assertEqual(self.client.get('/card.svg?repo=OWNER/project').status_code, 503)
            page.text = page.text.replace('owner/project', 'other/project')
            self.assertEqual(self.client.get('/card.svg?repo=other/project').status_code, 200)

    def test_public_repository_and_input_validation(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.assertEqual(self.client.get('/api/feedback?repo=../private').status_code, 400)
        self.assertEqual(self.write('rating', {'rating': True}, csrf).status_code, 400)
        self.assertEqual(self.write('review', {'body': ' '}, csrf).status_code, 400)
        self.assertEqual(self.client.get('/api/feedback?repo=owner/missing').status_code, 404)

    def test_long_unicode_review_is_accepted(self):
        self.login(); csrf = self.state()['user']['csrf']
        text = '界' * 4000
        self.assertEqual(self.write('review', {'body': text}, csrf).status_code, 200)
        self.assertEqual(self.state()['reviews'][0]['body'], text)

    def test_owner_cannot_vote_or_moderate_own_project(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.assertEqual(self.write('rating', {'rating': 4}, csrf).status_code, 200)
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('INSERT INTO users VALUES (?,?,?)', (99, 'owner', self.created_at))
            connection.execute('INSERT INTO ratings VALUES (?,?,?,?)', (7, 99, 5, int(time.time())))
            connection.commit()
        owner_csrf = self.act_as(99, 'owner')
        result = self.state()
        self.assertEqual((result['count'], result['average']), (1, 4))
        self.assertTrue(result['user']['owner'])
        self.assertEqual(self.write('rating', {'rating': 5}, owner_csrf).status_code, 403)
        self.assertEqual(self.write('review', {'body': 'owner review'}, owner_csrf).status_code, 403)
        self.assertEqual(self.client.get('/api/reports?repo=owner/project').status_code, 403)

    def test_owner_check_does_not_use_cached_repository_owner(self):
        self.login(); csrf = self.state()['user']['csrf']
        changed = Response({'id': 7, 'full_name': 'owner/project', 'private': False, 'owner': {'id': 42}})
        with patch('app.requests.get', return_value=changed):
            self.assertEqual(self.write('rating', {'rating': 5}, csrf).status_code, 403)

    def test_reports_do_not_hide_until_independent_decision_and_log_restore(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.assertEqual(self.write('review', {'body': 'Original review'}, csrf).status_code, 200)
        review = self.state()['reviews'][0]
        report_body = {'author_id': review['user_id'], 'revision': review['updated'], 'reason': 'spam'}
        reporter_csrf = self.act_as(55, 'reporter')
        self.assertEqual(self.write('report', report_body, reporter_csrf).status_code, 200)
        self.assertEqual(self.write('report', report_body, reporter_csrf).status_code, 409)
        self.assertEqual(self.state()['reviews'][0]['body'], 'Original review')
        self.assertEqual(self.client.get('/api/moderation-log?repo=owner/project').get_json()['events'], [])
        self.assertEqual(self.client.get('/api/reports?repo=owner/project').status_code, 403)
        mod_csrf = self.act_as(77, 'moderator')
        report_id = self.client.get('/api/reports?repo=owner/project').get_json()['reports'][0]['id']
        decision = {'report_id': report_id, 'action': 'hide', 'reason': 'spam'}
        self.assertEqual(self.write('moderate', decision, mod_csrf).status_code, 200)
        self.assertEqual(self.state()['reviews'], [])
        log = self.client.get('/api/moderation-log?repo=owner/project').get_json()['events']
        self.assertEqual((log[0]['action'], log[0]['reason'], log[0]['moderator']), ('hide', 'spam', 'moderator'))
        self.assertNotIn('reporter', log[0])
        self.assertEqual(self.write('moderate', {'report_id': report_id, 'action': 'restore', 'reason': 'no_violation'}, mod_csrf).status_code, 200)
        self.assertEqual(self.state()['reviews'][0]['body'], 'Original review')
        self.assertEqual(len(self.client.get('/api/moderation-log?repo=owner/project').get_json()['events']), 2)

    def test_young_account_cannot_report(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.write('review', {'body': 'Review'}, csrf)
        review = self.state()['reviews'][0]
        young = datetime.now(timezone.utc).isoformat()
        young_csrf = self.act_as(55, 'young', young)
        self.assertEqual(self.write('report', {'author_id': review['user_id'], 'revision': review['updated'], 'reason': 'spam'}, young_csrf).status_code, 403)

    def test_moderator_cannot_decide_own_report_and_stale_review(self):
        self.login(); csrf = self.state()['user']['csrf']
        self.write('review', {'body': 'Original'}, csrf)
        review = self.state()['reviews'][0]
        moderator_csrf = self.act_as(77, 'moderator')
        report_data = {'author_id': review['user_id'], 'revision': review['updated'], 'reason': 'spam'}
        self.assertEqual(self.write('report', report_data, moderator_csrf).status_code, 200)
        report_id = self.client.get('/api/reports?repo=owner/project').get_json()['reports'][0]['id']
        self.assertEqual(self.write('moderate', {'report_id': report_id, 'action': 'hide', 'reason': 'spam'}, moderator_csrf).status_code, 403)
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('INSERT INTO users VALUES (?,?,?)', (55, 'reporter', self.created_at))
            connection.execute('UPDATE reports SET reporter_id=? WHERE id=?', (55, report_id))
            connection.execute('UPDATE reviews SET updated=updated+10 WHERE repo_id=? AND user_id=?', (7, 42))
            connection.commit()
        self.assertEqual(self.write('moderate', {'report_id': report_id, 'action': 'hide', 'reason': 'spam'}, moderator_csrf).status_code, 409)
        self.assertEqual(self.state()['reviews'][0]['body'], 'Original')

    def test_hourly_account_limit_and_invalid_origin(self):
        self.login(); csrf = self.state()['user']['csrf']
        response = self.client.post('/api/rating?repo=owner/project', json={'rating': 5},
                                    headers={'Origin': 'https://evil.example', 'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 403)
        with sqlite_connection(self.app.config['DATABASE']) as connection:
            connection.execute('INSERT INTO write_limits VALUES (?,?,?)', (42, int(time.time()), 20))
            connection.commit()
        self.assertEqual(self.write('rating', {'rating': 5}, csrf).status_code, 429)
        self.assertEqual(self.state()['count'], 0)


def sqlite_connection(path):
    import sqlite3
    return closing(sqlite3.connect(path))


if __name__ == '__main__':
    unittest.main()
