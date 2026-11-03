"""Bounded, anonymous public repository search. No tokens or database writes."""
from collections import OrderedDict, deque
from copy import deepcopy
import re
from threading import Lock
import time

import requests

PAGE_SIZE = 20
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$')
TOPICS = {'Interfaces':'frontend', 'Backend':'backend', 'AI & ML':'machine-learning',
          'Developer tools':'developer-tools', 'Languages':'programming-language',
          'Data':'database', 'Service testing':'community-feedback'}


class SearchUnavailable(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class GitHubSearch:
    def __init__(self):
        self.cache = OrderedDict()
        self.calls = deque()
        self.lock = Lock()
        self.cooldown = 0

    def search(self, query, topic='', sort='', page=1):
        query = re.sub(r'^https?://github\.com/', '', query.strip(), flags=re.I).strip('/')
        if NAME.fullmatch(query):
            query = 'repo:' + query
        if topic in TOPICS:
            query += ' topic:' + TOPICS[topic]
        query = query.strip() + ' is:public'
        upstream_sort = sort if sort in ('stars', 'updated') else ''
        key = (query, upstream_sort, page)
        with self.lock:
            now = time.monotonic()
            for expired in [k for k, (expires, _) in self.cache.items() if expires <= now]:
                del self.cache[expired]
            if key in self.cache:
                self.cache.move_to_end(key)
                return deepcopy(self.cache[key][1])
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if now < self.cooldown or len(self.calls) >= 8:
                raise SearchUnavailable('GitHub search is temporarily rate-limited. Wait a minute and try again.', 429)
            self.calls.append(now)
            params = {'q':query, 'per_page':PAGE_SIZE, 'page':page}
            if upstream_sort:
                params.update(sort=upstream_sort, order='desc')
            try:
                response = requests.get('https://api.github.com/search/repositories', params=params,
                    headers={'Accept':'application/vnd.github+json', 'User-Agent':'community-feedback-service'},
                    timeout=(5, 12), allow_redirects=False)
                if response.status_code in (403, 429):
                    self.cooldown = time.monotonic() + 60
                    raise SearchUnavailable('GitHub search is temporarily rate-limited. Wait a minute and try again.', 429)
                if response.status_code == 422:
                    raise SearchUnavailable('GitHub could not understand this search. Try a project name or a simpler query.', 400)
                if response.status_code != 200:
                    raise ValueError('Unexpected search status')
                data = response.json()
                if (not isinstance(data, dict) or type(data.get('total_count')) is not int
                        or data['total_count'] < 0 or not isinstance(data.get('items'), list)
                        or len(data['items']) > PAGE_SIZE or type(data.get('incomplete_results')) is not bool):
                    raise ValueError('Invalid search envelope')
                projects = []
                for item in data['items']:
                    owner = item.get('owner') or {}
                    name = item.get('full_name', '')
                    if (item.get('private') is not False or not isinstance(name, str) or not NAME.fullmatch(name)
                            or type(item.get('id')) is not int or item['id'] <= 0
                            or type(owner.get('id')) is not int or owner.get('type') not in ('User','Organization')):
                        raise ValueError('Invalid public repository')
                    projects.append({'repo':name, 'name':name.split('/')[1],
                        'description':str(item.get('description') or 'No description provided.')[:320],
                        'topic':topic or str(item.get('language') or 'GitHub project')[:60],
                        'github_stars':max(0, int(item.get('stargazers_count', 0))),
                        '_github_repo':{'id':item['id'], 'full_name':name, 'private':False,
                                        'owner':{'id':owner['id'], 'type':owner['type']}}})
                result = {'projects':projects, 'total':data['total_count'], 'incomplete':data['incomplete_results'],
                          'page':page, 'has_next':page * PAGE_SIZE < min(1000, data['total_count']) and bool(projects)}
            except (requests.RequestException, ValueError, TypeError, AttributeError, OverflowError):
                raise SearchUnavailable('GitHub search is unavailable. Try again later. Your reviews are unchanged.') from None
            self.cache[key] = (time.monotonic() + 120, result)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
            return deepcopy(result)
