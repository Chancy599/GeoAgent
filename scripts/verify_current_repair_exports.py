"""Check accepted relations in the actual generated TeX engine coordinates."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.config import load_settings
from geoagent.state.tikz_geometry import extract_geometry
from geoagent.state.relation_candidates import pair_metrics
from scripts.test_numeric_relations import reference_points


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT/'results/latest')
    parser.add_argument('--archive', type=Path, default=ROOT/'outputs/ours')
    parser.add_argument('--workers', type=int, default=20)
    args = parser.parse_args()
    out, archive = args.results.resolve(), args.archive.resolve()
    reports=read(out/'repair_manifest.json')['reports']
    settings=load_settings()
    generated_settings=SimpleNamespace(paths=SimpleNamespace(latex_dir=archive/'latex',tectonic=settings.paths.tectonic))
    def verify(report):
        stem=report['stem'];geom=extract_geometry((archive/'latex'/f'{stem}.tex').read_text(encoding='utf-8'))
        executed=reference_points(stem,out/'engine_verification',geom,generated_settings)
        rows=[]
        for candidate in report['accepted']:
            error=pair_metrics(executed,*(geom['segments'][s] for s in candidate['segments']))[candidate['type']+'_error_deg']
            rows.append({'type':candidate['type'],'segments':candidate['segments'],'error_deg':error})
        result={'stem':stem,'relations':rows,'max_engine_error_deg':max((r['error_deg'] for r in rows),default=0)}
        save(archive/'stem'/stem/'engine_verification.json',result)
        return result
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(verify,[r for r in reports if r['applied']]))
    save(out/'engine_verification.json',{'results':results,'errors':[],'coordinate_decimals':3,'source':'generated programs only'})
    summary=read(out/'summary.json')
    summary.update(engine_verified_images=len(results),engine_errors=[],max_engine_error_deg=max((r['max_engine_error_deg'] for r in results),default=0))
    save(out/'summary.json',summary)
    print(f"Verified {len(results)} generated programs; max engine direction residual {summary['max_engine_error_deg']:.8f} degrees.")


if __name__=='__main__':main()
