#!/usr/bin/env python3
"""Parse GM 7.0 object records (name, parent, per-event GML) out of a decrypted tree.

Companion to gm7tree.py, which does rooms. Self-verifying the same way: a candidate is
accepted only if [u32 len][plausible name][u32 == 430] holds AND the whole record parses
to a sane end. Field order from elipsitz/gm_reader.

Two format traps, both of which silently yield zero objects if you get them wrong:
  * GM 7.0 objects declare ELEVEN event types (event_type_count_minus_1 == 10). The
    twelfth (Trigger) is GM 8 only.
  * The section header is [u32 version=400][u32 count]; count is 1016 slots for BSF and
    388 of them are empty (exists == 0). Honour the empty slots or every object index is
    wrong -- ctr_Ship is index 1, not 0.

Usage:
    python3 gmobj.py [dump/tree_plain.bin]      # writes objects.json, prints a summary

walk_section() is the one to call for index-correct output.
"""
import re, struct, sys, json

OBJ_VER = 430
ACTLIST_VER = 400
ACTION_VER = 440
NAME_RE = re.compile(rb'^[A-Za-z_][A-Za-z0-9_ ]{0,63}$')
EVENT_TYPES = {0:'Create',1:'Destroy',2:'Alarm',3:'Step',4:'Collision',5:'Keyboard',
               6:'Mouse',7:'Other',8:'Draw',9:'KeyPress',10:'KeyRelease',11:'Trigger'}

#: Where gm7.py writes the decrypted tree.
DEFAULT_TREE = 'dump/tree_plain.bin'

def u32(b,p): return struct.unpack_from('<I',b,p)[0]
def i32(b,p): return struct.unpack_from('<i',b,p)[0]
def rstr(b,p):
    n=u32(b,p)
    if n > (1<<22): raise ValueError('bad str len')
    return b[p+4:p+4+n], p+4+n

def parse_action(b,p):
    if u32(b,p)!=ACTION_VER: raise ValueError('bad action ver')
    p+=4
    p+=4*7                       # lib_id, action_id, kind, may_be_relative, question, applies_to_something, action_type
    _fn,p=rstr(b,p)              # function name
    code,p=rstr(b,p)             # function code  <-- the GML for a code action
    p+=4                         # arg_count_used
    n=u32(b,p); p+=4             # arg count (8)
    if n>16: raise ValueError('bad argc')
    p+=4*n                       # arg kinds
    p+=4                         # applies_to_object
    p+=4                         # relative
    n2=u32(b,p); p+=4            # arg count again
    if n2>16: raise ValueError('bad argc2')
    args=[]
    for _ in range(n2):
        s,p=rstr(b,p); args.append(s)
    p+=4                         # not flag
    return code, args, p

def parse_object(b,pos):
    name,p=rstr(b,pos)
    if not NAME_RE.match(name): return None
    if u32(b,p)!=OBJ_VER: return None
    p+=4
    sprite=i32(b,p); p+=4
    solid=u32(b,p); p+=4
    visible=u32(b,p); p+=4
    depth=i32(b,p); p+=4
    persistent=u32(b,p); p+=4
    parent=i32(b,p); p+=4
    mask=i32(b,p); p+=4
    ntypes=u32(b,p)+1; p+=4
    if ntypes not in (11,12): return None
    events={}
    for et in range(ntypes):
        while True:
            en=i32(b,p); p+=4
            if en==-1: break
            if not (0<=en<=4096): raise ValueError('bad event number')
            if u32(b,p)!=ACTLIST_VER: raise ValueError('bad actlist ver')
            p+=4
            na=u32(b,p); p+=4
            if na>4096: raise ValueError('bad action count')
            chunks=[]
            for _ in range(na):
                code,args,p=parse_action(b,p)
                # code actions carry their GML in arg[0]; execute-code actions in `code`
                for s in ([code]+list(args)):
                    if len(s)>8 and (b'(' in s or b'=' in s or b'\n' in s):
                        chunks.append(s.decode('utf-8','replace'))
            if chunks: events.setdefault(f'{et}:{en}',[]).extend(chunks)
    return dict(name=name.decode(), sprite=sprite, depth=depth, parent=parent,
                persistent=persistent, events=events), p

def candidates(b):
    """Ascending positions where an object record plausibly starts.

    A record is [u32 name_len][name][u32 OBJ_VER], so the version dword is found
    first and the start backed out of it -- 64 checks per hit instead of a struct
    unpack at all ~7M byte positions of the tree. Same positions, same order.
    """
    tag = struct.pack('<I', OBJ_VER)
    out = []
    v = b.find(tag)
    while v >= 0:
        for pos in range(max(0, v - 4 - 64), v - 4):
            if u32(b, pos) == v - 4 - pos:
                out.append(pos)
        v = b.find(tag, v + 1)
    out.sort()
    return out


def main(path):
    b=open(path,'rb').read()
    objs=[]; seen=set()
    for pos in candidates(b):
        try:
            r=parse_object(b,pos)
        except Exception:
            continue
        if not r: continue
        o,end=r
        if o['name'] in seen: continue
        seen.add(o['name']); o['_pos']=pos; o['_end']=end
        objs.append(o)
    objs.sort(key=lambda o:o['_pos'])
    print(f"parsed {len(objs)} object records", file=sys.stderr)
    return objs


def walk_section(path=DEFAULT_TREE):
    """Walk the object section in index order, honouring empty slots.

    Returns {object_index: record or None}. The section header is located from the
    first parsable object record, so no absolute offset is baked in.
    """
    b = open(path, 'rb').read()
    first = None
    for pos in candidates(b):
        try:
            if parse_object(b, pos):
                first = pos
                break
        except Exception:
            continue
    if first is None:
        raise ValueError('no object records found')
    count = u32(b, first - 12)
    p, idx, table = first - 8, 0, {}
    while idx < count and p < len(b) - 8:
        exists = u32(b, p); p += 4
        if exists == 0:
            table[idx] = None; idx += 1; continue
        r = parse_object(b, p)
        if not r:
            raise ValueError('parse failed at object index %d (0x%X)' % (idx, p))
        table[idx], p = r[0], r[1]
        idx += 1
    return table

if __name__=='__main__':
    objs=main(sys.argv[1] if len(sys.argv)>1 else DEFAULT_TREE)
    json.dump(objs, open('objects.json','w'))
    for o in objs[:15]:
        evs=', '.join(f"{EVENT_TYPES.get(int(k.split(':')[0]),k)}[{k.split(':')[1]}]" for k in o['events'])
        print(f"  {o['name']:24s} parent={o['parent']:6d} depth={o['depth']:6d} events: {evs[:110]}")
