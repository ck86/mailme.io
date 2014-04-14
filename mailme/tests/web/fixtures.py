import json
import re

import httpretty
import pytest

from social.apps.django_app.default.models import DjangoStorage
from social.backends.google import GoogleOAuth2
from social.p3 import urlparse
from social.strategies.django_strategy import DjangoStrategy
from social.utils import parse_qs


def handle_state(backend, start_url, target_url):
    try:
        if backend.STATE_PARAMETER or backend.REDIRECT_STATE:
            query = parse_qs(urlparse(start_url).query)
            target_url = target_url + ('?' in target_url and '&' or '?')
            if 'state' in query or 'redirect_state' in query:
                name = 'state' in query and 'state' or 'redirect_state'
                target_url += '{0}={1}'.format(name, query[name])
    except AttributeError:
        pass
    return target_url


@pytest.yield_fixture
def facebook_auth():
    httpretty.enable()

    def callback(method, uri, headers):
        if 'graph.facebook.com/oauth/access_token' in uri:
            body = 'access_token=test_access_token&expires=5156423'
        elif 'graph.facebook.com/me' in uri:
            body = json.dumps({
                'id': '12345',
                'name': 'Foo Bar',
                'username': 'foo.bar',
                'email': 'foobar@googlemail.com'
            })
        else:
            raise Exception('API call without mocking: {0}.'.format(uri))
        return (200, headers, body)

    httpretty.register_uri(httpretty.GET, re.compile(r'.*'), body=callback)

    yield

    httpretty.disable()
    httpretty.reset()


@pytest.yield_fixture
def twitter_auth():
    httpretty.enable()

    request_token_body = '&'.join([
        'oauth_token=test_request_token',
        'oauth_token_secret=test_request_token_secret',
        'oauth_callback_confirmed=true'])
    httpretty.register_uri(
        httpretty.GET,
        re.compile(r'.*api\.twitter\.com/oauth/request_token'),
        body=request_token_body)

    access_token_body = '&'.join([
        'oauth_token=test_access_token',
        'oauth_token_secret=test_access_token_secret',
        'user_id=12345',
        'screen_name=pappeldackel'])
    httpretty.register_uri(
        httpretty.GET,
        re.compile(r'.*api\.twitter\.com/oauth/access_token'),
        body=access_token_body)

    verify_credentials_body = json.dumps({
        'id': 12345,
        'name': 'Foo Bar',
        'screen_name': 'foobar',
        'notifications': False})
    httpretty.register_uri(
        httpretty.GET,
        re.compile(r'.*twitter\.com/1\.1/account/verify_credentials\.json'),
        body=verify_credentials_body)

    yield {'oauth_token': 'test_request_token'}

    httpretty.disable()
    httpretty.reset()


@pytest.yield_fixture
def google_auth():
    # TODO: This could be abstracted for twitter and facebook too.
    httpretty.enable()

    def _method(method):
        return {'GET': httpretty.GET,
                'POST': httpretty.POST}[method]

    strategy = DjangoStrategy(GoogleOAuth2, DjangoStorage)

    start_url = strategy.start().url

    target_url = handle_state(
        GoogleOAuth2,
        start_url,
        strategy.build_absolute_uri('/complete/{0}/?code=foobar')
    )

    httpretty.register_uri(
        httpretty.GET,
        start_url,
        status=301,
        location=target_url
    )

    httpretty.register_uri(
        httpretty.GET,
        target_url,
        status=200,
        body='foobar'
    )

    httpretty.register_uri(
        _method(GoogleOAuth2.ACCESS_TOKEN_METHOD),
        uri=GoogleOAuth2.ACCESS_TOKEN_URL,
        status=200,
        body=json.dumps({
            'access_token': 'foobar',
            'token_type': 'bearer'}),
        content_type='text/json'
    )

    user_data_url = 'https://www.googleapis.com/oauth2/v1/userinfo'

    if user_data_url:
        httpretty.register_uri(
            httpretty.GET,
            user_data_url,
            body=json.dumps({
                'email': 'foo@bar.com',
                'id': '101010101010101010101'}),
            content_type='application/json'
        )

    yield

    httpretty.disable()
    httpretty.reset()
