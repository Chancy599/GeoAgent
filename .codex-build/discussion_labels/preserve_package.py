from pathlib import Path
import zipfile,re,json
d=Path(__file__).parent
targets={1:{'step2','step2detail','step3','step3detail','step4','step4detail'},2:{'origcap','cvcap','cvdetail','gesdetail'}}
extra={1:{'least-squares','least-squares-note'},2:{'labelcap'}}
pat=re.compile(r'<p:sp\b[\s\S]*?</p:sp>')
pics=re.compile(r'<p:pic\b[\s\S]*?</p:pic>')
def name(block):
 m=re.search(r'<p:cNvPr\b[^>]*\bname="([^"]+)"',block);return m[1] if m else None
def newid(block,idx):return re.sub(r'(<p:cNvPr\b[^>]*\bid=")\d+',lambda m:m[1]+str(idx),block,count=1)
with zipfile.ZipFile(d/'original.pptx') as src,zipfile.ZipFile(d/'authored.pptx') as art:
 files={n:src.read(n) for n in src.namelist()}
 for i in (1,2):
  part=f'ppt/slides/slide{i}.xml';old=files[part].decode();auth=art.read(part).decode();byname={name(b):b for b in pat.findall(auth)}
  new=pat.sub(lambda m:byname[name(m[0])] if name(m[0]) in targets[i] else m[0],old)
  maxid=max(map(int,re.findall(r'<p:cNvPr\b[^>]*\bid="(\d+)"',new)))
  for n in sorted(extra[i]):
   maxid+=1;new=new.replace('</p:spTree>',newid(byname[n],maxid)+'</p:spTree>')
  if i==2:
   oldpics=pics.findall(new);apics=pics.findall(auth)
   assert len(apics)==len(oldpics)+1
   xf=re.compile(r'<a:xfrm\b[\s\S]*?</a:xfrm>')
   for j in (0,1):
    newxf=xf.search(apics[j])[0]
    replacement=xf.sub(lambda m:newxf,oldpics[j],count=1)
    new=new.replace(oldpics[j],replacement,1)
   pic=apics[-1]
   relpart='ppt/slides/_rels/slide2.xml.rels';rels=files[relpart].decode();rid='rId'+str(max(map(int,re.findall(r'Id="rId(\d+)"',rels)))+1)
   pic=re.sub(r'r:embed="[^"]+"',f'r:embed="{rid}"',pic)
   maxid+=1;pic=newid(pic,maxid)
   new=new.replace('</p:spTree>',pic+'</p:spTree>')
   rels=rels.replace('</Relationships>',f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/labels_772.png"/></Relationships>')
   files[relpart]=rels.encode();files['ppt/media/labels_772.png']=(d/'assets/match_label_templates.png').read_bytes()
  files[part]=new.encode()
 with zipfile.ZipFile(d/'candidate.pptx','w',zipfile.ZIP_DEFLATED) as out:
  for n,v in files.items():out.writestr(n,v)
 with zipfile.ZipFile(d/'candidate.pptx') as out:
  old=src.read('ppt/slides/slide1.xml').decode();new=out.read('ppt/slides/slide1.xml').decode()
  for nm in ['angle-formula','ratio-formula']:
   assert [v for v in pat.findall(old) if name(v)==nm]==[v for v in pat.findall(new) if name(v)==nm],nm
  for nm in ['step4','step4detail']:
   before=next(v for v in pat.findall(old) if name(v)==nm);after=next(v for v in pat.findall(new) if name(v)==nm)
   assert re.findall(r'<a:t>(.*?)</a:t>',before)==re.findall(r'<a:t>(.*?)</a:t>',after),nm
  assert src.read('ppt/slides/slide3.xml')==out.read('ppt/slides/slide3.xml')
  for n in src.namelist():
   if n.startswith('ppt/media/'):assert src.read(n)==out.read(n)
print('Preserved user 04, equations, media and complete framework slide. Added label-detection image.')
