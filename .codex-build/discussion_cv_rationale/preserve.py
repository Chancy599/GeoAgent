import re,zipfile
from pathlib import Path
d=Path(__file__).parent
with zipfile.ZipFile(d/'original.pptx') as src,zipfile.ZipFile(d/'authored.pptx') as art:
 files={n:src.read(n) for n in src.namelist()}
 key='ppt/slides/slide3.xml';old=files[key].decode();auth=art.read(key).decode()
 block=next(s for s in re.findall(r'<p:sp\b[\s\S]*?</p:sp>',auth) if 'name="cv-repair-rationale"' in s)
 idx=max(map(int,re.findall(r'<p:cNvPr\b[^>]*\bid="(\d+)"',old)))+1
 block=re.sub(r'(<p:cNvPr\b[^>]*\bid=")\d+',lambda m:m[1]+str(idx),block,count=1)
 files[key]=old.replace('</p:spTree>',block+'</p:spTree>').encode()
 with zipfile.ZipFile(d/'candidate.pptx','w',zipfile.ZIP_DEFLATED) as out:
  for n,v in files.items():out.writestr(n,v)
 assert files[key].decode().replace(block,'')==old
print('Only added CV rationale; original slide content preserved exactly.')
