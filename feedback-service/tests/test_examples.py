"""Behavioral checks for the public, read-only examples surface."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from app import create_app


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.app = create_app({'TESTING': True, 'DATABASE_URL': '',
                               'DATABASE': str(Path(self.temp.name) / 'preview.sqlite'),
                               'BASE_URL': 'http://localhost'})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_all_examples_are_labelled_and_need_no_database_or_github(self):
        with patch('app.sqlite3.connect', side_effect=AssertionError('Unexpected database access')), \
             patch('app.requests.get', side_effect=AssertionError('Unexpected GitHub request')):
            for rating, expected in [('1', '1.0'), ('2', '2.0'), ('3', '3.0'),
                                     ('4', '4.0'), ('5', '5.0'), ('mixed', '4.2'), ('empty', '—')]:
                for style in ('card', 'compact', 'shield', 'mini'):
                    for theme in ('light', 'dark', 'high-contrast', 'auto'):
                        with self.subTest(rating=rating, style=style, theme=theme):
                            response = self.client.get('/examples/card.svg', query_string={
                                'rating': rating, 'style': style, 'theme': theme,
                                'repo': 'owner/project'})
                            self.assertEqual(response.status_code, 200)
                            root = ET.fromstring(response.data)
                            text = ''.join(root.itertext())
                            self.assertIn('DEMO · FICTIONAL', text)
                            self.assertIn('Not real community feedback', text)
                            self.assertIn(expected, text)
                            self.assertIn('sandbox', response.headers['Content-Security-Policy'])
                            if style == 'card' and rating == 'empty':
                                self.assertIn('No reviews yet', text)
                                self.assertIn('0 ratings', text)
                            if theme == 'auto':
                                self.assertIn('prefers-color-scheme:dark', text)

    def test_examples_ignore_untrusted_values_and_reject_writes(self):
        expected = self.client.get('/examples/card.svg').data
        response = self.client.get('/examples/card.svg', query_string={
            'rating': '<script>alert(1)</script>', 'theme': '"><script>', 'style': '../card'})
        self.assertEqual(response.data, expected)
        self.assertEqual(self.client.post('/examples/card.svg', json={'rating': 5}).status_code, 405)

    def test_home_and_builder_work_without_a_repository_or_remote_access(self):
        with patch('app.sqlite3.connect', side_effect=AssertionError('Unexpected database access')), \
             patch('app.requests.get', side_effect=AssertionError('Unexpected GitHub request')):
            home = self.client.get('/')
            self.assertEqual(home.status_code, 200)
            self.assertIn(b'GitHub repository', home.data)
            self.assertIn(b'/badge', home.data)
            builder = self.client.get('/badge')
            self.assertEqual(builder.status_code, 200)
            self.assertIn(b'Example rating', builder.data)
            self.assertEqual(self.client.get('/badge?repo=owner/project').status_code, 200)
            self.assertEqual(self.client.get('/badge?repo=invalid').status_code, 400)

    def test_mobile_examples_remain_read_only_and_keep_disclosure(self):
        with patch('app.sqlite3.connect', side_effect=AssertionError('Unexpected database access')), \
             patch('app.requests.get', side_effect=AssertionError('Unexpected GitHub request')):
            for rating in ('empty', '1', '5', 'mixed'):
                for theme in ('light', 'dark', 'high-contrast', 'auto'):
                    response = self.client.get('/examples/card.svg', query_string={
                        'rating': rating, 'theme': theme, 'layout': 'mobile'})
                    self.assertEqual(response.status_code, 200)
                    root = ET.fromstring(response.data)
                    self.assertEqual(root.attrib['width'], '280')
                    self.assertIn('DEMO', ''.join(root.itertext()))
                    self.assertIn('Not real community feedback', ''.join(root.itertext()))
            desktop = ET.fromstring(self.client.get('/examples/card.svg').data)
            self.assertEqual(desktop.attrib['width'], '640')
            unknown = ET.fromstring(self.client.get('/examples/card.svg?layout=invalid').data)
            self.assertEqual(unknown.attrib['width'], '640')

    def test_mobile_long_reviews_are_escaped_and_fit_vertical_canvas(self):
        from copy import deepcopy
        from badge import render_badge
        from mobile_badge import wrap_review
        data = {'average': 4.6, 'count': 7, 'security_concerns': 1,
                'reviews': [{'login': 'a-long-account-name', 'owner': True,
                             'body': '<script>' + 'W' * 200 + '世界' * 30} for _ in range(3)]}
        original = deepcopy(data)
        root = ET.fromstring(render_badge(data, 'dark', 'card', 'mobile'))
        self.assertEqual(data, original)
        self.assertNotIn('<script>', ET.tostring(root, encoding='unicode'))
        self.assertIn('4.6 / 5', ''.join(root.itertext()))
        self.assertIn('Security: 1', ''.join(root.itertext()))
        self.assertEqual(wrap_review('W' * 200)[0], 'W' * 16)
        self.assertTrue(wrap_review('W' * 200)[-1].endswith('…'))
        height = float(root.attrib['height'])
        for node in root.iter('{http://www.w3.org/2000/svg}text'):
            self.assertGreater(float(node.attrib['y']), 0)
            self.assertLess(float(node.attrib['y']), height)


if __name__ == '__main__':
    unittest.main()
