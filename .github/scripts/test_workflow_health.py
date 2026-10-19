import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('workflow_health', Path(__file__).with_name('workflow_health.py'))
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class MaintenanceTests(unittest.TestCase):
    def fake_api(self, state, previous=None):
        calls = []
        current = [state]
        def api(method, path, data=None):
            calls.append((method, path, data))
            if path.endswith('/enable'):
                current[0] = 'active'
                return None
            if '/contents/' in path:
                if method == 'PUT':
                    return {'commit': {'html_url': 'https://example.test/commit'}}
                if previous is None:
                    raise HTTPError(path, 404, 'Not found', {}, None)
                import base64
                return {'sha': 'old-record', 'content': base64.b64encode(json.dumps(previous).encode()).decode()}
            if '/runs?' in path:
                return {'workflow_runs': [{'id': 123, 'status': 'completed', 'conclusion': 'failure', 'secret': 'must-not-copy'}]}
            return {'state': current[0]}
        return api, calls

    def test_fresh_snapshot_does_not_commit(self):
        now = datetime.now(timezone.utc)
        api, calls = self.fake_api('active', {'recorded_at': now.isoformat()})
        health.maintain(api, 'owner/repo', 'main', now)
        self.assertFalse(any(method == 'PUT' for method, _, _ in calls))

    def test_disabled_inactivity_is_enabled_and_recorded(self):
        api, calls = self.fake_api('disabled_inactivity')
        snapshot = health.maintain(api, 'owner/repo', 'main', datetime.now(timezone.utc))
        self.assertTrue(snapshot['reactivated_after_inactivity'])
        self.assertEqual(snapshot['workflow_state'], 'active')
        self.assertEqual(snapshot['latest_scheduled_run']['conclusion'], 'failure')
        self.assertNotIn('secret', snapshot['latest_scheduled_run'])
        self.assertTrue(any(path.endswith('/enable') for _, path, _ in calls))

    def test_manual_disable_is_preserved(self):
        api, calls = self.fake_api('disabled_manually')
        health.maintain(api, 'owner/repo', 'main', datetime.now(timezone.utc))
        self.assertFalse(any(path.endswith('/enable') for _, path, _ in calls))

    def test_old_snapshot_updates_with_file_sha(self):
        now = datetime.now(timezone.utc)
        api, calls = self.fake_api('active', {'recorded_at': (now-timedelta(days=31)).isoformat()})
        health.maintain(api, 'owner/repo', 'main', now)
        writes = [body for method, path, body in calls if method == 'PUT']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['sha'], 'old-record')

    def test_dry_run_never_mutates(self):
        api, calls = self.fake_api('disabled_inactivity')
        health.maintain(api, 'owner/repo', 'main', datetime.now(timezone.utc), dry_run=True)
        self.assertFalse(any(method == 'PUT' for method, _, _ in calls))


if __name__ == '__main__':
    unittest.main()
