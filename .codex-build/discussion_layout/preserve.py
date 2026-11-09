from pathlib import Path
import zipfile,re,xml.etree.ElementTree as E
d=Path(__file__).parent
sp=re.compile(r'<p:sp\b[\s\S]*?</p:sp>');pic=re.compile(r'<p:pic\b[\s\S]*?</p:pic>');xf=re.compile(r'<a:xfrm\b[\s\S]*?</a:xfrm>')
def ident(s):return re.search(r'<p:cNvPr\b[^>]*\bid="(\d+)"',s)[1]
def texts(s):return re.findall(r'<(?:a|m):t>([\s\S]*?)</(?:a|m):t>',s)
with zipfile.ZipFile(d/'original.pptx') as orig,zipfile.ZipFile(d/'authored.pptx') as art:
 files={n:orig.read(n) for n in orig.namelist()}
 for i in range(1,4):
  part=f'ppt/slides/slide{i}.xml';old=files[part].decode();new=art.read(part).decode()
  amap={ident(s):s for s in sp.findall(new)}
  cmap={ident(s):s for s in re.findall(r'<p:cxnSp\b[\s\S]*?</p:cxnSp>',new)}
  def repl(m):
   s=m[0];idx=ident(s);a=amap[idx]
   # Never replace native equation markup with import/export's text representation.
   if i==3 and idx in ('27','28'):return xf.sub(lambda _:xf.search(a)[0],s,count=1)
   return a
  result=sp.sub(repl,old)
  result=re.sub(r'<p:cxnSp\b[\s\S]*?</p:cxnSp>',lambda m:xf.sub(lambda _:xf.search(cmap[ident(m[0])])[0],m[0],count=1),result)
  apics={ident(s):s for s in pic.findall(new)}
  result=pic.sub(lambda m:xf.sub(lambda _:xf.search(apics[ident(m[0])])[0],m[0],count=1),result)
  files[part]=result.encode()
  n={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
  def content(xml):
   r=E.fromstring(xml)
   return [''.join(t.itertext()) for t in r.iter() if t.tag in ('{'+n['a']+'}t','{'+n['m']+'}t')]
  assert re.sub(r'\s+','',''.join(content(old)))==re.sub(r'\s+','',''.join(content(result))),f'Content changed on {i}'
 # Keep original table cell contents, formatting, and native equations.
 with zipfile.ZipFile(d/'candidate.pptx','w',zipfile.ZIP_DEFLATED) as out:
  for n,v in files.items():out.writestr(n,v)
print('Original wording, native equations, table, and image assets preserved.')
