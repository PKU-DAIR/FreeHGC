import numba
import numpy as np
import scipy.sparse as sp
import torch
import scipy
from torch_sparse import SparseTensor

@numba.njit(cache=True, locals={'_val': numba.float32, 'res': numba.float32, 'res_vnode': numba.float32})
def _calc_ppr_node(inode, indptr, indices, deg, alpha, epsilon):
    alpha_eps = alpha * epsilon
    f32_0 = numba.float32(0)
    p = {inode: f32_0}
    r = {}
    r[inode] = alpha
    q = [inode]
    while len(q) > 0:
        unode = q.pop()

        res = r[unode] if unode in r else f32_0
        if unode in p:
            p[unode] += res
        else:
            p[unode] = res
        r[unode] = f32_0
        for vnode in indices[indptr[unode]:indptr[unode + 1]]:
            _val = (1 - alpha) * res / deg[unode]
            if vnode in r:
                r[vnode] += _val
            else:
                r[vnode] = _val

            res_vnode = r[vnode] if vnode in r else f32_0
            if res_vnode >= alpha_eps * deg[vnode]:
                if vnode not in q:
                    q.append(vnode)

    return list(p.keys()), list(p.values())


@numba.njit(cache=True)
def calc_ppr(indptr, indices, deg, alpha, epsilon, nodes):
    js = []
    vals = []
    for i, node in enumerate(nodes):
        j, val = _calc_ppr_node(node, indptr, indices, deg, alpha, epsilon)
        js.append(j)
        vals.append(val)
    return js, vals


@numba.njit(cache=True, parallel=True)
def calc_ppr_topk_parallel(indptr, indices, deg, alpha, epsilon, nodes, topk):
    js = [np.zeros(0, dtype=np.int64)] * len(nodes)
    vals = [np.zeros(0, dtype=np.float32)] * len(nodes)
    for i in numba.prange(len(nodes)):
        j, val = _calc_ppr_node(nodes[i], indptr, indices, deg, alpha, epsilon)
        j_np, val_np = np.array(j), np.array(val)
        
        if topk>0:
            idx_topk = np.argsort(val_np)[-topk:]
            js[i] = j_np[idx_topk]
            vals[i] = val_np[idx_topk]
        else:
            js[i] = j_np
            vals[i] = val_np

    return js, vals


def ppr_topk(adj_matrix, alpha, epsilon, nodes, topk):
    """Calculate the PPR matrix approximately using Anderson."""

    out_degree = np.sum(adj_matrix > 0, axis=1).A1
    nnodes = adj_matrix.shape[0]

    neighbors, weights = calc_ppr_topk_parallel(adj_matrix.indptr, adj_matrix.indices, out_degree,
                                                numba.float32(alpha), numba.float32(epsilon), nodes, topk)

    return construct_sparse(neighbors, weights, (len(nodes), nnodes))


def construct_sparse(neighbors, weights, shape):
    i = np.repeat(np.arange(len(neighbors)), np.fromiter(map(len, neighbors), dtype=int))  #dtype=np.int改为 int
    j = np.concatenate(neighbors)
    return sp.coo_matrix((np.concatenate(weights), (i, j)), shape)


