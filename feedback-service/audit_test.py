"""Compare explicitly marked test entries and card to the verified mirror."""
import argparse
from pathlib import Path
from xml.etree import ElementTree
import requests
from journal_mirror import load
from audit_feedback import fetch_json


def check(entries, repo_id, owner_id, data, card):
    latest = {}
    for item in entries:
        e = item['event']
        if e['repo_id'] == str(repo_id) and e.get('user_id') == str(owner_id) and e['kind'] in ('test_rating','test_review'):
            if e['details'].get('test_only') is not True:
                raise ValueError('Test event is not marked as test-only')
            latest[e['kind']] = e['details']
    if data.get('test_only') is not True or data.get('rating') != latest.get('test_rating') or data.get('review') != latest.get('test_review'):
        raise ValueError('Test feedback differs from the signed journal')
    root = ElementTree.fromstring(card)
    text = ' '.join(''.join(n.itertext()) for n in root.iter() if n.tag.endswith('text'))
    if 'TEST ONLY' not in text:
        raise ValueError('Test card is not clearly marked')
    if data['rating'] and f"{data['rating']['rating']:.1f} / 5" not in text:
        raise ValueError('Test card rating differs from signed journal')
    if data['review']:
        import textwrap
        lines = textwrap.wrap(' '.join(data['review']['body'].split()), width=38, max_lines=3, placeholder='…') or ['']
        if any(line not in text for line in lines):
            raise ValueError('Test card review differs from signed journal')
    return len(latest)


def run(origin, repo, path, key):
    entries, _, _ = load(path, key)
    metadata = fetch_json('https://api.github.com/repos/' + repo)
    data = fetch_json(origin + '/api/test-feedback', {'repo':repo})
    response = requests.get(origin + '/test-card.svg',params={'repo':repo},timeout=20,allow_redirects=False)
    response.raise_for_status()
    count = check(entries, metadata['id'], metadata['owner']['id'], data, response.content)
    print('Verified test events:', count)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin'); parser.add_argument('repo'); parser.add_argument('mirror',type=Path); parser.add_argument('public_key')
    args = parser.parse_args()
    run(args.origin,args.repo,args.mirror,args.public_key)
