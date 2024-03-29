import os
import os.path as osp
from datetime import datetime
from numpy.core.numeric import indices
from torch.distributions.normal import Normal
from algorithms.utils import collect, mem_report
from algorithms.models import GraphConvolutionalModel, MLP, CategoricalActor
from tqdm.std import trange
# from algorithms.algorithm import ReplayBuffer
from gym.spaces.box import Box
import torch
import torch.nn as nn
from torch.distributions.categorical import Categorical
from torch.optim import Adam
import numpy as np
import pickle
from copy import deepcopy as dp
from algorithms.models import CategoricalActor
import random
import multiprocessing as mp
# import torch.multiprocessing as mp
from torch import distributed as dist
import argparse
from algorithms.algo.buffer import MultiCollect, Trajectory, TrajectoryBuffer, ModelBuffer
import time

def write_output(info, output_dir, tag='train'):
    logging_path = osp.join(output_dir, f'{tag}_output.txt')
    with open(logging_path, 'a') as f:
        f.write('[' + datetime.strftime(datetime.now(), '%Y-%m-%d %H:%M:%S') + ']\n')
        f.write(f""
                # f"best_{tag}_reward: {'%.3f' % self.best_eval_reward if tag == 'eval' else '%.3f' % self.best_train_reward} "
                f"QoI: {'%.3f' % info['QoI']} "
                f"episodic_aoi: {'%.3f' % info['episodic_aoi']} "
                f"aoi_satis_ratio: {'%.3f' % info['aoi_satis_ratio']} "
                f"data_satis_ratio: {'%.3f' % info['data_satis_ratio']} "
                # f"tx_satis_ratio: {'%.3f' % info['tx_satis_ratio']} "
                # f"soft_tx_satis_ratio: {'%.3f' % info['soft_tx_satis_ratio']} "
                f"energy_consuming: {'%.3f' % info['energy_consuming']} "
                + '\n'
                )


