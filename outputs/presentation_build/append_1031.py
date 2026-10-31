from pathlib import Path
import zipfile,xml.etree.ElementTree as E,shutil
root=Path('D:/Users/18217/Desktop/我的文件/GeoAgent')
rev=root/'outputs/presentation_build/1031'
src=root/'outputs/presentations/1031汇报.pptx'
backup=rev/'1031_original.pptx'
if not backup.exists():shutil.copy2(src,backup)
R='http://schemas.openxmlformats.org/package/2006/relationships'
P='http://schemas.openxmlformats.org/presentationml/2006/main'
O='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
T='http://schemas.openxmlformats.org/package/2006/content-types'
with zipfile.ZipFile(backup) as old,zipfile.ZipFile(rev/'third-only.pptx') as new:
    data={n:old.read(n) for n in old.namelist()}
    rel=E.fromstring(new.read('ppt/slides/_rels/slide1.xml.rels'))
    for e in rel:
        typ=e.attrib['Type'].rsplit('/',1)[-1]
        if typ=='slideLayout':e.set('Target','../slideLayouts/slideLayout6.xml')
        elif typ=='notesSlide':e.set('Target','../notesSlides/notesSlide2.xml')
        elif typ=='image':
            target=e.attrib['Target'].lstrip('/')
            name='case1260_'+Path(target).name
            data['ppt/media/'+name]=new.read(target)
            e.set('Target','../media/'+name)
    data['ppt/slides/slide2.xml']=new.read('ppt/slides/slide1.xml')
    data['ppt/slides/_rels/slide2.xml.rels']=E.tostring(rel,encoding='utf-8',xml_declaration=True)
    data['ppt/notesSlides/notesSlide2.xml']=new.read('ppt/notesSlides/notesSlide1.xml')
    rel=E.fromstring(new.read('ppt/notesSlides/_rels/notesSlide1.xml.rels'))
    for e in rel:
        typ=e.attrib['Type'].rsplit('/',1)[-1]
        e.set('Target','../slides/slide2.xml' if typ=='slide' else '../notesMasters/notesMaster1.xml')
    data['ppt/notesSlides/_rels/notesSlide2.xml.rels']=E.tostring(rel,encoding='utf-8',xml_declaration=True)
    # Keep the first slide and all its dependencies byte-for-byte intact.
    xml=data['ppt/presentation.xml'].decode('utf-8')
    assert xml.count('<p:sldId ')==1
    xml=xml.replace('</p:sldIdLst>','<p:sldId id="257" r:id="rIdCase1260"/></p:sldIdLst>')
    data['ppt/presentation.xml']=xml.encode('utf-8')
    rel=E.fromstring(data['ppt/_rels/presentation.xml.rels'])
    E.SubElement(rel,'{'+R+'}Relationship',{'Id':'rIdCase1260','Type':O+'/slide','Target':'slides/slide2.xml'})
    data['ppt/_rels/presentation.xml.rels']=E.tostring(rel,encoding='utf-8',xml_declaration=True)
    types=E.fromstring(data['[Content_Types].xml'])
    for name,ctype in [('ppt/slides/slide2.xml','application/vnd.openxmlformats-officedocument.presentationml.slide+xml'),('ppt/notesSlides/notesSlide2.xml','application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml')]:
        E.SubElement(types,'{'+T+'}Override',{'PartName':'/'+name,'ContentType':ctype})
    if not any(e.attrib.get('Extension')=='png' for e in types):E.SubElement(types,'{'+T+'}Default',{'Extension':'png','ContentType':'image/png'})
    E.register_namespace('',T)
    data['[Content_Types].xml']=E.tostring(types,encoding='utf-8',xml_declaration=True)
    if 'docProps/app.xml' in data:
        data['docProps/app.xml']=data['docProps/app.xml'].replace(b'<Slides>1</Slides>',b'<Slides>2</Slides>')
    with zipfile.ZipFile(rev/'candidate.pptx','w',zipfile.ZIP_DEFLATED) as z:
        for n,b in data.items():z.writestr(n,b)
    assert data['ppt/slides/slide1.xml']==old.read('ppt/slides/slide1.xml')
print('Appended page 2; page 1 preserved.')
