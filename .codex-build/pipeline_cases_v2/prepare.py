import json, sys, re, math
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from geoagent.cv_tools.line_detection import detect_lines
from geoagent.cv_tools.circle_detection import detect_circles
from geoagent.tools.compiler import compile_tikz
from geoagent.tools.renderer import render_pdf, frame_like_original
assets=Path(__file__).parent/'assets'
source=root/'data/test/image/772_q_fig2.png'
for name,fn in [('lines',detect_lines),('circles',detect_circles)]:
    result=fn(source,out_dir=assets/'cv',visualize=True)
    (assets/f'{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,result.get('visualization'),flush=True)
for v in (1,2):
    tex=(assets/f'772_v{v}.tex').read_text(encoding='utf-8')
    c=compile_tikz(tex,out_dir=assets/f'v{v}',stem=f'v{v}')
    if not c.get('ok'): raise RuntimeError(c)
    render=render_pdf(c['pdf_path'],assets/f'772_v{v}.png',dpi=240)
    frame_like_original(render['png_path'],source)
    pts={n:(float(x),float(y)) for n,x,y in re.findall(r'\\coordinate\s*\((\w+)\)\s*at\s*\(([-\d.]+),([-\d.]+)\)',tex)}
    o=pts['O'];r=2.015
    errors={n:round((math.dist(o,pts[n])-r)/.017021,3) for n in ['Vt','D1a','D1b','D2a','D2b']}
    print('version',v,'radial_residual_px',errors,flush=True)
