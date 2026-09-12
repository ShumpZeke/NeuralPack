"""New deterministic behavior questions for frozen Requests/urllib3/Packaging.

Expected values must be produced by executing these probes against the captured
package sources. No request is sent, no sleep is performed, and no model is used.
Questions are development evaluation data, not an unseen-generalization claim.
"""
from contextlib import contextmanager


TASKS = [
    {'id':'retry_captured_default','package':'urllib3',
     'query':'In urllib3 2.7.0, after the retry module has been imported, set Retry.DEFAULT_BACKOFF_MAX to 7. '
             'Create one Retry with no backoff_max argument and another with backoff_max=Retry.DEFAULT_BACKOFF_MAX. '
             'What backoff_max values do the two instances hold? Return JSON keys omitted and explicit. '
             'Do not reload the module or alter function defaults.'},
    {'id':'retry_empty_methods','package':'urllib3',
     'query':'In urllib3 2.7.0, three Retry policies have total=2 and status_forcelist=[503]. '
             'Their allowed_methods settings are respectively omitted, None, and an empty list. '
             'For each policy, does a POST response with status 503 qualify for a status retry, with no Retry-After header? '
             'Return JSON booleans under default, none and empty. Do not perform or increment a request.'},
    {'id':'retry_false_zero','package':'urllib3',
     'query':'In urllib3 2.7.0, construct Retry(total=False) and Retry(total=0), leaving redirect and '
             'raise_on_redirect unspecified. What redirect and raise_on_redirect attributes does each hold? '
             'Return JSON objects under false_total and zero_total; each has keys redirect and raises. '
             'Preserve the distinction between null, zero and false.'},
    {'id':'retry_backoff_history','package':'urllib3',
     'query':'In urllib3 2.7.0, compute backoff without sleeping or adding jitter. Use backoff_factor=0.5. '
             'Compare these oldest-to-newest histories: three errors with no redirect; three errors, a redirect, '
             'then one error; and three errors, a redirect, then two errors. All non-redirect history entries '
             'have redirect_location=None; the redirect entry has /next. Also cap the third policy at backoff_max=0.75. '
             'Return JSON numbers under three_errors, after_one, after_two and capped.'},
    {'id':'retry_after_cap','package':'urllib3',
     'query':'In urllib3 2.7.0, parse numeric Retry-After headers directly, without sleeping. '
             'What does header "99999" produce with default settings and with retry_after_max=5? '
             'With default settings, what does "0" produce and what exception class, if any, does "-1" raise? '
             'Return JSON keys default, configured, zero and negative. Do not treat "-1" as a valid date.'},
    {'id':'session_none_merge','package':'requests',
     'query':'In Requests 2.34.2, merge per-request settings {"a": null, "c": 3} with session settings '
             '{"a": 1, "b": 2, "d": null} using the ordinary setting merge helper and default dictionary class. '
             'Also merge an entirely None request setting with the same session dictionary. '
             'Return the resulting mappings as JSON keys mapping_override and no_override.'},
    {'id':'session_empty_hooks','package':'requests',
     'query':'In Requests 2.34.2, the session response-hook list contains a function named session_hook. '
             'Compare merging a request response-hook list that is empty with one containing request_hook. '
             'Use the session hook-merging helper; do not invoke either hook. '
             'Return the resulting hook-name arrays as JSON keys empty_request and populated_request.'},
    {'id':'json_encoding_patterns','package':'requests',
     'query':'In Requests 2.34.2, apply its byte-pattern JSON encoding guesser to byte strings written here in hexadecimal: '
             'fffe0000, 007b0022, 7b006162, and the empty byte string. '
             'Return the encoding names or null in that order as a JSON array. Do not actually decode or parse JSON.'},
    {'id':'uri_unreserved_only','package':'requests',
     'query':'In Requests 2.34.2, its URI unreserved-character unquoting helper receives '
             'a%2Fb%7Ec%20d%41 and bad%GG. Give each exact returned string or exception class as '
             'JSON keys valid and invalid. Reserved slash and space escapes must follow the implementation; '
             'do not substitute a generic URL decoder.'},
    {'id':'version_normalization_order','package':'packaging',
     'query':'In Packaging 26.3, normalize version strings v1.0-1 and 1.0+AB.01 using Version. '
             'Then sort 1.0.post1, 1.0, 1.0a1 and 1.0.dev1 in ascending version order. '
             'Return JSON keys normalized (two strings in input order) and ordered (four strings).'},
    {'id':'specifier_prerelease_fallback','package':'packaging',
     'query':'In Packaging 26.3, with prereleases unspecified, test membership of 1.1a1 in SpecifierSet(">=1.0"). '
             'Also filter the list ["1.1a1"] through that same set and through an empty SpecifierSet. '
             'Return JSON keys contains (boolean), constrained_filter (array), and empty_filter (array).'},
    {'id':'specifier_local_versions','package':'packaging',
     'query':'In Packaging 26.3, test the version 1.0+linux.1 against each individual specifier '
             '==1.0, ===1.0, <=1.0 and ==1.0+linux.1 using contains. '
             'Return four booleans in that order as a JSON array. Distinguish arbitrary equality from version equality.'},
]


