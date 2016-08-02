import torch
from torch.legacy import nn

# tensorCache maintains a list of all tensors and storages that have been
# converted (recursively) by calls to recursiveType() and type().
# It caches conversions in order to preserve sharing semantics
# i.e. if two tensors share a common storage, then type conversion
# should preserve that.
#
# You can preserve sharing semantics across multiple networks by
# passing tensorCache between the calls to type, e.g.
#
# > tensorCache = {}
# > net1:type('torch.cuda.FloatTensor', tensorCache)
# > net2:type('torch.cuda.FloatTensor', tensorCache)
# > nn.utils.recursiveType(anotherTensor, 'torch.cuda.FloatTensor', tensorCache)
def recursiveType(param, type, tensorCache={}):
    if isinstance(param, list):
        for i, p in enumerate(param):
            param[i] = recursiveType(p, type, tensorCache)
    elif isinstance(param, nn.Module) or isinstance(param, nn.Criterion):
        param.type(type, tensorCache)
    elif torch.isTensor(param):
        if torch.typename(param) != type:
            key = param._cdata
            if key in tensorCache:
                newparam = tensorCache[key]
            else:
                newparam = torch.Tensor().type(type)
                storageType = type.replace('Tensor','Storage')
                param_storage = param.storage()
                if param_storage:
                    storage_key = param_storage._cdata
                    if storage_key not in tensorCache:
                        tensorCache[storage_key] = torch._import_dotted_name(storageType)(param_storage.size()).copy(param_storage)
                    newparam.set(
                        tensorCache[storage_key],
                        param.storageOffset(),
                        param.size(),
                        param.stride()
                    )
                tensorCache[key] = newparam
            param = newparam
    return param

def recursiveResizeAs(t1, t2):
    if isinstance(t2, list):
        t1 = t1 if isinstance(t1, list) else [t1]
        if len(t1) < len(t2):
            t1 += [None] * (len(t2) - len(t1))
        for i, _ in enumerate(t2):
            t1[i], t2[i] = recursiveResizeAs(t1[i], t2[i])
        t1 = t1[:len(t2)]
    elif torch.isTensor(t2):
        t1 = t1 if torch.isTensor(t1) else t2.new()
        t1.resizeAs(t2)
    else:
        raise RuntimeError("Expecting nested tensors or tables. Got " + \
                type(t1).__name__  + " and " + type(t2).__name__  + "instead")
    return t1, t2

def recursiveFill(t2, val):
    if isinstance(t2, list):
        t2 = [recursiveFill(x, val) for x in t2]
    elif torch.isTensor(t2):
        t2.fill(val)
    else:
        raise RuntimeError("expecting tensor or table thereof. Got " + \
            type(t2).__name__ + " instead")
    return t2

def recursiveAdd(t1, val=1, t2=None):
    if t2 is None:
        t2 = val
        val = 1
    if isinstance(t2, list):
        t1 = t1 if isinstance(t1, list) else [t1]
        for i, _ in enumerate(t2):
            t1[i], t2[i] = recursiveAdd(t1[i], val, t2[i])
    elif torch.isTensor(t1) and torch.isTensor(t2):
        t1.add(val, t2)
    else:
        raise RuntimeError("expecting nested tensors or tables. Got " + \
                type(t1).__name__ + " and " + type(t2).__name__ + " instead")
    return t1, t2

def recursiveCopy(t1, t2):
    if isinstance(t2, list):
        t1 = t1 if isinstance(t1, list) else [t1]
        for i, _ in enumerate(t2):
            t1[i], t2[i] = recursiveCopy(t1[i], t2[i])
    elif torch.isTensor(t2):
        t1 = t1 if torch.isTensor(t1) else t2.new()
        t1.resizeAs(t2).copy(t2)
    else:
        raise RuntimeError("expecting nested tensors or tables. Got " + \
                type(t1).__name__ + " and " + type(t2).__name__ + " instead")
    return t1, t2

def addSingletonDimension(*args):
    view = None
    if len(args) < 3:
        t, dim = args
    else:
        view, t, dim = args
        assert torch.isTensor(view)

    assert torch.isTensor(t)

    if view is None:
        view = t.new()
    size = torch.LongStorage(t.dim() + 1)
    stride = torch.LongStorage(t.dim() + 1)

    for d in range(dim):
        size[d] = t.size(d)
        stride[d] = t.stride(d)
    size[dim] = 1
    stride[dim] = 1
    for d in range(dim+1, t.dim()+1):
        size[d] = t.size(d - 1)
        stride[d] = t.stride(d - 1)

    view.set(t.storage(), t.storageOffset(), size, stride)
    return view

def contiguousView(output, input, *args):
    output = output or input.new()
    if input.isContiguous():
        output.view(input, *args)
    else:
        output.resizeAs(input)
        output.copy(input)
        output.view(output, *args)
    return output

# go over specified fields and clear them. accepts
# nn.utils.clearState(self, ['_buffer', '_buffer2']) and
# nn.utils.clearState(self, '_buffer', '_buffer2')
def clear(self, *args):
    if len(args) == 1 and isinstance(args[0], list):
        args = args[1]
    def _clear(f):
        if not hasattr(self, f):
            return
        attr = getattr(self, f)
        if torch.isTensor(attr):
            attr.set()
        elif isinstance(attr, list):
            del attr[:]
        else:
            delattr(self, f)
    for key in arg:
        _clear(key)
    return self

