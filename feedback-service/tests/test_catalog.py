"""Independent catalog expectations: privacy, owner exclusion and ranking eligibility."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class RepoResponse:
    status_code = 200
    def json(self):
        return {'id':7, 'full_name':'facebook/react', 'private':False, 'owner':{'id':99, 'type':'User'}}
    def raise_for_status(self):
        pass


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = str(Path(self.temp.name)/'catalog.sqlite')
        self.app = create_app({'TESTING':True, 'DATABASE_URL':'', 'DATABASE':self.path,
                               'BASE_URL':'http://localhost', 'TURNSTILE_SITE_KEY':'', 'TURNSTILE_SECRET_KEY':''})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO repositories VALUES (7,'facebook/react')")
            for uid in (1,2,3,4,5,6,99):
                db.execute('INSERT INTO users VALUES (?,?,?)',(uid,'reviewer-'+str(uid),'2020-01-01T00:00:00Z'))
                db.execute('INSERT INTO ratings VALUES (?,?,?,?)',(7,uid,4 if uid!=99 else 1,100))
            db.execute("INSERT INTO reviews VALUES (7,1,'A useful, real review.',101)")
            db.execute("INSERT INTO reviews VALUES (7,6,'PRIVATE HIDDEN TEXT',102)")
            db.execute("INSERT INTO reports VALUES ('r',7,6,102,1,'spam',103)")
            db.execute("INSERT INTO moderation_events VALUES ('m','r',7,6,102,77,'hide','spam',104)")
            db.execute("INSERT INTO users VALUES (8,'young','2999-01-01T00:00:00Z')")
            db.execute('INSERT INTO ratings VALUES (7,8,1,105)')
            db.execute("INSERT INTO reviews VALUES (7,8,'NOT PUBLIC YET',106)")

    def test_empty_catalog_never_invents_scores_or_resolves_every_project(self):
        with patch('app.requests.get',side_effect=AssertionError('Unexpected network')):
            result=self.client.get('/api/projects').get_json()
        self.assertTrue(result['projects'])
        self.assertTrue(all(p['average'] is None and p['rating_count']==0 and p['latest_review'] is None for p in result['projects']))
        self.assertEqual(self.client.get('/api/projects?sort=top').get_json()['projects'],[])

    def test_rating_and_excerpt_match_public_rules_without_mutation(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            before='\n'.join(db.iterdump())
        with patch('app.requests.get',return_value=RepoResponse()):
            response=self.client.get('/api/projects?q=facebook/react&sort=top')
        self.assertEqual(response.status_code,200)
        data=response.get_json(); self.assertEqual(len(data['projects']),1)
        p=data['projects'][0]
        self.assertEqual((p['average'],p['rating_count'],p['review_count']),(4.0,5,1))
        self.assertTrue(p['top_eligible']); self.assertEqual(p['security_status'],'not_assessed')
        self.assertEqual(p['latest_review']['excerpt'],'A useful, real review.')
        self.assertNotIn('PRIVATE HIDDEN TEXT',response.text); self.assertNotIn('NOT PUBLIC YET',response.text)
        self.assertNotIn('reporter',response.text)
        with sqlite3.connect(self.path) as db:
            self.assertEqual('\n'.join(db.iterdump()),before)

    def test_ownership_failure_withholds_rating_and_ranking_but_keeps_public_review(self):
        self.seed()
        import requests
        with patch('app.requests.get',side_effect=requests.ConnectionError()):
            # Avoid the external retry sleeps; this failure is already independently supplied.
            with patch('http_retry.time.sleep'):
                data=self.client.get('/api/projects?q=facebook/react').get_json()['projects'][0]
        self.assertFalse(data['ratings_available']); self.assertFalse(data['top_eligible'])
        self.assertIsNone(data['average']); self.assertEqual(data['review_count'],1)

    def test_legacy_owner_review_remains_visible_but_is_labeled_and_never_affects_score(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO reviews VALUES (7,99,'Legacy owner review',200)")
        with patch('app.requests.get',return_value=RepoResponse()):
            data=self.client.get('/api/projects?q=facebook/react').get_json()['projects'][0]
        self.assertEqual((data['average'],data['rating_count'],data['review_count']),(4.0,5,2))
        self.assertTrue(data['latest_review']['owner'])
        self.assertNotIn('user_id',data['latest_review'])

    def test_database_outage_is_unknown_instead_of_zero_or_fake_security(self):
        with patch('app.sqlite3.connect',side_effect=sqlite3.OperationalError('Unavailable')):
            data=self.client.get('/api/projects?q=facebook/react').get_json()['projects'][0]
        self.assertFalse(data['feedback_available']); self.assertFalse(data['ratings_available'])
        self.assertIsNone(data['average']); self.assertEqual(data['security_status'],'not_assessed')
