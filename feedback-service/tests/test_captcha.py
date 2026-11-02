from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch

import requests
from werkzeug.exceptions import Forbidden, ServiceUnavailable
from captcha import validate_token


class CaptchaTests(unittest.TestCase):
    def test_partial_configuration_is_refused_before_database_access(self):
        from app import create_app
        with patch('app.sqlite3.connect') as connect, self.assertRaisesRegex(ValueError,'both site and secret'):
            create_app({'TURNSTILE_SITE_KEY':'site','TURNSTILE_SECRET_KEY':''})
        connect.assert_not_called()

    def valid(self):
        return {'success':True, 'action':'feedback', 'hostname':'example.com',
                'challenge_ts':datetime.now(timezone.utc).isoformat()}

    def test_missing_token_never_calls_provider(self):
        with patch('captcha.requests.post') as provider, self.assertRaises(Forbidden):
            validate_token('', 'secret', 'https://example.com')
        provider.assert_not_called()

    def test_success_and_replay_rejection_require_server_validation(self):
        with patch('captcha.requests.post') as provider:
            provider.return_value.json.return_value=self.valid()
            validate_token('single-use-token', 'secret', 'https://example.com')
            self.assertEqual(provider.call_args.kwargs['timeout'],(5,10))
            provider.return_value.json.return_value={'success':False,'error-codes':['timeout-or-duplicate']}
            with self.assertRaises(Forbidden):
                validate_token('single-use-token','secret','https://example.com')

    def test_wrong_host_action_and_expiry_are_rejected(self):
        for fields in ({'hostname':'attacker.com'},{'action':'login'},
                       {'challenge_ts':(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()}):
            with self.subTest(fields=fields), patch('captcha.requests.post') as provider:
                provider.return_value.json.return_value={**self.valid(),**fields}
                with self.assertRaises(Forbidden):
                    validate_token('token','secret','https://example.com')

    def test_provider_failure_does_not_allow_submission(self):
        with patch('captcha.requests.post',side_effect=requests.Timeout()), self.assertRaises(ServiceUnavailable):
            validate_token('token','secret','https://example.com')
