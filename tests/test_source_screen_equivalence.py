"""The cheap screen must preserve the original regex policy on boundary cases."""
from npk.pack.source_policy import PATTERNS,check_source
from npk.pack.format import PackError


def test_literal_prefilter_preserves_recognition_at_token_and_unicode_boundaries():
    values=['nvapi-'+'A'*64,'sk-proj-'+'B'*80,'sk-svcacct-'+'C'*50,'sk-'+'D'*32,
            'AKIA'+'E'*16,'ASIA'+'F'*16,
            *['gh'+letter+'_'+'G'*36 for letter in 'pousr'],'github_pat_'+'H'*40,
            *['-----BEGIN '+kind+'PRIVATE KEY-----' for kind in ('','RSA ','EC ','DSA ','OPENSSH ','ENCRYPTED ')]]
    for value in values:
        for changed in (value,value.lower(),value.upper(),value[:10],value[1:]):
            for prefix in ('','word','./','\u2028','漢字','\n'):
                text=prefix+changed+' end'
                expected=any(pattern.search(text) for _,pattern in PATTERNS)
                rejected=False
                try:check_source(text,'synthetic-input.py')
                except PackError:rejected=True
                assert rejected==bool(expected),'screen changed the supported regex recognition policy'
