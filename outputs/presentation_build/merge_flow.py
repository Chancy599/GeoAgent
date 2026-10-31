from pathlib import Path
import zipfile, xml.etree.ElementTree as ET
root=Path('D:/Users/18217/Desktop/我的文件/GeoAgent')
base=root/'outputs/presentations/GeoAgent_三页汇报.pptx'
rev=root/'outputs/presentation_build/flow'
ns={'r':'http://schemas.openxmlformats.org/package/2006/relationships'}
with zipfile.ZipFile(base) as old, zipfile.ZipFile(rev/'third-only.pptx') as new:
    entries={n:old.read(n) for n in old.namelist()}
    rel=ET.fromstring(new.read('ppt/slides/_rels/slide1.xml.rels'))
    for e in rel:
        typ=e.attrib['Type'].rsplit('/',1)[-1]
        if typ=='slideLayout': e.set('Target','../slideLayouts/slideLayout6.xml')
        elif typ=='notesSlide': e.set('Target','../notesSlides/notesSlide3.xml')
        elif typ=='image':
            oldpath=e.attrib['Target'].lstrip('/')
            name='flow3_'+Path(oldpath).name
            entries['ppt/media/'+name]=new.read(oldpath)
            e.set('Target','../media/'+name)
    entries['ppt/slides/slide3.xml']=new.read('ppt/slides/slide1.xml')
    entries['ppt/slides/_rels/slide3.xml.rels']=ET.tostring(rel,encoding='utf-8',xml_declaration=True)
    entries['ppt/notesSlides/notesSlide3.xml']=new.read('ppt/notesSlides/notesSlide1.xml')
    rel=ET.fromstring(new.read('ppt/notesSlides/_rels/notesSlide1.xml.rels'))
    for e in rel:
        typ=e.attrib['Type'].rsplit('/',1)[-1]
        e.set('Target','../slides/slide3.xml' if typ=='slide' else '../notesMasters/notesMaster1.xml')
    entries['ppt/notesSlides/_rels/notesSlide3.xml.rels']=ET.tostring(rel,encoding='utf-8',xml_declaration=True)
    with zipfile.ZipFile(rev/'candidate.pptx','w',zipfile.ZIP_DEFLATED) as merged:
        for n,data in entries.items(): merged.writestr(n,data)
    for i in [1,2]:
        assert entries[f'ppt/slides/slide{i}.xml']==old.read(f'ppt/slides/slide{i}.xml')
    print('Merged slide 3. Original slide 1 and 2 XML preserved exactly.')

