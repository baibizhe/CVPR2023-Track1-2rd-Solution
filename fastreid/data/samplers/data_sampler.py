# !/usr/bin/env python3
# encoding: utf-8
"""
@author:  l1aoxingyu
@contact: sherlockliao01@gmail.com
"""
import itertools
from typing import Optional
import logging

import numpy as np
from paddle.io import Sampler

from utils import comm
logger = logging.getLogger(__name__)

class TrainingSampler(Sampler):
    """
    In training, we only care about the "infinite stream" of training data.
    So this sampler produces an infinite stream of indices and
    all workers cooperate to correctly shuffle the indices and sample different indices.
    The samplers in each worker effectively produces `indices[worker_id::num_workers]`
    where `indices` is an infinite stream of indices consisting of
    `shuffle(range(size)) + shuffle(range(size)) + ...` (if shuffle is True)
    or `range(size) + range(size) + ...` (if shuffle is False)
    """

    def __init__(self, dataset, shuffle=True, seed=None, dp_group=None, moe_group=None):
        """
        Args:
            size (int): the total number of data of the underlying dataset to sample from
            shuffle (bool): whether to shuffle the indices or not
            seed (int): the initial seed of the shuffle. Must be the same
                across all workers. If None, will use a random seed shared
                among workers (require synchronization among all workers).
        """
        self._size = len(dataset)
        assert self._size > 0
        self._shuffle = shuffle
        if seed is None:
            seed = comm.shared_random_seed()
        self._seed = int(seed)

        # self._rank = comm.get_rank()
        # self._world_size = comm.get_world_size()
        if dp_group is None: 
            self._rank = comm.get_rank()
            self._world_size = comm.get_world_size()
        else:
            self._rank = comm.get_rank() // moe_group.nranks
            self._world_size = dp_group.nranks
        logger.info("dataset {}: rank {} is mapped to _rank {} under the real local world size {}".format(dataset.dataset_name, comm.get_rank(), self._rank, self._world_size))
        self._generate_indices()

    def _generate_indices(self,):
        indices = self._finite_indices()
        
        local_indices = []
        for i in range(self._rank, len(indices), self._world_size):
            local_indices.append(indices[i])
        self.local_indices = local_indices

    def __iter__(self):
        # while True:
        #     for indice in self.local_indices:
        #         yield indice
        #     self._seed += 1
        #     self._generate_indices()
        # yield from self.local_indices
        start = self._rank
        yield from itertools.islice(self._infinite_indices(), start, None, self._world_size)
    
    def __len__(self,):
        return 0 #len(self.local_indices)

    def _finite_indices(self,):
        np.random.seed(self._seed)
        if self._shuffle:
            ret_indices =  np.random.permutation(self._size)
        else:
            ret_indices = np.arange(self._size)
        return ret_indices

    def _infinite_indices(self):
        np.random.seed(self._seed)
        while True:
            if self._shuffle:
                yield from np.random.permutation(self._size)
            else:
                yield from np.arange(self._size)




# def _weighted_sample(weights, num_samples, replacement=True):
#     if isinstance(weights, core.LoDTensor):
#         weights = weights.numpy()
#     if isinstance(weights, (list, tuple)):
#         weights = np.array(weights)
#     assert isinstance(weights, np.ndarray), \
#             "weights should be paddle.Tensor, numpy.ndarray, list or tuple"
#     assert len(weights.shape) <= 2, \
#             "weights should be a 1-D or 2-D array"
#     weights = weights.reshape((-1, weights.shape[-1]))
#     assert np.all(weights >= 0.), \
#             "weights should be positive value"
#     assert not np.any(weights == np.inf), \
#             "weights shoule not be INF"
#     assert not np.any(weights == np.nan), \
#             "weights shoule not be NaN"

#     non_zeros = np.sum(weights > 0., axis=1)
#     assert np.all(non_zeros > 0), \
#             "weights should have positive values"
#     if not replacement:
#         assert np.all(non_zeros >= num_samples), \
#             "weights positive value number should not " \
#             "less than num_samples when replacement=False"

#     weights = weights / weights.sum(axis=1)
#     rets = []
#     for i in range(weights.shape[0]):
#         ret = np.random.choice(weights.shape[1], num_samples, replacement,
#                                weights[i])
#         rets.append(ret)
#     return np.array(rets)


# #重写无限流的数据读取
# class TrainingWeightedRandomSampler(Sampler):
#     def __init__(self, dataset, weights, seed=None, dp_group=None, moe_group=None ,replacement=True):
#         if not isinstance(replacement, bool):
#             raise ValueError("replacement should be a boolean value")
#         self.weights = weights  #采样权重
#         self.replacement = replacement
#         self._size = len(dataset)  #数据集样本数
#         assert self._size > 0
#         # self._shuffle = shuffle
#         if seed is None:
#             seed = comm.shared_random_seed()
#         self._seed = int(seed)

#         # self._rank = comm.get_rank()
#         # self._world_size = comm.get_world_size()
#         if dp_group is None: 
#             self._rank = comm.get_rank()
#             self._world_size = comm.get_world_size()
#         else:
#             self._rank = comm.get_rank() // moe_group.nranks
#             self._world_size = dp_group.nranks
#         logger.info("dataset {}: rank {} is mapped to _rank {} under the real local world size {}".format(dataset.dataset_name, comm.get_rank(), self._rank, self._world_size))
#         self._generate_indices()

