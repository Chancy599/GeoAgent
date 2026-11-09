from pathlib import Path
import zipfile,re,hashlib,json
d=Path(__file__).parent
targets={1:{'step2','step2detail','step3','step3detail','step4','step4detail'},2:{'phase1','phase2','phase3','cvdetail','gesdetail','v1detail','v2detail','effect'}}
remove={1:{'opt-objective','opt-definition','opt-iteration'},2:set()}
pattern=re.compile(r'<p:sp\b[\s\S]*?</p:sp>')
def name(block):
    m=re.search(r'<p:cNvPr\b[^>]*\bname="([^"]+)"',block)
    return m[1] if m else None
with zipfile.ZipFile(d/'original.pptx') as source,zipfile.ZipFile(d/'authored.pptx') as authored,zipfile.ZipFile(d/'candidate.pptx','w') as out:
    changed=[]
    for info in source.infolist():
        data=source.read(info.filename)
        for slide in (1,2):
            if info.filename==f'ppt/slides/slide{slide}.xml':
                new=authored.read(info.filename).decode('utf-8')
                byname={name(b):b for b in pattern.findall(new)}
                assert targets[slide]<=byname.keys()
                old=data.decode('utf-8')
                def replace(m):
                    n=name(m[0])
                    if n in remove[slide]:return ''
                    if n in targets[slide]:return byname[n]
                    return m[0]
                data=pattern.sub(replace,old).encode('utf-8')
                changed.append(info.filename)
        out.writestr(info,data)
with zipfile.ZipFile(d/'original.pptx') as old,zipfile.ZipFile(d/'candidate.pptx') as new:
    changed=[n for n in old.namelist() if old.read(n)!=new.read(n)]
    assert changed==['ppt/slides/slide1.xml','ppt/slides/slide2.xml'],changed
    old1=old.read('ppt/slides/slide1.xml').decode()
    new1=new.read('ppt/slides/slide1.xml').decode()
    untouched={'title','steps-heading','step1','step1detail','metrics-heading','formula-heading','angle-formula','ratio-formula'}
    for n in untouched:
        assert [b for b in pattern.findall(old1) if name(b)==n]==[b for b in pattern.findall(new1) if name(b)==n],n
print(json.dumps({'modified_parts':changed,'original_formulas_and_media':'preserved'},ensure_ascii=False))