def topk_ppr_matrix(adj_matrix, flag, alpha, eps, idx, topk, normalization='sym'):
    """Create a sparse matrix where each node has up to the topk PPR neighbors and their weights."""


    row = torch.cat((adj_matrix.storage.row(), adj_matrix.t().storage.row()+adj_matrix.size(0)))
    col = torch.cat((adj_matrix.storage.col()+adj_matrix.size(0), adj_matrix.t().storage.col()))
    sparse_sizes = (adj_matrix.size(0)+ adj_matrix.size(1), adj_matrix.size(0)+ adj_matrix.size(1))
    # adj_symm = SparseTensor(row=row, col=col, sparse_sizes=sparse_sizes)
    data = torch.ones(len(row))
    A = scipy.sparse.csr_matrix((data, (row.cpu(), col.cpu())), shape=sparse_sizes)

    topk_matrix = ppr_topk(A, alpha, eps, idx, topk).tocsr()

    if normalization == 'sym':
        # Assume undirected (symmetric) adjacency matrix
        deg = A.sum(1).A1
        deg_sqrt = np.sqrt(np.maximum(deg, 1e-12))
        deg_inv_sqrt = 1. / deg_sqrt

        row, col = topk_matrix.nonzero()
        # assert np.all(deg[idx[row]] > 0)
        # assert np.all(deg[col] > 0)
        topk_matrix.data = deg_sqrt[idx[row]] * topk_matrix.data * deg_inv_sqrt[col]
    elif normalization == 'col':
        # Assume undirected (symmetric) adjacency matrix
        deg = A.sum(1).A1
        deg_inv = 1. / np.maximum(deg, 1e-12)

        row, col = topk_matrix.nonzero()
        # assert np.all(deg[idx[row]] > 0)
        # assert np.all(deg[col] > 0)
        topk_matrix.data = deg[idx[row]] * topk_matrix.data * deg_inv[col]
    elif normalization == 'row':
        pass
    else:
        raise ValueError(f"Unknown PPR normalization: {normalization}")

    if flag:
        return topk_matrix
    else:
        return topk_matrix[:adj_matrix.size(0),adj_matrix.size(0):]


# @numba.njit(cache=True, locals={'_val': numba.float32, 'res': numba.float32, 'res_vnode': numba.float32})
def _calc_gpr_node(inode_list, indptr, indices, deg, alpha, epsilon):
    

    alpha_eps = alpha * epsilon
    # f32_0 = numba.float32(0)
    f32_0 = np.float32(0)
    p = {inode: f32_0 for inode in inode_list}
    r = {inode: alpha for inode in inode_list}
    # r[inode] = alpha
    q = []
    q.extend(inode_list)
    while len(q) > 0:
        unode = q.pop()

        res = r[unode] if unode in r else f32_0
        if unode in p:
            p[unode] += res
        else:
            p[unode] = res
        r[unode] = f32_0
        for vnode in indices[indptr[unode]:indptr[unode + 1]]:
            _val = (1 - alpha) * res / deg[unode]
            if vnode in r:
                r[vnode] += _val
            else:
                r[vnode] = _val

            res_vnode = r[vnode] if vnode in r else f32_0
            if res_vnode >= alpha_eps * deg[vnode]:
                if vnode not in q:
                    q.append(vnode)

    return list(p.keys()), list(p.values())


#-------
# @numba.njit(cache=True, parallel=True)
def calc_gpr_topk_parallel(indptr, indices, deg, alpha, epsilon, train_idx, cls_size, topk):
    js = [np.zeros(0, dtype=np.int64)] * cls_size
    vals = [np.zeros(0, dtype=np.float32)] * cls_size
    for i in numba.prange(cls_size):

        iter_where = np.where(train_idx==i)[0]
        iter_list  = [x for x in iter_where]
        j, val = _calc_gpr_node(iter_list, indptr, indices, deg, alpha, epsilon)
        j_np, val_np = np.array(j), np.array(val)

        if topk>0:
            idx_topk = np.argsort(val_np)[-topk:]
            js[i] = j_np[idx_topk]
            vals[i] = val_np[idx_topk]
        else:
            js[i] = j_np
            vals[i] = val_np

    return js, vals

def topk_gpr_matrix(adj_matrix, alpha, eps, train_idx, topk):

    cls_size = np.max(train_idx)+1

    print(cls_size)
    
    out_degree = np.sum(adj_matrix > 0, axis=1).A1
    
    nnodes = adj_matrix.shape[0]

    neighbors, weights = calc_gpr_topk_parallel(adj_matrix.indptr, adj_matrix.indices, out_degree,
                                                numba.float32(alpha), numba.float32(eps), train_idx, cls_size,topk)

    return construct_sparse(neighbors, weights, (cls_size, nnodes)).tocsr()

