"""Permanent adversarial messages: repetition and whitespace can carry meaning."""
import json


def cases():
    first = json.dumps({'message': 'spacing matters here: ' + 'a  b ' * 20})
    second = json.dumps({'message': 'spacing matters here: ' + 'a b ' * 20})
    repeated = 'The payment processor recorded an accepted transaction for account EXAMPLE-42.'
    license_text = '# MIT License\n# Redistribution requires this exact notice.\n# Keep the attribution to Example Authors.\n'
    ordered = [
        {'role': 'user', 'content': 'Record the following events in their original order.'},
        {'role': 'assistant', 'content': repeated + '\n\n' + repeated,
         'tool_calls': [{'id': 'synthetic-call-1', 'type': 'function',
                         'function': {'name': 'read_events', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'synthetic-call-1', 'content': ('Historical event record. ' * 150)},
        {'role': 'user', 'content': 'Which message came immediately before the tool result? Count the accepted transactions.'},
    ]
    data = [
        ('distinct_string_literals', first+'\n\n'+second,
         'Are the two message strings byte-identical? Quote each exact value.'),
        ('repeated_events', '\n\n'.join([repeated]*4),
         'How many accepted transaction records appear? Count occurrences, including identical records.'),
        ('license_notice', license_text+'\nOrdinary project description. '*20,
         'Quote the complete license notice, including all attribution requirements.'),
        ('literal_blank_lines', 'BEGIN_LITERAL\r\n\r\n\r\n  keep these spaces  \r\n\r\nEND_LITERAL',
         'Describe the exact line endings, blank lines, and leading and trailing spaces.'),
    ]
    result = [{'id': key, 'messages': [{'role': 'user', 'content': context},
                                     {'role': 'user', 'content': question}]}
              for key, context, question in data]
    result.append({'id': 'message_order_and_tool_metadata', 'messages': ordered})
    return result
