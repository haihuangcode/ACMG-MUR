python ucf_vggsound.py \
--gpu 0 \
--lr 0.0004 \
--clip_gradient 0.5 \
--snapshot_pref "./Exps/ucf_vggsound/" \
--n_epoch 30 \
--b 80 \
--test_batch_size 64 \
--dataset_name "vgga_ucfv" \
--print_freq 1 \
--eval_freq 1 