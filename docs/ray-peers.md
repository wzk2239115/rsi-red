# 单容器、共享8卡的四会话部署

该模式在现有平台Docker里生成配置，不需要Docker-in-Docker、namespace或额外内核权限。四个harness会话平级，执行侧共享一个Ray head和rsi服务。目录和凭证只作工作分离；同一Unix用户仍能互读，不是安全沙箱。

## 1. 在GPU容器初始化（新目录）

使用已安装Ray extra的Python环境；现有H100部署可以先git pull，再在原venv中pip install -e '.[ray]'。无需为初始化停止现有Ray head。

```sh
source .venv/bin/activate
rsi init --profile ray-peers --output .rsi/eight-gpu-peers \
  --ray-address http://127.0.0.1:8265 \
  --python-executable "$VIRTUAL_ENV/bin/python" \
  --ray-auth-mode auto --json
```

auto沿用Ray SDK环境策略，不代表关掉认证。若现有head使用token，明确传入`--ray-auth-mode token --ray-token-file /secure/ray-auth-token`；只有操作者已选择无认证的隔离测试head才使用disabled。初始化不读取Ray token内容、不更改head模式。具体策略见ray.md。

GPU job若带image声明，需初始化时传`--cluster-image`，其值沿用现场已确认的环境指纹声明；当前仍只是标签比对，不验证真实容器。不要编造digest。

默认Python是执行初始化的sys.executable，所以应在GPU容器里执行；若在控制机准备配置，--python-executable必须是执行节点上的实际路径。路径有效性在节点运行时验收。

已有输出目录一律拒绝覆盖；不会修改`.rsi/h100-service`。不要把CPU配置的state复制成GPU环境已完成研究的证据。

## 2. 生成结果

```text
.rsi/eight-gpu-peers/
  service.json          # 含全部服务身份，留给操作者
  token                 # operator凭证
  peers.json            # 四个身份/环境路径；expected_gpus=8，未探测设备
  peers/agent-1/        # agent-2、3、4同样结构
    token
    environment.sh
    workspace/
    tmp/
    cache/
    logs/
    outputs/
  shared/models/
  shared/datasets/
```

凭证/配置文件0600，生成目录0700；environment.sh只引用凭证路径，不含token字面值。共享目录按团队约定管理，不声称只读挂载。

## 3. 启动控制服务

确认使用同一容器已有Ray head、所需端口未被其他rsi服务占用。

```sh
python -m rsi_red.server --config .rsi/eight-gpu-peers/service.json \
  --ready-file .rsi/eight-gpu-peers/ready.json
```

默认控制端口8787。如果旧服务仍在运行，不要直接启动第二个同端口服务：选择继续使用旧部署，或在计划切换时停止旧控制进程。若改listen端口，同步修改四个环境文件中的RSI_ENDPOINT。此切换不要求全局ray stop。

操作者另开终端连接服务、完成模型/数据/开发协议登记和campaign配置：

```sh
export RSI_ENDPOINT=http://127.0.0.1:8787
export RSI_TOKEN_FILE="$PWD/.rsi/eight-gpu-peers/token"
rsi doctor --json
rsi resource show --json
rsi kanban
```

campaign成员设置为agent-1、agent-2、agent-3、agent-4；operator不需要加入成员也能管理。模型和数据使用实际登记ID。evaluator默认unconfigured，避免把模拟分数当真实评测；真实evaluator和训练starter仍需要接入。

## 4. 四个平级会话分别配置

在每个会话的GPU容器执行终端，加载本人的环境；以agent-1为例：

```sh
source /ABSOLUTE/PATH/.rsi/eight-gpu-peers/peers/agent-1/environment.sh
cd "$RSI_WORKSPACE"
rsi campaign list --json
```

其余三个会话分别使用agent-2、3、4的文件，不共享operator token。如果harness在外部，使用已有远程终端/SSH访问GPU容器后执行以上命令；本功能不会自动创建或连接四个harness会话，也不会建立SSH隧道。

在各会话调用`$rsi-research`，提供同一campaign ID、已登记模型/数据/开发协议、目标和预算。研究者以recipe上报尝试、关联job，并通过eval/artifact/note保留结果。不必固定每个会话两张卡；Ray按实际资源请求排队。

环境变量RSI_WORKSPACE/TMPDIR/HF_HOME/RSI_LOG_DIR/RSI_OUTPUT_DIR/RSI_SHARED_MODELS/RSI_SHARED_DATASETS只是目录约定。训练程序需要明确使用输出/日志参数；这些变量不会自动约束任意程序写入路径、授予GPU或建立子进程隔离。

## 5. 验收边界

初始化只生成配置，不启动head、研究会话或训练。8是期望GPU数，不是发现结果；resource.show仅采集控制服务所在节点。CPU Ray集成测试验证四个独立身份、recipe、任务和看板归属，不证明8卡训练通过。

现场建议先单卡CUDA冒烟，再申请8卡检查调度和分布式通信，最后用选定模型/训练数据/冻结评测跑短程真实闭环。当前仍缺真实模型evaluator/训练入口和用户数据，不能由profile创建成功推断它们已具备。
