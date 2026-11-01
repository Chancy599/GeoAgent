"""Same fixed visual protocol, with content-addressed encoder features."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from geoagent.datasets import scan_dataset
from geoagent.evaluation.visual_metrics import (
    clip_embeddings,dino_embeddings,ssim_pair,_cosine,_encoder_config,_verify_weights,
)


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--group",action="append",required=True)
    p.add_argument("--ref-dir",type=Path,default=ROOT/"data/test/image")
    p.add_argument("--cache",type=Path,default=ROOT/".cache/visual_evaluation")
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    groups={n:Path(folder) for n,folder in (s.split("=",1) for s in args.group)}
    refs={i.stem:i.image_path for i in scan_dataset(args.ref_dir)}
    stems=sorted(set(refs)&set.intersection(*({p.stem for p in folder.glob('*.png')} for folder in groups.values())))
    if not stems:raise SystemExit("No common images")
    paths={"reference":{s:refs[s] for s in stems},**{n:{s:folder/f"{s}.png" for s in stems} for n,folder in groups.items()}}
    hashes={n:{s:digest(path) for s,path in images.items()} for n,images in paths.items()}
    unique={hashes[n][s]:path for n,images in paths.items() for s,path in images.items()}
    config={"clip":_encoder_config("clip-model"),"dino":_encoder_config("dino-model")}
    _verify_weights(config["clip"]["weights_path"],config["clip"]["weights_sha256"],"CLIP")
    for filename,spec in config["dino"]["files"].items():
        _verify_weights(Path(config["dino"]["snapshot_path"])/filename,spec["sha256"],"DINO")
    features={}
    for name,encode in (("clip",clip_embeddings),("dino",dino_embeddings)):
        fingerprint=hashlib.sha256(json.dumps(config[name],sort_keys=True).encode()).hexdigest()[:16]
        folder=args.cache/name/fingerprint;folder.mkdir(parents=True,exist_ok=True)
        missing=[key for key in unique if not (folder/f"{key}.npy").exists()]
        print(f"{name}: {len(unique)} unique images, {len(missing)} to encode",flush=True)
        if missing:
            vectors=encode([unique[k] for k in missing])
            for key,vector in zip(missing,vectors):np.save(folder/f"{key}.npy",vector,allow_pickle=False)
        features[name]={k:np.load(folder/f"{k}.npy",allow_pickle=False) for k in unique}
        print(f"{name}: features ready",flush=True)
    rows={};summary={}
    ssim_cache=args.cache/"ssim";ssim_cache.mkdir(parents=True,exist_ok=True)
    for group,images in paths.items():
        if group=="reference":continue
        cosine={n:_cosine(np.stack([features[n][hashes[group][s]] for s in stems]),
                         np.stack([features[n][hashes['reference'][s]] for s in stems])) for n in features}
        rows[group]=[]
        for i,stem in enumerate(stems):
            key=hashlib.sha256((hashes[group][stem]+hashes['reference'][stem]+"ssim1000.v1").encode()).hexdigest()
            cache=ssim_cache/f"{key}.json"
            if cache.exists():ssim=float(json.loads(cache.read_text()))
            else:
                ssim=ssim_pair(images[stem],paths['reference'][stem]);cache.write_text(json.dumps(ssim))
            rows[group].append({"stem":stem,"ssim":ssim,"clip":float(cosine['clip'][i]),"dino":float(cosine['dino'][i])})
        summary[group]={n:float(np.mean([r[n] for r in rows[group]])) for n in ('ssim','clip','dino')}
        print(group,json.dumps({k:v*100 for k,v in summary[group].items()}),flush=True)
    result={"schema":"fixed-visual-cached.v1","shared_stems":stems,"count":len(stems),
        "groups":{g:{"summary":summary[g],"per_stem":rows[g],"image_dir":str(groups[g])} for g in groups},
        "encoder_configs":config,"protocol":"TriGeoBench whole-image fixed protocol; SSIM/CLIP/DINO unchanged; content-addressed features"}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=="__main__":main()
