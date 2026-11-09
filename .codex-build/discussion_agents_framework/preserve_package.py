from pathlib import Path
import zipfile,re,json,xml.etree.ElementTree as E
d=Path(__file__).parent
targets={1:{'step1','step1detail','step2','step2detail','step3','step3detail','step4','step4detail','metrics-heading'},2:{'phase1','phase2','phase3','cvdetail','gesdetail','v1detail','v2detail'}}
addition={1:set(),2:{'role-summary'}}
pat=re.compile(r'<p:sp\b[\s\S]*?</p:sp>')
def name(block):
 m=re.search(r'<p:cNvPr\b[^>]*\bname="([^"]+)"',block);return m[1] if m else None
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
R='http://schemas.openxmlformats.org/package/2006/relationships'
with zipfile.ZipFile(d/'original.pptx') as src,zipfile.ZipFile(d/'authored.pptx') as art:
 files={n:src.read(n) for n in src.namelist()}
 for i in (1,2):
  part=f'ppt/slides/slide{i}.xml';new=art.read(part).decode();byname={name(b):b for b in pat.findall(new)};old=files[part].decode()
  assert targets[i]<=byname.keys()
  out=pat.sub(lambda m:byname[name(m[0])] if name(m[0]) in targets[i] else m[0],old)
  if i==1:
   # Preserve original native equations and every image, replacing only the editable table.
   tables=re.compile(r'<p:graphicFrame\b[\s\S]*?</p:graphicFrame>')
   original_tables=tables.findall(out);new_tables=tables.findall(new)
   assert len(original_tables)==len(new_tables)==1
   replacement=new_tables[0]
   old_id=re.search(r'<p:cNvPr\b[^>]*\bid="(\d+)"',original_tables[0])[1]
   replacement=re.sub(r'(<p:cNvPr\b[^>]*\bid=")\d+',lambda m:m[1]+old_id,replacement,count=1)
   out=tables.sub(lambda m:replacement,out)
  maxid=max(map(int,re.findall(r'<p:cNvPr\b[^>]*\bid="(\d+)"',out)))
  for nm in addition[i]:
   block=byname[nm];maxid+=1
   block=re.sub(r'(<p:cNvPr\b[^>]*\bid=")\d+',lambda m:m[1]+str(maxid),block,count=1)
   out=out.replace('</p:spTree>',block+'</p:spTree>')
  files[part]=out.encode()
 # Add the native editable framework slide to the original package.
 files['ppt/slides/slide3.xml']=art.read('ppt/slides/slide3.xml')
 rels1=E.fromstring(src.read('ppt/slides/_rels/slide1.xml.rels'))
 layout=next(r.attrib['Target'] for r in rels1 if r.attrib['Type'].endswith('/slideLayout'))
 files['ppt/slides/_rels/slide3.xml.rels']=(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{R}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="{layout}"/></Relationships>').encode()
 pres=files['ppt/presentation.xml'].decode();maxslide=max(map(int,re.findall(r'<p:sldId\b[^>]*\bid="(\d+)"',pres)))
 rels=files['ppt/_rels/presentation.xml.rels'].decode();rid='rId'+str(max(map(int,re.findall(r'Id="rId(\d+)"',rels)))+1)
 pres=pres.replace('</p:sldIdLst>',f'<p:sldId id="{maxslide+1}" r:id="{rid}"/></p:sldIdLst>')
 rels=rels.replace('</Relationships>',f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide3.xml"/></Relationships>')
 files['ppt/presentation.xml']=pres.encode();files['ppt/_rels/presentation.xml.rels']=rels.encode()
 ct=files['[Content_Types].xml'].decode().replace('</Types>','<Override PartName="/ppt/slides/slide3.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>')
 files['[Content_Types].xml']=ct.encode()
 with zipfile.ZipFile(d/'candidate.pptx','w',zipfile.ZIP_DEFLATED) as out:
  for n,v in files.items():out.writestr(n,v)
 # Exact preservation of existing mathematical expressions and media.
 with zipfile.ZipFile(d/'candidate.pptx') as out:
  for n in src.namelist():
   if n.startswith('ppt/media/'):assert src.read(n)==out.read(n),n
  old=src.read('ppt/slides/slide1.xml').decode();new=out.read('ppt/slides/slide1.xml').decode()
  for n in ['angle-formula','ratio-formula']:
   assert [b for b in pat.findall(old) if name(b)==n]==[b for b in pat.findall(new) if name(b)==n],n
print('Preserved original formulas/media; merged table, text and framework slide.')
