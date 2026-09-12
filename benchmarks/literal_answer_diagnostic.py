"""Post-hoc format diagnostic; never replaces the frozen strict JSON grader.

Accept only bounded JSON or literal Python containers for inspecting values.
No execution, expression repair, class-name normalization or substring scoring.
"""
import ast
from benchmarks.repository_eval import grade_answer,equal_answer


def inspect_values(content,expected):
    primary=grade_answer(content,expected)
    if not primary['parse_error']:
        return {'form':'JSON','values_match':primary['task_success']}
    if not isinstance(content,str) or len(content)>8192:
        return {'form':'unresolved','values_match':None}
    try:
        tree=ast.parse(content.strip(),mode='eval')
        if sum(1 for _ in ast.walk(tree))>512:raise ValueError('Too many nodes')
        def value(node,depth=0):
            if depth>16:raise ValueError('Too deep')
            if isinstance(node,ast.Dict):
                result={}
                for key,item in zip(node.keys,node.values,strict=True):
                    k=value(key,depth+1)
                    if type(k) is not str or k in result:raise ValueError('Non-string or duplicate key')
                    result[k]=value(item,depth+1)
                return result
            if isinstance(node,ast.List):return [value(n,depth+1) for n in node.elts]
            if isinstance(node,ast.Constant) and type(node.value) in (str,int,float,bool,type(None)):
                import math
                if type(node.value) is float and not math.isfinite(node.value):raise ValueError('Non-finite value')
                return node.value
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):
                number=value(node.operand,depth+1)
                if type(number) not in (int,float):raise ValueError('Not a number')
                return -number
            raise ValueError('Not a literal JSON-shaped value')
        parsed=value(tree.body)
    except (ValueError,SyntaxError,RecursionError,TypeError):
        return {'form':'unresolved','values_match':None}
    return {'form':'Python literal','values_match':equal_answer(parsed,expected)}
