import argparse

def parse_args():
    parser = argparse.ArgumentParser()
    # 已经验证这里的参数可被存入params.json

    parser.add_argument('--debug', action='store_true', default=False, )
    parser.add_argument('--test', action='store_true', default=False, )
    parser.add_argument('--test-with-shenbi', action='store_true')
    parser.add_argument('--test-save-heatmap', action='store_true')
    parser.add_argument('--user', type=str, default='yyx')
    parser.add_argument('--env', type=str, default='Mobile')
    parser.add_argument('--algo', type=str, required=False, default='IPPO', help="algorithm(G2ANet/IC3Net/CPPO/DPPO/IA2C/IPPO/Random) ")
    parser.add_argument('--device', type=str, required=False, default='cuda:0', help="device(cpu/cuda:0/cuda:1/...) ")
    parser.add_argument("--dataset", type=str, default='NCSU', choices=['NCSU', 'KAIST', 'purdue'])
    parser.add_argument("--poi_num", type=int, default=116)  # KAIST
    parser.add_argument("--tag", type=str, default='', help='每个单独实验的备注')
    # dirs
    parser.add_argument("--output_dir", type=str, default='runs/debug', help="which fold to save under 'runs/'")
    parser.add_argument('--group', type=str, default='debug', help='填写我对一组实验的备注，作用与wandb的group和tb的实验保存路径')
    # system stub
    parser.add_argument('--mute_wandb', default=True, action='store_false')  # 后期服务器联网不稳定 网断了进程就会sleep 不要用wandb！
    # tune agent
    parser.add_argument('--checkpoint', type=str)  # load pretrained model
    parser.add_argument('--n_thread', type=int, default=16)
    parser.add_argument('--n_iter', type=int, default=-1)
    # tune algo
    parser.add_argument('--lr', type=float)
    parser.add_argument('--lr_v', type=float)
    parser.add_argument('--lr_colla', type=float)
    parser.add_argument('--use-stack-frame', action='store_true')
    # parser.add_argument('--use_extended_value', action='store_false', help='反逻辑，仅用于DPPO')
    # parser.add_argument('--use-mlp-model', action='store_true', help='将model改为最简单的mlp，仅用于DMPO')
    # parser.add_argument('--multi-mlp', action='store_true', help='在model中分开预测obs中不同类别的信息，仅用于DMPO')
    parser.add_argument('--g2a_hidden_dim', type=int, default=64, help='在model中分开预测obs中不同类别的信息，仅用于DMPO')
    parser.add_argument('--tau', type=float, default=0.01)
    parser.add_argument('--map_size', type=int, default=6)  # hyper
    parser.add_argument('--g2a_hops', type=int, default=1)  # hyper
    parser.add_argument('--update_colla_by_v_0307', action='store_true')  # hyper

    # tune env
    ## setting
    parser.add_argument('--fixed-range', action='store_false')  # 重要，sensing range现在固定了
    parser.add_argument('--collect_range', type=float, default=500)
    parser.add_argument('--dyna_level', type=str, default='2', help='指明读取不同难度的poi_QoS.npy')
    parser.add_argument('--init_energy', type=float, default=719280)
    parser.add_argument('--w_noise', type=float, default=-107)  # 0222morning determined
    parser.add_argument('--user_data_amount', type=float, default=0.75)
    parser.add_argument('--update_num', type=int, default=10)  # 两个数据集统一将default设为10
    parser.add_argument('--uav_num', type=int, default=5)
    parser.add_argument('--fixed-col-time', action='store_false')
    parser.add_argument('--aoith', default=30, type=int)  # 0222morning determined
    parser.add_argument('--txth', default=3, type=int)
    parser.add_argument('--uav_height', default=100, type=int)
    parser.add_argument('--hao02191630', action='store_false')
    parser.add_argument('--always_fixed_antenna02230040', default=-1, type=int)

    ## MDP
    parser.add_argument('--max_episode_step', type=int, default=120)
    parser.add_argument('--future_obs', type=int, default=0)
    parser.add_argument('--use_snrmap', action='store_true')  # shrotcut is always used
    parser.add_argument('--high_level_dont_use_snrmap', action='store_true')  #
    parser.add_argument('--high_level_knn_coefficient', type=float, default=-1)  #
    parser.add_argument('--aVPS', type=float, default=0.2)
    parser.add_argument('--tVPS', type=float, default=0.2)
    parser.add_argument('--agent_field', type=float, default=750)
    input_args = parser.parse_args()


    if input_args.test_with_shenbi:
        input_args.test = True


    if input_args.algo == 'G2ANet':
        input_args.use_snrmap = True
        if input_args.dataset == 'NCSU':
            input_args.knn_coefficient = 0.1
        elif input_args.dataset == 'KAIST':
            input_args.knn_coefficient = 0.5
        else:
            raise NotImplementedError


    if input_args.algo == 'ConvLSTM':
        input_args.use_snrmap = True

    if input_args.algo == 'Random':
        input_args.mute_wandb = True
        input_args.n_thread = 1

    if input_args.high_level_dont_use_snrmap:
        input_args.use_snrmap = False
    if input_args.high_level_knn_coefficient != -1:
        input_args.knn_coefficient = input_args.high_level_knn_coefficient

    if input_args.debug:
        input_args.group = 'debug'
        input_args.n_thread = 2
    input_args.output_dir = f'runs/{input_args.group}'

    if input_args.test:
        input_args.group = 'test'
        input_args.n_thread = 1
        input_args.output_dir = f'{input_args.checkpoint}/test'


    if input_args.dataset == 'NCSU':  # 在NCSU的默认值
        if input_args.poi_num == 116:
            input_args.poi_num = 48

    env_args = {
        "max_episode_step": input_args.max_episode_step,
        "collect_range": input_args.collect_range,
        "initial_energy": input_args.init_energy,
        "user_data_amount": input_args.user_data_amount,
        "update_num": input_args.update_num,
        "uav_num": input_args.uav_num,
        "AoI_THRESHOLD": input_args.aoith,
        "RATE_THRESHOLD": input_args.txth,
        "uav_height": input_args.uav_height,
        "aoi_vio_penalty_scale": input_args.aVPS,
        "hao02191630": input_args.hao02191630,
        "w_noise": input_args.w_noise,
        "agent_field": input_args.agent_field,
    }
    if input_args.poi_num is not None:
        env_args["poi_num"] = input_args.poi_num

    return input_args, env_args