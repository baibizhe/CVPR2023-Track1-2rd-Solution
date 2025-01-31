# !/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Facebook, Inc. and its affiliates.

import logging
import numpy as np
import time
import weakref
from typing import List, Mapping, Optional
import pickle

import paddle
from paddle.distributed.fleet.utils.hybrid_parallel_util import fused_allreduce_gradients

from utils import comm
# import fastreid.engine
from detectron2.utils.events import EventStorage, get_event_storage
from detectron2.utils.logger import _log_api_usage

__all__ = ["HookBase", "TrainerBase", "SimpleTrainer", "AMPTrainer"]


class HookBase:
    """
    Base class for hooks that can be registered with :class:`TrainerBase`.

    Each hook can implement 4 methods. The way they are called is demonstrated
    in the following snippet:
    ::
        hook.before_train()
        for iter in range(start_iter, max_iter):
            hook.before_step()
            trainer.run_step()
            hook.after_step()
        iter += 1
        hook.after_train()

    Notes:
        1. In the hook method, users can access ``self.trainer`` to access more
           properties about the context (e.g., model, current iteration, or config
           if using :class:`DefaultTrainer`).

        2. A hook that does something in :meth:`before_step` can often be
           implemented equivalently in :meth:`after_step`.
           If the hook takes non-trivial time, it is strongly recommended to
           implement the hook in :meth:`after_step` instead of :meth:`before_step`.
           The convention is that :meth:`before_step` should only take negligible time.

           Following this convention will allow hooks that do care about the difference
           between :meth:`before_step` and :meth:`after_step` (e.g., timer) to
           function properly.

    """

    trainer: "TrainerBase" = None
    """
    A weak reference to the trainer object. Set by the trainer when the hook is registered.
    """

    def before_train(self):
        """
        Called before the first iteration.
        """
        pass

    def after_train(self):
        """
        Called after the last iteration.
        """
        pass

    def before_step(self):
        """
        Called before each iteration.
        """
        pass

    def after_step(self):
        """
        Called after each iteration.
        """
        pass

    def state_dict(self):
        """
        Hooks are stateless by default, but can be made checkpointable by
        implementing `state_dict` and `load_state_dict`.
        """
        return {}


class TrainerBase:
    """
    Base class for iterative trainer with hooks.

    The only assumption we made here is: the training runs in a loop.
    A subclass can implement what the loop is.
    We made no assumptions about the existence of dataloader, optimizer, model, etc.

    Attributes:
        iter(int): the current iteration.

        start_iter(int): The iteration to start with.
            By convention the minimum possible value is 0.

        max_iter(int): The iteration to end training.

        storage(EventStorage): An EventStorage that's opened during the course of training.
    """

    def __init__(self):
        self._hooks=[]
        self.iter=0
        self.start_iter=0
        self.max_iter=0
        self.storage=None
        _log_api_usage("trainer." + self.__class__.__name__)

    def register_hooks(self, hooks=[]):
        """
        Register hooks to the trainer. The hooks are executed in the order
        they are registered.

        Args:
            hooks (list[Optional[HookBase]]): list of hooks
        """
        hooks = [h for h in hooks if h is not None]
        for h in hooks:
            # assert isinstance(h, HookBase) or isinstance(h, fastreid.engine.HookBase)
            assert isinstance(h, HookBase) #TODO include fastreid.engine.HookBase
            # To avoid circular reference, hooks and trainer cannot own each other.
            # This normally does not matter, but will cause memory leak if the
            # involved objects contain __del__:
            # See http://engineering.hearsaysocial.com/2013/06/16/circular-references-in-python/
            h.trainer = weakref.proxy(self)
        self._hooks.extend(hooks)

    def train(self, start_iter, max_iter):
        """
        Args:
            start_iter, max_iter (int): See docs above
        """
        logger = logging.getLogger(__name__)
        logger.info("Starting training from iteration {}".format(start_iter))

        self.iter = self.start_iter = start_iter
        self.max_iter = max_iter

        with EventStorage(start_iter) as self.storage:
            try:
                self.before_train()
                for self.iter in range(start_iter, max_iter):
                    self.before_step()
                    self.run_step()
                    self.after_step()
                # self.iter == max_iter can be used by `after_train` to
                # tell whether the training successfully finished or failed
                # due to exceptions.
                self.iter += 1
            except Exception:
                logger.exception("Exception during training:")
                raise
            finally:
                self.after_train()

    def before_train(self):
        for h in self._hooks:
            h.before_train()

    def after_train(self):
        self.storage.iter = self.iter
        for h in self._hooks:
            h.after_train()

    def before_step(self):
        # Maintain the invariant that storage.iter == trainer.iter
        # for the entire execution of each step
        self.storage.iter = self.iter

        for h in self._hooks:
            h.before_step()

    def after_step(self):
        for h in self._hooks:
            h.after_step()

    def run_step(self):
        raise NotImplementedError

    def state_dict(self):
        ret = {"iteration": self.iter}
        hooks_state = {}
        for h in self._hooks:
            sd = h.state_dict()
            if sd:
                name = type(h).__qualname__
                if name in hooks_state:
                    # TODO handle repetitive stateful hooks
                    continue
                hooks_state[name] = sd
        if hooks_state:
            ret["hooks"] = hooks_state
        return ret

    def set_state_dict(self, state_dict):
        logger = logging.getLogger(__name__)
        self.iter = state_dict["iteration"]
        for key, value in state_dict.get("hooks", {}).items():
            for h in self._hooks:
                try:
                    name = type(h).__qualname__
                except AttributeError:
                    continue
                if name == key:
                    h.set_state_dict(value)
                    break
            else:
                logger.warning(f"Cannot find the hook '{key}', its state_dict is ignored.")


