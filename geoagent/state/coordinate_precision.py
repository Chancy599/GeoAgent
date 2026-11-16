"""Shared three-decimal serialization of generated geometry (not measurements)."""
import math
import re

DECIMALS = 3
QUANTUM = 10 ** -DECIMALS
NUM = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
VALUE = r'('+NUM+r')(\s*(?:cm|mm|pt|in|em|ex)\b)?'
PT_PER_CM = 72.27 / 2.54
_CARTESIAN = re.compile(r'\s*(' + NUM + r')\s*(pt)?\s*,\s*(' + NUM + r')\s*(pt)?\s*')


def cartesian_values(token):
    """Parse a plain Cartesian pair or a pair of explicit TeX pt dimensions."""
    match = _CARTESIAN.fullmatch(token)
    if match is None or match[2] != match[4]:
        return None
    scale = PT_PER_CM if match[2] else 1
    return [float(match[1]) / scale, float(match[3]) / scale]


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Nonfinite coordinate')
    result = f'{value:.{DECIMALS}f}'
    return '0.000' if result == '-0.000' else result


def quantize_tex(tex):
    """Round numeric Cartesian/polar coordinates and explicit curve dimensions.

    Point names, label text, styles and comments remain intact. Computation and
    reference JSON retain floating precision; only exported geometry is rounded.
    """
    pattern = r'\(\s*'+VALUE+r'\s*([,:])\s*'+VALUE+r'(?:\s*:\s*'+VALUE+r')?\s*\)'
    def coordinate(match):
        a, au, separator, b, bu, c, cu = match.groups()
        result = '('+number(a)+(au or '').strip()+separator+number(b)+(bu or '').strip()
        if c is not None:
            result += ':'+number(c)+(cu or '').strip()
        return result+')'
    def fragment(text):
        text = re.sub(pattern, coordinate, text)
        text = re.sub(r'\b(circle)\s*\(\s*'+VALUE+r'\s*\)',
                      lambda m: m[1]+' ('+number(m[2])+(m[3] or '').strip()+')', text)
        return re.sub(r'\b((?:(?:x|y)\s+)?radius|start\s+angle|end\s+angle)\s*=\s*('+NUM+r')',
                      lambda m: m[1]+'='+number(m[2]), text)
    pieces = re.split(r'((?<!\\)%[^\n]*)', tex)
    return ''.join(piece if i%2 else fragment(piece) for i,piece in enumerate(pieces))
