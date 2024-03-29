## Overview

目录树：

```
.
├── source_code
│   ├── algorithms
│   │   ├── algo
│   │   │   ├── agent  # ours和baseline算法类的定义
│   │   │   ├── main.py  # OnPolicyRunner类定义，负责智能体与环境交互
│   ├── envs  
│   │   ├── env_mobile.py  # generate-at-will的aoi定义的场景
│   ├── env_configs  # 环境参数
│   └── tools  # 功能脚本，预处理和后处理
│   │   ├── post
│   │   │   ├── vis.py  # 训练后绘制html可视化文件
│   ├── main_DPPO.py  # 训练启动入口脚本
```



## How to train

conda环境为yyx_adept(77)，yyx_ishen(75)，yyx_jsac(56/76)，adept(yyx本地)。
依赖项不多，哪个包缺了手动pip即可。

Docker部署（Optional）
```sh
docker build -t linc/mcs:drl_dyna_aoi-v1 . --network host

xhost +

docker run -it --privileged --net=host --ipc=host --device=/dev/dri:/dev/dri -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY --gpus all --name test_mcs linc/mcs:drl_dyna_aoi-v1 /bin/bash
```

训练DRL-PCN：

```sh
cd source_code
python main_DPPO.py --algo G2ANet --use_snrmap
```

命令行参数：

- `--debug`：开启debug模式，快速验证代码全流程无bug，将实验结果存入`runs/debug`路径
- `--group foo`： 将实验结果存入`runs/foo`路径
- `--algo foo`：选择使用方法foo，默认方法为IPPO
- `--dataset foo`：选择使用数据集 foo 可选NCSU或KAIST
- `--n_thread n`：设置多线程环境数为n，加速训练

环境：
- `--poi_num n`：poi个数，不使用该参数时为默认数量，注意NCSU只能填50，KAIST只能填122

调整五点图自变量：
- `--uav_num n`：uav个数
- `--aoith n`：aoi阈值，单位为timeslot
- `--txth n`：tx阈值，单位为Mbps
- `--update_num n`：天线个数，一个uav在一个timeslot里最多服务n个user

更多命令行参数的使用方式参见代码。

## Training outputs 

实验结果文件夹包括以下内容：

```sh
.
├── events.out.tfevents.1675849821.omnisky.107733.0  # tensorboard可视化
├── Models  # 保存最优actor模型
├── params.json  # 记录本次实验的参数防止遗忘
└── train_saved_trajs  # 训练episode的最优uav轨迹
└── train_output.txt  # 记录最优模型对应的metric
└── vis.html  # 根据最优uav轨迹绘制的html可视化文件
```

除tensorboard外，还实现了基于wandb的可视化，本地结果存放在`wandb`路径下。

手动绘制html可视化文件：

```sh
cd source_code
python tools/post/vis.py --output_dir <OUTPUT_DIR>
```

在实验结果文件夹下生成`vis.html`：

<img src="https://cdn.jsdelivr.net/gh/1candoallthings/figure-bed@main/img/202302112014826.png" alt="image-20230211201439409" style="zoom: 25%;" />

批量绘制一个group下所有实验的可视化文件：
```sh
cd source_code
python tools/post/bat_vis.py --group_dir <GROUP_DIR>
```
其中GROUP_DIR是OUTPUT_DIR的父目录。

## How to inference

加载模型进行测试：
```sh
cd source_code
python main_DPPO.py --test --init_checkpoint <OUTPUT_DIR>  # <OUTPUT_DIR> contains folder 'Models'
```
测试结果默认保存在`<OUTPUT_DIR>/test`路径下

（训练和测试的评测是同一套代码，所以直接用train_output.txt填实验即可）

