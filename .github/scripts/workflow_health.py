"""Inspect the real workflow state and periodically publish a small health snapshot."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


RECORD_PATH = '.github/workflow-health.json'
MIN_INTERVAL = timedelta(days=30)


def utc_now():
    return datetime.now(timezone.utc)


def due_for_snapshot(previous, now):
    try:
        recorded = datetime.fromisoformat(previous['recorded_at'].replace('Z', '+00:00'))
        return now - recorded >= MIN_INTERVAL
    except (KeyError, TypeError, ValueError):
        return True


def run_summary(run):
    if run is None:
        return None
    # Explicit allowlist: do not store logs, credentials, environment or script output.
    return {key: run.get(key) for key in (
        'id', 'run_number', 'event', 'status', 'conclusion',
        'created_at', 'updated_at', 'html_url', 'head_sha')}


def maintain(api, repository, branch, now, dry_run=False):
    root = f'/repos/{repository}'
    workflow = root + '/actions/workflows/deploy.yml'
    metadata = api('GET', workflow)
    state = metadata['state']
    enabled = False
    # A manually disabled workflow is an intentional user choice; preserve it.
    if state == 'disabled_inactivity':
        if not dry_run:
            api('PUT', workflow + '/enable')
            state = api('GET', workflow)['state']
            if state != 'active':
                raise RuntimeError('Workflow did not become active after enabling')
            enabled = True
        print('Inactive schedule detected' + (' (dry run)' if dry_run else '; re-enabled'))

    record_endpoint = root + '/contents/' + RECORD_PATH
    existing = None
    previous = {}
    try:
        existing = api('GET', record_endpoint + '?' + urlencode({'ref': branch}))
        previous = json.loads(base64.b64decode(existing['content']))
    except HTTPError as exc:
        if exc.code != 404:
            raise
    except (ValueError, KeyError, TypeError):
        # A malformed previous snapshot should be replaced, not stop maintenance.
        previous = {}

    if not enabled and not due_for_snapshot(previous, now):
        print('Workflow state:', state)
        print('Health snapshot is less than 30 days old; no commit needed.')
        return None

    latest = api('GET', workflow + '/runs?per_page=1')['workflow_runs']
    scheduled = api('GET', workflow + '/runs?event=schedule&per_page=1')['workflow_runs']
    snapshot = {
        'recorded_at': now.isoformat().replace('+00:00', 'Z'),
        'repository': repository,
        'workflow': '.github/workflows/deploy.yml',
        'workflow_state': state,
        'reactivated_after_inactivity': enabled,
        'latest_run': run_summary(latest[0] if latest else None),
        'latest_scheduled_run': run_summary(scheduled[0] if scheduled else None),
        'maintenance_run_url': (
            f'https://github.com/{repository}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
            if os.environ.get('GITHUB_RUN_ID') else None),
    }
    if dry_run:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return snapshot

    body = {
        'message': 'Record workflow health snapshot',
        'branch': branch,
        'content': base64.b64encode(
            (json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n').encode()).decode(),
    }
    if existing:
        body['sha'] = existing['sha']
    # The Contents API creates a commit on the current branch atomically, avoiding
    # pushing an old checkout over newer repository changes.
    saved = api('PUT', record_endpoint, body)
    print('Workflow state:', state)
    print('Health snapshot saved:', saved['commit']['html_url'])
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    repository = os.environ['GITHUB_REPOSITORY']
    branch = os.environ.get('DEFAULT_BRANCH', 'main')
    token = os.environ.get('GITHUB_TOKEN')
    if not token and not args.dry_run:
        raise RuntimeError('GITHUB_TOKEN is required to publish a health snapshot')

    def api(method, path, data=None):
        headers = {'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'wxread-workflow-health'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request('https://api.github.com' + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        with urlopen(request, timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else None

    maintain(api, repository, branch, utc_now(), args.dry_run)


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print(f'GitHub API request failed (HTTP {exc.code}). Check job permissions and repository rules.', file=sys.stderr)
        sys.exit(1)
