export MPCOMM_NIC_FILTER="mlx5_bond_1,mlx5_bond_2,mlx5_bond_3,mlx5_bond_4,mlx5_bond_5,mlx5_bond_6,mlx5_bond_7,mlx5_bond_8"

export MPCOMM_MAX_RDMA_TRANSFER_SIZE=65536
export MPCOMM_QPS_PER_CONNECTION=4
export MPCOMM_POLL_INTERVAL=16
export MPCOMM_MAX_SEND_WR=128
export MPCOMM_MAX_OUTSTANDING_PER_QP=16

./build/scatter_test \
    --target t1:29.160.42.103:12345 \
    --size 1000000000 \
    --iterations 10