class SimpleTrainer(TrainerBase):
    """
    A simple trainer for the most common type of task:
    single-cost single-optimizer single-data-source iterative optimization,
    optionally using data-parallelism.
    It assumes that every step, you:

    1. Compute the loss with a data from the data_loader.
    2. Compute the gradients with the above loss.
    3. Update the model with the optimizer.

    All other tasks during training (checkpointing, logging, evaluation, LR schedule)
    are maintained by hooks, which can be registered by :meth:`TrainerBase.register_hooks`.

    If you want to do anything fancier than this,
    either subclass TrainerBase and implement your own `run_step`,
    or write your own training loop.
    """

    def __init__(self, model, data_loader, optimizer):
        """
        Args:
            model: a torch Module. Takes a data from data_loader and returns a
                dict of losses.
            data_loader: an iterable. Contains data to be used to call model.
            optimizer: a torch optimizer.
        """
        super().__init__()

        """
        We set the model to training mode in the trainer.
        However it's valid to train a model that's in eval mode.
        If you want your model (or a submodule of it) to behave
        like evaluation during training, you can overwrite its train() method.
        """
        model.train()

        self.model = model
        self.data_loader = data_loader
        self._data_loader_iter = iter(data_loader)
        self.optimizer = optimizer
        self.grad_scaler = None
        self.data = None

    def run_step(self):
        """
        Implement the standard training logic described above.
        """
        assert self.model.training, "[SimpleTrainer] model was changed to eval mode!"
        start = time.perf_counter()
        """
        If you want to do something with the data, you can wrap the dataloader.
        """
        # if self.data is None:
        #     data = next(self._data_loader_iter)
        #     self.data = data
        # else:
        #     data = self.data
        data = next(self._data_loader_iter)
        data_time = time.perf_counter() - start

        """
        If you want to do something with the losses, you can wrap the model.
        """
        """
        If you need to accumulate gradients or do something similar, you can
        wrap the optimizer with your custom `zero_grad()` method.
        """
        # self.optimizer.clear_grad()
        # # step 1 : skip gradient synchronization by 'no_sync'
        # with self.model.no_sync():
        #     loss_dict = self.model(data)
        #     if isinstance(loss_dict, paddle.Tensor):
        #         losses = loss_dict
        #         loss_dict = {"total_loss": loss_dict}
        #     else:
        #         losses = sum(loss_dict.values()) 
        #     losses.backward()
        # # step 2 : fuse + allreduce manually before optimization
        # fused_allreduce_gradients(list(self.model.parameters()), None)
        loss_dict = {}
        self.optimizer.clear_grad()
        with self.model.no_sync():  #多gpu条件下
            for task_name, val in data.items():
                task_loss_dict = self.model({task_name: val}, self.iter) #self.teacher)
                losses = sum(task_loss_dict.values())
                losses.backward()
                loss_dict.update(task_loss_dict)
        # for task_name, val in data.items():  #单独gpu
        #     task_loss_dict = self.model({task_name: val}, self.iter) #self.teacher)
        #     losses = sum(task_loss_dict.values())
        #     losses.backward() 
        #     loss_dict.update(task_loss_dict)
        fused_allreduce_gradients(list(self.model.parameters()), None)  #单机训练可以注释掉

        self._write_metrics(loss_dict, data_time)
        """
        If you need gradient clipping/scaling or other processing, you can
        wrap the optimizer with your custom `step()` method. But it is
        suboptimal as explained in https://arxiv.org/abs/2006.15704 Sec 3.2.4
        """
        self.optimizer.step()

    def _write_metrics(
        self,
        loss_dict,
        data_time,
        prefix="",
    ):
        SimpleTrainer.write_metrics(loss_dict, data_time, prefix)

    @staticmethod
    def write_metrics(
        loss_dict,
        data_time,
        prefix="",
    ):
        """
        Args:
            loss_dict (dict): dict of scalar losses
            data_time (float): time taken by the dataloader iteration
            prefix (str): prefix for logging keys
        """
        # metrics_dict = {k: v.detach().cpu().item() for k, v in loss_dict.items()}
        

        # Gather metrics among all workers for logging
        # This assumes we do DDP-style training, which is currently the only
        # supported method in detectron2.

        metrics_dict = {}
        for k, v in loss_dict.items():
            v_list = comm.gather_v(v)
            metrics_dict[k] = np.mean([v.detach().cpu().numpy() for v in v_list])
        # metrics_dict["data_time"] = data_time
        if comm.is_main_process():
            storage = get_event_storage()

            # data_time among workers can have high variance. The actual latency
            # caused by data_time is the maximum among workers.
            # data_time = metrics_dict["data_time"]
            storage.put_scalar("data_time", data_time)

            # average the rest metrics
            # metrics_dict = {
            #     k: np.mean([x[k].detach().cpu().numpy() for x in all_metrics_dict]) for k in all_metrics_dict[0].keys()
            # }
            total_losses_reduced = sum(metrics_dict.values())
            if not np.isfinite(total_losses_reduced):
                raise FloatingPointError(
                    "Loss became infinite or NaN at iteration={storage.iter}!\n"
                    "loss_dict = {metrics_dict}"
                )

            storage.put_scalar("{}total_loss".format(prefix), total_losses_reduced)
            if len(metrics_dict) > 1:
                storage.put_scalars(**metrics_dict)

    def state_dict(self):
        ret = super().state_dict()
        ret["optimizer"] = self.optimizer.state_dict()
        return ret

    def set_state_dict(self, state_dict):
        # state_dict["optimizer"]['dymic_weight_moment1_0'] = paddle.zeros([3]) #增加的
        # state_dict["optimizer"]['dymic_weight_moment2_0'] = paddle.zeros([3]) #增加的
        # state_dict["optimizer"]['dymic_weight_beta1_pow_acc_0'] = paddle.zeros([1])  #增加的
        # state_dict["optimizer"]['dymic_weight_beta2_pow_acc_0'] = paddle.zeros([1])  #增加的
        super().set_state_dict(state_dict)
        self.optimizer.set_state_dict(state_dict["optimizer"])


