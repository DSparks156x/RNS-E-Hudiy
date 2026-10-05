"""Regenerate approved72x72 native navigation masks from curated Maps SVGs.

Development dependencies: Pillow, Node.js, sharp (tools/native_nav_icons).
Runtime nav_icons_data.py remains standard-library-only. Default raster policy
is the bench-approved complete-viewport72px, phase(0,0),8x BOX coverage>=128.
No glyph-specific hinting, occupied-bounds crop, or synthesized mirrors.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

ET.register_namespace('', 'http://www.w3.org/2000/svg')

SIZE=72
OVERSAMPLE=8
THRESHOLD=128
REPO=Path(__file__).resolve().parents[1]
DEFAULT_SOURCE=REPO/'dis_client/nav_icons_sources'
RENDERER=Path(__file__).resolve().parent/'native_nav_icons/render_svg_batch.js'


def source_manifest(source_dir=DEFAULT_SOURCE):
    """Verify curated byte provenance before rasterizing source geometry."""
    directory=Path(source_dir)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    for name,item in manifest['icons'].items():
        source=directory/item['svg']
        actual=hashlib.sha256(source.read_bytes()).hexdigest()
        if actual!=item['svg_sha256']:
            raise ValueError('Curated SVG hash mismatch for '+name)
    return manifest


def local_tag(node):
    return node.tag.rsplit('}',1)[-1]


def layer_svg(source, selected):
    """Normalize separately authored context alpha before coverage sampling.

    Curated sources preserve original active/context path layers. Source alpha
    <.99 marks secondary roads, not dim active pixels. Opaque route wins where
    layers overlap. Clip definitions and group transforms are preserved.
    """
    if selected not in ('active','context'):
        raise ValueError('Unknown semantic layer')
    root=copy.deepcopy(source)
    def walk(node,inherited=1.,definition=False):
        effective=inherited*float(node.get('opacity','1'))
        definition=definition or local_tag(node) in ('defs','clipPath','mask')
        node.attrib.pop('opacity',None)
        for child in list(node):
            if local_tag(child) in ('path','rect','circle','polygon','ellipse') and not definition:
                if child.get('fill')=='none' and child.get('stroke','none')=='none':
                    node.remove(child);continue
                alpha=effective*float(child.get('opacity','1'))*float(child.get('fill-opacity','1'))
                if selected!=('context' if alpha<.99 else 'active') or alpha<=0:
                    node.remove(child);continue
                # Do not fill an explicitly stroke-only source path.
                if child.get('fill')!='none':
                    child.set('fill','#ffffff');child.set('fill-opacity','1')
                child.attrib.pop('opacity',None)
                if child.get('stroke','none')!='none':
                    child.set('stroke','#ffffff');child.set('stroke-opacity','1')
            else:
                walk(child,effective,definition)
    walk(root)
    return root


def contain_coverage(layer):
    """Uniformly contain complete layer canvas, not the occupied glyph bbox."""
    image=layer.convert('L')
    scale=SIZE/max(image.size)
    dimensions=(round(image.width*scale),round(image.height*scale))
    output=Image.new('L',(SIZE,SIZE))
    output.paste(image.resize(dimensions,Image.Resampling.BOX),
                 ((SIZE-dimensions[0])//2,(SIZE-dimensions[1])//2))
    return output


def native_from_layers(active,context):
    """Threshold solid coverage and apply a fixed secondary-road checker."""
    masks=[contain_coverage(layer).point(lambda v:255 if v>=THRESHOLD else 0)
           for layer in (active,context)]
    output=Image.new('1',(SIZE,SIZE))
    a,c,b=masks[0].load(),masks[1].load(),output.load()
    for y in range(SIZE):
        for x in range(SIZE):
            b[x,y]=bool(a[x,y] or (c[x,y] and (x+y)%2==0))
    return output


def build_icons(source_dir=DEFAULT_SOURCE,node='node',sharp_module=None):
    """Render each mapped SVG, retaining authored aliases and handedness."""
    source_dir=Path(source_dir)
    manifest=source_manifest(source_dir)
    icons,provenance={},{}
    with tempfile.TemporaryDirectory(prefix='native-nav-icons-') as temporary:
        work=Path(temporary);jobs=[]
        # Source names can be shared by different keys; render each only once.
        for filename in sorted({item['svg'] for item in manifest['icons'].values()}):
            root=ET.parse(source_dir/filename).getroot()
            for layer in ('active','context'):
                target=work/(Path(filename).stem+'_'+layer+'.svg')
                ET.ElementTree(layer_svg(root,layer)).write(target,encoding='utf-8',xml_declaration=True)
                jobs.append({'input':str(target),'output':str(target.with_suffix('.png')),'size':SIZE*OVERSAMPLE})
        jobsfile=work/'jobs.json';jobsfile.write_text(json.dumps(jobs),encoding='utf-8')
        command=[str(node),str(RENDERER),str(jobsfile)]
        if sharp_module:command.append(str(sharp_module))
        try:
            subprocess.run(command,check=True,capture_output=True,text=True)
        except FileNotFoundError as error:
            raise RuntimeError('Node.js is required only to regenerate native navigation assets.') from error
        except subprocess.CalledProcessError as error:
            raise RuntimeError('SVG rendering failed. Install tools/native_nav_icons development dependencies.\n'+error.stderr) from error
        rendered={}
        for filename in sorted({item['svg'] for item in manifest['icons'].values()}):
            coverage=[]
            for layer in ('active','context'):
                with Image.open(work/(Path(filename).stem+'_'+layer+'.png')) as image:
                    coverage.append(image.convert('RGBA').getchannel('A'))
            rendered[filename]=native_from_layers(*coverage)
        for name,item in sorted(manifest['icons'].items()):
            icons[name]=rendered[item['svg']].copy()
            provenance[name]=item['svg']
    return icons,provenance


def generate_assets(path,icons,provenance):
    lines=['"""Generated Maps SVG72x72 native masks; see nav_icons_sources provenance."""',
           'RASTER_POLICY = '+repr({'size':72,'phase':[0,0],'coverage_oversample':8,'threshold':128,'context':'x+y even checker'}),
           'ICON_SOURCES = {']
    lines += ['    '+repr(name)+': '+repr(provenance[name])+',' for name in sorted(icons)]
    lines += ['}', '', 'ICON_HEX = {']
    lines += ['    '+repr(name)+': '+repr(icons[name].tobytes().hex())+',' for name in sorted(icons)]
    lines += ['}', '']
    Path(path).write_text('\n'.join(lines),encoding='utf-8')


def preview_icons(path,icons):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    columns=5;width=232;height=190
    sheet=Image.new('RGB',(columns*width,((len(icons)+columns-1)//columns)*height),'#1d2025')
    draw=ImageDraw.Draw(sheet)
    for index,name in enumerate(sorted(icons)):
        icons[name].save(path/(name.lower()+'.png'))
        x,y=(index%columns)*width,(index//columns)*height
        sheet.paste(icons[name].convert('RGB').resize((144,144),Image.Resampling.NEAREST),(x+44,y+6))
        label=name.replace('COUNTERCLOCKWISE','CCW').replace('CLOCKWISE','CW')
        draw.text((x+8,y+158),label,fill='white')
    sheet.save(path/'navigation_icon_contact_sheet.png')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--assets',type=Path,default=REPO/'dis_client/nav_icons_data.py')
    parser.add_argument('--previews',type=Path)
    parser.add_argument('--node',default='node')
    parser.add_argument('--sharp-module',help='Optional alternate installed sharp module directory')
    parser.add_argument('--check',action='store_true',help='Compare to current packed assets without modifying them')
    parser.add_argument('--update-reference',action='store_true',help='Also update reviewed source-folder reference72 masks')
    args=parser.parse_args()
    icons,provenance=build_icons(args.sources,args.node,args.sharp_module)
    if args.check:
        import importlib.util
        spec=importlib.util.spec_from_file_location('native_nav_existing',args.assets)
        existing=importlib.util.module_from_spec(spec);spec.loader.exec_module(existing)
        if set(existing.ICON_HEX)!=set(icons) or any(existing.ICON_HEX[name]!=icons[name].tobytes().hex() for name in icons):
            raise SystemExit('Generated navigation assets differ from installed masks')
    else:
        generate_assets(args.assets,icons,provenance)
    if args.update_reference:
        reference=args.sources/'reference72';reference.mkdir(parents=True,exist_ok=True)
        for name,icon in icons.items():icon.save(reference/(name+'.png'))
    if args.previews:preview_icons(args.previews,icons)
    print(('Verified' if args.check else 'Generated')+' '+str(len(icons))+' source-faithful Maps native navigation masks')


if __name__=='__main__':main()