class OnPolicyRunner:
    def __init__(self, logger, agent, envs_learn, envs_test, dummy_env,
                 run_args, alg_args, input_args, **kwargs):
        self.run_args = run_args
        self.input_args = input_args
        self.debug = self.run_args.debug
        self.logger = logger
        self.name = run_args.name
        # agent initialization
        self.agent = agent
        self.num_agent = agent.n_agent
        self.device = self.agent.device if hasattr(self.agent, "device") else "cpu"

        if run_args.checkpoint is not None:  # not train from scratch
            self.agent.load_nets(run_args.checkpoint, best=True)
            logger.log(interaction=run_args.start_step)
        self.start_step = run_args.start_step
        self.env_name = input_args.env
        self.algo_name = input_args.algo
        self.n_thread = input_args.n_thread

        # yyx add
        self.best_episode_reward = float('-inf')
        self.best_test_episode_reward = float('-inf')
        self.best_count = 0

        # algorithm arguments
        self.n_iter = alg_args.n_iter
        self.n_inner_iter = alg_args.n_inner_iter
        self.n_warmup = alg_args.n_warmup if not self.run_args.debug else 1
        self.n_model_update = alg_args.n_model_update
        self.n_model_update_warmup = alg_args.n_model_update_warmup if not self.run_args.debug else 1
        self.n_test = alg_args.n_test
        self.test_interval = alg_args.test_interval
        self.rollout_length = alg_args.rollout_length
        self.use_stack_frame = alg_args.use_stack_frame

        # environment initialization
        self.envs_learn = envs_learn
        self.envs_test = envs_test
        self.dummy_env = dummy_env

        # buffer initialization
        self.model_based = alg_args.model_based
        self.model_batch_size = alg_args.model_batch_size
        if self.model_based:
            self.n_traj = alg_args.n_traj
            self.model_traj_length = alg_args.model_traj_length
            self.model_error_thres = alg_args.model_error_thres
            self.model_buffer = ModelBuffer(alg_args.model_buffer_size)
            self.model_update_length = alg_args.model_update_length
            self.model_validate_interval = alg_args.model_validate_interval
            self.model_prob = alg_args.model_prob
        # 一定注意，PPO并不是在每次调用rollout时reset，一次rollout和是否reset没有直接对应关系
        _, self.episode_len = self.envs_learn.reset(), 0
        self.agent.train_saved_hard_att = []
        self.infer_times = []
        # 每个环境分别记录episode_reward
        self.episode_reward = np.zeros((self.input_args.n_thread))

        # load pretrained env model when model-based
        self.load_pretrained_model = alg_args.load_pretrained_model
        if self.model_based and self.load_pretrained_model:
            self.agent.load_model(alg_args.pretrained_model)

    def run(self):  # 被launcher.py调用的主循环

        if self.run_args.test:
            self.test()
            return

        self.routine_count = 0
        self.rr = 0
        # for iter in trange(self.n_iter, desc='rollout env'):
        for iter in range(self.n_iter):
            if iter % 50 == 0:
                self.test()
            if iter % 1000 == 0:
                self.agent.save_nets(dir_name=self.run_args.output_dir, iter=iter)  # routine

            trajs = self.rollout_env(iter)
            if self.model_based:
                self.model_buffer.storeTrajs(trajs)
                if iter % 10 == 0:
                    self.updateModel()

            agentInfo = []
            # for inner in trange(self.n_inner_iter, desc='inner-iter updateAgent'):
            for inner in range(self.n_inner_iter):
                if self.model_based and np.random.uniform() < self.model_prob:  # Use the model with a certain probability
                    trajs = self.rollout_model(trajs)
                info = self.agent.updateAgent(trajs)
                agentInfo.append(info)
                if self.agent.checkConverged(agentInfo):
                    break

            if not self.input_args.algo == 'Random':
                self.logger.log(inner_iter=inner + 1, iter=iter)

    def test(self):
        """
        The environment should return sth like [n_agent, dim] or [batch_size, n_agent, dim] in either numpy or torch.
        """
        returns = []
        lengths = []

        # for i in trange(self.n_test, desc='test'):
        for i in range(self.n_test):
            done, ep_ret, ep_len = False, np.zeros((1,)), 0  # ep_ret改为分threads存
            envs = self.envs_test
            envs.reset()
            self.agent.test_saved_hard_att = []
            infer_times = []
            while not done:  # 测试时限定一个episode最大为length步
                s = envs.get_obs_from_outside()
                start = time.time()
                a = self.agent.act(s, phase='test')  # shape = (-1, 3)
                end = time.time()
                infer_times.append(end-start)
                # if self.input_args.test: print('inference_time:', end-start)
                # 0221凌晨test改为取概率最大动作
                # action1 = a['branch1'].sample()
                # action2 = a['branch2'].sample()
                action1 = a['branch1'].probs.argmax(dim=-1)
                action2 = a['branch2'].probs.argmax(dim=-1)

                a = torch.stack([action1, action2], dim=-1)
                # if len(a.shape) == 2 and a.shape[0] == 1:  # for IA2C and IC3Net 注意：向量环境下这个需要改！
                #     a = a.squeeze(0)
                a = a.detach().cpu().numpy()  # # shape should be (UAV_NUM, )
                s1, r, done, envs_info = envs.step(a.tolist())
                done = done.any()
                ep_ret += r.sum(axis=-1)  # 对各agent的奖励求和
                ep_len += 1
                self.logger.log(interaction=None)

            import matplotlib.pyplot as plt
            if self.input_args.test:
                print('average inference time:', np.mean(infer_times))
                # plt.hist(infer_times, bins=20, range=(0.003, 0.005))
                # plt.show()

            if ep_ret.max() > self.best_test_episode_reward:
                max_id = ep_ret.argmax()
                self.best_test_episode_reward = ep_ret.max()
                best_eval_trajs = self.envs_test.get_saved_trajs()
                poi_aoi_history = self.envs_test.get_poi_aoi_history()
                serves = self.envs_learn.get_serves()
                write_output(envs_info[max_id], self.run_args.output_dir, tag='test')
                adj = np.stack(self.agent.test_saved_hard_att, axis=1)[max_id] if self.input_args.algo == 'G2ANet' else None
                self.dummy_env.save_trajs_2(
                    best_eval_trajs[max_id], poi_aoi_history[max_id], serves[max_id], phase='test', is_newbest=True, adj=adj)

            returns += [ep_ret.sum()]
            lengths += [ep_len]
        returns = np.stack(returns, axis=0)
        lengths = np.stack(lengths, axis=0)
        self.logger.log(test_episode_reward=returns.mean(),
                        test_episode_len=lengths.mean(), test_round=None)
        average_ret = returns.mean()
        if self.input_args.debug:
            print(f"{self.n_test} episodes average accumulated reward: {average_ret}")

        return average_ret

    def rollout_env(self, iter):  # 与环境交互得到trajs
        """
        The environment should return sth like [n_agent, dim] or [batch_size, n_agent, dim] in either numpy or torch.
        """
        self.routine_count += 1

        trajBuffer = TrajectoryBuffer(device=self.device)
        envs = self.envs_learn
        for t in range(int(self.rollout_length / self.input_args.n_thread)):  # 加入向量环境后，控制总训练步数不变
            s = envs.get_obs_from_outside()
            start = time.time()
            dist = self.agent.act(s, phase='train')
            end = time.time()
            self.infer_times.append(end-start)
            a = []
            logp = []
            for key in ['branch1', 'branch2']:
                a_tmp = dist[key].sample()
                logp_tmp = dist[key].log_prob(a_tmp)
                a.append(a_tmp)
                logp.append(logp_tmp)
            a = torch.stack(a, dim=-1)
            logp = torch.stack(logp, dim=-1)

            a = a.detach().cpu().numpy()
            s1, r, done, env_info = envs.step(a.tolist())
            done = done.any()
            trajBuffer.store(s, a, r, s1,
                             np.full((self.n_thread, self.num_agent), done),
                             logp)
            episode_r = r
            assert episode_r.ndim > 1
            episode_r = episode_r.sum(axis=-1)  # 对各agent奖励求和
            self.episode_reward += episode_r
            self.episode_len += 1
            self.logger.log(interaction=None)

            if done:
                ep_r = self.episode_reward
                if self.input_args.debug:
                    print('train episode reward:', ep_r)
                self.logger.log(mean_episode_reward=ep_r.mean(), episode_len=self.episode_len, episode=None)
                self.logger.log(max_episode_reward=ep_r.max(), episode_len=self.episode_len, episode=None)
                if ep_r.max() > self.best_episode_reward:
                    max_id = ep_r.argmax()
                    self.best_episode_reward = ep_r.max()
                    self.best_count += 1
                    self.agent.save_nets(dir_name=self.run_args.output_dir, is_newbest=True)
                    best_train_trajs = self.envs_learn.get_saved_trajs()
                    poi_aoi_history = self.envs_learn.get_poi_aoi_history()
                    serves = self.envs_learn.get_serves()
                    write_output(env_info[max_id], self.run_args.output_dir)
                    adj = np.stack(self.agent.train_saved_hard_att, axis=1)[max_id] if self.input_args.algo == 'G2ANet' else None
                    self.dummy_env.save_trajs_2(
                        best_train_trajs[max_id], poi_aoi_history[max_id], serves[max_id], phase='train', is_newbest=True, adj=adj, best_count=self.best_count)


                if self.routine_count // 500 > 0:  # routinely vis (OK)
                    max_id = ep_r.argmax()
                    best_train_trajs = self.envs_learn.get_saved_trajs()
                    poi_aoi_history = self.envs_learn.get_poi_aoi_history()
                    serves = self.envs_learn.get_serves()
                    adj = np.stack(self.agent.train_saved_hard_att, axis=1)[max_id] if self.input_args.algo == 'G2ANet' else None
                    self.dummy_env.save_trajs_2(
                        best_train_trajs[max_id], poi_aoi_history[max_id], serves[max_id],
                        iter=self.rr*500, phase='train', adj=adj)
                    self.rr += self.routine_count // 500
                    self.routine_count = self.routine_count % 500

                self.logger.log(QoI=sum(d['QoI'] for d in env_info) / len(env_info),
                                episodic_aoi=sum(d['episodic_aoi'] for d in env_info) / len(env_info),
                                aoi_satis_ratio=sum(d['aoi_satis_ratio'] for d in env_info) / len(env_info),
                                data_satis_ratio=sum(d['data_satis_ratio'] for d in env_info) / len(env_info),
                                energy_consuming=sum(d['energy_consuming'] for d in env_info) / len(env_info),
                                good_reward=sum(d['good_reward'] for d in env_info) / len(env_info),
                                aoi_penalty_reward=sum(d['aoi_penalty_reward'] for d in env_info) / len(env_info),
                                knn_reward=sum(d['knn_reward'] for d in env_info) / len(env_info),
                                energy_reward=sum(d['energy_reward'] for d in env_info) / len(env_info),
                                )
                '''执行env的reset'''
                try:
                    if self.debug:
                        print('average inference time:', np.mean(self.infer_times))
                    _, self.episode_len = self.envs_learn.reset(), 0
                    self.agent.train_saved_hard_att = []
                    self.infer_times = []
                    self.episode_reward = np.zeros((self.input_args.n_thread))
                except Exception as e:
                    raise NotImplementedError

        return trajBuffer.retrieve()

