NODES=1
NUMA=0,1

if [[ $NODES == 1 ]]; then
    MPCOMM_TARGETS=target1:29.160.42.103:12345
else
    MPCOMM_TARGETS=target1:29.160.42.103:12345,target2:29.160.42.140:12345
fi

export MPCOMM_NIC_FILTER="mlx5_bond_1,mlx5_bond_2,mlx5_bond_3,mlx5_bond_4,mlx5_bond_5,mlx5_bond_6,mlx5_bond_7,mlx5_bond_8"

export MPCOMM_MAX_RDMA_TRANSFER_SIZE=65536
export MPCOMM_QPS_PER_CONNECTION=4
export MPCOMM_POLL_INTERVAL=16
export MPCOMM_MAX_SEND_WR=128
export MPCOMM_MAX_OUTSTANDING_PER_QP=16
#export MPCOMM_POLL_BATCH_SIZE=80
#export MPCOMM_MAX_IDLE_SPINS=1000

export PYTHONPATH=../mpcomm-install/lib/python:$PYTHONPATH

numactl --cpubind=1 python ./test_mpcomm.py --target=$MPCOMM_TARGETS --min-chunk-size 1000000000 --max-chunk-size 1000000001 --test-mode performance --iterations 20000 --num-numas $NUMA --mode scatter
