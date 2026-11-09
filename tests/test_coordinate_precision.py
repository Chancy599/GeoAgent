import re

import numpy as np

from geoagent.state.coordinate_precision import number, quantize_tex


def test_numeric_coordinates_curves_units_and_comments():
    source = r'\draw (-0.00001,1.234567)--(A1) arc[start angle=0,end angle=180,radius=2.34567]; \draw (0:90:2.12345); \draw (1.23456cm,-2.45678pt); % (1.234567,2)'
    result = quantize_tex(source)
    assert '(0.000,1.235)--(A1)' in result
    assert 'radius=2.346' in result and '(0.000:90.000:2.123)' in result
    assert '(1.235cm,-2.457pt)' in result
    assert '% (1.234567,2)' in result
    assert quantize_tex(result) == result


def test_rounding_error_bound_and_no_negative_zero():
    for value in np.linspace(-2, 2, 10001):
        text = number(value)
        assert re.fullmatch(r'-?\d+\.\d{3}', text)
        assert abs(float(text)-value)<=.0005+1e-12
        assert text!='-0.000'


def test_multiline_coordinates_preserve_comments():
    assert quantize_tex('\\coordinate(A) at (1.234567,\n2.345678); % 9.123456\n') == '\\coordinate(A) at (1.235,2.346); % 9.123456\n'
