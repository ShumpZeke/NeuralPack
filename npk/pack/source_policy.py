"""Deterministic rejection of recognized credential-shaped input.

This is a limited pattern screen, not proof that arbitrary source is secret-free.
It rejects the build instead of modifying source or omitting matching passages.
"""
import re
from .format import PackError


PATTERNS=(
    ('nvidia',re.compile(r'nvapi-[A-Za-z0-9_-]{30,}')),
    ('openai',re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}')),
    ('aws',re.compile(r'(?:AKIA|ASIA)[0-9A-Z]{16}')),
    ('github',re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})')),
    ('private_key',re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')),
)


def safe_label(path):
    value=str(path)
    for _,pattern in PATTERNS:value=pattern.sub('[credential]',value)
    return value


def check_source(text,path):
    for name,pattern in PATTERNS:
        # Every supported OpenAI match contains this literal. Avoid running a
        # word-boundary regex across ordinary files that cannot contain a match.
        if name=='openai' and 'sk-' not in text:continue
        if pattern.search(text):
            raise PackError(f'source contains potential credential ({name}): {safe_label(path)}; '
                            'remove it from the source or compile a reviewed source collection')


def stat_identity(st):
    return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
