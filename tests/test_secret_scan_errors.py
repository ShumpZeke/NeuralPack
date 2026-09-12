"""An incomplete working-tree scan cannot be recorded as clean."""
from pathlib import Path
from types import SimpleNamespace
import pytest
import test_secrets as scanner


@pytest.mark.parametrize('failure',['permission','missing','invalid_utf8'])
def test_scan_read_failures_are_visible_without_echoing_values(tmp_path,monkeypatch,failure):
    path=tmp_path/'fixture.py'
    if failure=='invalid_utf8':path.write_bytes(b'header\xfftail')
    elif failure!='missing':path.write_text('value = 7\n')
    monkeypatch.setattr(scanner,'REPO_ROOT',tmp_path)
    monkeypatch.setattr(scanner.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='fixture.py\n'))
    if failure=='permission':
        original=Path.read_text
        def unreadable(self,*a,**k):
            if self==path:raise PermissionError(scanner.SYNTHETIC_NVIDIA_KEY)
            return original(self,*a,**k)
        monkeypatch.setattr(Path,'read_text',unreadable)
    message=None
    try:scanner.test_no_secrets_in_tracked_files()
    except AssertionError as error:message=str(error)
    assert message is not None, 'an incomplete scan was recorded as clean'
    assert 'fixture.py' in message and 'incomplete' in message.lower()
    assert scanner.SYNTHETIC_NVIDIA_KEY not in message
