# avvp_av or avvp_va
python avvp.py \
--gpu 0 \
--lr 0.0004 \
--clip_gradient 0.5 \
--snapshot_pref "./Exps/avvp/" \
--n_epoch 50 \
--b 80 \
--test_batch_size 64 \
--dataset_name "avvp_av" \
--print_freq 1 \
--eval_freq 1