def probe(task_id):
    from urllib3.util.retry import Retry, RequestHistory
    from requests.sessions import merge_setting, merge_hooks
    from requests.utils import guess_json_utf, unquote_unreserved
    from packaging.version import Version
    from packaging.specifiers import Specifier, SpecifierSet

    def capture(call):
        try: return call()
        except Exception as error: return type(error).__name__

    if task_id=='retry_captured_default':
        old=Retry.DEFAULT_BACKOFF_MAX
        try:
            Retry.DEFAULT_BACKOFF_MAX=7
            return {'omitted':Retry().backoff_max,'explicit':Retry(backoff_max=Retry.DEFAULT_BACKOFF_MAX).backoff_max}
        finally:Retry.DEFAULT_BACKOFF_MAX=old
    if task_id=='retry_empty_methods':
        return {key:Retry(total=2,status_forcelist=[503],**kw).is_retry('POST',503,has_retry_after=False)
                for key,kw in [('default',{}),('none',{'allowed_methods':None}),('empty',{'allowed_methods':[]})]}
    if task_id=='retry_false_zero':
        return {key:{'redirect':r.redirect,'raises':r.raise_on_redirect} for key,r in
                [('false_total',Retry(total=False)),('zero_total',Retry(total=0))]}
    if task_id=='retry_backoff_history':
        e=RequestHistory('GET','/',None,503,None);d=RequestHistory('GET','/',None,302,'/next')
        groups=[('three_errors',(e,e,e),{}),('after_one',(e,e,e,d,e),{}),
                ('after_two',(e,e,e,d,e,e),{}),('capped',(e,e,e,d,e,e),{'backoff_max':.75})]
        return {key:Retry(backoff_factor=.5,history=hist,backoff_jitter=0,**kw).get_backoff_time() for key,hist,kw in groups}
    if task_id=='retry_after_cap':
        return {'default':Retry().parse_retry_after('99999'),'configured':Retry(retry_after_max=5).parse_retry_after('99999'),
                'zero':Retry().parse_retry_after('0'),'negative':capture(lambda:Retry().parse_retry_after('-1'))}
    if task_id=='session_none_merge':
        session={'a':1,'b':2,'d':None}
        return {'mapping_override':dict(merge_setting({'a':None,'c':3},session)),
                'no_override':dict(merge_setting(None,session))}
    if task_id=='session_empty_hooks':
        def session_hook():raise AssertionError('Hook must not execute')
        def request_hook():raise AssertionError('Hook must not execute')
        return {key:[f.__name__ for f in merge_hooks({'response':hooks},{'response':[session_hook]})['response']]
                for key,hooks in [('empty_request',[]),('populated_request',[request_hook])]}
    if task_id=='json_encoding_patterns':
        return [guess_json_utf(bytes.fromhex(s)) for s in ('fffe0000','007b0022','7b006162','')]
    if task_id=='uri_unreserved_only':
        return {'valid':unquote_unreserved('a%2Fb%7Ec%20d%41'),'invalid':capture(lambda:unquote_unreserved('bad%GG'))}
    if task_id=='version_normalization_order':
        return {'normalized':[str(Version(v)) for v in ('v1.0-1','1.0+AB.01')],
                'ordered':[str(v) for v in sorted(map(Version,('1.0.post1','1.0','1.0a1','1.0.dev1')))]}
    if task_id=='specifier_prerelease_fallback':
        constrained=SpecifierSet('>=1.0')
        return {'contains':constrained.contains('1.1a1'),'constrained_filter':list(constrained.filter(['1.1a1'])),
                'empty_filter':list(SpecifierSet().filter(['1.1a1']))}
    if task_id=='specifier_local_versions':
        return [Specifier(s).contains('1.0+linux.1') for s in ('==1.0','===1.0','<=1.0','==1.0+linux.1')]
    raise ValueError('Unknown behavior task')