class AMPTrainer(SimpleTrainer):
    """
    Like :class:`SimpleTrainer`, but uses PyTorch's native automatic mixed precision
    in the training loop.
    """

    def __init__(self, model, data_loader, optimizer, grad_scaler=None):
        """
        Args:
            model, data_loader, optimizer: same as in :class:`SimpleTrainer`.
            grad_scaler: torch GradScaler to automatically scale gradients.
        """
        unsupported = "AMPTrainer does not support single-process multi-device training!"
        # if isinstance(model,  paddle.DataParallel):
        #     assert not (model.device_ids and len(model.device_ids) > 1), unsupported
        # assert not isinstance(model, DataParallel), unsupported

        super().__init__(model, data_loader, optimizer)

        if grad_scaler is None:
            grad_scaler = paddle.amp.GradScaler(init_loss_scaling=1024.0)
        self.grad_scaler = grad_scaler

    def run_step(self):
        """
        Implement the AMP training logic.
        """
        assert self.model.training, "[AMPTrainer] model was changed to eval mode!"
        start = time.perf_counter()
        data = next(self._data_loader_iter)
        data_time = time.perf_counter() - start
        # with paddle.amp.auto_cast():
        #     loss_dict = self.model(data) #self.teacher)
        #     if isinstance(loss_dict, paddle.Tensor):
        #         losses = loss_dict
        #         loss_dict = {"total_loss": loss_dict}
        #     else:
        #         losses = sum(loss_dict.values())
        # scaled = self.grad_scaler.scale(losses)
        # scaled.backward()
        # self.grad_scaler.minimize(self.optimizer, scaled)
        # self.optimizer.clear_grad()

        # # step 1 : skip gradient synchronization by 'no_sync'
        # with model.no_sync():
        #     y_pred = model(x)
        #     loss = y_pred.mean()
        #     loss.backward()

        # # step 2 : fuse + allreduce manually before optimization
        # fused_allreduce_gradients(list(model.parameters()), None)
        # with paddle.amp.auto_cast():
        #     self.optimizer.clear_grad()
        #     with self.model.no_sync():
        #         loss_dict = self.model(data) #self.teacher)
        #         if isinstance(loss_dict, paddle.Tensor):
        #             losses = loss_dict
        #             loss_dict = {"total_loss": loss_dict}
        #         else:
        #             losses = sum(loss_dict.values())       
        #         scaled = self.grad_scaler.scale(losses)
        #         scaled.backward()
        #     fused_allreduce_gradients(list(self.model.parameters()), None)
        #     self.grad_scaler.minimize(self.optimizer, scaled)
        loss_dict = {}
        with paddle.amp.auto_cast():
            self.optimizer.clear_grad()
            with self.model.no_sync():
                for task_name, val in data.items():
                    task_loss_dict = self.model({task_name: val}) #self.teacher)
                    losses = sum(task_loss_dict.values())       
                    scaled = self.grad_scaler.scale(losses)
                    scaled.backward()
                    loss_dict.update(task_loss_dict)
            fused_allreduce_gradients(list(self.model.parameters()), None)
            self.grad_scaler.minimize(self.optimizer, scaled)
        self._write_metrics(loss_dict, data_time)

    def state_dict(self):
        ret = super().state_dict()
        ret["grad_scaler"] = self.grad_scaler.state_dict()
        return ret

    def set_state_dict(self, state_dict):
        super().set_state_dict(state_dict)
        self.grad_scaler.load_state_dict(state_dict["grad_scaler"])