#     def _generate_indices(self,):
#         indices = self._finite_indices()
        
#         local_indices = []
#         for i in range(self._rank, len(indices), self._world_size):
#             local_indices.append(indices[i])
#         self.local_indices = local_indices

#     def _finite_indices(self,):
#         np.random.seed(self._seed)
#         ret_indices = np.random.shuffle(_weighted_sample(self.weights, self._size,
#                             self.replacement))  #产生indice
#         return ret_indices

#     def _infinite_indices(self):
#         np.random.seed(self._seed)
#         while True:
#             yield from  np.random.shuffle(_weighted_sample(self.weights, self._size, self.replacement))  #产生indice

#     def __iter__(self):
#         start = self._rank
#         yield from itertools.islice(self._infinite_indices(), start, None, self._world_size)    
    

    # def __len__(self,):
    #     return 0 #len(self.local_indices)

    # def __iter__(self):
    #     idxs = _weighted_sample(self.weights, self._size,
    #                             self.replacement)
    #     return iter(idxs.reshape((-1)).tolist())

    # def __len__(self):
    #     mul = np.prod(self.weights.shape) // self.weights.shape[-1]
    #     return self._size * mul





class InferenceSampler(Sampler):
    """
    Produce indices for inference.
    Inference needs to run on the __exact__ set of samples,
    therefore when the total number of samples is not divisible by the number of workers,
    this sampler produces different number of samples on different workers.
    """

    def __init__(self, dataset, dp_group=None, moe_group=None):
        """
        Args:
            size (int): the total number of data of the underlying dataset to sample from
        """
        self._size = len(dataset)
        assert self._size > 0
        if dp_group is None: 
            self._rank = comm.get_rank()
            self._world_size = comm.get_world_size()
        else:
            self._rank = comm.get_rank() // moe_group.nranks
            self._world_size = dp_group.nranks
        logger.info("dataset {}: rank {} is mapped to _rank {} under the real local world size {}".format(dataset.dataset_name, comm.get_rank(), self._rank, self._world_size))

        # shard_size = (self._size - 1) // self._world_size + 1
        # begin = shard_size * self._rank
        # end = min(shard_size * (self._rank + 1), self._size)
        # self._local_indices = range(begin, end)

        # shard_size = self._size // self._world_size
        # begin = shard_size * self._rank
        # end = min(shard_size * (self._rank + 1), self._size)
        # self._local_indices = range(begin, end)

        self._local_indices = range(self._rank, self._size, self._world_size)

    def __iter__(self):
        yield from self._local_indices

    def __len__(self):
        return len(self._local_indices)


class OrderInferenceSampler(Sampler):
    """
    Produce indices for inference.
    Inference needs to run on the __exact__ set of samples,
    therefore when the total number of samples is not divisible by the number of workers,
    this sampler produces different number of samples on different workers.
    """

    def __init__(self, dataset, mini_batch_size, dp_group=None, moe_group=None):
        """
        Args:
            size (int): the total number of data of the underlying dataset to sample from
        """
        self._size = len(dataset)
        assert self._size > 0
        if dp_group is None: 
            self._rank = comm.get_rank()
            self._world_size = comm.get_world_size()
        else:
            self._rank = comm.get_rank() // moe_group.nranks
            self._world_size = dp_group.nranks
        logger.info("dataset {}: rank {} is mapped to _rank {} under the real local world size {}".format(dataset.dataset_name, comm.get_rank(), self._rank, self._world_size))
        batch_size = mini_batch_size * self._world_size

        # shard_size = (self._size - 1) // self._world_size + 1
        # begin = shard_size * self._rank
        # end = min(shard_size * (self._rank + 1), self._size)
        # self._local_indices = range(begin, end)

        # shard_size = self._size // self._world_size
        # begin = shard_size * self._rank
        # end = min(shard_size * (self._rank + 1), self._size)
        # self._local_indices = range(begin, end)

        # self._local_indices = range(self._rank, self._size, self._world_size)

        self._local_indices = []
        if self._size % batch_size == 0:
            for j in range(0, self._size//batch_size):
                for i in range(0, mini_batch_size):
                    idx = self._rank * mini_batch_size + i + j * batch_size
                    if idx < self._size:
                        self._local_indices.append(idx)
                    else:
                        break
        else:
            for j in range(0, self._size//batch_size):
                for i in range(0, mini_batch_size):
                    idx = self._rank * mini_batch_size + i + j * batch_size
                    if idx < self._size:
                        self._local_indices.append(idx)
                    else:
                        break
            left = self._size % batch_size
            assert left % self._world_size == 0
            for i in range(0, left // self._world_size):
                idx = self._rank * mini_batch_size + i + j * batch_size
                self._local_indices.append(idx)
        print("rank {} has {} items".format(self._rank, len(self._local_indices)))

    def __iter__(self):
        yield from self._local_indices

    def __len__(self):
        return len(self._local_indices)
