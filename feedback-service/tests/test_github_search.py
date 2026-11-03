"""Public search isolation, bounded upstream use, and independent feedback invariants."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from app import create_app
from github_search import GitHubSearch, SearchUnavailable


def repository(name='outside-catalog/new-project', rid=501):
    return {'id':rid, 'full_name':name, 'private':False, 'description':'A real public search result',
            'owner':{'id':99,'type':'User'}, 'language':'Python', 'stargazers_count':123}


class Response:
    def __init__(self, items=None, status=200, total=41, incomplete=False):
        self.status_code=status
        self.data={'items':items if items is not None else [repository()], 'total_count':total,'incomplete_results':incomplete}
    def json(self):
        return self.data


class GitHubSearchTests(unittest.TestCase):
    def test_public_search_pages_and_categories_have_no_credentials_or_redirects(self):
        search=GitHubSearch()
        with patch('github_search.requests.get',return_value=Response()) as get:
            result=search.search('https://github.com/outside-catalog/new-project/','Data','stars',2)
        args=get.call_args
        self.assertEqual(args.args[0],'https://api.github.com/search/repositories')
        self.assertEqual(args.kwargs['params'],{'q':'repo:outside-catalog/new-project topic:database is:public','sort':'stars','order':'desc','page':2,'per_page':20})
        self.assertNotIn('Authorization',args.kwargs['headers']);self.assertFalse(args.kwargs['allow_redirects'])
        self.assertTrue(result['has_next']);self.assertEqual(result['projects'][0]['github_stars'],123)

    def test_cache_is_bounded_independent_and_rate_limits_do_not_create_retry_storms(self):
        search=GitHubSearch()
        with patch('github_search.requests.get',return_value=Response()) as get:
            first=search.search('different');first['projects'][0]['name']='MUTATED'
            self.assertEqual(search.search('different')['projects'][0]['name'],'new-project')
            self.assertEqual(get.call_count,1)
            for index in range(7):search.search('query'+str(index))
            with self.assertRaises(SearchUnavailable) as raised:search.search('over-budget')
            self.assertEqual(raised.exception.status,429);self.assertEqual(get.call_count,8)
        self.assertLessEqual(len(search.cache),64)

    def test_provider_errors_never_masquerade_as_empty_success(self):
        for status in (403,429,422,500,302):
            with self.subTest(status=status),patch('github_search.requests.get',return_value=Response(status=status)):
                with self.assertRaises(SearchUnavailable):GitHubSearch().search('test')
        with patch('github_search.requests.get',side_effect=requests.Timeout()):
            with self.assertRaises(SearchUnavailable):GitHubSearch().search('test')

    def test_private_or_malformed_results_fail_closed(self):
        for item in [dict(repository(),private=True),dict(repository(),full_name='https://evil.test/a'),dict(repository(),id=True)]:
            with self.subTest(item=item['id']),patch('github_search.requests.get',return_value=Response([item])):
                with self.assertRaises(SearchUnavailable):GitHubSearch().search('test')

    def test_incomplete_and_thousand_result_limit_are_explicit(self):
        with patch('github_search.requests.get',return_value=Response(total=99999,incomplete=True)):
            data=GitHubSearch().search('broad',page=50)
        self.assertFalse(data['has_next']);self.assertTrue(data['incomplete'])


class GlobalCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.database=Path(self.temp.name)/'feedback.sqlite3'
        self.app=create_app({'TESTING':True,'DATABASE_URL':'','DATABASE':str(self.database),'BASE_URL':'http://localhost','TURNSTILE_SITE_KEY':'','TURNSTILE_SECRET_KEY':''})
        self.client=self.app.test_client()

    def tearDown(self):self.temp.cleanup()

    def snapshot(self):
        with sqlite3.connect(self.database) as db:return '\n'.join(db.iterdump())

    def test_outside_catalog_search_is_anonymous_and_does_not_register_repositories(self):
        before=self.snapshot()
        with patch('github_search.requests.get',return_value=Response()):
            response=self.client.get('/api/projects?source=github&q=new-project&page=2')
        self.assertEqual(response.status_code,200)
        data=response.get_json();self.assertEqual(data['projects'][0]['repo'],'outside-catalog/new-project')
        self.assertEqual(data['total'],41);self.assertEqual(data['page'],2);self.assertTrue(data['has_next'])
        self.assertNotIn('_github_repo',response.text);self.assertEqual(self.snapshot(),before)

    def seed(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO repositories VALUES (501,'outside-catalog/new-project')")
            for uid in range(1,6):
                db.execute("INSERT INTO users VALUES (?,?,'2020-01-01T00:00:00Z')",(uid,'reader'+str(uid)))
                db.execute('INSERT INTO ratings VALUES (501,?,4,100)',(uid,))
            db.execute("INSERT INTO reviews VALUES (501,1,'Preserve this existing review.',100)")

    def test_existing_feedback_filters_and_owner_exclusion_survive_global_search(self):
        self.seed();before=self.snapshot()
        with patch('github_search.requests.get',return_value=Response()):
            data=self.client.get('/api/projects?source=github&q=new-project&min_rating=4&has_reviews=1&sort=top').get_json()
            self.assertEqual(len(data['projects']),1)
            self.assertEqual(data['projects'][0]['average'],4)
            self.assertEqual(data['projects'][0]['rating_count'],5)
            self.assertEqual(data['projects'][0]['latest_review']['excerpt'],'Preserve this existing review.')
            empty=self.client.get('/api/projects?source=github&q=new-project&min_rating=4.5').get_json()
            self.assertEqual(empty['projects'],[]);self.assertTrue(empty['has_next'])
        self.assertEqual(self.snapshot(),before)

    def test_reused_repository_name_cannot_inherit_old_feedback(self):
        self.seed();before=self.snapshot()
        with patch('github_search.requests.get',return_value=Response([repository(rid=777)])):
            data=self.client.get('/api/projects?source=github&q=new-project').get_json()['projects'][0]
        self.assertIsNone(data['average']);self.assertEqual(data['review_count'],0)
        self.assertEqual(self.snapshot(),before)

    def test_invalid_page_and_upstream_limit_surface_errors_without_writes(self):
        before=self.snapshot()
        for page in ('0','51','invalid'):
            self.assertEqual(self.client.get('/api/projects?source=github&q=test&page='+page).status_code,400)
        with patch('github_search.requests.get',return_value=Response(status=403)):
            response=self.client.get('/api/projects?source=github&q=test')
        self.assertEqual(response.status_code,429);self.assertIn('rate-limited',response.text)
        self.assertEqual(response.headers['Retry-After'],'60')
        self.assertEqual(self.snapshot(),before)
