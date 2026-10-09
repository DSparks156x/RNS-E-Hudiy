"""Bounded stock mono screen4/5 byte compiler; no transport or semantic map."""
from dataclasses import dataclass
from pathlib import Path
import hashlib,json

STOCK_SHA256='9edf419c023b97c3e1b435f8a47ac3c168f8e3146e084d6aa82b0425d91e5ba2'
FIELDS=frozenset(('command','source_object','object_stage','screen_selector','raw_progress','road_bytes'))

def binary(value,label,maximum):
    if isinstance(value,bytes):result=value
    elif isinstance(value,(list,tuple)) and all(type(v) is int and 0<=v<=255 for v in value):result=bytes(value)
    else:raise ValueError(label+' requires binary integer bytes')
    if len(result)>maximum:raise ValueError(label+' exceeds proven extent')
    return result

def records_from_stream(stream):
    result=[];at=0
    while at<len(stream):
        if len(stream)-at<2 or stream[at] not in (0x52,0x57):raise ValueError('unsupported mono record')
        size=stream[at+1]+2
        if at+size>len(stream):raise ValueError('truncated mono record')
        row=stream[at:at+size]
        if row[0]==0x52:
            if row not in (bytes.fromhex('520500001b4030'),bytes.fromhex('520502001b3628')):
                raise ValueError('unsupported stock52 window')
        elif size<6 or row[2] not in (0x0A,0x0B,0x06,0x26) or row[3]>=64 or row[4]>=48:
            raise ValueError('stock57 flags or anchor outside known central renderer')
        result.append(row);at+=size
    return tuple(result)

def batch(records):
    result=[];pending=bytearray()
    for record in records:
        if len(record)>49:raise ValueError('stock record exceeds49-byte bound')
        if pending and len(pending)+len(record)>49:result.append(bytes(pending));pending.clear()
        pending.extend(record)
    if pending:result.append(bytes(pending))
    return tuple(result)

@dataclass(frozen=True)
class StockFrame:
    records:tuple
    messages:tuple
    source_object:bytes
    object_stage:str
    screen_selector:int
    raw_progress:int
    road_bytes:bytes
    normalized:bytes|None

    @property
    def source(self):
        return dict(command='draw_stock_mono_frame',source_object=list(self.source_object),
                    object_stage=self.object_stage,screen_selector=self.screen_selector,
                    raw_progress=self.raw_progress,road_bytes=list(self.road_bytes))

class StockMonoFrameCompiler:
    def __init__(self,path=None):
        path=Path(path) if path is not None else Path(__file__).with_name('stock_mono_catalog.json')
        raw=path.read_bytes();digest=path.with_suffix('.sha256').read_text().split()[0]
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('stock mono catalog hash changed')
        self.data=json.loads(raw)
        if self.data.get('schema')!=1 or self.data.get('stock_sha256')!=STOCK_SHA256:
            raise ValueError('stock mono catalog source/schema mismatch')

    def compile_command(self,command):
        if not isinstance(command,dict) or set(command)!=FIELDS or command.get('command')!='draw_stock_mono_frame':
            raise ValueError('stock frame requires exactly the documented raw fields')
        obj=binary(command['source_object'],'source_object',258)
        stage=command['object_stage'];selector=command['screen_selector'];progress=command['raw_progress']
        road=binary(command['road_bytes'],'road_bytes',24)
        if stage not in ('render','source_ff'):raise ValueError('object_stage must be explicit render or source_ff')
        if type(selector) is not int or selector not in (4,5):raise ValueError('only proven stock screens4/5 supported')
        if type(progress) is not int or not 0<=progress<=255:raise ValueError('raw_progress must be integer0..255')
        if 0 in road:raise ValueError('road00 termination semantics unresolved')
        icon=self.data['icons'][stage].get(obj.hex())
        if icon is None:raise ValueError('object outside native-verified '+stage+' domain')
        level=(progress*100//255)//5
        stream=bytes.fromhex('520500001b4030')+bytes.fromhex(self.data['bar'][level])
        stream+=bytes.fromhex('5710060029')+b'\x65'*13
        if road:
            body=b'\x69'+road[:20]
            stream+=bytes((0x57,len(body)+3,0x26,0,0x29))+body
        stream+=bytes.fromhex(icon['stream'])
        records=records_from_stream(stream)
        return StockFrame(records,batch(records),obj,stage,selector,progress,road,
                          bytes.fromhex(icon['normalized']) if 'normalized' in icon else None)
