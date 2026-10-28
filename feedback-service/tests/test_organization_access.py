import unittest
import base64
import json
from unittest.mock import patch

import requests
from organization_access import owners, OrganizationUnavailable


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
    def json(self):
        return self.body
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('request failed')


class OrganizationAccessTests(unittest.TestCase):
    def setUp(self):
        self.installation = Response({'id':12, 'account':{'id':99,'type':'Organization','login':'example'},
                                      'permissions':{'members':'read'}, 'suspended_at':None})
        self.token = Response({'token':'test-token','permissions':{'members':'read'}})

    def test_current_owners_and_pagination(self):
        first = [{'id':i, 'type':'User'} for i in range(1,101)]
        second = [{'id':101, 'type':'User'}]
        with patch('organization_access._jwt', return_value='jwt'), patch('organization_access.requests.get', side_effect=[self.installation,Response(first),Response(second)]) as get, patch('organization_access.requests.post', return_value=self.token):
            self.assertEqual(owners('example', 99, 'id', 'key'), set(range(1,102)))
            self.assertEqual(get.call_count, 3)
            self.assertEqual(get.call_args.kwargs['params']['role'], 'admin')

    def test_untrusted_or_unavailable_installations_fail_closed(self):
        for installation in [Response({},404), Response({'id':12,'account':{'id':98},'permissions':{'members':'read'}}),
                             Response({'id':12,'account':{'id':99,'type':'Organization','login':'example'},'permissions':{'members':'read'},'suspended_at':'now'})]:
            with self.subTest(installation=installation.body), patch('organization_access._jwt', return_value='jwt'), patch('organization_access.requests.get', return_value=installation):
                with self.assertRaises(OrganizationUnavailable): owners('example', 99, 'id', 'key')
        with patch('organization_access._jwt', return_value='jwt'), patch('organization_access.requests.get', side_effect=[self.installation,Response([])]), patch('organization_access.requests.post', return_value=self.token):
            with self.assertRaises(OrganizationUnavailable): owners('example', 99, 'id', 'key')

    def test_missing_or_insufficient_permissions_fail_closed(self):
        with self.assertRaises(OrganizationUnavailable): owners('example', 99, '', '')
        with patch('organization_access._jwt', return_value='jwt'), patch('organization_access.requests.get', return_value=self.installation), patch('organization_access.requests.post', return_value=Response({'token':'secret','permissions':{}})):
            with self.assertRaises(OrganizationUnavailable): owners('example', 99, 'id', 'key')

    def test_app_jwt_is_signed_with_the_private_key(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from organization_access import _jwt
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        head, payload, signature = _jwt('123', pem).split('.')
        decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        key.public_key().verify(decode(signature), (head + '.' + payload).encode(), padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(json.loads(decode(payload))['iss'], '123')
